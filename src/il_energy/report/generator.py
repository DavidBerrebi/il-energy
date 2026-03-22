"""Professional SI 5282 residential report generator.

Produces three output files:
  residential_report.md  — formatted Markdown report
  units.csv              — per-unit grades (matches expert output.csv format)
  windows.csv            — window/surface analysis (matches expert windows.csv)
"""

from __future__ import annotations

import csv
import re
from datetime import date
from pathlib import Path
from typing import Dict, List, Optional

from il_energy.analysis.windows import build_window_records, window_summary_by_flat, write_windows_csv
from il_energy.models import SimulationOutput


# Grade ↔ numeric score mappings
_SCORE_TO_GRADE = {5: "A+", 4: "A", 3: "B", 2: "C", 1: "D", 0: "E", -1: "F"}
_GRADE_TO_SCORE = {v: k for k, v in _SCORE_TO_GRADE.items()}
_GRADE_HE = {
    "A+": "יהלום", "A": "פלטינה", "B": "זהב",
    "C": "כסף",  "D": "ארד",    "E": "דרגת בסיס", "F": "לא עומד",
}
_GRADE_EN = {
    "A+": "Diamond", "A": "Platinum", "B": "Gold",
    "C": "Silver",   "D": "Bronze",   "E": "Base Grade", "F": "Below Base",
}


def _building_grade(unit_ratings: List[Dict], climate_zone: str) -> Dict:
    """Compute building-level grade from per-unit scores (area-weighted average).

    Per SI 5282: if any unit is F the building is F (new buildings).
    """
    if any(u["grade"]["score"] <= -1 for u in unit_ratings):
        g = "F"
        return {"grade": g, "name_en": _GRADE_EN[g], "name_he": _GRADE_HE[g],
                "score": -1, "weighted_score": -1.0}

    total_area = sum(u["area_m2"] for u in unit_ratings)
    if total_area <= 0:
        return {"grade": "?", "name_en": "", "name_he": "", "score": 0, "weighted_score": 0.0}

    weighted_score = sum(u["grade"]["score"] * u["area_m2"] for u in unit_ratings) / total_area
    rounded = round(weighted_score)
    rounded = max(-1, min(5, rounded))
    g = _SCORE_TO_GRADE.get(rounded, "F")
    return {"grade": g, "name_en": _GRADE_EN[g], "name_he": _GRADE_HE[g],
            "score": rounded, "weighted_score": round(weighted_score, 3)}


def _flat_unit_number(flat_id: str) -> str:
    m = re.search(r"X(\d+)$", flat_id, re.IGNORECASE)
    return m.group(1) if m else flat_id


def _flat_floor(flat_id: str) -> str:
    m = re.match(r"^(\d+)", flat_id)
    return m.group(1) if m else ""


def write_units_csv(unit_ratings: List[Dict], output_path: Path) -> None:
    """Write units.csv matching expert output.csv format."""
    columns = [
        "Multiplier", "Grade", "Rating (G)", "Floor Area {m2}",
        "Orientation", "Flat or Zone", "Floor",
    ]
    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(columns)
        for u in unit_ratings:
            fid = u["flat_id"]
            writer.writerow([
                1,
                u["grade"]["score"],
                u["grade"]["grade"],
                f"{u['area_m2']:.2f}",
                "",
                _flat_unit_number(fid),
                _flat_floor(fid),
            ])


