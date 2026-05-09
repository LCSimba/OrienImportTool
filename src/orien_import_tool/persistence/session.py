"""Engine + session factory + schema bootstrap.

For tests use ``make_engine("sqlite:///:memory:")``; for production point at
``postgresql+psycopg://...``. SQLAlchemy 2.x is portable enough that the
same ORM models work on both — see :mod:`persistence.models` for the design
choices that keep them so.

When the schema needs to evolve, switch from :func:`init_db` (which calls
``Base.metadata.create_all``) to Alembic migrations. The ORM models are
already structured to give Alembic a clean autogenerate target.
"""

from __future__ import annotations

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from orien_import_tool.persistence.models import Base


def make_engine(url: str, *, echo: bool = False) -> Engine:
    """Create a SQLAlchemy engine.

    For SQLite use ``"sqlite:///path.db"`` or ``"sqlite:///:memory:"``.
    For PostgreSQL use ``"postgresql+psycopg://user:pass@host/db"``.
    """
    return create_engine(url, echo=echo, future=True)


def make_session_factory(engine: Engine) -> sessionmaker[Session]:
    """Return a ``sessionmaker`` bound to ``engine``."""
    return sessionmaker(bind=engine, expire_on_commit=False, future=True)


def init_db(engine: Engine) -> None:
    """Create all tables on ``engine`` if they don't already exist.

    Idempotent — safe to call repeatedly. For production, prefer Alembic
    migrations once the schema has shipped a release.
    """
    Base.metadata.create_all(engine)
