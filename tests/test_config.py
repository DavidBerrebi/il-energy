"""Tests for il_energy.config — climate zone detection."""

import pytest
from pathlib import Path

from il_energy.config import detect_zone_from_epw


class TestDetectZoneFromEPW:
    """Test SI 5282 climate zone detection from EPW files."""

    def _write_epw_header(self, tmp_path, wmo, lat=32.0, lon=34.8, elev=10.0):
        """Create a minimal EPW file with LOCATION header."""
        epw = tmp_path / "test.epw"
        header = f"LOCATION,TestCity,TestState,ISR,TestSource,{wmo},{lat},{lon},2.0,{elev}"
        epw.write_text(header + "\n", encoding="latin-1")
        return epw

    def test_tel_aviv_sde_dov_zone_a(self, tmp_path):
        epw = self._write_epw_header(tmp_path, "401762")
        assert detect_zone_from_epw(epw) == "A"

    def test_haifa_zone_a(self, tmp_path):
        epw = self._write_epw_header(tmp_path, "401550")
        assert detect_zone_from_epw(epw) == "A"

    def test_eilat_zone_b(self, tmp_path):
        epw = self._write_epw_header(tmp_path, "401990")
        assert detect_zone_from_epw(epw) == "B"

    def test_beersheba_zone_b(self, tmp_path):
        epw = self._write_epw_header(tmp_path, "401880")
        assert detect_zone_from_epw(epw) == "B"

    def test_jerusalem_zone_c(self, tmp_path):
        epw = self._write_epw_header(tmp_path, "401830")
        assert detect_zone_from_epw(epw) == "C"

    def test_heuristic_high_elevation_zone_c(self, tmp_path):
        # Unknown WMO but high elevation → Zone C
        epw = self._write_epw_header(tmp_path, "999999", lat=31.7, elev=800.0)
        assert detect_zone_from_epw(epw) == "C"

    def test_heuristic_low_latitude_zone_b(self, tmp_path):
        # Unknown WMO, low latitude (<30.5°N), low elevation → Zone B
        epw = self._write_epw_header(tmp_path, "999999", lat=29.5, elev=50.0)
        assert detect_zone_from_epw(epw) == "B"

    def test_heuristic_default_zone_a(self, tmp_path):
        # Unknown WMO, moderate latitude, low elevation → Zone A (coastal default)
        epw = self._write_epw_header(tmp_path, "999999", lat=32.0, elev=20.0)
        assert detect_zone_from_epw(epw) == "A"

    def test_missing_file_returns_b(self, tmp_path):
        missing = tmp_path / "nonexistent.epw"
        assert detect_zone_from_epw(missing) == "B"

    def test_malformed_header_returns_b(self, tmp_path):
        epw = tmp_path / "bad.epw"
        epw.write_text("NOT_A_LOCATION_LINE\n", encoding="latin-1")
        assert detect_zone_from_epw(epw) == "B"

    def test_short_header_returns_b(self, tmp_path):
        epw = tmp_path / "short.epw"
        epw.write_text("LOCATION,City,State\n", encoding="latin-1")
        assert detect_zone_from_epw(epw) == "B"
