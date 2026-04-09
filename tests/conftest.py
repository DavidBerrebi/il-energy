"""Shared test fixtures."""

import json
from pathlib import Path

import pytest

FIXTURES_DIR = Path(__file__).parent / "fixtures"
NILI_GOLDEN_DIR = FIXTURES_DIR / "nili_golden"


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


@pytest.fixture
def nili_sql_path():
    """Path to the Nili project EnergyPlus SQL output."""
    path = NILI_GOLDEN_DIR / "eplusout.sql"
    if not path.exists():
        pytest.skip("Nili eplusout.sql fixture not found")
    return path


@pytest.fixture
def nili_golden_rating():
    """Load the Nili golden residential_rating.json."""
    path = NILI_GOLDEN_DIR / "residential_rating.json"
    if not path.exists():
        pytest.skip("Nili golden residential_rating.json not found")
    with open(path, encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture
def nili_golden_units_csv():
    """Load the Nili golden units.csv as list of lines."""
    path = NILI_GOLDEN_DIR / "units.csv"
    if not path.exists():
        pytest.skip("Nili golden units.csv not found")
    return path.read_text(encoding="utf-8")
