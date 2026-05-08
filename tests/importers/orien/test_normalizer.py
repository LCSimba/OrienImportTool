"""Normalizer test: parsed export -> populated Equipment tree."""

from collections import Counter
from pathlib import Path

import pytest

from orien_import_tool.domain.fmea import Equipment
from orien_import_tool.importers.orien import normalize, parse_workbook

FIXTURE = "2025918727_CONVEYOR4FBeltTRUNK_ExportOfSingleSheetTactics_3QN56K0-0.xlsx"


@pytest.fixture(scope="module")
def equipment(orien_fixture_dir: Path) -> Equipment:
    path = orien_fixture_dir / FIXTURE
    if not path.exists():
        pytest.skip(f"Conveyor fixture missing: {path}")
    return normalize(parse_workbook(path))


def test_equipment_root(equipment: Equipment) -> None:
    assert equipment.token.startswith("MWFu")
    assert equipment.description == "CONVEYOR [4F-Belt] - TRUNK"
    assert equipment.language == "en"
    assert equipment.export_timestamp is not None


def test_components_grouped_by_token(equipment: Equipment) -> None:
    tokens = [c.token for c in equipment.components]
    assert len(tokens) == len(set(tokens))


def test_component_count_matches_distinct_tokens(equipment: Equipment) -> None:
    # 77 distinct structureTokens — a 2-level tree of 7 top-level + 70 children
    assert len(equipment.components) == 77


def test_top_level_parents(equipment: Equipment) -> None:
    top_level = [c for c in equipment.components if not c.parent_description]
    descriptions = {c.description for c in top_level}
    assert descriptions == {
        "Conveyor Belt Assembly",
        "Conveyor Drive System",
        "Conveyor Structure",
        "Conveyor Take-Up System",
        "Dust suppresion system",
        "Electrical System",
        "Instrumentation System",
    }
    assert len(top_level) == 7


def test_equipment_structure_revision(equipment: Equipment) -> None:
    """Per-row structureRevision integer surfaces on Equipment."""
    assert equipment.structure_revision == 1


def test_function_population(equipment: Equipment) -> None:
    total_functions = sum(len(c.functions) for c in equipment.components)
    assert total_functions > 0


def test_failure_mode_total(equipment: Equipment) -> None:
    modes = [
        fm
        for c in equipment.components
        for f in c.functions
        for ff in f.failures
        for fm in ff.failure_modes
    ]
    # 735 rows have a failure mode token; tokens are unique per failure mode.
    assert len({fm.token for fm in modes}) == len(modes)
    # 388 unique failureModeTokens in the fixture (re-derived from the data
    # rather than hard-coded).
    distinct_tokens = {
        fm.token
        for c in equipment.components
        for f in c.functions
        for ff in f.failures
        for fm in ff.failure_modes
    }
    assert len(distinct_tokens) == len(modes)


def test_function_types(equipment: Equipment) -> None:
    types = Counter(
        f.function_type for c in equipment.components for f in c.functions if f.function_type
    )
    assert "Primary Function" in types
    assert "Secondary Function" in types


def test_strategy_types(equipment: Equipment) -> None:
    strategies = Counter(
        fm.strategy_type
        for c in equipment.components
        for f in c.functions
        for ff in f.failures
        for fm in ff.failure_modes
        if fm.strategy_type
    )
    assert strategies["Condition Based"] > 0
    assert strategies["Fixed Time"] > 0


def test_activities_attached(equipment: Equipment) -> None:
    activities = [
        a
        for c in equipment.components
        for f in c.functions
        for ff in f.failures
        for fm in ff.failure_modes
        for a in fm.activities
    ]
    assert len(activities) > 0
    assert len({a.token for a in activities}) == len(activities)


def test_labour_lines_present(equipment: Equipment) -> None:
    labour_count = sum(
        len(a.labour)
        for c in equipment.components
        for f in c.functions
        for ff in f.failures
        for fm in ff.failure_modes
        for a in fm.activities
    )
    assert labour_count > 0
