# ruff: noqa: E501
"""Tests for the embedding-based downtime classifier.

A deterministic ``FakeEncoder`` substitutes for sentence-transformers so the
tests run in milliseconds and don't require torch / a model download. The
fake assigns a hand-built vector to each input string; tests choose vectors
so that the cosine similarity ordering matches the semantic intent.
"""

from __future__ import annotations

import hashlib
from datetime import datetime

import numpy as np
import pytest

from orien_import_tool.classification import EmbeddingClassifier
from orien_import_tool.domain.downtime import DowntimeEvent
from orien_import_tool.domain.fmea import (
    Component,
    Equipment,
    FailureMode,
    Function,
    FunctionalFailure,
)

# --- Fake encoder ---------------------------------------------------------------------


class FakeEncoder:
    """Returns a hand-picked vector for each input string.

    Inputs we don't have a mapping for fall back to a small random-looking
    vector keyed by ``hash(text)`` so the cosine never accidentally lines up
    with a real fixture vector.
    """

    def __init__(self, vectors: dict[str, list[float]]) -> None:
        self._vectors = {k: np.asarray(v, dtype=np.float32) for k, v in vectors.items()}
        self._dim = len(next(iter(self._vectors.values())))

    def encode(self, texts: list[str]) -> np.ndarray:
        rows = []
        for text in texts:
            if text in self._vectors:
                rows.append(self._vectors[text])
                continue
            # Deterministic fallback so we don't have flaky tests when text
            # doesn't appear in the prebuilt map. ``hashlib`` (not Python's
            # built-in hash) is stable across processes.
            digest = hashlib.md5(text.encode("utf-8")).digest()
            seed = int.from_bytes(digest[:4], "big")
            rng = np.random.default_rng(seed)
            rows.append(rng.standard_normal(self._dim).astype(np.float32))
        return np.stack(rows, axis=0)


# --- Fixture --------------------------------------------------------------------------


@pytest.fixture
def equipment() -> Equipment:
    belt_fm = FailureMode(
        token="fm-belt",
        what="Belt",
        mechanism_and_cause="Wears due to Mechanical overload",
    )
    motor_fm = FailureMode(
        token="fm-motor",
        what="Motor bearing",
        mechanism_and_cause="Overheats due to Lack of lubrication",
    )

    belt_function = Function(
        description="To convey ore",
        failures=[FunctionalFailure(description="Belt fails", failure_modes=[belt_fm])],
    )
    motor_function = Function(
        description="To drive the conveyor",
        failures=[FunctionalFailure(description="Motor fails", failure_modes=[motor_fm])],
    )

    belt = Component(
        token="c-belt",
        description="Conveyor Belt Assembly",
        functions=[belt_function],
    )
    motor = Component(
        token="c-motor",
        description="Drive Motor",
        functions=[motor_function],
    )
    return Equipment(token="eq-1", description="Test conveyor", components=[belt, motor])


def _event(text: str, eid: str = "e-1", asset: str = "conveyor") -> DowntimeEvent:
    return DowntimeEvent(
        external_id=eid,
        asset_ref=asset,
        text=text,
        start_ts=datetime(2026, 1, 1),
    )


def _make_encoder() -> FakeEncoder:
    """Build a fake encoder where vectors are aligned semantically.

    Vectors are 4-dim with axes loosely standing for:
      [0] = belt-ish, [1] = motor-ish, [2] = wear-ish, [3] = heat-ish

    The classifier normalises before cosine, so absolute magnitudes don't
    matter — only directions.
    """
    return FakeEncoder(
        {
            # Failure-mode composed texts (mirror _compose_failure_mode_text)
            "Conveyor Belt Assembly | To convey ore | Belt fails | Belt | Wears due to Mechanical overload": [
                1.0,
                0.0,
                1.0,
                0.0,
            ],
            "Drive Motor | To drive the conveyor | Motor fails | Motor bearing | Overheats due to Lack of lubrication": [
                0.0,
                1.0,
                0.0,
                1.0,
            ],
            # Component composed texts
            "Conveyor Belt Assembly": [1.0, 0.0, 0.0, 0.0],
            "Drive Motor": [0.0, 1.0, 0.0, 0.0],
            # Event texts (passed through ``normalise`` before encoding)
            "belt assembly wore out under load conveyor": [1.0, 0.0, 1.0, 0.0],
            "motor running hot overheating issue conveyor": [0.0, 1.0, 0.0, 1.0],
            "unrelated noise about cooking recipes nowhere near machinery": [
                0.0,
                0.0,
                0.0,
                0.0,
            ],
        }
    )


