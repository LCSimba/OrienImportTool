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
