"""Canonical domain model for FMEA + tactics + activity hierarchy.

Mirrors the structure described in ``docs/data-model.md``. The model is
storage-agnostic: it is a pure-Python tree that the parser populates and
downstream code (mapping, persistence, classification) consumes.

ISO 14224 mappings live in a separate ``mapping`` module (Chunk 3); they
attach to entities by reference, not as fields here, so the model stays
free of that dependency.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class Equipment:
    """Top-level asset (the Orien `location`)."""

    token: str
    description: str
    make: str = ""
    model: str = ""
    structure_revision: int | None = None
    language: str = "en"
    export_timestamp: datetime | None = None
    components: list[Component] = field(default_factory=list)


@dataclass
class Component:
    """A node in the equipment hierarchy.

    ``parent_description`` mirrors the Orien export's
    ``parentComponentDescription``; an empty string means top-level (direct
    child of :class:`Equipment`).
    """

    token: str
    description: str
    parent_description: str = ""
    make: str = ""
    model: str = ""
    comments: str = ""
    sort_position: int | None = None
    component_status: str = ""
    component_revision: int | None = None
    structure_status: str = ""
    is_reference: str = ""
    functions: list[Function] = field(default_factory=list)


@dataclass
class Function:
    """One function of a :class:`Component`."""

    description: str
    function_category: str = ""
    function_type: str = ""
    failures: list[FunctionalFailure] = field(default_factory=list)


@dataclass
class FunctionalFailure:
    """One way a :class:`Function` can fail."""

    description: str
    failure_modes: list[FailureMode] = field(default_factory=list)


@dataclass
class FailureMode:
    """Specific cause path for a :class:`FunctionalFailure`.

    The raw ``mechanism_and_cause`` string is preserved verbatim; the rule
    proposer (Chunk 3) decomposes it into B15 mode + B2 mechanism + B3 cause.
    """

    token: str
    what: str = ""
    mechanism_and_cause: str = ""
    strategy_type: str = ""
    is_redundant: bool = False
    eta: float | None = None
    beta: float | None = None
    gamma: float | None = None
    eta_unit: str = ""
    notes: str = ""
    allocation_type: str = ""
    is_replacement: bool = False
    is_dominant_replacement: bool = False
    custom_attributes: dict[str, str] = field(default_factory=dict)
    activities: list[Activity] = field(default_factory=list)


@dataclass
class Activity:
    """Maintenance activity addressing a :class:`FailureMode`.

    Maps to ISO 14224 B5 (always — see ``data/iso14224/SCHEMA.md``).
    """

    token: str
    description: str
    activity_code: str = ""
    activity_type: str = ""
    frequency: float | None = None
    unit: str = ""
    budget_type: str = ""
    linked_activity_description: str = ""
    constraint: str = ""
    acceptable_limits: str = ""
    conditional_comments: str = ""
    consequences: str = ""
    origin: str = ""
    access_time_hours: float | None = None
    unscheduled_overhead_hours: float | None = None
    is_critical: bool = False
    perform_tactic_review: bool = False
    review_period_days: int | None = None
    task_colour: str = ""
    labour: list[ActivityLabour] = field(default_factory=list)
    materials: list[ActivityMaterial] = field(default_factory=list)
    costs: list[ActivityCost] = field(default_factory=list)


@dataclass
class ActivityLabour:
    """One labour line on an :class:`Activity` (Orien supports up to 5 slots)."""

    description: str
    work_hours: float | None = None
    required: float | None = None


@dataclass
class ActivityMaterial:
    """One material line on an :class:`Activity` (up to 5 slots)."""

    description: str
    part_number: str = ""
    stock_code: str = ""
    plant_code: str = ""
    quantity: float | None = None


@dataclass
class ActivityCost:
    """One cost line on an :class:`Activity` (up to 5 slots)."""

    description: str
    cost_type: str = ""
    expense_element: str = ""
    quantity: float | None = None
    total_cost: float | None = None
    currency: str = ""
    custom_attributes: dict[str, str] = field(default_factory=dict)
