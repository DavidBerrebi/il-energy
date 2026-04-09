"""Tests for il_energy.rating.calculator."""

import pytest

from il_energy.models import FlatEnergy
from il_energy.rating.calculator import compute_ip, compute_unit_ratings, grade_from_ip


class TestComputeIP:
    """Test the Improvement Percentage formula."""

    def test_positive_improvement(self):
        # Proposed 30, reference 40 → IP = (40-30)/40*100 = 25%
        assert compute_ip(30.0, 40.0) == pytest.approx(25.0)

    def test_zero_improvement(self):
        assert compute_ip(40.0, 40.0) == pytest.approx(0.0)

    def test_negative_improvement(self):
        # Proposed worse than reference
        assert compute_ip(50.0, 40.0) == pytest.approx(-25.0)

    def test_zero_reference(self):
        # Should return 0 to avoid division by zero
        assert compute_ip(30.0, 0.0) == 0.0

    def test_negative_reference(self):
        assert compute_ip(30.0, -5.0) == 0.0

    def test_both_zero(self):
        assert compute_ip(0.0, 0.0) == 0.0

    def test_high_improvement(self):
        # Proposed 10, reference 40 → IP = 75%
        assert compute_ip(10.0, 40.0) == pytest.approx(75.0)


class TestGradeFromIP:
    """Test grade lookup from IP percentage."""

    def test_grade_a_plus(self):
        result = grade_from_ip(50.0)
        assert result["grade"] == "A+"

    def test_grade_a(self):
        result = grade_from_ip(35.0)
        assert result["grade"] == "A"

    def test_grade_b(self):
        result = grade_from_ip(20.0)
        assert result["grade"] == "B"

    def test_grade_c(self):
        result = grade_from_ip(10.0)
        assert result["grade"] == "C"

    def test_grade_d(self):
        result = grade_from_ip(0.0)
        assert result["grade"] == "D"

    def test_grade_e(self):
        result = grade_from_ip(-5.0)
        assert result["grade"] == "E"

    def test_grade_f(self):
        result = grade_from_ip(-15.0)
        assert result["grade"] == "F"

    def test_boundary_b_to_a(self):
        # Exactly at 30% boundary
        result = grade_from_ip(30.0)
        assert result["grade"] == "A"

    def test_just_below_b(self):
        result = grade_from_ip(19.9)
        assert result["grade"] == "C"

    def test_has_required_keys(self):
        result = grade_from_ip(25.0)
        assert "grade" in result
        assert "name_en" in result
        assert "name_he" in result
        assert "score" in result
        assert "ip_range" in result


class TestComputeUnitRatings:
    """Test per-unit rating computation."""

    def _make_flat(self, flat_id, floor_type, area, cooling, heating, floor_number=0):
        return FlatEnergy(
            flat_id=flat_id,
            floor_type=floor_type,
            floor_number=floor_number,
            floor_area_m2=area,
            cooling_kwh=cooling,
            heating_kwh=heating,
        )

    def test_basic_unit_rating(self):
        flats = [self._make_flat("01X1", "middle", 100.0, 9000.0, 1000.0)]
        ep_ref = {"middle": 40.0}
        results = compute_unit_ratings(flats, ep_ref, cop=3.0)

        assert len(results) == 1
        unit = results[0]
        # EPdes = (9000+1000) / 3.0 / 100 = 33.33
        assert unit["ep_des_kwh_m2"] == pytest.approx(33.333, rel=1e-2)
        assert unit["ep_ref_kwh_m2"] == pytest.approx(40.0)
        # IP = (40-33.33)/40*100 = 16.67%
        assert unit["ip_percent"] == pytest.approx(16.67, rel=1e-2)
        assert unit["grade"]["grade"] == "C"

    def test_per_flat_epref_overrides_floor_type(self):
        flats = [self._make_flat("01X2", "middle", 48.0, 4000.0, 200.0)]
        ep_ref_ft = {"middle": 39.0}
        ep_ref_flat = {"01X2": 46.0}  # Small unit gets higher EPref
        results = compute_unit_ratings(flats, ep_ref_ft, cop=3.0, ep_ref_by_flat_id=ep_ref_flat)

        assert results[0]["ep_ref_kwh_m2"] == pytest.approx(46.0)

    def test_zero_area_flat_excluded(self):
        flats = [self._make_flat("00X1", "ground", 0.0, 0.0, 0.0)]
        results = compute_unit_ratings(flats, {"ground": 30.0})
        assert len(results) == 0

    def test_multiple_flats_sorted(self):
        flats = [
            self._make_flat("02X1", "middle", 100.0, 6000.0, 0.0, floor_number=2),
            self._make_flat("01X1", "middle", 100.0, 6000.0, 0.0, floor_number=1),
        ]
        results = compute_unit_ratings(flats, {"middle": 30.0})
        assert results[0]["flat_id"] == "01X1"
        assert results[1]["flat_id"] == "02X1"

    def test_fallback_to_middle_when_floor_type_missing(self):
        flats = [self._make_flat("00X1", "ground", 100.0, 6000.0, 0.0)]
        ep_ref = {"middle": 35.0}  # No "ground" key
        results = compute_unit_ratings(flats, ep_ref)
        assert results[0]["ep_ref_kwh_m2"] == pytest.approx(35.0)
