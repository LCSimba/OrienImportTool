"""Semantic embedding classifier for downtime events.

A second classifier alongside :class:`AliasClassifier` — same input shape, same
output shape, very different mechanism. Instead of IDF-weighted token overlap
(lexical), it computes cosine similarity between sentence-transformer
embeddings (semantic). That closes the operator-vocabulary gap without any
hand-curated alias dictionary: ``TRIPPED WITH HIGH TENSION`` and
``Cracks due to Cyclic loading`` share no tokens but are semantically close,
and the embedding model picks that up.

The classifier accepts an injected ``Encoder`` so tests can substitute a fake
deterministic encoder. In production, leave ``encoder=None`` and the
constructor will lazy-import :mod:`sentence_transformers` (gated by the
``[ml]`` extra). The model and event corpus stay encoded in-memory; for very
large equipment trees, consider persisting the FMEA embeddings via the future
``EmbeddingRepository``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

import numpy as np

from orien_import_tool.classification.preprocessor import normalise
from orien_import_tool.domain.downtime import (
    ComponentMatch,
    DowntimeClassification,
    DowntimeEvent,
    FailureModeCandidate,
)
from orien_import_tool.domain.fmea import Component, Equipment, FailureMode

if TYPE_CHECKING:  # pragma: no cover
    from numpy.typing import NDArray

DEFAULT_MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"
DEFAULT_TOP_K = 3
DEFAULT_COMPONENT_THRESHOLD = 0.55


class Encoder(Protocol):
    """Minimal sentence-encoder protocol — anything ``.encode(list[str])``-shaped."""

    def encode(self, texts: list[str]) -> NDArray[np.floating]: ...


@dataclass(frozen=True, slots=True)
class _FailureModeEntry:
    token: str
    component_token: str
    text: str


@dataclass(frozen=True, slots=True)
class _ComponentEntry:
    token: str
    description: str
    text: str


class EmbeddingClassifier:
    """Cosine-similarity classifier over sentence-transformer embeddings.

    Pre-computes embeddings for every Component and FailureMode at
    construction; at classify time, embeds the event text once and runs a
    matrix-vector cosine against the cached corpus.

    Cosine similarity is clipped to ``[0, 1]`` (negative cosine == unrelated,
    same as orthogonal) for the ``DowntimeClassification.score`` field. Keeps
    the ordering and matches the convention used by :class:`AliasClassifier`,
    so ``needs_review`` thresholds carry across both classifiers.
    """

    def __init__(
        self,
        equipment: Equipment,
        *,
        encoder: Encoder | None = None,
        model_name: str = DEFAULT_MODEL_NAME,
        top_k: int = DEFAULT_TOP_K,
        component_match_threshold: float = DEFAULT_COMPONENT_THRESHOLD,
    ) -> None:
        self._equipment = equipment
        self._top_k = top_k
        self._component_match_threshold = component_match_threshold
        self._encoder = encoder if encoder is not None else _load_sentence_transformer(model_name)

        self._fm_entries = _collect_failure_modes(equipment)
        self._comp_entries = _collect_components(equipment)
        self._fms_by_component = _index_failure_modes_by_component(self._fm_entries)

        self._fm_matrix = self._embed([e.text for e in self._fm_entries])
        self._comp_matrix = self._embed([e.text for e in self._comp_entries])

    def classify(self, event: DowntimeEvent) -> DowntimeClassification:
        event_text = _compose_event_text(event)
        if not event_text:
            return DowntimeClassification(
                event_external_id=event.external_id,
                component_match=None,
                notes="event text contains no content",
                proposer="embedding",
            )

        event_vec = self._embed([event_text])[0]

        component_match = self._best_component(event_vec)
        candidate_pool = self._candidate_failure_modes(component_match)
        failure_candidates = self._top_failure_modes(event_vec, candidate_pool)

        return DowntimeClassification(
            event_external_id=event.external_id,
            component_match=component_match,
            failure_mode_candidates=failure_candidates,
            proposer="embedding",
        )

    # --- Internals -------------------------------------------------------------------

    def _embed(self, texts: list[str]) -> NDArray[np.floating]:
        vectors = np.asarray(self._encoder.encode(texts), dtype=np.float32)
        # L2-normalise so the dot product becomes cosine similarity.
        norms = np.linalg.norm(vectors, axis=1, keepdims=True)
        norms = np.where(norms == 0, 1.0, norms)
        return vectors / norms

    def _best_component(self, event_vec: NDArray[np.floating]) -> ComponentMatch | None:
        if self._comp_matrix.shape[0] == 0:
            return None
        sims = self._comp_matrix @ event_vec  # cosine, since both are unit-norm
        idx = int(np.argmax(sims))
        score = _to_unit(float(sims[idx]))
        entry = self._comp_entries[idx]
        return ComponentMatch(
            component_token=entry.token,
            component_description=entry.description,
            score=score,
            matched_terms=(),
        )

    def _candidate_failure_modes(
        self,
        component_match: ComponentMatch | None,
    ) -> list[int]:
        """Indices into ``_fm_entries`` to consider for this event."""
        if component_match is not None and component_match.score >= self._component_match_threshold:
            scoped = self._fms_by_component.get(component_match.component_token, [])
            if scoped:
                return scoped
        return list(range(len(self._fm_entries)))

    def _top_failure_modes(
        self,
        event_vec: NDArray[np.floating],
        candidate_indices: list[int],
    ) -> list[FailureModeCandidate]:
        if not candidate_indices:
            return []
        sub_matrix = self._fm_matrix[candidate_indices]
        sims = sub_matrix @ event_vec
        order = np.argsort(-sims)[: self._top_k]
        out: list[FailureModeCandidate] = []
        for local_idx in order:
            entry_idx = candidate_indices[int(local_idx)]
            entry = self._fm_entries[entry_idx]
            out.append(
                FailureModeCandidate(
                    failure_mode_token=entry.token,
                    component_token=entry.component_token,
                    score=_to_unit(float(sims[int(local_idx)])),
                    matched_terms=(),
                    rationale="semantic cosine similarity",
                )
            )
        return out


# --- Module helpers -----------------------------------------------------------------


def _collect_failure_modes(equipment: Equipment) -> list[_FailureModeEntry]:
    entries: list[_FailureModeEntry] = []
    for component in equipment.components:
        for function in component.functions:
            for failure in function.failures:
                for fm in failure.failure_modes:
                    entries.append(
                        _FailureModeEntry(
                            token=fm.token,
                            component_token=component.token,
                            text=_compose_failure_mode_text(
                                fm,
                                function.description,
                                failure.description,
                                component.description,
                            ),
                        )
                    )
    return entries


def _collect_components(equipment: Equipment) -> list[_ComponentEntry]:
    return [
        _ComponentEntry(
            token=component.token,
            description=component.description,
            text=_compose_component_text(component),
        )
        for component in equipment.components
    ]


def _index_failure_modes_by_component(
    entries: list[_FailureModeEntry],
) -> dict[str, list[int]]:
    out: dict[str, list[int]] = {}
    for i, entry in enumerate(entries):
        out.setdefault(entry.component_token, []).append(i)
    return out


def _compose_failure_mode_text(
    fm: FailureMode,
    function_description: str,
    failure_description: str,
    component_description: str,
) -> str:
    """Build the text that represents a failure mode for embedding.

    Joins everything that describes *what this failure mode is about* — the
    operator-facing reading. We include the component name as context so a
    pump's bearing failure mode embeds differently from a fan's bearing
    failure mode even when the mechanism text is identical.
    """
    parts = [component_description, function_description, failure_description]
    if fm.what:
        parts.append(fm.what)
    if fm.mechanism_and_cause:
        parts.append(fm.mechanism_and_cause)
    return " | ".join(p for p in parts if p)


def _compose_component_text(component: Component) -> str:
    parts = [component.description]
    if component.parent_description:
        parts.append(component.parent_description)
    if component.make:
        parts.append(component.make)
    if component.model:
        parts.append(component.model)
    return " | ".join(p for p in parts if p)


def _compose_event_text(event: DowntimeEvent) -> str:
    parts = [event.text]
    if event.asset_ref:
        parts.append(event.asset_ref)
    joined = " | ".join(parts)
    return normalise(joined) if joined else ""


def _to_unit(cos: float) -> float:
    """Clip cosine similarity to ``[0, 1]``.

    Anti-aligned (negative cosine) and orthogonal both mean "unrelated" for
    a retrieval classifier, so we clamp to 0. This keeps the score in the
    same convention as :class:`AliasClassifier` (0 = no match) and lets
    ``DowntimeClassification.needs_review`` use its existing ``< 0.5``
    threshold meaningfully.
    """
    return max(0.0, min(1.0, cos))


def _load_sentence_transformer(model_name: str) -> Encoder:
    """Lazy-load sentence-transformers — only when the caller doesn't inject."""
    try:
        from sentence_transformers import SentenceTransformer
    except ImportError as exc:  # pragma: no cover
        raise ImportError(
            "EmbeddingClassifier requires the [ml] extra: pip install 'orien_import_tool[ml]'"
        ) from exc

    model = SentenceTransformer(model_name)

    class _Adapter:
        def encode(self, texts: list[str]) -> NDArray[np.floating]:
            return np.asarray(model.encode(texts, show_progress_bar=False))

    return _Adapter()
