"""Normalize a :class:`ParsedExport` (denormalized rows) into the canonical model.

Each Orien row is one ``(location, component, function, failure, failure_mode,
activity)`` tuple with up to 5 labour, 5 material, and 5 cost line-items inline.
This module groups rows by stable token to reconstruct the tree.
"""

from __future__ import annotations

from typing import Any

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
from orien_import_tool.importers.orien import schema as S
from orien_import_tool.importers.orien.parser import ParsedExport


def normalize(parsed: ParsedExport) -> Equipment:
    """Convert a parsed export into a populated :class:`Equipment` tree."""

    equipment = Equipment(
        token=parsed.header.location_token,
        description=parsed.header.location_description,
        language=parsed.header.language,
        export_timestamp=parsed.header.export_timestamp,
        structure_revision=_int(_first_nonblank(parsed.rows, "structureRevision")),
    )

    components_by_token: dict[str, Component] = {}
    functions_by_key: dict[tuple[str, str], Function] = {}
    failures_by_key: dict[tuple[int, str], FunctionalFailure] = {}
    failure_modes_by_token: dict[str, FailureMode] = {}
    activities_by_token: dict[str, Activity] = {}

    for row in parsed.rows:
        component = _ensure_component(row, equipment, components_by_token)
        function = _ensure_function(row, component, functions_by_key)
        if function is None:
            continue
        functional_failure = _ensure_failure(row, function, failures_by_key)
        if functional_failure is None:
            continue
        failure_mode = _ensure_failure_mode(row, functional_failure, failure_modes_by_token)
        if failure_mode is None:
            continue
        _ensure_activity(row, failure_mode, activities_by_token)

    if not equipment.make:
        equipment.make = _first_nonblank(parsed.rows, "locationMake")
    if not equipment.model:
        equipment.model = _first_nonblank(parsed.rows, "locationModel")
    return equipment


# --- Ensure-or-create helpers ---------------------------------------------------------


def _ensure_component(
    row: dict[str, Any],
    equipment: Equipment,
    seen: dict[str, Component],
) -> Component:
    token = _str(row["structureToken"])
    component = seen.get(token)
    if component is None:
        component = Component(
            token=token,
            description=_str(row["componentDescription"]),
            parent_description=_str(row["parentComponentDescription"]),
            make=_str(row.get("make", "")),
            model=_str(row.get("model", "")),
            comments=_str(row.get("comments", "")),
            sort_position=_int(row.get("sortPosition")),
            component_status=_str(row.get("componentStatus", "")),
            component_revision=_int(row.get("componentRevision")),
            structure_status=_str(row.get("structureStatus", "")),
            is_reference=_str(row.get("isReference", "")),
        )
        seen[token] = component
        equipment.components.append(component)
    return component


def _ensure_function(
    row: dict[str, Any],
    component: Component,
    seen: dict[tuple[str, str], Function],
) -> Function | None:
    text = _str(row["function"])
    if not text:
        return None
    key = (component.token, text)
    function = seen.get(key)
    if function is None:
        function = Function(
            description=text,
            function_category=_str(row.get("functionCategory", "")),
            function_type=_str(row.get("functionType", "")),
        )
        seen[key] = function
        component.functions.append(function)
    return function


def _ensure_failure(
    row: dict[str, Any],
    function: Function,
    seen: dict[tuple[int, str], FunctionalFailure],
) -> FunctionalFailure | None:
    text = _str(row["failure"])
    if not text:
        return None
    key = (id(function), text)
    failure = seen.get(key)
    if failure is None:
        failure = FunctionalFailure(description=text)
        seen[key] = failure
        function.failures.append(failure)
    return failure


def _ensure_failure_mode(
    row: dict[str, Any],
    failure: FunctionalFailure,
    seen: dict[str, FailureMode],
) -> FailureMode | None:
    token = _str(row.get("failureModeToken", ""))
    if not token:
        return None
    failure_mode = seen.get(token)
    if failure_mode is None:
        failure_mode = FailureMode(
            token=token,
            what=_str(row.get("what", "")),
            mechanism_and_cause=_str(row.get("mechanismAndCause", "")),
            strategy_type=_str(row.get("strategyType", "")),
            is_redundant=_yn(row.get("isRedundantYN")),
            eta=_float(row.get("eta")),
            beta=_float(row.get("beta")),
            gamma=_float(row.get("gamma")),
            eta_unit=_str(row.get("etaUnit", "")),
            notes=_str(row.get("notes", "")),
            allocation_type=_str(row.get("allocationType", "")),
            is_replacement=_yn(row.get("isReplacement")),
            is_dominant_replacement=_yn(row.get("isDominantReplacement")),
            custom_attributes=_collect_custom(row, S.FAILURE_MODE_CUSTOM_PREFIX),
        )
        seen[token] = failure_mode
        failure.failure_modes.append(failure_mode)
    return failure_mode


