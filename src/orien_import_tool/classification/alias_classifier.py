"""Alias-based downtime classifier.

For each :class:`DowntimeEvent`:

1. Tokenise the event text.
2. Score every :class:`Component` by IDF-weighted token overlap with the
   event tokens.
3. Score :class:`FailureMode` candidates the same way; if the top component
   match is strong enough, restrict the search to failure modes under that
   component (sharper signal).
4. Return the best component match plus the top-K failure-mode candidates.

Scores are normalised to ``[0, 1]`` per source-text length so that a
2-token component description matching 1 token gets a different score than
a 10-token failure-mode text matching the same token.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from orien_import_tool.classification.preprocessor import tokenise
from orien_import_tool.classification.seeds import SeedIndex
from orien_import_tool.domain.downtime import (
    ComponentMatch,
    DowntimeClassification,
    DowntimeEvent,
    FailureModeCandidate,
)

if TYPE_CHECKING:
    from orien_import_tool.aliases.store import AliasStore
    from orien_import_tool.textnorm.normalizer import TextNormalizer


@dataclass(frozen=True, slots=True)
class _ScoredCandidate:
    token: str
    score: float
    matched_terms: tuple[str, ...]


class AliasClassifier:
    """Stateless classifier driven by a :class:`SeedIndex`.

    ``component_match_threshold`` is the minimum component score below which
    we ignore the component scope and search all failure modes. The default
    (0.4) was chosen empirically on the conveyor fixture; raise it to be
    stricter, lower it to be more aggressive about scoping.

    ``alias_store`` is optional. When supplied, event tokens are expanded via
    the alias store before scoring — operator vocabulary like ``tripped``
    expands to canonical FMEA tokens like ``stoppage``, lifting matches the
    raw token sets would miss.

    ``normalizer`` is optional. When supplied, event text is cleaned (typos
    fixed, abbreviations expanded) before tokenising — so ``beraing`` and
    ``c/v`` match as ``bearing`` and ``conveyor``. Pipeline order is
    normalize -> alias-expand -> score.
    """

    def __init__(
        self,
        index: SeedIndex,
        *,
        top_k: int = 3,
        component_match_threshold: float = 0.4,
        alias_store: AliasStore | None = None,
        normalizer: TextNormalizer | None = None,
    ) -> None:
        self._index = index
        self._top_k = top_k
        self._component_match_threshold = component_match_threshold
        self._alias_store = alias_store
        self._normalizer = normalizer

    def classify(self, event: DowntimeEvent) -> DowntimeClassification:
        text = event.text
        if self._normalizer is not None:
            text = self._normalizer.normalize(text).cleaned_text
        raw_tokens: set[str] = set(tokenise(text))
        if event.asset_ref:
            raw_tokens.update(tokenise(event.asset_ref))
        event_tokens = frozenset(self._expand_with_aliases(raw_tokens))
        if not event_tokens:
            return DowntimeClassification(
                event_external_id=event.external_id,
                component_match=None,
                notes="event text contains no content tokens",
            )

        component = self._best_component(event_tokens)
        candidate_pool = self._candidate_failure_modes(component)
        candidates = self._score_failure_modes(event_tokens, candidate_pool)

        component_match: ComponentMatch | None = None
        if component:
            component_match = ComponentMatch(
                component_token=component.token,
                component_description=self._index.component_descriptions[component.token],
                score=component.score,
                matched_terms=component.matched_terms,
            )

        failure_mode_candidates = [
            FailureModeCandidate(
                failure_mode_token=c.token,
                component_token=self._owner_component(c.token, component) or "",
                score=c.score,
                matched_terms=c.matched_terms,
                rationale=f"{len(c.matched_terms)} term(s) matched",
            )
            for c in candidates[: self._top_k]
        ]

        return DowntimeClassification(
            event_external_id=event.external_id,
            component_match=component_match,
            failure_mode_candidates=failure_mode_candidates,
        )

    # --- Internals ----------------------------------------------------------------

    def _best_component(self, event_tokens: frozenset[str]) -> _ScoredCandidate | None:
        best: _ScoredCandidate | None = None
        for token, doc in self._index.component_docs.items():
            scored = self._score(event_tokens, doc.token_set)
            if scored is None:
                continue
            candidate = _ScoredCandidate(token=token, score=scored[0], matched_terms=scored[1])
            if best is None or candidate.score > best.score:
                best = candidate
        return best

    def _candidate_failure_modes(
        self,
        component: _ScoredCandidate | None,
    ) -> list[str]:
        if component is None or component.score < self._component_match_threshold:
            return self._index.all_failure_modes()
        scoped = self._index.failure_modes_under(component.token)
        # Component-scoped search; if the component has no failure modes (rare),
        # fall back to the global pool so we still produce candidates.
        return list(scoped) if scoped else self._index.all_failure_modes()

    def _score_failure_modes(
        self,
        event_tokens: frozenset[str],
        candidate_pool: list[str],
    ) -> list[_ScoredCandidate]:
        scored: list[_ScoredCandidate] = []
        for fm_token in candidate_pool:
            doc = self._index.failure_mode_docs[fm_token]
            result = self._score(event_tokens, doc.token_set)
            if result is None:
                continue
            scored.append(
                _ScoredCandidate(token=fm_token, score=result[0], matched_terms=result[1])
            )
        scored.sort(key=lambda c: c.score, reverse=True)
        return scored

    def _score(
        self,
        event_tokens: frozenset[str],
        seed_tokens: frozenset[str],
    ) -> tuple[float, tuple[str, ...]] | None:
        """Return ``(score, matched_terms)`` or ``None`` if no overlap.

        Score = sum of IDF weights of overlapping tokens, normalised by the
        total IDF weight of the seed (so longer seeds aren't penalised by
        partial matches but are credited for matching their key tokens).
        """
        overlap = event_tokens & seed_tokens
        if not overlap:
            return None
        idf = self._index.idf
        match_weight = sum(idf(t) for t in overlap)
        seed_weight = sum(idf(t) for t in seed_tokens)
        if seed_weight == 0:
            return None
        score = match_weight / seed_weight
        return score, tuple(sorted(overlap))

    def _owner_component(
        self,
        fm_token: str,
        component: _ScoredCandidate | None,
    ) -> str | None:
        if component and fm_token in self._index.failure_modes_under(component.token):
            return component.token
        for comp_token, fms in self._index.failure_modes_by_component.items():
            if fm_token in fms:
                return comp_token
        return None

    def _expand_with_aliases(self, tokens: set[str]) -> set[str]:
        if self._alias_store is None:
            return tokens
        expanded = set(tokens)
        expanded.update(self._alias_store.expand_tokens(tokens))
        return expanded
