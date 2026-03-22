"""Generate SI 5282 Part 1 standardized reference unit (יחידת הייחוס) IDF.

Per Appendix ג of SI 5282 Part 1 (February 2023):
- Fixed geometry: 100 m² floor (10×10 m), 3.0 m floor-to-floor height
- One glazed wall: 8 m wide × 2.5 m tall (U=4.0, SHGC=0.63, LT=0.61)
- External shutter: closed 6:00–18:00 summer, open 6:00–18:00 winter
- Constructions per Table ג-1 by climate zone
- Internal loads per Table ג-2 (4 occupants, equipment, lighting schedules)
- HVAC: IdealLoads, cooling setpoint 24°C (Apr–Nov), heating 20°C (Dec–Mar), COP=3.0
- Infiltration: 1.0 ACH constant
- Run 4 times (N/E/S/W orientations), EPref = average HVAC thermal / COP / 100 m²

Zone naming (our project → SI 5282 Part 1 standard):
  Our A (Eilat)     → Standard Zone D
  Our B (Tel Aviv)  → Standard Zone A
  Our C (Jerusalem) → Standard Zone C
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional


# ── Reference R-values from Table ג-1 (material R, no film) ──────────────────
# fmt: off
_R_VALUES = {
    # (our zone) → { element: r_material [m²K/W] }
    "A": {"extwall": 0.89, "roof": 1.51, "open_floor": 1.04, "sep_floor": 0.79, "ground": 0.68, "inter": 0.17},
    "B": {"extwall": 0.63, "roof": 1.51, "open_floor": 0.67, "sep_floor": 0.67, "ground": 0.68, "inter": 0.17},
    "C": {"extwall": 0.80, "roof": 1.51, "open_floor": 1.04, "sep_floor": 0.79, "ground": 0.68, "inter": 0.17},
}
# fmt: on

# Cooling and heating months by zone (1-indexed months)
_COOLING_MONTHS = {
    "A": (4, 11),   # Apr–Nov  (Standard Zone D / hot-arid Eilat)
    "B": (4, 11),   # Apr–Nov  (Standard Zone A / Tel Aviv coastal)
    "C": (5, 10),   # May–Oct  (Standard Zone C / Jerusalem temperate)
}
_HEATING_MONTHS = {
    "A": (12, 3),
    "B": (12, 3),
    "C": (11, 4),
}


def _cooling_schedule(zone: str) -> str:
    """Return Schedule:Compact text: 1 during cooling months, 0 otherwise."""
    c1, c2 = _COOLING_MONTHS[zone]
    if c1 < c2:
        # e.g. Apr(4)–Nov(11)  →  Jan–Mar: 0, Apr–Nov: 1, Dec: 0
        h1_end = f"{c1 - 1}/31" if c1 > 1 else None
        h2_start = f"{c1}/1"
        h2_end = f"{c2}/30" if c2 in (4, 6, 9, 11) else (f"{c2}/31" if c2 != 2 else f"{c2}/28")
        lines = []
        if h1_end:
            lines.append(f"    Through: {h1_end},\n    For: AllDays,\n    Until: 24:00, 0,")
        lines.append(f"    Through: {h2_end},\n    For: AllDays,\n    Until: 24:00, 1,")
        lines.append("    Through: 12/31,\n    For: AllDays,\n    Until: 24:00, 0;")
        return "\n".join(lines)
    else:
        # wraps around year (e.g. Dec–Mar)
        h1_end = f"{c2}/31" if c2 not in (4, 6, 9, 11) else f"{c2}/30"
        h2_start = c1
        lines = [
            f"    Through: {h1_end},\n    For: AllDays,\n    Until: 24:00, 1,",
            f"    Through: {h2_start - 1}/30,\n    For: AllDays,\n    Until: 24:00, 0,",
            "    Through: 12/31,\n    For: AllDays,\n    Until: 24:00, 1;",
        ]
        return "\n".join(lines)


def _heating_schedule(zone: str) -> str:
    h1, h2 = _HEATING_MONTHS[zone]
    if h1 > h2:
        # wraps: Dec(12)–Mar(3)
        # → Jan–Mar: 1, Apr–Nov: 0, Dec: 1
        h2_last = f"3/31"  # Mar 31
        lines = [
            f"    Through: {h2_last},\n    For: AllDays,\n    Until: 24:00, 1,",
            "    Through: 11/30,\n    For: AllDays,\n    Until: 24:00, 0,",
            "    Through: 12/31,\n    For: AllDays,\n    Until: 24:00, 1;",
        ]
        return "\n".join(lines)
    else:
        # Nov(11)–Apr(4) for zone C
        h1_end = f"{h1}/30"
        h2_end = f"{h2}/30"
        lines = [
            f"    Through: {h2_end},\n    For: AllDays,\n    Until: 24:00, 1,",
            "    Through: 10/31,\n    For: AllDays,\n    Until: 24:00, 0,",
            f"    Through: {h1_end},\n    For: AllDays,\n    Until: 24:00, 1,",
            "    Through: 12/31,\n    For: AllDays,\n    Until: 24:00, 0;",
        ]
        return "\n".join(lines)


def generate_reference_box_idf(
    output_idf: Path,
    climate_zone: str = "B",
    north_axis_deg: float = 0.0,
    floor_type: str = "middle",
    epw_path: Optional[Path] = None,
) -> None:
    """Write a SI 5282 Appendix ג reference unit IDF to output_idf.

    Args:
        output_idf: Destination path for the generated IDF.
        climate_zone: Our zone label ("A"=Eilat, "B"=Tel Aviv, "C"=Jerusalem).
        north_axis_deg: Building North Axis in degrees (0=window S, 90=window W,
                        180=window N, 270=window E).
        floor_type: "middle" (adiabatic floor+ceiling), "top" (insulated roof),
                    "ground" (slab-on-grade floor), "open" (exposed floor).
        epw_path: Unused — weather file is passed at runtime via CLI.
    """
    if climate_zone not in _R_VALUES:
        raise ValueError(f"Unsupported zone '{climate_zone}'. Use A, B, or C.")

    r = _R_VALUES[climate_zone]

    # Determine roof and floor R-values based on floor type
    if floor_type == "top":
        r_ceiling = r["roof"]
        ceiling_bc = "Outdoors"
        ceiling_sun = "SunExposed"
        ceiling_wind = "WindExposed"
    else:
        r_ceiling = r["inter"]
        ceiling_bc = "Adiabatic"
        ceiling_sun = "NoSun"
        ceiling_wind = "NoWind"

    if floor_type == "ground":
        r_floor = r["ground"]
        floor_bc = "Ground"
        floor_sun = "NoSun"
        floor_wind = "NoWind"
    elif floor_type == "open":
        r_floor = r["open_floor"]
        floor_bc = "Outdoors"
        floor_sun = "SunExposed"
        floor_wind = "WindExposed"
    else:
        r_floor = r["inter"]
        floor_bc = "Adiabatic"
        floor_sun = "NoSun"
        floor_wind = "NoWind"

    # Separation floor (between units, contributes 0.5 factor in H)
    r_sep = r["sep_floor"]  # stored for reference but not used in standalone box

    cooling_sched = _cooling_schedule(climate_zone)
    heating_sched = _heating_schedule(climate_zone)

    # Outside boundary condition object (blank for Adiabatic/Outdoors/Ground)
    ceiling_obc_obj = "" if ceiling_bc in ("Adiabatic", "Outdoors", "Ground") else ""
    floor_obc_obj = "" if floor_bc in ("Adiabatic", "Outdoors", "Ground") else ""

    idf = f"""! SI 5282 Part 1 Reference Unit (יחידת הייחוס) — Appendix ג
