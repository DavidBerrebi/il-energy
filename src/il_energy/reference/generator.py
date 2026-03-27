"""Generate SI 5282 reference building IDF from a proposed IDF.

Strategy:
- Same geometry, zones, schedules, occupancy, HVAC as proposed
- Replace the exterior opaque constructions with reference U-value constructions
- Reference U-values are taken from SI 5282 Part 1 Table ג-1 (February 2023)

IMPORTANT — Reference building methodology note:
  SI 5282 Part 1 (residential) defines the reference unit (יחידת הייחוס) as a
  standardized 100 m² box (10×10×3 m) with one glazed wall (U=4.0, SHGC=0.63),
  run 4 times facing each cardinal direction, EPref = average ÷ COP (3.0).
  This generator instead applies the reference construction R-values from Table ג-1
  to the PROPOSED building's geometry — an approximation suitable for commercial
  buildings (SI 5282 Part 2) or for a quick first-pass on residential buildings.

Zone naming — this file uses the Amendment naming convention:
  Zone A = Eilat (extreme hot-arid)   → maps to Standard Part 1 Zone D
  Zone B = Tel Aviv coastal (hot-humid) → maps to Standard Part 1 Zone A
  Zone C = Jerusalem (temperate)       → maps to Standard Part 1 Zone C

Source: SI 5282 Part 1, Table ג-1, page 43. R-values are material resistance
[m²K/W] without film. U_with_film = 1 / (r_material + R_FILMS).
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from il_energy.exceptions import IDFError

# Air film resistances (inside + outside) for opaque surfaces, m²K/W
R_FILMS = 0.17

# ── Reference U-values by climate zone ────────────────────────────────────────
# Maps climate_zone → { construction_keyword → U_target (W/m²K) }
# Keys are substrings matched against construction names (case-insensitive).
# More specific keys should come first.
#
# Source: SI 5282 Part 1, Table ג-1 (February 2023), page 43.
# R_material values (m²K/W) from the standard, converted to U_with_film using:
#   U = 1 / (r_material + R_FILMS)  where R_FILMS = 0.17 m²K/W
#
# Zone mapping (this file → SI 5282 Part 1 standard zone):
#   Our A (Eilat)     → Standard Zone D: r_wall=0.89, r_roof=1.51, r_open_floor=1.04, r_ground=0.68
#   Our B (Tel Aviv)  → Standard Zone A: r_wall=0.63, r_roof=1.51, r_open_floor=0.67, r_ground=0.68
#   Our C (Jerusalem) → Standard Zone C: r_wall=0.80, r_roof=1.51, r_open_floor=1.04, r_ground=0.68
#
# Note: "top ceiling" (roof) has r=1.51 for ALL zones in the standard —
# the reference roof is INSULATED (55mm insulation + 140mm concrete slab).
REFERENCE_U_VALUES: Dict[str, Dict[str, float]] = {
    # Zone B (Tel Aviv coastal, hot-humid) → Standard Part 1 Zone A
    # r_wall=0.63, r_roof=1.51, r_open_floor=0.67, r_ground=0.68
    "B": {
        "extwall":      round(1.0 / (0.63 + R_FILMS), 4),  # 1.2500 W/m²K  (22cm concrete block, no added insulation)
        "extwallmamad": round(1.0 / (0.63 + R_FILMS), 4),  # 1.2500 W/m²K  (same as extwall)
        "flatroof":     round(1.0 / (1.51 + R_FILMS), 4),  # 0.5952 W/m²K  (insulated: 55mm XPS + 140mm slab)
        "groundfloor":  round(1.0 / (0.68 + R_FILMS), 4),  # 1.1765 W/m²K  (20mm insulation + 200mm slab; all zones same)
        "extfloor":     round(1.0 / (0.67 + R_FILMS), 4),  # 1.1905 W/m²K  (floor above open space, Zone A value)
    },
    # Zone A (Eilat, extreme hot-arid) → Standard Part 1 Zone D
    # r_wall=0.89, r_roof=1.51, r_open_floor=1.04, r_ground=0.68
    "A": {
        "extwall":      round(1.0 / (0.89 + R_FILMS), 4),  # 0.9434 W/m²K  (29cm concrete block)
        "extwallmamad": round(1.0 / (0.89 + R_FILMS), 4),  # 0.9434 W/m²K
        "flatroof":     round(1.0 / (1.51 + R_FILMS), 4),  # 0.5952 W/m²K  (same for all zones)
        "groundfloor":  round(1.0 / (0.68 + R_FILMS), 4),  # 1.1765 W/m²K  (all zones same)
        "extfloor":     round(1.0 / (1.04 + R_FILMS), 4),  # 0.8264 W/m²K  (Zone D value, same as Zone C)
    },
    # Zone C (Jerusalem, temperate) → Standard Part 1 Zone C
    # r_wall=0.80, r_roof=1.51, r_open_floor=1.04, r_ground=0.68
    "C": {
        "extwall":      round(1.0 / (0.80 + R_FILMS), 4),  # 1.0309 W/m²K  (26cm concrete block)
        "extwallmamad": round(1.0 / (0.80 + R_FILMS), 4),  # 1.0309 W/m²K
        "flatroof":     round(1.0 / (1.51 + R_FILMS), 4),  # 0.5952 W/m²K  (same for all zones)
        "groundfloor":  round(1.0 / (0.68 + R_FILMS), 4),  # 1.1765 W/m²K  (all zones same)
        "extfloor":     round(1.0 / (1.04 + R_FILMS), 4),  # 0.8264 W/m²K  (Zone C/D value)
    },
}


def _match_construction_type(construction_name: str, zone: str) -> Optional[str]:
    """Return the matched key from REFERENCE_U_VALUES for a construction name.

    Matches from most-specific to least-specific keyword.
    Returns None if no match found.
    """
    name_lower = construction_name.lower()
    u_map = REFERENCE_U_VALUES.get(zone, {})
    # Sort by length descending so longer (more specific) keys match first
    for key in sorted(u_map.keys(), key=len, reverse=True):
        if key in name_lower:
            return key
    return None


def _surface_type_to_ref_key(surface_type: str, boundary: str) -> Optional[str]:
    """Map (EnergyPlus surface type, boundary condition) → reference key.

    This allows construction identification based on how a surface is used
    in the building model rather than by construction name keywords — making
    the generator work regardless of the project's naming conventions.

    surface_type: first field in the BSD "Class and Construction Name" line
                  (e.g. "Wall", "Ceiling", "Floor", "Roof", "Window")
    boundary:     first field in the "Outside Face Environment" line
                  (e.g. "Outdoors", "Ground", "Surface", "OtherSideCoefficients")
    """
    st = surface_type.strip().lower()
    bc = boundary.strip().lower()

    if st == "wall" and bc == "outdoors":
        return "extwall"
    if st in ("ceiling", "roof") and bc == "outdoors":
        return "flatroof"
    if st == "floor" and bc == "ground":
        return "groundfloor"
    if st == "floor" and bc == "outdoors":
        return "extfloor"
    # Interior surfaces (Surface/OtherSide/Zone) — not replaced
    return None


def _parse_bsd_surface_info(block: str) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    """Extract (construction_name, surface_type, boundary_condition) from a BSD block.

    Handles both standard (one-field-per-line) and compact (Type, Construction
    on one line) DesignBuilder export formats.

    Returns (construction_name, surface_type, boundary_condition).
    Any or all may be None if not found.
    """
    lines = block.split("\n")
    construction: Optional[str] = None
    surface_type: Optional[str] = None
    boundary: Optional[str] = None

    for line in lines[1:]:
        stripped = line.strip()
        bang = stripped.find("!")
        comment = stripped[bang:].lower() if bang >= 0 else ""
        value_part = stripped[:bang].strip() if bang >= 0 else stripped

        if "construction name" in comment:
            # Could be "SurfaceType, ConstructionName" (compact) or just "ConstructionName"
            fields = [f.strip().rstrip(",;") for f in value_part.split(",") if f.strip()]
            if len(fields) >= 2:
                surface_type = fields[0]
                construction = fields[-1]
            elif len(fields) == 1:
                construction = fields[0]

        elif "surface type" in comment or "class" in comment:
            # Standard format where surface type is on its own line
            fields = [f.strip().rstrip(",;") for f in value_part.split(",") if f.strip()]
            if fields:
                surface_type = fields[0]

        elif "outside face" in comment or "boundary condition" in comment:
            # "Surface, AdjacentSurfaceName" or "Outdoors" or "Ground"
            fields = [f.strip().rstrip(",;") for f in value_part.split(",") if f.strip()]
            if fields:
                boundary = fields[0]

    return construction, surface_type, boundary


def _build_ref_objects(
    construction_map: Dict[str, Tuple[str, float]],
    zone: str,
) -> str:
    """Build IDF text for reference Material:NoMass + Construction objects.

    Args:
        construction_map: Maps proposed_name → (ref_name, U_target)
        zone: Climate zone string (e.g. "B")

    Returns:
        Multi-line IDF object string to inject.
    """
    lines: List[str] = [
        "",
        "! ============================================================",
        f"! SI 5282 Reference Building Constructions — Climate Zone {zone}",
        "! U-values from SI 5282 Part 1, Table G-1 (February 2023), page 43",
        "! ============================================================",
        "",
    ]
    seen_refs: set = set()
    for proposed_name, (ref_name, u_target) in construction_map.items():
        if ref_name in seen_refs:
            continue
        seen_refs.add(ref_name)
        r_mat = max(0.01, 1.0 / u_target - R_FILMS)
        mat_name = f"MAT_{ref_name}"
        lines += [
            "  Material:NoMass,",
            f"    {mat_name},          !- Name",
            "    MediumRough,           !- Roughness",
            f"    {r_mat:.4f},           !- Thermal Resistance {{m2-K/W}}  [U_target={u_target:.2f} W/m2K]",
            "    0.9,                   !- Thermal Absorptance",
            "    0.6,                   !- Solar Absorptance",
            "    0.6;                   !- Visible Absorptance",
            "",
            "  Construction,",
            f"    {ref_name},   !- Name",
            f"    {mat_name};   !- Outside Layer",
            "",
        ]
    return "\n".join(lines)


def _extract_bsd_construction(lines: List[str]) -> Optional[str]:
    """Extract construction name from a BuildingSurface:Detailed block's lines.

    Handles two DesignBuilder export formats:
      Standard (EP ≥ 8.x one-field-per-line):
        lines[2] = Surface Type
        lines[3] = Construction Name           ← single field
      Compact (EP 9.x combined field):
        lines[2] = "SurfaceType, ConstructionName,  !- Class and Construction Name"
                                                ← two fields on one line

    Returns the construction name string, or None if not found.
    """
    # Scan each line for a "Construction Name" comment clue
    for line in lines[1:]:  # skip the 'BuildingSurface:Detailed,' header
        stripped = line.strip()
        bang = stripped.find("!")
        comment = stripped[bang:].lower() if bang >= 0 else ""
        if "construction name" in comment:
            # Extract the value portion (before '!')
            value_part = stripped[:bang] if bang >= 0 else stripped
            fields = [f.strip().rstrip(",;") for f in value_part.split(",") if f.strip()]
            if fields:
                return fields[-1]  # last field = construction name (handles combined line)

    # Fallback: standard format — construction name on line index 3
    if len(lines) > 3:
        name_match = re.search(r"^\s*([^,;!]+)", lines[3])
        if name_match:
            return name_match.group(1).strip()

    return None


def _replace_constructions_in_idf(
    text: str,
    construction_map: Dict[str, str],
) -> Tuple[str, Dict[str, int]]:
    """Replace construction names in BuildingSurface:Detailed objects.

    Handles both standard (one-field-per-line) and compact (Type, Construction
    on one line) DesignBuilder IDF export formats.

    Args:
        text: Full IDF text.
        construction_map: Maps proposed_name → ref_name (exact, case-insensitive match).

    Returns:
        (modified_text, counts) where counts maps proposed_name → surfaces replaced.
    """
    counts: Dict[str, int] = {k: 0 for k in construction_map}

    def _replace_block(m: re.Match) -> str:
        block = m.group(0)
        lines = block.split("\n")

        for i, line in enumerate(lines[1:], 1):  # skip header line
            stripped = line.strip()
            bang = stripped.find("!")
            comment = stripped[bang:].lower() if bang >= 0 else ""
            if "construction name" not in comment:
                continue
            # This line contains the construction name.
            # Sort by length descending so longer (more specific) names match first,
            # avoiding partial replacement of "EG_FOO BAR" when "EG_FOO" is also a key.
            for proposed, ref in sorted(construction_map.items(), key=lambda kv: len(kv[0]), reverse=True):
                pat = rf"(?<![A-Za-z0-9_]){re.escape(proposed)}(?![A-Za-z0-9_])"
                if re.search(pat, line, re.IGNORECASE):
                    lines[i] = re.sub(pat, ref, line, flags=re.IGNORECASE)
                    counts[proposed] += 1
                    return "\n".join(lines)  # only one construction per block
            break  # found the construction line but no match — no further search

        # Fallback: try line index 3 (standard format without comments)
        field_idx = 3
        if len(lines) > field_idx:
            line = lines[field_idx]
            for proposed, ref in sorted(construction_map.items(), key=lambda kv: len(kv[0]), reverse=True):
                pat = rf"(?<![A-Za-z0-9_]){re.escape(proposed)}(?![A-Za-z0-9_])"
                if re.search(pat, line, re.IGNORECASE):
                    lines[field_idx] = re.sub(pat, ref, line, flags=re.IGNORECASE)
                    counts[proposed] += 1
                    break
        return "\n".join(lines)

    pattern = re.compile(
        r"BuildingSurface:Detailed\s*,[^;]+;",
        re.DOTALL | re.IGNORECASE,
    )
    text = pattern.sub(_replace_block, text)
    return text, counts


def generate_reference_idf(
    proposed_idf: Path,
    output_idf: Path,
    climate_zone: str = "B",
) -> Dict[str, object]:
    """Generate a SI 5282 reference building IDF from a proposed IDF.

    Reads the proposed IDF, identifies exterior opaque constructions, replaces
    them with reference constructions at standard-prescribed U-values, and writes
    the modified IDF to output_idf.

    Args:
        proposed_idf: Path to the proposed building IDF.
        output_idf: Path where the reference IDF will be written.
        climate_zone: SI 5282 climate zone ("A", "B", or "C").

    Returns:
        dict with keys:
            - "climate_zone": str
            - "replacements": dict mapping proposed_name → count of surfaces replaced
            - "constructions": dict mapping proposed_name → {ref_name, u_target, r_mat}
            - "u_values_estimated": bool (True = not from full standard tables)

    Raises:
        IDFError: If the proposed IDF is not found or has no replaceable constructions.
        ValueError: If the climate zone is not supported.
    """
    proposed_idf = Path(proposed_idf)
    output_idf = Path(output_idf)

    if not proposed_idf.is_file():
        raise IDFError(f"Proposed IDF not found: {proposed_idf}")

    if climate_zone not in REFERENCE_U_VALUES:
        supported = ", ".join(sorted(REFERENCE_U_VALUES.keys()))
        raise ValueError(f"Unsupported climate zone '{climate_zone}'. Supported: {supported}")

    text = proposed_idf.read_text(encoding="utf-8", errors="replace")

    # Discover constructions used in BuildingSurface:Detailed and map them to
    # reference types using surface_type + boundary_condition analysis.
    # This approach works regardless of construction naming conventions.
    # Fallback to keyword matching for constructions whose surface context is
    # ambiguous (e.g. old standard-format IDFs without comments).
    #
    # Use semicolons as block delimiters (every IDF object ends with ';') —
    # more robust than blank-line lookahead since comment lines between blocks
    # would break the blank-line pattern.
    bsd_pattern = re.compile(
        r"BuildingSurface:Detailed\s*,[^;]+;",
        re.DOTALL | re.IGNORECASE,
    )

    # const_name → best ref_key found across all surfaces using this construction
    const_ref_key: Dict[str, str] = {}

    for m in bsd_pattern.finditer(text):
        const_name, surf_type, boundary = _parse_bsd_surface_info(m.group(0))
        if not const_name:
            continue

        # Primary: determine reference type from how the surface is used
        ref_key: Optional[str] = None
        if surf_type and boundary:
            ref_key = _surface_type_to_ref_key(surf_type, boundary)

        # Fallback: keyword matching on construction name
        if ref_key is None:
            ref_key = _match_construction_type(const_name, climate_zone)

        if ref_key is not None:
            # If a construction is used as both an exterior wall and something else,
            # prefer the existing assignment to avoid overwriting.
            if const_name not in const_ref_key:
                const_ref_key[const_name] = ref_key

    if not const_ref_key:
        raise IDFError(
            f"No exterior opaque constructions found for zone {climate_zone}. "
            "Expected exterior Wall/Ceiling/Floor surfaces in BuildingSurface:Detailed."
        )

    # Build construction map and info
    construction_map: Dict[str, str] = {}   # proposed_name → ref_name
    constructions_info: Dict[str, dict] = {}

    for const_name, ref_key in sorted(const_ref_key.items()):
        u_target = REFERENCE_U_VALUES[climate_zone][ref_key]
        r_mat = max(0.01, 1.0 / u_target - R_FILMS)
        ref_name = f"REF_{ref_key.upper()}"  # e.g. REF_EXTWALL (shared across all walls)
        construction_map[const_name] = ref_name
        constructions_info[const_name] = {
            "ref_name": ref_name,
            "u_target": u_target,
            "r_mat": r_mat,
            "ref_key": ref_key,
        }

    # Build map of proposed_name → (ref_name, u_target) for object generation
    ref_obj_map = {
        proposed: (info["ref_name"], info["u_target"])
        for proposed, info in constructions_info.items()
    }

    # Replace construction references in BuildingSurface:Detailed objects
    modified, counts = _replace_constructions_in_idf(text, construction_map)

    # Inject reference material + construction objects before HeatBalanceAlgorithm
    ref_objects_text = _build_ref_objects(ref_obj_map, climate_zone)
    inject_marker = "  HeatBalanceAlgorithm,"
    if inject_marker in modified:
        modified = modified.replace(inject_marker, ref_objects_text + "\n" + inject_marker, 1)
    else:
        modified += ref_objects_text

    # Ensure Output:SQLite is present (needed for SQL parser)
    if "Output:SQLite" not in modified:
        modified += "\nOutput:SQLite,\n  SimpleAndTabular;\n"

    output_idf.parent.mkdir(parents=True, exist_ok=True)
    output_idf.write_text(modified, encoding="utf-8")

    return {
        "climate_zone": climate_zone,
        "replacements": counts,
        "constructions": constructions_info,
        "u_values_estimated": False,  # From SI 5282 Part 1 Table ג-1 (Feb 2023)
    }
