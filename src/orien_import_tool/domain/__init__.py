"""Canonical domain model — equipment, FMEA, activities, downtime."""

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

__all__ = [
    "Activity",
    "ActivityCost",
    "ActivityLabour",
    "ActivityMaterial",
    "Component",
    "ComponentMatch",
    "DowntimeClassification",
    "DowntimeEvent",
    "Equipment",
    "FailureMode",
    "FailureModeCandidate",
    "Function",
    "FunctionalFailure",
]
