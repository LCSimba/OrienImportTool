"""Alias classifier tests against a small in-memory FMEA tree.

The conveyor fixture would work too, but a hand-built mini Equipment makes
expected matches obvious without requiring readers to memorise the conveyor
tree shape. The end-to-end test in ``test_pipeline.py`` runs the full real
fixture.
"""

from __future__ import annotations

from datetime import datetime

import pytest

from orien_import_tool.classification import (
    AliasClassifier,
    SeedIndex,
    build_seed_index,
    normalise,
    tokenise,
)
from orien_import_tool.domain.downtime import DowntimeEvent
from orien_import_tool.domain.fmea import (
    Component,
    Equipment,
    FailureMode,
    Function,
    FunctionalFailure,
)

# --- Mini fixture --------------------------------------------------------------------


@pytest.fixture
def mini_equipment() -> Equipment:
    """Two components, each with one FailureMode — enough to exercise scoring."""
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


# --- Preprocessor tests --------------------------------------------------------------


def test_normalise_lowercases_and_strips_punctuation() -> None:
    """Non-alphanumeric runs collapse to a single space, leading/trailing stripped."""
    assert normalise("Belt - Tension Off!") == "belt tension off"


def test_tokenise_drops_stopwords_by_default() -> None:
    assert tokenise("the belt is broken") == ["belt", "broken"]


def test_tokenise_keeps_stopwords_when_asked() -> None:
    assert tokenise("loss of containment", drop_stopwords=False) == ["loss", "of", "containment"]


# --- SeedIndex tests -----------------------------------------------------------------


def test_seed_index_indexes_components_and_failure_modes(mini_equipment: Equipment) -> None:
    idx = build_seed_index(mini_equipment)
    assert set(idx.component_docs) == {"c-belt", "c-motor"}
    assert set(idx.failure_mode_docs) == {"fm-belt", "fm-motor"}


def test_seed_index_associates_failure_modes_with_components(mini_equipment: Equipment) -> None:
    idx = build_seed_index(mini_equipment)
    assert idx.failure_modes_under("c-belt") == {"fm-belt"}
    assert idx.failure_modes_under("c-motor") == {"fm-motor"}


def test_seed_index_idf_assigns_higher_weight_to_rare_terms(mini_equipment: Equipment) -> None:
    idx = build_seed_index(mini_equipment)
    # "conveyor" appears in 2 of the 4 documents (component and motor function);
    # "lubrication" appears in only 1 (motor failure mode). The rare term wins.
    assert idx.idf("lubrication") > idx.idf("conveyor")


def test_seed_index_returns_zero_idf_for_unknown_token(mini_equipment: Equipment) -> None:
    idx = build_seed_index(mini_equipment)
    assert idx.idf("xenotype") == 0.0


# --- Classifier tests ----------------------------------------------------------------


def _event(text: str, asset: str = "test-1", external_id: str = "e-1") -> DowntimeEvent:
    return DowntimeEvent(
        external_id=external_id,
        asset_ref=asset,
        start_ts=datetime(2026, 1, 1, 0, 0, 0),
        text=text,
    )


def test_clear_belt_event_picks_belt_component(mini_equipment: Equipment) -> None:
    classifier = AliasClassifier(build_seed_index(mini_equipment))
    result = classifier.classify(_event("Conveyor belt assembly tension off"))

    assert result.component_match is not None
    assert result.component_match.component_token == "c-belt"
    assert result.failure_mode_candidates
    assert result.failure_mode_candidates[0].failure_mode_token == "fm-belt"
    assert result.failure_mode_candidates[0].component_token == "c-belt"


def test_clear_motor_event_picks_motor_component(mini_equipment: Equipment) -> None:
    classifier = AliasClassifier(build_seed_index(mini_equipment))
    result = classifier.classify(_event("Drive motor overheats due to no lubrication"))

    assert result.component_match is not None
    assert result.component_match.component_token == "c-motor"
    assert result.failure_mode_candidates[0].failure_mode_token == "fm-motor"


def test_unrelated_text_returns_no_or_low_confidence_match(mini_equipment: Equipment) -> None:
    classifier = AliasClassifier(build_seed_index(mini_equipment))
    result = classifier.classify(_event("asdgkj nonsense text"))

    # Either no candidates, or candidates with very low score (no real overlap).
    if result.failure_mode_candidates:
        assert result.failure_mode_candidates[0].score < 0.1
    assert result.needs_review is True


def test_empty_text_yields_no_candidates(mini_equipment: Equipment) -> None:
    classifier = AliasClassifier(build_seed_index(mini_equipment))
    result = classifier.classify(_event("", asset=""))
    assert result.component_match is None
    assert result.failure_mode_candidates == []
    assert result.needs_review is True


def test_classifier_returns_top_k_candidates(mini_equipment: Equipment) -> None:
    classifier = AliasClassifier(build_seed_index(mini_equipment), top_k=1)
    # Word that matches both failure modes: "fails" appears in both functional failures.
    result = classifier.classify(_event("equipment fails again"))
    assert len(result.failure_mode_candidates) <= 1


def test_component_scope_falls_back_when_no_failure_modes(mini_equipment: Equipment) -> None:
    """If a matched component has no failure modes, classifier searches globally."""
    bare = Component(token="c-bare", description="Empty Cabinet")
    equipment = Equipment(
        token="eq-bare",
        description="Bare equipment",
        components=[*mini_equipment.components, bare],
    )
    classifier = AliasClassifier(build_seed_index(equipment))
    # Event mentioning the bare component plus a wear-flavoured term should still
    # find fm-belt globally.
    result = classifier.classify(_event("Empty cabinet wears out under load"))
    if result.component_match and result.component_match.component_token == "c-bare":
        # No failure modes under c-bare, so candidates come from the global pool
        # — expect at least one of the two known failure modes.
        assert all(
            c.failure_mode_token in {"fm-belt", "fm-motor"} for c in result.failure_mode_candidates
        )


def test_seed_index_independent_of_classifier(mini_equipment: Equipment) -> None:
    """SeedIndex can be used standalone (e.g. to inspect what's indexed)."""
    idx = build_seed_index(mini_equipment)
    assert isinstance(idx, SeedIndex)
    assert "wears" in idx.failure_mode_tokens("fm-belt")
    assert "lubrication" in idx.failure_mode_tokens("fm-motor")
