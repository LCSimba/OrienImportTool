"""Tests for the ISO 14224 CSV loaders.

The CSVs in ``data/iso14224/`` are the system's reference data; these tests
double as a contract that warns when an upstream re-emit changes the schema
in a breaking way.
"""

from pathlib import Path

import pytest

from orien_import_tool.iso14224 import (
    Iso14224ReferenceSet,
    load_all,
    load_detection_methods,
    load_failure_causes,
    load_failure_mechanisms,
    load_failure_modes,
    load_maintenance_activities,
)
from orien_import_tool.iso14224.loader import IsoLoadError

# --- B15 Failure Modes ---------------------------------------------------------------


def test_load_failure_modes_count(iso_dir: Path) -> None:
    modes = load_failure_modes(iso_dir)
    assert len(modes) == 29


def test_load_failure_modes_contains_canonical_examples(iso_dir: Path) -> None:
    modes = load_failure_modes(iso_dir)
    for code in ["Leak", "No output", "Worn", "Corroded", "Open circuit", "Unknown"]:
        assert code in modes, f"expected B15 entry {code!r} missing"


def test_load_failure_modes_keys_match_models(iso_dir: Path) -> None:
    modes = load_failure_modes(iso_dir)
    for code, mode in modes.items():
        assert code == mode.code


# --- B2 Failure Mechanisms -----------------------------------------------------------


def test_load_failure_mechanisms_count(iso_dir: Path) -> None:
    mechanisms = load_failure_mechanisms(iso_dir)
    assert len(mechanisms) == 38


def test_load_failure_mechanisms_six_categories(iso_dir: Path) -> None:
    mechanisms = load_failure_mechanisms(iso_dir)
    categories = {m.main_category for m in mechanisms.values()}
    assert categories == {
        "Mechanical failure",
        "Material failure",
        "Instrument failure",
        "Electrical failure",
        "External influence",
        "Miscellaneous",
    }


def test_load_failure_mechanisms_general_disambiguated(iso_dir: Path) -> None:
    mechanisms = load_failure_mechanisms(iso_dir)
    generals = [m for m in mechanisms.values() if m.is_general]
    assert len(generals) == 6
    sub_codes = {m.sub_code for m in generals}
    assert sub_codes == {"1", "2", "3", "4", "5", "6"}


def test_load_failure_mechanisms_sub_codes_unique(iso_dir: Path) -> None:
    mechanisms = load_failure_mechanisms(iso_dir)
    assert len(mechanisms) == len({m.sub_code for m in mechanisms.values()})


# --- B3 Failure Causes ---------------------------------------------------------------


def test_load_failure_causes_count(iso_dir: Path) -> None:
    causes = load_failure_causes(iso_dir)
    assert len(causes) == 21


def test_load_failure_causes_four_categories(iso_dir: Path) -> None:
    causes = load_failure_causes(iso_dir)
    categories = {c.main_category for c in causes.values()}
    assert categories == {
        "Design/manufacturing",
        "Operation/maintenance",
        "External",
        "Other",
    }


def test_load_failure_causes_subcode_hierarchy_consistent(iso_dir: Path) -> None:
    causes = load_failure_causes(iso_dir)
    for c in causes.values():
        if "." in c.sub_code:
            head = c.sub_code.split(".", 1)[0]
            assert int(head) == c.main_code


# --- B4 Detection Methods ------------------------------------------------------------


def test_load_detection_methods_count(iso_dir: Path) -> None:
    methods = load_detection_methods(iso_dir)
    assert len(methods) == 10


def test_load_detection_methods_codes_are_1_to_10(iso_dir: Path) -> None:
    methods = load_detection_methods(iso_dir)
    assert set(methods.keys()) == set(range(1, 11))


def test_load_detection_methods_unknown_examples_blank(iso_dir: Path) -> None:
    """The B4 'Unknown' row has no examples; the loader must accept that."""
    methods = load_detection_methods(iso_dir)
    assert methods[10].method == "Unknown"
    assert methods[10].examples == ""


# --- B5 Maintenance Activities -------------------------------------------------------


def test_load_maintenance_activities_count(iso_dir: Path) -> None:
    """12 ISO-standard rows + extensions loaded from B5_Extensions.csv."""
    activities = load_maintenance_activities(iso_dir)
    iso_rows = [a for a in activities.values() if not a.is_extension]
    extension_rows = [a for a in activities.values() if a.is_extension]
    assert len(iso_rows) == 12
    assert len(extension_rows) >= 1


def test_load_maintenance_activities_statutory_extension(iso_dir: Path) -> None:
    activities = load_maintenance_activities(iso_dir)
    statutory = activities[1001]
    assert statutory.activity == "Statutory"
    assert statutory.is_extension is True
    assert statutory.code_number >= 1001


def test_load_maintenance_activities_use_values(iso_dir: Path) -> None:
    activities = load_maintenance_activities(iso_dir)
    for a in activities.values():
        tokens = {t.strip() for t in a.use.split(",") if t.strip()}
        assert tokens <= {"C", "P"}, f"row {a.code_number} use={a.use!r}"


def test_load_maintenance_activities_repair_corrective_only(iso_dir: Path) -> None:
    activities = load_maintenance_activities(iso_dir)
    repair = activities[2]
    assert repair.activity == "Repair"
    assert repair.is_corrective
    assert not repair.is_preventative


def test_load_maintenance_activities_replace_both(iso_dir: Path) -> None:
    activities = load_maintenance_activities(iso_dir)
    replace = activities[1]
    assert replace.activity == "Replace"
    assert replace.is_corrective and replace.is_preventative


# --- Bundle ---------------------------------------------------------------------------


def test_load_all_returns_complete_set(iso_dir: Path) -> None:
    refset = load_all(iso_dir)
    assert isinstance(refset, Iso14224ReferenceSet)
    assert len(refset.failure_modes) == 29
    assert len(refset.failure_mechanisms) == 38
    assert len(refset.failure_causes) == 21
    assert len(refset.detection_methods) == 10
    iso_rows = [a for a in refset.maintenance_activities.values() if not a.is_extension]
    assert len(iso_rows) == 12


# --- Error handling -------------------------------------------------------------------


def test_load_failure_modes_missing_file(tmp_path: Path) -> None:
    with pytest.raises(IsoLoadError, match="missing"):
        load_failure_modes(tmp_path)


def test_load_failure_modes_missing_columns(tmp_path: Path) -> None:
    bad = tmp_path / "ISO14224_Table_B15_FailureModeDescriptions.csv"
    bad.write_text("only_one_column\nLeak\n", encoding="utf-8")
    with pytest.raises(IsoLoadError, match="missing columns"):
        load_failure_modes(tmp_path)


def test_load_failure_mechanisms_duplicate_subcode(tmp_path: Path) -> None:
    bad = tmp_path / "ISO14224_Table_B2_FailureMechanisms.csv"
    bad.write_text(
        "main_code,main_category,sub_code,sub_name,description\n"
        "1,Mechanical,1.1,Leakage,leak\n"
        "1,Mechanical,1.1,DupLeakage,leak\n",
        encoding="utf-8",
    )
    with pytest.raises(IsoLoadError, match="duplicate"):
        load_failure_mechanisms(tmp_path)