! Climate Zone: {climate_zone} (Our naming: A=Eilat, B=Tel Aviv, C=Jerusalem)
! North Axis: {north_axis_deg}° (0=window S, 90=window W, 180=window N, 270=window E)
! Floor type: {floor_type}
! Auto-generated by il_energy reference/box_generator.py

  Version, 25.2;

  Building,
    SI5282_RefUnit,          !- Name
    {north_axis_deg:.1f},               !- North Axis {{deg}}
    Suburbs,                 !- Terrain
    ,                        !- Loads Convergence Tolerance Value
    ,                        !- Temperature Convergence Tolerance Value
    FullExterior,            !- Solar Distribution
    25,                      !- Maximum Number of Warmup Days
    6;                       !- Minimum Number of Warmup Days

  Timestep, 6;

  SurfaceConvectionAlgorithm:Inside, TARP;
  SurfaceConvectionAlgorithm:Outside, DOE-2;
  HeatBalanceAlgorithm, ConductionTransferFunction;

  ShadowCalculation,
    PolygonClipping,         !- Shading Calculation Method
    Periodic,                !- Shading Calculation Update Frequency Method
    20;                      !- Shading Calculation Update Frequency

  RunPeriod,
    FullYear,                !- Name
    1,                       !- Begin Month
    1,                       !- Begin Day of Month
    ,                        !- Begin Year
    12,                      !- End Month
    31,                      !- End Day of Month
    ,                        !- End Year
    Sunday,                  !- Day of Week for Start Day
    Yes,                     !- Use Weather File Holidays and Special Days
    No,                      !- Use Weather File Daylight Saving Period
    Yes,                     !- Apply Weekend Holiday Rule
    Yes,                     !- Use Weather File Rain Indicators
    Yes;                     !- Use Weather File Snow Indicators

  Site:GroundTemperature:BuildingSurface,
    18, 18, 18, 18, 18, 18, 18, 18, 18, 18, 18, 18;

