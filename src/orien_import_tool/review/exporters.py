"""Export :class:`ReviewQueue` to CSV / Markdown; import decisions back from CSV.

The CSV is the round-trip format. Columns:

* ``item_id`` (read-only, identifies the item)
* ``item_type``, ``summary``, ``detail``, ``primary_proposal``, ``alternates``,
  ``confidence``, ``proposer`` — populated by the exporter; the SME ignores
  these or reads them for context.
* ``verdict`` — empty on export. SME fills with ``accepted`` / ``rejected``
  / ``corrected``.
* ``chosen_alternative`` — populated when ``verdict == corrected`` (one of
  the values in the alternates list, or a free-text override).
* ``note`` — optional free-text note from the SME.
* ``sme_user`` — optional reviewer name.

The Markdown exporter is read-only — it groups by item_type and is intended
for inspection / audit, not edit-and-reimport.
"""

from __future__ import annotations

import csv
from collections.abc import Iterable
from datetime import datetime
from io import StringIO

from orien_import_tool.review.models import (
    ReviewDecision,
    ReviewItem,
    ReviewItemType,
    ReviewQueue,
    ReviewVerdict,
)

CSV_FIELDS = (
    "item_id",
    "item_type",
    "summary",
    "detail",
    "primary_proposal",
    "alternates",
    "confidence",
    "proposer",
    "verdict",
    "chosen_alternative",
    "note",
    "sme_user",
)


# --- CSV export ----------------------------------------------------------------------


def queue_to_csv(queue: ReviewQueue) -> str:
    """Serialise the queue with empty decision columns ready for SME edit."""
    buffer = StringIO()
    writer = csv.DictWriter(buffer, fieldnames=CSV_FIELDS)
    writer.writeheader()
    for item in queue.items:
        writer.writerow(
            {
                "item_id": item.item_id,
                "item_type": item.item_type.value,
                "summary": item.summary,
                "detail": item.detail,
                "primary_proposal": item.primary_proposal,
                "alternates": " | ".join(item.alternates),
                "confidence": f"{item.confidence:.3f}",
                "proposer": item.proposer,
                "verdict": "",
                "chosen_alternative": "",
                "note": "",
                "sme_user": "",
            }
        )
    return buffer.getvalue()


# --- CSV import (decisions) ----------------------------------------------------------


def decisions_from_csv(csv_text: str) -> list[ReviewDecision]:
    """Parse a CSV produced by :func:`queue_to_csv` after SME has filled in verdicts."""
    decisions: list[ReviewDecision] = []
    reader = csv.DictReader(StringIO(csv_text))
    for row in reader:
        verdict_raw = (row.get("verdict") or "").strip().lower()
        if not verdict_raw or verdict_raw == ReviewVerdict.PENDING.value:
            continue
        try:
            verdict = ReviewVerdict(verdict_raw)
        except ValueError:
            # Skip rows with unrecognised verdicts; the caller can audit
            # via row counts before/after.
            continue
        decisions.append(
            ReviewDecision(
                item_id=(row.get("item_id") or "").strip(),
                verdict=verdict,
                chosen_alternative=(row.get("chosen_alternative") or "").strip(),
                note=(row.get("note") or "").strip(),
                sme_user=(row.get("sme_user") or "").strip(),
                decided_at=datetime.now(),
            )
        )
    return decisions


# --- Markdown export -----------------------------------------------------------------


def queue_to_markdown(queue: ReviewQueue) -> str:
    """Render the queue grouped by ``item_type`` for browsing in a Markdown viewer."""
    if not queue.items:
        return "# SME Review Queue\n\nNothing pending. \U0001f389\n"

    out: list[str] = ["# SME Review Queue", ""]
    type_count = len({i.item_type for i in queue.items})
    out.append(f"_{len(queue)} items pending across {type_count} types._")
    out.append("")

    for item_type in ReviewItemType:
        section_items = queue.by_type(item_type)
        if not section_items:
            continue
        out.append(f"## {item_type.value.replace('_', ' ').title()} ({len(section_items)})")
        out.append("")
        for item in section_items:
            out.extend(_render_item_md(item))
            out.append("")
    return "\n".join(out).rstrip() + "\n"


def _render_item_md(item: ReviewItem) -> Iterable[str]:
    yield f"### `{item.item_id}`"
    yield ""
    yield f"- **summary:** {item.summary}"
    yield f"- **proposed:** `{item.primary_proposal}`"
    if item.alternates:
        alts = ", ".join(f"`{a}`" for a in item.alternates)
        yield f"- **alternates:** {alts}"
    yield f"- **confidence:** {item.confidence:.2f}  _(proposer: {item.proposer})_"
    if item.detail:
        yield f"- **detail:** {item.detail}"
