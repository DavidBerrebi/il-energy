"""Professional SI 5282 residential report generator — Evergreen-parity layout.

Produces:
  residential_report.html — intermediate HTML
  residential_report.pdf  — professional PDF (via WeasyPrint or Chrome headless)
  units.csv               — per-unit grades (Evergreen-compatible)
  windows.csv             — window/surface analysis
"""

from __future__ import annotations

import csv
import re
from datetime import date
from pathlib import Path
from typing import Dict, List, Optional

from il_energy.analysis.windows import build_window_records, window_summary_by_flat, write_windows_csv
from il_energy.models import SimulationOutput


# ── Constants ──────────────────────────────────────────────────────────────────
_ELECTRICITY_RATE_NIS = 0.62   # NIS/kWh — residential tariff approximation
_COST_YEARS = 5                 # 5-year projection (per Evergreen convention)

# Grade ↔ score
_SCORE_TO_GRADE = {5: "A+", 4: "A", 3: "B", 2: "C", 1: "D", 0: "E", -1: "F"}
_GRADE_TO_SCORE = {v: k for k, v in _SCORE_TO_GRADE.items()}
_GRADE_ORDER = ["A+", "A", "B", "C", "D", "E", "F"]
_GRADE_HE = {
    "A+": "יהלום", "A": "פלטינה", "B": "זהב",
    "C": "כסף",   "D": "ארד",    "E": "דרגת בסיס", "F": "לא עומד",
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
    """Area-weighted building grade from per-unit scores."""
    if any(u["grade"]["score"] <= -1 for u in unit_ratings):
        g = "F"
        return {"grade": g, "name_en": _GRADE_EN[g], "name_he": _GRADE_HE[g],
                "score": -1, "weighted_score": -1.0}
    total_area = sum(u["area_m2"] for u in unit_ratings)
    if total_area <= 0:
        return {"grade": "?", "name_en": "", "name_he": "", "score": 0, "weighted_score": 0.0}
    weighted_score = sum(u["grade"]["score"] * u["area_m2"] for u in unit_ratings) / total_area
    rounded = max(-1, min(5, round(weighted_score)))
    g = _SCORE_TO_GRADE.get(rounded, "F")
    return {"grade": g, "name_en": _GRADE_EN[g], "name_he": _GRADE_HE[g],
            "score": rounded, "weighted_score": round(weighted_score, 3)}


def _five_year_costs(ep_ref_weighted: float, ep_des: float, cond_area: float) -> Dict:
    """Compute 5-year electricity cost comparison in NIS.

    ref_nis     = weighted EPref × area × 5 years × 0.62 NIS/kWh
    savings_nis = (EPref - EPdes) × area × 5 × 0.62
    """
    ref_nis = ep_ref_weighted * cond_area * _COST_YEARS * _ELECTRICITY_RATE_NIS
    proposed_nis = ep_des * cond_area * _COST_YEARS * _ELECTRICITY_RATE_NIS
    savings_nis = ref_nis - proposed_nis
    return {
        "ref_nis": ref_nis,
        "proposed_nis": proposed_nis,
        "savings_nis": max(0.0, savings_nis),
        "savings_pct": max(0.0, savings_nis / ref_nis * 100) if ref_nis > 0 else 0.0,
    }


def _flat_unit_number(flat_id: str) -> str:
    m = re.search(r"X(\d+\w*)$", flat_id, re.IGNORECASE)
    return m.group(1) if m else flat_id


def _flat_floor(flat_id: str) -> str:
    m = re.match(r"^(\d+)", flat_id)
    return m.group(1) if m else ""


def write_units_csv(unit_ratings: List[Dict], output_path: Path) -> None:
    """Write units.csv matching Evergreen _Results format."""
    columns = [
        "Multiplier", "Grade", "Rating (G)", "Savings%",
        "EPdes Sum", "EPdes Cooling", "EPdes Heating", "EPdes Fan",
        "EPref", "Floor Area {m2}", "Orientation", "Flat or Zone", "Floor",
    ]
    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(columns)
        for u in unit_ratings:
            fid = u["flat_id"]
            cop = u.get("cop", 3.0)
            area = u["area_m2"]
            cooling_m2 = u["cooling_kwh"] / cop / area if area > 0 else 0.0
            heating_m2 = u["heating_kwh"] / cop / area if area > 0 else 0.0
            writer.writerow([
                1,
                u["grade"]["score"],
                u["grade"]["grade"],
                f"{u['ip_percent']:.1f}",
                f"{u['ep_des_kwh_m2']:.2f}",
                f"{cooling_m2:.2f}",
                f"{heating_m2:.2f}",
                "0.00",
                f"{u['ep_ref_kwh_m2']:.2f}",
                f"{area:.2f}",
                u.get("orientation", ""),
                _flat_unit_number(fid),
                _flat_floor(fid),
            ])


# ── HTML / PDF ─────────────────────────────────────────────────────────────────

_HTML_CSS = """
* { box-sizing: border-box; margin: 0; padding: 0; }

body {
    font-family: 'Helvetica Neue', Arial, sans-serif;
    font-size: 9.5pt;
    color: #1a1a2e;
    background: #fff;
    line-height: 1.45;
}

.page {
    width: 210mm;
    min-height: 297mm;
    padding: 16mm 16mm 20mm 16mm;
    position: relative;
}

/* ── Cover page ─────────────────────────────────────────── */

.cover-top {
    display: flex;
    justify-content: space-between;
    align-items: center;
    border-bottom: 2px solid #1a1a2e;
    padding-bottom: 8pt;
    margin-bottom: 18pt;
}
.cover-brand {
    font-size: 13pt;
    font-weight: 700;
    color: #1a1a2e;
    letter-spacing: -0.2px;
}
.cover-standard {
    font-size: 9pt;
    color: #555;
    text-align: right;
}

.cover-title {
    text-align: center;
    margin-bottom: 22pt;
}
.cover-title h1 {
    font-size: 19pt;
    font-weight: 700;
    color: #1a1a2e;
    direction: rtl;
    margin-bottom: 4pt;
}
.cover-title h2 {
    font-size: 13pt;
    font-weight: 400;
    color: #444;
}

/* ── Grade arrow scale ─────────────────────────────────── */

.grade-scale-wrap {
    margin: 0 0 22pt 0;
}
.grade-scale-label {
    font-size: 7.5pt;
    color: #777;
    text-transform: uppercase;
    letter-spacing: 0.5px;
    margin-bottom: 5pt;
}
.grade-scale {
    display: flex;
    height: 58pt;
    align-items: stretch;
    gap: 0;
}
.grade-box {
    flex: 1;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    color: white;
    position: relative;
    padding: 4pt 2pt;
}
/* First box: flat left, arrow right */
.grade-box.pos-first {
    clip-path: polygon(0% 0%, calc(100% - 13px) 0%, 100% 50%, calc(100% - 13px) 100%, 0% 100%);
    border-radius: 3px 0 0 3px;
}
/* Middle boxes: notch left, arrow right */
.grade-box.pos-mid {
    clip-path: polygon(13px 0%, calc(100% - 13px) 0%, 100% 50%, calc(100% - 13px) 100%, 13px 100%, 0% 50%);
    margin-left: -7px;
}
/* Last box: notch left, flat right */
.grade-box.pos-last {
    clip-path: polygon(13px 0%, 100% 0%, 100% 100%, 13px 100%, 0% 50%);
    margin-left: -7px;
    border-radius: 0 3px 3px 0;
}
.grade-box .box-letter {
    font-size: 15pt;
    font-weight: 700;
    line-height: 1;
}
.grade-box .box-name {
    font-size: 6.5pt;
    opacity: 0.9;
    margin-top: 2pt;
    text-align: center;
}
/* Active grade: wrapped in outer div for border effect */
.grade-box-outer {
    flex: 1;
    display: flex;
    align-items: stretch;
    position: relative;
}
.grade-box-active-wrap {
    flex: 1;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    color: white;
    position: relative;
    z-index: 5;
    transform: scaleY(1.18);
    filter: drop-shadow(0 0 4px rgba(0,0,0,0.8));
}
.grade-box-active-wrap.pos-first {
    clip-path: polygon(0% 0%, calc(100% - 13px) 0%, 100% 50%, calc(100% - 13px) 100%, 0% 100%);
    border-radius: 3px 0 0 3px;
}
.grade-box-active-wrap.pos-mid {
    clip-path: polygon(13px 0%, calc(100% - 13px) 0%, 100% 50%, calc(100% - 13px) 100%, 13px 100%, 0% 50%);
    margin-left: -7px;
}
.grade-box-active-wrap.pos-last {
    clip-path: polygon(13px 0%, 100% 0%, 100% 100%, 13px 100%, 0% 50%);
    margin-left: -7px;
}
.active-letter {
    font-size: 17pt;
    font-weight: 700;
    line-height: 1;
}
.active-name {
    font-size: 7pt;
    font-weight: 600;
    margin-top: 2pt;
}

/* ── Project info table ────────────────────────────────── */

.project-info {
    width: 100%;
    border-collapse: collapse;
    margin-bottom: 20pt;
    font-size: 9pt;
}
.project-info td {
    padding: 5pt 8pt;
    border: 1px solid #ddd;
}
.project-info td.label {
    background: #f0f2f5;
    font-weight: 600;
    color: #444;
    width: 18%;
}
.project-info td.value {
    color: #1a1a2e;
    font-weight: 500;
    width: 32%;
}

/* ── 5-year cost bars ─────────────────────────────────── */

.cost-section h3 {
    font-size: 9pt;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.5px;
    color: #1a1a2e;
    border-bottom: 1.5px solid #e0e0e0;
    padding-bottom: 4pt;
    margin-bottom: 10pt;
}
.cost-bar-row {
    display: flex;
    align-items: center;
    gap: 10pt;
    margin-bottom: 7pt;
}
.cost-bar-label {
    width: 42pt;
    font-size: 8pt;
    color: #555;
    text-align: right;
    flex-shrink: 0;
}
.cost-bar-track {
    flex: 1;
    background: #f0f2f5;
    border-radius: 3pt;
    height: 22pt;
    position: relative;
    overflow: hidden;
}
.cost-bar-fill {
    height: 100%;
    border-radius: 3pt;
    display: flex;
    align-items: center;
    padding: 0 8pt;
    color: white;
    font-size: 9pt;
    font-weight: 600;
    white-space: nowrap;
}
.bar-ref   { background: #c0392b; }
.bar-save  { background: #27ae60; }
.cost-note {
    font-size: 7.5pt;
    color: #777;
    margin-top: 4pt;
    font-style: italic;
}

/* ── Results page header ───────────────────────────────── */

.results-header {
    display: flex;
    justify-content: space-between;
    align-items: flex-start;
    border-bottom: 2px solid #1a1a2e;
    padding-bottom: 6pt;
    margin-bottom: 10pt;
}
.results-header h1 {
    font-size: 13pt;
    font-weight: 700;
    color: #1a1a2e;
}
.results-header .meta {
    font-size: 7.5pt;
    color: #666;
    text-align: right;
    line-height: 1.7;
}

.summary-bar {
    background: #ffd600;
    border-radius: 4pt;
    padding: 7pt 12pt;
    display: flex;
    align-items: center;
    gap: 20pt;
    margin-bottom: 10pt;
}
.summary-bar .sb-item {
    font-size: 9pt;
    color: #1a1a2e;
}
.summary-bar .sb-item strong {
    font-size: 11pt;
}
.summary-bar .sb-grade {
    margin-left: auto;
    display: flex;
    align-items: center;
    gap: 8pt;
}
.summary-bar .sb-grade-badge {
    width: 34pt;
    height: 34pt;
    border-radius: 50%;
    display: flex;
    align-items: center;
    justify-content: center;
    color: white;
    font-size: 14pt;
    font-weight: 700;
}

/* ── Section headings ─────────────────────────────────── */

h3 {
    font-size: 8.5pt;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.5px;
    color: #1a1a2e;
    border-bottom: 1.5px solid #e0e0e0;
    padding-bottom: 3pt;
    margin: 12pt 0 7pt 0;
}

/* ── Tables ───────────────────────────────────────────── */

table {
    width: 100%;
    border-collapse: collapse;
    font-size: 7.8pt;
    margin-bottom: 8pt;
}
thead tr { background: #1a1a2e; color: white; }
thead th {
    padding: 4pt 5pt;
    text-align: left;
    font-weight: 500;
    font-size: 7.5pt;
}
tbody tr:nth-child(even) { background: #f7f8fa; }
tbody td {
    padding: 3.5pt 5pt;
    border-bottom: 1px solid #e8eaed;
    color: #2c2c3e;
}
.num { text-align: right; font-variant-numeric: tabular-nums; }
.ctr { text-align: center; }

/* Grade pill */
.grade-pill {
    display: inline-block;
    border-radius: 3px;
    padding: 1pt 5pt;
    font-size: 7.5pt;
    font-weight: 700;
    color: white;
    min-width: 20pt;
    text-align: center;
}

/* EPref table */
.epref-source {
    font-size: 7pt;
    color: #777;
    margin-top: 3pt;
    font-style: italic;
}

/* Grade distribution bar */
.dist-bar {
    display: flex;
    gap: 8pt;
    flex-wrap: wrap;
    margin-bottom: 8pt;
    font-size: 8pt;
}
.dist-item { display: flex; align-items: center; gap: 4pt; }
.dist-swatch { width: 10pt; height: 10pt; border-radius: 2px; }

/* ── Footer ───────────────────────────────────────────── */

.footer {
    position: fixed;
    bottom: 10mm;
    left: 16mm;
    right: 16mm;
    display: flex;
    justify-content: space-between;
    font-size: 6.5pt;
    color: #bbb;
    border-top: 1px solid #e0e0e0;
    padding-top: 4pt;
}

.page-break { page-break-before: always; }
"""


def _render_pdf(html_str: str, html_path: "Path", pdf_path: "Path") -> "Optional[Path]":
    """Render HTML to PDF using WeasyPrint, Chrome headless, or skip gracefully."""
    import warnings

    # Try WeasyPrint first
    try:
        from weasyprint import HTML as WP_HTML
        WP_HTML(string=html_str, base_url=str(html_path.parent)).write_pdf(str(pdf_path))
        return pdf_path
    except Exception:
        pass

    # Try Google Chrome headless (macOS or Linux)
    import subprocess
    import shutil
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
        "HTML report at: " + str(html_path)
    )
    return None


