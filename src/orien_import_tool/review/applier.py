"""Apply :class:`ReviewDecision` rows back to the relevant stores.

Each decision dispatches by ``item_type``:

* ``alias`` — accepted/corrected aliases land in the supplied
  :class:`AliasStore` (in-memory, for runtime use without a DB) and/or
  :class:`AliasRepository` (persistent). Rejected aliases are counted but
  not written.
* ``iso_mapping`` — accepted/corrected mapping decisions insert a fresh
  ``proposer=sme`` row into :class:`MappingRepository`. Both rule/llm and
  sme rows coexist (different proposer is part of the unique key); reads
  that want a single answer pick by precedence (SME > LLM > rule).
* ``classification`` — accepted/corrected classification decisions append
  a new ``proposer=sme`` :class:`DowntimeClassification` to
  :class:`DowntimeRepository`.
* every decision (regardless of type or verdict) appends to
  :class:`AuditLogRepository` if supplied — this is the canonical
  who-did-what-when record.

If the relevant repository is not supplied for a given item type, the
decision lands in :attr:`ApplyResult.skipped` so the caller can detect
under-wired pipelines without losing data silently.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from orien_import_tool.aliases.models import Alias, AliasProposer
from orien_import_tool.aliases.store import AliasStore
from orien_import_tool.domain.downtime import (
    ComponentMatch,
    DowntimeClassification,
    FailureModeCandidate,
)
from orien_import_tool.mapping.models import (
    Iso14224Mapping,
    MappingDimension,
    Proposer,
)
from orien_import_tool.review.models import (
    ReviewItem,
    ReviewItemType,
    ReviewQueue,
    ReviewVerdict,
)
from orien_import_tool.textnorm.abbreviations import (
    Abbreviation,
    AbbreviationStore,
    AbbrevProposer,
)

if TYPE_CHECKING:
    from orien_import_tool.persistence.repositories import (
        AbbreviationRepository,
        AliasRepository,
        AuditLogRepository,
        DowntimeRepository,
        MappingRepository,
    )
    from orien_import_tool.review.models import ReviewDecision


@dataclass
class ApplyResult:
    """Outcome of applying a decision batch.

    Each counter records *actual writes* — items that fell through to
    ``skipped`` are not counted. Audit log entries are independent: every
    decision tries to log, regardless of whether the typed write succeeded.
    """

    aliases_added: int = 0
    aliases_rejected: int = 0
    mappings_recorded: int = 0
    classifications_recorded: int = 0
    abbreviations_added: int = 0
    abbreviations_rejected: int = 0
    audit_entries: int = 0
    skipped: list[str] = field(default_factory=list)


def apply_decisions(
    decisions: Iterable[ReviewDecision],
    queue: ReviewQueue,
    *,
    alias_store: AliasStore | None = None,
    alias_repository: AliasRepository | None = None,
    mapping_repository: MappingRepository | None = None,
    downtime_repository: DowntimeRepository | None = None,
    abbreviation_store: AbbreviationStore | None = None,
    abbreviation_repository: AbbreviationRepository | None = None,
    audit_log_repository: AuditLogRepository | None = None,
    sme_user: str = "",
) -> ApplyResult:
    """Apply each decision to the matching item, recording an audit entry."""
    result = ApplyResult()
    for decision in decisions:
        item = queue.get(decision.item_id)
        if item is None:
            result.skipped.append(decision.item_id)
            continue

        if item.item_type == ReviewItemType.ALIAS:
            _apply_alias(decision, item, alias_store, alias_repository, result)
        elif item.item_type == ReviewItemType.ISO_MAPPING:
            _apply_mapping(decision, item, mapping_repository, result)
        elif item.item_type == ReviewItemType.CLASSIFICATION:
            _apply_classification(decision, item, downtime_repository, result)
        elif item.item_type == ReviewItemType.ABBREVIATION:
            _apply_abbreviation(decision, item, abbreviation_store, abbreviation_repository, result)

        if audit_log_repository is not None:
            _audit(audit_log_repository, decision, item, sme_user)
            result.audit_entries += 1
    return result


# --- Alias --------------------------------------------------------------------------


def _apply_alias(
    decision: ReviewDecision,
    item: ReviewItem,
    alias_store: AliasStore | None,
    alias_repository: AliasRepository | None,
    result: ApplyResult,
) -> None:
    if decision.verdict == ReviewVerdict.REJECTED:
        result.aliases_rejected += 1
        return
    if decision.verdict not in (ReviewVerdict.ACCEPTED, ReviewVerdict.CORRECTED):
        return
    if alias_store is None and alias_repository is None:
        result.skipped.append(item.item_id)
        return

    payload = item.payload
    canonical_tokens = tuple(payload.get("canonical_tokens", ()))
    if decision.verdict == ReviewVerdict.CORRECTED and decision.chosen_alternative:
        canonical_tokens = tuple(decision.chosen_alternative.split())
    if not canonical_tokens:
        result.skipped.append(item.item_id)
        return

    sme_alias = Alias(
        alias_text=str(payload.get("alias_text", "")),
        canonical_tokens=canonical_tokens,
        proposer=AliasProposer.SME,
        confidence=1.0,
        scope_equipment_token=payload.get("scope_equipment_token"),
        iso_hint=str(payload.get("iso_hint", "")),
        rationale=decision.note or "Confirmed by SME review",
    )

    if alias_store is not None:
        alias_store.add(sme_alias)
    if alias_repository is not None:
        alias_repository.add(sme_alias)
    result.aliases_added += 1


# --- Abbreviation -------------------------------------------------------------------


def _apply_abbreviation(
    decision: ReviewDecision,
    item: ReviewItem,
    abbreviation_store: AbbreviationStore | None,
    abbreviation_repository: AbbreviationRepository | None,
    result: ApplyResult,
) -> None:
    if decision.verdict == ReviewVerdict.REJECTED:
        result.abbreviations_rejected += 1
        return
    if decision.verdict not in (ReviewVerdict.ACCEPTED, ReviewVerdict.CORRECTED):
        return
    if abbreviation_store is None and abbreviation_repository is None:
        result.skipped.append(item.item_id)
        return

    payload = item.payload
    expansion = str(payload.get("expansion", ""))
    if decision.verdict == ReviewVerdict.CORRECTED and decision.chosen_alternative:
        expansion = decision.chosen_alternative
    short = str(payload.get("short", ""))
    if not short or not expansion:
        result.skipped.append(item.item_id)
        return

    sme_abbrev = Abbreviation(
        short=short,
        expansion=expansion,
        proposer=AbbrevProposer.SME,
        confidence=1.0,
        rationale=decision.note or "Confirmed by SME review",
    )
    if abbreviation_store is not None:
        abbreviation_store.add(sme_abbrev)
    if abbreviation_repository is not None:
        abbreviation_repository.add(sme_abbrev)
    result.abbreviations_added += 1


# --- Mapping ------------------------------------------------------------------------


def _apply_mapping(
    decision: ReviewDecision,
    item: ReviewItem,
    repository: MappingRepository | None,
    result: ApplyResult,
) -> None:
    if decision.verdict == ReviewVerdict.REJECTED:
        return  # nothing to write; the audit entry is the record
    if decision.verdict not in (ReviewVerdict.ACCEPTED, ReviewVerdict.CORRECTED):
        return
    if repository is None:
        result.skipped.append(item.item_id)
        return

    iso_code = (
        item.primary_proposal
        if decision.verdict == ReviewVerdict.ACCEPTED
        else decision.chosen_alternative
    )
    if not iso_code:
        result.skipped.append(item.item_id)
        return

    payload = item.payload
    sme_mapping = Iso14224Mapping(
        source_entity_type=payload["source_entity_type"],
        source_entity_id=payload["source_entity_id"],
        dimension=MappingDimension(payload["dimension"]),
        iso_code=iso_code,
        proposer=Proposer.SME,
        confidence=1.0,
        rationale=decision.note or "Confirmed by SME review",
        priority=0,
    )
    added = repository.add_all([sme_mapping])
    result.mappings_recorded += added


# --- Classification -----------------------------------------------------------------


def _apply_classification(
    decision: ReviewDecision,
    item: ReviewItem,
    repository: DowntimeRepository | None,
    result: ApplyResult,
) -> None:
    if decision.verdict == ReviewVerdict.REJECTED:
        return
    if decision.verdict not in (ReviewVerdict.ACCEPTED, ReviewVerdict.CORRECTED):
        return
    if repository is None:
        result.skipped.append(item.item_id)
        return

    payload = item.payload
    candidate_tokens = payload.get("candidate_tokens", []) or []
    if decision.verdict == ReviewVerdict.ACCEPTED:
        chosen_fm = candidate_tokens[0] if candidate_tokens else ""
    else:
        chosen_fm = decision.chosen_alternative
    if not chosen_fm:
        result.skipped.append(item.item_id)
        return

    component_token = payload.get("component_token") or ""
    component_match = (
        ComponentMatch(
            component_token=component_token,
            component_description="",
            score=1.0,
            matched_terms=(),
        )
        if component_token
        else None
    )
    classification = DowntimeClassification(
        event_external_id=payload["event_external_id"],
        component_match=component_match,
        failure_mode_candidates=[
            FailureModeCandidate(
                failure_mode_token=chosen_fm,
                component_token=component_token,
                score=1.0,
                matched_terms=(),
                rationale=decision.note or "Confirmed by SME review",
            )
        ],
        proposer="sme",
        notes=decision.note,
    )
    repository.add_classifications([classification], model_run_id="sme-review")
    result.classifications_recorded += 1


# --- Audit log ----------------------------------------------------------------------


def _audit(
    repository: AuditLogRepository,
    decision: ReviewDecision,
    item: ReviewItem,
    sme_user: str,
) -> None:
    repository.append(
        actor=sme_user or decision.sme_user or "",
        action=f"{item.item_type.value}.{decision.verdict.value}",
        entity_type=item.item_type.value,
        entity_id=item.item_id,
        payload={
            "verdict": decision.verdict.value,
            "chosen_alternative": decision.chosen_alternative,
            "primary_proposal": item.primary_proposal,
        },
        note=decision.note,
    )
