"""Frozen dataclasses for the ISO 14224 reference tables.

The five tables live in ``data/iso14224/`` as CSVs. They are immutable from the
application; any update is a new CSV plus a versioned reload. See
``data/iso14224/SCHEMA.md`` for column-level notes.
"""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Iso14224FailureMode:
    """ISO 14224 Table B.15 — observable failure mode (the "what failed")."""

    code: str
    description: str


@dataclass(frozen=True, slots=True)
class Iso14224FailureMechanism:
    """ISO 14224 Table B.2 — failure mechanism, hierarchical (main + sub)."""

    sub_code: str
    main_code: int
    main_category: str
    sub_name: str
    description: str

    @property
    def is_general(self) -> bool:
        return self.sub_name.casefold() == "general"


@dataclass(frozen=True, slots=True)
class Iso14224FailureCause:
    """ISO 14224 Table B.3 — root failure cause, hierarchical (main + sub)."""

    sub_code: str
    main_code: int
    main_category: str
    sub_name: str
    description: str

    @property
    def is_general(self) -> bool:
        return self.sub_name.casefold() == "general"


@dataclass(frozen=True, slots=True)
class Iso14224DetectionMethod:
    """ISO 14224 Table B.4 — how a failure was detected."""

    code_number: int
    method: str
    description: str
    examples: str


@dataclass(frozen=True, slots=True)
class Iso14224MaintenanceActivity:
    """ISO 14224 Table B.5 — maintenance activity taxonomy.

    ``use`` carries the corrective/preventative applicability flag from the CSV
    (``"C"``, ``"P"``, or ``"C, P"``). The redundant ``Corrective`` and
    ``Preventative`` columns in the source CSV are intentionally not loaded.
    """

    code_number: int
    activity: str
    description: str
    examples: str
    use: str

    @property
    def is_corrective(self) -> bool:
        return "C" in {token.strip() for token in self.use.split(",")}

    @property
    def is_preventative(self) -> bool:
        return "P" in {token.strip() for token in self.use.split(",")}
