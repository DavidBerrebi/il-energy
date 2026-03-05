"""Zone-to-flat aggregation for residential buildings."""

from __future__ import annotations

import re
from typing import Callable, Dict, List, Optional

from il_energy.models import FlatEnergy, ZoneEnergy


def _default_flat_extractor(zone_name: str) -> Optional[str]:
    """Extract flat ID from zone name using common patterns.

    Tries patterns like:
    - "FF01:LIVING" → "FF01"
    - "FLAT_3_BEDROOM" → "FLAT_3"
    - "APT-2A:KITCHEN" → "APT-2A"
    - Falls back to zone name if no separator found.
    """
    # Pattern: PREFIX:ROOM or PREFIX_ROOM
    match = re.match(r"^([A-Za-z]+\d+[A-Za-z]*)[:_]", zone_name)
    if match:
        return match.group(1)

    # Pattern: FLAT/APT prefix with number
    match = re.match(r"^((?:FLAT|APT|UNIT|FF)\S*?)[:_\s]", zone_name, re.IGNORECASE)
    if match:
        return match.group(1)

    return None


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
    extractor = flat_extractor or _default_flat_extractor

    flat_map: Dict[str, FlatEnergy] = {}

    for zone in zones:
        flat_id = extractor(zone.zone_name)
        if flat_id is None:
            continue

        if flat_id not in flat_map:
            flat_map[flat_id] = FlatEnergy(flat_id=flat_id)

        flat = flat_map[flat_id]
        flat.zones.append(zone.zone_name)
        flat.floor_area_m2 += zone.floor_area_m2
        flat.heating_kwh += zone.heating_kwh
        flat.cooling_kwh += zone.cooling_kwh
        flat.total_kwh += zone.total_kwh

    # Compute per-m² values
    for flat in flat_map.values():
        if flat.floor_area_m2 > 0:
            flat.heating_kwh_per_m2 = flat.heating_kwh / flat.floor_area_m2
            flat.cooling_kwh_per_m2 = flat.cooling_kwh / flat.floor_area_m2
            flat.total_kwh_per_m2 = flat.total_kwh / flat.floor_area_m2

    return list(flat_map.values())