! ── Schedule Type Limits ────────────────────────────────────────────────────────

  ScheduleTypeLimits,
    Fraction,                !- Name
    0.0,                     !- Lower Limit
    1.0,                     !- Upper Limit
    CONTINUOUS;

  ScheduleTypeLimits,
    AnyNumber;               !- Name

! ── External Shutter Schedule ──────────────────────────────────────────────────
! 1=shade deployed (closed), 0=shade retracted (open)
! Winter (Dec–Mar): closed 0–6, open 6–18, closed 18–24
! Summer (Apr–Nov): open 0–6, closed 6–18, open 18–24

  Schedule:Compact,
    ShutterSched,            !- Name
    Fraction,                !- Schedule Type Limits Name
    Through: 3/31,           !- Jan–Mar (winter)
    For: AllDays,
    Until: 06:00, 1.0,
    Until: 18:00, 0.0,
    Until: 24:00, 1.0,
    Through: 11/30,          !- Apr–Nov (summer)
    For: AllDays,
    Until: 06:00, 0.0,
    Until: 18:00, 1.0,
    Until: 24:00, 0.0,
    Through: 12/31,          !- Dec (winter)
    For: AllDays,
    Until: 06:00, 1.0,
    Until: 18:00, 0.0,
    Until: 24:00, 1.0;

! ── Occupancy Schedule ─────────────────────────────────────────────────────────
! 4 persons: 0–8 present (sleep), 8–16 absent, 16–24 present (light activity)

  Schedule:Compact,
    OccupSched,              !- Occupancy fraction (0 or 1)
    Fraction,
    Through: 12/31,
    For: AllDays,
    Until: 08:00, 1.0,
    Until: 16:00, 0.0,
    Until: 24:00, 1.0;

! Activity level: sleep=80 W/person (320W/4), activity=125 W/person (500W/4)
  Schedule:Compact,
    ActivitySched,           !- W/person
    AnyNumber,
    Through: 12/31,
    For: AllDays,
    Until: 08:00, 80.0,
    Until: 16:00, 80.0,
    Until: 24:00, 125.0;

! ── Equipment Schedules ─────────────────────────────────────────────────────────
! 0–16h: 1 W/m² = 100W total; 16–24h: 9 W/m² = 900W total
! Implemented as two ElectricEquipment objects each with its own schedule.

  Schedule:Compact,
    EquipSched_Low,          !- ON 0–16h only
    Fraction,
    Through: 12/31,
    For: AllDays,
    Until: 16:00, 1.0,
    Until: 24:00, 0.0;

  Schedule:Compact,
    EquipSched_High,         !- ON 16–24h only
    Fraction,
    Through: 12/31,
    For: AllDays,
    Until: 16:00, 0.0,
    Until: 24:00, 1.0;

! ── Lighting Schedule ───────────────────────────────────────────────────────────
! 200W, active 17–24h only

  Schedule:Compact,
    LightSched,
    Fraction,
    Through: 12/31,
    For: AllDays,
    Until: 17:00, 0.0,
    Until: 24:00, 1.0;

! ── HVAC Availability Schedules ────────────────────────────────────────────────

  Schedule:Compact,
    CoolAvailSched,          !- 1 during cooling months
    Fraction,
{cooling_sched}

  Schedule:Compact,
    HeatAvailSched,          !- 1 during heating months
    Fraction,
{heating_sched}

  Schedule:Compact,
    AlwaysOn,
    Fraction,
    Through: 12/31,
    For: AllDays,
    Until: 24:00, 1.0;

