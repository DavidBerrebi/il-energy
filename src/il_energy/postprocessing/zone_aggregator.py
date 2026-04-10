
"""Zone-to-flat aggregation for residential buildings."""

from __future__ import annotations

from typing import Callable, Dict, List, Optional

from il_energy.constants import ROOF_RATIO_THRESHOLD, ROOF_TILT_THRESHOLD_DEG
from il_energy.models import EnvelopeSurface, FlatEnergy, WindowSurface, ZoneEnergy
from il_energy.utils.zone_naming import azimuth_to_cardinal as _azimuth_to_cardinal
from il_energy.utils.zone_naming import parse_flat_and_floor, zone_to_flat

# Re-export for backward compatibility with existing tests and imports
_parse_flat_and_floor = parse_flat_and_floor


def _default_flat_extractor(zone_name: str) -> Optional[str]:
    """Extract flat ID from zone name (legacy interface)."""
    return zone_to_flat(zone_name)


def aggregate_zones_to_flats(
    zones: List[ZoneEnergy],
    flat_extractor: Optional[Callable[[str], Optional[str]]] = None,
) -> List[FlatEnergy]:
    """Group zones into flats and compute per-flat metrics.

    Args:
        zones: List of zone energy data.
        flat_extractor: Function that extracts flat ID from zone name.
            Returns None for zones that don't belong to a flat.
            Defaults to _default_flat_extractor.
    """
    # Use the richer parser when no custom extractor is provided
    use_default = flat_extractor is None
    extractor = flat_extractor or _default_flat_extractor

    flat_map: Dict[str, FlatEnergy] = {}
    floor_map: Dict[str, Optional[int]] = {}  # flat_id → floor_number

    for zone in zones:
        if use_default:
            flat_id, floor_num = _parse_flat_and_floor(zone.zone_name)
        else:
            flat_id = extractor(zone.zone_name)
            floor_num = None

        if flat_id is None:
            continue

        if flat_id not in flat_map:
            flat_map[flat_id] = FlatEnergy(flat_id=flat_id, floor_number=floor_num)
            floor_map[flat_id] = floor_num

        flat = flat_map[flat_id]
        flat.zones.append(zone.zone_name)
        flat.floor_area_m2 += zone.floor_area_m2
        flat.heating_kwh += zone.heating_kwh
        flat.cooling_kwh += zone.cooling_kwh
        flat.total_kwh += zone.total_kwh

    # Assign floor_type (ground / middle / top) based on floor numbers
    known_floors = [f for f in floor_map.values() if f is not None]
    if known_floors:
        min_floor = min(known_floors)
        max_floor = max(known_floors)
        for flat in flat_map.values():
            fn = flat.floor_number
            if fn is None:
                flat.floor_type = "middle"
            elif fn == min_floor:
                flat.floor_type = "ground"
            elif fn == max_floor:
                flat.floor_type = "top"
            else:
                flat.floor_type = "middle"

    # Compute per-m² values
    for flat in flat_map.values():
        if flat.floor_area_m2 > 0:
            flat.heating_kwh_per_m2 = flat.heating_kwh / flat.floor_area_m2
            flat.cooling_kwh_per_m2 = flat.cooling_kwh / flat.floor_area_m2
            flat.total_kwh_per_m2 = flat.total_kwh / flat.floor_area_m2

    return list(flat_map.values())


def override_floor_types_from_surfaces(
    flats: List[FlatEnergy],
    surfaces: List[EnvelopeSurface],
) -> None:
    """Override flat floor_type based on actual roof/floor surfaces.

    Upgrades floor_type in-place for flats that have a significant exposed
    horizontal roof (penthouse / setback units) — even when their floor number
    is not the building maximum.

    A flat is promoted to "top" when the total area of exterior horizontal
    surfaces (tilt < ROOF_TILT_THRESHOLD_DEG) exceeds ROOF_RATIO_THRESHOLD
    of the flat's floor area. This avoids false-positives from small balcony
    ceiling slabs or tiny roof offsets.

    Args:
        flats: Flat list to update in-place.
        surfaces: Opaque exterior surfaces from the SQL parser.
    """
    # Build zone→flat_id lookup
    zone_to_flat: Dict[str, str] = {}
    for flat in flats:
        for z in flat.zones:
            zone_to_flat[z.upper()] = flat.flat_id

    flat_by_id: Dict[str, FlatEnergy] = {f.flat_id: f for f in flats}

    # Accumulate exposed roof area per flat
    roof_area_by_flat: Dict[str, float] = {}
    for surf in surfaces:
        if surf.tilt_deg is None or surf.adjacency != "Exterior":
            continue
        flat_id = zone_to_flat.get(surf.zone.upper())
        if flat_id is None:
            continue
        if surf.tilt_deg < ROOF_TILT_THRESHOLD_DEG:
            roof_area_by_flat[flat_id] = (
                roof_area_by_flat.get(flat_id, 0.0) + (surf.gross_area_m2 or 0.0)
            )

    # Promote flats whose roof area / floor area exceeds the threshold
    for flat_id, roof_area in roof_area_by_flat.items():
        flat = flat_by_id.get(flat_id)
        if flat is None or flat.floor_area_m2 <= 0:
            continue
        if roof_area / flat.floor_area_m2 >= ROOF_RATIO_THRESHOLD:
            flat.floor_type = "top"


def assign_orientations_from_windows(
    flats: List[FlatEnergy],
    windows: List[WindowSurface],
) -> None:
    """Set flat.orientation to the dominant glazing direction (N/E/S/W).

    Uses exterior fenestration glass area by azimuth.  The cardinal direction
    with the largest total glass area wins.  Flats with no windows keep an
    empty orientation string.

    Args:
        flats:   Flat list to update in-place.
        windows: Exterior window surfaces from the SQL parser (envelope_windows).
    """
    # Build zone → flat_id lookup
    zone_to_flat: Dict[str, str] = {}
    for flat in flats:
        for z in flat.zones:
            zone_to_flat[z.upper()] = flat.flat_id

    flat_by_id: Dict[str, FlatEnergy] = {f.flat_id: f for f in flats}

    # Accumulate glass area by (flat_id, cardinal)
    area_by_flat_dir: Dict[str, Dict[str, float]] = {}
    for win in windows:
        if win.azimuth_deg is None:
            continue
        flat_id = zone_to_flat.get(win.zone.upper())
        if flat_id is None:
            continue
        cardinal = _azimuth_to_cardinal(win.azimuth_deg)
        glass = win.glass_area_m2 or 0.0
        if flat_id not in area_by_flat_dir:
            area_by_flat_dir[flat_id] = {}
        area_by_flat_dir[flat_id][cardinal] = (
            area_by_flat_dir[flat_id].get(cardinal, 0.0) + glass
        )

    # Assign dominant orientation
    for flat_id, dir_areas in area_by_flat_dir.items():
        flat = flat_by_id.get(flat_id)
        if flat is None or not dir_areas:
            continue
        flat.orientation = max(dir_areas, key=lambda d: dir_areas[d])
