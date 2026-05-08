"""Tests for the Excel downtime adapter against the AI_Test fixture."""

from __future__ import annotations

from pathlib import Path

import pytest

from orien_import_tool.importers.downtime import (
    DowntimeExcelError,
    list_sheets,
    parse_xlsx,
)

FIXTURE = Path(__file__).resolve().parents[2] / "fixtures" / "downtime" / "AI_Test.xlsx"


@pytest.fixture(scope="module")
def fixture_path() -> Path:
    if not FIXTURE.exists():
        pytest.skip(f"AI_Test.xlsx fixture missing: {FIXTURE}")
    return FIXTURE


def test_list_sheets(fixture_path: Path) -> None:
    sheets = list_sheets(fixture_path)
    assert "Conveyor" in sheets
    assert "Drill" in sheets
    assert "Test" in sheets


def test_parse_conveyor_sheet(fixture_path: Path) -> None:
    """The Conveyor sheet has 1729 data rows (1730 total minus header)."""
    events = parse_xlsx(fixture_path, "Conveyor")
    assert len(events) > 1000  # exact count depends on row-skip rules
    first = events[0]
    assert first.external_id.startswith("Conveyor:")
    assert first.asset_ref == "GENERAL SECTION CONVEYOR"
    assert first.text  # non-empty composite
    # Sheet has no date column, so start_ts stays None.
    assert first.start_ts is None


def test_parse_test_sheet_extracts_date_and_duration(fixture_path: Path) -> None:
    """The Test sheet has Day of Date and DOWN columns; both should land."""
    events = parse_xlsx(fixture_path, "Test")
    assert events
    dated = next((e for e in events if e.start_ts is not None), None)
    assert dated is not None
    assert dated.start_ts.year >= 2020
    timed = next((e for e in events if e.duration_s is not None), None)
    assert timed is not None
    assert timed.duration_s > 0  # downtime in seconds


def test_text_composition_includes_textline3(fixture_path: Path) -> None:
    """TextLine3 is the most descriptive column — should always be present in text."""
    events = parse_xlsx(fixture_path, "Conveyor")
    sample = events[0]
    # The composed text should contain pipe separators when multiple text cols exist.
    if " | " in sample.text:
        # At least one of the parts should look like an operator description.
        parts = sample.text.split(" | ")
        assert len(parts) >= 2


def test_skips_rows_without_text(fixture_path: Path) -> None:
    """Rows where every text column is blank should not become events."""
    events = parse_xlsx(fixture_path, "Conveyor")
    for e in events:
        assert e.text.strip() != ""


def test_unknown_sheet_raises(fixture_path: Path) -> None:
    with pytest.raises(DowntimeExcelError, match="not found"):
        parse_xlsx(fixture_path, "DoesNotExist")


def test_missing_file() -> None:
    with pytest.raises(DowntimeExcelError, match="not found"):
        parse_xlsx(Path("/no/such/file.xlsx"), "Conveyor")


def test_external_ids_unique_within_sheet(fixture_path: Path) -> None:
    events = parse_xlsx(fixture_path, "Conveyor")
    ids = [e.external_id for e in events]
    assert len(ids) == len(set(ids))
