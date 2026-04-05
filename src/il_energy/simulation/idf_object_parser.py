"""Generic IDF parser — extract all objects grouped by class, preserving field metadata.

Parses any EnergyPlus IDF file into a dict of {class_name: [IDFObject, ...]},
where each object carries its field values along with field names and units
extracted from inline ``!-`` comments.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional


@dataclass
class IDFField:
    """A single field within an IDF object."""
    value: str         # Raw field value (stripped)
    name: str = ""     # Field name from !- comment (e.g., "Thickness")
    unit: str = ""     # Unit from {unit} in comment (e.g., "m"), or ""


@dataclass
class IDFObject:
    """A parsed IDF object with its class name and fields."""
    class_name: str
    fields: List[IDFField] = field(default_factory=list)


def _parse_field_comment(comment: str) -> tuple:
    """Extract field name and unit from an IDF inline comment.

    Example: ``"!- Thickness {m}"`` → ``("Thickness", "m")``
    """
    if not comment:
        return ("", "")
    # Strip the leading "!-" or "!"
    comment = comment.strip()
    if comment.startswith("!-"):
        comment = comment[2:].strip()
    elif comment.startswith("!"):
        comment = comment[1:].strip()

    # Extract unit from {unit}
    unit = ""
    unit_match = re.search(r"\{([^}]+)\}", comment)
    if unit_match:
        unit = unit_match.group(1).strip()
        comment = comment[:unit_match.start()].strip()

    return (comment, unit)


def parse_idf_objects(idf_text: str) -> Dict[str, List[IDFObject]]:
    """Parse an IDF file into a dict of {class_name: [IDFObject, ...]}.

    Preserves field names and units from inline ``!-`` comments.
    Returns a dict keyed by class name (case-preserving).
    """
    result: Dict[str, List[IDFObject]] = {}

    # Split into lines, then reassemble into object blocks by tracking
    # comma/semicolon delimiters
    current_fields: List[IDFField] = []
    current_class: str = ""
    is_first_field = True

    for line in idf_text.splitlines():
        # Separate content from comment
        bang_pos = line.find("!")
        if bang_pos >= 0:
            content_part = line[:bang_pos]
            comment_part = line[bang_pos:]
        else:
            content_part = line
            comment_part = ""

        # Skip empty content lines (pure comments or blank lines)
        stripped = content_part.strip()
        if not stripped:
            continue

        # Process tokens separated by comma or semicolon
        # A line may contain the class name, a field value, or both
        # Split on comma and semicolon, keeping delimiters
        tokens = re.split(r"([,;])", stripped)

        for i, token in enumerate(tokens):
            token = token.strip()
            if token in (",", ";", ""):
                if token == ";":
                    # End of object — store it
                    if current_class:
                        result.setdefault(current_class, []).append(
                            IDFObject(class_name=current_class, fields=list(current_fields))
                        )
                    current_fields = []
                    current_class = ""
                    is_first_field = True
                continue

            if is_first_field:
                # First non-empty token is the class name
                current_class = token
                is_first_field = False
            else:
                # It's a field value — extract metadata from comment
                field_name, field_unit = _parse_field_comment(comment_part)
                current_fields.append(IDFField(
                    value=token,
                    name=field_name,
                    unit=field_unit,
                ))
                # Only use comment for the first field value on this line
                comment_part = ""

        # After processing the line, check if it ended with a delimiter
        # If the line had a semicolon, the object is already stored above

    return result


def extract_idf_version(idf_text: str) -> str:
    """Extract the EnergyPlus version string from IDF text.

    Returns e.g. ``"25.2"`` or ``""`` if not found.
    """
    match = re.search(r"Version\s*,\s*([0-9.]+)\s*;", idf_text, re.IGNORECASE)
    if match:
        return match.group(1).rstrip(".")
    return ""