def _grade_pill_html(grade: str) -> str:
    color = _GRADE_COLOR.get(grade, "#666")
    return f'<span class="grade-pill" style="background:{color}">{grade}</span>'


def _grade_scale_html(active_grade: str) -> str:
    """Build the horizontal grade arrow scale HTML."""
    boxes = []
    n = len(_GRADE_ORDER)
    for i, g in enumerate(_GRADE_ORDER):
        color = _GRADE_COLOR.get(g, "#666")
        he = _GRADE_HE.get(g, "")
        pos_cls = "pos-first" if i == 0 else ("pos-last" if i == n - 1 else "pos-mid")
        if g == active_grade:
            boxes.append(
                f'<div class="grade-box-active-wrap {pos_cls}" style="background:{color}">'
                f'<div class="active-letter">{g}</div>'
                f'<div class="active-name">{he}</div>'
                f'</div>'
            )
        else:
            boxes.append(
                f'<div class="grade-box {pos_cls}" style="background:{color}">'
                f'<div class="box-letter">{g}</div>'
                f'<div class="box-name">{he}</div>'
                f'</div>'
            )
    return (
        '<div class="grade-scale-wrap">'
        '<div class="grade-scale-label">אנרגיה · Energy Rating Scale</div>'
        '<div class="grade-scale">' + "".join(boxes) + '</div>'
        '</div>'
    )


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
    ep_ref_weighted: float,
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
    costs: Dict,
) -> str:
    grade_color = _GRADE_COLOR.get(grade_letter, "#444")
    grade_scale = _grade_scale_html(grade_letter)

    # ── Cover page ──────────────────────────────────────────────────────────────
    n_units = len(unit_ratings)
    total_unit_area = sum(u["area_m2"] for u in unit_ratings)

    # Project info rows (2 columns × 3 rows)
    project_info = f"""
    <table class="project-info">
      <tr>
        <td class="label">Project</td>
        <td class="value">{project_name}</td>
        <td class="label">Date</td>
        <td class="value">{today}</td>
      </tr>
      <tr>
        <td class="label">Standard</td>
        <td class="value">ת"י 5282 חלק 1 (2024)</td>
        <td class="label">Climate Zone</td>
        <td class="value">{climate_zone}</td>
      </tr>
      <tr>
        <td class="label">Total Units</td>
        <td class="value">{n_units}</td>
        <td class="label">Cond. Area</td>
        <td class="value">{cond_area:,.0f} m²</td>
      </tr>
      <tr>
        <td class="label">EPdes</td>
        <td class="value">{ep_des:.2f} kWh/m²/yr</td>
        <td class="label">EPref</td>
        <td class="value">{ep_ref_weighted:.2f} kWh/m²/yr (weighted)</td>
      </tr>
      <tr>
        <td class="label">IP</td>
        <td class="value"><strong>{ip_pct:+.1f}%</strong></td>
        <td class="label">Engine</td>
        <td class="value">EnergyPlus 25.2</td>
      </tr>
    </table>"""

    # 5-year cost bars
    ref_nis = costs["ref_nis"]
    sav_nis = costs["savings_nis"]
    sav_pct = costs["savings_pct"]
    bar_savings_width = min(100.0, sav_pct)  # savings bar relative to reference
    cost_bars = f"""
    <div class="cost-section">
      <h3>5-Year Electricity Cost Comparison (estimated)</h3>
      <div class="cost-bar-row">
        <div class="cost-bar-label">Reference</div>
        <div class="cost-bar-track">
          <div class="cost-bar-fill bar-ref" style="width:100%">
            {ref_nis:,.0f} ₪
          </div>
        </div>
      </div>
      <div class="cost-bar-row">
        <div class="cost-bar-label">Savings</div>
        <div class="cost-bar-track">
          <div class="cost-bar-fill bar-save" style="width:{bar_savings_width:.1f}%">
            {sav_nis:,.0f} ₪&nbsp;({sav_pct:.1f}%)
          </div>
        </div>
      </div>
      <p class="cost-note">
        Estimate: EPref × area × {_COST_YEARS} yr × {_ELECTRICITY_RATE_NIS} NIS/kWh.
        Weighted EPref = {ep_ref_weighted:.2f} kWh/m²/yr.
      </p>
    </div>"""

    # ── Results page: summary bar ───────────────────────────────────────────────
    weighted_score = building_grade_info["weighted_score"]
    summary_bar = f"""
    <div class="summary-bar">
      <div class="sb-item"><strong>{n_units}</strong> units</div>
      <div class="sb-item">Weighted score: <strong>{weighted_score:.2f}</strong></div>
      <div class="sb-item">Score: <strong>{building_grade_info['score']}</strong></div>
      <div class="sb-item">IP: <strong>{ip_pct:+.1f}%</strong></div>
      <div class="sb-grade">
        <div class="sb-grade-badge" style="background:{grade_color}">{grade_letter}</div>
        <div style="font-size:9pt;color:#1a1a2e;">
          <strong>{grade_en}</strong><br>{grade_he}
        </div>
      </div>
    </div>"""

    # ── EPref section ───────────────────────────────────────────────────────────
    if tabulated_epref:
        epref_rows = "".join(
            f"<tr><td>{ft.capitalize()}</td><td class='num'>{ep_ref_by_floor_type[ft]:.2f}</td></tr>"
            for ft in ("ground", "middle", "top") if ft in ep_ref_by_floor_type
        )
        epref_section = f"""
        <h3>Reference EPref — SI 5282 Part 1, Annex ג (Zone {climate_zone})</h3>
        <table>
            <thead><tr><th>Floor Type</th><th>EPref [kWh/m²/yr]</th></tr></thead>
            <tbody>{epref_rows}</tbody>
        </table>
        <p class="epref-source">Tabulated per SI 5282 Part 1 (2024). COP = {cop}.
        Units ≤ 50 m² use higher EPref per standard.</p>"""
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
        <p class="epref-source" style="margin-bottom:5pt">Unit: {int(box_area)} m²
        (10×10×3 m), 4 orientations. COP = {cop}.</p>
        <table>
            <thead><tr>
                <th>Floor Type</th><th>S (kWh)</th><th>W (kWh)</th>
                <th>N (kWh)</th><th>E (kWh)</th>
                <th>Avg/m²</th><th>EPref</th>
            </tr></thead>
            <tbody>{epref_rows}</tbody>
        </table>"""

    # ── Grade distribution ──────────────────────────────────────────────────────
    dist_items = "".join(
        f'<div class="dist-item">'
        f'<div class="dist-swatch" style="background:{_GRADE_COLOR.get(g,"#666")}"></div>'
        f'<span><strong>{g}</strong> {_GRADE_HE.get(g,"")} — {n} unit{"s" if n>1 else ""}</span>'
        f'</div>'
        for g, n in sorted(grade_dist.items(), key=lambda x: -_GRADE_TO_SCORE.get(x[0], -1))
    )

    # ── Per-unit table (Evergreen _Results columns) ─────────────────────────────
    unit_rows = ""
    for u in unit_ratings:
        g = u["grade"]["grade"]
        pill = _grade_pill_html(g)
        cop_u = u.get("cop", cop)
        area = u["area_m2"]
        cooling_m2 = u["cooling_kwh"] / cop_u / area if area > 0 else 0.0
        heating_m2 = u["heating_kwh"] / cop_u / area if area > 0 else 0.0
        fan_m2 = 0.0
        ip = u["ip_percent"]
        orient = u.get("orientation", "")
        unit_rows += (
            f"<tr>"
            f"<td>{_flat_floor(u['flat_id'])}</td>"
            f"<td class='ctr'>{_flat_unit_number(u['flat_id'])}</td>"
            f"<td class='ctr'>{u['floor_type'][:3].capitalize()}</td>"
            f"<td class='num'>{area:.1f}</td>"
            f"<td class='num'>{u['ep_des_kwh_m2']:.2f}</td>"
            f"<td class='num'>{cooling_m2:.2f}</td>"
            f"<td class='num'>{heating_m2:.2f}</td>"
            f"<td class='num'>{fan_m2:.2f}</td>"
            f"<td class='num'>{u['ep_ref_kwh_m2']:.2f}</td>"
            f"<td class='num'>{ip:+.1f}%</td>"
            f"<td class='ctr'>{orient}</td>"
            f"<td class='ctr'>{pill}</td>"
            f"</tr>"
        )

    # ── Window summary ──────────────────────────────────────────────────────────
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

    # ── Assemble HTML ───────────────────────────────────────────────────────────
    html = f"""<!DOCTYPE html>
