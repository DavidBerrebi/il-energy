"""Convert DesignBuilder EP 8.9 IDF to EP 25.x compatible format.

Key changes handled:
1. BuildingSurface:Detailed: insert blank "Space Name" field after Zone Name.
2. FenestrationSurface:Detailed: remove inline "Shading Control Name" field.
3. WindowProperty:ShadingControl → WindowShadingControl (zone-based, lists windows).
4. InternalMass: insert blank "Space or SpaceList Name" between Zone and Surface Area.
5. RunPeriod: insert blank Begin/End Year; fix day_of_week (UseWeatherFile→Sunday);
   remove obsolete "Number of years" field.
6. ShadowCalculation: rename method values; insert new Update Frequency Method field.
7. People: ZoneAveraged → EnclosureAveraged (MRT calculation type).
8. Version: update to 25.2.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple


def _comment_field(block: str, comment: str) -> str:
    """Extract value from a line whose comment matches `comment` (case-insensitive)."""
    m = re.search(
        r"^\s*([^,\n!]*),?\s*!-\s*" + re.escape(comment),
        block, re.IGNORECASE | re.MULTILINE
    )
    return m.group(1).strip().rstrip(",").strip() if m else ""


def convert_v89_idf(text: str) -> str:
    """Convert EP 8.9 IDF text to EP 25.x compatible format."""

    # ── Step 1: Parse WindowProperty:ShadingControl objects ──────────────────
    # Use comment-based extraction to handle blank fields correctly.
    shading_controls: Dict[str, dict] = {}
    wpc_pattern = re.compile(
        r"(WindowProperty:ShadingControl\s*,\s*\w+\s*,.*?;)",
        re.DOTALL | re.IGNORECASE,
    )
    for m in wpc_pattern.finditer(text):
        block = m.group(1)
        # Extract name: first field after keyword
        name_m = re.search(
            r"WindowProperty:ShadingControl\s*,\s*(\w+)\s*,",
            block, re.IGNORECASE
        )
        if not name_m:
            continue
        ctrl_name = name_m.group(1).strip()

        shading_controls[ctrl_name] = {
            "shading_type":  _comment_field(block, "Shading type"),
            "construction":  _comment_field(block, "Name of glazed construction with shading"),
            "control_type":  _comment_field(block, "Shading control type"),
            "schedule":      _comment_field(block, "Schedule name"),
            "setpoint":      _comment_field(block, "Setpoint"),
            "is_scheduled":  _comment_field(block, "Shading control is scheduled"),
            "glare_control": _comment_field(block, "Glare control is active"),
            "material_name": _comment_field(block, "Material name of shading device"),
            "slat_control":  _comment_field(block, "Type of slat angle control"),
            "slat_schedule": _comment_field(block, "Slat angle schedule name"),
            "setpoint2":     _comment_field(block, "Setpoint 2"),
        }

    # ── Step 2: Parse BuildingSurface:Detailed to map surface → zone ─────────
    # DesignBuilder puts the Name on a separate line with "!- Surface name".
    surface_zone: Dict[str, str] = {}
    bsd_block_scan = re.compile(
        r"BuildingSurface:Detailed\s*,.*?;",
        re.DOTALL | re.IGNORECASE,
    )
    for m in bsd_block_scan.finditer(text):
        block = m.group(0)
        surf_name = _comment_field(block, "Surface name")
        zone_name = _comment_field(block, "Zone Name")
        if surf_name and zone_name:
            surface_zone[surf_name.upper()] = zone_name

    # ── Step 3: Parse FenestrationSurface:Detailed ───────────────────────────
    # Comment-based detection of shading control and base surface.
    window_control: Dict[str, Tuple[str, str]] = {}
    fen_block_pat = re.compile(
        r"(FenestrationSurface:Detailed\s*,.*?;)",
        re.DOTALL | re.IGNORECASE,
    )

    for m in fen_block_pat.finditer(text):
        block = m.group(1)
        # Name is on the SAME line as the keyword
        name_m = re.search(
            r"FenestrationSurface:Detailed\s*,\s*([^,\n!]+)",
            block, re.IGNORECASE
        )
        if not name_m:
            continue
        win_name = name_m.group(1).strip()
        base_surf = _comment_field(block, "Base surface")
        shade_ctrl = _comment_field(block, "Window shading control")
        if shade_ctrl:
            window_control[win_name] = (base_surf, shade_ctrl)

    # ── Step 4: Build window → zone mapping ──────────────────────────────────
    window_zone: Dict[str, str] = {}
    for win_name, (base_surf, _) in window_control.items():
        window_zone[win_name] = surface_zone.get(base_surf.upper(), "")

    # ── Step 5: Group windows by (zone, control) ─────────────────────────────
    from collections import defaultdict
    zone_ctrl_windows: Dict[Tuple[str, str], List[str]] = defaultdict(list)
    for win_name, (_, ctrl) in window_control.items():
        zone = window_zone.get(win_name, "")
        if zone and ctrl:
            zone_ctrl_windows[(zone, ctrl)].append(win_name)

    # ── Step 6: Fix BuildingSurface:Detailed — insert blank Space Name ────────
    bsd_block_pat = re.compile(
        r"(BuildingSurface:Detailed\s*,.*?;)",
        re.DOTALL | re.IGNORECASE,
    )

    def _add_space_name(m: re.Match) -> str:
        block = m.group(1)
        return re.sub(
            r"(,\s*!-\s*Zone Name\b[^\n]*\n)",
            r"\1      ,                                           !- Space Name\n",
            block,
        )

    text = bsd_block_pat.sub(_add_space_name, text)

    # ── Step 6b: Fix InternalMass — insert blank Space or SpaceList Name ──────
    # EP 25.2 InternalMass: Name, Construction, Zone, *SpaceList*, SurfaceArea
    im_block_pat = re.compile(
        r"(InternalMass\s*,.*?;)",
        re.DOTALL | re.IGNORECASE,
    )

    def _fix_internal_mass(m: re.Match) -> str:
        block = m.group(1)
        # Insert blank "Space or SpaceList Name" after the zone name field.
        # DesignBuilder marks it "!- Name of Associated Thermal Zone"
        fixed = re.sub(
            r"(,\s*!-\s*Name of Associated Thermal Zone\b[^\n]*\n)",
            r"\1      ,                                           !- Space or SpaceList Name\n",
            block,
            flags=re.IGNORECASE,
        )
        return fixed

    text = im_block_pat.sub(_fix_internal_mass, text)

    # ── Step 7: Remove WindowProperty:ShadingControl objects ──────────────────
    text = wpc_pattern.sub("", text)

    # ── Step 8: Fix FenestrationSurface:Detailed — remove shading ctrl field ──
    def _fix_fen_block(m: re.Match) -> str:
        block = m.group(1)
        return re.sub(
            r"(?m)^\s*[^,\n!]+,\s*!-\s*Window shading control\b[^\n]*\n?",
            "",
            block,
            flags=re.IGNORECASE,
        )

    text = fen_block_pat.sub(_fix_fen_block, text)

    # ── Step 9: Build WindowShadingControl objects ────────────────────────────
    wsc_lines: List[str] = [
        "",
        "! ── WindowShadingControl objects (converted from WindowProperty:ShadingControl) ──",
        "",
    ]
    seq_by_zone: Dict[str, int] = {}
    for (zone, ctrl), windows in sorted(zone_ctrl_windows.items()):
        if ctrl not in shading_controls:
            continue
        sc = shading_controls[ctrl]
        seq = seq_by_zone.get(zone, 0) + 1
        seq_by_zone[zone] = seq
        ctrl_obj_name = f"ShadeCtrl_{zone.replace(':', '_').replace(' ', '_')}_{ctrl}"
        setpoint_val = sc["setpoint"] if sc["setpoint"] else "0"
        is_sched = "YES" if sc["is_scheduled"].upper() in ("YES", "1", "TRUE") else "NO"
        glare = "YES" if sc["glare_control"].upper() in ("YES", "1", "TRUE") else "NO"
        wsc_lines += [
            f"  WindowShadingControl,",
            f"    {ctrl_obj_name},           !- Name",
            f"    {zone},                    !- Zone Name",
            f"    {seq},                     !- Shading Control Sequence Number",
            f"    {sc['shading_type']},      !- Shading Type",
            f"    {sc['construction']},      !- Construction with Shading Name",
            f"    {sc['control_type']},      !- Shading Control Type",
            f"    {sc['schedule']},          !- Schedule Name",
            f"    {setpoint_val},            !- Setpoint",
            f"    {is_sched},               !- Shading Control Is Scheduled",
            f"    {glare},                  !- Glare Control Is Active",
            f"    {sc['material_name']},    !- Shading Device Material Name",
            f"    {sc['slat_control'] or 'FixedSlatAngle'},  !- Type of Slat Angle Control",
            f"    {sc['slat_schedule']},    !- Slat Angle Schedule Name",
            f"    {sc['setpoint2'] or '0'}, !- Setpoint 2",
            f"    ,                          !- Daylighting Control Object Name",
            f"    Sequential,               !- Multiple Surface Control Type",
        ]
        for win in windows:
            wsc_lines.append(f"    {win},")
        if wsc_lines[-1].endswith(","):
            wsc_lines[-1] = wsc_lines[-1][:-1] + ";"
        wsc_lines.append("")

    inject_marker = "  Output:"
    if inject_marker in text:
        wsc_text = "\n".join(wsc_lines)
        idx = text.index(inject_marker)
        text = text[:idx] + wsc_text + "\n" + text[idx:]
    else:
        text += "\n".join(wsc_lines)

    # ── Step 10: Fix RunPeriod ─────────────────────────────────────────────────
    # Changes: insert blank Begin/End Year; UseWeatherFile→Sunday; remove Number of Years.
    def _fix_runperiod(m: re.Match) -> str:
        block = m.group(1)

        # Insert blank Begin Year after begin day line
        block = re.sub(
            r"(,\s*!-\s*Start Month\s*,\s*Day\b[^\n]*\n)",
            r"\1      ,                                           !- Begin Year\n",
            block, flags=re.IGNORECASE,
        )
        # Insert blank End Year after end day line
        block = re.sub(
            r"(,\s*!-\s*End Month\s*,\s*Day\b[^\n]*\n)",
            r"\1      ,                                           !- End Year\n",
            block, flags=re.IGNORECASE,
        )

        # Change UseWeatherFile → Sunday (not valid in EP 25.2)
        block = re.sub(r"\bUseWeatherFile\b", "Sunday", block, flags=re.IGNORECASE)

        # Remove the "Number of years in simulation" / "Treat Weather as Actual" line.
        # The Number of years line ends the object with ";".
        # Replace trailing ",  !- snow indicators\n   1;" with ";  !- snow indicators"
        block = re.sub(
            r"(,)(\s*!-\s*use weather file snow indicators[^\n]*\n)\s*\d+\s*;[^\n]*",
            r";\2",
            block,
            flags=re.IGNORECASE,
        )
        return block

    rp_pat = re.compile(r"(RunPeriod\s*,.*?;)", re.DOTALL | re.IGNORECASE)
    text = rp_pat.sub(_fix_runperiod, text)

    # ── Step 11: Fix ShadowCalculation ────────────────────────────────────────
    # EP 8.9: ShadowCalculation, AverageOverDaysInFrequency, 20, 15000, SutherlandHodgman, SimpleSkyDiffuse;
    # EP 25.2: ShadowCalculation, PolygonClipping, Periodic, 20, 15000;
    #   - Field 1 renamed → "PolygonClipping"
    #   - New field 2 inserted → "Periodic"
    #   - Fields 5+ (PolygonClipping Algorithm, PixelCounting Resolution, SkyDiffuse)
    #     removed; EP 25.2 uses defaults and a new pixel_counting_resolution int
    #     field was inserted between the algo fields, making the old 5-field form invalid.
    sc_pat = re.compile(r"(ShadowCalculation\s*,.*?;)", re.DOTALL | re.IGNORECASE)

    def _fix_shadow_calc(m: re.Match) -> str:
        block = m.group(1)
        # Extract the frequency integer and max figures from the original block
        # Original fields: method, frequency_int, max_figures, algo, sky_diffuse
        # After our previous regex inserted "Periodic", fields are:
        #   PolygonClipping, Periodic, frequency_int, max_figures, algo, sky_diffuse
        # Just rewrite the whole object cleanly.
        # Extract integers from the block (frequency and max figures)
        nums = re.findall(r"(?<![.\w])\d+(?![.\w])", block)
        freq = nums[0] if nums else "20"
        max_fig = nums[1] if len(nums) > 1 else "15000"
        return (
            f"  ShadowCalculation,\n"
            f"    PolygonClipping,              !- Shading Calculation Method\n"
            f"    Periodic,                     !- Shading Calculation Update Frequency Method\n"
            f"    {freq},                       !- Shading Calculation Update Frequency\n"
            f"    {max_fig};                    !- Maximum Figures in Shadow Overlap Calculations\n"
        )

    text = sc_pat.sub(_fix_shadow_calc, text)

    # ── Step 12: Fix People — ZoneAveraged → EnclosureAveraged ───────────────
    text = re.sub(r"\bZoneAveraged\b", "EnclosureAveraged", text, flags=re.IGNORECASE)

    # ── Step 13: Fix version string ────────────────────────────────────────────
    text = re.sub(r"Version,\s*[\d.]+\s*;", "Version, 25.2;", text)

    return text


def convert_idf_file(src: Path, dst: Path) -> None:
    """Read src, convert, write to dst."""
    text = src.read_text(encoding="utf-8", errors="replace")
    converted = convert_v89_idf(text)
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text(converted, encoding="utf-8")
    print(f"Converted: {src.name} → {dst.name}")


if __name__ == "__main__":
    import sys
    src = Path(sys.argv[1])
    dst = Path(sys.argv[2]) if len(sys.argv) > 2 else src.with_suffix(".conv.idf")
    convert_idf_file(src, dst)
