"""Apply SI 5282 Part 1 reference operating conditions to a residential IDF.

EVERGREEN (the expert reference tool) pre-processes the proposed IDF before
rating simulation, replacing design schedules with SI 5282 standard reference
schedules and adding reference natural ventilation.  This module replicates
that pre-processing so our engine produces EPdes values comparable to the
standard.

Changes applied
---------------
1. Lighting schedule    : ``_Lighting``   → ``_EPrefResidentialGenLighting``
                          Radiant fraction: 0.72 → 0.28 ; Visible: 0.18 → 0.22
2. Computing equipment  : ``_Computer``   → ``_EPrefResidentialComputer``
                          Wattage: 10 W/m² → 9 W/m²
3. General equipment    : ``_Equipment``  → ``_EPrefResidentialEquipment``
                          Wattage: 3 W/m² → 1 W/m²
4. Shading schedule     : ``_Shading``    → ``_EPrefResidentialShading A-B``
5. Infiltration schedule: ``_Infiltration`` → ``_EPrefResidentialInfiltration``
6. Inject EPref Schedule:Compact definitions (idempotent — skipped if present)
7. Add ZoneVentilation:DesignFlowRate (2 ACH natural, seasonal schedule)
   for every zone that appears in Lights objects (residential zones only)
"""

from __future__ import annotations

import re
from pathlib import Path


# ---------------------------------------------------------------------------
# Schedule definitions (SI 5282 Part 1, Climate Zone B — Tel Aviv)
# ---------------------------------------------------------------------------

_SCHEDULES = """\

!-- SI 5282 Reference Schedules (injected by si5282_preprocessor) --

Schedule:Compact,
    _EPrefResidentialGenLighting, !- Name
    Fraction,                     !- Schedule Type Limits Name
    Through: 31 Dec,
    For: AllDays,
    Until: 17:00, 0,
    Until: 24:00, 1;

Schedule:Compact,
    _EPrefResidentialComputer,    !- Name
    Fraction,                     !- Schedule Type Limits Name
    Through: 31 Dec,
    For: AllDays,
    Until: 16:00, 0,
    Until: 24:00, 1;

Schedule:Compact,
    _EPrefResidentialEquipment,   !- Name
    Fraction,                     !- Schedule Type Limits Name
    Through: 31 Dec,
    For: AllDays,
    Until: 16:00, 1,
    Until: 24:00, 0;

Schedule:Compact,
    _EPrefResidentialNatVent A-B, !- Name
    Fraction,                     !- Schedule Type Limits Name
    Through: 31 Mar,
    For: AllDays,
    Until: 24:00, 0,
    Through: 30 Nov,
    For: AllDays,
    Until: 07:00, 1,
    Until: 20:00, 0,
    Until: 24:00, 1,
    Through: 31 Dec,
    For: AllDays,
    Until: 24:00, 0;

Schedule:Compact,
    _EPrefResidentialShading A-B, !- Name
    Fraction,                     !- Schedule Type Limits Name
    Through: 31 Mar,
    For: AllDays,
    Until: 06:00, 1,
    Until: 18:00, 0,
    Until: 24:00, 1,
    Through: 30 Nov,
    For: AllDays,
    Until: 06:00, 0,
    Until: 18:00, 1,
    Until: 24:00, 0,
    Through: 31 Dec,
    For: AllDays,
    Until: 06:00, 1,
    Until: 18:00, 0,
    Until: 24:00, 1;

Schedule:Compact,
    _EPrefResidentialInfiltration, !- Name
    Fraction,                      !- Schedule Type Limits Name
    Through: 31 Dec,
    For: AllDays,
    Until: 24:00, 1;

"""

# Marker to detect already-processed IDF
_MARKER = '_EPrefResidentialGenLighting'