! Control type 4 = DualSetpointWithDeadband (required by ZoneControl:Thermostat)
  Schedule:Compact,
    DualSetpointCtrlSched,
    AnyNumber,
    Through: 12/31,
    For: AllDays,
    Until: 24:00, 4;

  GlobalGeometryRules,
    UpperLeftCorner,         !- Starting Vertex Position
    CounterClockWise,        !- Vertex Entry Direction
    Relative;                !- Coordinate System (relative to zone; Building North Axis rotates solar)

! ── Zone ────────────────────────────────────────────────────────────────────────

  Zone,
    RefZone,                 !- Name
    0,                       !- Direction of Relative North {{deg}}
    0,                       !- X Origin {{m}}
    0,                       !- Y Origin {{m}}
    0,                       !- Z Origin {{m}}
    1,                       !- Type
    1,                       !- Multiplier
    3.0,                     !- Ceiling Height {{m}}
    300.0;                   !- Volume {{m3}}

! ── Materials ───────────────────────────────────────────────────────────────────
! Using Material:NoMass — r values are material resistance (no film).
! EnergyPlus adds inside/outside film resistances automatically.

  Material:NoMass,
    MAT_ExtWall,             !- Name
    MediumRough,             !- Roughness
    {r['extwall']:.4f},              !- Thermal Resistance {{m2-K/W}}
    0.9,                     !- Thermal Absorptance
    0.7,                     !- Solar Absorptance (dark exterior per Table ג-1)
    0.7;                     !- Visible Absorptance

  Material:NoMass,
    MAT_Ceiling,             !- Name
    MediumRough,             !- Roughness
    {r_ceiling:.4f},              !- Thermal Resistance {{m2-K/W}}
    0.9,                     !- Thermal Absorptance
    0.45,                    !- Solar Absorptance (medium roof per Table ג-1)
    0.45;                    !- Visible Absorptance

  Material:NoMass,
    MAT_Floor,               !- Name
    Smooth,                  !- Roughness
    {r_floor:.4f},              !- Thermal Resistance {{m2-K/W}}
    0.9,                     !- Thermal Absorptance
    0.6,                     !- Solar Absorptance
    0.6;                     !- Visible Absorptance

! Internal mass (effective thermal mass of interior walls per Table ג-1)
! 120 m² of interior wall → input as 240 m² (both sides) per standard note
! Concrete block 10cm (900 kg/m³, k=0.34, c=1000) + plaster both sides (1.5cm)
  Material,
    MAT_IntMass,             !- Name
    MediumRough,             !- Roughness
    0.13,                    !- Thickness {{m}} (plaster+block+plaster = 0.015+0.10+0.015)
    0.4,                     !- Conductivity {{W/m-K}} (effective)
    950,                     !- Density {{kg/m3}}
    1000;                    !- Specific Heat {{J/kg-K}}

! ── Constructions ───────────────────────────────────────────────────────────────

  Construction,
    Const_ExtWall,           !- Name
    MAT_ExtWall;             !- Outside Layer

  Construction,
    Const_Ceiling,           !- Name
    MAT_Ceiling;             !- Outside Layer

  Construction,
    Const_Floor,             !- Name
    MAT_Floor;               !- Outside Layer

  Construction,
    Const_IntMass,           !- Name
    MAT_IntMass;             !- Outside Layer

! ── Glazing ─────────────────────────────────────────────────────────────────────
! Table ג-1: U=4.0 W/m²K, SHGC=0.63, LT=0.61

  WindowMaterial:SimpleGlazingSystem,
    Glazing_Ref,             !- Name
    4.0,                     !- U-Factor {{W/m2-K}}
    0.63,                    !- Solar Heat Gain Coefficient
    0.61;                    !- Visible Transmittance

  Construction,
    Const_Window,            !- Name
    Glazing_Ref;             !- Outside Layer

