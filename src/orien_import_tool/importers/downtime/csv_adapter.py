"""CSV adapter for downtime events.

Expected column names (case-insensitive, exact match required for the first
match; falls back to common synonyms):

| Canonical    | Synonyms                              |
|--------------|---------------------------------------|
| external_id  | event_id, id, ticket, work_order      |
| asset_ref    | asset, equipment, machine, asset_id   |
| start_ts     | start, start_time, started_at         |
| end_ts       | end, end_time, ended_at               |
| duration_s   | duration, duration_seconds            |
| text         | description, notes, comments          |
| source_system| source                                |

Rows missing required fields (``external_id``, ``asset_ref``, ``start_ts``,
``text``) are quarantined: the parser raises :class:`DowntimeIngestError`
listing offending row numbers, but only after attempting every row so the
caller sees the full picture.
"""

from __future__ import annotations

import csv
from datetime import datetime
from pathlib import Path

from orien_import_tool.domain.downtime import DowntimeEvent

_COLUMN_SYNONYMS: dict[str, tuple[str, ...]] = {
    "external_id": ("external_id", "event_id", "id", "ticket", "work_order"),
    "asset_ref": ("asset_ref", "asset", "equipment", "machine", "asset_id"),
    "start_ts": ("start_ts", "start", "start_time", "started_at"),
    "end_ts": ("end_ts", "end", "end_time", "ended_at"),
    "duration_s": ("duration_s", "duration", "duration_seconds"),
    "text": ("text", "description", "notes", "comments"),
    "source_system": ("source_system", "source"),
}

_REQUIRED = ("external_id", "asset_ref", "start_ts", "text")


class DowntimeIngestError(ValueError):
    """Raised when one or more rows fail to parse."""


def parse_csv(path: Path) -> list[DowntimeEvent]:
    """Parse a CSV file into :class:`DowntimeEvent` records.

    Idempotency is the caller's responsibility: dedupe on ``external_id``
    when persisting.
    """
    if not path.exists():
        raise DowntimeIngestError(f"downtime CSV not found: {path}")

    events: list[DowntimeEvent] = []
    bad_rows: list[tuple[int, str]] = []

    with path.open(encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        if reader.fieldnames is None:
            raise DowntimeIngestError(f"{path.name}: empty CSV")

        column_index = _resolve_columns(path, reader.fieldnames)
        for row_no, raw in enumerate(reader, start=2):  # 1 = header row
            try:
                events.append(_row_to_event(raw, column_index))
            except (ValueError, KeyError) as exc:
                bad_rows.append((row_no, str(exc)))

    if bad_rows:
        details = "; ".join(f"row {n}: {msg}" for n, msg in bad_rows[:5])
        more = f" (+{len(bad_rows) - 5} more)" if len(bad_rows) > 5 else ""
        raise DowntimeIngestError(f"{path.name}: {len(bad_rows)} bad rows — {details}{more}")
    return events


def _resolve_columns(path: Path, headers: list[str]) -> dict[str, str]:
    """Return ``{canonical: actual_column}`` for every canonical column found.

    Required columns missing from the file produce an immediate error.
    """
    lowered = {h.strip().lower(): h for h in headers}
    resolved: dict[str, str] = {}
    for canonical, synonyms in _COLUMN_SYNONYMS.items():
        for syn in synonyms:
            if syn.lower() in lowered:
                resolved[canonical] = lowered[syn.lower()]
                break
    missing = [c for c in _REQUIRED if c not in resolved]
    if missing:
        raise DowntimeIngestError(
            f"{path.name}: missing required column(s) {sorted(missing)}; got headers {headers!r}"
        )
    return resolved


def _row_to_event(raw: dict[str, str], cols: dict[str, str]) -> DowntimeEvent:
    external_id = (raw.get(cols["external_id"]) or "").strip()
    asset_ref = (raw.get(cols["asset_ref"]) or "").strip()
    text = (raw.get(cols["text"]) or "").strip()
    start_raw = (raw.get(cols["start_ts"]) or "").strip()
    if not (external_id and asset_ref and text and start_raw):
        raise ValueError("missing required field(s)")

    start_ts = _parse_ts(start_raw)
    end_ts = (
        _parse_ts(raw[cols["end_ts"]].strip())
        if "end_ts" in cols and raw.get(cols["end_ts"], "").strip()
        else None
    )
    duration_raw = raw.get(cols["duration_s"], "").strip() if "duration_s" in cols else ""
    duration_s = float(duration_raw) if duration_raw else None
    source_system = raw.get(cols["source_system"], "").strip() if "source_system" in cols else ""

    return DowntimeEvent(
        external_id=external_id,
        asset_ref=asset_ref,
        start_ts=start_ts,
        text=text,
        end_ts=end_ts,
        duration_s=duration_s,
        source_system=source_system,
    )


def _parse_ts(value: str) -> datetime:
    """Parse ISO 8601-like timestamps; tolerant of trailing 'Z' and missing seconds."""
    cleaned = value.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(cleaned)
    except ValueError as exc:
        raise ValueError(f"unparseable timestamp {value!r}") from exc