def _build_nat_vent_block(zone_name: str) -> str:
    """Return a ZoneVentilation:DesignFlowRate object for one zone."""
    return (
        f"ZoneVentilation:DesignFlowRate,\n"
        f"    {zone_name} EPref Nat Vent,        !- Name\n"
        f"    {zone_name},                        !- Zone or ZoneList Name\n"
        f"    _EPrefResidentialNatVent A-B,       !- Schedule Name\n"
        f"    AirChanges/Hour,                    !- Design Flow Rate Calculation Method\n"
        f"    ,                                   !- Design Flow Rate {{m3/s}}\n"
        f"    ,                                   !- Flow Rate per Zone Floor Area {{m3/s-m2}}\n"
        f"    ,                                   !- Flow Rate per Person {{m3/s-person}}\n"
        f"    2,                                  !- Air Changes per Hour {{1/hr}}\n"
        f"    Natural,                            !- Ventilation Type\n"
        f"    ,                                   !- Fan Pressure Rise\n"
        f"    ,                                   !- Fan Total Efficiency\n"
        f"    1,                                  !- Constant Term Coefficient\n"
        f"    0,                                  !- Temperature Term Coefficient\n"
        f"    0,                                  !- Velocity Term Coefficient\n"
        f"    0,                                  !- Velocity Squared Term Coefficient\n"
        f"    0,                                  !- Minimum Indoor Temperature {{C}}\n"
        f"    ,                                   !- Minimum Indoor Temperature Schedule Name\n"
        f"    21,                                 !- Maximum Indoor Temperature {{C}}\n"
        f"    ,                                   !- Maximum Indoor Temperature Schedule Name\n"
        f"    16,                                 !- Delta Temperature {{deltaC}}\n"
        f"    ,                                   !- Delta Temperature Schedule Name\n"
        f"    23,                                 !- Minimum Outdoor Temperature {{C}}\n"
        f"    ,                                   !- Minimum Outdoor Temperature Schedule Name\n"
        f"    40,                                 !- Maximum Outdoor Temperature {{C}}\n"
        f"    ,                                   !- Maximum Outdoor Temperature Schedule Name\n"
        f"    40;                                 !- Maximum Wind Speed {{m/s}}\n\n"
    )


def _extract_zone_names_from_lights(idf: str) -> list[str]:
    """Return unique zone names from Lights objects (residential zones only)."""
    zones: list[str] = []
    seen: set[str] = set()
    # IDF may indent keyword with spaces, e.g. "   Lights, Name, ..."
    for m in re.finditer(r'(?i)^\s*Lights\s*,([^;]*);', idf, re.MULTILINE | re.DOTALL):
        block = m.group(1)
        # Collect all comma-separated non-comment field values
        fields = []
        for line in block.split('\n'):
            # Strip inline comments
            value = line.split('!')[0].strip().rstrip(',').strip()
            if value:
                fields.append(value)
        # fields[0] = Name (first field after "Lights,")
        # fields[1] = Zone Name
        if len(fields) >= 2:
            zone = fields[1]
            if zone and zone not in seen:
                seen.add(zone)
                zones.append(zone)
    return zones


# ---------------------------------------------------------------------------
# Object-level patchers
# ---------------------------------------------------------------------------

def _patch_lights_block(m: re.Match) -> str:
    block = m.group(0)
    # Schedule name: "_Lighting," → "_EPrefResidentialGenLighting,"
    block = re.sub(
        r'(?m)^(\s*)(_Lighting)(\s*,)',
        r'\g<1>_EPrefResidentialGenLighting\g<3>',
        block,
    )
    # Radiant fraction: .72 → 0.28
    block = re.sub(
        r'(?m)^(\s*)\.?72(\s*,\s*!-[^\n]*[Rr]adiant)',
        r'\g<1>0.28\g<2>',
        block,
    )
    # Visible fraction: .18 → 0.22
    block = re.sub(
        r'(?m)^(\s*)\.?18(\s*,\s*!-[^\n]*[Vv]isible)',
        r'\g<1>0.22\g<2>',
        block,
    )
    return block


