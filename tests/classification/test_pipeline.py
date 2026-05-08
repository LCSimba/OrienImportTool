"""End-to-end: parse the conveyor fixture, ingest synthetic downtime, classify.

This test wires every layer together — Orien parser → normalizer →
seed-index builder → alias classifier — so a regression anywhere shows up
here.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from orien_import_tool.classification import AliasClassifier, build_seed_index
from orien_import_tool.importers.downtime import parse_csv
from orien_import_tool.importers.orien import normalize, parse_workbook

ORIEN_FIXTURE = "2025918727_CONVEYOR4FBeltTRUNK_ExportOfSingleSheetTactics_3QN56K0-0.xlsx"
DOWNTIME_FIXTURE = (
    Path(__file__).resolve().parents[1] / "fixtures" / "downtime" / "synthetic_downtime.csv"
)


@pytest.fixture(scope="module")
def classifier(orien_fixture_dir: Path):
    path = orien_fixture_dir / ORIEN_FIXTURE
    if not path.exists():
        pytest.skip(f"Conveyor fixture missing: {path}")
    equipment = normalize(parse_workbook(path))
    return AliasClassifier(build_seed_index(equipment))


@pytest.fixture(scope="module")
def events():
    return parse_csv(DOWNTIME_FIXTURE)


def test_pipeline_classifies_every_event(classifier, events) -> None:
    for event in events:
        result = classifier.classify(event)
        assert result.event_external_id == event.external_id


def test_belt_event_lands_on_belt_component(classifier, events) -> None:
    """e-005: 'Belt assembly tension off' should match the Conveyor Belt Assembly."""
    e = next(ev for ev in events if ev.external_id == "e-005")
    result = classifier.classify(e)
    assert result.component_match is not None
    assert "belt" in result.component_match.component_description.lower()


def test_lock_out_event_matches_electrical_related_component(classifier, events) -> None:
    """e-003 should pick an electrical-related component.

    "Lock out facility broken on electrical panel" — the fixture has
    "Electrical System" at the top level plus children like "Panel, Winch".
    With IDF-weighted scoring, a child that matches both ``electrical`` and
    ``panel`` typically beats the broader system match; both are correct
    outcomes for SME review. Accept either.
    """
    e = next(ev for ev in events if ev.external_id == "e-003")
    result = classifier.classify(e)
    assert result.component_match is not None
    desc = result.component_match.component_description.lower()
    matched = set(result.component_match.matched_terms)
    assert "electrical" in desc or "panel" in desc or matched & {"electrical", "panel", "lock"}


def test_nonsense_event_flags_for_review(classifier, events) -> None:
    e = next(ev for ev in events if ev.external_id == "e-006")
    result = classifier.classify(e)
    assert result.needs_review is True


def test_event_with_unknown_asset_still_classifies(classifier, events) -> None:
    """e-007: asset_ref UNKNOWN, but text mentions 'drive system'."""
    e = next(ev for ev in events if ev.external_id == "e-007")
    result = classifier.classify(e)
    # The classifier doesn't require a known asset_ref — text alone should give
    # us at least one candidate from the conveyor's drive-system failure modes.
    assert result.failure_mode_candidates


def test_classifier_idempotent(classifier, events) -> None:
    """Running the classifier twice on the same event yields identical results."""
    for event in events:
        a = classifier.classify(event)
        b = classifier.classify(event)
        assert (a.component_match and a.component_match.component_token) == (
            b.component_match and b.component_match.component_token
        )
        assert [c.failure_mode_token for c in a.failure_mode_candidates] == [
            c.failure_mode_token for c in b.failure_mode_candidates
        ]
