"""Shared fixtures for persistence tests — SQLite in-memory engine."""

from __future__ import annotations

import pytest
from sqlalchemy.orm import Session

from orien_import_tool.persistence import init_db, make_engine, make_session_factory


@pytest.fixture
def session() -> Session:
    """Fresh in-memory SQLite database per test, with all tables created."""
    engine = make_engine("sqlite:///:memory:")
    init_db(engine)
    factory = make_session_factory(engine)
    with factory() as session:
        yield session
