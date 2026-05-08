"""Tests for the downtime CSV adapter."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from orien_import_tool.importers.downtime import DowntimeIngestError, parse_csv

FIXTURE_DIR = Path(__file__).resolve().parents[2] / "fixtures" / "downtime"


def test_parse_synthetic_fixture() -> None:
    events = parse_csv(FIXTURE_DIR / "synthetic_downtime.csv")
    assert len(events) == 7
    first = events[0]
    assert first.external_id == "e-001"
    assert first.asset_ref == "4FC025"
    assert first.start_ts == datetime(2026, 4, 1, 8, 30, 0)
    assert first.end_ts == datetime(2026, 4, 1, 9, 15, 0)
    assert first.duration_s == 2700.0
    assert "Belt motor" in first.text
    assert first.source_system == "cmms-export"


def test_column_synonyms_are_recognised(tmp_path: Path) -> None:
    """The adapter accepts a few common header spellings for each canonical column."""
    csv = tmp_path / "alt.csv"
    csv.write_text(
        "ticket,equipment,started_at,ended_at,duration,notes,source\n"
        "T-1,RIG-04,2026-05-01T07:00:00,,1500,Pump leak detected,cmms\n",
        encoding="utf-8",
    )
    events = parse_csv(csv)
    assert len(events) == 1
    assert events[0].external_id == "T-1"
    assert events[0].asset_ref == "RIG-04"
    assert events[0].duration_s == 1500.0
    assert events[0].end_ts is None


def test_missing_required_column_raises(tmp_path: Path) -> None:
    csv = tmp_path / "bad.csv"
    csv.write_text("event_id,description\nE-1,no asset\n", encoding="utf-8")
    with pytest.raises(DowntimeIngestError, match="missing required column"):
        parse_csv(csv)


def test_unparseable_timestamp_quarantined(tmp_path: Path) -> None:
    csv = tmp_path / "bad.csv"
    csv.write_text(
        "event_id,asset,start_time,description\nE-1,X,not-a-timestamp,t\n",
        encoding="utf-8",
    )
    with pytest.raises(DowntimeIngestError, match="row 2"):
        parse_csv(csv)


def test_missing_file() -> None:
    with pytest.raises(DowntimeIngestError, match="not found"):
        parse_csv(Path("/no/such/file.csv"))


def test_idempotency_via_external_id() -> None:
    """Re-parsing the same file produces events with stable external_ids."""
    a = parse_csv(FIXTURE_DIR / "synthetic_downtime.csv")
    b = parse_csv(FIXTURE_DIR / "synthetic_downtime.csv")
    assert [e.external_id for e in a] == [e.external_id for e in b]
