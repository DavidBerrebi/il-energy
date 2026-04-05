"""Generate Evergreen-parity PDF reports for each IDF object class.

One PDF per IDF class (e.g. Material.pdf, Construction.pdf …).
Layout: landscape A4, 2-object columns per block, field names + units columns,
object names in bold red, Hebrew note in header, footer with filename + date.
"""

from __future__ import annotations

import html
import subprocess
from datetime import date
from pathlib import Path
from typing import Dict, List, Optional

from il_energy.simulation.idf_object_parser import IDFField, IDFObject
from il_energy.report.idf_class_registry import IDFClassDef


# ── CSS ───────────────────────────────────────────────────────────────────────

_CSS = """
* { box-sizing: border-box; margin: 0; padding: 0; }

body {
    font-family: 'Helvetica Neue', Arial, sans-serif;
    font-size: 7.5pt;
    color: #1a1a1a;
    background: #fff;
    line-height: 1.3;
}

@page {
    size: A4 landscape;
    margin: 10mm 8mm 12mm 8mm;
}

.page {
    width: 277mm;
    padding: 6mm;
    position: relative;
}

.page-header {
    display: flex;
    justify-content: space-between;
    align-items: flex-end;
    border-bottom: 2px solid #1a1a2e;
    padding-bottom: 4pt;
    margin-bottom: 8pt;
}
.page-header h1 {
    font-size: 11pt;
    font-weight: 700;
    color: #1a1a2e;
}
.page-header .note {
    font-size: 7pt;
    color: #555;
    text-align: right;
}

.block {
    margin-bottom: 10pt;
    page-break-inside: avoid;
}

table {
    width: 100%;
    border-collapse: collapse;
    font-size: 7pt;
}
th, td {
    border: 1px solid #c8c8c8;
    padding: 2pt 3pt;
    vertical-align: top;
}
th {
    background: #2d5016;
    color: #fff;
    font-weight: 600;
    text-align: center;
    white-space: nowrap;
    font-size: 7pt;
}
th.obj-name {
    color: #cc0000;
    background: #f5f0f0;
    font-weight: 700;
    font-size: 7pt;
    text-align: left;
}
td.field-name {
    background: #f7f7f7;
    font-weight: 500;
    width: 28%;
}
td.unit-col {
    background: #f7f7f7;
    color: #555;
    width: 10%;
    text-align: center;
}
td.value-col {
    width: 31%;
    word-break: break-word;
}
td.empty-col {
    background: #fafafa;
    color: #aaa;
    text-align: center;
    font-style: italic;
}
tr:nth-child(even) td.field-name,
tr:nth-child(even) td.unit-col {
    background: #efefef;
}

.footer {
    font-size: 6pt;
    color: #888;
    margin-top: 6pt;
    border-top: 1px solid #ddd;
    padding-top: 3pt;
    display: flex;
    justify-content: space-between;
}
"""


# ── Helpers ───────────────────────────────────────────────────────────────────

def _h(text: str) -> str:
    """HTML-escape a string."""
    return html.escape(str(text))


def _get_fields(obj: IDFObject, field_indices: Optional[List[int]]) -> List[IDFField]:
    """Return ordered list of fields to display for an object.

    Args:
        obj: Parsed IDF object.
        field_indices: 1-based indices into obj.fields.  None = all fields.
    """
    if field_indices is None:
        return list(obj.fields)
    result = []
    for idx in field_indices:
        i = idx - 1  # convert to 0-based
        if i < len(obj.fields):
            result.append(obj.fields[i])
        else:
            result.append(IDFField(value="", name="", unit=""))
    return result


def _merged_field_rows(
    obj_a: IDFObject,
    obj_b: Optional[IDFObject],
    field_indices: Optional[List[int]],
) -> List[tuple]:
    """Build merged field rows for a 2-column block.

    Returns list of (field_name, unit, value_a, value_b) tuples.
    Pads shorter object to length of longer one.
    """
    fields_a = _get_fields(obj_a, field_indices)
    fields_b = _get_fields(obj_b, field_indices) if obj_b else []

    n = max(len(fields_a), len(fields_b))
    empty = IDFField(value="", name="", unit="")

    rows = []
    for i in range(n):
        fa = fields_a[i] if i < len(fields_a) else empty
        fb = fields_b[i] if i < len(fields_b) else empty

        # Prefer non-empty field name/unit between the two objects
        name = fa.name or fb.name
        unit = fa.unit or fb.unit
        rows.append((name, unit, fa.value, fb.value))
    return rows


def _object_name(obj: IDFObject) -> str:
    """Return the name field (first field value) of an IDF object, or class name."""
    if obj.fields:
        return obj.fields[0].value or obj.class_name
    return obj.class_name


