"""SI 5282 H-indicator computation for residential dwelling units.

The H-indicator is the area-weighted mean thermal transmittance of all
boundary surfaces of a dwelling unit:

    H = Σ(U_i × A_i) / A_floor    [W/m²K]

Pass condition (new buildings):
    H_calculated ≤ H_required    (2.10 for ground/middle, 2.70 for top)

Data comes entirely from EnergyPlus SQL output (SimulationOutput), so no
additional IDF parsing is needed for U-values or areas.  The only IDF data
needed is frame conductance, supplied via idf_surface_parser.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

from il_energy.models import FlatEnergy, SimulationOutput
from il_energy.postprocessing.zone_aggregator import _parse_flat_and_floor


from il_energy import STANDARDS_DIR
_H_THRESHOLDS_PATH = STANDARDS_DIR / "h_thresholds.json"

# Fallback frame conductance (W/m²K) — aluminum without thermal break
_DEFAULT_FRAME_CONDUCTANCE = 5.8


# ── Data classes ──────────────────────────────────────────────────────────────


@dataclass
class HSurfaceRow:
    """One surface contribution to a unit's H calculation."""

    flat_id: str
    surface_name: str
    construction: str
    adjacency: str       # "Exterior" | "Semi-Exterior"
    surface_type: str    # "Wall" | "Roof" | "Floor" | "Glazing" | "Frame"
    net_area_m2: float
    um: float            # W/m²K (including film resistances)
    u_times_a: float     # W/K


@dataclass
class HValueUnit:
    """H-indicator result for one dwelling unit."""

    flat_id: str
    floor_type: str       # ground | middle | top | above_unconditioned
    floor_name: str       # display label e.g. "קומה 00"
    unit_name: str        # display label e.g. "1"
    unit_area_m2: float
    surfaces: List[HSurfaceRow] = field(default_factory=list)
    calculated_h: float = 0.0   # W/m²K
    required_h: float = 0.0     # W/m²K
    passes: bool = False


# ── Helpers ───────────────────────────────────────────────────────────────────


def _zone_to_flat(zone_name: str) -> Optional[str]:
    flat_id, _ = _parse_flat_and_floor(zone_name)
    return flat_id


def _flat_unit_number(flat_id: str) -> str:
    m = re.search(r"X(\d+\w*)$", flat_id, re.IGNORECASE)
    return m.group(1) if m else flat_id


def _flat_floor_label(flat_id: str) -> str:
    m = re.match(r"^(\d+)", flat_id)
    return m.group(1) if m else ""


def _surface_type_from_tilt(tilt_deg: Optional[float]) -> str:
    """Classify surface by tilt angle (0=horizontal roof, 90=vertical wall, 180=floor)."""
    if tilt_deg is None:
        return "Wall"
    if tilt_deg < 30:
        return "Roof"
    if tilt_deg > 150:
        return "Floor"
    return "Wall"


def _load_h_thresholds() -> Dict:
    if _H_THRESHOLDS_PATH.is_file():
        with open(_H_THRESHOLDS_PATH, encoding="utf-8") as f:
            return json.load(f)
    # Hardcoded fallback if file missing
    return {
        "new": {
            "ground": {"h_req": 2.10}, "middle": {"h_req": 2.10},
            "top": {"h_req": 2.70}, "above_unconditioned": {"h_req": 2.70},
        },
        "existing": {
            "ground": {"h_req": 2.30}, "middle": {"h_req": 2.30},
            "top": {"h_req": 3.00}, "above_unconditioned": {"h_req": 3.00},
        },
    }


def _h_required(floor_type: str, building_type: str, thresholds: Dict) -> float:
    """Look up required H for a floor type and building vintage."""
    vintage = thresholds.get(building_type, thresholds.get("new", {}))
    row = vintage.get(floor_type) or vintage.get("middle", {"h_req": 2.10})
    return row.get("h_req", 2.10)


# ── Public API ────────────────────────────────────────────────────────────────


