"""Bridge a captured conversation into the existing downtime tables.

A finished :class:`CapturedDowntime` is the same shape of fact the CSV/Excel
downtime adapters produce, so it flows into the very same pipeline: a
:class:`DowntimeEvent` (the raw record) plus a pre-filled
:class:`DowntimeClassification` (the component / failure-mode the technician
already told us, so it does *not* need re-classifying). Because the technician
picked these against the FMEA, the classification's ``proposer`` is recorded as
``"voicebot"`` and confidence is full for any slot that resolved to a canonical
token.
"""

from __future__ import annotations

from orien_import_tool.domain.downtime import (
    ComponentMatch,
    DowntimeClassification,
    DowntimeEvent,
    FailureModeCandidate,
)
from orien_import_tool.downtime_bot.slots import CapturedDowntime

MODEL_RUN_ID = "voicebot"
SOURCE_SYSTEM = "voicebot"


def make_external_id(captured: CapturedDowntime) -> str:
    """Deterministic natural key from the capture's start time + machine."""
    stamp = captured.started_at.strftime("%Y%m%d%H%M%S%f")
    token = captured.equipment_token or "na"
    return f"voicebot-{stamp}-{token}"


def compose_text(captured: CapturedDowntime) -> str:
    """One-line human-readable record, mirroring how CMMS rows read."""
    parts = [captured.machine_type]
    if captured.asset_ref:
        parts.append(f"({captured.asset_ref})")
    if captured.position:
        parts.append(f"{captured.position} {captured.component}".strip())
    elif captured.component:
        parts.append(captured.component)
    if captured.failure_mode:
        parts.append(f"- {captured.failure_mode}")
    if captured.root_cause:
        parts.append(f"due to {captured.root_cause}")
    return " ".join(p for p in parts if p).strip()


def to_event(captured: CapturedDowntime) -> DowntimeEvent:
    """Build the raw :class:`DowntimeEvent` for a capture."""
    free_text = " ".join(
        p for p in (captured.failure_mode, captured.root_cause) if p
    )
    coded = tuple(
        p
        for p in (
            captured.component,
            captured.position,
            captured.failure_mode,
            captured.root_cause,
        )
        if p
    )
    return DowntimeEvent(
        external_id=make_external_id(captured),
        asset_ref=captured.asset_ref or captured.machine_type,
        text=compose_text(captured),
        free_text=free_text,
        start_ts=captured.started_at,
        end_ts=captured.completed_at,
        source_system=SOURCE_SYSTEM,
        coded_context=coded,
        text_line3=free_text,
    )


def to_classification(captured: CapturedDowntime) -> DowntimeClassification:
    """Build the pre-filled :class:`DowntimeClassification` for a capture.

    The technician *told* us the component and failure mode, so we record them
    as the classification rather than leaving them for the ML/LLM pipeline. A
    slot that resolved to a canonical FMEA token gets full confidence; a
    free-text answer the taxonomy did not recognise gets ``0.0`` so it still
    surfaces for SME review.
    """
    component_match = None
    if captured.component:
        component_match = ComponentMatch(
            component_token=captured.component_token,
            component_description=captured.component,
            score=1.0 if captured.component_token else 0.0,
            matched_terms=(captured.component,),
        )

    candidates: list[FailureModeCandidate] = []
    if captured.failure_mode:
        candidates.append(
            FailureModeCandidate(
                failure_mode_token=captured.failure_mode_token,
                component_token=captured.component_token,
                score=1.0 if captured.failure_mode_token else 0.0,
                matched_terms=(captured.failure_mode,),
                rationale=captured.root_cause,
            )
        )

    notes = f"root_cause={captured.root_cause}" if captured.root_cause else ""
    return DowntimeClassification(
        event_external_id=make_external_id(captured),
        component_match=component_match,
        failure_mode_candidates=candidates,
        proposer="voicebot",
        notes=notes,
    )


def persist(session, captured: CapturedDowntime) -> str:
    """Write the event, its classification, and an audit row; return the id.

    ``session`` is a SQLAlchemy session; the caller owns the transaction and
    commits. Imported lazily so this module stays usable (for ``to_event`` /
    ``to_classification``) without the optional ``sqlalchemy`` dependency.
    """
    from orien_import_tool.persistence.repositories import (
        AuditLogRepository,
        DowntimeRepository,
    )

    event = to_event(captured)
    classification = to_classification(captured)

    downtime = DowntimeRepository(session)
    downtime.upsert_events([event])
    downtime.add_classifications([classification], model_run_id=MODEL_RUN_ID)

    AuditLogRepository(session).append(
        actor=captured.technician or "voicebot",
        action="capture_downtime",
        entity_type="downtime_event",
        entity_id=event.external_id,
        payload={
            "machine_type": captured.machine_type,
            "component": captured.component,
            "position": captured.position,
            "failure_mode": captured.failure_mode,
            "root_cause": captured.root_cause,
        },
    )
    return event.external_id