def _build_html(
    class_def: IDFClassDef,
    objects: List[IDFObject],
    idf_filename: str,
    idf_version: str,
    today: str,
) -> str:
    """Build full HTML document for one IDF class."""

    ver_str = f"v{idf_version}" if idf_version else "EnergyPlus"
    footer_left = _h(f"{idf_filename} ({ver_str})")
    footer_right = _h(today)

    header = f"""
<div class="page-header">
  <div>
    <h1>{_h(class_def.display_name)}</h1>
  </div>
  <div class="note">
    מבנה מגורים לפי ת"י 5282 חלק 1 (2024)
  </div>
</div>"""

    # Build 2-object blocks
    blocks_html = ""
    for i in range(0, len(objects), 2):
        obj_a = objects[i]
        obj_b = objects[i + 1] if i + 1 < len(objects) else None

        name_a = _object_name(obj_a)
        name_b = _object_name(obj_b) if obj_b else "-NA-"

        field_rows = _merged_field_rows(obj_a, obj_b, class_def.field_indices)

        # Table header row with object names
        col_a_cls = "obj-name"
        col_b_cls = "obj-name" if obj_b else "obj-name"

        block = f"""
<div class="block">
  <table>
    <thead>
      <tr>
        <th style="width:28%">Field</th>
        <th style="width:10%">Units</th>
        <th class="{col_a_cls}" style="width:31%">{_h(name_a)}</th>
        <th class="{col_b_cls}" style="width:31%">{_h(name_b)}</th>
      </tr>
    </thead>
    <tbody>"""

        for fname, funit, val_a, val_b in field_rows:
            val_b_html = (
                f'<td class="empty-col">-NA-</td>'
                if obj_b is None
                else f'<td class="value-col">{_h(val_b)}</td>'
            )
            block += (
                f"\n      <tr>"
                f'<td class="field-name">{_h(fname)}</td>'
                f'<td class="unit-col">{_h(funit)}</td>'
                f'<td class="value-col">{_h(val_a)}</td>'
                f"{val_b_html}"
                f"</tr>"
            )

        block += """
    </tbody>
  </table>
</div>"""
        blocks_html += block

    footer = f"""
<div class="footer">
  <span>{footer_left}</span>
  <span>{footer_right}</span>
</div>"""

    return (
        "<!DOCTYPE html><html><head>"
        "<meta charset='utf-8'>"
        f"<style>{_CSS}</style>"
        "</head><body>"
        f"<div class='page'>{header}{blocks_html}{footer}</div>"
        "</body></html>"
    )


# ── PDF conversion (same pattern as report_1045.py) ──────────────────────────

def _html_to_pdf(html_path: Path, pdf_path: Path) -> bool:
    """Convert HTML → PDF via WeasyPrint (primary) or Chrome headless."""
    try:
        import weasyprint  # type: ignore
        with open(html_path, encoding="utf-8") as f:
            html_str = f.read()
        weasyprint.HTML(string=html_str).write_pdf(str(pdf_path))
        return True
    except Exception:
        pass

    for chrome in (
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        "google-chrome",
        "chromium-browser",
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


# ── Public API ────────────────────────────────────────────────────────────────

def generate_idf_object_pdf(
    class_def: IDFClassDef,
    objects: List[IDFObject],
    output_dir: Path,
    idf_filename: str = "",
    idf_version: str = "",
) -> Optional[Path]:
    """Generate a single IDF-class PDF (Evergreen-parity format).

    Returns path to PDF if generated, else path to HTML fallback, else None.
    """
    if not objects:
        return None

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    today = date.today().strftime("%d-%m-%Y")
    html_str = _build_html(class_def, objects, idf_filename, idf_version, today)

    html_path = output_dir / f"{class_def.pdf_stem}.html"
    html_path.write_text(html_str, encoding="utf-8")

    pdf_path = output_dir / f"{class_def.pdf_stem}.pdf"
    if _html_to_pdf(html_path, pdf_path):
        html_path.unlink(missing_ok=True)  # clean up HTML after PDF created
        return pdf_path

    return html_path  # fallback: return HTML path


def generate_all_idf_object_reports(
    idf_objects: Dict[str, List[IDFObject]],
    output_dir: Path,
    idf_filename: str = "",
    idf_version: str = "",
) -> List[Path]:
    """Generate Evergreen-parity PDFs for all registered IDF classes present in *idf_objects*.

    Args:
        idf_objects: Dict from :func:`parse_idf_objects` keyed by class name.
        output_dir:  Directory to write PDFs into.
        idf_filename: Original IDF filename for footer.
        idf_version:  EnergyPlus version string for footer.

    Returns:
        List of generated file paths (PDF or HTML fallback).
    """
    from il_energy.report.idf_class_registry import REGISTRY

    output_dir = Path(output_dir)
    generated: List[Path] = []

    # Build case-insensitive lookup from parsed objects
    objects_lower: Dict[str, List[IDFObject]] = {
        k.lower(): v for k, v in idf_objects.items()
    }

    for class_def in REGISTRY:
        objects = objects_lower.get(class_def.idf_type.lower(), [])
        if not objects:
            continue
        result = generate_idf_object_pdf(
            class_def,
            objects,
            output_dir,
            idf_filename=idf_filename,
            idf_version=idf_version,
        )
        if result:
            generated.append(result)

    return generated
