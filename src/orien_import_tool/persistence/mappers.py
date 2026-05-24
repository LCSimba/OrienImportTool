"""Domain-dataclass <-> ORM-row conversion helpers.

Round-trips the *essential* fields used by downstream code (token,
description, parent linkage, mechanism_and_cause, activities). Less-used
fields on Component / FailureMode (comments, sort_position, statuses, etc.)
are dropped on persist — they live in the source workbook and can be
re-imported. Add columns for them if a query path needs them.

Activity round-trip rehydrates the nested ``ActivityLabour`` /
``ActivityMaterial`` / ``ActivityCost`` sub-dataclasses so consumers don't
get plain dicts back. Tuple fields (``matched_terms``) are cast on the way
out since JSON only knows lists.
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from orien_import_tool.aliases.models import Alias, AliasProposer
from orien_import_tool.domain.downtime import (
    ComponentMatch,
    DowntimeClassification,
    DowntimeEvent,
    FailureModeCandidate,
)
from orien_import_tool.domain.fmea import (
    Activity,
    ActivityCost,
    ActivityLabour,
    ActivityMaterial,
    Component,
    Equipment,
    FailureMode,
    Function,
    FunctionalFailure,
)
from orien_import_tool.mapping.models import (
    Iso14224Mapping,
    MappingDimension,
    Proposer,
)
from orien_import_tool.persistence.models import (
    AbbreviationRow,
    AliasRow,
    ComponentRow,
    DowntimeClassificationRow,
    DowntimeEventRow,
    EquipmentRow,
    FailureModeRow,
    Iso14224MappingRow,
)
from orien_import_tool.textnorm.abbreviations import Abbreviation, AbbrevProposer

# --- Equipment / Component / FailureMode --------------------------------------------


def equipment_to_orm(equipment: Equipment, *, file_hash: str = "") -> EquipmentRow:
    row = EquipmentRow(
        token=equipment.token,
        description=equipment.description,
        location="",
        parent_token="",
        metadata_json={"make": equipment.make, "model": equipment.model},
        file_hash=file_hash,
    )
    row.components = [_component_to_orm(c, equipment.token) for c in equipment.components]
    return row


def equipment_from_orm(row: EquipmentRow) -> Equipment:
    metadata = row.metadata_json or {}
    return Equipment(
        token=row.token,
        description=row.description,
        make=metadata.get("make", ""),
        model=metadata.get("model", ""),
        components=[_component_from_orm(c) for c in row.components],
    )


def _component_to_orm(component: Component, equipment_token: str) -> ComponentRow:
    row = ComponentRow(
        token=component.token,
        equipment_token=equipment_token,
        description=component.description,
        parent_description=component.parent_description,
        make=component.make,
        model=component.model,
    )
    row.failure_modes = [
        _failure_mode_to_orm(fm, function.description, failure.description, component.token)
        for function in component.functions
        for failure in function.failures
        for fm in failure.failure_modes
    ]
    return row


def _component_from_orm(row: ComponentRow) -> Component:
    """Rebuild Component+Function+FunctionalFailure tree from flat FailureMode rows."""
    function_groups: dict[str, dict[str, list[FailureMode]]] = {}
    for fm_row in row.failure_modes:
        function_groups.setdefault(fm_row.function_description, {}).setdefault(
            fm_row.failure_description, []
        ).append(_failure_mode_from_orm(fm_row))

    functions = [
        Function(
            description=fn_desc,
            failures=[
                FunctionalFailure(description=fail_desc, failure_modes=fms)
                for fail_desc, fms in failures.items()
            ],
        )
        for fn_desc, failures in function_groups.items()
    ]

    return Component(
        token=row.token,
        description=row.description,
        parent_description=row.parent_description,
        make=row.make,
        model=row.model,
        functions=functions,
    )


def _failure_mode_to_orm(
    fm: FailureMode,
    function_description: str,
    failure_description: str,
    component_token: str,
) -> FailureModeRow:
    return FailureModeRow(
        token=fm.token,
        component_token=component_token,
        function_description=function_description,
        failure_description=failure_description,
        what=fm.what,
        mechanism_and_cause=fm.mechanism_and_cause,
        strategy_type=fm.strategy_type,
        activities_json=[_activity_to_dict(a) for a in fm.activities],
    )


def _failure_mode_from_orm(row: FailureModeRow) -> FailureMode:
    activities = [_activity_from_dict(payload) for payload in (row.activities_json or [])]
    return FailureMode(
        token=row.token,
        what=row.what,
        mechanism_and_cause=row.mechanism_and_cause,
        strategy_type=row.strategy_type,
        activities=activities,
    )


# --- Activity (with nested sub-dataclasses) -----------------------------------------


def _activity_to_dict(activity: Activity) -> dict[str, Any]:
    return asdict(activity)


def _activity_from_dict(payload: dict[str, Any]) -> Activity:
    """Rehydrate Activity + nested sub-dataclasses from a JSON payload.

    JSON gives us plain dicts for the labour/materials/costs lists; we walk
    them and reconstruct the sub-dataclasses so callers get proper domain
    objects, not dicts.
    """
    payload = dict(payload)
    labour_payload = payload.pop("labour", []) or []
    materials_payload = payload.pop("materials", []) or []
    costs_payload = payload.pop("costs", []) or []
    activity = Activity(
        labour=[ActivityLabour(**raw) for raw in labour_payload],
        materials=[ActivityMaterial(**raw) for raw in materials_payload],
        costs=[ActivityCost(**raw) for raw in costs_payload],
        **payload,
    )
    return activity


# --- Iso14224Mapping ----------------------------------------------------------------


def mapping_to_orm(m: Iso14224Mapping) -> Iso14224MappingRow:
    return Iso14224MappingRow(
        source_entity_type=m.source_entity_type,
        source_entity_id=m.source_entity_id,
        dimension=m.dimension.value,
        iso_code=m.iso_code,
        proposer=m.proposer.value,
        confidence=m.confidence,
        rationale=m.rationale,
        priority=m.priority,
        iso_table_version=m.iso_table_version,
    )


def mapping_from_orm(row: Iso14224MappingRow) -> Iso14224Mapping:
    return Iso14224Mapping(
        source_entity_type=row.source_entity_type,
        source_entity_id=row.source_entity_id,
        dimension=MappingDimension(row.dimension),
        iso_code=row.iso_code,
        proposer=Proposer(row.proposer),
        confidence=row.confidence,
        rationale=row.rationale,
        priority=row.priority,
        iso_table_version=row.iso_table_version,
    )


# --- Alias --------------------------------------------------------------------------


def alias_to_orm(alias: Alias) -> AliasRow:
    return AliasRow(
        alias_text=alias.alias_text,
        canonical_tokens_json=list(alias.canonical_tokens),
        proposer=alias.proposer.value,
        confidence=alias.confidence,
        scope_equipment_token=alias.scope_equipment_token or "",
        iso_hint=alias.iso_hint,
        rationale=alias.rationale,
    )


def alias_from_orm(row: AliasRow) -> Alias:
    return Alias(
        alias_text=row.alias_text,
        canonical_tokens=tuple(row.canonical_tokens_json or ()),
        proposer=AliasProposer(row.proposer),
        confidence=row.confidence,
        scope_equipment_token=row.scope_equipment_token or None,
        iso_hint=row.iso_hint,
        rationale=row.rationale,
    )


# --- Abbreviation -------------------------------------------------------------------


def abbreviation_to_orm(abbrev: Abbreviation) -> AbbreviationRow:
    return AbbreviationRow(
        short=abbrev.short,
        expansion=abbrev.expansion,
        proposer=abbrev.proposer.value,
        confidence=abbrev.confidence,
        rationale=abbrev.rationale,
    )


def abbreviation_from_orm(row: AbbreviationRow) -> Abbreviation:
    return Abbreviation(
        short=row.short,
        expansion=row.expansion,
        proposer=AbbrevProposer(row.proposer),
        confidence=row.confidence,
        rationale=row.rationale,
    )


# --- Downtime ----------------------------------------------------------------------


def downtime_event_to_orm(event: DowntimeEvent) -> DowntimeEventRow:
    return DowntimeEventRow(
        external_id=event.external_id,
        asset_ref=event.asset_ref,
        text=event.text,
        start_ts=event.start_ts,
        end_ts=event.end_ts,
        duration_s=event.duration_s,
        source_system=event.source_system,
    )


def downtime_event_from_orm(row: DowntimeEventRow) -> DowntimeEvent:
    return DowntimeEvent(
        external_id=row.external_id,
        asset_ref=row.asset_ref,
        text=row.text,
        start_ts=row.start_ts,
        end_ts=row.end_ts,
        duration_s=row.duration_s,
        source_system=row.source_system,
    )


def classification_to_orm(
    classification: DowntimeClassification,
    *,
    model_run_id: str = "",
) -> DowntimeClassificationRow:
    return DowntimeClassificationRow(
        event_external_id=classification.event_external_id,
        component_token=(
            classification.component_match.component_token if classification.component_match else ""
        ),
        component_score=(
            classification.component_match.score if classification.component_match else 0.0
        ),
        failure_mode_candidates_json=[
            _candidate_to_dict(c) for c in classification.failure_mode_candidates
        ],
        proposer=classification.proposer,
        notes=classification.notes,
        model_run_id=model_run_id,
    )


def classification_from_orm(row: DowntimeClassificationRow) -> DowntimeClassification:
    candidates = [
        _candidate_from_dict(payload) for payload in (row.failure_mode_candidates_json or [])
    ]
    component_match = (
        ComponentMatch(
            component_token=row.component_token,
            component_description="",  # not persisted; resolve via EquipmentRepository
            score=row.component_score,
            matched_terms=(),
        )
        if row.component_token
        else None
    )
    return DowntimeClassification(
        event_external_id=row.event_external_id,
        component_match=component_match,
        failure_mode_candidates=candidates,
        proposer=row.proposer,
        notes=row.notes,
    )


def _candidate_to_dict(candidate: FailureModeCandidate) -> dict[str, Any]:
    return asdict(candidate)


def _candidate_from_dict(payload: dict[str, Any]) -> FailureModeCandidate:
    payload = dict(payload)
    payload["matched_terms"] = tuple(payload.get("matched_terms", ()))
    return FailureModeCandidate(**payload)
