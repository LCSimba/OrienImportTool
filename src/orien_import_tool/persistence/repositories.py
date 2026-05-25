"""Repository pattern over the SQLAlchemy ORM.

One repository per aggregate root. The repositories accept and return domain
dataclasses; mapping to/from ORM rows happens internally via
:mod:`persistence.mappers`. Downstream code never touches the ORM directly.

Sessions are passed in by the caller — repositories don't manage transactions.
The caller (typically a service or CLI) owns the unit of work and decides when
to commit:

    with session_factory() as session:
        repo = AliasRepository(session)
        repo.add_many(aliases)
        session.commit()
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from orien_import_tool.aliases.models import Alias
from orien_import_tool.aliases.store import AliasStore
from orien_import_tool.domain.downtime import DowntimeClassification, DowntimeEvent
from orien_import_tool.domain.fmea import Equipment
from orien_import_tool.mapping.models import Iso14224Mapping, MappingDimension
from orien_import_tool.persistence import mappers
from orien_import_tool.persistence.models import (
    AbbreviationRow,
    AliasRow,
    AuditLogRow,
    ComponentRow,
    DowntimeClassificationRow,
    DowntimeEventRow,
    EquipmentRow,
    Iso14224MappingRow,
    NonExpandableTokenRow,
)
from orien_import_tool.textnorm.abbreviations import (
    Abbreviation,
    AbbreviationStore,
    build_initial_abbreviations,
)

# --- EquipmentRepository ------------------------------------------------------------


class EquipmentRepository:
    """Persist and load FMEA equipment trees."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def upsert(self, equipment: Equipment, *, file_hash: str = "") -> None:
        """Insert or replace an equipment tree.

        Replaces the entire ``components`` cascade — re-importing an Orien
        export must be idempotent. Equipment metadata (description, file_hash)
        updates in place.
        """
        existing = self._session.get(EquipmentRow, equipment.token)
        if existing is not None:
            self._session.delete(existing)
            self._session.flush()
        self._session.add(mappers.equipment_to_orm(equipment, file_hash=file_hash))

    def get(self, token: str) -> Equipment | None:
        row = self._session.execute(
            select(EquipmentRow)
            .where(EquipmentRow.token == token)
            .options(selectinload(EquipmentRow.components).selectinload(ComponentRow.failure_modes))
        ).scalar_one_or_none()
        if row is None:
            return None
        return mappers.equipment_from_orm(row)

    def list(self) -> list[Equipment]:
        rows = (
            self._session.execute(
                select(EquipmentRow).options(
                    selectinload(EquipmentRow.components).selectinload(ComponentRow.failure_modes)
                )
            )
            .scalars()
            .all()
        )
        return [mappers.equipment_from_orm(row) for row in rows]


# --- MappingRepository --------------------------------------------------------------


class MappingRepository:
    """Persist Iso14224Mapping rows; supports supersession for SME corrections."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def add_all(self, mappings: Iterable[Iso14224Mapping]) -> int:
        """Bulk insert mappings, skipping rows that already exist on the unique key."""
        added = 0
        for m in mappings:
            existing = self._session.execute(
                select(Iso14224MappingRow).where(
                    Iso14224MappingRow.source_entity_type == m.source_entity_type,
                    Iso14224MappingRow.source_entity_id == m.source_entity_id,
                    Iso14224MappingRow.dimension == m.dimension.value,
                    Iso14224MappingRow.iso_code == m.iso_code,
                    Iso14224MappingRow.proposer == m.proposer.value,
                )
            ).scalar_one_or_none()
            if existing is not None:
                continue
            self._session.add(mappers.mapping_to_orm(m))
            added += 1
        return added

    def for_entity(
        self,
        source_entity_type: str,
        source_entity_id: str,
        *,
        include_superseded: bool = False,
    ) -> list[Iso14224Mapping]:
        stmt = select(Iso14224MappingRow).where(
            Iso14224MappingRow.source_entity_type == source_entity_type,
            Iso14224MappingRow.source_entity_id == source_entity_id,
        )
        if not include_superseded:
            stmt = stmt.where(Iso14224MappingRow.superseded_by_id.is_(None))
        rows = self._session.execute(stmt).scalars().all()
        return [mappers.mapping_from_orm(row) for row in rows]

    def for_dimension(self, dimension: MappingDimension) -> list[Iso14224Mapping]:
        rows = (
            self._session.execute(
                select(Iso14224MappingRow).where(
                    Iso14224MappingRow.dimension == dimension.value,
                    Iso14224MappingRow.superseded_by_id.is_(None),
                )
            )
            .scalars()
            .all()
        )
        return [mappers.mapping_from_orm(row) for row in rows]

    def supersede(
        self,
        old_id: int,
        replacement: Iso14224Mapping,
    ) -> int:
        """Mark ``old_id`` superseded by a freshly-inserted replacement.

        Returns the new row's id. SME corrections preserve history this way.
        """
        old = self._session.get(Iso14224MappingRow, old_id)
        if old is None:
            raise ValueError(f"mapping id {old_id} not found")
        new_row = mappers.mapping_to_orm(replacement)
        self._session.add(new_row)
        self._session.flush()
        old.superseded_by_id = new_row.id
        return new_row.id


# --- AliasRepository ----------------------------------------------------------------


class AliasRepository:
    """Persist Alias rows and rehydrate them into an :class:`AliasStore`."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, alias: Alias) -> None:
        self._session.add(mappers.alias_to_orm(alias))

    def add_many(self, aliases: Iterable[Alias]) -> int:
        count = 0
        for alias in aliases:
            self._session.add(mappers.alias_to_orm(alias))
            count += 1
        return count

    def all(self, *, include_superseded: bool = False) -> list[Alias]:
        stmt = select(AliasRow)
        if not include_superseded:
            stmt = stmt.where(AliasRow.superseded_by_id.is_(None))
        rows = self._session.execute(stmt).scalars().all()
        return [mappers.alias_from_orm(row) for row in rows]

    def to_alias_store(self) -> AliasStore:
        """Return an :class:`AliasStore` populated with every active alias."""
        store = AliasStore()
        store.add_many(self.all())
        return store


