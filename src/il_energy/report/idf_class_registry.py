"""Registry of IDF object classes to include in Evergreen-parity PDF reports.

Each entry maps an IDF class name to display metadata and the ordered list of
field indices to render (0-based, where field 0 is the class name itself, so
field 1 is the first real field).  A ``None`` field list means "show all".
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class IDFClassDef:
    """Metadata for one IDF object class to report."""
    idf_type: str            # Exact IDF class name (case-insensitive match)
    display_name: str        # Human-friendly name shown in PDF header
    pdf_stem: str            # Output filename stem (e.g. "Material")
    field_indices: Optional[List[int]] = None  # 1-based field indices to show; None = all


# ── Registry ─────────────────────────────────────────────────────────────────

REGISTRY: List[IDFClassDef] = [
    IDFClassDef(
        idf_type="Building",
        display_name="Building",
        pdf_stem="Building",
        field_indices=None,
    ),
    IDFClassDef(
        idf_type="BuildingSurface:Detailed",
        display_name="BuildingSurface-Detailed",
        pdf_stem="BuildingSurface-Detailed",
        field_indices=[1, 2, 3, 4, 5, 6, 7, 8, 9],
    ),
    IDFClassDef(
        idf_type="Construction",
        display_name="Construction",
        pdf_stem="Construction",
        field_indices=None,  # extensible — all layers shown
    ),
    IDFClassDef(
        idf_type="FenestrationSurface:Detailed",
        display_name="FenestrationSurface-Detailed",
        pdf_stem="FenestrationSurface-Detailed",
        field_indices=[1, 2, 3, 4, 5, 6, 7, 8, 9, 10],
    ),
    IDFClassDef(
        idf_type="HeatBalanceAlgorithm",
        display_name="HeatBalanceAlgorithm",
        pdf_stem="HeatBalanceAlgorithm",
        field_indices=None,
    ),
    IDFClassDef(
        idf_type="ZoneInfiltration:DesignFlowRate",
        display_name="Infiltration",
        pdf_stem="Infiltration",
        field_indices=[1, 2, 3, 4, 5, 6],
    ),
    IDFClassDef(
        idf_type="Lights",
        display_name="Lights",
        pdf_stem="Lights",
        field_indices=[1, 2, 3, 4, 5, 6],
    ),
    IDFClassDef(
        idf_type="Material",
        display_name="Material",
        pdf_stem="Material",
        field_indices=None,
    ),
    IDFClassDef(
        idf_type="Material:NoMass",
        display_name="Material-Resistance",
        pdf_stem="Material-Resistance",
        field_indices=None,
    ),
    IDFClassDef(
        idf_type="DesignSpecification:ZoneHVAC:Sizing",
        display_name="MechanicalVentilation",
        pdf_stem="MechanicalVentilation",
        field_indices=None,
    ),
    IDFClassDef(
        idf_type="ZoneVentilation:DesignFlowRate",
        display_name="NaturalVentilation",
        pdf_stem="NaturalVentilation",
        field_indices=[1, 2, 3, 4, 5, 6],
    ),
    IDFClassDef(
        idf_type="People",
        display_name="Occupancy",
        pdf_stem="Occupancy",
        field_indices=[1, 2, 3, 4, 5],
    ),
    IDFClassDef(
        idf_type="OtherEquipment",
        display_name="OtherEquipment",
        pdf_stem="OtherEquipment",
        field_indices=[1, 2, 3, 4, 5, 6],
    ),
    IDFClassDef(
        idf_type="RunPeriod",
        display_name="RunPeriod",
        pdf_stem="RunPeriod",
        field_indices=None,
    ),
    IDFClassDef(
        idf_type="Schedule:Compact",
        display_name="Schedule-Compact",
        pdf_stem="Schedule-Compact",
        field_indices=None,
    ),
    IDFClassDef(
        idf_type="Schedule:Day:Hourly",
        display_name="Schedule-Day-Hourly",
        pdf_stem="Schedule-Day-Hourly",
        field_indices=None,
    ),
    IDFClassDef(
        idf_type="Schedule:Day:Interval",
        display_name="Schedule-Day-Interval",
        pdf_stem="Schedule-Day-Interval",
        field_indices=None,
    ),
    IDFClassDef(
        idf_type="Schedule:Week:Daily",
        display_name="Schedule-Week-Daily",
        pdf_stem="Schedule-Week-Daily",
        field_indices=None,
    ),
    IDFClassDef(
        idf_type="Schedule:Year",
        display_name="Schedule-Year",
        pdf_stem="Schedule-Year",
        field_indices=None,
    ),
    IDFClassDef(
        idf_type="ShadowCalculation",
        display_name="ShadowCalculation",
        pdf_stem="ShadowCalculation",
        field_indices=None,
    ),
    IDFClassDef(
        idf_type="Site:GroundTemperature:BuildingSurface",
        display_name="Site-GroundTemperature-BuildingSurface",
        pdf_stem="Site-GroundTemperature-BuildingSurface",
        field_indices=None,
    ),
    IDFClassDef(
        idf_type="Site:Location",
        display_name="Site-Location",
        pdf_stem="Site-Location",
        field_indices=None,
    ),
    IDFClassDef(
        idf_type="SurfaceConvectionAlgorithm:Inside",
        display_name="SurfaceConvectionAlgorithm-Inside",
        pdf_stem="SurfaceConvectionAlgorithm-Inside",
        field_indices=None,
    ),
    IDFClassDef(
        idf_type="SurfaceConvectionAlgorithm:Outside",
        display_name="SurfaceConvectionAlgorithm-Outside",
        pdf_stem="SurfaceConvectionAlgorithm-Outside",
        field_indices=None,
    ),
    IDFClassDef(
        idf_type="Timestep",
        display_name="Timestep",
        pdf_stem="Timestep",
        field_indices=None,
    ),
    IDFClassDef(
        idf_type="WindowMaterial:Shade",
        display_name="WindowMaterial-Shade",
        pdf_stem="WindowMaterial-Shade",
        field_indices=None,
    ),
    IDFClassDef(
        idf_type="WindowMaterial:SimpleGlazingSystem",
        display_name="WindowMaterial-SimpleGlazingSystem",
        pdf_stem="WindowMaterial-SimpleGlazingSystem",
        field_indices=None,
    ),
    IDFClassDef(
        idf_type="WindowProperty:FrameAndDivider",
        display_name="WindowProperty-FrameAndDivider",
        pdf_stem="WindowProperty-FrameAndDivider",
        field_indices=None,
    ),
    IDFClassDef(
        idf_type="WindowShadingControl",
        display_name="WindowShadingControl",
        pdf_stem="WindowShadingControl",
        field_indices=None,
    ),
    IDFClassDef(
        idf_type="ZoneHVAC:EquipmentList",
        display_name="ZoneHVAC-EquipmentList",
        pdf_stem="ZoneHVAC-EquipmentList",
        field_indices=None,
    ),
    IDFClassDef(
        idf_type="ZoneHVAC:IdealLoadsAirSystem",
        display_name="ZoneHVAC-IdealLoadsAirSystem",
        pdf_stem="ZoneHVAC-IdealLoadsAirSystem",
        field_indices=None,
    ),
]

# Fast lookup by normalised IDF type
_BY_IDF_TYPE: dict[str, IDFClassDef] = {
    c.idf_type.lower(): c for c in REGISTRY
}


def get_class_def(idf_type: str) -> Optional[IDFClassDef]:
    """Return the IDFClassDef for *idf_type*, or None if not in registry."""
    return _BY_IDF_TYPE.get(idf_type.lower())
