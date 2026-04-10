"""Window and envelope surface analysis for SI 5282 reporting.

Extracts per-unit window properties (U, SHGC, VT, orientation, WWR)
from a SimulationOutput and produces structured records matching the
expert `windows.csv` format.
"""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Dict, List, Optional

from il_energy.models import EnvelopeSurface, SimulationOutput, WindowSurface
from il_energy.utils.zone_naming import (
    flat_floor_label as _flat_floor,
    flat_unit_number as _flat_unit_number,
    orientation_label_8dir as _orientation_label,
    zone_to_flat as _zone_to_flat,
)


def build_window_records(
    output: SimulationOutput,
    shading_ctrl_names: Optional[set] = None,
) -> List[Dict]:
    """Build per-surface window records from a SimulationOutput.

    Covers both glazing surfaces (with U/SHGC/VT data) and opaque exterior
    surfaces (adjacency only), matching the expert windows.csv layout.

    Args:
        output: SimulationOutput from extract_metrics().
        shading_ctrl_names: Set of window surface names that have a shading
            control object assigned.  If None, the field is left empty.

    Returns:
        List of dicts with keys matching the expert windows.csv columns.
        Sorted by flat_id then surface name.
    """
    if shading_ctrl_names is None:
        shading_ctrl_names = set()

    # Build flat-area lookup from zones
    flat_area: Dict[str, float] = {}
    for zone in output.zones:
        fid = _zone_to_flat(zone.zone_name)
        if fid:
            flat_area[fid] = flat_area.get(fid, 0.0) + zone.floor_area_m2

    records: List[Dict] = []

    # ── Fenestration surfaces ─────────────────────────────────────────────────
    # Compute per-flat gross wall area for WWR denominator
    flat_wall_area: Dict[str, float] = {}
    flat_window_area: Dict[str, float] = {}

    for surf in output.envelope_opaque:
        if surf.adjacency != "Exterior":
            continue  # semi-exterior walls excluded from WWR denominator
        if surf.tilt_deg is None or surf.tilt_deg < 45:
            continue  # skip horizontal surfaces (roofs, floors)
        fid = _zone_to_flat(surf.zone)
        if fid is None:
            continue
        flat_wall_area[fid] = flat_wall_area.get(fid, 0.0) + (surf.gross_area_m2 or 0.0)

    for win in output.envelope_windows:
        fid = _zone_to_flat(win.zone)
        if fid is None:
            continue
        flat_window_area[fid] = flat_window_area.get(fid, 0.0) + (win.glass_area_m2 or 0.0)
        # Add window area to wall gross area denominator too
        flat_wall_area[fid] = flat_wall_area.get(fid, 0.0) + (win.glass_area_m2 or 0.0)

    # ── Build opaque surface records ──────────────────────────────────────────
    for surf in output.envelope_opaque:
        fid = _zone_to_flat(surf.zone)
        if fid is None:
            continue
        records.append({
            "Floor Name": _flat_floor(fid),
            "Unit Name": _flat_unit_number(fid),
            "Unit Orientation": "",
            "Unit Area {m2}": f"{flat_area.get(fid, 0.0):.2f}",
            "Surface Name": surf.name,
            "Construction": surf.construction,
            "Adjacency": surf.adjacency,
            "Area (Net) {m2}": f"{surf.gross_area_m2:.2f}" if surf.gross_area_m2 else "",
            "Um": f"{surf.u_factor_w_m2k:.2f}" if surf.u_factor_w_m2k else "",
            "Glass SHGC": "",
            "Glass Visible Transmittance": "",
            "Window Shading Control": "",
            "Window Orientation": "",
            "WWR": "",
            "_flat_id": fid,
            "_is_window": False,
        })

    # ── Build fenestration records ────────────────────────────────────────────
    for win in output.envelope_windows:
        fid = _zone_to_flat(win.zone)
        if fid is None:
            continue

        # WWR = total window area / total wall+window area for this flat
        total_wall = flat_wall_area.get(fid, 0.0)
        wwr = (flat_window_area.get(fid, 0.0) / total_wall) if total_wall > 0 else 0.0

        has_shading = "Yes" if win.name.upper() in {n.upper() for n in shading_ctrl_names} else "No"

        records.append({
            "Floor Name": _flat_floor(fid),
            "Unit Name": _flat_unit_number(fid),
            "Unit Orientation": "",
            "Unit Area {m2}": f"{flat_area.get(fid, 0.0):.2f}",
            "Surface Name": win.name,
            "Construction": win.construction,
            "Adjacency": "Exterior",
            "Area (Net) {m2}": f"{win.glass_area_m2:.2f}" if win.glass_area_m2 else "",
            "Um": f"{win.u_factor_w_m2k:.2f}" if win.u_factor_w_m2k else "",
            "Glass SHGC": f"{win.shgc:.2f}" if win.shgc else "",
            "Glass Visible Transmittance": f"{win.visible_transmittance:.2f}" if win.visible_transmittance else "",
            "Window Shading Control": has_shading if shading_ctrl_names else "",
            "Window Orientation": str(int(win.azimuth_deg)) if win.azimuth_deg is not None else "",
            "WWR": f"{wwr:.2f}",
            "_flat_id": fid,
            "_is_window": True,
        })

    # Sort by flat_id then surface name
    records.sort(key=lambda r: (r["_flat_id"], r["Surface Name"]))
    return records


def write_windows_csv(records: List[Dict], output_path: Path) -> None:
    """Write window records to CSV, matching the expert windows.csv format."""
    columns = [
        "Floor Name", "Unit Name", "Unit Orientation", "Unit Area {m2}",
        "Surface Name", "Construction", "Adjacency", "Area (Net) {m2}",
        "Um", "Glass SHGC", "Glass Visible Transmittance",
        "Window Shading Control", "Window Orientation", "WWR",
    ]
    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(records)


def window_summary_by_flat(records: List[Dict]) -> Dict[str, Dict]:
    """Aggregate per-flat window statistics from window records.

    Returns dict keyed by flat_id with:
        window_count, total_glass_area_m2, avg_u, avg_shgc,
        orientation_breakdown (dict compass→area_m2), wwr
    """
    summary: Dict[str, Dict] = {}

    for rec in records:
        if not rec.get("_is_window"):
            continue
        fid = rec["_flat_id"]
        if fid not in summary:
            summary[fid] = {
                "window_count": 0,
                "total_glass_area_m2": 0.0,
                "u_sum": 0.0,
                "shgc_sum": 0.0,
                "orientation_area": {},
                "wwr": 0.0,
            }
        s = summary[fid]
        area = float(rec["Area (Net) {m2}"] or 0)
        u = float(rec["Um"] or 0)
        shgc = float(rec["Glass SHGC"] or 0)
        orient = _orientation_label(
            float(rec["Window Orientation"]) if rec["Window Orientation"] else None
        )

        s["window_count"] += 1
        s["total_glass_area_m2"] += area
        s["u_sum"] += u * area
        s["shgc_sum"] += shgc * area
        s["orientation_area"][orient] = s["orientation_area"].get(orient, 0.0) + area
        s["wwr"] = float(rec["WWR"] or 0)

    # Compute area-weighted averages
    for fid, s in summary.items():
        total = s["total_glass_area_m2"]
        s["avg_u"] = s["u_sum"] / total if total > 0 else 0.0
        s["avg_shgc"] = s["shgc_sum"] / total if total > 0 else 0.0

    return summary