! External shutter material (per Table ג-1 note (א)):
!   Solar transmittance=0.15, Solar reflectance=0.6, IR emissivity=0.9,
!   IR transmittance=0.05, thickness=0.001m, conductivity=160 W/mK, dist=0.1m

  WindowMaterial:Shade,
    ShutterMat,              !- Name
    0.15,                    !- Solar Transmittance
    0.6,                     !- Solar Reflectance
    0.15,                    !- Visible Transmittance
    0.6,                     !- Visible Reflectance
    0.9,                     !- Infrared Hemispherical Emissivity
    0.05,                    !- Infrared Transmittance
    0.001,                   !- Thickness {{m}}
    160,                     !- Conductivity {{W/m-K}}
    0.1,                     !- Shade to Glass Distance {{m}}
    1.0,                     !- Top Opening Multiplier
    1.0,                     !- Bottom Opening Multiplier
    1.0,                     !- Left-Side Opening Multiplier
    1.0,                     !- Right-Side Opening Multiplier
    0.0;                     !- Airflow Permeability

! ── Geometry ────────────────────────────────────────────────────────────────────
! 10m × 10m × 3m box.
! Window on South wall (Y=0 face, azimuth 180°): 8m × 2.5m, sill at Z=0.25m.
! EnergyPlus vertex order: counterclockwise when viewed from outside.

! Vertex order: CounterClockWise when viewed from OUTSIDE (outward normal rule).
! Pattern from EP 1ZoneUncontrolled example: start at one corner at Z=H,
! go DOWN to Z=0, sweep along wall base, then go UP to Z=H.
! South wall (Y=0, normal -Y): viewed from south, right=+X → start (X=0,Z=H)
! East  wall (X=10, normal +X): viewed from east, right=+Y  → start (Y=0,Z=H)
! North wall (Y=10, normal +Y): viewed from north, right=-X → start (X=10,Z=H)
! West  wall (X=0,  normal -X): viewed from west, right=-Y  → start (Y=10,Z=H)

  BuildingSurface:Detailed,
    South_Wall,              !- Name
    Wall,                    !- Surface Type
    Const_ExtWall,           !- Construction Name
    RefZone,                 !- Zone Name
    ,                        !- Space Name
    Outdoors,                !- Outside Boundary Condition
    ,                        !- Outside Boundary Condition Object
    SunExposed,              !- Sun Exposure
    WindExposed,             !- Wind Exposure
    autocalculate,           !- View Factor to Ground
    4,                       !- Number of Vertices
    0, 0, 3,
    0, 0, 0,
    10, 0, 0,
    10, 0, 3;

  BuildingSurface:Detailed,
    East_Wall,               !- Name
    Wall, Const_ExtWall,
    RefZone, ,
    Outdoors, ,
    SunExposed, WindExposed,
    autocalculate, 4,
    10, 0, 3,
    10, 0, 0,
    10, 10, 0,
    10, 10, 3;

  BuildingSurface:Detailed,
    North_Wall,              !- Name
    Wall, Const_ExtWall,
    RefZone, ,
    Outdoors, ,
    SunExposed, WindExposed,
    autocalculate, 4,
    10, 10, 3,
    10, 10, 0,
    0, 10, 0,
    0, 10, 3;

  BuildingSurface:Detailed,
    West_Wall,               !- Name
    Wall, Const_ExtWall,
    RefZone, ,
    Outdoors, ,
    SunExposed, WindExposed,
    autocalculate, 4,
    0, 10, 3,
    0, 10, 0,
    0, 0, 0,
    0, 0, 3;

  BuildingSurface:Detailed,
    Ceiling,                 !- Name
    Ceiling, Const_Ceiling,
    RefZone, ,
    {ceiling_bc}, {ceiling_obc_obj},
    {ceiling_sun}, {ceiling_wind},
    autocalculate, 4,
    0, 0, 3,
    10, 0, 3,
    10, 10, 3,
    0, 10, 3;

  BuildingSurface:Detailed,
    Floor_Surf,              !- Name
    Floor, Const_Floor,
    RefZone, ,
    {floor_bc}, {floor_obc_obj},
    {floor_sun}, {floor_wind},
    autocalculate, 4,
    10, 0, 0,
    0, 0, 0,
    0, 10, 0,
    10, 10, 0;

! ── Window (South wall, 8m × 2.5m, centered) ────────────────────────────────────
! X: 1.0 to 9.0 (centered in 10m wall), Z: 0.25 to 2.75

  FenestrationSurface:Detailed,
    South_Window,            !- Name
    Window,                  !- Surface Type
    Const_Window,            !- Construction Name
    South_Wall,              !- Building Surface Name
    ,                        !- Outside Boundary Condition Object
    autocalculate,           !- View Factor to Ground
    ,                        !- Frame and Divider Name
    1,                       !- Multiplier
    4,                       !- Number of Vertices
    1.0, 0.0, 2.75,
    1.0, 0.0, 0.25,
    9.0, 0.0, 0.25,
    9.0, 0.0, 2.75;