# --- Tests ----------------------------------------------------------------------------


def test_belt_event_classifies_to_belt(equipment: Equipment) -> None:
    classifier = EmbeddingClassifier(equipment, encoder=_make_encoder())
    result = classifier.classify(_event("Belt assembly wore out under load"))

    assert result.component_match is not None
    assert result.component_match.component_token == "c-belt"
    assert result.failure_mode_candidates
    assert result.failure_mode_candidates[0].failure_mode_token == "fm-belt"
    assert result.proposer == "embedding"


def test_motor_event_classifies_to_motor(equipment: Equipment) -> None:
    classifier = EmbeddingClassifier(equipment, encoder=_make_encoder())
    result = classifier.classify(_event("Motor running hot, overheating issue"))

    assert result.component_match is not None
    assert result.component_match.component_token == "c-motor"
    assert result.failure_mode_candidates[0].failure_mode_token == "fm-motor"


def test_orthogonal_event_still_returns_top_k(equipment: Equipment) -> None:
    """Even a semantically distant event yields candidates (just with low scores).

    The classifier is built for *retrieval* — there's always a nearest
    neighbour, but the SME-review gate (needs_review) catches low confidence.
    """
    classifier = EmbeddingClassifier(equipment, encoder=_make_encoder())
    result = classifier.classify(
        _event("unrelated noise about cooking recipes nowhere near machinery")
    )

    assert result.failure_mode_candidates  # always returns up to top_k
    assert result.needs_review  # low cosine -> low score -> review


def test_top_k_respected(equipment: Equipment) -> None:
    classifier = EmbeddingClassifier(equipment, encoder=_make_encoder(), top_k=1)
    result = classifier.classify(_event("Belt assembly wore out under load"))
    assert len(result.failure_mode_candidates) == 1


def test_component_scope_restricts_when_strong(equipment: Equipment) -> None:
    """A strong component match scopes the FM search to that component."""
    classifier = EmbeddingClassifier(
        equipment,
        encoder=_make_encoder(),
        component_match_threshold=0.55,
    )
    result = classifier.classify(_event("Belt assembly wore out under load"))
    assert result.component_match.component_token == "c-belt"
    # Only the belt's failure mode should appear, not the motor's.
    assert all(c.component_token == "c-belt" for c in result.failure_mode_candidates)


def test_classifier_output_shape_matches_alias_classifier(equipment: Equipment) -> None:
    """Same return type as AliasClassifier — both produce DowntimeClassification."""
    from orien_import_tool.classification import AliasClassifier, build_seed_index
    from orien_import_tool.domain.downtime import DowntimeClassification

    alias_clf = AliasClassifier(build_seed_index(equipment))
    embed_clf = EmbeddingClassifier(equipment, encoder=_make_encoder())

    event = _event("Belt assembly wore out under load")
    assert isinstance(alias_clf.classify(event), DowntimeClassification)
    assert isinstance(embed_clf.classify(event), DowntimeClassification)


def test_empty_text_yields_no_candidates(equipment: Equipment) -> None:
    classifier = EmbeddingClassifier(equipment, encoder=_make_encoder())
    result = classifier.classify(_event("", asset=""))
    assert result.failure_mode_candidates == []
    assert result.component_match is None


def test_scores_are_in_unit_range(equipment: Equipment) -> None:
    """Cosine in [-1, 1] is mapped to [0, 1] for the score field."""
    classifier = EmbeddingClassifier(equipment, encoder=_make_encoder())
    result = classifier.classify(_event("Belt assembly wore out under load"))
    for candidate in result.failure_mode_candidates:
        assert 0.0 <= candidate.score <= 1.0
    if result.component_match:
        assert 0.0 <= result.component_match.score <= 1.0
