"""Verify that an AliasStore lifts classifier scores on operator-vocabulary events."""

from __future__ import annotations

from datetime import datetime

import pytest

from orien_import_tool.aliases import (
    Alias,
    AliasProposer,
    AliasStore,
    build_initial_alias_store,
)
from orien_import_tool.classification import AliasClassifier, build_seed_index
from orien_import_tool.domain.downtime import DowntimeEvent
from orien_import_tool.domain.fmea import (
    Component,
    Equipment,
    FailureMode,
    Function,
    FunctionalFailure,
)


@pytest.fixture
def equipment() -> Equipment:
    """Mini Equipment whose vocabulary uses FMEA verbs (stoppage, breakage)."""
    fm = FailureMode(
        token="fm-1",
        what="Belt drive",
        mechanism_and_cause="Wears due to Mechanical overload causing total stoppage",
    )
    return Equipment(
        token="eq-1",
        description="Conveyor",
        components=[
            Component(
                token="c-1",
                description="Belt drive system",
                functions=[
                    Function(
                        description="To convey ore at planned tonnage",
                        failures=[
                            FunctionalFailure(
                                description="Stoppage of the belt",
                                failure_modes=[fm],
                            )
                        ],
                    )
                ],
            )
        ],
    )


def _event(text: str) -> DowntimeEvent:
    return DowntimeEvent(
        external_id="e-1",
        asset_ref="conveyor",
        text=text,
        start_ts=datetime(2026, 1, 1),
    )


def test_alias_store_lifts_score_on_operator_term(equipment: Equipment) -> None:
    """'Belt drive tripped' contains no FMEA token directly, but with aliases
    'tripped' expands to 'stoppage' / 'stop' which appear in the seed text.
    """
    seed_index = build_seed_index(equipment)
    event = _event("Belt drive tripped overnight")

    bare = AliasClassifier(seed_index)
    aliased = AliasClassifier(seed_index, alias_store=build_initial_alias_store())

    bare_result = bare.classify(event)
    aliased_result = aliased.classify(event)

    bare_top = (
        bare_result.failure_mode_candidates[0].score if bare_result.failure_mode_candidates else 0.0
    )
    aliased_top = aliased_result.failure_mode_candidates[0].score
    assert aliased_top > bare_top, (
        f"alias store should lift score; bare={bare_top}, aliased={aliased_top}"
    )


def test_alias_store_does_not_invent_matches(equipment: Equipment) -> None:
    """Aliases that point to tokens not in the seed index don't add false matches."""
    seed_index = build_seed_index(equipment)
    store = AliasStore()
    store.add(
        Alias(
            alias_text="alien",
            canonical_tokens=("nonexistent_in_fmea",),
            proposer=AliasProposer.LLM,
        )
    )
    classifier = AliasClassifier(seed_index, alias_store=store)
    event = _event("alien word here")
    result = classifier.classify(event)
    assert result.needs_review is True


def test_classifier_unchanged_when_alias_store_omitted(equipment: Equipment) -> None:
    """Backwards compatibility: existing call sites without alias_store work."""
    classifier = AliasClassifier(build_seed_index(equipment))
    result = classifier.classify(_event("Belt drive tripped"))
    assert result.event_external_id == "e-1"
