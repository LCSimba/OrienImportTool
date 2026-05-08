"""Contract test: parse the conveyor fixture and assert SCHEMA.md invariants.

Bound to ``tests/fixtures/orien/2025918727_CONVEYOR4FBeltTRUNK_*.xlsx``.
A failure here is a signal that either the export format has drifted, the
parser regressed, or the schema doc is stale — all three need investigating.
"""

from pathlib import Path

import pytest

from orien_import_tool.importers.orien import parse_workbook
from orien_import_tool.importers.orien.parser import OrienParseError
from orien_import_tool.importers.orien.schema import (
    EXPECTED_SHEET_NAMES,
    REQUIRED_COLUMNS,
)

FIXTURE = "2025918727_CONVEYOR4FBeltTRUNK_ExportOfSingleSheetTactics_3QN56K0-0.xlsx"


@pytest.fixture(scope="module")
def conveyor_path(orien_fixture_dir: Path) -> Path:
    path = orien_fixture_dir / FIXTURE
    if not path.exists():
        pytest.skip(f"Conveyor fixture missing: {path}")
    return path


@pytest.fixture(scope="module")
def parsed(conveyor_path: Path):
    return parse_workbook(conveyor_path)


# --- Workbook structure --------------------------------------------------------------


def test_expected_sheet_names_constant() -> None:
    assert EXPECTED_SHEET_NAMES == ("r8DropdownValues", "Single Sheet Tactics")


# --- Header metadata -----------------------------------------------------------------


def test_header_extracts_location(parsed) -> None:
    assert parsed.header.location_token.startswith("MWFu")
    assert parsed.header.location_description == "CONVEYOR [4F-Belt] - TRUNK"
    assert parsed.header.language == "en"


def test_header_export_timestamp(parsed) -> None:
    assert parsed.header.export_timestamp is not None
    assert parsed.header.export_timestamp.year == 2025
    assert parsed.header.export_timestamp.month == 9


def test_header_structure_revision_token(parsed) -> None:
    """The header's ``revision`` key is a snapshot UUID, not an integer.

    The integer revision (``structureRevision`` on each data row) is captured
    by the normalizer onto Equipment.
    """
    assert parsed.header.structure_revision_token
    assert isinstance(parsed.header.structure_revision_token, str)


def test_header_component_library_flag(parsed) -> None:
    assert parsed.header.component_library is False


# --- Column index --------------------------------------------------------------------


def test_column_index_has_132_columns(parsed) -> None:
    assert len(parsed.column_index) == 132


def test_column_index_first_column_is_makeChanges(parsed) -> None:
    assert parsed.column_index["makeChanges"] == 0


def test_required_columns_present(parsed) -> None:
    missing = REQUIRED_COLUMNS - set(parsed.column_index)
    assert not missing, f"missing required columns: {sorted(missing)}"


def test_columns_unique(parsed) -> None:
    indices = list(parsed.column_index.values())
    assert len(indices) == len(set(indices))


# --- Data rows -----------------------------------------------------------------------


def test_data_row_count(parsed) -> None:
    assert len(parsed.rows) == 752


def test_every_row_has_location_token(parsed) -> None:
    for row in parsed.rows:
        assert row["locationToken"] == parsed.header.location_token


def test_failure_mode_population(parsed) -> None:
    rows_with_mode = sum(1 for r in parsed.rows if r["failureModeToken"])
    assert rows_with_mode == 735


def test_activity_population(parsed) -> None:
    rows_with_activity = sum(1 for r in parsed.rows if r["activityToken"])
    assert rows_with_activity == 737


def test_distinct_components(parsed) -> None:
    descriptions = {r["componentDescription"] for r in parsed.rows if r["componentDescription"]}
    parents = {
        r["parentComponentDescription"] for r in parsed.rows if r["parentComponentDescription"]
    }
    tokens = {r["structureToken"] for r in parsed.rows if r["structureToken"]}
    assert len(descriptions) == 77
    assert len(parents) == 7
    assert len(tokens) == 77  # 7 top-level + 70 children


def test_distinct_failure_mechanisms(parsed) -> None:
    mechs = {r["mechanismAndCause"] for r in parsed.rows if r["mechanismAndCause"]}
    assert len(mechs) == 21


def test_strategy_distribution(parsed) -> None:
    from collections import Counter

    strategies = Counter(r["strategyType"] for r in parsed.rows if r["strategyType"])
    assert strategies["Condition Based"] == 692
    assert strategies["Fixed Time"] == 35
    assert strategies["Fault Find Interval"] == 8


# --- Error paths ---------------------------------------------------------------------


def test_parse_missing_file(tmp_path: Path) -> None:
    with pytest.raises(OrienParseError, match="not found"):
        parse_workbook(tmp_path / "nope.xlsx")
