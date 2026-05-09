"""Apply SME decisions through the persistence layer.

Verifies that the same review queue + decisions plumbed through repositories
produces real database rows on the alias / mapping / classification /
audit_log tables.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from orien_import_tool.aliases import Alias, AliasProposer
from orien_import_tool.domain.downtime import (
    ComponentMatch,
    DowntimeClassification,
    DowntimeEvent,
    FailureModeCandidate,
)
from orien_import_tool.domain.fmea import (
    Component,
    Equipment,
    FailureMode,
    Function,
    FunctionalFailure,
)
from orien_import_tool.iso14224 import load_all
from orien_import_tool.mapping import Proposer, propose_mappings
from orien_import_tool.persistence import (
    AliasRepository,
    AuditLogRepository,
    DowntimeRepository,
    EquipmentRepository,
    MappingRepository,
)
from orien_import_tool.review import (
    ReviewDecision,
    ReviewVerdict,
    apply_decisions,
    build_alias_review,
    build_classification_review,
    build_mapping_review,
)

# --- Equipment fixture (same as persistence tests) -------------------------------


@pytest.fixture
def equipment() -> Equipment:
    fm = FailureMode(
        token="fm-1",
        what="Bearing",
        mechanism_and_cause="Wears due to Mechanical overload",
    )
    return Equipment(
        token="eq-1",
        description="Test conveyor",
        components=[
            Component(
                token="c-1",
                description="Drive Motor",
                functions=[
                    Function(
                        description="Drive belt",
                        failures=[
                            FunctionalFailure(
                                description="Motor stops",
                                failure_modes=[fm],
                            )
                        ],
                    )
                ],
            )
        ],
    )


# --- Mapping decisions -----------------------------------------------------------


def test_accepted_mapping_decision_writes_sme_row(
    session: Session, equipment: Equipment, iso_dir: Path
) -> None:
    EquipmentRepository(session).upsert(equipment)
    ref = load_all(iso_dir)
    mapping_result = propose_mappings(equipment, ref)
    MappingRepository(session).add_all(mapping_result.mappings)
    session.commit()

    queue = build_mapping_review(mapping_result)
    if not queue.items:
        pytest.skip("no multi-candidate mappings to review for this fixture")

    item = queue.items[0]
    decision = ReviewDecision(item_id=item.item_id, verdict=ReviewVerdict.ACCEPTED)

    repo = MappingRepository(session)
    audit = AuditLogRepository(session)
    result = apply_decisions(
        [decision],
        queue,
        mapping_repository=repo,
        audit_log_repository=audit,
        sme_user="alice",
    )
    session.commit()

    assert result.mappings_recorded == 1
    assert result.audit_entries == 1

    # Look up the active mapping rows for this entity/dimension; both rule
    # and SME rows coexist (different proposer = different unique-key).
    rows = repo.for_entity(item.payload["source_entity_type"], item.payload["source_entity_id"])
    proposers = {m.proposer for m in rows if m.dimension.value == item.payload["dimension"]}
    assert Proposer.SME in proposers


def test_corrected_mapping_decision_uses_chosen_alternative(
    session: Session, equipment: Equipment, iso_dir: Path
) -> None:
    EquipmentRepository(session).upsert(equipment)
    ref = load_all(iso_dir)
    mapping_result = propose_mappings(equipment, ref)
    MappingRepository(session).add_all(mapping_result.mappings)
    session.commit()

    queue = build_mapping_review(mapping_result)
    if not queue.items:
        pytest.skip("no multi-candidate mappings to review for this fixture")
    item = queue.items[0]
    chosen = item.alternates[0]
    decision = ReviewDecision(
        item_id=item.item_id,
        verdict=ReviewVerdict.CORRECTED,
        chosen_alternative=chosen,
    )

    repo = MappingRepository(session)
    apply_decisions([decision], queue, mapping_repository=repo)
    session.commit()

    sme_rows = [
        m
        for m in repo.for_entity(
            item.payload["source_entity_type"], item.payload["source_entity_id"]
        )
        if m.proposer == Proposer.SME and m.dimension.value == item.payload["dimension"]
    ]
    assert len(sme_rows) == 1
    assert sme_rows[0].iso_code == chosen


def test_rejected_mapping_decision_writes_no_row_but_audits(
    session: Session, equipment: Equipment, iso_dir: Path
) -> None:
    EquipmentRepository(session).upsert(equipment)
    ref = load_all(iso_dir)
    mapping_result = propose_mappings(equipment, ref)
    MappingRepository(session).add_all(mapping_result.mappings)
    session.commit()

    queue = build_mapping_review(mapping_result)
    if not queue.items:
        pytest.skip("no multi-candidate mappings to review for this fixture")
    item = queue.items[0]
    decision = ReviewDecision(item_id=item.item_id, verdict=ReviewVerdict.REJECTED)

    audit = AuditLogRepository(session)
    repo = MappingRepository(session)
    result = apply_decisions([decision], queue, mapping_repository=repo, audit_log_repository=audit)
    session.commit()

    assert result.mappings_recorded == 0
    audit_rows = audit.for_entity("iso_mapping", item.item_id)
    assert len(audit_rows) == 1
    assert audit_rows[0].action == "iso_mapping.rejected"


# --- Alias decisions -------------------------------------------------------------


def test_accepted_alias_decision_writes_sme_row(session: Session) -> None:
    aliases = [
        Alias(
            alias_text="tripped",
            canonical_tokens=("stoppage", "stop"),
            proposer=AliasProposer.LLM,
            confidence=0.85,
        )
    ]
    queue = build_alias_review(aliases)
    decision = ReviewDecision(item_id=queue.items[0].item_id, verdict=ReviewVerdict.ACCEPTED)

    repo = AliasRepository(session)
    audit = AuditLogRepository(session)
    result = apply_decisions(
        [decision],
        queue,
        alias_repository=repo,
        audit_log_repository=audit,
        sme_user="bob",
    )
    session.commit()

    assert result.aliases_added == 1
    assert result.audit_entries == 1
    persisted = repo.all()
    assert any(a.alias_text == "tripped" and a.proposer == AliasProposer.SME for a in persisted)


def test_alias_decision_can_write_to_both_store_and_repo(session: Session) -> None:
    """Write-through: an in-memory store stays current alongside the DB."""
    from orien_import_tool.aliases import AliasStore

    aliases = [
        Alias(
            alias_text="faulty",
            canonical_tokens=("failure",),
            proposer=AliasProposer.LLM,
        )
    ]
    queue = build_alias_review(aliases)
    decision = ReviewDecision(item_id=queue.items[0].item_id, verdict=ReviewVerdict.ACCEPTED)

    store = AliasStore()
    repo = AliasRepository(session)
    apply_decisions([decision], queue, alias_store=store, alias_repository=repo)
    session.commit()

    assert any(a.proposer == AliasProposer.SME for a in store.get("faulty"))
    assert any(a.proposer == AliasProposer.SME for a in repo.all())


# --- Classification decisions ----------------------------------------------------


def test_accepted_classification_decision_writes_sme_row(session: Session) -> None:
    DowntimeRepository(session).upsert_events(
        [
            DowntimeEvent(
                external_id="e-1",
                asset_ref="conveyor",
                text="belt tripped",
                start_ts=datetime(2026, 4, 1),
            )
        ]
    )
    session.commit()

    classification = DowntimeClassification(
        event_external_id="e-1",
        component_match=ComponentMatch(
            component_token="c-1",
            component_description="Belt",
            score=0.9,
            matched_terms=("belt",),
        ),
        failure_mode_candidates=[
            FailureModeCandidate(
                failure_mode_token="fm-1",
                component_token="c-1",
                score=0.4,  # forces needs_review
                matched_terms=("belt",),
            )
        ],
    )
    event = DowntimeEvent(
        external_id="e-1",
        asset_ref="conveyor",
        text="belt tripped",
        start_ts=datetime(2026, 4, 1),
    )
    queue = build_classification_review([classification], events={"e-1": event})
    assert queue.items, "low-score classification should land in review"

    decision = ReviewDecision(item_id=queue.items[0].item_id, verdict=ReviewVerdict.ACCEPTED)
    repo = DowntimeRepository(session)
    audit = AuditLogRepository(session)
    result = apply_decisions(
        [decision], queue, downtime_repository=repo, audit_log_repository=audit
    )
    session.commit()

    assert result.classifications_recorded == 1
    persisted = repo.latest_classifications("e-1")
    sme_rows = [c for c in persisted if c.proposer == "sme"]
    assert len(sme_rows) == 1
    assert sme_rows[0].failure_mode_candidates[0].failure_mode_token == "fm-1"


def test_corrected_classification_uses_chosen_alternative(session: Session) -> None:
    DowntimeRepository(session).upsert_events(
        [
            DowntimeEvent(
                external_id="e-2",
                asset_ref="conveyor",
                text="something",
                start_ts=datetime(2026, 4, 1),
            )
        ]
    )
    session.commit()

    classification = DowntimeClassification(
        event_external_id="e-2",
        component_match=None,
        failure_mode_candidates=[
            FailureModeCandidate(
                failure_mode_token="fm-wrong",
                component_token="",
                score=0.2,
                matched_terms=(),
            )
        ],
    )
    event = DowntimeEvent(external_id="e-2", asset_ref="x", text="x")
    queue = build_classification_review([classification], events={"e-2": event})

    decision = ReviewDecision(
        item_id=queue.items[0].item_id,
        verdict=ReviewVerdict.CORRECTED,
        chosen_alternative="fm-correct",
    )
    repo = DowntimeRepository(session)
    apply_decisions([decision], queue, downtime_repository=repo)
    session.commit()

    sme_rows = [c for c in repo.latest_classifications("e-2") if c.proposer == "sme"]
    assert len(sme_rows) == 1
    assert sme_rows[0].failure_mode_candidates[0].failure_mode_token == "fm-correct"


# --- Audit log -------------------------------------------------------------------


def test_audit_log_records_each_decision(
    session: Session, equipment: Equipment, iso_dir: Path
) -> None:
    EquipmentRepository(session).upsert(equipment)
    ref = load_all(iso_dir)
    mapping_result = propose_mappings(equipment, ref)
    MappingRepository(session).add_all(mapping_result.mappings)
    session.commit()

    queue = build_mapping_review(mapping_result)
    if len(queue.items) < 2:
        pytest.skip("need at least two review items for this test")

    decisions = [
        ReviewDecision(
            item_id=queue.items[0].item_id,
            verdict=ReviewVerdict.ACCEPTED,
            sme_user="alice",
        ),
        ReviewDecision(
            item_id=queue.items[1].item_id,
            verdict=ReviewVerdict.REJECTED,
            sme_user="alice",
        ),
    ]
    audit = AuditLogRepository(session)
    apply_decisions(
        decisions,
        queue,
        mapping_repository=MappingRepository(session),
        audit_log_repository=audit,
    )
    session.commit()

    rows_a = audit.for_entity("iso_mapping", queue.items[0].item_id)
    rows_b = audit.for_entity("iso_mapping", queue.items[1].item_id)
    assert len(rows_a) == 1
    assert rows_a[0].action == "iso_mapping.accepted"
    assert len(rows_b) == 1
    assert rows_b[0].action == "iso_mapping.rejected"
    assert rows_a[0].actor == "alice"


# --- Skipped paths ---------------------------------------------------------------


def test_skipped_when_repository_omitted(
    session: Session, equipment: Equipment, iso_dir: Path
) -> None:
    """A write-style decision with no repo lands in 'skipped', not silently dropped."""
    EquipmentRepository(session).upsert(equipment)
    ref = load_all(iso_dir)
    mapping_result = propose_mappings(equipment, ref)
    queue = build_mapping_review(mapping_result)
    if not queue.items:
        pytest.skip("no review items for fixture")

    decision = ReviewDecision(item_id=queue.items[0].item_id, verdict=ReviewVerdict.ACCEPTED)
    audit = AuditLogRepository(session)
    result = apply_decisions([decision], queue, audit_log_repository=audit)
    session.commit()

    assert result.mappings_recorded == 0
    assert queue.items[0].item_id in result.skipped
    # Audit still fires — the skip itself is auditable.
    assert audit.for_entity("iso_mapping", queue.items[0].item_id)
