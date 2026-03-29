"""Lightweight IDF parser for data not available in the EnergyPlus SQL output.

Currently extracts:
- WindowProperty:FrameAndDivider objects → frame conductance per name
"""

from __future__ import annotations

import re


# Default aluminum frame conductance (W/m²K) when not specified in IDF.
# Represents a standard non-thermally-broken aluminum frame per SI 5282.
_DEFAULT_FRAME_CONDUCTANCE = 5.8


def _strip_comments(idf_text: str) -> str:
    """Remove IDF inline comments (everything after '!' on each line)."""
    lines = []
    for line in idf_text.splitlines():
        bang = line.find("!")
        if bang >= 0:
            line = line[:bang]
        lines.append(line)
    return "\n".join(lines)


def _iter_idf_blocks(idf_text: str, object_type: str) -> list[list[str]]:
    """Yield field lists for every IDF object of the given type.

    Splits the IDF into comma/semicolon-delimited fields, groups by object
    boundary (semicolon ends an object).  Returns only blocks whose first
    field matches *object_type* (case-insensitive).
    """
    clean = _strip_comments(idf_text)

    # Split on commas and semicolons, keeping the delimiters to detect block ends
    tokens = re.split(r"([,;])", clean)

    current_fields: list[str] = []
    blocks: list[list[str]] = []

    for i in range(0, len(tokens) - 1, 2):
        field = tokens[i].strip()
        delim = tokens[i + 1] if i + 1 < len(tokens) else ""

        if field:
            current_fields.append(field)

        if delim == ";":
            if current_fields and current_fields[0].strip().lower() == object_type.lower():
                blocks.append(current_fields[:])
            current_fields = []

    return blocks


def parse_frame_conductances(idf_text: str) -> dict[str, float]:
    """Parse WindowProperty:FrameAndDivider blocks and return frame conductances.

    Returns:
        Dict mapping frame/divider name → frame conductance in W/m²K.
        Falls back to ``_DEFAULT_FRAME_CONDUCTANCE`` values are stored as the
        default — callers that look up a missing name should use the default.

    IDF field order for WindowProperty:FrameAndDivider (1-indexed, field 0 = object type):
        1  Name
        2  Frame Width {m}
        3  Frame Outside Projection {m}
        4  Frame Inside Projection {m}
        5  Frame Conductance {W/m2-K}   ← we want this
        ...
    """
    result: dict[str, float] = {}
    for fields in _iter_idf_blocks(idf_text, "WindowProperty:FrameAndDivider"):
        # fields[0] = object type; fields[1] = Name; fields[5] = Frame Conductance
        if len(fields) < 6:
            continue
        name = fields[1].strip()
        try:
            conductance = float(fields[5].strip())
        except (ValueError, IndexError):
            conductance = _DEFAULT_FRAME_CONDUCTANCE
        if name:
            result[name] = conductance
    return result


def get_frame_conductance(
    frame_conductances: dict[str, float],
    frame_name: str,
) -> float:
    """Return frame conductance for *frame_name*, falling back to default.

    Args:
        frame_conductances: Dict from :func:`parse_frame_conductances`.
        frame_name:         Frame/divider name from FenestrationSurface:Detailed.

    Returns:
        Conductance in W/m²K.
    """
    if not frame_name:
        return _DEFAULT_FRAME_CONDUCTANCE
    return frame_conductances.get(frame_name.strip(), _DEFAULT_FRAME_CONDUCTANCE)