! ── Window Shading Control (External Shutter) ────────────────────────────────────

  WindowShadingControl,
    ShutterCtrl,             !- Name
    RefZone,                 !- Zone Name
    1,                       !- Shading Control Sequence Number
    ExteriorShade,           !- Shading Type
    ,                        !- Construction with Shading Name (not used for material-based shade)
    OnIfScheduleAllows,      !- Shading Control Type
    ShutterSched,            !- Schedule Name
    0.0,                     !- Setpoint
    YES,                     !- Shading Control Is Scheduled
    NO,                      !- Glare Control Is Active
    ShutterMat,              !- Shading Device Material Name
    FixedSlatAngle,          !- Type of Slat Angle Control for Blinds
    ,                        !- Slat Angle Schedule Name
    ,                        !- Setpoint 2
    ,                        !- Daylighting Control Object Name
    Sequential,              !- Multiple Surface Control Type
    South_Window;            !- Fenestration Surface 1 Name

! ── Internal Mass (thermal mass of interior walls, 240 m² input per standard) ──

  InternalMass,
    IntMass,                 !- Name
    Const_IntMass,           !- Construction Name
    RefZone,                 !- Zone or ZoneList Name
    ,                        !- Space or SpaceList Name
    240.0;                   !- Surface Area {{m2}}

! ── Internal Loads ──────────────────────────────────────────────────────────────
! Per Table ג-2: 4 persons, equipment, 200W lighting (17–24h only)

  People,
    RefZone_People,          !- Name
    RefZone,                 !- Zone Name
    OccupSched,              !- Number of People Schedule Name
    People,                  !- Number of People Calculation Method
    4.0,                     !- Number of People
    ,                        !- People per Zone Floor Area (blank = use number above)
    ,                        !- Zone Floor Area per Person
    0.3,                     !- Fraction Radiant
    ,                        !- Sensible Heat Fraction (autocalculate)
    ActivitySched;           !- Activity Level Schedule Name

! Equipment: 1 W/m² × 100 m² = 100W during 0–16h (radiant fraction 0.20 per standard)
  ElectricEquipment,
    Equip_Low,               !- Name
    RefZone,                 !- Zone Name
    EquipSched_Low,          !- Schedule Name
    EquipmentLevel,          !- Design Level Calculation Method
    100.0,                   !- Design Level {{W}}
    ,                        !- W/m2
    ,                        !- W/person
    0.20,                    !- Fraction Latent
    0.20,                    !- Fraction Radiant (per standard note (ב))
    0.0;                     !- Fraction Lost

! Equipment: 9 W/m² × 100 m² = 900W during 16–24h
  ElectricEquipment,
    Equip_High,              !- Name
    RefZone,                 !- Zone Name
    EquipSched_High,         !- Schedule Name
    EquipmentLevel,          !- Design Level Calculation Method
    900.0,                   !- Design Level {{W}}
    ,
    ,
    0.20,                    !- Fraction Latent
    0.20,                    !- Fraction Radiant
    0.0;                     !- Fraction Lost

! Lighting: 200W, 17–24h (visible fraction 0.22, radiant fraction 0.28 per standard note (ג))
  Lights,
    RefZone_Lights,          !- Name
    RefZone,                 !- Zone Name
    LightSched,              !- Schedule Name
    LightingLevel,           !- Design Level Calculation Method
    200.0,                   !- Lighting Level {{W}}
    ,
    ,
    0.0,                     !- Fraction Return Air
    0.28,                    !- Fraction Radiant
    0.22,                    !- Fraction Visible
    0.0;                     !- Fraction Replaceable

! ── Infiltration ─────────────────────────────────────────────────────────────────
! 1.0 ACH constant (Table ג-1)

  ZoneInfiltration:DesignFlowRate,
    RefZone_Infiltration,    !- Name
    RefZone,                 !- Zone Name
    AlwaysOn,                !- Schedule Name
    AirChanges/Hour,         !- Design Flow Rate Calculation Method
    ,                        !- Design Flow Rate {{m3/s}}
    ,                        !- Flow per Zone Floor Area {{m3/s-m2}}
    ,                        !- Flow per Exterior Surface Area {{m3/s-m2}}
    1.0,                     !- Air Changes per Hour
    1.0, 0.0, 0.0, 0.0;     !- Coefficients (constant only)