def _ensure_activity(
    row: dict[str, Any],
    failure_mode: FailureMode,
    seen: dict[str, Activity],
) -> Activity | None:
    token = _str(row.get("activityToken", ""))
    if not token:
        return None
    activity = seen.get(token)
    if activity is None:
        activity = Activity(
            token=token,
            description=_str(row.get("activityDescription", "")),
            activity_code=_str(row.get("activityCode", "")),
            activity_type=_str(row.get("activityType", "")),
            frequency=_float(row.get("frequency")),
            unit=_str(row.get("unit", "")),
            budget_type=_str(row.get("budgetType", "")),
            linked_activity_description=_str(row.get("linkedActivityDescription", "")),
            constraint=_str(row.get("constraint", "")),
            acceptable_limits=_str(row.get("acceptableLimits", "")),
            conditional_comments=_str(row.get("conditionalComments", "")),
            consequences=_str(row.get("consequences", "")),
            origin=_str(row.get("origin", "")),
            access_time_hours=_float(row.get("accessTimeHours")),
            unscheduled_overhead_hours=_float(row.get("unscheduledOverheadHours")),
            is_critical=_yn(row.get("criticalYN")),
            perform_tactic_review=_yn(row.get("tacticReviewPerformYN")),
            review_period_days=_int(row.get("tacticReviewPeriodDays")),
            task_colour=_str(row.get("taskColour", "")),
            labour=list(_iter_labour(row)),
            materials=list(_iter_materials(row)),
            costs=list(_iter_costs(row)),
        )
        seen[token] = activity
        failure_mode.activities.append(activity)
    return activity


# --- Slot iterators -------------------------------------------------------------------


def _iter_labour(row: dict[str, Any]):
    for slot in range(1, S.LABOUR_SLOTS + 1):
        desc = _str(row.get(f"labourDescription{slot}", ""))
        if not desc:
            continue
        yield ActivityLabour(
            description=desc,
            work_hours=_float(row.get(f"work{slot}")),
            required=_float(row.get(f"required{slot}")),
        )


def _iter_materials(row: dict[str, Any]):
    for slot in range(1, S.MATERIAL_SLOTS + 1):
        desc = _str(row.get(f"materialDescription{slot}", ""))
        if not desc:
            continue
        yield ActivityMaterial(
            description=desc,
            part_number=_str(row.get(f"materialPartNumber{slot}", "")),
            stock_code=_str(row.get(f"materialStockCode{slot}", "")),
            plant_code=_str(row.get(f"materialPlantCode{slot}", "")),
            quantity=_float(row.get(f"materialQuantity{slot}")),
        )


def _iter_costs(row: dict[str, Any]):
    for slot in range(1, S.COST_SLOTS + 1):
        desc = _str(row.get(f"costDescription{slot}", ""))
        if not desc:
            continue
        custom_prefix = S.COST_CUSTOM_PATTERN.format(slot=slot)
        yield ActivityCost(
            description=desc,
            cost_type=_str(row.get(f"costType{slot}", "")),
            expense_element=_str(row.get(f"expenseElement{slot}", "")),
            quantity=_float(row.get(f"quantity{slot}")),
            total_cost=_float(row.get(f"totalCost{slot}")),
            currency=_str(row.get(f"currency{slot}", "")),
            custom_attributes=_collect_custom(row, custom_prefix),
        )


# --- Coercion helpers -----------------------------------------------------------------


def _str(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    return str(value).strip()


def _int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value) if value.is_integer() else None
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def _float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    if isinstance(value, bool):
        return float(value)
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return None


def _yn(value: Any) -> bool:
    if value is None:
        return False
    return str(value).strip().upper() == "Y"


def _collect_custom(row: dict[str, Any], prefix: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for key, value in row.items():
        if not key.startswith(prefix):
            continue
        text = _str(value)
        if not text:
            continue
        out[key[len(prefix) :]] = text
    return out


def _first_nonblank(rows: list[dict[str, Any]], column: str) -> str:
    for row in rows:
        text = _str(row.get(column, ""))
        if text:
            return text
    return ""
