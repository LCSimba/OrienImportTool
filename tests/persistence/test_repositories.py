"""Repository tests — round-trip every aggregate through SQLite."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from orien_import_tool.aliases import Alias, AliasProposer
from orien_import_tool.domain.downtime import (
    ComponentMatch,
    DowntimeClassification,
    DowntimeEvent,
    FailureModeCandidate,
)
from orien_import_tool.domain.fmea import (
    Activity,
    ActivityLabour,
    Component,
    Equipment,
    FailureMode,
    Function,
    FunctionalFailure,
)
from orien_import_tool.iso14224 import load_all
from orien_import_tool.mapping import (
    Iso14224Mapping,
    MappingDimension,
    Proposer,
    propose_mappings,
)
from orien_import_tool.persistence import (
    AliasRepository,
    AuditLogRepository,
    DowntimeRepository,
    EquipmentRepository,
    MappingRepository,
)
from orien_import_tool.persistence.models import AliasRow, Iso14224MappingRow

# --- Equipment -------------------------------------------------------------------


@pytest.fixture
def equipment() -> Equipment:
    fm = FailureMode(
        token="fm-1",
        what="Bearing",
        mechanism_and_cause="Wears due to Mechanical overload",
        activities=[
            Activity(
                token="a-1",
                description="Inspect bearing",
                activity_code="Inspection",
                labour=[ActivityLabour(description="Mechanical fitter", work_hours=2.0)],
            )
        ],
    )
    return Equipment(
        token="eq-1",
        description="Test conveyor",
        components=[
            Component(
                token="c-1",
                description="Drive Motor",
                make="ACME",
                model="DM-100",
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


def test_equipment_round_trip(session: Session, equipment: Equipment) -> None:
    repo = EquipmentRepository(session)
    repo.upsert(equipment, file_hash="sha256:abc")
    session.commit()
    loaded = repo.get("eq-1")
    assert loaded is not None
    assert loaded.token == "eq-1"
    assert loaded.description == "Test conveyor"
    assert len(loaded.components) == 1
    component = loaded.components[0]
    assert component.token == "c-1"
    assert component.make == "ACME"
    assert len(component.functions) == 1
    assert component.functions[0].description == "Drive belt"
    fm = component.functions[0].failures[0].failure_modes[0]
    assert fm.mechanism_and_cause == "Wears due to Mechanical overload"
    assert len(fm.activities) == 1
    assert fm.activities[0].activity_code == "Inspection"
    # Sub-dataclass rehydration — labour entry must be ActivityLabour, not dict.
    assert isinstance(fm.activities[0].labour[0], ActivityLabour)
    assert fm.activities[0].labour[0].work_hours == 2.0


def test_equipment_upsert_replaces_components(session: Session, equipment: Equipment) -> None:
    repo = EquipmentRepository(session)
    repo.upsert(equipment)
    session.commit()

    # Re-import a smaller version of the same equipment.
    smaller = Equipment(token="eq-1", description="Slimmed", components=[])
    repo.upsert(smaller)
    session.commit()

    loaded = repo.get("eq-1")
    assert loaded.description == "Slimmed"
    assert loaded.components == []


def test_equipment_get_unknown_returns_none(session: Session) -> None:
    repo = EquipmentRepository(session)
    assert repo.get("missing") is None


def test_equipment_list(session: Session, equipment: Equipment) -> None:
    repo = EquipmentRepository(session)
    repo.upsert(equipment)
    other = Equipment(token="eq-2", description="Other", components=[])
    repo.upsert(other)
    session.commit()
    tokens = {e.token for e in repo.list()}
    assert tokens == {"eq-1", "eq-2"}


# --- Mapping --------------------------------------------------------------------


def test_mapping_repo_roundtrips_real_proposer_output(
    session: Session, equipment: Equipment, iso_dir: Path
) -> None:
    ref = load_all(iso_dir)
    result = propose_mappings(equipment, ref)
    repo = MappingRepository(session)
    added = repo.add_all(result.mappings)
    session.commit()
    assert added == len(result.mappings)
    loaded = repo.for_entity("FailureMode", "fm-1")
    expected = {
        m.dimension
        for m in result.mappings
        if m.source_entity_type == "FailureMode" and m.source_entity_id == "fm-1"
    }
    assert {m.dimension for m in loaded} == expected


def test_mapping_repo_dedupes_on_unique_key(session: Session) -> None:
    repo = MappingRepository(session)
    m = Iso14224Mapping(
        source_entity_type="FailureMode",
        source_entity_id="fm-1",
        dimension=MappingDimension.MODE,
        iso_code="Worn",
        proposer=Proposer.RULE,
        confidence=0.9,
    )
    assert repo.add_all([m]) == 1
    session.commit()
    # Adding the identical row again is a no-op.
    assert repo.add_all([m]) == 0


def test_mapping_supersede_records_chain(session: Session) -> None:
    repo = MappingRepository(session)
    original = Iso14224Mapping(
        source_entity_type="FailureMode",
        source_entity_id="fm-1",
        dimension=MappingDimension.CAUSE,
        iso_code="2.1",
        proposer=Proposer.RULE,
        confidence=0.7,
    )
    repo.add_all([original])
    session.commit()
    old_id = session.execute(select(Iso14224MappingRow.id)).scalar_one()

    sme_replacement = Iso14224Mapping(
        source_entity_type="FailureMode",
        source_entity_id="fm-1",
        dimension=MappingDimension.CAUSE,
        iso_code="1.1",
        proposer=Proposer.SME,
        confidence=1.0,
    )
    repo.supersede(old_id, sme_replacement)
    session.commit()

    active = repo.for_entity("FailureMode", "fm-1")
    assert [m.iso_code for m in active] == ["1.1"]
    all_history = repo.for_entity("FailureMode", "fm-1", include_superseded=True)
    assert len(all_history) == 2
    assert {m.iso_code for m in all_history} == {"2.1", "1.1"}


# --- Alias ----------------------------------------------------------------------


def test_alias_repo_round_trips_alias_store(session: Session) -> None:
    repo = AliasRepository(session)
    repo.add_many(
        [
            Alias(
                alias_text="tripped",
                canonical_tokens=("stoppage", "stop"),
                proposer=AliasProposer.RULE,
                confidence=0.9,
            ),
            Alias(
                alias_text="faulty",
                canonical_tokens=("failure",),
                proposer=AliasProposer.LLM,
                confidence=0.6,
                rationale="LLM-mined",
            ),
        ]
    )
    session.commit()
    store = repo.to_alias_store()
    assert store.expand_token("tripped") == {"stoppage", "stop"}
    assert store.expand_token("faulty") == {"failure"}


def test_alias_repo_excludes_superseded(session: Session) -> None:
    """all() should hide superseded aliases by default."""
    repo = AliasRepository(session)
    repo.add(Alias(alias_text="x", canonical_tokens=("a",), proposer=AliasProposer.LLM))
    session.commit()

    rows = session.execute(select(AliasRow)).scalars().all()
    assert len(rows) == 1
    rows[0].superseded_by_id = rows[0].id  # self-supersede sentinel
    session.commit()

    assert repo.all() == []
    assert len(repo.all(include_superseded=True)) == 1


# --- Downtime -------------------------------------------------------------------


def test_downtime_event_upsert_is_idempotent(session: Session) -> None:
    repo = DowntimeRepository(session)
    e = DowntimeEvent(
        external_id="e-1",
        asset_ref="conveyor",
        text="belt tripped",
        start_ts=datetime(2026, 4, 1),
        source_system="cmms",
    )
    assert repo.upsert_events([e]) == 1
    session.commit()
    # Re-inserting the same external_id with updated text replaces in place.
    e2 = DowntimeEvent(
        external_id="e-1",
        asset_ref="conveyor",
        text="belt tripped (corrected)",
        start_ts=datetime(2026, 4, 1),
        source_system="cmms",
    )
    repo.upsert_events([e2])
    session.commit()
    listed = repo.list_events()
    assert len(listed) == 1
    assert listed[0].text == "belt tripped (corrected)"


def test_downtime_classifications_persist_and_load(session: Session) -> None:
    repo = DowntimeRepository(session)
    repo.upsert_events(
        [
            DowntimeEvent(
                external_id="e-1",
                asset_ref="conveyor",
                text="belt tripped",
                start_ts=datetime(2026, 4, 1),
            )
        ]
    )
    classification = DowntimeClassification(
        event_external_id="e-1",
        component_match=ComponentMatch(
            component_token="c-1",
            component_description="Belt",
            score=0.8,
            matched_terms=("belt",),
        ),
        failure_mode_candidates=[
            FailureModeCandidate(
                failure_mode_token="fm-1",
                component_token="c-1",
                score=0.5,
                matched_terms=("belt", "tripped"),
            )
        ],
    )
    repo.add_classifications([classification], model_run_id="run-2026-05-08")
    session.commit()

    loaded = repo.latest_classifications("e-1")
    assert len(loaded) == 1
    assert loaded[0].component_match.component_token == "c-1"
    assert loaded[0].component_match.score == pytest.approx(0.8)
    assert loaded[0].failure_mode_candidates[0].matched_terms == ("belt", "tripped")


def test_downtime_list_filtering(session: Session) -> None:
    repo = DowntimeRepository(session)
    repo.upsert_events(
        [
            DowntimeEvent(
                external_id=f"e-{i}",
                asset_ref="x",
                text=f"text-{i}",
                source_system="cmms" if i % 2 == 0 else "historian",
            )
            for i in range(4)
        ]
    )
    session.commit()
    cmms = repo.list_events(source_system="cmms")
    assert {e.external_id for e in cmms} == {"e-0", "e-2"}


# --- AuditLog -------------------------------------------------------------------


def test_audit_log_append_and_query(session: Session) -> None:
    repo = AuditLogRepository(session)
    repo.append(
        actor="alice",
        action="alias.accept",
        entity_type="alias",
        entity_id="alias:tripped",
        payload={"canonical_tokens": ["stoppage"]},
        note="confirmed",
    )
    session.commit()
    rows = repo.for_entity("alias", "alias:tripped")
    assert len(rows) == 1
    assert rows[0].actor == "alice"
    assert rows[0].payload_json == {"canonical_tokens": ["stoppage"]}


# --- End-to-end -----------------------------------------------------------------


def test_full_pipeline_persists_to_db(
    session: Session, equipment: Equipment, iso_dir: Path
) -> None:
    """Persist an equipment tree, its mappings, an alias, and a classification together."""
    EquipmentRepository(session).upsert(equipment)
    ref = load_all(iso_dir)
    MappingRepository(session).add_all(propose_mappings(equipment, ref).mappings)
    AliasRepository(session).add(
        Alias(
            alias_text="tripped",
            canonical_tokens=("stoppage",),
            proposer=AliasProposer.RULE,
        )
    )
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
    AuditLogRepository(session).append(
        actor="system",
        action="pipeline.run",
        entity_type="run",
        entity_id="2026-05-08",
    )
    session.commit()

    # Cross-aggregate reads after commit.
    assert EquipmentRepository(session).get("eq-1") is not None
    assert AliasRepository(session).to_alias_store().expand_token("tripped") == {"stoppage"}
    assert DowntimeRepository(session).list_events() != []


def test_non_expandable_token_repository(session: Session) -> None:
    """Confirmed non-expandable tokens round-trip as a casefolded, deduped set."""
    from orien_import_tool.persistence import NonExpandableTokenRepository

    repo = NonExpandableTokenRepository(session)
    repo.add("VUMA", reason="conveyor name", sme_user="alice")
    repo.add("vuma")  # idempotent — same casefolded token
    repo.add("scada")
    repo.add("   ")  # blank ignored
    session.commit()

    assert repo.tokens() == {"vuma", "scada"}