! ── HVAC: Ideal Loads Air System ────────────────────────────────────────────────
! COP=3.0 modeled by converting thermal energy to electrical in post-processing.
! Setpoints: cooling=24°C, heating=20°C (Table ג-3)
! Limits: None (unlimited heating and cooling capacity per Table ג-4)

  ZoneHVAC:IdealLoadsAirSystem,
    RefZone_HVAC,            !- Name
    ,                        !- Availability Schedule Name (always available)
    RefZone_Supply_In,       !- Zone Supply Air Node Name
    RefZone_Exhaust_Out,     !- Zone Exhaust Air Node Name
    ,                        !- System Inlet Air Node Name
    50.0,                    !- Maximum Heating Supply Air Temperature {{C}}
    13.0,                    !- Minimum Cooling Supply Air Temperature {{C}}
    0.0156,                  !- Maximum Heating Supply Air Humidity Ratio
    0.0077,                  !- Minimum Cooling Supply Air Humidity Ratio
    NoLimit,                 !- Heating Limit
    ,                        !- Maximum Heating Air Flow Rate
    ,                        !- Maximum Sensible Heating Capacity
    NoLimit,                 !- Cooling Limit
    ,                        !- Maximum Cooling Air Flow Rate
    ,                        !- Maximum Total Cooling Capacity
    HeatAvailSched,          !- Heating Availability Schedule Name
    CoolAvailSched,          !- Cooling Availability Schedule Name
    None,                    !- Dehumidification Control Type
    ,                        !- Cooling Sensible Heat Ratio
    None,                    !- Humidification Control Type

    ,                        !- Design Specification Outdoor Air Object Name
    ,                        !- Outdoor Air Inlet Node Name
    ,                        !- Demand Controlled Ventilation Type
    ,                        !- Outdoor Air Economizer Type
    ,                        !- Heat Recovery Type
    ,                        !- Sensible Heat Recovery Effectiveness
    ;                        !- Latent Heat Recovery Effectiveness

  ZoneHVAC:EquipmentList,
    RefZone_EquipList,       !- Name
    SequentialLoad,          !- Load Distribution Scheme
    ZoneHVAC:IdealLoadsAirSystem, RefZone_HVAC,
    1, 1;                    !- Cooling/Heating Priorities

  ZoneHVAC:EquipmentConnections,
    RefZone,                 !- Zone Name
    RefZone_EquipList,       !- Zone Conditioning Equipment List Name
    RefZone_Supply_In,       !- Zone Air Inlet Node or NodeList Name
    RefZone_Exhaust_Out,     !- Zone Air Exhaust Node or NodeList Name
    RefZone_Air_Node,        !- Zone Air Node Name
    RefZone_Return_Air;      !- Zone Return Air Node or NodeList Name

! ── Setpoint Managers ────────────────────────────────────────────────────────────

  ThermostatSetpoint:DualSetpoint,
    RefZone_Thermostat,      !- Name
    HeatingSetpointSched,    !- Heating Setpoint Temperature Schedule Name
    CoolingSetpointSched;    !- Cooling Setpoint Temperature Schedule Name

  Schedule:Compact,
    HeatingSetpointSched,
    AnyNumber,
    Through: 12/31,
    For: AllDays,
    Until: 24:00, 20.0;

  Schedule:Compact,
    CoolingSetpointSched,
    AnyNumber,
    Through: 12/31,
    For: AllDays,
    Until: 24:00, 24.0;

  ZoneControl:Thermostat,
    RefZone_ThermostatCtrl,  !- Name
    RefZone,                 !- Zone Name
    DualSetpointCtrlSched,   !- Control Type Schedule Name
    ThermostatSetpoint:DualSetpoint,  !- Control 1 Object Type
    RefZone_Thermostat;      !- Control 1 Name

! ── Outputs ──────────────────────────────────────────────────────────────────────

  Output:SQLite,
    SimpleAndTabular;

  Output:Table:SummaryReports,
    AllSummary;

  OutputControl:Table:Style, Comma;

  Output:VariableDictionary, IDF;

"""
    output_idf = Path(output_idf)
    output_idf.parent.mkdir(parents=True, exist_ok=True)
    output_idf.write_text(idf, encoding="utf-8")
