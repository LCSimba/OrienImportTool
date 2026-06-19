"""Tests that the taxonomy adapter derives the right options from the FMEA."""

from __future__ import annotations

from orien_import_tool.downtime_bot.taxonomy import CaptureTaxonomy


def test_machine_types(taxonomy: CaptureTaxonomy) -> None:
    types = taxonomy.machine_types()
    assert [t.value for t in types] == ["Conveyor"]
    assert types[0].token == "CONV1"
    assert "ACME" in types[0].aliases


def test_components_scoped_to_machine(taxonomy: CaptureTaxonomy) -> None:
    values = [c.value for c in taxonomy.components("CONV1")]
    assert values == ["Drive motor", "Head pulley bearing", "Conveyor belt"]
    assert taxonomy.components("UNKNOWN") == []


def test_failure_modes_for_component(taxonomy: CaptureTaxonomy) -> None:
    modes = taxonomy.failure_modes("C-MOTOR")
    assert [m.value for m in modes] == ["Motor overheats"]
    assert modes[0].token == "FM-MOT-1"


def test_root_causes_parsed_from_mechanism(taxonomy: CaptureTaxonomy) -> None:
    causes = [c.value for c in taxonomy.root_causes("C-BEARING")]
    assert "contamination" in causes


def test_position_hints_mined_from_descriptions(taxonomy: CaptureTaxonomy) -> None:
    hints = taxonomy.position_hints("C-BEARING")
    # "Head pulley" appears in the component text, so "head" is offered.
    assert "head" in hints


def test_empty_taxonomy_has_no_machine_types() -> None:
    empty = CaptureTaxonomy(equipment=[], iso=None)
    assert empty.machine_types() == []
    assert empty.failure_modes("anything") == []
