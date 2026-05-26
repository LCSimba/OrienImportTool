"""Stage 3 — link extracted spans to the FMEA / ISO 14224 (deterministic).

The LLM already did the open extraction (stage 2). Linking is rule-based:

* **components** — score the span's tokens against each FMEA component's seed
  doc (IDF-weighted overlap, reusing :class:`SeedIndex`); the best match above
  ``component_threshold`` wins, otherwise the span is left unmatched (a
  candidate new component). Asset/section IDs are filtered first.
* **failure modes** — resolve each extracted failure term to an ISO 14224 B.15
  description: exact/prefix match against the B.15 vocabulary, then the curated
  :data:`VERB_TO_B15` table as a fallback (catches ``wears`` -> ``Worn`` etc.).

This is where Pipeline B finally "compares to the FMEA list".
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from orien_import_tool.classification.preprocessor import tokenise
from orien_import_tool.domain.downtime import (
    ComponentLink,
    ExtractedEntities,
    FailureModeLink,
    LinkedEntities,
)
from orien_import_tool.linking.asset_ids import looks_like_asset_id
from orien_import_tool.mapping.rules import VERB_TO_B15

if TYPE_CHECKING:
    from orien_import_tool.classification.seeds import SeedIndex
    from orien_import_tool.iso14224 import Iso14224ReferenceSet


class ComponentLinker:
    """Resolve a component span to the best-matching FMEA component."""

    def __init__(self, index: SeedIndex, *, threshold: float = 0.35) -> None:
        self._index = index
        self._threshold = threshold

    def link(self, span: str) -> ComponentLink:
        tokens = frozenset(tokenise(span))
        span_weight = sum(self._index.idf(t) for t in tokens)
        best_token, best_score = "", 0.0
        if span_weight > 0:
            for ctoken, doc in self._index.component_docs.items():
                overlap = tokens & doc.token_set
                if not overlap:
                    continue
                seed_weight = sum(self._index.idf(t) for t in doc.token_set)
                denom = min(span_weight, seed_weight)
                if denom <= 0:
                    continue
                # Containment: how much of the shorter side the overlap covers,
                # so a span matching a component's key token scores high even
                # when the component description has extra words.
                score = sum(self._index.idf(t) for t in overlap) / denom
                if score > best_score:
                    best_token, best_score = ctoken, score
        matched = best_token if best_score >= self._threshold else ""
        return ComponentLink(
            span=span,
            component_token=matched,
            component_description=self._index.component_descriptions.get(matched, ""),
            score=round(best_score, 3),
        )


class FailureModeLinker:
    """Resolve a failure term to an ISO 14224 B.15 failure-mode description."""

    def __init__(self, ref: Iso14224ReferenceSet) -> None:
        # word -> B.15 description (first description that uses the word wins)
        self._by_word: dict[str, str] = {}
        for description in ref.failure_modes:  # keys are the B.15 descriptions
            for word in tokenise(description):
                self._by_word.setdefault(word, description)

    def link(self, term: str) -> FailureModeLink:
        t = term.casefold()
        if t in self._by_word:
            return FailureModeLink(term, self._by_word[t], 1.0)
        # 4-char stem match (fracture~fractured, blockage~blocked, corrosion~corroded)
        for word, description in self._by_word.items():
            if len(t) >= 4 and len(word) >= 4 and t[:4] == word[:4]:
                return FailureModeLink(term, description, 0.8)
        # curated verb table (wears->Worn, breaks->Cracked/fractured/broken, ...)
        for pattern, b15 in VERB_TO_B15:
            if pattern in t or t in pattern:
                return FailureModeLink(term, b15, 0.7)
        return FailureModeLink(term, "", 0.0)


class EntityLinker:
    """Orchestrate stage-3 linking for one event's :class:`ExtractedEntities`."""

    def __init__(
        self,
        index: SeedIndex,
        ref: Iso14224ReferenceSet,
        *,
        component_threshold: float = 0.35,
    ) -> None:
        self._components = ComponentLinker(index, threshold=component_threshold)
        self._failures = FailureModeLinker(ref)

    def link(self, extracted: ExtractedEntities) -> LinkedEntities:
        component_links: list[ComponentLink] = []
        asset_ids: list[str] = []
        for span in extracted.components:
            if looks_like_asset_id(span):
                asset_ids.append(span)
            else:
                component_links.append(self._components.link(span))

        failure_links = [self._failures.link(term) for term in extracted.failure_modes]

        return LinkedEntities(
            event_external_id=extracted.event_external_id,
            components=tuple(component_links),
            failure_modes=tuple(failure_links),
            asset_ids=tuple(asset_ids),
        )

    def link_all(self, extracted: list[ExtractedEntities]) -> list[LinkedEntities]:
        return [self.link(e) for e in extracted]
