"""CSV loaders for the ISO 14224 reference tables.

Each loader returns a dict keyed by the table's natural primary key (see
``data/iso14224/SCHEMA.md``). ``load_all`` returns an :class:`Iso14224ReferenceSet`
bundling every table for downstream mapping.
"""

import csv
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from orien_import_tool.iso14224.models import (
    Iso14224DetectionMethod,
    Iso14224FailureCause,
    Iso14224FailureMechanism,
    Iso14224FailureMode,
    Iso14224MaintenanceActivity,
)

DEFAULT_ISO_DIR = Path("data/iso14224")

_FILES = {
    "failure_modes": "ISO14224_Table_B15_FailureModeDescriptions.csv",
    "failure_mechanisms": "ISO14224_Table_B2_FailureMechanisms.csv",
    "failure_causes": "ISO14224_Table_B3_FailureCauses.csv",
    "detection_methods": "ISO14224_Table_B4_DetectionMethods.csv",
    "maintenance_activities": "ISO14224_Table_B5_MaintenanceActivities.csv",
    "maintenance_activity_extensions": "ISO14224_Table_B5_Extensions.csv",
}

# Extension code numbers must be at or above this value to leave room for
# future ISO 14224 standard rows.
_EXTENSION_CODE_FLOOR = 1001


class IsoLoadError(ValueError):
    """Raised when an ISO 14224 CSV violates its expected schema."""