# --- AbbreviationRepository ---------------------------------------------------------


class AbbreviationRepository:
    """Persist Abbreviation rows and rehydrate them into an AbbreviationStore."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, abbrev: Abbreviation) -> None:
        self._session.add(mappers.abbreviation_to_orm(abbrev))

    def add_many(self, abbreviations: Iterable[Abbreviation]) -> int:
        count = 0
        for abbrev in abbreviations:
            self._session.add(mappers.abbreviation_to_orm(abbrev))
            count += 1
        return count

    def all(self, *, include_superseded: bool = False) -> list[Abbreviation]:
        stmt = select(AbbreviationRow)
        if not include_superseded:
            stmt = stmt.where(AbbreviationRow.superseded_by_id.is_(None))
        rows = self._session.execute(stmt).scalars().all()
        return [mappers.abbreviation_from_orm(row) for row in rows]

    def to_store(self, *, seeded: bool = True) -> AbbreviationStore:
        """Return an AbbreviationStore = (optional rule seed) + persisted rows.

        ``seeded=True`` starts from :func:`build_initial_abbreviations` (the
        domain-general CMMS shorthand) and layers the persisted SME/LLM rows
        on top — the store the normaliser should use in production.
        """
        store = build_initial_abbreviations() if seeded else AbbreviationStore()
        store.add_many(self.all())
        return store


class NonExpandableTokenRepository:
    """Tokens an SME confirmed are not abbreviations — load them as a skip set.

    The abbreviation miner consults this set so confirmed product/equipment
    names (``vuma``, ``scada``, ...) stop re-surfacing as unknowns each run.
    """

    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, token: str, *, reason: str = "", sme_user: str = "") -> None:
        key = token.strip().casefold()
        if not key or self._session.get(NonExpandableTokenRow, key) is not None:
            return
        self._session.add(NonExpandableTokenRow(token=key, reason=reason, sme_user=sme_user))

    def tokens(self) -> set[str]:
        return set(self._session.execute(select(NonExpandableTokenRow.token)).scalars().all())


# --- DowntimeRepository -------------------------------------------------------------


class DowntimeRepository:
    """Persist DowntimeEvents and their classifications.

    Events are upserted on ``external_id`` (the natural key from the source
    system); classifications append per (event, model_run) pair so multiple
    classifier runs are reproducible.
    """

    def __init__(self, session: Session) -> None:
        self._session = session

    def upsert_events(self, events: Iterable[DowntimeEvent]) -> int:
        added = 0
        updated = 0
        for event in events:
            existing = self._session.get(DowntimeEventRow, event.external_id)
            if existing is None:
                self._session.add(mappers.downtime_event_to_orm(event))
                added += 1
            else:
                # Refresh mutable text-side fields; preserve ingested_at.
                existing.asset_ref = event.asset_ref
                existing.text = event.text
                existing.start_ts = event.start_ts
                existing.end_ts = event.end_ts
                existing.duration_s = event.duration_s
                existing.source_system = event.source_system
                updated += 1
        return added + updated

    def list_events(
        self,
        *,
        source_system: str | None = None,
        limit: int | None = None,
    ) -> list[DowntimeEvent]:
        stmt = select(DowntimeEventRow)
        if source_system is not None:
            stmt = stmt.where(DowntimeEventRow.source_system == source_system)
        if limit is not None:
            stmt = stmt.limit(limit)
        rows = self._session.execute(stmt).scalars().all()
        return [mappers.downtime_event_from_orm(row) for row in rows]

    def add_classifications(
        self,
        classifications: Iterable[DowntimeClassification],
        *,
        model_run_id: str = "",
    ) -> int:
        count = 0
        for classification in classifications:
            self._session.add(
                mappers.classification_to_orm(classification, model_run_id=model_run_id)
            )
            count += 1
        return count

    def latest_classifications(
        self,
        event_external_id: str,
    ) -> list[DowntimeClassification]:
        rows = (
            self._session.execute(
                select(DowntimeClassificationRow)
                .where(DowntimeClassificationRow.event_external_id == event_external_id)
                .order_by(DowntimeClassificationRow.created_at.desc())
            )
            .scalars()
            .all()
        )
        return [mappers.classification_from_orm(row) for row in rows]


# --- AuditLogRepository -------------------------------------------------------------


class AuditLogRepository:
    """Append-only log of state-changing actions."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def append(
        self,
        *,
        actor: str,
        action: str,
        entity_type: str,
        entity_id: str,
        payload: dict[str, Any] | None = None,
        note: str = "",
    ) -> None:
        self._session.add(
            AuditLogRow(
                actor=actor,
                action=action,
                entity_type=entity_type,
                entity_id=entity_id,
                payload_json=dict(payload) if payload else {},
                note=note,
                created_at=datetime.utcnow(),
            )
        )

    def for_entity(self, entity_type: str, entity_id: str) -> list[AuditLogRow]:
        return list(
            self._session.execute(
                select(AuditLogRow).where(
                    AuditLogRow.entity_type == entity_type,
                    AuditLogRow.entity_id == entity_id,
                )
            ).scalars()
        )
