"""SI 5282 ReportH PDF generator — envelope H-indicator compliance report.

Produces:
  report_h.html  — intermediate HTML
  report_h.pdf   — per-unit per-surface H-value compliance (Evergreen parity)
  h_values.csv   — raw H data for further analysis
"""

from __future__ import annotations

import warnings
from datetime import date
from pathlib import Path
from typing import Dict, List, Optional

from il_energy.envelope.h_value import HValueUnit, write_h_values_csv


# ── CSS ────────────────────────────────────────────────────────────────────────

_CSS = """
* { box-sizing: border-box; margin: 0; padding: 0; }

body {
    font-family: 'Helvetica Neue', Arial, sans-serif;
    font-size: 8.5pt;
    color: #1a1a2e;
    background: #fff;
    line-height: 1.4;
}

.page {
    width: 210mm;
    min-height: 297mm;
    padding: 14mm 14mm 18mm 14mm;
    position: relative;
}

/* ── Page header ─── */
.page-header {
    display: flex;
    justify-content: space-between;
    align-items: flex-end;
    border-bottom: 2px solid #1a1a2e;
    padding-bottom: 6pt;
    margin-bottom: 12pt;
}
.page-header h1 {
    font-size: 13pt;
    font-weight: 700;
    color: #1a1a2e;
}
.page-header .meta {
    text-align: right;
    font-size: 7.5pt;
    color: #666;
    line-height: 1.7;
}

/* ── Unit block ─── */
.unit-block {
    margin-bottom: 14pt;
    page-break-inside: avoid;
}

/* Unit title bar */
.unit-title {
    display: flex;
    align-items: center;
    gap: 10pt;
    background: #e8eaf0;
    border-left: 4px solid #1a1a2e;
    padding: 5pt 8pt;
    margin-bottom: 0;
    font-size: 8.5pt;
    font-weight: 600;
}
.unit-title .ut-floor { color: #555; font-weight: 400; }
.unit-title .ut-area  { margin-left: auto; color: #444; font-weight: 400; }

/* Surface table */
table {
    width: 100%;
    border-collapse: collapse;
    font-size: 7.8pt;
}
thead tr { background: #2c2c3e; color: white; }
thead th {
    padding: 3.5pt 5pt;
    text-align: left;
    font-weight: 500;
    font-size: 7.5pt;
    white-space: nowrap;
}
tbody tr:nth-child(even) { background: #f7f8fa; }
tbody td {
    padding: 3pt 5pt;
    border-bottom: 1px solid #e8eaed;
    color: #2c2c3e;
}
.num { text-align: right; font-variant-numeric: tabular-nums; }
.ctr { text-align: center; }

/* Surface type badge */
.stype {
    display: inline-block;
    border-radius: 2px;
    padding: 0 4pt;
    font-size: 6.8pt;
    font-weight: 600;
    color: white;
    background: #888;
}
.stype-Wall    { background: #6b7280; }
.stype-Roof    { background: #b45309; }
.stype-Floor   { background: #0369a1; }
.stype-Glazing { background: #0e7490; }
.stype-Frame   { background: #475569; }

/* Adjacency text */
.adj-semi { color: #d97706; font-style: italic; }

/* H result row */
.h-result-row td {
    padding: 4pt 5pt;
    font-weight: 600;
    font-size: 8pt;
    border-top: 1.5px solid #ccc;
    border-bottom: none;
}
.h-pass { background: #d1fae5 !important; color: #065f46; }
.h-fail { background: #fee2e2 !important; color: #991b1b; }

.pass-badge, .fail-badge {
    display: inline-block;
    border-radius: 3px;
    padding: 1pt 6pt;
    font-size: 8pt;
    font-weight: 700;
    color: white;
}
.pass-badge { background: #059669; }
.fail-badge { background: #dc2626; }

/* ── Summary table ─── */
.summary-table { margin-bottom: 14pt; }
.summary-table table thead tr { background: #1a1a2e; }

/* ── Footer ─── */
.footer {
    position: fixed;
    bottom: 8mm;
    left: 14mm;
    right: 14mm;
    display: flex;
    justify-content: space-between;
    font-size: 6.5pt;
    color: #bbb;
    border-top: 1px solid #e0e0e0;
    padding-top: 3pt;
}

.page-break { page-break-before: always; }
"""


