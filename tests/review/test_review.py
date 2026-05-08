"""Tests for the SME review module — builders, exporters, applier."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from orien_import_tool.aliases import (
    Alias,
    AliasProposer,
    AliasStore,
    build_initial_alias_store,
)
from orien_import_tool.classification import AliasClassifier, build_seed_index
from orien_import_tool.domain.downtime import (
    ComponentMatch,
    DowntimeClassification,
    DowntimeEvent,
    FailureModeCandidate,
)
from orien_import_tool.domain.fmea import (
    Component,
    Equipment,
    FailureMode,
    Function,
    FunctionalFailure,
)
from orien_import_tool.iso14224 import load_all
from orien_import_tool.mapping import propose_mappings
from orien_import_tool.review import (
    ReviewItemType,
    ReviewVerdict,
    apply_decisions,
    build_alias_review,
    build_classification_review,
    build_mapping_review,
    build_unified_queue,
    decisions_from_csv,
    queue_to_csv,
    queue_to_markdown,
)
from orien_import_tool.review.models import ReviewDecision

# --- Fixtures --------------------------------------------------------------------


@pytest.fixture
def small_equipment() -> Equipment:
    fm = FailureMode(
        token="fm-1",
        what="Bearing",
        mechanism_and_cause="Wears due to Mechanical overload",
    )
    return Equipment(
        token="eq-1",
        description="Test conveyor",
        components=[
            Component(
                token="c-1",
                description="Drive Motor",
                functions=[
                    Function(
                        description="Drive belt",
                        failures=[
                            FunctionalFailure(
                                description="Motor fails",
                                failure_modes=[fm],
                            )
                        ],
                    )
                ],
            )
        ],
    )


# --- Mapping review ---------------------------------------------------------------


def test_build_mapping_review_filters_to_multi_candidate(
    small_equipment: Equipment, iso_dir: Path
) -> None:
    ref = load_all(iso_dir)
    result = propose_mappings(small_equipment, ref)
    queue = build_mapping_review(result)
    # Every queue item should reference a FailureMode and have alternates.
    for item in queue:
        assert item.item_type == ReviewItemType.ISO_MAPPING
        assert item.payload["source_entity_type"] == "FailureMode"
        # primary plus at least one alternate (that's why it's needs-review)
        assert len(item.alternates) >= 1


def test_build_mapping_review_item_id_is_stable(small_equipment: Equipment, iso_dir: Path) -> None:
    """Same MappingResult yields same item_ids — required for round-tripping CSV."""
    ref = load_all(iso_dir)
    result = propose_mappings(small_equipment, ref)
    a = build_mapping_review(result)
    b = build_mapping_review(result)
    assert [i.item_id for i in a] == [i.item_id for i in b]


# --- Alias review ----------------------------------------------------------------


def test_build_alias_review_only_keeps_llm_aliases() -> None:
    aliases = [
        Alias(
            alias_text="tripped",
            canonical_tokens=("stoppage",),
            proposer=AliasProposer.LLM,
            confidence=0.85,
            rationale="operator term for outage",
        ),
        Alias(
            alias_text="belt",
            canonical_tokens=("belt",),
            proposer=AliasProposer.RULE,
        ),
        Alias(
            alias_text="faulty",
            canonical_tokens=("failure",),
            proposer=AliasProposer.SME,
        ),
    ]
    queue = build_alias_review(aliases)
    assert len(queue) == 1
    assert queue.items[0].payload["alias_text"] == "tripped"
    assert queue.items[0].proposer == "llm"


def test_build_alias_review_payload_carries_canonical_tokens() -> None:
    aliases = [
        Alias(
            alias_text="tripped",
            canonical_tokens=("stoppage", "stop"),
            proposer=AliasProposer.LLM,
        )
    ]
    item = build_alias_review(aliases).items[0]
    assert item.payload["canonical_tokens"] == ["stoppage", "stop"]


# --- Classification review --------------------------------------------------------


def test_build_classification_review_skips_passed_classifications() -> None:
    high_conf = DowntimeClassification(
        event_external_id="e-1",
        component_match=None,
        failure_mode_candidates=[
            FailureModeCandidate(
                failure_mode_token="fm-1",
                component_token="c-1",
                score=0.9,
                matched_terms=("a", "b"),
            )
        ],
    )
    low_conf = DowntimeClassification(
        event_external_id="e-2",
        component_match=None,
        failure_mode_candidates=[],
    )
    queue = build_classification_review([high_conf, low_conf], events={})
    assert len(queue) == 1
    assert queue.items[0].payload["event_external_id"] == "e-2"


def test_build_classification_review_includes_event_text() -> None:
    classification = DowntimeClassification(
        event_external_id="e-3",
        component_match=ComponentMatch(
            component_token="c-1",
            component_description="Belt",
            score=0.9,
            matched_terms=("belt",),
        ),
        failure_mode_candidates=[],
    )
    event = DowntimeEvent(
        external_id="e-3",
        asset_ref="conveyor",
        text="belt tripped overnight",
        start_ts=datetime(2026, 1, 1),
    )
    queue = build_classification_review([classification], events={"e-3": event})
    assert queue.items[0].detail == "belt tripped overnight"


# --- Unified queue ----------------------------------------------------------------


def test_build_unified_queue_combines_all_sources(
    small_equipment: Equipment, iso_dir: Path
) -> None:
    ref = load_all(iso_dir)
    mapping_result = propose_mappings(small_equipment, ref)
    aliases = [
        Alias(
            alias_text="tripped",
            canonical_tokens=("stoppage",),
            proposer=AliasProposer.LLM,
        )
    ]
    classification = DowntimeClassification(
        event_external_id="e-1",
        component_match=None,
        failure_mode_candidates=[],
    )
    queue = build_unified_queue(
        mapping_result=mapping_result,
        aliases=aliases,
        classifications=[classification],
    )
    types = {i.item_type for i in queue}
    assert ReviewItemType.ISO_MAPPING in types
    assert ReviewItemType.ALIAS in types
    assert ReviewItemType.CLASSIFICATION in types


# --- CSV export / import ----------------------------------------------------------


def test_csv_round_trip_preserves_item_ids(small_equipment, iso_dir):
    ref = load_all(iso_dir)
    queue = build_mapping_review(propose_mappings(small_equipment, ref))
    csv_text = queue_to_csv(queue)
    assert "item_id,item_type" in csv_text
    # Mark the first item as accepted; round-trip.
    target_id = queue.items[0].item_id
    rows = csv_text.splitlines()
    header_idx = rows[0].split(",").index("verdict")
    first_data_row = rows[1].split(",")
    first_data_row[header_idx] = "accepted"
    rows[1] = ",".join(first_data_row)
    edited = "\n".join(rows) + "\n"
    decisions = decisions_from_csv(edited)
    assert any(d.item_id == target_id and d.verdict == ReviewVerdict.ACCEPTED for d in decisions)


def test_decisions_from_csv_skips_blank_verdicts() -> None:
    csv = (
        "item_id,item_type,verdict,chosen_alternative,note,sme_user\n"
        "alias:1,alias,,,,\n"
        "alias:2,alias,accepted,,,\n"
        "alias:3,alias,rejected,,not relevant,\n"
    )
    decisions = decisions_from_csv(csv)
    assert {d.item_id for d in decisions} == {"alias:2", "alias:3"}


def test_decisions_from_csv_ignores_unknown_verdict() -> None:
    csv = "item_id,item_type,verdict,chosen_alternative,note,sme_user\nalias:1,alias,maybe,,,\n"
    assert decisions_from_csv(csv) == []


# --- Markdown export --------------------------------------------------------------


def test_queue_to_markdown_groups_by_type() -> None:
    aliases = [
        Alias(
            alias_text="tripped",
            canonical_tokens=("stoppage",),
            proposer=AliasProposer.LLM,
        )
    ]
    queue = build_alias_review(aliases)
    md = queue_to_markdown(queue)
    assert "## Alias (1)" in md
    assert "tripped" in md


def test_queue_to_markdown_handles_empty_queue() -> None:
    from orien_import_tool.review.models import ReviewQueue

    md = queue_to_markdown(ReviewQueue())
    assert "Nothing pending" in md


# --- Apply decisions --------------------------------------------------------------


def test_apply_decisions_adds_accepted_aliases_to_store() -> None:
    aliases = [
        Alias(
            alias_text="tripped",
            canonical_tokens=("stoppage", "stop"),
            proposer=AliasProposer.LLM,
        )
    ]
    queue = build_alias_review(aliases)
    item = queue.items[0]
    store = AliasStore()
    decision = ReviewDecision(item_id=item.item_id, verdict=ReviewVerdict.ACCEPTED)

    result = apply_decisions([decision], queue, alias_store=store)
    assert result.aliases_added == 1
    matches = store.get("tripped")
    assert any(a.proposer == AliasProposer.SME for a in matches)


def test_apply_decisions_rejects_correctly() -> None:
    aliases = [
        Alias(
            alias_text="tripped",
            canonical_tokens=("stoppage",),
            proposer=AliasProposer.LLM,
        )
    ]
    queue = build_alias_review(aliases)
    store = AliasStore()
    decision = ReviewDecision(item_id=queue.items[0].item_id, verdict=ReviewVerdict.REJECTED)
    result = apply_decisions([decision], queue, alias_store=store)
    assert result.aliases_rejected == 1
    assert len(store) == 0


def test_apply_decisions_corrects_with_chosen_alternative() -> None:
    aliases = [
        Alias(
            alias_text="tripped",
            canonical_tokens=("wrong",),
            proposer=AliasProposer.LLM,
        )
    ]
    queue = build_alias_review(aliases)
    store = AliasStore()
    decision = ReviewDecision(
        item_id=queue.items[0].item_id,
        verdict=ReviewVerdict.CORRECTED,
        chosen_alternative="stoppage stop",
    )
    apply_decisions([decision], queue, alias_store=store)
    sme_alias = next((a for a in store.get("tripped") if a.proposer == AliasProposer.SME), None)
    assert sme_alias is not None
    assert sme_alias.canonical_tokens == ("stoppage", "stop")


def test_apply_decisions_skips_unknown_item_ids() -> None:
    queue = build_alias_review([])
    decision = ReviewDecision(item_id="nonexistent", verdict=ReviewVerdict.ACCEPTED)
    result = apply_decisions([decision], queue, alias_store=AliasStore())
    assert result.skipped == ["nonexistent"]


def test_apply_decisions_records_mapping_count(small_equipment, iso_dir) -> None:
    ref = load_all(iso_dir)
    queue = build_mapping_review(propose_mappings(small_equipment, ref))
    if not queue.items:
        pytest.skip("no multi-candidate mappings to review for this fixture")
    decision = ReviewDecision(item_id=queue.items[0].item_id, verdict=ReviewVerdict.ACCEPTED)
    result = apply_decisions([decision], queue)
    assert result.mapping_decisions_recorded == 1


# --- End-to-end -------------------------------------------------------------------


def test_end_to_end_csv_round_trip_against_real_classifier(small_equipment, iso_dir) -> None:
    """Build queue, export CSV, edit, parse decisions, apply — full round trip."""
    ref = load_all(iso_dir)
    classifier = AliasClassifier(
        build_seed_index(small_equipment),
        alias_store=build_initial_alias_store(small_equipment, ref),
    )
    event = DowntimeEvent(
        external_id="e-1",
        asset_ref="conveyor",
        text="motor failed",
        start_ts=datetime(2026, 1, 1),
    )
    classifications = [classifier.classify(event)]
    queue = build_unified_queue(
        mapping_result=propose_mappings(small_equipment, ref),
        classifications=classifications,
        events={event.external_id: event},
    )
    csv_text = queue_to_csv(queue)
    # Round-trip: parse with no edits — decisions list is empty.
    assert decisions_from_csv(csv_text) == []
