"""Tests for il_energy.report.generator — building grade, costs, CSV output."""

import csv
from io import StringIO

import pytest

from il_energy.report.generator import (
    _building_grade,
    _five_year_costs,
    write_units_csv,
)


class TestBuildingGrade:
    """Test area-weighted building grade computation."""

    def _unit(self, area, score, grade_letter):
        return {
            "area_m2": area,
            "grade": {"score": score, "grade": grade_letter},
        }

    def test_all_same_grade(self):
        units = [self._unit(100.0, 3, "B"), self._unit(50.0, 3, "B")]
        result = _building_grade(units, "A")
        assert result["grade"] == "B"
        assert result["weighted_score"] == pytest.approx(3.0)

    def test_area_weighted_average(self):
        units = [
            self._unit(100.0, 4, "A"),   # score 4 × 100 = 400
            self._unit(100.0, 2, "C"),   # score 2 × 100 = 200
        ]
        result = _building_grade(units, "A")
        # Weighted avg = 600/200 = 3.0 → Grade B
        assert result["grade"] == "B"
        assert result["weighted_score"] == pytest.approx(3.0)

    def test_any_f_unit_makes_building_f(self):
        units = [
            self._unit(100.0, 4, "A"),
            self._unit(50.0, -1, "F"),
        ]
        result = _building_grade(units, "A")
        assert result["grade"] == "F"
        assert result["score"] == -1

    def test_rounding_up(self):
        units = [
            self._unit(60.0, 4, "A"),   # 240
            self._unit(40.0, 3, "B"),   # 120
        ]
        # Weighted avg = 360/100 = 3.6 → rounds to 4 → Grade A
        result = _building_grade(units, "A")
        assert result["grade"] == "A"

    def test_rounding_down(self):
        units = [
            self._unit(60.0, 3, "B"),   # 180
            self._unit(40.0, 2, "C"),   # 80
        ]
        # Weighted avg = 260/100 = 2.6 → rounds to 3 → Grade B
        result = _building_grade(units, "A")
        assert result["grade"] == "B"

    def test_empty_units(self):
        result = _building_grade([], "A")
        assert result["grade"] == "?"


class TestFiveYearCosts:
    """Test 5-year electricity cost projections."""

    def test_basic_savings(self):
        result = _five_year_costs(ep_ref_weighted=40.0, ep_des=30.0, cond_area=100.0)
        # ref_nis = 40 * 100 * 5 * 0.62 = 12,400
        # proposed_nis = 30 * 100 * 5 * 0.62 = 9,300
        # savings_nis = 3,100
        assert result["ref_nis"] == pytest.approx(12400.0)
        assert result["proposed_nis"] == pytest.approx(9300.0)
        assert result["savings_nis"] == pytest.approx(3100.0)
        assert result["savings_pct"] == pytest.approx(25.0)

    def test_no_savings_when_proposed_worse(self):
        result = _five_year_costs(ep_ref_weighted=30.0, ep_des=40.0, cond_area=100.0)
        assert result["savings_nis"] == 0.0
        assert result["savings_pct"] == 0.0

    def test_zero_area(self):
        result = _five_year_costs(ep_ref_weighted=40.0, ep_des=30.0, cond_area=0.0)
        assert result["ref_nis"] == 0.0
        assert result["savings_nis"] == 0.0

    def test_zero_reference(self):
        result = _five_year_costs(ep_ref_weighted=0.0, ep_des=30.0, cond_area=100.0)
        assert result["savings_pct"] == 0.0


class TestWriteUnitsCsv:
    """Test units.csv output format."""

    def test_writes_correct_format(self, tmp_path):
        unit_ratings = [
            {
                "flat_id": "00X1",
                "floor_number": 0,
                "floor_type": "ground",
                "orientation": "S",
                "area_m2": 108.73,
                "cooling_kwh": 7559.36,
                "heating_kwh": 4.98,
                "hvac_kwh": 7564.34,
                "cop": 3.0,
                "ep_des_kwh_m2": 23.19,
                "ep_ref_kwh_m2": 27.43,
                "ip_percent": 15.5,
                "grade": {"grade": "C", "name_en": "Silver", "name_he": "כסף", "score": 2},
            },
        ]
        out = tmp_path / "units.csv"
        write_units_csv(unit_ratings, out)

        content = out.read_text(encoding="utf-8")
        reader = csv.DictReader(StringIO(content))
        rows = list(reader)
        assert len(rows) == 1
        row = rows[0]
        assert row["Multiplier"] == "1"
        assert row["Grade"] == "2"
        assert row["Rating (G)"] == "C"
        assert row["Flat or Zone"] == "1"
        assert row["Floor"] == "00"
        assert row["Orientation"] == "S"

    def test_multiple_units(self, tmp_path):
        unit_ratings = [
            {
                "flat_id": f"0{i}X1", "floor_number": i, "floor_type": "middle",
                "orientation": "E", "area_m2": 100.0,
                "cooling_kwh": 6000.0, "heating_kwh": 100.0, "hvac_kwh": 6100.0,
                "cop": 3.0, "ep_des_kwh_m2": 20.33, "ep_ref_kwh_m2": 39.16,
                "ip_percent": 48.1,
                "grade": {"grade": "A+", "name_en": "Diamond", "score": 5},
            }
            for i in range(3)
        ]
        out = tmp_path / "units.csv"
        write_units_csv(unit_ratings, out)
        content = out.read_text(encoding="utf-8")
        lines = content.strip().split("\n")
        assert len(lines) == 4  # header + 3 rows
