"""Apply :class:`ReviewDecision` rows back to the relevant stores.

For now only the alias path is wired — :class:`AliasStore` is the only
mutable store in the system. Mapping and classification stores need
persistence first; their decisions are recorded in the :class:`ApplyResult`
so the SME's work isn't lost, and they'll be replayed when the persistence
chunk lands.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field

from orien_import_tool.aliases.models import Alias, AliasProposer
from orien_import_tool.aliases.store import AliasStore
from orien_import_tool.review.models import (
    ReviewItemType,
    ReviewQueue,
    ReviewVerdict,
)


@dataclass
class ApplyResult:
    """Outcome of applying a decision batch back to the system stores."""

    aliases_added: int = 0
    aliases_rejected: int = 0
    mapping_decisions_recorded: int = 0
    classification_decisions_recorded: int = 0
    skipped: list[str] = field(default_factory=list)


def apply_decisions(
    decisions: Iterable,
    queue: ReviewQueue,
    *,
    alias_store: AliasStore | None = None,
) -> ApplyResult:
    """Apply each decision to the matching item.

    Decisions whose item is missing from the queue are recorded under
    ``skipped`` rather than raising, so a stale CSV doesn't fail the whole
    batch. Mapping and classification decisions are counted but not yet
    written anywhere — that requires the persistence chunk.
    """
    result = ApplyResult()
    for decision in decisions:
        item = queue.get(decision.item_id)
        if item is None:
            result.skipped.append(decision.item_id)
            continue

        if item.item_type == ReviewItemType.ALIAS:
            _apply_alias_decision(decision, item, alias_store, result)
        elif item.item_type == ReviewItemType.ISO_MAPPING:
            result.mapping_decisions_recorded += 1
        elif item.item_type == ReviewItemType.CLASSIFICATION:
            result.classification_decisions_recorded += 1
    return result


def _apply_alias_decision(
    decision,
    item,
    alias_store: AliasStore | None,
    result: ApplyResult,
) -> None:
    if decision.verdict == ReviewVerdict.REJECTED:
        result.aliases_rejected += 1
        return
    if decision.verdict not in (ReviewVerdict.ACCEPTED, ReviewVerdict.CORRECTED):
        return
    if alias_store is None:
        result.skipped.append(item.item_id)
        return

    payload = item.payload
    canonical_tokens = tuple(payload.get("canonical_tokens", ()))
    # If the SME corrected the alias, replace the canonical tokens with the
    # space-separated value from chosen_alternative.
    if decision.verdict == ReviewVerdict.CORRECTED and decision.chosen_alternative:
        canonical_tokens = tuple(decision.chosen_alternative.split())

    if not canonical_tokens:
        result.skipped.append(item.item_id)
        return

    alias_store.add(
        Alias(
            alias_text=str(payload.get("alias_text", "")),
            canonical_tokens=canonical_tokens,
            proposer=AliasProposer.SME,
            confidence=1.0,
            scope_equipment_token=payload.get("scope_equipment_token"),
            iso_hint=str(payload.get("iso_hint", "")),
            rationale=decision.note or "Confirmed by SME review",
        )
    )
    result.aliases_added += 1
