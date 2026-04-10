"""Shared zone/flat naming utilities.

Provides canonical implementations of flat_id parsing, floor extraction,
and orientation helpers used across multiple modules (windows, h_value,
zone_aggregator, report generator).
"""

from __future__ import annotations

import re
from typing import Optional, Tuple


def parse_flat_and_floor(zone_name: str) -> Tuple[Optional[str], Optional[int]]:
    """Parse flat ID and floor number from a zone name.

    Returns (flat_id, floor_number) or (None, None) if the zone is not
    associated with a residential flat (e.g., corridors, core zones).

    Supported patterns:
    - Nili-style digit-first:  ``"00X1:LIVING"`` → ``("00X1", 0)``
    - Letter-first:            ``"FF01:LIVING"``  → ``("FF01", None)``
    - FLAT/APT/UNIT prefix:    ``"FLAT_3:BEDROOM"`` → ``("FLAT", None)``
    - Core/corridor exclusion: ``"COREX00:..."`` → ``(None, None)``
    """
    # Nili-style: "{floor_2dig}X{unit}:{room}"
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


def zone_to_flat(zone_name: str) -> Optional[str]:
    """Return flat_id for a zone, or None for corridors/unknowns."""
    flat_id, _ = parse_flat_and_floor(zone_name)
    return flat_id


def flat_unit_number(flat_id: str) -> str:
    """Extract the unit number suffix from a flat_id.

    Example: ``"00X1"`` → ``"1"``, ``"06X2"`` → ``"2"``.
    Returns the full flat_id if the pattern doesn't match.
    """
    match = re.search(r"X(\d+\w*)$", flat_id, re.IGNORECASE)
    return match.group(1) if match else flat_id


def flat_floor_label(flat_id: str) -> str:
    """Extract the floor prefix from a flat_id.

    Example: ``"00X1"`` → ``"00"``, ``"06X2"`` → ``"06"``.
    Returns empty string if no leading digits found.
    """
    match = re.match(r"^(\d+)", flat_id)
    return match.group(1) if match else ""


def orientation_label_8dir(azimuth_deg: Optional[float]) -> str:
    """Convert azimuth (0=N, CW) to 8-direction compass label.

    Returns one of: N, NE, E, SE, S, SW, W, NW, or empty string if None.
    """
    if azimuth_deg is None:
        return ""
    azimuth = azimuth_deg % 360
    if azimuth < 22.5 or azimuth >= 337.5:
        return "N"
    if azimuth < 67.5:
        return "NE"
    if azimuth < 112.5:
        return "E"
    if azimuth < 157.5:
        return "SE"
    if azimuth < 202.5:
        return "S"
    if azimuth < 247.5:
        return "SW"
    if azimuth < 292.5:
        return "W"
    return "NW"


def azimuth_to_cardinal(azimuth_deg: float) -> str:
    """Convert azimuth (0=N, CW) to 4-direction cardinal letter (N/E/S/W)."""
    azimuth = azimuth_deg % 360.0
    if azimuth < 45 or azimuth >= 315:
        return "N"
    if azimuth < 135:
        return "E"
    if azimuth < 225:
        return "S"
    return "W"
