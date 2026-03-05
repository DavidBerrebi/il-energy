"""Tests for the SQL parser module."""

import pytest

from il_energy.simulation.sql_parser import SQLParser


class TestSQLParser:
    """Test SQLParser against the sample eplusout.sql fixture."""

    def test_parse_metadata(self, sample_sql_path):
        with SQLParser(sample_sql_path) as p:
            meta = p.parse_metadata()
        assert "EnergyPlus" in meta.ep_version
        assert "25.2.0" in meta.ep_version

    def test_parse_building_area(self, sample_sql_path):
        with SQLParser(sample_sql_path) as p:
            area = p.parse_building_area()
        assert area.total_m2 == pytest.approx(232.26, abs=0.1)
        assert area.unconditioned_m2 == pytest.approx(232.26, abs=0.1)

    def test_parse_site_energy(self, sample_sql_path):
        with SQLParser(sample_sql_path) as p:
            gj = p.parse_site_energy_gj()
        assert gj == pytest.approx(82.41, abs=0.1)

    def test_parse_source_energy(self, sample_sql_path):
        with SQLParser(sample_sql_path) as p:
            gj = p.parse_source_energy_gj()
        assert gj == pytest.approx(260.99, abs=0.1)

    def test_parse_end_uses(self, sample_sql_path):
        with SQLParser(sample_sql_path) as p:
            eu = p.parse_end_uses()
        assert eu.total_kwh > 0
        assert eu.exterior_lighting_kwh > 0
        # 1ZoneUncontrolled has only exterior lighting
        assert eu.heating_kwh == 0.0
        assert eu.cooling_kwh == 0.0

    def test_parse_opaque_surfaces(self, sample_sql_path):
        with SQLParser(sample_sql_path) as p:
            surfaces = p.parse_opaque_surfaces()
        assert len(surfaces) == 5  # 4 walls + 1 roof
        wall = next(s for s in surfaces if "WALL001" in s.name)
        assert wall.u_factor_w_m2k == pytest.approx(0.41, abs=0.01)
        assert wall.construction == "R13WALL"

    def test_parse_unmet_hours(self, sample_sql_path):
        with SQLParser(sample_sql_path) as p:
            unmet = p.parse_unmet_hours()
        assert unmet.total_unmet_hours == 0.0

    def test_parse_zone_energy(self, sample_sql_path):
        with SQLParser(sample_sql_path) as p:
            zones = p.parse_zone_energy()
        assert len(zones) == 1
        assert zones[0].zone_name == "ZONE ONE"
        assert zones[0].floor_area_m2 == pytest.approx(232.26, abs=0.1)

    def test_file_not_found(self, tmp_path):
        from il_energy.exceptions import SQLParseError
        with pytest.raises(SQLParseError):
            SQLParser(tmp_path / "nonexistent.sql")