# ── Helpers ────────────────────────────────────────────────────────────────────

def _render_pdf(html_str: str, html_path: Path, pdf_path: Path) -> Optional[Path]:
    """WeasyPrint → Chrome headless fallback."""
    try:
        from weasyprint import HTML as WP_HTML
        WP_HTML(string=html_str, base_url=str(html_path.parent)).write_pdf(str(pdf_path))
        return pdf_path
    except Exception:
        pass

    import subprocess
    import shutil
    for c in [
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        "google-chrome", "chromium", "chromium-browser",
    ]:
        if shutil.which(c) or (c.startswith("/") and Path(c).exists()):
            try:
                subprocess.run(
                    [c, "--headless=new", "--disable-gpu", "--no-sandbox",
                     f"--print-to-pdf={pdf_path}", "--print-to-pdf-no-header",
                     str(html_path)],
                    check=True, capture_output=True,
                )
                if pdf_path.exists() and pdf_path.stat().st_size > 0:
                    return pdf_path
            except Exception as e:
                warnings.warn(f"Chrome PDF failed: {e}")
            break

    warnings.warn("PDF generation skipped — install WeasyPrint or Chrome. HTML: " + str(html_path))
    return None


def _stype_badge(stype: str) -> str:
    return f'<span class="stype stype-{stype}">{stype}</span>'


def _adj_cell(adjacency: str) -> str:
    if adjacency == "Semi-Exterior":
        return f'<span class="adj-semi">{adjacency}</span>'
    return adjacency


# ── HTML builder ───────────────────────────────────────────────────────────────

