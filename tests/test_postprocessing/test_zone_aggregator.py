"""Tests for il_energy.postprocessing.zone_aggregator."""

import pytest

from il_energy.models import EnvelopeSurface, FlatEnergy, WindowSurface, ZoneEnergy
from il_energy.postprocessing.zone_aggregator import (
    _azimuth_to_cardinal,
    _parse_flat_and_floor,
    aggregate_zones_to_flats,
    assign_orientations_from_windows,
    override_floor_types_from_surfaces,
)


class TestParseFlatAndFloor:
    """Test zone name → (flat_id, floor_number) parsing."""

    def test_nili_style_ground_floor(self):
        flat_id, floor_num = _parse_flat_and_floor("00X1:LIVING")
        assert flat_id == "00X1"
        assert floor_num == 0

    def test_nili_style_upper_floor(self):
        flat_id, floor_num = _parse_flat_and_floor("06X2:SERVICE")
        assert flat_id == "06X2"
        assert floor_num == 6

    def test_core_zone_excluded(self):
        flat_id, floor_num = _parse_flat_and_floor("COREX00:STAIRWAY")
        assert flat_id is None
        assert floor_num is None

    def test_letter_first_style(self):
        flat_id, floor_num = _parse_flat_and_floor("FF01:LIVING")
        assert flat_id == "FF01"
        assert floor_num is None

    def test_flat_prefix_style(self):
        flat_id, floor_num = _parse_flat_and_floor("FLAT_3_BEDROOM")
        # The regex captures the prefix up to the first separator
        assert flat_id == "FLAT"

    def test_apt_prefix_style(self):
        flat_id, floor_num = _parse_flat_and_floor("APT1:KITCHEN")
        assert flat_id == "APT1"

    def test_unknown_zone(self):
        flat_id, floor_num = _parse_flat_and_floor("ZONE ONE")
        assert flat_id is None


class TestAggregateZonesToFlats:
    """Test zone-to-flat grouping."""

    def _zone(self, name, area=50.0, cooling=1000.0, heating=200.0):
        return ZoneEnergy(
            zone_name=name,
            floor_area_m2=area,
            cooling_kwh=cooling,
            heating_kwh=heating,
            total_kwh=cooling + heating,
        )

    def test_basic_aggregation(self):
        zones = [
            self._zone("00X1:LIVING", area=60.0, cooling=2000.0, heating=100.0),
            self._zone("00X1:SERVICE", area=20.0, cooling=500.0, heating=50.0),
        ]
        flats = aggregate_zones_to_flats(zones)
        assert len(flats) == 1
        flat = flats[0]
        assert flat.flat_id == "00X1"
        assert flat.floor_area_m2 == pytest.approx(80.0)
        assert flat.cooling_kwh == pytest.approx(2500.0)
        assert flat.heating_kwh == pytest.approx(150.0)

    def test_floor_type_assignment(self):
        zones = [
            self._zone("00X1:LIVING"),
            self._zone("01X1:LIVING"),
            self._zone("02X1:LIVING"),
        ]
        flats = aggregate_zones_to_flats(zones)
        flat_map = {f.flat_id: f for f in flats}
        assert flat_map["00X1"].floor_type == "ground"
        assert flat_map["01X1"].floor_type == "middle"
        assert flat_map["02X1"].floor_type == "top"

    def test_single_floor_is_ground(self):
        zones = [self._zone("00X1:LIVING")]
        flats = aggregate_zones_to_flats(zones)
        # With only one floor, min==max, so it gets both ground and top
        # In practice it will be "ground" since fn == min_floor is checked first
        assert flats[0].floor_type == "ground"

    def test_core_zones_excluded(self):
        zones = [
            self._zone("00X1:LIVING"),
            self._zone("COREX00:STAIRWAY"),
        ]
        flats = aggregate_zones_to_flats(zones)
        assert len(flats) == 1
        assert flats[0].flat_id == "00X1"

    def test_per_m2_values_computed(self):
        zones = [self._zone("00X1:LIVING", area=100.0, cooling=3000.0, heating=600.0)]
        flats = aggregate_zones_to_flats(zones)
        flat = flats[0]
        assert flat.cooling_kwh_per_m2 == pytest.approx(30.0)
        assert flat.heating_kwh_per_m2 == pytest.approx(6.0)


class TestOverrideFloorTypesFromSurfaces:
    """Test roof-ratio-based floor type promotion."""

    def test_promote_to_top(self):
        flat = FlatEnergy(
            flat_id="05X3", floor_type="middle", floor_area_m2=90.0,
            zones=["05X3:LIVING", "05X3:SERVICE"],
        )
        surfaces = [
            EnvelopeSurface(
                name="ROOF1", zone="05X3:LIVING", adjacency="Exterior",
                tilt_deg=0.0, gross_area_m2=60.0,
            ),
        ]
        override_floor_types_from_surfaces([flat], surfaces)
        assert flat.floor_type == "top"

    def test_no_promotion_below_threshold(self):
        flat = FlatEnergy(
            flat_id="03X1", floor_type="middle", floor_area_m2=100.0,
            zones=["03X1:LIVING"],
        )
        surfaces = [
            EnvelopeSurface(
                name="BALCONY_ROOF", zone="03X1:LIVING", adjacency="Exterior",
                tilt_deg=0.0, gross_area_m2=10.0,  # 10% < 50%
            ),
        ]
        override_floor_types_from_surfaces([flat], surfaces)
        assert flat.floor_type == "middle"

    def test_non_exterior_surfaces_ignored(self):
        flat = FlatEnergy(
            flat_id="03X1", floor_type="middle", floor_area_m2=90.0,
            zones=["03X1:LIVING"],
        )
        surfaces = [
            EnvelopeSurface(
                name="ROOF1", zone="03X1:LIVING", adjacency="Semi-Exterior",
                tilt_deg=0.0, gross_area_m2=90.0,
            ),
        ]
        override_floor_types_from_surfaces([flat], surfaces)
        assert flat.floor_type == "middle"


class TestAzimuthToCardinal:
    """Test azimuth → N/E/S/W conversion."""

    def test_north(self):
        assert _azimuth_to_cardinal(0.0) == "N"
        assert _azimuth_to_cardinal(350.0) == "N"

    def test_east(self):
        assert _azimuth_to_cardinal(90.0) == "E"

    def test_south(self):
        assert _azimuth_to_cardinal(180.0) == "S"

    def test_west(self):
        assert _azimuth_to_cardinal(270.0) == "W"

    def test_wrap_around(self):
        assert _azimuth_to_cardinal(360.0) == "N"


class TestAssignOrientationsFromWindows:
    """Test dominant glazing orientation assignment."""

    def test_assigns_dominant_direction(self):
        flat = FlatEnergy(
            flat_id="01X1", zones=["01X1:LIVING", "01X1:SERVICE"],
            floor_area_m2=100.0,
        )
        windows = [
            WindowSurface(name="W1", zone="01X1:LIVING", glass_area_m2=5.0, azimuth_deg=180.0),  # South
            WindowSurface(name="W2", zone="01X1:LIVING", glass_area_m2=3.0, azimuth_deg=90.0),   # East
            WindowSurface(name="W3", zone="01X1:SERVICE", glass_area_m2=2.0, azimuth_deg=180.0), # South
        ]
        assign_orientations_from_windows([flat], windows)
        assert flat.orientation == "S"

    def test_no_windows_leaves_empty(self):
        flat = FlatEnergy(flat_id="01X1", zones=["01X1:LIVING"], floor_area_m2=100.0)
        assign_orientations_from_windows([flat], [])
        assert flat.orientation == ""
