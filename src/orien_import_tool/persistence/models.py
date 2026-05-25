"""SQLAlchemy 2.x ORM models — one table per domain aggregate.

Schema is portable across SQLite (tests) and PostgreSQL (production):

* Generic ``JSON`` (not Postgres-specific ``JSONB``) for nested data —
  swap to JSONB in a migration when the volume needs it.
* ``DateTime`` (not ``TIMESTAMPTZ``) — timestamps are recorded UTC at the
  application layer.
* No array columns; lists serialise into JSON columns.

Iso14224Mapping and Alias rows carry a ``superseded_by_id`` link so SME
corrections accumulate as new rows rather than mutating history. Read paths
filter ``superseded_by_id IS NULL`` to see only the currently-active row;
audit and rollback walk the whole chain.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    JSON,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    """SQLAlchemy declarative base for all ORM rows."""


class EquipmentRow(Base):
    __tablename__ = "equipment"

    token: Mapped[str] = mapped_column(String, primary_key=True)
    description: Mapped[str] = mapped_column(String, nullable=False)
    location: Mapped[str] = mapped_column(String, default="")
    parent_token: Mapped[str] = mapped_column(String, default="")
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict)
    file_hash: Mapped[str] = mapped_column(String, default="")
    imported_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    components: Mapped[list[ComponentRow]] = relationship(
        back_populates="equipment", cascade="all, delete-orphan"
    )


class ComponentRow(Base):
    __tablename__ = "components"

    token: Mapped[str] = mapped_column(String, primary_key=True)
    equipment_token: Mapped[str] = mapped_column(
        String, ForeignKey("equipment.token", ondelete="CASCADE"), nullable=False
    )
    description: Mapped[str] = mapped_column(String, nullable=False)
    parent_description: Mapped[str] = mapped_column(String, default="")
    make: Mapped[str] = mapped_column(String, default="")
    model: Mapped[str] = mapped_column(String, default="")

    equipment: Mapped[EquipmentRow] = relationship(back_populates="components")
    failure_modes: Mapped[list[FailureModeRow]] = relationship(
        back_populates="component", cascade="all, delete-orphan"
    )

    __table_args__ = (Index("ix_components_equipment", "equipment_token"),)


class FailureModeRow(Base):
    __tablename__ = "failure_modes"

    token: Mapped[str] = mapped_column(String, primary_key=True)
    component_token: Mapped[str] = mapped_column(
        String, ForeignKey("components.token", ondelete="CASCADE"), nullable=False
    )
    function_description: Mapped[str] = mapped_column(String, default="")
    failure_description: Mapped[str] = mapped_column(String, default="")
    what: Mapped[str] = mapped_column(String, default="")
    mechanism_and_cause: Mapped[str] = mapped_column(String, default="")
    strategy_type: Mapped[str] = mapped_column(String, default="")
    activities_json: Mapped[list] = mapped_column(JSON, default=list)

    component: Mapped[ComponentRow] = relationship(back_populates="failure_modes")

    __table_args__ = (Index("ix_failure_modes_component", "component_token"),)


class Iso14224MappingRow(Base):
    __tablename__ = "iso14224_mappings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source_entity_type: Mapped[str] = mapped_column(String, nullable=False)
    source_entity_id: Mapped[str] = mapped_column(String, nullable=False)
    dimension: Mapped[str] = mapped_column(String, nullable=False)
    iso_code: Mapped[str] = mapped_column(String, nullable=False)
    proposer: Mapped[str] = mapped_column(String, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    rationale: Mapped[str] = mapped_column(Text, default="")
    priority: Mapped[int] = mapped_column(Integer, default=0)
    iso_table_version: Mapped[str] = mapped_column(String, default="v1")
    superseded_by_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("iso14224_mappings.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        Index(
            "ix_mappings_source",
            "source_entity_type",
            "source_entity_id",
            "dimension",
        ),
        UniqueConstraint(
            "source_entity_type",
            "source_entity_id",
            "dimension",
            "iso_code",
            "proposer",
            name="uq_mappings_canonical",
        ),
    )


class AliasRow(Base):
    __tablename__ = "aliases"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    alias_text: Mapped[str] = mapped_column(String, nullable=False)
    canonical_tokens_json: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    proposer: Mapped[str] = mapped_column(String, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, default=1.0)
    scope_equipment_token: Mapped[str] = mapped_column(String, default="")
    iso_hint: Mapped[str] = mapped_column(String, default="")
    rationale: Mapped[str] = mapped_column(Text, default="")
    superseded_by_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("aliases.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    __table_args__ = (Index("ix_aliases_text", "alias_text"),)


class AbbreviationRow(Base):
    """Operator-shorthand expansion (c/v -> conveyor, instr -> instrument).

    Distinct from AliasRow: an abbreviation rewrites the *text* (one expansion
    string) during normalisation, whereas an alias maps to canonical *tokens*
    for matching. Same superseded_by_id supersession model.
    """

    __tablename__ = "abbreviations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    short: Mapped[str] = mapped_column(String, nullable=False)
    expansion: Mapped[str] = mapped_column(String, nullable=False)
    proposer: Mapped[str] = mapped_column(String, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, default=1.0)
    rationale: Mapped[str] = mapped_column(Text, default="")
    superseded_by_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("abbreviations.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    __table_args__ = (Index("ix_abbreviations_short", "short"),)


class NonExpandableTokenRow(Base):
    """A token an SME confirmed is *not* an abbreviation (product/equipment name).

    Recorded so the abbreviation miner stops re-surfacing it on every run.
    Keyed by the lowercased token; ``reason`` carries the original rationale.
    """

    __tablename__ = "non_expandable_tokens"

    token: Mapped[str] = mapped_column(String, primary_key=True)
    reason: Mapped[str] = mapped_column(Text, default="")
    sme_user: Mapped[str] = mapped_column(String, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class DowntimeEventRow(Base):
    __tablename__ = "downtime_events"

    external_id: Mapped[str] = mapped_column(String, primary_key=True)
    asset_ref: Mapped[str] = mapped_column(String, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    start_ts: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    end_ts: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    duration_s: Mapped[float | None] = mapped_column(Float, nullable=True)
    source_system: Mapped[str] = mapped_column(String, default="")
    ingested_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    classifications: Mapped[list[DowntimeClassificationRow]] = relationship(
        back_populates="event", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("ix_downtime_asset_start", "asset_ref", "start_ts"),
        Index("ix_downtime_source", "source_system"),
    )


class DowntimeClassificationRow(Base):
    __tablename__ = "downtime_classifications"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    event_external_id: Mapped[str] = mapped_column(
        String,
        ForeignKey("downtime_events.external_id", ondelete="CASCADE"),
        nullable=False,
    )
    component_token: Mapped[str] = mapped_column(String, default="")
    component_score: Mapped[float] = mapped_column(Float, default=0.0)
    failure_mode_candidates_json: Mapped[list] = mapped_column(JSON, default=list)
    proposer: Mapped[str] = mapped_column(String, default="alias-rule")
    notes: Mapped[str] = mapped_column(Text, default="")
    model_run_id: Mapped[str] = mapped_column(String, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    event: Mapped[DowntimeEventRow] = relationship(back_populates="classifications")

    __table_args__ = (
        Index("ix_classifications_event", "event_external_id"),
        Index("ix_classifications_run", "model_run_id"),
    )


class AuditLogRow(Base):
    """Append-only record of SME decisions and other state-changing actions.

    Persisted SME decisions on mappings and aliases land here as well as on
    the target row (or solely here, until the corresponding repository
    supports them). Replay-from-log is a future feature; for now this is
    the canonical 'who did what when' source.
    """

    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    actor: Mapped[str] = mapped_column(String, default="")
    action: Mapped[str] = mapped_column(String, nullable=False)
    entity_type: Mapped[str] = mapped_column(String, nullable=False)
    entity_id: Mapped[str] = mapped_column(String, nullable=False)
    payload_json: Mapped[dict] = mapped_column(JSON, default=dict)
    note: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        Index("ix_audit_entity", "entity_type", "entity_id"),
        Index("ix_audit_actor", "actor"),
    )
