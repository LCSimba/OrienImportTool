"""Domain types for the SME review queue."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum


class ReviewItemType(StrEnum):
    """What kind of artefact this row represents."""

    ISO_MAPPING = "iso_mapping"
    ALIAS = "alias"
    CLASSIFICATION = "classification"
    ABBREVIATION = "abbreviation"
    UNKNOWN_TOKEN = "unknown_token"


class ReviewVerdict(StrEnum):
    """SME's decision on an item."""

    PENDING = "pending"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    CORRECTED = "corrected"


@dataclass(frozen=True, slots=True)
class ReviewItem:
    """One reviewable artefact, ready for SME inspection.

    ``payload`` carries enough context to apply the SME's decision back to the
    original store (e.g. an :class:`Alias` for alias decisions, the
    ``source_entity`` reference for mapping decisions).
    """

    item_id: str
    item_type: ReviewItemType
    summary: str
    detail: str
    primary_proposal: str
    alternates: tuple[str, ...]
    confidence: float
    proposer: str
    payload: dict = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ReviewDecision:
    """One SME decision applied to a :class:`ReviewItem`."""

    item_id: str
    verdict: ReviewVerdict
    chosen_alternative: str = ""
    note: str = ""
    sme_user: str = ""
    decided_at: datetime | None = None


@dataclass
class ReviewQueue:
    """An ordered list of pending :class:`ReviewItem` rows."""

    items: list[ReviewItem] = field(default_factory=list)

    def __len__(self) -> int:
        return len(self.items)

    def __iter__(self):
        return iter(self.items)

    def by_type(self, item_type: ReviewItemType) -> list[ReviewItem]:
        return [i for i in self.items if i.item_type == item_type]

    def get(self, item_id: str) -> ReviewItem | None:
        return next((i for i in self.items if i.item_id == item_id), None)

    def extend(self, items: list[ReviewItem]) -> None:
        self.items.extend(items)
