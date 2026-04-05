"""IDF file preparation — inject required output objects before simulation."""

from __future__ import annotations

import re
import tempfile
from pathlib import Path

from il_energy.exceptions import IDFError
from il_energy.simulation.idf_v89_converter import convert_v89_idf, convert_v9x_idf

# Objects to inject if missing
_OUTPUT_SQLITE = "\nOutput:SQLite,\n  SimpleAndTabular;\n"
_OUTPUT_SUMMARY = "\nOutput:Table:SummaryReports,\n  AllSummary;\n"
_OUTPUT_TABLE_STYLE = "\nOutputControl:Table:Style,\n  Comma;\n"
# EP variable names for zone-level ideal loads energy (J), written per zone name.
# Use SENSIBLE variants to exclude latent dehumidification — matches EP 9.x / EVERGREEN.
# These match Strategy 1 in sql_parser.parse_zone_energy (%Ideal Loads%Energy%).
_OUTPUT_IDEAL_LOADS_HEAT = (
    "\nOutput:Variable,*,Zone Ideal Loads Supply Air Sensible Heating Energy,Annual;\n"
)
_OUTPUT_IDEAL_LOADS_COOL = (
    "\nOutput:Variable,*,Zone Ideal Loads Supply Air Sensible Cooling Energy,Annual;\n"
)


def _has_object(content: str, object_type: str) -> bool:
    """Check if an IDF contains a specific object type (case-insensitive)."""
    pattern = rf"^\s*{re.escape(object_type)}\s*[,;]"
    return bool(re.search(pattern, content, re.MULTILINE | re.IGNORECASE))


def ensure_sql_output(idf_path: Path) -> Path:
    """Prepare an IDF for simulation by injecting required output objects.

    Returns path to a modified temp copy (or original if no changes needed).
    Never modifies the original file.
    """
    idf_path = Path(idf_path)
    if not idf_path.is_file():
        raise IDFError(f"IDF file not found: {idf_path}")

    original = idf_path.read_text(encoding="utf-8", errors="replace")
    content = original
    converted = False

    # Auto-convert older IDFs to EP 25.x format
    version_match = re.search(r"Version\s*,\s*(\d+)\.", content, re.IGNORECASE)
    if version_match:
        major = int(version_match.group(1))
        if major == 8:
            content = convert_v89_idf(content)
            converted = True
        elif major == 9:
            content = convert_v9x_idf(content)
            converted = True

    injections: list[str] = []

    if not _has_object(content, "Output:SQLite"):
        injections.append(_OUTPUT_SQLITE)

    if not _has_object(content, "Output:Table:SummaryReports"):
        injections.append(_OUTPUT_SUMMARY)

    if not _has_object(content, "OutputControl:Table:Style"):
        injections.append(_OUTPUT_TABLE_STYLE)

    if "Zone Ideal Loads Supply Air Sensible Heating Energy" not in content:
        injections.append(_OUTPUT_IDEAL_LOADS_HEAT)
    if "Zone Ideal Loads Supply Air Sensible Cooling Energy" not in content:
        injections.append(_OUTPUT_IDEAL_LOADS_COOL)

    if not injections and not converted:
        return idf_path

    modified = content + "\n" + "\n".join(injections)

    tmp = tempfile.NamedTemporaryFile(
        mode="w",
        suffix=".idf",
        prefix="il_energy_",
        delete=False,
        encoding="utf-8",
    )
    tmp.write(modified)
    tmp.close()
    return Path(tmp.name)
