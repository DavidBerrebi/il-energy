"""Professional SI 5282 residential report generator.

Produces output files:
  residential_report.md  — formatted Markdown report
  residential_report.pdf — professional PDF (via weasyprint)
  units.csv              — per-unit grades (EVERGREEN output.csv format)
  windows.csv            — window/surface analysis
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
_GRADE_COLOR = {
    "A+": "#1a1a2e", "A": "#6b3fa0", "B": "#c9a84c",
    "C": "#8c9aab",  "D": "#b87333", "E": "#6c757d", "F": "#c0392b",
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
    m = re.search(r"X(\d+\w*)$", flat_id, re.IGNORECASE)
    return m.group(1) if m else flat_id


def _flat_floor(flat_id: str) -> str:
    m = re.match(r"^(\d+)", flat_id)
    return m.group(1) if m else ""


def write_units_csv(unit_ratings: List[Dict], output_path: Path) -> None:
    """Write units.csv matching SI 5282 output format."""
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


# ── HTML/PDF report ────────────────────────────────────────────────────────────

_HTML_CSS = """
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap');

* { box-sizing: border-box; margin: 0; padding: 0; }

body {
    font-family: 'Inter', 'Helvetica Neue', Arial, sans-serif;
    font-size: 10pt;
    color: #1a1a2e;
    background: #fff;
    line-height: 1.5;
}

.page {
    width: 210mm;
    min-height: 297mm;
    padding: 18mm 18mm 20mm 18mm;
}

/* Header */
.header {
    display: flex;
    justify-content: space-between;
    align-items: flex-start;
    border-bottom: 3px solid #1a1a2e;
    padding-bottom: 8pt;
    margin-bottom: 16pt;
}
.header-left h1 {
    font-size: 15pt;
    font-weight: 700;
    color: #1a1a2e;
    letter-spacing: -0.3px;
}
.header-left p {
    font-size: 8.5pt;
    color: #555;
    margin-top: 2pt;
}
.header-right {
    text-align: right;
    font-size: 8pt;
    color: #555;
    line-height: 1.7;
}

/* Grade banner */
.grade-banner {
    border-radius: 6px;
    padding: 14pt 18pt;
    margin-bottom: 16pt;
    display: flex;
    align-items: center;
    gap: 18pt;
    color: white;
}
.grade-letter {
    font-size: 42pt;
    font-weight: 700;
    line-height: 1;
    min-width: 56pt;
    text-align: center;
}
.grade-details h2 {
    font-size: 14pt;
    font-weight: 600;
    margin-bottom: 3pt;
}
.grade-details p {
    font-size: 9pt;
    opacity: 0.9;
}
.grade-ip {
    margin-left: auto;
    text-align: right;
}
.grade-ip .ip-value {
    font-size: 22pt;
    font-weight: 700;
    line-height: 1;
}
.grade-ip .ip-label {
    font-size: 7.5pt;
    opacity: 0.85;
    margin-top: 2pt;
}

/* Section headings */
h3 {
    font-size: 9pt;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.6px;
    color: #1a1a2e;
    border-bottom: 1.5px solid #e0e0e0;
    padding-bottom: 4pt;
    margin: 14pt 0 8pt 0;
}

/* Two-column layout */
.two-col {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 14pt;
    margin-bottom: 4pt;
}

/* Summary cards */
.summary-grid {
    display: grid;
    grid-template-columns: repeat(3, 1fr);
    gap: 8pt;
    margin-bottom: 4pt;
}
.card {
    background: #f7f8fa;
    border-radius: 5px;
    padding: 8pt 10pt;
    border-left: 3px solid #1a1a2e;
}
.card .card-label {
    font-size: 7pt;
    color: #777;
    text-transform: uppercase;
    letter-spacing: 0.4px;
}
.card .card-value {
    font-size: 11.5pt;
    font-weight: 600;
    color: #1a1a2e;
    margin-top: 1pt;
}
.card .card-unit {
    font-size: 7.5pt;
    color: #555;
    margin-top: 1pt;
}