def generate_residential_report(
    rating_result: Dict,
    output: SimulationOutput,
    output_dir: Path,
    project_name: str = "",
    shading_ctrl_names: Optional[set] = None,
) -> Dict[str, Path]:
    """Generate professional SI 5282 residential report files.

    Args:
        rating_result:  The dict returned by the compare-residential CLI
                        (contains standard, climate_zone, ep_des_kwh_m2,
                        ep_ref_kwh_m2, ip_percent, grade, unit_ratings, …).
        output:         SimulationOutput from the proposed building run.
        output_dir:     Directory to write report files into.
        project_name:   Optional project label for the report header.
        shading_ctrl_names: Window names that have shading controls.

    Returns:
        Dict mapping "report_md", "units_csv", "windows_csv" to output paths.
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    unit_ratings = rating_result.get("unit_ratings", [])
    climate_zone = rating_result.get("climate_zone", "?")
    ep_des = rating_result.get("ep_des_kwh_m2", 0.0)
    ep_ref = rating_result.get("ep_ref_kwh_m2", 0.0)
    ip_pct = rating_result.get("ip_percent", 0.0)
    building_grade = rating_result.get("grade", {})
    cond_area = rating_result.get("conditioned_area_m2", output.building_area.conditioned_m2)
    cop = rating_result.get("cop", 3.0)
    box_area = rating_result.get("reference_unit_area_m2", 100.0)

    # Recompute building grade from unit scores (consistent with formula)
    building_grade_info = _building_grade(unit_ratings, climate_zone)
    grade_letter = building_grade_info["grade"]
    grade_he = building_grade_info["name_he"]
    grade_en = building_grade_info["name_en"]

    # Grade badge line
    grade_badge = {
        "A+": "⬛ GRADE A+ — יהלום (Diamond)",
        "A":  "🟫 GRADE A  — פלטינה (Platinum)",
        "B":  "🟨 GRADE B  — זהב (Gold)",
        "C":  "🟩 GRADE C  — כסף (Silver)",
        "D":  "🟦 GRADE D  — ארד (Bronze)",
        "E":  "🟧 GRADE E  — דרגת בסיס (Base Grade)",
        "F":  "🟥 GRADE F  — לא עומד (Below Base)",
    }.get(grade_letter, f"GRADE {grade_letter}")

    today = date.today().strftime("%d %B %Y")
    ref_hvac = rating_result.get("ref_box_hvac_by_orientation", {})

    # Window analysis
    window_records = build_window_records(output, shading_ctrl_names)
    win_summary = window_summary_by_flat(window_records)
    total_windows = sum(s["window_count"] for s in win_summary.values())
    total_glass_area = sum(s["total_glass_area_m2"] for s in win_summary.values())

    # ── Grade distribution ────────────────────────────────────────────────────
    grade_dist: Dict[str, int] = {}
    for u in unit_ratings:
        g = u["grade"]["grade"]
        grade_dist[g] = grade_dist.get(g, 0) + 1

    # ── Markdown report ───────────────────────────────────────────────────────
    lines: List[str] = []

    title = project_name if project_name else "Building Energy Rating"
    lines += [
        f"# SI 5282 Energy Rating Report",
        f"## {title}",
        "",
        f"**Date:** {today}  |  **Standard:** SI 5282 Part 1  |  **Climate Zone:** {climate_zone}",
        "",
        "---",
        "",
        f"## {grade_badge}",
        "",
        f"| Metric | Value |",
        f"|--------|-------|",
        f"| IP (Improvement Percentage) | **{ip_pct:+.1f}%** |",
        f"| EPdes (proposed) | {ep_des:.2f} kWh/m²/yr |",
        f"| EPref (reference box) | {ep_ref:.2f} kWh/m²/yr |",
        f"| Weighted building score | {building_grade_info['weighted_score']:.2f} → Grade {grade_letter} |",
        "",
        "---",
        "",
        "## Building Summary",
        "",
        f"| Metric | Value |",
        f"|--------|-------|",
        f"| Conditioned area | {cond_area:.1f} m² |",
        f"| Total units | {len(unit_ratings)} |",
        f"| Annual cooling | {output.end_uses.cooling_kwh:,.0f} kWh |",
        f"| Annual heating | {output.end_uses.heating_kwh:,.0f} kWh |",
        f"| Annual HVAC thermal | {output.end_uses.cooling_kwh + output.end_uses.heating_kwh:,.0f} kWh |",
        f"| Interior lighting | {output.end_uses.interior_lighting_kwh:,.0f} kWh |",
        f"| Interior equipment | {output.end_uses.interior_equipment_kwh:,.0f} kWh |",
        f"| Total site energy | {output.site_energy_kwh:,.0f} kWh |",
        f"| EUI (site) | {output.site_energy_kwh / cond_area:.1f} kWh/m²/yr |",
        f"| Total windows | {total_windows} |",
        f"| Total glazing area | {total_glass_area:.1f} m² |",
        f"| COP used | {cop} |",
        "",
        "---",
        "",
        "## Reference Box Results",
        "",
        f"Reference unit: 100 m² (10×10×3 m) per SI 5282 Part 1, simulated in 4 orientations.",
        "",
        f"| Orientation | HVAC Thermal (kWh) | HVAC/m² (kWh/m²) |",
        f"|-------------|--------------------|--------------------|",
    ]
    for orient in ("S", "W", "N", "E"):
        hvac = ref_hvac.get(orient, 0.0)
        lines.append(f"| {orient} | {hvac:,.1f} | {hvac / box_area:.2f} |")
    lines += [
        f"| **Average** | **{sum(ref_hvac.values()) / 4:,.1f}** | **{ep_ref * cop:.2f}** |",
        "",
        "---",
        "",
        "## Per-Unit Results",
        "",
        f"Grade distribution: " + "  |  ".join(
            f"**{g}** ({_GRADE_HE.get(g, '')}): {n} unit{'s' if n > 1 else ''}"
            for g, n in sorted(grade_dist.items(), key=lambda x: -_GRADE_TO_SCORE.get(x[0], -1))
        ),
        "",
        f"| Unit | Floor | Type | Area (m²) | EPdes | EPref | IP% | Grade |",
        f"|------|-------|------|-----------|-------|-------|-----|-------|",
    ]
    for u in unit_ratings:
        fid = u["flat_id"]
        g = u["grade"]["grade"]
        he = _GRADE_HE.get(g, "")
        lines.append(
            f"| {fid} | {u['floor_number']} | {u['floor_type']} | {u['area_m2']:.1f} "
            f"| {u['ep_des_kwh_m2']:.2f} | {u['ep_ref_kwh_m2']:.2f} "
            f"| {u['ip_percent']:+.1f}% | **{g}** {he} |"
        )

    lines += [
        "",
        "---",
        "",
        "## Window Analysis Summary",
        "",
        f"| Unit | Windows | Glass Area (m²) | Avg U (W/m²K) | Avg SHGC | WWR | Orientations |",
        f"|------|---------|-----------------|---------------|----------|-----|--------------|",
    ]
    for fid, s in sorted(win_summary.items()):
        orients = " / ".join(
            f"{k}:{v:.1f}m²" for k, v in sorted(
                s["orientation_area"].items(),
                key=lambda x: -x[1]
            )
        )
        lines.append(
            f"| {fid} | {s['window_count']} | {s['total_glass_area_m2']:.1f} "
            f"| {s['avg_u']:.2f} | {s['avg_shgc']:.3f} | {s['wwr']:.2f} | {orients} |"
        )

    lines += [
        "",
        "---",
        "",
        "## Notes",
        "",
        f"- **EPdes** = (cooling + heating kWh) / COP({cop}) / conditioned area",
        "- **EPref** = average HVAC of 4-orientation reference box / COP / 100 m²",
        "- Reference unit: 10×10×3 m box per SI 5282 Part 1, Appendix ג",
        "- Per-unit floor type: ground / middle / top (affects reference box selection)",
        "- Building grade = area-weighted average of unit scores, rounded to nearest integer",
        f"- Simulation engine: EnergyPlus 25.2",
        "",
    ]

    md_path = output_dir / "residential_report.md"
    md_path.write_text("\n".join(lines), encoding="utf-8")

    # ── units.csv ─────────────────────────────────────────────────────────────
    units_path = output_dir / "units.csv"
    write_units_csv(unit_ratings, units_path)

    # ── windows.csv ───────────────────────────────────────────────────────────
    windows_path = output_dir / "windows.csv"
    write_windows_csv(window_records, windows_path)

    return {
        "report_md": md_path,
        "units_csv": units_path,
        "windows_csv": windows_path,
    }
