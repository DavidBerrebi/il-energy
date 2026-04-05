"""SI 1045 Report — Construction Surface thermal insulation compliance.

Produces:
  report_1045.html — intermediate HTML
  report_1045.pdf  — construction assembly table (Evergreen parity)

The report lists each unique exterior/semi-exterior construction used in the
building with its material layers, thermal resistance, density, and pass/fail
against SI 1045 minimum required resistance values.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import List, Optional

from il_energy.models import ConstructionAssembly

_STANDARDS_DIR = Path(__file__).resolve().parent.parent.parent.parent / "standards" / "si5282"


# ── Load SI 1045 required resistance values ─────────────────────────────────

def _load_required_resistances(climate_zone: str) -> dict[str, float]:
    """Return required resistance map for a climate zone.

    Keys: ``wall_exterior``, ``wall_semi_exterior``, ``roof_exterior``,
    ``floor_exterior``, ``floor_semi_exterior``, ``ceiling_semi_exterior``.
    """
    path = _STANDARDS_DIR / "si1045_resistance.json"
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    return data.get(climate_zone, data["A"])


def _lookup_required_resistance(
    reqs: dict[str, float],
    surface_class: str,
    adjacency: str,
) -> float:
    """Map surface class + adjacency to SI 1045 required resistance."""
    key = f"{surface_class.lower()}_{adjacency.lower().replace('-', '_')}"
    return reqs.get(key, 0.0)


def assign_required_resistances(
    assemblies: List[ConstructionAssembly],
    climate_zone: str,
) -> None:
    """Populate ``required_resistance_m2kw`` on each assembly in-place."""
    reqs = _load_required_resistances(climate_zone)
    for a in assemblies:
        a.required_resistance_m2kw = _lookup_required_resistance(
            reqs, a.surface_class, a.adjacency,
        )


# ── CSS ──────────────────────────────────────────────────────────────────────

_CSS = """
* { box-sizing: border-box; margin: 0; padding: 0; }

body {
    font-family: 'Helvetica Neue', Arial, sans-serif;
    font-size: 8pt;
    color: #1a1a2e;
    background: #fff;
    line-height: 1.35;
}

@page {
    size: A4 landscape;
    margin: 12mm 10mm 14mm 10mm;
}

.page {
    width: 297mm;
    padding: 10mm;
    position: relative;
}

.page-header {
    display: flex;
    justify-content: space-between;
    align-items: flex-end;
    border-bottom: 2px solid #1a1a2e;
    padding-bottom: 5pt;
    margin-bottom: 10pt;
}
.page-header h1 {
    font-size: 12pt;
    font-weight: 700;
    color: #1a1a2e;
}
.page-header .meta {
    text-align: right;
    font-size: 7pt;
    color: #666;
    line-height: 1.7;
}

table {
    width: 100%;
    border-collapse: collapse;
    margin-bottom: 6pt;
}
th, td {
    border: 1px solid #c0c0c0;
    padding: 2pt 4pt;
    text-align: left;
    vertical-align: top;
    font-size: 7.5pt;
}
th {
    background: #2d5016;
    color: #fff;
    font-weight: 600;
    font-size: 7pt;
    text-align: center;
    white-space: nowrap;
}
td.num { text-align: right; font-variant-numeric: tabular-nums; }
td.ctr { text-align: center; }

tr.construction-header td {
    background: #f0f4e8;
    font-weight: 600;
    font-size: 7.5pt;
    border-top: 2px solid #2d5016;
}
tr.layer td {
    font-size: 7pt;
    color: #333;
    border-top: none;
    border-bottom: 1px solid #e0e0e0;
}
tr.layer td:first-child {
    padding-left: 12pt;
}