<html lang="he-IL">
<head>
<meta charset="UTF-8">
<style>{_HTML_CSS}</style>
</head>
<body>

<!-- ═══════════════════════════════════════════ PAGE 1: COVER ══ -->
<div class="page">

  <div class="cover-top">
    <div class="cover-brand">il&#8209;energy</div>
    <div class="cover-standard">
      ת"י 5282 חלק 1 (2024)<br>SI 5282 Part 1 — Residential Energy Rating
    </div>
  </div>

  <div class="cover-title">
    <h1>דוח דירוג אנרגטי</h1>
    <h2>Energy Rating Certificate</h2>
  </div>

  {grade_scale}

  {project_info}

  {cost_bars}

  <div class="footer">
    <span>il-energy — SI 5282 Compliance Engine</span>
    <span>{project_name} &nbsp;|&nbsp; {today}</span>
  </div>

</div>

<!-- ═══════════════════════════════════════════ PAGE 2: RESULTS ══ -->
<div class="page-break"></div>
<div class="page">

  <div class="results-header">
    <div>
      <h1>Per-Unit Results — ת"י 5282 חלק 1</h1>
    </div>
    <div class="meta">
      <div><strong>Project:</strong> {project_name}</div>
      <div><strong>Date:</strong> {today}</div>
      <div><strong>Zone:</strong> {climate_zone} &nbsp;|&nbsp; <strong>COP:</strong> {cop}</div>
    </div>
  </div>

  {summary_bar}

  {epref_section}

  <h3>Grade Distribution</h3>
  <div class="dist-bar">{dist_items}</div>

  <h3>Per-Unit Energy Results ({n_units} Apartments)</h3>
  <table>
    <thead>
      <tr>
        <th>Floor</th>
        <th>Flat</th>
        <th>Type</th>
        <th>Area m²</th>
        <th>EPdes Sum</th>
        <th>Cooling</th>
        <th>Heating</th>
        <th>Fan</th>
        <th>EPref</th>
        <th>Savings%</th>
        <th>Orient</th>
        <th>Grade</th>
      </tr>
    </thead>
    <tbody>{unit_rows}</tbody>
  </table>
  <p class="epref-source">All EPdes values in kWh/m²/yr electrical (sensible HVAC ÷ COP {cop}).
  Fan = 0 (no central fan system). EPref per SI 5282 Part 1 Annex ג, Zone {climate_zone}.</p>

  <div class="footer">
    <span>il-energy — SI 5282 Compliance Engine</span>
    <span>{project_name} &nbsp;|&nbsp; {today}</span>
  </div>

