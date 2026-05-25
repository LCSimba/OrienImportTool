"""Build a :class:`ReviewQueue` from each proposer's output.

Each builder is independent — call as many or as few as relevant for the
SME's session — and :func:`build_unified_queue` composes them.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping

from orien_import_tool.aliases.models import Alias, AliasProposer
from orien_import_tool.domain.downtime import DowntimeClassification, DowntimeEvent
from orien_import_tool.mapping.models import (
    Iso14224Mapping,
    MappingResult,
)
from orien_import_tool.review.models import (
    ReviewItem,
    ReviewItemType,
    ReviewQueue,
)
from orien_import_tool.textnorm.abbreviations import Abbreviation, AbbrevProposer
from orien_import_tool.textnorm.miner import UnexpandableToken

# --- Mapping reviews -----------------------------------------------------------------


def build_mapping_review(result: MappingResult) -> ReviewQueue:
    """Convert the multi-candidate mappings flagged by needs_review() into ReviewItems.

    Each ReviewItem represents one ``(source_entity, dimension)`` cell — its
    primary candidate plus any alternates the proposer ranked behind it.
    """
    queue = ReviewQueue()
    for primary in result.needs_review():
        siblings = sorted(
            (
                m
                for m in result.mappings
                if m.source_entity_type == primary.source_entity_type
                and m.source_entity_id == primary.source_entity_id
                and m.dimension == primary.dimension
                and m.priority > 0
            ),
            key=lambda m: m.priority,
        )
        item_id = _mapping_item_id(primary)
        queue.items.append(
            ReviewItem(
                item_id=item_id,
                item_type=ReviewItemType.ISO_MAPPING,
                summary=(
                    f"{primary.source_entity_type} "
                    f"{_short_id(primary.source_entity_id)}: "
                    f"{primary.dimension.value}"
                ),
                detail=primary.rationale,
                primary_proposal=primary.iso_code,
                alternates=tuple(m.iso_code for m in siblings),
                confidence=primary.confidence,
                proposer=primary.proposer.value,
                payload={
                    "source_entity_type": primary.source_entity_type,
                    "source_entity_id": primary.source_entity_id,
                    "dimension": primary.dimension.value,
                },
            )
        )
    return queue


def _mapping_item_id(m: Iso14224Mapping) -> str:
    return f"map:{m.source_entity_type}:{m.source_entity_id}:{m.dimension.value}"


# --- Alias reviews -------------------------------------------------------------------


def build_alias_review(
    aliases: Iterable[Alias],
    *,
    examples: Mapping[str, list[str]] | None = None,
) -> ReviewQueue:
    """Convert LLM-proposed aliases into ReviewItems for SME accept/reject.

    Rule-seeded and SME-confirmed aliases are skipped — only LLM proposals
    need review. Re-running over already-accepted SME aliases would re-queue
    settled work. ``examples`` optionally maps ``alias_text`` to a few original
    downtime snippets where the term appears, for reviewer context.
    """
    queue = ReviewQueue()
    for alias in aliases:
        if alias.proposer != AliasProposer.LLM:
            continue
        item_id = _alias_item_id(alias)
        queue.items.append(
            ReviewItem(
                item_id=item_id,
                item_type=ReviewItemType.ALIAS,
                summary=f"alias '{alias.alias_text}' -> {list(alias.canonical_tokens)}",
                detail=alias.rationale,
                primary_proposal=" ".join(alias.canonical_tokens),
                alternates=(),
                confidence=alias.confidence,
                proposer=alias.proposer.value,
                payload={
                    "alias_text": alias.alias_text,
                    "canonical_tokens": list(alias.canonical_tokens),
                    "scope_equipment_token": alias.scope_equipment_token,
                    "iso_hint": alias.iso_hint,
                    "rationale": alias.rationale,
                    "examples": list((examples or {}).get(alias.alias_text, [])),
                },
            )
        )
    return queue


def _alias_item_id(alias: Alias) -> str:
    tokens = ",".join(sorted(alias.canonical_tokens))
    scope = alias.scope_equipment_token or "global"
    return f"alias:{alias.alias_text}:{tokens}:{scope}"


# --- Abbreviation reviews ------------------------------------------------------------


def build_abbreviation_review(
    abbreviations: Iterable[Abbreviation],
    *,
    examples: Mapping[str, list[str]] | None = None,
) -> ReviewQueue:
    """Convert LLM-proposed abbreviations into ReviewItems for SME accept/reject.

    Rule-seeded and SME-confirmed abbreviations are skipped — only LLM
    proposals need review. ``examples`` optionally maps ``short`` to a few
    original downtime snippets where the token appears, for reviewer context.
    """
    queue = ReviewQueue()
    for abbrev in abbreviations:
        if abbrev.proposer != AbbrevProposer.LLM:
            continue
        queue.items.append(
            ReviewItem(
                item_id=f"abbr:{abbrev.short}:{abbrev.expansion}",
                item_type=ReviewItemType.ABBREVIATION,
                summary=f"abbreviation '{abbrev.short}' -> '{abbrev.expansion}'",
                detail=abbrev.rationale,
                primary_proposal=abbrev.expansion,
                alternates=(),
                confidence=abbrev.confidence,
                proposer=abbrev.proposer.value,
                payload={
                    "short": abbrev.short,
                    "expansion": abbrev.expansion,
                    "rationale": abbrev.rationale,
                    "group": abbrev.group,
                    "examples": list((examples or {}).get(abbrev.short, [])),
                },
            )
        )
    return queue


def build_unexpandable_review(
    tokens: Iterable[UnexpandableToken],
    *,
    examples: Mapping[str, list[str]] | None = None,
) -> ReviewQueue:
    """Surface tokens the miner deliberately left unexpanded for SME review.

    These are the product names / equipment codes / proper nouns the model
    flagged as *not* abbreviations. Accepting confirms "correctly left as-is";
    correcting (supplying an expansion) rescues a wrongly-skipped abbreviation.
    Grouped via the same family label as the expandable proposals. ``examples``
    optionally maps ``short`` to original downtime snippets, for context.
    """
    queue = ReviewQueue()
    for token in tokens:
        queue.items.append(
            ReviewItem(
                item_id=f"unknown:{token.short}",
                item_type=ReviewItemType.UNKNOWN_TOKEN,
                summary=f"unknown token '{token.short}' — left unexpanded",
                detail=token.rationale,
                primary_proposal="",
                alternates=(),
                confidence=token.confidence,
                proposer=AbbrevProposer.LLM.value,
                payload={
                    "short": token.short,
                    "rationale": token.rationale,
                    "group": token.group,
                    "examples": list((examples or {}).get(token.short, [])),
                },
            )
        )
    return queue


# --- Classification reviews ----------------------------------------------------------


def build_classification_review(
    classifications: Iterable[DowntimeClassification],
    events: Mapping[str, DowntimeEvent] | None = None,
) -> ReviewQueue:
    """Convert needs_review classifications into ReviewItems.

    ``events`` is optional but recommended — without it, the ReviewItem
    detail won't carry the original event text.
    """
    queue = ReviewQueue()
    events = events or {}
    for classification in classifications:
        if not classification.needs_review:
            continue
        primary = classification.best_failure_mode
        event = events.get(classification.event_external_id)
        item_id = f"class:{classification.event_external_id}"
        queue.items.append(
            ReviewItem(
                item_id=item_id,
                item_type=ReviewItemType.CLASSIFICATION,
                summary=(
                    f"event {classification.event_external_id}: "
                    f"{(event.text[:70] if event else '(no text)')}"
                ),
                detail=event.text if event else "",
                primary_proposal=(
                    _short_id(primary.failure_mode_token) if primary else "no candidate"
                ),
                alternates=tuple(
                    _short_id(c.failure_mode_token)
                    for c in classification.failure_mode_candidates[1:]
                ),
                confidence=primary.score if primary else 0.0,
                proposer=classification.proposer,
                payload={
                    "event_external_id": classification.event_external_id,
                    "asset_ref": event.asset_ref if event else "",
                    "component_token": (
                        classification.component_match.component_token
                        if classification.component_match
                        else ""
                    ),
                    "candidate_tokens": [
                        c.failure_mode_token for c in classification.failure_mode_candidates
                    ],
                },
            )
        )
    return queue


# --- Composite -----------------------------------------------------------------------


def build_unified_queue(
    *,
    mapping_result: MappingResult | None = None,
    aliases: Iterable[Alias] | None = None,
    classifications: Iterable[DowntimeClassification] | None = None,
    events: Mapping[str, DowntimeEvent] | None = None,
) -> ReviewQueue:
    """Build one :class:`ReviewQueue` containing every relevant pending item."""
    queue = ReviewQueue()
    if mapping_result is not None:
        queue.extend(build_mapping_review(mapping_result).items)
    if aliases is not None:
        queue.extend(build_alias_review(aliases).items)
    if classifications is not None:
        queue.extend(build_classification_review(classifications, events).items)
    return queue


# --- Helpers -------------------------------------------------------------------------


def _short_id(text: str, max_len: int = 24) -> str:
    if len(text) <= max_len:
        return text
    return text[: max_len - 1] + "…"
