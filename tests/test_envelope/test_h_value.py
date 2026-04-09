"""Tests for il_energy.envelope.h_value."""

import pytest

from il_energy.envelope.h_value import (
    _surface_type_from_tilt,
    _h_required,
    _load_h_thresholds,
    compute_h_value_units,
)
from il_energy.models import (
    BuildingArea,
    EnergyEndUse,
    EnvelopeSurface,
    FlatEnergy,
    SimulationOutput,
    WindowSurface,
    ZoneEnergy,
)


class TestSurfaceTypeFromTilt:
    """Test tilt angle → surface type classification."""

    def test_horizontal_roof(self):
        assert _surface_type_from_tilt(0.0) == "Roof"
        assert _surface_type_from_tilt(15.0) == "Roof"

    def test_vertical_wall(self):
        assert _surface_type_from_tilt(90.0) == "Wall"
        assert _surface_type_from_tilt(45.0) == "Wall"

    def test_floor(self):
        assert _surface_type_from_tilt(180.0) == "Floor"
        assert _surface_type_from_tilt(160.0) == "Floor"

    def test_none_defaults_to_wall(self):
        assert _surface_type_from_tilt(None) == "Wall"


class TestHRequired:
    """Test H_required lookup."""

    def test_new_ground(self):
        thresholds = _load_h_thresholds()
        assert _h_required("ground", "new", thresholds) == pytest.approx(2.10)

    def test_new_top(self):
        thresholds = _load_h_thresholds()
        assert _h_required("top", "new", thresholds) == pytest.approx(2.70)

    def test_existing_ground(self):
        thresholds = _load_h_thresholds()
        assert _h_required("ground", "existing", thresholds) == pytest.approx(2.30)

    def test_unknown_floor_type_falls_back(self):
        thresholds = _load_h_thresholds()
        # Unknown floor type falls back to "middle"
        result = _h_required("unknown_type", "new", thresholds)
        assert result == pytest.approx(2.10)


class TestComputeHValueUnits:
    """Test the full H-indicator computation pipeline."""

    def _make_test_data(self, wall_u=1.2, wall_area=40.0, window_u=2.5,
                        glass_area=4.0, frame_area=1.0, flat_area=100.0):
        """Create minimal test data for H-value computation."""
        flat = FlatEnergy(
            flat_id="00X1",
            floor_type="middle",
            floor_area_m2=flat_area,
            zones=["00X1:LIVING"],
        )
        output = SimulationOutput(
            building_area=BuildingArea(conditioned_m2=flat_area),
            end_uses=EnergyEndUse(),
            zones=[ZoneEnergy(zone_name="00X1:LIVING", floor_area_m2=flat_area)],
            envelope_opaque=[
                EnvelopeSurface(
                    name="WALL1", zone="00X1:LIVING", adjacency="Exterior",
                    u_factor_w_m2k=wall_u, gross_area_m2=wall_area, tilt_deg=90.0,
                ),
            ],
            envelope_windows=[
                WindowSurface(
                    name="WIN1", zone="00X1:LIVING",
                    u_factor_w_m2k=window_u, glass_area_m2=glass_area,
                    frame_area_m2=frame_area, azimuth_deg=180.0,
                ),
            ],
        )
        return output, [flat]

    def test_basic_h_calculation(self):
        output, flats = self._make_test_data()
        results = compute_h_value_units(output, flats)

        assert len(results) == 1
        h_unit = results[0]
        assert h_unit.flat_id == "00X1"
        assert h_unit.calculated_h > 0
        assert h_unit.required_h == pytest.approx(2.10)

        # Manual calculation:
        # Wall: 1.2 * 40 = 48.0 W/K
        # Glass: 2.5 * 4.0 = 10.0 W/K
        # Frame: 5.8 * 1.0 = 5.8 W/K (default frame conductance)
        # Total UA = 63.8, H = 63.8 / 100 = 0.638 W/m²K
        assert h_unit.calculated_h == pytest.approx(0.638, rel=1e-2)

    def test_pass_condition(self):
        output, flats = self._make_test_data()
        results = compute_h_value_units(output, flats)
        # H = 0.638 < 2.10 → passes
        assert results[0].passes is True

    def test_fail_condition(self):
        # Very high U-values to fail
        output, flats = self._make_test_data(wall_u=5.0, wall_area=100.0)
        results = compute_h_value_units(output, flats)
        # H = (5.0*100 + 2.5*4 + 5.8*1) / 100 = 5.158 W/m²K > 2.10
        assert results[0].passes is False

    def test_custom_frame_conductance(self):
        output, flats = self._make_test_data(wall_area=0.0)
        frame_conds = {"default": 3.0}
        results = compute_h_value_units(output, flats, frame_conductances=frame_conds)

        # Only window: glass U=2.5*4=10, frame U=3.0*1=3.0, total=13, H=13/100=0.13
        h_unit = results[0]
        assert h_unit.calculated_h == pytest.approx(0.13, rel=1e-2)

    def test_empty_flats(self):
        output = SimulationOutput()
        results = compute_h_value_units(output, [])
        assert results == []

    def test_zero_area_flat_excluded(self):
        flat = FlatEnergy(flat_id="00X1", floor_type="middle", floor_area_m2=0.0)
        output = SimulationOutput()
        results = compute_h_value_units(output, [flat])
        assert results == []
