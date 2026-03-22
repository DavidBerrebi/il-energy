
"""Zone-to-flat aggregation for residential buildings."""

from __future__ import annotations

import re
from typing import Callable, Dict, List, Optional, Tuple

from il_energy.models import FlatEnergy, ZoneEnergy


def _parse_flat_and_floor(zone_name: str) -> Tuple[Optional[str], Optional[int]]:
    """Parse flat ID and floor number from zone name.

    Returns (flat_id, floor_number) or (None, None) if not a flat zone.

    Supports:
    - Nili-style digit-first:  "00X1:LIVING" → ("00X1", 0)
    - Letter-first:            "FF01:LIVING"  → ("FF01", None)
    - FLAT/APT prefix:         "FLAT_3_BEDROOM" → ("FLAT_3", None)
    - Core/corridor exclusion: "COREX00:..." → (None, None)
    """
    # Nili-style: "{floor_2dig}X{unit}:{room}" e.g. "00X1:LIVING", "06X2:SERVICE"
    match = re.match(r"^(\d{2}X\d+):", zone_name)
    if match:
        flat_id = match.group(1)
        floor_num = int(flat_id[:2])
        return flat_id, floor_num

    # Explicit corridor/core exclusion
    if re.match(r"^CORE", zone_name, re.IGNORECASE):
        return None, None

    # Generic letter-first prefix: "FF01:LIVING" → "FF01"
    match = re.match(r"^([A-Za-z]+\d+[A-Za-z]*)[:_]", zone_name)
    if match:
        return match.group(1), None

    # FLAT/APT/UNIT prefix
    match = re.match(r"^((?:FLAT|APT|UNIT|FF)\S*?)[:_\s]", zone_name, re.IGNORECASE)
    if match:
        return match.group(1), None

    return None, None


def _default_flat_extractor(zone_name: str) -> Optional[str]:
    """Extract flat ID from zone name (legacy interface)."""
    flat_id, _ = _parse_flat_and_floor(zone_name)
    return flat_id


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