def _read_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        raise IsoLoadError(f"missing ISO 14224 table: {path}")
    with path.open(encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        rows = [{(k or "").strip(): (v or "").strip() for k, v in row.items()} for row in reader]
    return rows


def _require_columns(path: Path, row: Mapping[str, str], expected: set[str]) -> None:
    missing = expected - set(row)
    if missing:
        raise IsoLoadError(f"{path.name}: missing columns {sorted(missing)}")


def _check_unique(path: Path, key_fn, items: list, dimension: str) -> None:
    seen: set = set()
    for item in items:
        key = key_fn(item)
        if key in seen:
            raise IsoLoadError(f"{path.name}: duplicate {dimension} {key!r}")
        seen.add(key)


def load_failure_modes(iso_dir: Path = DEFAULT_ISO_DIR) -> dict[str, Iso14224FailureMode]:
    path = iso_dir / _FILES["failure_modes"]
    rows = _read_rows(path)
    if not rows:
        raise IsoLoadError(f"{path.name}: no data rows")
    _require_columns(path, rows[0], {"failure_mode", "description"})
    items = [
        Iso14224FailureMode(code=r["failure_mode"], description=r["description"]) for r in rows
    ]
    _check_unique(path, lambda m: m.code, items, "failure_mode")
    return {m.code: m for m in items}


def _load_hierarchical(
    path: Path,
    cls: type,
) -> list:
    rows = _read_rows(path)
    if not rows:
        raise IsoLoadError(f"{path.name}: no data rows")
    _require_columns(
        path,
        rows[0],
        {"main_code", "main_category", "sub_code", "sub_name", "description"},
    )
    items = []
    for r in rows:
        try:
            main_code = int(r["main_code"])
        except ValueError as exc:
            raise IsoLoadError(f"{path.name}: non-integer main_code {r['main_code']!r}") from exc
        items.append(
            cls(
                sub_code=r["sub_code"],
                main_code=main_code,
                main_category=r["main_category"],
                sub_name=r["sub_name"],
                description=r["description"],
            )
        )
    _check_unique(path, lambda x: x.sub_code, items, "sub_code")
    return items


def load_failure_mechanisms(
    iso_dir: Path = DEFAULT_ISO_DIR,
) -> dict[str, Iso14224FailureMechanism]:
    path = iso_dir / _FILES["failure_mechanisms"]
    items = _load_hierarchical(path, Iso14224FailureMechanism)
    return {m.sub_code: m for m in items}


def load_failure_causes(iso_dir: Path = DEFAULT_ISO_DIR) -> dict[str, Iso14224FailureCause]:
    path = iso_dir / _FILES["failure_causes"]
    items = _load_hierarchical(path, Iso14224FailureCause)
    return {c.sub_code: c for c in items}


def load_detection_methods(
    iso_dir: Path = DEFAULT_ISO_DIR,
) -> dict[int, Iso14224DetectionMethod]:
    path = iso_dir / _FILES["detection_methods"]
    rows = _read_rows(path)
    if not rows:
        raise IsoLoadError(f"{path.name}: no data rows")
    _require_columns(path, rows[0], {"code_number", "method", "description", "examples"})
    items = []
    for r in rows:
        try:
            code = int(r["code_number"])
        except ValueError as exc:
            raise IsoLoadError(
                f"{path.name}: non-integer code_number {r['code_number']!r}"
            ) from exc
        items.append(
            Iso14224DetectionMethod(
                code_number=code,
                method=r["method"],
                description=r["description"],
                examples=r["examples"],
            )
        )
    _check_unique(path, lambda d: d.code_number, items, "code_number")
    return {d.code_number: d for d in items}


def load_maintenance_activities(
    iso_dir: Path = DEFAULT_ISO_DIR,
) -> dict[int, Iso14224MaintenanceActivity]:
    """Load B5 plus any local extensions from ``ISO14224_Table_B5_Extensions.csv``.

    Extension rows are flagged ``is_extension=True`` and must use code numbers
    at or above ``_EXTENSION_CODE_FLOOR`` (1001) to leave room for future ISO
    14224 standard rows.
    """

    items = list(_load_b5_rows(iso_dir / _FILES["maintenance_activities"], is_extension=False))

    extensions_path = iso_dir / _FILES["maintenance_activity_extensions"]
    if extensions_path.exists():
        extension_items = list(_load_b5_rows(extensions_path, is_extension=True))
        for ext in extension_items:
            if ext.code_number < _EXTENSION_CODE_FLOOR:
                raise IsoLoadError(
                    f"{extensions_path.name}: extension code_number {ext.code_number} "
                    f"is below the {_EXTENSION_CODE_FLOOR} floor reserved for "
                    f"local additions"
                )
        items.extend(extension_items)

    _check_unique(
        iso_dir / _FILES["maintenance_activities"],
        lambda a: a.code_number,
        items,
        "code_number",
    )
    return {a.code_number: a for a in items}


def _load_b5_rows(path: Path, *, is_extension: bool):
    rows = _read_rows(path)
    if not rows:
        raise IsoLoadError(f"{path.name}: no data rows")
    _require_columns(path, rows[0], {"code_number", "activity", "description", "examples", "use"})
    for r in rows:
        try:
            code = int(r["code_number"])
        except ValueError as exc:
            raise IsoLoadError(
                f"{path.name}: non-integer code_number {r['code_number']!r}"
            ) from exc
        use_tokens = {t.strip() for t in r["use"].split(",") if t.strip()}
        if use_tokens and not use_tokens <= {"C", "P"}:
            raise IsoLoadError(
                f"{path.name}: row {code} has unexpected `use` tokens {sorted(use_tokens)}"
            )
        yield Iso14224MaintenanceActivity(
            code_number=code,
            activity=r["activity"],
            description=r["description"],
            examples=r["examples"],
            use=r["use"],
            is_extension=is_extension,
        )


@dataclass(frozen=True, slots=True)
class Iso14224ReferenceSet:
    """Bundle of every loaded ISO 14224 table, keyed by primary key."""

    failure_modes: dict[str, Iso14224FailureMode]
    failure_mechanisms: dict[str, Iso14224FailureMechanism]
    failure_causes: dict[str, Iso14224FailureCause]
    detection_methods: dict[int, Iso14224DetectionMethod]
    maintenance_activities: dict[int, Iso14224MaintenanceActivity]


def load_all(iso_dir: Path = DEFAULT_ISO_DIR) -> Iso14224ReferenceSet:
    return Iso14224ReferenceSet(
        failure_modes=load_failure_modes(iso_dir),
        failure_mechanisms=load_failure_mechanisms(iso_dir),
        failure_causes=load_failure_causes(iso_dir),
        detection_methods=load_detection_methods(iso_dir),
        maintenance_activities=load_maintenance_activities(iso_dir),
    )
