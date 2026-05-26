"""Excel adapter for downtime exports.

Schema-tolerant: detects which of the known column names are present and
composes :class:`DowntimeEvent` records from whatever's available. Built
against the AI_Test fixture (CMMS-style export), which carries two shapes:

* 10-column descriptive (no date/duration): ``EquipmentTypeDescription``,
  ``EquipmentGroupIDName``, ``Availability_Name``, ``ComponentCode``,
  ``ComponentCodeDescription``, ``Table Desc``, ``TextLine1``,
  ``TextLine2``, ``TextLine3``, ``UDC Description``.
* 8-column aggregated (with date + downtime hours): adds ``Day of Date``
  and ``DOWN``, drops the ``ComponentCode`` block.

Multi-sheet workbooks require an explicit ``sheet_name`` — the workbook
typically holds different equipment classes per sheet (Conveyor, Drill,
ZibuloConveyors, etc.) and we want the caller to choose deliberately.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import openpyxl

from orien_import_tool.domain.downtime import DowntimeEvent

# Columns composed into the full ``text`` field (free-text *and* validated
# columns), ordered by descending specificity. Empty values are skipped at
# compose time. The classifier matches against this — the coded descriptions
# (Table Desc, ComponentCodeDescription) are useful signal.
_TEXT_COLUMNS: tuple[str, ...] = (
    "TextLine3",
    "TextLine2",
    "TextLine1",
    "Table Desc",
    "UDC Description",
    "ComponentCodeDescription",
)

# The only operator-typed, non-validated columns. Spelling/abbreviation
# cleanup and mining run against *these alone* — the other columns are
# validated codes (ComponentCode, Table Desc) and carry their own
# descriptions, so "correcting" them would be wrong.
_FREE_TEXT_COLUMNS: tuple[str, ...] = (
    "TextLine1",
    "TextLine2",
    "TextLine3",
)

_ASSET_COLUMNS: tuple[str, ...] = (
    "EquipmentGroupIDName",
    "EquipmentTypeDescription",
)

_DATE_COLUMNS: tuple[str, ...] = (
    "Day of Date",
    "Date",
    "DateTime",
)

_DURATION_HOURS_COLUMNS: tuple[str, ...] = (
    "DOWN",
    "Duration (hours)",
    "Hours",
)

_CATEGORY_COLUMNS: tuple[str, ...] = ("Availability_Name",)

# Validated/coded columns surfaced as ``coded_context`` — disambiguation
# context for an LLM (not matched, not corrected). Most-specific last.
_CONTEXT_COLUMNS: tuple[str, ...] = (
    "Availability_Name",
    "ComponentCodeDescription",
    "Table Desc",
)


class DowntimeExcelError(ValueError):
    """Raised when an Excel downtime export fails to parse."""


def parse_xlsx(
    path: Path,
    sheet_name: str,
    *,
    source_system: str = "excel",
) -> list[DowntimeEvent]:
    """Parse one sheet of a downtime XLSX into :class:`DowntimeEvent` records.

    External IDs are synthesised as ``"{sheet_name}:{row_number}"`` since
    CMMS aggregate exports don't carry a stable per-row key. Callers that
    re-ingest the same workbook must rely on (file_hash, sheet_name,
    row_number) for idempotency.
    """
    if not path.exists():
        raise DowntimeExcelError(f"downtime XLSX not found: {path}")

    wb = openpyxl.load_workbook(path, data_only=True, read_only=True)
    if sheet_name not in wb.sheetnames:
        raise DowntimeExcelError(
            f"{path.name}: sheet {sheet_name!r} not found; available sheets: {wb.sheetnames!r}"
        )

    ws = wb[sheet_name]
    rows = list(ws.iter_rows(values_only=True))
    if not rows:
        return []

    headers = [(h or "").strip() if isinstance(h, str) else "" for h in rows[0]]
    col_idx = {h: i for i, h in enumerate(headers) if h}

    text_cols = [c for c in _TEXT_COLUMNS if c in col_idx]
    free_text_cols = [c for c in _FREE_TEXT_COLUMNS if c in col_idx]
    context_cols = [c for c in _CONTEXT_COLUMNS if c in col_idx]
    asset_cols = [c for c in _ASSET_COLUMNS if c in col_idx]
    if not text_cols:
        raise DowntimeExcelError(
            f"{path.name}/{sheet_name}: no text column found "
            f"(looked for {list(_TEXT_COLUMNS)}); got headers {list(col_idx)}"
        )
    if not asset_cols:
        raise DowntimeExcelError(
            f"{path.name}/{sheet_name}: no asset column found "
            f"(looked for {list(_ASSET_COLUMNS)}); got headers {list(col_idx)}"
        )

    date_col = next((c for c in _DATE_COLUMNS if c in col_idx), None)
    duration_col = next((c for c in _DURATION_HOURS_COLUMNS if c in col_idx), None)

    events: list[DowntimeEvent] = []
    for row_no, row in enumerate(rows[1:], start=2):
        text = _compose_text(row, col_idx, text_cols)
        if not text:
            continue
        asset_ref = _first_nonblank(row, col_idx, asset_cols)
        if not asset_ref:
            continue

        events.append(
            DowntimeEvent(
                external_id=f"{sheet_name}:{row_no}",
                asset_ref=asset_ref,
                text=text,
                free_text=_compose_text(row, col_idx, free_text_cols),
                coded_context=_distinct_values(row, col_idx, context_cols),
                text_line3=_cell(row, col_idx, "TextLine3"),
                start_ts=_extract_datetime(row, col_idx, date_col),
                duration_s=_extract_duration_seconds(row, col_idx, duration_col),
                source_system=source_system,
            )
        )
    return events


def list_sheets(path: Path) -> list[str]:
    """Return the sheet names in a workbook (helper for choosing sheets)."""
    if not path.exists():
        raise DowntimeExcelError(f"downtime XLSX not found: {path}")
    wb = openpyxl.load_workbook(path, data_only=True, read_only=True)
    return list(wb.sheetnames)


# --- Internals --------------------------------------------------------------------


def _compose_text(
    row: tuple,
    col_idx: dict[str, int],
    text_cols: list[str],
) -> str:
    seen: set[str] = set()
    parts: list[str] = []
    for col in text_cols:
        value = row[col_idx[col]]
        if value is None:
            continue
        text = str(value).strip()
        if not text:
            continue
        # Avoid stuttering when several columns hold the same string
        # (UDC Description often duplicates TextLine2).
        key = text.casefold()
        if key in seen:
            continue
        seen.add(key)
        parts.append(text)
    return " | ".join(parts)


def _cell(row: tuple, col_idx: dict[str, int], col: str) -> str:
    """Single trimmed cell value, or '' if the column is absent/blank."""
    if col not in col_idx:
        return ""
    value = row[col_idx[col]]
    return str(value).strip() if value is not None else ""


def _distinct_values(
    row: tuple,
    col_idx: dict[str, int],
    cols: list[str],
) -> tuple[str, ...]:
    """Distinct, non-blank values across ``cols`` (casefold-deduped, in order)."""
    seen: set[str] = set()
    out: list[str] = []
    for col in cols:
        value = row[col_idx[col]]
        if value is None:
            continue
        text = str(value).strip()
        if not text:
            continue
        key = text.casefold()
        if key in seen:
            continue
        seen.add(key)
        out.append(text)
    return tuple(out)


def _first_nonblank(
    row: tuple,
    col_idx: dict[str, int],
    cols: list[str],
) -> str:
    for col in cols:
        value = row[col_idx[col]]
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return ""


def _extract_datetime(
    row: tuple,
    col_idx: dict[str, int],
    col: str | None,
) -> datetime | None:
    if col is None:
        return None
    value = row[col_idx[col]]
    if isinstance(value, datetime):
        return value
    if isinstance(value, str) and value.strip():
        try:
            return datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        except ValueError:
            return None
    return None


def _extract_duration_seconds(
    row: tuple,
    col_idx: dict[str, int],
    col: str | None,
) -> float | None:
    """``DOWN`` is in hours per the CMMS convention; convert to seconds."""
    if col is None:
        return None
    value = row[col_idx[col]]
    if isinstance(value, (int, float)):
        return float(value) * 3600.0
    return None