/* Tables */
table {
    width: 100%;
    border-collapse: collapse;
    font-size: 8pt;
    margin-bottom: 8pt;
}
thead tr {
    background: #1a1a2e;
    color: white;
}
thead th {
    padding: 5pt 7pt;
    text-align: left;
    font-weight: 500;
    letter-spacing: 0.2px;
}
tbody tr:nth-child(even) { background: #f7f8fa; }
tbody tr:hover { background: #eef0f5; }
tbody td {
    padding: 4pt 7pt;
    border-bottom: 1px solid #e8eaed;
    color: #2c2c3e;
}
.num { text-align: right; font-variant-numeric: tabular-nums; }
.center { text-align: center; }

/* Grade pill */
.grade-pill {
    display: inline-block;
    border-radius: 3px;
    padding: 1pt 5pt;
    font-size: 7.5pt;
    font-weight: 600;
    color: white;
    min-width: 22pt;
    text-align: center;
}

/* EPref table */
.epref-table { margin-bottom: 0; }
.epref-source {
    font-size: 7.5pt;
    color: #777;
    margin-top: 4pt;
    font-style: italic;
}

/* Grade distribution bar */
.dist-bar {
    display: flex;
    gap: 6pt;
    flex-wrap: wrap;
    margin-bottom: 6pt;
}
.dist-item {
    display: flex;
    align-items: center;
    gap: 4pt;
    font-size: 8pt;
}
.dist-swatch {
    width: 10pt;
    height: 10pt;
    border-radius: 2px;
}

/* Footer */
.footer {
    position: fixed;
    bottom: 12mm;
    left: 18mm;
    right: 18mm;
    display: flex;
    justify-content: space-between;
    font-size: 7pt;
    color: #aaa;
    border-top: 1px solid #e0e0e0;
    padding-top: 5pt;
}

/* Page break */
.page-break { page-break-before: always; }
"""


def _render_pdf(html_str: str, html_path: "Path", pdf_path: "Path") -> "Optional[Path]":
    """Render HTML to PDF using WeasyPrint, Chrome headless, or skip gracefully."""
    import warnings

    # Try WeasyPrint first
    try:
        from weasyprint import HTML as WP_HTML
        WP_HTML(string=html_str).write_pdf(str(pdf_path))
        return pdf_path
    except Exception:
        pass

    # Try Google Chrome headless (macOS or Linux)
    import subprocess, shutil
    chrome_candidates = [
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        "google-chrome",
        "chromium",
        "chromium-browser",
    ]
    chrome_bin = None
    for c in chrome_candidates:
        if shutil.which(c) or (c.startswith("/") and Path(c).exists()):
            chrome_bin = c
            break

    if chrome_bin:
        try:
            subprocess.run(
                [
                    chrome_bin,
                    "--headless=new",
                    "--disable-gpu",
                    "--no-sandbox",
                    f"--print-to-pdf={pdf_path}",
                    "--print-to-pdf-no-header",
                    str(html_path),
                ],
                check=True,
                capture_output=True,
            )
            if pdf_path.exists() and pdf_path.stat().st_size > 0:
                return pdf_path
        except Exception as e:
            warnings.warn(f"Chrome PDF generation failed: {e}")

    warnings.warn(
        "PDF generation skipped: neither WeasyPrint nor Chrome headless is available. "
        "The HTML report is at: " + str(html_path)
    )
    return None


def _grade_pill_html(grade: str) -> str:
    color = _GRADE_COLOR.get(grade, "#666")
    return f'<span class="grade-pill" style="background:{color}">{grade}</span>'


def _build_html(
    project_name: str,
    today: str,
    climate_zone: str,
    grade_letter: str,
    grade_en: str,
    grade_he: str,
    ip_pct: float,
    ep_des: float,
    ep_ref: float,
    cop: float,
    cond_area: float,
    unit_ratings: List[Dict],
    grade_dist: Dict[str, int],
    building_grade_info: Dict,
    output: SimulationOutput,
    ep_ref_by_floor_type: Dict,
    ref_hvac_by_ft: Dict,
    tabulated_epref: bool,
    box_area: float,
    win_summary: Dict,
    total_windows: int,
    total_glass_area: float,
) -> str:
    color = _GRADE_COLOR.get(grade_letter, "#444")

    # ── Grade banner ──
    banner = f"""
    <div class="grade-banner" style="background:{color}">
        <div class="grade-letter">{grade_letter}</div>
        <div class="grade-details">
            <h2>{grade_en} / {grade_he}</h2>
            <p>ת"י 5282 חלק 1 (2024) &nbsp;|&nbsp; Climate Zone {climate_zone}</p>
            <p>Weighted score: {building_grade_info['weighted_score']:.2f}</p>
        </div>
        <div class="grade-ip">
            <div class="ip-value">{ip_pct:+.1f}%</div>
            <div class="ip-label">Improvement<br>Percentage (IP)</div>
        </div>
    </div>"""

    # ── Summary cards ──
    hvac_kwh = output.end_uses.cooling_kwh + output.end_uses.heating_kwh
    cards = f"""
    <div class="summary-grid">
        <div class="card">
            <div class="card-label">EPdes (Proposed)</div>
            <div class="card-value">{ep_des:.2f}</div>
            <div class="card-unit">kWh/m²/yr</div>
        </div>
        <div class="card">
            <div class="card-label">EPref (Reference)</div>
            <div class="card-value">{ep_ref:.2f}</div>
            <div class="card-unit">kWh/m²/yr</div>
        </div>
        <div class="card">
            <div class="card-label">Conditioned Area</div>
            <div class="card-value">{cond_area:,.0f}</div>
            <div class="card-unit">m²</div>
        </div>
        <div class="card">
            <div class="card-label">Annual Cooling</div>
            <div class="card-value">{output.end_uses.cooling_kwh:,.0f}</div>
            <div class="card-unit">kWh</div>
        </div>
        <div class="card">
            <div class="card-label">Annual Heating</div>
            <div class="card-value">{output.end_uses.heating_kwh:,.0f}</div>
            <div class="card-unit">kWh</div>
        </div>
        <div class="card">
            <div class="card-label">Total Units</div>
            <div class="card-value">{len(unit_ratings)}</div>
            <div class="card-unit">apartments</div>
        </div>
        <div class="card">
            <div class="card-label">Total Site Energy</div>
            <div class="card-value">{output.site_energy_kwh:,.0f}</div>
            <div class="card-unit">kWh/yr</div>
        </div>
        <div class="card">
            <div class="card-label">EUI (Site)</div>
            <div class="card-value">{output.site_energy_kwh / cond_area:.1f}</div>
            <div class="card-unit">kWh/m²/yr</div>
        </div>
        <div class="card">
            <div class="card-label">Total Glazing</div>
            <div class="card-value">{total_glass_area:.1f}</div>
            <div class="card-unit">m² ({total_windows} windows)</div>
        </div>
    </div>"""

    # ── EPref section ──
    if tabulated_epref:
        epref_rows = "".join(
            f"<tr><td>{ft.capitalize()}</td><td class='num'>{ep_ref_by_floor_type[ft]:.2f}</td></tr>"
            for ft in ("ground", "middle", "top") if ft in ep_ref_by_floor_type
        )
        epref_section = f"""
        <h3>Reference EPref — SI 5282 Part 1, Annex ג (Zone {climate_zone})</h3>
        <table class="epref-table">
            <thead><tr><th>Floor Type</th><th>EPref [kWh/m²/yr]</th></tr></thead>
            <tbody>{epref_rows}</tbody>
        </table>
        <p class="epref-source">Values per SI 5282 Part 1 (2024 amendment), Zone {climate_zone}.
        COP = {cop}. Small units ≤ 50 m² use higher EPref per standard.</p>"""
    else:
        epref_rows = ""
        for ft_key, hvac_map in sorted(ref_hvac_by_ft.items()):
            vals = [hvac_map.get(o, 0.0) for o in ("S", "W", "N", "E")]
            avg_m2 = sum(vals) / len(vals) / box_area if vals else 0.0
            epref_ft = avg_m2 / cop
            epref_rows += (
                f"<tr><td>{ft_key}</td>"
                + "".join(f"<td class='num'>{v:,.0f}</td>" for v in vals)
                + f"<td class='num'>{avg_m2:.2f}</td><td class='num'>{epref_ft:.2f}</td></tr>"
            )
        epref_section = f"""
        <h3>Reference Box Simulation — SI 5282 Part 1, Annex ג</h3>
        <p class="epref-source" style="margin-bottom:6pt">Reference unit: {int(box_area)} m² (10×10×3 m),
        4 cardinal orientations. COP = {cop}.</p>
        <table>
            <thead><tr>
                <th>Floor Type</th><th>S (kWh)</th><th>W (kWh)</th>
                <th>N (kWh)</th><th>E (kWh)</th>
                <th>Avg/m²</th><th>EPref</th>
            </tr></thead>
            <tbody>{epref_rows}</tbody>
        </table>"""

    # ── Grade distribution ──
    dist_items = "".join(
        f'<div class="dist-item">'
        f'<div class="dist-swatch" style="background:{_GRADE_COLOR.get(g,"#666")}"></div>'
        f'<span><strong>{g}</strong> {_GRADE_HE.get(g,"")} — {n} unit{"s" if n>1 else ""}</span>'
        f'</div>'
        for g, n in sorted(grade_dist.items(), key=lambda x: -_GRADE_TO_SCORE.get(x[0], -1))
    )

    # ── Per-unit table ──
    unit_rows = ""
    for u in unit_ratings:
        g = u["grade"]["grade"]
        pill = _grade_pill_html(g)
        unit_rows += (
            f"<tr>"
            f"<td>{u['flat_id']}</td>"
            f"<td class='center'>{u['floor_number']}</td>"
            f"<td class='center'>{u['floor_type']}</td>"
            f"<td class='num'>{u['area_m2']:.1f}</td>"
            f"<td class='num'>{u['ep_des_kwh_m2']:.2f}</td>"
            f"<td class='num'>{u['ep_ref_kwh_m2']:.2f}</td>"
            f"<td class='num'>{u['ip_percent']:+.1f}%</td>"
            f"<td class='center'>{pill}</td>"
            f"</tr>"
        )

    # ── Window analysis table ──
    win_rows = ""
    for fid, s in sorted(win_summary.items()):
        orients = ", ".join(
            f"{k} {v:.1f} m²" for k, v in sorted(s["orientation_area"].items(), key=lambda x: -x[1])
        )
        win_rows += (
            f"<tr>"
            f"<td>{fid}</td>"
            f"<td class='num'>{s['window_count']}</td>"
            f"<td class='num'>{s['total_glass_area_m2']:.1f}</td>"
            f"<td class='num'>{s['avg_u']:.2f}</td>"
            f"<td class='num'>{s['avg_shgc']:.3f}</td>"
            f"<td class='num'>{s['wwr']:.2f}</td>"
            f"<td>{orients}</td>"
            f"</tr>"
        )

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<style>{_HTML_CSS}</style>
</head>
<body>
<div class="page">

  <!-- Header -->
  <div class="header">
    <div class="header-left">
      <h1>Energy Rating Report &nbsp;—&nbsp; ת"י 5282 חלק 1</h1>
      <p><strong>{project_name}</strong></p>
    </div>
    <div class="header-right">
      <div><strong>Date:</strong> {today}</div>
      <div><strong>Standard:</strong> SI 5282 Part 1 (2024)</div>
      <div><strong>Climate Zone:</strong> {climate_zone}</div>
      <div><strong>Engine:</strong> EnergyPlus 25.2</div>
    </div>
  </div>

  <!-- Grade banner -->
  {banner}

  <!-- Summary cards -->
  <h3>Building Summary</h3>
  {cards}

  <!-- EPref -->
  {epref_section}

  <!-- Grade distribution -->
  <h3>Grade Distribution</h3>
  <div class="dist-bar">{dist_items}</div>

  <!-- Per-unit table -->
  <h3>Per-Unit Results ({len(unit_ratings)} Apartments)</h3>
  <table>
    <thead>
      <tr>
        <th>Unit</th><th>Floor</th><th>Type</th>
        <th>Area (m²)</th><th>EPdes</th><th>EPref</th><th>IP%</th><th>Grade</th>
      </tr>
    </thead>
    <tbody>{unit_rows}</tbody>
  </table>

  <!-- Window analysis -->
  <div class="page-break"></div>
  <div class="header">
    <div class="header-left">
      <h1>Energy Rating Report &nbsp;—&nbsp; ת"י 5282 חלק 1</h1>
      <p><strong>{project_name}</strong></p>
    </div>
    <div class="header-right">
      <div><strong>Date:</strong> {today}</div>
      <div><strong>Climate Zone:</strong> {climate_zone}</div>
    </div>
  </div>
  <h3>Window Analysis Summary</h3>
  <table>
    <thead>
      <tr>
        <th>Unit</th><th>Count</th><th>Glass Area (m²)</th>
        <th>Avg U (W/m²K)</th><th>Avg SHGC</th><th>WWR</th><th>Orientations</th>
      </tr>
    </thead>
    <tbody>{win_rows}</tbody>
  </table>

  <!-- Notes -->
  <h3>Methodology Notes</h3>
  <table>
    <tbody>
      <tr><td><strong>EPdes</strong></td><td>Σ(zone sensible cooling + heating) / COP({cop}) / conditioned area [kWh/m²/yr electrical]</td></tr>
      <tr><td><strong>EPref</strong></td><td>SI 5282 Part 1 Annex ג reference values per floor type and unit area</td></tr>
      <tr><td><strong>IP</strong></td><td>(EPref − EPdes) / EPref × 100 %</td></tr>
      <tr><td><strong>Floor type</strong></td><td>Ground = lowest floor, Top = highest floor or exposed-roof ratio ≥ 50%, Middle = all others</td></tr>
      <tr><td><strong>Building grade</strong></td><td>Area-weighted average of unit scores, rounded to nearest integer</td></tr>
    </tbody>
  </table>

  <!-- Footer -->
  <div class="footer">
    <span>il-energy — SI 5282 Compliance Engine</span>
    <span>{project_name} &nbsp;|&nbsp; {today}</span>
  </div>

</div>
</body>
</html>"""
    return html


def generate_residential_report(
    rating_result: Dict,
    output: SimulationOutput,
    output_dir: Path,
    project_name: str = "",
    shading_ctrl_names: Optional[set] = None,
) -> Dict[str, Path]:
    """Generate professional SI 5282 residential report files.

    Args:
        rating_result:  The dict returned by the compare-residential CLI.
        output:         SimulationOutput from the proposed building run.
        output_dir:     Directory to write report files into.
        project_name:   Optional project label for the report header.
        shading_ctrl_names: Window names that have shading controls.

    Returns:
        Dict mapping "report_md", "report_pdf", "units_csv", "windows_csv" to output paths.
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    unit_ratings = rating_result.get("unit_ratings", [])
    climate_zone = rating_result.get("climate_zone", "?")
    ep_des = rating_result.get("ep_des_kwh_m2", 0.0)
    ep_ref = rating_result.get("ep_ref_kwh_m2", 0.0)
    ip_pct = rating_result.get("ip_percent", 0.0)
    cond_area = rating_result.get("conditioned_area_m2", output.building_area.conditioned_m2)
    cop = rating_result.get("cop", 3.0)
    box_area = rating_result.get("reference_unit_area_m2", 100.0)
    ref_hvac_by_ft = rating_result.get("ref_box_hvac_by_floor_type", {})
    ep_ref_by_floor_type = rating_result.get("ep_ref_by_floor_type", {})
    tabulated_epref = not bool(ref_hvac_by_ft)

    building_grade_info = _building_grade(unit_ratings, climate_zone)
    grade_letter = building_grade_info["grade"]
    grade_en = building_grade_info["name_en"]
    grade_he = building_grade_info["name_he"]

    today = date.today().strftime("%d %B %Y")

    window_records = build_window_records(output, shading_ctrl_names)
    win_summary = window_summary_by_flat(window_records)
    total_windows = sum(s["window_count"] for s in win_summary.values())
    total_glass_area = sum(s["total_glass_area_m2"] for s in win_summary.values())

    grade_dist: Dict[str, int] = {}
    for u in unit_ratings:
        g = u["grade"]["grade"]
        grade_dist[g] = grade_dist.get(g, 0) + 1

    # ── Markdown report ───────────────────────────────────────────────────────
    lines: List[str] = [
        "# SI 5282 Energy Rating Report",
        f"## {project_name or 'Building Energy Rating'}",
        "",
        f"**Date:** {today}  |  **Standard:** SI 5282 Part 1 (2024)  |  **Climate Zone:** {climate_zone}  |  **Engine:** EnergyPlus 25.2",
        "",
        "---",
        "",
        f"## Grade {grade_letter} — {grade_en} / {grade_he}",
        "",
        f"| Metric | Value |",
        f"|--------|-------|",
        f"| IP (Improvement Percentage) | **{ip_pct:+.1f}%** |",
        f"| EPdes (proposed) | {ep_des:.2f} kWh/m²/yr |",
        f"| EPref (reference) | {ep_ref:.2f} kWh/m²/yr |",
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
        f"| Total site energy | {output.site_energy_kwh:,.0f} kWh |",
        f"| EUI (site) | {output.site_energy_kwh / cond_area:.1f} kWh/m²/yr |",
        f"| Total glazing | {total_glass_area:.1f} m² ({total_windows} windows) |",
        f"| COP | {cop} |",
        "",
        "---",
        "",
        f"## Reference EPref — SI 5282 Part 1 Annex ג, Zone {climate_zone}",
        "",
    ]

    if tabulated_epref:
        lines += [
            f"| Floor Type | EPref [kWh/m²/yr] |",
            f"|------------|------------------|",
        ]
        for ft in ("ground", "middle", "top"):
            if ft in ep_ref_by_floor_type:
                lines.append(f"| {ft.capitalize()} | {ep_ref_by_floor_type[ft]:.2f} |")
        lines += ["", f"_Per SI 5282 Part 1 (2024 amendment), Zone {climate_zone}. COP = {cop}._"]
    else:
        lines += [
            f"Reference unit: {int(box_area)} m² (10×10×3 m), simulated in 4 cardinal orientations.",
            "",
            f"| Floor type | S (kWh) | W (kWh) | N (kWh) | E (kWh) | EPref [kWh/m²/yr] |",
            f"|------------|---------|---------|---------|---------|------------------|",
        ]
        for ft_key, hvac_map in sorted(ref_hvac_by_ft.items()):
            vals = [hvac_map.get(o, 0.0) for o in ("S", "W", "N", "E")]
            avg_m2 = sum(vals) / len(vals) / box_area if vals else 0.0
            epref_ft = avg_m2 / cop
            lines.append(
                f"| {ft_key} | {vals[0]:,.0f} | {vals[1]:,.0f} | {vals[2]:,.0f} | {vals[3]:,.0f} | {epref_ft:.2f} |"
            )

    lines += [
        "",
        "---",
        "",
        "## Per-Unit Results",
        "",
        "Grade distribution: " + "  |  ".join(
            f"**{g}** ({_GRADE_HE.get(g, '')}): {n} unit{'s' if n > 1 else ''}"
            for g, n in sorted(grade_dist.items(), key=lambda x: -_GRADE_TO_SCORE.get(x[0], -1))
        ),
        "",
        f"| Unit | Floor | Type | Area (m²) | EPdes | EPref | IP% | Grade |",
        f"|------|-------|------|-----------|-------|-------|-----|-------|",
    ]
    for u in unit_ratings:
        g = u["grade"]["grade"]
        lines.append(
            f"| {u['flat_id']} | {u['floor_number']} | {u['floor_type']} | {u['area_m2']:.1f} "
            f"| {u['ep_des_kwh_m2']:.2f} | {u['ep_ref_kwh_m2']:.2f} "
            f"| {u['ip_percent']:+.1f}% | **{g}** {_GRADE_HE.get(g, '')} |"
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
            f"{k}:{v:.1f}m²" for k, v in sorted(s["orientation_area"].items(), key=lambda x: -x[1])
        )
        lines.append(
            f"| {fid} | {s['window_count']} | {s['total_glass_area_m2']:.1f} "
            f"| {s['avg_u']:.2f} | {s['avg_shgc']:.3f} | {s['wwr']:.2f} | {orients} |"
        )

    lines += [
        "",
        "---",
        "",
        "## Methodology",
        "",
        "- **EPdes** = Σ(zone sensible cooling + heating) / COP / conditioned area [kWh/m²/yr electrical]",
        f"- **EPref** = SI 5282 Part 1 Annex ג reference values per floor type and unit area (Zone {climate_zone})",
        "- **IP** = (EPref − EPdes) / EPref × 100 %",
        "- **Floor type:** Ground = lowest floor, Top = highest floor or exposed-roof ratio ≥ 50%, Middle = all others",
        "- **Building grade** = area-weighted average of unit scores, rounded to nearest integer",
        "",
    ]

    md_path = output_dir / "residential_report.md"
    md_path.write_text("\n".join(lines), encoding="utf-8")

    # ── PDF report ────────────────────────────────────────────────────────────
    pdf_path = output_dir / "residential_report.pdf"
    html_str = _build_html(
        project_name=project_name or "Building Energy Rating",
        today=today,
        climate_zone=climate_zone,
        grade_letter=grade_letter,
        grade_en=grade_en,
        grade_he=grade_he,
        ip_pct=ip_pct,
        ep_des=ep_des,
        ep_ref=ep_ref,
        cop=cop,
        cond_area=cond_area,
        unit_ratings=unit_ratings,
        grade_dist=grade_dist,
        building_grade_info=building_grade_info,
        output=output,
        ep_ref_by_floor_type=ep_ref_by_floor_type,
        ref_hvac_by_ft=ref_hvac_by_ft,
        tabulated_epref=tabulated_epref,
        box_area=box_area,
        win_summary=win_summary,
        total_windows=total_windows,
        total_glass_area=total_glass_area,
    )
    html_path = output_dir / "residential_report.html"
    html_path.write_text(html_str, encoding="utf-8")

    pdf_path = _render_pdf(html_str, html_path, pdf_path)

    # ── units.csv ─────────────────────────────────────────────────────────────
    units_path = output_dir / "units.csv"
    write_units_csv(unit_ratings, units_path)

    # ── windows.csv ───────────────────────────────────────────────────────────
    windows_path = output_dir / "windows.csv"
    write_windows_csv(window_records, windows_path)

    result = {"report_md": md_path, "units_csv": units_path, "windows_csv": windows_path}
    if pdf_path:
        result["report_pdf"] = pdf_path
    return result
