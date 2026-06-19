"""Capture slots and the structured result of one bot conversation.

The voice bot fills a fixed set of *slots* — the reliability fields a call
centre must capture from an artisan reporting downtime. The slot order is the
conversation's spine: machine type first (it scopes every later option), then
the component, its position, the observed failure mode, and finally the root
cause if the technician knows it.

``CapturedDowntime`` is the deliverable. It is deliberately storage-agnostic;
:mod:`orien_import_tool.downtime_bot.persistence` bridges it to the existing
``DowntimeEvent`` / ``DowntimeClassification`` rows.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum


class Slot(StrEnum):
    """The reliability fields captured, in conversation order.

    ``GREETING`` and ``CONFIRM`` are conversational states rather than data
    fields; ``DONE`` is the terminal state. The data-bearing slots in between
    are what :class:`CapturedDowntime` records.
    """

    GREETING = "greeting"
    MACHINE_TYPE = "machine_type"
    ASSET_REF = "asset_ref"
    COMPONENT = "component"
    POSITION = "position"
    FAILURE_MODE = "failure_mode"
    ROOT_CAUSE = "root_cause"
    CONFIRM = "confirm"
    DONE = "done"


# Slots the operator must answer (asset ref and root cause are optional —
# asset ref is a convenience identifier, root cause is captured "if known").
REQUIRED_SLOTS: tuple[Slot, ...] = (
    Slot.MACHINE_TYPE,
    Slot.COMPONENT,
    Slot.POSITION,
    Slot.FAILURE_MODE,
)

OPTIONAL_SLOTS: tuple[Slot, ...] = (Slot.ASSET_REF, Slot.ROOT_CAUSE)


@dataclass
class CapturedDowntime:
    """Everything one conversation captures about a downtime event.

    ``*_token`` fields hold the canonical FMEA identifier when the spoken
    answer resolved to a known Component / FailureMode; they stay empty for
    free-text answers the taxonomy did not recognise (still captured, just
    unlinked). ``transcript`` keeps the full turn-by-turn exchange for audit.
    """

    technician: str = ""
    machine_type: str = ""
    equipment_token: str = ""
    asset_ref: str = ""
    component: str = ""
    component_token: str = ""
    position: str = ""
    failure_mode: str = ""
    failure_mode_token: str = ""
    root_cause: str = ""
    root_cause_known: bool = False
    notes: str = ""
    started_at: datetime = field(default_factory=datetime.utcnow)
    completed_at: datetime | None = None
    transcript: list[tuple[str, str]] = field(default_factory=list)

    def value_for(self, slot: Slot) -> str:
        """Return the captured string for ``slot`` (``""`` if unset)."""
        return {
            Slot.MACHINE_TYPE: self.machine_type,
            Slot.ASSET_REF: self.asset_ref,
            Slot.COMPONENT: self.component,
            Slot.POSITION: self.position,
            Slot.FAILURE_MODE: self.failure_mode,
            Slot.ROOT_CAUSE: self.root_cause,
        }.get(slot, "")

    def is_complete(self) -> bool:
        """True once every required slot carries a value."""
        return all(self.value_for(slot) for slot in REQUIRED_SLOTS)

    def summary_lines(self) -> list[str]:
        """Human-readable recap, one field per line (used for read-back)."""
        lines = [f"Machine type: {self.machine_type or '(not captured)'}"]
        if self.asset_ref:
            lines.append(f"Asset reference: {self.asset_ref}")
        lines.append(f"Component: {self.component or '(not captured)'}")
        lines.append(f"Position: {self.position or '(not captured)'}")
        lines.append(f"Failure mode: {self.failure_mode or '(not captured)'}")
        lines.append(
            "Root cause: "
            + (self.root_cause if self.root_cause else "(not known)")
        )
        return lines
