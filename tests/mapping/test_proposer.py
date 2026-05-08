"""Tests for the rule-based ISO 14224 proposer.

Asserts specific failure-mode and activity-code mappings against the conveyor
fixture vocabulary. Failures here mean either a rule regressed or the
upstream Orien vocabulary changed in a way that breaks an assumption.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from orien_import_tool.domain.fmea import Activity, FailureMode
from orien_import_tool.iso14224 import load_all
from orien_import_tool.mapping import (
    MappingDimension,
    Proposer,
    RuleProposer,
)


@pytest.fixture(scope="module")
def proposer(iso_dir: Path) -> RuleProposer:
    return RuleProposer(load_all(iso_dir))


def _codes(mappings, dimension: MappingDimension) -> list[str]:
    return [m.iso_code for m in mappings if m.dimension == dimension]


# --- FailureMode mappings ------------------------------------------------------------


def test_wears_due_to_mechanical_overload(proposer: RuleProposer) -> None:
    fm = FailureMode(
        token="t-001",
        what="Bearing",
        mechanism_and_cause="Wears due to Mechanical overload",
    )
    mappings = proposer.propose_for_failure_mode(fm)
    assert _codes(mappings, MappingDimension.MODE) == ["Worn"]
    assert _codes(mappings, MappingDimension.MECHANISM) == ["2.4"]  # Wear
    # Multi-candidate B3: 2.1 Operating error primary, 1.1 Design alternate
    cause_codes = _codes(mappings, MappingDimension.CAUSE)
    assert cause_codes == ["2.1", "1.1"]


def test_blocks_due_to_excessive_particle_size(proposer: RuleProposer) -> None:
    fm = FailureMode(
        token="t-002",
        mechanism_and_cause="Blocks due to Excessive particle size",
    )
    mappings = proposer.propose_for_failure_mode(fm)
    assert _codes(mappings, MappingDimension.MODE) == ["Blocked/plugged/restricted"]
    cause_codes = _codes(mappings, MappingDimension.CAUSE)
    # Operating error primary, contamination secondary, design last.
    assert cause_codes == ["2.1", "3.1", "1.1"]


def test_breaks_due_to_thermal_overload_multi_b2(proposer: RuleProposer) -> None:
    fm = FailureMode(
        token="t-003",
        mechanism_and_cause="Breaks/Fracture/Separates due to Thermal overload",
    )
    mappings = proposer.propose_for_failure_mode(fm)
    mech_codes = _codes(mappings, MappingDimension.MECHANISM)
    # Both Breakage (X-side) and Overheating (Y-side) should appear.
    breakage_subcode = "2.5"
    overheating_subcode = "2.7"
    assert breakage_subcode in mech_codes
    assert overheating_subcode in mech_codes


def test_loses_preload_due_to_vibration_b3_now_populated(proposer: RuleProposer) -> None:
    fm = FailureMode(
        token="t-004",
        mechanism_and_cause="Loses Preload due to Vibration",
    )
    mappings = proposer.propose_for_failure_mode(fm)
    cause_codes = _codes(mappings, MappingDimension.CAUSE)
    assert cause_codes == ["1.1", "1.5", "2.3"]


def test_corrodes_due_to_crevice_multi_b3(proposer: RuleProposer) -> None:
    fm = FailureMode(
        token="t-005",
        mechanism_and_cause="Corrodes due to Crevice",
    )
    mappings = proposer.propose_for_failure_mode(fm)
    assert _codes(mappings, MappingDimension.CAUSE) == ["1.1", "1.5"]


def test_pure_environment_temperature_stays_single_b3(proposer: RuleProposer) -> None:
    fm = FailureMode(
        token="t-006",
        mechanism_and_cause="Cracks due to High temperature in corrosive environment",
    )
    mappings = proposer.propose_for_failure_mode(fm)
    assert _codes(mappings, MappingDimension.CAUSE) == ["3.4"]


def test_b3_priority_assigned_in_order(proposer: RuleProposer) -> None:
    """Multi-candidate B3 mappings carry priority 0..N in order."""
    fm = FailureMode(
        token="t-007",
        mechanism_and_cause="Wears due to Low pressure",
    )
    cause_mappings = [
        m for m in proposer.propose_for_failure_mode(fm) if m.dimension == MappingDimension.CAUSE
    ]
    priorities = [m.priority for m in cause_mappings]
    assert priorities == list(range(len(cause_mappings)))
    assert [m.iso_code for m in cause_mappings] == ["1.1", "2.1", "2.3"]


def test_confidence_decreases_with_priority(proposer: RuleProposer) -> None:
    fm = FailureMode(
        token="t-008",
        mechanism_and_cause="Wears due to Low pressure",
    )
    cause_mappings = [
        m for m in proposer.propose_for_failure_mode(fm) if m.dimension == MappingDimension.CAUSE
    ]
    confidences = [m.confidence for m in cause_mappings]
    assert confidences[0] >= confidences[1] >= confidences[2]


def test_unknown_mechanism_text_returns_no_b15(proposer: RuleProposer) -> None:
    fm = FailureMode(token="t-009", mechanism_and_cause="Disintegrates due to gremlins")
    mappings = proposer.propose_for_failure_mode(fm)
    assert _codes(mappings, MappingDimension.MODE) == []


# --- Activity mappings ---------------------------------------------------------------


def test_activity_direct_match(proposer: RuleProposer) -> None:
    activity = Activity(token="a-001", description="Replace bearing", activity_code="Replace")
    mappings = proposer.propose_for_activity(activity)
    assert len(mappings) == 1
    m = mappings[0]
    assert m.dimension == MappingDimension.MAINTENANCE_ACTIVITY
    assert m.iso_code == "1"
    assert m.confidence == 1.0


def test_activity_via_examples(proposer: RuleProposer) -> None:
    activity = Activity(token="a-002", description="Calibrate sensor", activity_code="Calibrate")
    m = proposer.propose_for_activity(activity)[0]
    assert m.iso_code == "4"  # B5:4 Adjust
    assert m.confidence < 1.0


def test_activity_condition_monitoring_routes_to_inspection(proposer: RuleProposer) -> None:
    for code in ["Vibration Analysis", "Thermography", "Oil Analysis", "Ultrasonic Testing"]:
        activity = Activity(token=f"a-cm-{code}", description=code, activity_code=code)
        m = proposer.propose_for_activity(activity)[0]
        assert m.iso_code == "9"  # B5:9 Inspection


def test_activity_statutory_routes_to_extension(proposer: RuleProposer) -> None:
    activity = Activity(
        token="a-stat", description="Statutory inspection", activity_code="Statutory"
    )
    m = proposer.propose_for_activity(activity)[0]
    assert m.iso_code == "1001"  # B5 extension
    assert m.confidence == 1.0


def test_activity_blank_code_yields_no_mapping(proposer: RuleProposer) -> None:
    """activity_type is *not* a fallback — it's a different axis (B5 use column).

    The conveyor fixture has activityCode blank throughout, which means the
    fixture genuinely has 0% B5 coverage. Future Orien exports with populated
    activity_code will map. This test documents the deliberate gap.
    """
    activity = Activity(
        token="a-fb",
        description="Inspect lock out device",
        activity_code="",
        activity_type="Inspection",
    )
    assert proposer.propose_for_activity(activity) == []


def test_activity_unknown_code_yields_no_mapping(proposer: RuleProposer) -> None:
    activity = Activity(token="a-bad", description="x", activity_code="Wibble")
    assert proposer.propose_for_activity(activity) == []


def test_proposer_tag(proposer: RuleProposer) -> None:
    fm = FailureMode(token="t-tag", mechanism_and_cause="Wears due to Mechanical overload")
    for m in proposer.propose_for_failure_mode(fm):
        assert m.proposer == Proposer.RULE