def compute_h_value_units(
    output: SimulationOutput,
    flats: List[FlatEnergy],
    frame_conductances: Optional[Dict[str, float]] = None,
    building_type: str = "new",
) -> List[HValueUnit]:
    """Compute H-indicator for every dwelling unit.

    Args:
        output:              SimulationOutput from the proposed building run.
        flats:               FlatEnergy list (with floor_type, zones populated).
        frame_conductances:  {frame_name: conductance} from idf_surface_parser.
                             If None, all frames use the default 5.8 W/m²K.
        building_type:       "new" (default) or "existing" — selects H_req.

    Returns:
        List of HValueUnit, sorted by flat_id.
    """
    if frame_conductances is None:
        frame_conductances = {}

    thresholds = _load_h_thresholds()

    # ── Build zone → FlatEnergy lookup ───────────────────────────────────────
    zone_to_flat: Dict[str, FlatEnergy] = {}
    flat_by_id: Dict[str, FlatEnergy] = {}
    for flat in flats:
        flat_by_id[flat.flat_id] = flat
        for z in flat.zones:
            zone_to_flat[z.upper()] = flat

    # ── Initialise HValueUnit per flat ────────────────────────────────────────
    h_units: Dict[str, HValueUnit] = {}
    for flat in flats:
        if flat.floor_area_m2 <= 0:
            continue
        floor_lbl = _flat_floor_label(flat.flat_id)
        unit_lbl = _flat_unit_number(flat.flat_id)
        h_units[flat.flat_id] = HValueUnit(
            flat_id=flat.flat_id,
            floor_type=flat.floor_type,
            floor_name=f"קומה {floor_lbl}",
            unit_name=unit_lbl,
            unit_area_m2=flat.floor_area_m2,
            required_h=_h_required(flat.floor_type, building_type, thresholds),
        )

    # ── Add opaque surfaces (exterior + semi-exterior) ────────────────────────
    for surf in output.envelope_opaque:
        flat = zone_to_flat.get(surf.zone.upper())
        if flat is None or flat.flat_id not in h_units:
            continue
        if surf.u_factor_w_m2k is None or surf.gross_area_m2 is None:
            continue
        if surf.gross_area_m2 <= 0:
            continue

        stype = _surface_type_from_tilt(surf.tilt_deg)
        u_times_a = surf.u_factor_w_m2k * surf.gross_area_m2

        h_units[flat.flat_id].surfaces.append(HSurfaceRow(
            flat_id=flat.flat_id,
            surface_name=surf.name,
            construction=surf.construction,
            adjacency=surf.adjacency,
            surface_type=stype,
            net_area_m2=surf.gross_area_m2,
            um=surf.u_factor_w_m2k,
            u_times_a=u_times_a,
        ))

    # ── Add windows: Glazing row + Frame row ──────────────────────────────────
    for win in output.envelope_windows:
        flat = zone_to_flat.get(win.zone.upper())
        if flat is None or flat.flat_id not in h_units:
            continue
        if win.u_factor_w_m2k is None:
            continue

        # Glazing row
        glass_area = win.glass_area_m2 or 0.0
        if glass_area > 0:
            h_units[flat.flat_id].surfaces.append(HSurfaceRow(
                flat_id=flat.flat_id,
                surface_name=win.name,
                construction=win.construction,
                adjacency="Exterior",
                surface_type="Glazing",
                net_area_m2=glass_area,
                um=win.u_factor_w_m2k,
                u_times_a=win.u_factor_w_m2k * glass_area,
            ))

        # Frame row (if frame area exists)
        frame_area = win.frame_area_m2 or 0.0
        if frame_area > 0:
            # Find frame conductance by parent surface or construction name
            # WindowSurface doesn't carry frame_name directly from SQL —
            # use construction field as key, then fall back to default.
            frame_u = frame_conductances.get(
                win.construction, frame_conductances.get("default", _DEFAULT_FRAME_CONDUCTANCE)
            )
            h_units[flat.flat_id].surfaces.append(HSurfaceRow(
                flat_id=flat.flat_id,
                surface_name=win.name + "_frame",
                construction=win.construction + " (frame)",
                adjacency="Exterior",
                surface_type="Frame",
                net_area_m2=frame_area,
                um=frame_u,
                u_times_a=frame_u * frame_area,
            ))

    # ── Compute H per unit ────────────────────────────────────────────────────
    result: List[HValueUnit] = []
    for hu in sorted(h_units.values(), key=lambda x: x.flat_id):
        if not hu.surfaces:
            continue
        total_ua = sum(s.u_times_a for s in hu.surfaces)
        hu.calculated_h = total_ua / hu.unit_area_m2 if hu.unit_area_m2 > 0 else 0.0
        hu.passes = hu.calculated_h <= hu.required_h
        result.append(hu)

    return result


def write_h_values_csv(h_units: List[HValueUnit], output_path: Path) -> None:
    """Write per-surface H-value data to CSV (matches Evergreen ReportH layout)."""
    import csv

    columns = [
        "Floor Name", "Unit Name", "Unit Area {m2}",
        "Surface Name", "Construction", "Adjacency", "Surface Type",
        "Net Area {m2}", "Um {W/m2K}", "UxA {W/K}",
        "Calculated H {W/m2K}", "Required H {W/m2K}", "Pass",
    ]
    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(columns)
        for hu in h_units:
            for s in hu.surfaces:
                writer.writerow([
                    hu.floor_name,
                    hu.unit_name,
                    f"{hu.unit_area_m2:.2f}",
                    s.surface_name,
                    s.construction,
                    s.adjacency,
                    s.surface_type,
                    f"{s.net_area_m2:.3f}",
                    f"{s.um:.3f}",
                    f"{s.u_times_a:.3f}",
                    f"{hu.calculated_h:.3f}",
                    f"{hu.required_h:.2f}",
                    "Pass" if hu.passes else "Fail",
                ])
