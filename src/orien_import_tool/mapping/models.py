"""Polymorphic Iso14224Mapping — links Orien entities to ISO 14224 codes.

A single Orien :class:`FailureMode` typically yields up to 5 mapping rows:
1 MODE (B15) + N MECHANISM rows (B2 multi-tag) + M CAUSE rows (B3 multi-tag).
An Orien :class:`Activity` yields exactly 1 MAINTENANCE_ACTIVITY row (B5,
including extensions).

The polymorphism is captured by ``dimension``: each value selects which ISO
table ``iso_code`` indexes into.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class MappingDimension(StrEnum):
    """Which ISO 14224 table the ``iso_code`` belongs to."""

    MODE = "MODE"  # B.15 Failure mode descriptions
    MECHANISM = "MECHANISM"  # B.2 Failure mechanisms
    CAUSE = "CAUSE"  # B.3 Failure causes
    DETECTION_METHOD = "DETECTION_METHOD"  # B.4
    MAINTENANCE_ACTIVITY = "MAINTENANCE_ACTIVITY"  # B.5


class Proposer(StrEnum):
    """Where the mapping came from."""

    RULE = "rule"
    LLM = "llm"
    SME = "sme"


@dataclass(frozen=True, slots=True)
class Iso14224Mapping:
    """One mapping row.

    ``priority`` orders candidates within the same ``(source, dimension)``: 0 is
    the primary suggestion, 1+ are alternates the SME can pick instead. Multi-
    candidate B3 mappings carry priority 0..2; single-candidate mappings always
    have priority 0.
    """

    source_entity_type: str  # "FailureMode" | "Activity" | "DetectionMethod"
    source_entity_id: str  # token from the canonical model
    dimension: MappingDimension
    iso_code: str  # B15 code / B2 sub_code / B3 sub_code / B4-B5 code_number-as-str
    proposer: Proposer
    confidence: float  # 0..1
    rationale: str = ""
    priority: int = 0
    iso_table_version: str = "v1"  # placeholder; hash-based version comes with persistence


@dataclass
class MappingResult:
    """Proposer output for one Equipment, plus convenience accessors."""

    equipment_token: str
    mappings: list[Iso14224Mapping] = field(default_factory=list)

    def for_entity(
        self,
        source_entity_type: str,
        source_entity_id: str,
    ) -> list[Iso14224Mapping]:
        return [
            m
            for m in self.mappings
            if m.source_entity_type == source_entity_type and m.source_entity_id == source_entity_id
        ]

    def for_dimension(self, dimension: MappingDimension) -> list[Iso14224Mapping]:
        return [m for m in self.mappings if m.dimension == dimension]

    def needs_review(self) -> list[Iso14224Mapping]:
        """Primary mappings that have one or more alternates (i.e. SME must pick).

        A row is in the review queue if any sibling row exists at the same
        ``(source, dimension)`` with priority > 0.
        """
        keys_with_alternates: set[tuple[str, str, MappingDimension]] = set()
        for m in self.mappings:
            if m.priority > 0:
                keys_with_alternates.add((m.source_entity_type, m.source_entity_id, m.dimension))
        return [
            m
            for m in self.mappings
            if m.priority == 0
            and (m.source_entity_type, m.source_entity_id, m.dimension) in keys_with_alternates
        ]

    def coverage(self) -> dict[str, int]:
        from collections import Counter

        per_dim: Counter[MappingDimension] = Counter(m.dimension for m in self.mappings)
        return {d.value: per_dim[d] for d in MappingDimension}
