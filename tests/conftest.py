"""Shared test fixtures."""

from pathlib import Path

import pytest

FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture
def sample_sql_path():
    """Path to the sample EnergyPlus SQL output."""
    path = FIXTURES_DIR / "sample_eplusout.sql"
    if not path.exists():
        pytest.skip("sample_eplusout.sql fixture not found")
    return path


@pytest.fixture
def minimal_idf_path():
    """Path to the minimal IDF test file."""
    path = FIXTURES_DIR / "minimal.idf"
    if not path.exists():
        pytest.skip("minimal.idf fixture not found")
    return path
