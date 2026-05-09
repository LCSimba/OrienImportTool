"""Shared pytest fixtures."""

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="session")
def repo_root() -> Path:
    return REPO_ROOT


@pytest.fixture(scope="session")
def iso_dir(repo_root: Path) -> Path:
    return repo_root / "data" / "iso14224"


@pytest.fixture(scope="session")
def orien_fixture_dir(repo_root: Path) -> Path:
    return repo_root / "tests" / "fixtures" / "orien"


@pytest.fixture
def session():
    """Fresh in-memory SQLite session per test, with all tables created.

    Available globally so tests across modules (persistence, review) can
    share the same DB-fixture pattern.
    """
    from sqlalchemy.orm import Session as _Session  # noqa: F401  type only

    from orien_import_tool.persistence import init_db, make_engine, make_session_factory

    engine = make_engine("sqlite:///:memory:")
    init_db(engine)
    factory = make_session_factory(engine)
    with factory() as db_session:
        yield db_session