def _patch_computing(m: re.Match) -> str:
    block = m.group(0)
    if 'Computing gain' not in block and 'computing gain' not in block.lower():
        return block
    block = re.sub(
        r'(?m)^(\s*)(_Computer)(\s*,)',
        r'\g<1>_EPrefResidentialComputer\g<3>',
        block,
    )
    # Wattage: 10 → 9
    block = re.sub(
        r'(?m)^(\s*)10(\s*,\s*!-[^\n]*[Ww]atts per Zone)',
        r'\g<1>9\g<2>',
        block,
    )
    return block


def _patch_equipment(m: re.Match) -> str:
    block = m.group(0)
    if 'Equipment gain' not in block and 'equipment gain' not in block.lower():
        return block
    block = re.sub(
        r'(?m)^(\s*)(_Equipment)(\s*,)',
        r'\g<1>_EPrefResidentialEquipment\g<3>',
        block,
    )
    # Wattage: 3 → 1
    block = re.sub(
        r'(?m)^(\s*)3(\s*,\s*!-[^\n]*[Ww]atts per Zone)',
        r'\g<1>1\g<2>',
        block,
    )
    return block


def _patch_shading_ctrl(m: re.Match) -> str:
    block = m.group(0)
    block = re.sub(
        r'(?m)^(\s*)(_Shading)(\s*,)',
        r'\g<1>_EPrefResidentialShading A-B\g<3>',
        block,
    )
    return block


def _patch_infiltration(m: re.Match) -> str:
    block = m.group(0)
    block = re.sub(
        r'(?m)^(\s*)(_Infiltration)(\s*,)',
        r'\g<1>_EPrefResidentialInfiltration\g<3>',
        block,
    )
    return block




# IDF keyword pattern: keyword may be indented with spaces
_OBJ_FLAGS = re.DOTALL  # [^;]* already handles newlines; MULTILINE not needed here


def apply_si5282_reference_conditions(idf_content: str) -> str:
    """Return a modified IDF with SI 5282 Part 1 reference conditions applied.

    Safe to call multiple times (idempotent — already-replaced schedules are
    detected and skipped).
    """
    if _MARKER in idf_content:
        return idf_content  # already processed

    modified = idf_content

    # 1. Inject schedule definitions
    modified = modified + _SCHEDULES

    # 2. Lights
    modified = re.sub(
        r'(?im)^\s*Lights\s*,[^;]*;',
        _patch_lights_block,
        modified,
        flags=_OBJ_FLAGS,
    )

    # 3. OtherEquipment — Computing gain
    modified = re.sub(
        r'(?im)^\s*OtherEquipment\s*,[^;]*;',
        _patch_computing,
        modified,
        flags=_OBJ_FLAGS,
    )

    # 4. OtherEquipment — Equipment gain
    modified = re.sub(
        r'(?im)^\s*OtherEquipment\s*,[^;]*;',
        _patch_equipment,
        modified,
        flags=_OBJ_FLAGS,
    )

    # 5. WindowShadingControl
    modified = re.sub(
        r'(?im)^\s*WindowShadingControl\s*,[^;]*;',
        _patch_shading_ctrl,
        modified,
        flags=_OBJ_FLAGS,
    )

    # 6. ZoneInfiltration:DesignFlowRate
    modified = re.sub(
        r'(?im)^\s*ZoneInfiltration:DesignFlowRate\s*,[^;]*;',
        _patch_infiltration,
        modified,
        flags=_OBJ_FLAGS,
    )

    # 7. Natural ventilation for all residential zones
    zones = _extract_zone_names_from_lights(idf_content)
    nat_vent_blocks = ''.join(_build_nat_vent_block(z) for z in zones)
    modified = modified + "\n!-- SI 5282 Natural Ventilation (EPref) --\n\n" + nat_vent_blocks

    return modified