.pass { color: #065f46; font-weight: 700; }
.fail { color: #991b1b; font-weight: 700; }

.footer {
    font-size: 6.5pt;
    color: #888;
    margin-top: 8pt;
    border-top: 1px solid #ddd;
    padding-top: 4pt;
}
"""


# ── HTML builder ─────────────────────────────────────────────────────────────

def _fmt(val: float, decimals: int = 3) -> str:
    return f"{val:.{decimals}f}"


def _build_html(
    assemblies: List[ConstructionAssembly],
    project_name: str,
    today: str,
    climate_zone: str,
) -> str:
    header = f"""
<div class="page-header">
  <div>
    <h1>Report 1045</h1>
    <div style="font-size:8pt;color:#555;margin-top:2pt">
      מבנה מגורים לפי ת"י 5282 חלק 1 (2024)
    </div>
  </div>
  <div class="meta">
    <div><strong>{project_name}</strong></div>
    <div>Climate Zone {climate_zone} &nbsp;·&nbsp; {today}</div>
  </div>
</div>"""

    # Column headers matching expert format
    table_header = """
<table>
  <thead>
    <tr>
      <th style="width:18%">Construction</th>
      <th style="width:6%">Surface<br>Class</th>
      <th style="width:7%">Adjacency</th>
      <th style="width:22%">Material (Outside to Inside)</th>
      <th style="width:6%">Thickness<br>(m)</th>
      <th style="width:7%">Conductivity<br>(W/m-K)</th>
      <th style="width:7%">Resistance<br>(m2-K/W)</th>
      <th style="width:6%">Density<br>(Kg/m2)</th>
      <th style="width:7%">Calculated<br>density</th>
      <th style="width:7%">Required<br>resistance</th>
      <th style="width:7%">Calculated<br>resistance</th>
    </tr>
  </thead>
  <tbody>"""

    rows = ""
    for a in assemblies:
        n_layers = len(a.layers)
        passes = a.calculated_resistance_m2kw >= a.required_resistance_m2kw
        result_cls = "pass" if passes else "fail"

        # First row: construction header with first material layer
        if n_layers > 0:
            first = a.layers[0]
            rows += (
                f'<tr class="construction-header">'
                f'<td rowspan="{n_layers}">{a.name}</td>'
                f'<td rowspan="{n_layers}" class="ctr">{a.surface_class}</td>'
                f'<td rowspan="{n_layers}" class="ctr">{a.adjacency}</td>'
                f'<td>{first.name}</td>'
                f'<td class="num">{_fmt(first.thickness_m, 3)}</td>'
                f'<td class="num">{_fmt(first.conductivity_w_mk, 4) if first.conductivity_w_mk else ""}</td>'
                f'<td class="num">{_fmt(first.resistance_m2kw, 3)}</td>'
                f'<td class="num">{_fmt(first.calculated_density_kg_m2, 0) if first.calculated_density_kg_m2 else ""}</td>'
                f'<td rowspan="{n_layers}" class="num">{_fmt(a.calculated_density_kg_m2, 1)}</td>'
                f'<td rowspan="{n_layers}" class="num">{_fmt(a.required_resistance_m2kw, 2) if a.required_resistance_m2kw else ""}</td>'
                f'<td rowspan="{n_layers}" class="num {result_cls}">{_fmt(a.calculated_resistance_m2kw, 3)}</td>'
                f'</tr>\n'
            )
            # Subsequent material layers
            for layer in a.layers[1:]:
                rows += (
                    f'<tr class="layer">'
                    f'<td>{layer.name}</td>'
                    f'<td class="num">{_fmt(layer.thickness_m, 3)}</td>'
                    f'<td class="num">{_fmt(layer.conductivity_w_mk, 4) if layer.conductivity_w_mk else ""}</td>'
                    f'<td class="num">{_fmt(layer.resistance_m2kw, 3)}</td>'
                    f'<td class="num">{_fmt(layer.calculated_density_kg_m2, 0) if layer.calculated_density_kg_m2 else ""}</td>'
                    f'</tr>\n'
                )
        else:
            rows += (
                f'<tr class="construction-header">'
                f'<td>{a.name}</td>'
                f'<td class="ctr">{a.surface_class}</td>'
                f'<td class="ctr">{a.adjacency}</td>'
                f'<td colspan="5">No material layers found</td>'
                f'<td class="num">{_fmt(a.calculated_density_kg_m2, 1)}</td>'
                f'<td class="num">{_fmt(a.required_resistance_m2kw, 1)}</td>'
                f'<td class="num">{_fmt(a.calculated_resistance_m2kw, 3)}</td>'
                f'</tr>\n'
            )

    table_footer = """
  </tbody>
</table>"""

    footer = f"""
<div class="footer">
  {project_name} &nbsp;·&nbsp; {today}
</div>"""

    return (
        f"<!DOCTYPE html><html><head><meta charset='utf-8'>"
        f"<style>{_CSS}</style></head><body>"
        f"<div class='page'>{header}{table_header}{rows}{table_footer}{footer}</div>"
        f"</body></html>"
    )


# ── PDF conversion ───────────────────────────────────────────────────────────

def _html_to_pdf(html_path: Path, pdf_path: Path) -> bool:
    """Convert HTML to PDF via WeasyPrint (primary) or Chrome headless."""
    try:
        import weasyprint  # type: ignore
        with open(html_path, encoding="utf-8") as f:
            html_str = f.read()
        weasyprint.HTML(string=html_str).write_pdf(str(pdf_path))
        return True
    except Exception:
        pass

    import subprocess
    for chrome in (
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        "google-chrome", "chromium-browser",
    ):
        try:
            subprocess.run(
                [chrome, "--headless", "--disable-gpu", "--no-sandbox",
                 f"--print-to-pdf={pdf_path}", str(html_path)],
                check=True, capture_output=True, timeout=30,
            )
            return True
        except Exception:
            continue
    return False


# ── Public API ───────────────────────────────────────────────────────────────

def generate_report_1045(
    assemblies: List[ConstructionAssembly],
    output_dir: Path,
    project_name: str = "",
    climate_zone: str = "A",
) -> dict[str, Path]:
    """Generate Report 1045 (SI 1045 thermal insulation compliance).

    Returns dict of generated file paths keyed by type.
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    today = date.today().strftime("%d-%m-%Y")
    if not project_name:
        project_name = "Residential Building"

    # Assign required resistances
    assign_required_resistances(assemblies, climate_zone)

    # Sort: Walls first, then Roof, Floor, Ceiling
    order = {"Wall": 0, "Roof": 1, "Floor": 2, "Ceiling": 3}
    adj_order = {"Semi-Exterior": 0, "Exterior": 1}
    assemblies.sort(key=lambda a: (order.get(a.surface_class, 9), adj_order.get(a.adjacency, 9)))

    html_str = _build_html(assemblies, project_name, today, climate_zone)

    paths: dict[str, Path] = {}

    html_path = output_dir / "report_1045.html"
    html_path.write_text(html_str, encoding="utf-8")
    paths["html"] = html_path

    pdf_path = output_dir / "report_1045.pdf"
    if _html_to_pdf(html_path, pdf_path):
        paths["pdf"] = pdf_path

    return paths