def _build_html(
    h_units: List[HValueUnit],
    project_name: str,
    today: str,
    climate_zone: str,
    building_type: str,
) -> str:
    btype_label = "New Building" if building_type == "new" else "Existing Building"

    # ── Page header (repeated on each page via fixed position trick) ──────────
    page_header = f"""
  <div class="page-header">
    <div>
      <h1>ReportH — Envelope H-Indicator &nbsp;|&nbsp; ת"י 5282 חלק 1</h1>
      <div style="font-size:8pt;color:#555;margin-top:2pt">
        {btype_label} &nbsp;·&nbsp; Climate Zone {climate_zone}
      </div>
    </div>
    <div class="meta">
      <div><strong>{project_name}</strong></div>
      <div>{today}</div>
    </div>
  </div>"""

    # ── Summary table ─────────────────────────────────────────────────────────
    pass_count = sum(1 for hu in h_units if hu.passes)
    fail_count = len(h_units) - pass_count
    summary_rows = ""
    for hu in h_units:
        badge = ('<span class="pass-badge">Pass</span>' if hu.passes
                 else '<span class="fail-badge">Fail</span>')
        h_color = "#065f46" if hu.passes else "#991b1b"
        summary_rows += (
            f"<tr>"
            f"<td>{hu.floor_name}</td>"
            f"<td class='ctr'>{hu.unit_name}</td>"
            f"<td>{hu.floor_type.capitalize()}</td>"
            f"<td class='num'>{hu.unit_area_m2:.1f}</td>"
            f"<td class='num' style='color:{h_color};font-weight:600'>{hu.calculated_h:.3f}</td>"
            f"<td class='num'>{hu.required_h:.2f}</td>"
            f"<td class='ctr'>{badge}</td>"
            f"</tr>"
        )

    summary_section = f"""
  <div class="summary-table">
    <table>
      <thead>
        <tr>
          <th>Floor</th><th>Unit</th><th>Type</th>
          <th>Area m²</th><th>H calc</th><th>H req</th><th>Result</th>
        </tr>
      </thead>
      <tbody>{summary_rows}</tbody>
    </table>
    <p style="font-size:7pt;color:#777;margin-top:4pt">
      {pass_count} units pass · {fail_count} units fail ·
      H_req = 2.10 W/m²K (ground/middle) · 2.70 W/m²K (top/above unconditioned)
    </p>
  </div>"""

    # ── Per-unit blocks ───────────────────────────────────────────────────────
    unit_blocks = ""
    for hu in h_units:
        h_row_cls = "h-pass" if hu.passes else "h-fail"
        badge_html = ('<span class="pass-badge">✓ Pass</span>' if hu.passes
                      else '<span class="fail-badge">✗ Fail</span>')

        surface_rows = ""
        for s in sorted(hu.surfaces, key=lambda x: (x.surface_type, x.surface_name)):
            surface_rows += (
                f"<tr>"
                f"<td style='font-size:7pt;color:#555'>{s.surface_name}</td>"
                f"<td>{s.construction}</td>"
                f"<td>{_adj_cell(s.adjacency)}</td>"
                f"<td class='ctr'>{_stype_badge(s.surface_type)}</td>"
                f"<td class='num'>{s.net_area_m2:.3f}</td>"
                f"<td class='num'>{s.um:.3f}</td>"
                f"<td class='num'>{s.u_times_a:.3f}</td>"
                f"</tr>"
            )

        total_ua = sum(s.u_times_a for s in hu.surfaces)

        unit_blocks += f"""
  <div class="unit-block">
    <div class="unit-title">
      <span>{hu.floor_name}</span>
      <span style="color:#1a1a2e">Unit {hu.unit_name}</span>
      <span class="ut-floor">{hu.floor_type.capitalize()} floor</span>
      <span class="ut-area">Floor area: {hu.unit_area_m2:.1f} m²</span>
    </div>
    <table>
      <thead>
        <tr>
          <th>Surface Name</th>
          <th>Construction</th>
          <th>Adjacency</th>
          <th>Type</th>
          <th>Net Area m²</th>
          <th>Um W/m²K</th>
          <th>U×A W/K</th>
        </tr>
      </thead>
      <tbody>
        {surface_rows}
        <tr class="h-result-row {h_row_cls}">
          <td colspan="4">{badge_html} &nbsp;
            <strong>H = {hu.calculated_h:.3f}</strong> W/m²K
            &nbsp;(Required: {hu.required_h:.2f} W/m²K)
          </td>
          <td class="num">{sum(s.net_area_m2 for s in hu.surfaces):.2f}</td>
          <td></td>
          <td class="num">{total_ua:.3f}</td>
        </tr>
      </tbody>
    </table>
  </div>"""

    # ── Footer ────────────────────────────────────────────────────────────────
    footer = f"""
  <div class="footer">
    <span>il-energy — SI 5282 Compliance Engine &nbsp;|&nbsp; H = Σ(U×A)/A_floor</span>
    <span>{project_name} &nbsp;|&nbsp; {today}</span>
  </div>"""

    return f"""<!DOCTYPE html>
<html lang="he-IL">
<head>
<meta charset="UTF-8">
<style>{_CSS}</style>
</head>
<body>
<div class="page">
{page_header}
<h3 style="font-size:8.5pt;font-weight:600;text-transform:uppercase;
           letter-spacing:0.5px;border-bottom:1.5px solid #e0e0e0;
           padding-bottom:3pt;margin-bottom:8pt">
  Building Summary — {len(h_units)} units
</h3>
{summary_section}
<div class="page-break"></div>
<div class="page">
{page_header}
{unit_blocks}
{footer}
</div>
</div>
</body>
</html>"""


# ── Public entry point ─────────────────────────────────────────────────────────

def generate_report_h(
    h_units: List[HValueUnit],
    output_dir: Path,
    project_name: str = "",
    climate_zone: str = "B",
    building_type: str = "new",
) -> Dict[str, Path]:
    """Generate ReportH PDF + HTML + CSV.

    Args:
        h_units:       List from compute_h_value_units().
        output_dir:    Directory to write files into.
        project_name:  Project label for headers.
        climate_zone:  "A", "B", or "C".
        building_type: "new" or "existing".

    Returns:
        Dict with keys "report_h_html", "report_h_pdf" (if rendered), "h_values_csv".
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    today = date.today().strftime("%d %B %Y")
    name = project_name or "Building Energy Rating"

    html_str = _build_html(h_units, name, today, climate_zone, building_type)

    html_path = output_dir / "report_h.html"
    html_path.write_text(html_str, encoding="utf-8")

    pdf_path = output_dir / "report_h.pdf"
    pdf_result = _render_pdf(html_str, html_path, pdf_path)

    csv_path = output_dir / "h_values.csv"
    write_h_values_csv(h_units, csv_path)

    result: Dict[str, Path] = {
        "report_h_html": html_path,
        "h_values_csv": csv_path,
    }
    if pdf_result:
        result["report_h_pdf"] = pdf_result
    return result
