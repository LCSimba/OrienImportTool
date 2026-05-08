"""Tests for the rule-seeded alias store."""

from __future__ import annotations

from pathlib import Path

import pytest

from orien_import_tool.aliases import AliasProposer, build_initial_alias_store
from orien_import_tool.iso14224 import load_all


def test_default_seed_has_cmms_aliases() -> None:
    store = build_initial_alias_store()
    # A few canonical CMMS terms we curated.
    assert store.get("tripped"), "tripped should be seeded"
    assert store.get("collapsing"), "collapsing should be seeded"
    assert store.get("faulty"), "faulty should be seeded"
    assert all(a.proposer == AliasProposer.RULE for a in store)


def test_tripped_expands_to_stop_tokens() -> None:
    store = build_initial_alias_store()
    expanded = store.expand_token("tripped")
    assert "stoppage" in expanded
    assert "stop" in expanded


def test_collapsing_expands_to_breakage_tokens() -> None:
    store = build_initial_alias_store()
    expanded = store.expand_token("collapsing")
    assert {"breaks", "broken", "fracture"} & expanded


def test_iso_identity_aliases_added_when_ref_passed(iso_dir: Path) -> None:
    ref = load_all(iso_dir)
    store = build_initial_alias_store(iso_ref=ref)
    # B15 vocabulary should produce identity aliases.
    assert store.get("worn")
    assert store.get("corroded")
    # B2 / B3 sub_name tokens too.
    assert store.get("vibration")
    assert store.get("contamination")


def test_iso_identity_alias_carries_iso_hint(iso_dir: Path) -> None:
    ref = load_all(iso_dir)
    store = build_initial_alias_store(iso_ref=ref)
    matches = store.get("worn")
    iso_hints = {a.iso_hint for a in matches}
    assert any(hint.startswith("B15:") for hint in iso_hints)


@pytest.fixture(scope="module")
def conveyor_equipment(orien_fixture_dir: Path):
    from orien_import_tool.importers.orien import normalize, parse_workbook

    fixture = (
        orien_fixture_dir
        / "2025918727_CONVEYOR4FBeltTRUNK_ExportOfSingleSheetTactics_3QN56K0-0.xlsx"
    )
    if not fixture.exists():
        pytest.skip(f"Conveyor fixture missing: {fixture}")
    return normalize(parse_workbook(fixture))


def test_equipment_seed_adds_scoped_aliases(conveyor_equipment) -> None:
    store = build_initial_alias_store(equipment=conveyor_equipment)
    # Component-description tokens should be seeded with the equipment scope.
    matches = store.get("conveyor")
    assert any(a.scope_equipment_token == conveyor_equipment.token for a in matches)
