"""Persistence layer — SQLAlchemy ORM models, repositories, sessions.

The repositories are the only entry point downstream code needs. The ORM
models and mapper helpers stay package-private — domain dataclasses go in,
domain dataclasses come out.

Tests run against SQLite in-memory; production targets PostgreSQL via the
``[postgres]`` extra. The ORM is portable between both — JSON columns,
generic types, no Postgres-specific arrays.
"""

from orien_import_tool.persistence.models import (
    AliasRow,
    AuditLogRow,
    Base,
    ComponentRow,
    DowntimeClassificationRow,
    DowntimeEventRow,
    EquipmentRow,
    FailureModeRow,
    Iso14224MappingRow,
)
from orien_import_tool.persistence.repositories import (
    AliasRepository,
    AuditLogRepository,
    DowntimeRepository,
    EquipmentRepository,
    MappingRepository,
)
from orien_import_tool.persistence.session import (
    init_db,
    make_engine,
    make_session_factory,
)

__all__ = [
    "AliasRepository",
    "AliasRow",
    "AuditLogRepository",
    "AuditLogRow",
    "Base",
    "ComponentRow",
    "DowntimeClassificationRow",
    "DowntimeEventRow",
    "DowntimeRepository",
    "EquipmentRepository",
    "EquipmentRow",
    "FailureModeRow",
    "Iso14224MappingRow",
    "MappingRepository",
    "init_db",
    "make_engine",
    "make_session_factory",
]
