"""Generate SI 5282 reference building IDF from a proposed IDF.

Strategy:
- Same geometry, zones, schedules, occupancy, HVAC as proposed
- Replace the exterior opaque constructions with reference U-value constructions
- Reference U-values are looked up by climate zone from REFERENCE_U_VALUES

NOTE: Reference U-values for Zone B are ESTIMATED (Grade D/E boundary).
Exact values require SI 5282 Tables G-1, D-1, D-3 from the full standard.
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
# ESTIMATED values for Zone B (Tel Aviv area), Grade D/E boundary.
# Full standard tables (G-1, D-1, D-3) will replace these estimates.
REFERENCE_U_VALUES: Dict[str, Dict[str, float]] = {
    "B": {
        "extwall":      1.20,   # Exterior wall (uninsulated concrete block)
        "extwallmamad": 1.20,   # Mamad/safe-room wall
        "flatroof":     1.30,   # Flat roof (uninsulated concrete slab)
        "groundfloor":  1.50,   # Ground floor (slab-on-grade)
        "extfloor":     1.30,   # Semi-exposed floor
    },
    # Zone A (hot-arid, Eilat) — placeholder, requires standard tables
    "A": {
        "extwall":      1.40,
        "extwallmamad": 1.40,
        "flatroof":     1.40,
        "groundfloor":  1.60,
        "extfloor":     1.40,
    },
    # Zone C (temperate, Jerusalem) — placeholder, requires standard tables
    "C": {
        "extwall":      0.80,
        "extwallmamad": 0.80,
        "flatroof":     0.70,
        "groundfloor":  1.20,
        "extfloor":     0.80,
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
        "! VALUES ARE ESTIMATED — awaiting full standard Tables G-1, D-1, D-3",
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


def _replace_constructions_in_idf(
    text: str,
    construction_map: Dict[str, str],
) -> Tuple[str, Dict[str, int]]:
    """Replace construction names in BuildingSurface:Detailed objects.

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
        # BuildingSurface:Detailed field layout (DesignBuilder IDF convention):
        # line 0: "BuildingSurface:Detailed,"
        # line 1: Name field
        # line 2: Surface Type field
        # line 3: Construction Name field  ← replace here
        field_idx = 3
        if len(lines) > field_idx:
            line = lines[field_idx]
            for proposed, ref in construction_map.items():
                if re.search(rf"\b{re.escape(proposed)}\b", line, re.IGNORECASE):
                    lines[field_idx] = re.sub(
                        rf"\b{re.escape(proposed)}\b",
                        ref,
                        line,
                        flags=re.IGNORECASE,
                    )
                    counts[proposed] += 1
                    break
        return "\n".join(lines)

    pattern = re.compile(
        r"BuildingSurface:Detailed,.*?(?=\n\s*\n\s*[A-Za-z]|\Z)",
        re.DOTALL,
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

    # Discover all unique construction names used in BuildingSurface:Detailed
    bsd_pattern = re.compile(
        r"BuildingSurface:Detailed,.*?(?=\n\s*\n\s*[A-Za-z]|\Z)",
        re.DOTALL,
    )
    used_constructions: set = set()
    for m in bsd_pattern.finditer(text):
        lines = m.group(0).split("\n")
        if len(lines) > 3:
            line = lines[3]
            # Extract construction name (value before comma or semicolon)
            name_match = re.search(r"^\s*([^,;!]+)", line)
            if name_match:
                used_constructions.add(name_match.group(1).strip())

    if not used_constructions:
        raise IDFError("No BuildingSurface:Detailed constructions found in IDF.")

    # Match each used construction to a reference U-value
    construction_map: Dict[str, str] = {}   # proposed_name → ref_name
    constructions_info: Dict[str, dict] = {}

    for const_name in sorted(used_constructions):
        key = _match_construction_type(const_name, climate_zone)
        if key is None:
            continue  # Not an exterior opaque construction we replace
        u_target = REFERENCE_U_VALUES[climate_zone][key]
        r_mat = max(0.01, 1.0 / u_target - R_FILMS)
        ref_name = f"REF_{const_name}"
        construction_map[const_name] = ref_name
        constructions_info[const_name] = {
            "ref_name": ref_name,
            "u_target": u_target,
            "r_mat": r_mat,
        }

    if not construction_map:
        raise IDFError(
            f"No constructions matched reference U-value keywords for zone {climate_zone}. "
            "Check that construction names contain keywords like 'extwall', 'flatroof', etc."
        )

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
        "u_values_estimated": True,  # Until full standard tables are available
    }