</div>

<!-- ═══════════════════════════════════════════ PAGE 3: WINDOWS ══ -->
<div class="page-break"></div>
<div class="page">

  <div class="results-header">
    <div>
      <h1>Window Analysis — ת"י 5282 חלק 1</h1>
    </div>
    <div class="meta">
      <div><strong>Project:</strong> {project_name}</div>
      <div><strong>Date:</strong> {today}</div>
      <div>Total: {total_windows} windows, {total_glass_area:.1f} m² glass</div>
    </div>
  </div>

  <table>
    <thead>
      <tr>
        <th>Unit</th><th>Count</th><th>Glass Area m²</th>
        <th>Avg U W/m²K</th><th>Avg SHGC</th><th>WWR</th><th>Orientations</th>
      </tr>
    </thead>
    <tbody>{win_rows}</tbody>
  </table>

  <h3>Methodology</h3>
  <table>
    <tbody>
      <tr><td><strong>EPdes</strong></td>
          <td>Σ(zone sensible cooling + heating) ÷ COP({cop}) ÷ unit area [kWh/m²/yr electrical]</td></tr>
      <tr><td><strong>EPref</strong></td>
          <td>{'SI 5282 Part 1 Annex ג — reference box simulation (100 m², 4 orientations) per floor type (Zone ' + climate_zone + ')' if not tabulated_epref else 'SI 5282 Part 1 Annex ג tabulated values by floor type and unit area (Zone ' + climate_zone + ')'}</td></tr>
      <tr><td><strong>IP</strong></td>
          <td>(EPref − EPdes) ÷ EPref × 100 %</td></tr>
      <tr><td><strong>Floor type</strong></td>
          <td>Ground = lowest floor · Top = exposed-roof ratio ≥ 50% or highest floor · Middle = all others</td></tr>
      <tr><td><strong>Building grade</strong></td>
          <td>Area-weighted average of unit scores, rounded to nearest integer</td></tr>
      <tr><td><strong>5-year cost</strong></td>
          <td>EPref × area × 5 yr × {_ELECTRICITY_RATE_NIS} NIS/kWh (reference) vs EPdes (proposed)</td></tr>
    </tbody>
  </table>

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
        Dict mapping "report_md", "report_pdf", "units_csv", "windows_csv" to paths.
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

    # Area-weighted EPref (used for 5-year cost computation)
    total_unit_area = sum(u["area_m2"] for u in unit_ratings)
    if unit_ratings and total_unit_area > 0:
        ep_ref_weighted = sum(u["ep_ref_kwh_m2"] * u["area_m2"] for u in unit_ratings) / total_unit_area
    else:
        ep_ref_weighted = ep_ref

    costs = _five_year_costs(ep_ref_weighted, ep_des, cond_area)

    window_records = build_window_records(output, shading_ctrl_names)
    win_summary = window_summary_by_flat(window_records)
    total_windows = sum(s["window_count"] for s in win_summary.values())
    total_glass_area = sum(s["total_glass_area_m2"] for s in win_summary.values())

    grade_dist: Dict[str, int] = {}
    for u in unit_ratings:
        g = u["grade"]["grade"]
        grade_dist[g] = grade_dist.get(g, 0) + 1

    # ── Markdown report ───────────────────────────────────────────────────────────
    lines: List[str] = [
        "# SI 5282 Energy Rating Report",
        f"## {project_name or 'Building Energy Rating'}",
        "",
        f"**Date:** {today}  |  **Standard:** SI 5282 Part 1 (2024)  |  **Zone:** {climate_zone}  |  **Engine:** EnergyPlus 25.2",
        "",
        "---",
        "",
        f"## Grade {grade_letter} — {grade_en} / {grade_he}",
        "",
        "| Metric | Value |",
        "|--------|-------|",
        f"| IP (Improvement Percentage) | **{ip_pct:+.1f}%** |",
        f"| EPdes (proposed) | {ep_des:.2f} kWh/m²/yr |",
        f"| EPref weighted | {ep_ref_weighted:.2f} kWh/m²/yr |",
        f"| Weighted building score | {building_grade_info['weighted_score']:.2f} → Grade {grade_letter} |",
        f"| 5-year reference cost | {costs['ref_nis']:,.0f} ₪ |",
        f"| 5-year savings | {costs['savings_nis']:,.0f} ₪ ({costs['savings_pct']:.1f}%) |",
        "",
        "---",
        "",
        "## Building Summary",
        "",
        "| Metric | Value |",
        "|--------|-------|",
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
            "| Floor Type | EPref [kWh/m²/yr] |",
            "|------------|------------------|",
        ]
        for ft in ("ground", "middle", "top"):
            if ft in ep_ref_by_floor_type:
                lines.append(f"| {ft.capitalize()} | {ep_ref_by_floor_type[ft]:.2f} |")
        lines += ["", f"_Tabulated per SI 5282 Part 1 (2024), Zone {climate_zone}. COP = {cop}._"]
    else:
        lines += [
            f"Reference unit: {int(box_area)} m² (10×10×3 m), 4 cardinal orientations.",
            "",
            "| Floor type | S (kWh) | W (kWh) | N (kWh) | E (kWh) | EPref [kWh/m²/yr] |",
            "|------------|---------|---------|---------|---------|------------------|",
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
        "| Floor | Flat | Type | Area m² | EPdes | Cooling | Heating | Fan | EPref | Savings% | Grade |",
        "|-------|------|------|---------|-------|---------|---------|-----|-------|----------|-------|",
    ]
    for u in unit_ratings:
        cop_u = u.get("cop", cop)
        area = u["area_m2"]
        c_m2 = u["cooling_kwh"] / cop_u / area if area > 0 else 0.0
        h_m2 = u["heating_kwh"] / cop_u / area if area > 0 else 0.0
        g = u["grade"]["grade"]
        lines.append(
            f"| {_flat_floor(u['flat_id'])} | {_flat_unit_number(u['flat_id'])} "
            f"| {u['floor_type'][:3]} | {area:.1f} "
            f"| {u['ep_des_kwh_m2']:.2f} | {c_m2:.2f} | {h_m2:.2f} | 0.00 "
            f"| {u['ep_ref_kwh_m2']:.2f} | {u['ip_percent']:+.1f}% | **{g}** {_GRADE_HE.get(g, '')} |"
        )

    lines += [
        "",
        "---",
        "",
        "## Window Analysis Summary",
        "",
        "| Unit | Windows | Glass Area m² | Avg U W/m²K | Avg SHGC | WWR | Orientations |",
        "|------|---------|---------------|-------------|----------|-----|--------------|",
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
        "- **EPdes** = Σ(zone sensible cooling + heating) / COP / area [kWh/m²/yr electrical]",
        (f"- **EPref** = SI 5282 Part 1 Annex ג tabulated values by floor type (Zone {climate_zone})"
         if tabulated_epref else
         f"- **EPref** = SI 5282 Part 1 Annex ג reference box simulation — 100 m², 4 orientations, per floor type (Zone {climate_zone})"),
        "- **IP** = (EPref − EPdes) / EPref × 100 %",
        "- **Building grade** = area-weighted average of unit scores, rounded to integer",
        f"- **5-year cost** = EPref × area × 5 yr × {_ELECTRICITY_RATE_NIS} NIS/kWh",
        "",
    ]

    md_path = output_dir / "residential_report.md"
    md_path.write_text("\n".join(lines), encoding="utf-8")

    # ── PDF report ────────────────────────────────────────────────────────────────
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
        ep_ref_weighted=ep_ref_weighted,
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
        costs=costs,
    )
    html_path = output_dir / "residential_report.html"
    html_path.write_text(html_str, encoding="utf-8")

    pdf_path = output_dir / "residential_report.pdf"
    pdf_path = _render_pdf(html_str, html_path, pdf_path)

    # ── units.csv ─────────────────────────────────────────────────────────────────
    units_path = output_dir / "units.csv"
    write_units_csv(unit_ratings, units_path)

    # ── windows.csv ───────────────────────────────────────────────────────────────
    windows_path = output_dir / "windows.csv"
    write_windows_csv(window_records, windows_path)

    result = {"report_md": md_path, "units_csv": units_path, "windows_csv": windows_path}
    if pdf_path:
        result["report_pdf"] = pdf_path
    return result
