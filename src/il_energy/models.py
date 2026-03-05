"""Pydantic data models for the il-energy pipeline."""

from pathlib import Path
from typing import List, Optional

from pydantic import BaseModel, Field


# --- Simulation Request/Result ---


class SimulationRequest(BaseModel):
    """Input parameters for an EnergyPlus simulation."""

    idf_path: Path
    epw_path: Path
    output_dir: Path


class SimulationResult(BaseModel):
    """Raw result from an EnergyPlus run."""

    success: bool
    return_code: int
    output_dir: Path
    sql_path: Optional[Path] = None
    stdout: str = ""
    stderr: str = ""


# --- Building Area ---


class BuildingArea(BaseModel):
    """Building area breakdown from EP output."""

    total_m2: float = 0.0
    conditioned_m2: float = 0.0
    unconditioned_m2: float = 0.0


# --- Energy End Uses ---


class EnergyEndUse(BaseModel):
    """Annual energy consumption by end-use category (kWh)."""

    heating_kwh: float = 0.0
    cooling_kwh: float = 0.0
    interior_lighting_kwh: float = 0.0
    exterior_lighting_kwh: float = 0.0
    interior_equipment_kwh: float = 0.0
    fans_kwh: float = 0.0
    pumps_kwh: float = 0.0
    heat_rejection_kwh: float = 0.0
    water_systems_kwh: float = 0.0
    total_kwh: float = 0.0


# --- Envelope ---


class EnvelopeSurface(BaseModel):
    """Opaque exterior surface from the Envelope Summary."""

    name: str
    construction: str = ""
    zone: str = ""
    u_factor_w_m2k: Optional[float] = None
    gross_area_m2: Optional[float] = None
    azimuth_deg: Optional[float] = None
    tilt_deg: Optional[float] = None


class WindowSurface(BaseModel):
    """Exterior fenestration surface from the Envelope Summary."""

    name: str
    construction: str = ""
    zone: str = ""
    glass_area_m2: Optional[float] = None
    frame_area_m2: Optional[float] = None
    u_factor_w_m2k: Optional[float] = None
    shgc: Optional[float] = None
    visible_transmittance: Optional[float] = None
    azimuth_deg: Optional[float] = None
    parent_surface: str = ""


# --- Zone-Level Energy ---


class ZoneEnergy(BaseModel):
    """Annual energy for a single thermal zone."""

    zone_name: str
    floor_area_m2: float = 0.0
    heating_kwh: float = 0.0
    cooling_kwh: float = 0.0
    lighting_kwh: float = 0.0
    equipment_kwh: float = 0.0
    total_kwh: float = 0.0


# --- Flat / Unit Aggregation ---


class FlatEnergy(BaseModel):
    """Aggregated energy for a residential flat (group of zones)."""

    flat_id: str
    zones: List[str] = Field(default_factory=list)
    floor_area_m2: float = 0.0
    heating_kwh: float = 0.0
    cooling_kwh: float = 0.0
    total_kwh: float = 0.0
    heating_kwh_per_m2: float = 0.0
    cooling_kwh_per_m2: float = 0.0
    total_kwh_per_m2: float = 0.0


# --- Normalized Metrics ---


class NormalizedMetrics(BaseModel):
    """Energy Use Intensity (EUI) metrics normalized per m²."""

    total_eui_kwh_m2: float = 0.0
    heating_eui_kwh_m2: float = 0.0
    cooling_eui_kwh_m2: float = 0.0
    lighting_eui_kwh_m2: float = 0.0
    equipment_eui_kwh_m2: float = 0.0


# --- Unmet Hours ---


class UnmetHours(BaseModel):
    """Comfort and setpoint not met summary."""

    heating_unmet_hours: float = 0.0
    cooling_unmet_hours: float = 0.0
    total_unmet_hours: float = 0.0


# --- Simulation Metadata ---


class SimulationMetadata(BaseModel):
    """Metadata extracted from the Simulations table."""

    ep_version: str = ""
    timestamp: str = ""
    weather_file: str = ""
    idf_file: str = ""


# --- Top-Level Output ---


class SimulationOutput(BaseModel):
    """Complete structured output from a simulation run."""

    metadata: SimulationMetadata = Field(default_factory=SimulationMetadata)
    building_area: BuildingArea = Field(default_factory=BuildingArea)
    site_energy_kwh: float = 0.0
    source_energy_kwh: float = 0.0
    end_uses: EnergyEndUse = Field(default_factory=EnergyEndUse)
    normalized: NormalizedMetrics = Field(default_factory=NormalizedMetrics)
    unmet_hours: UnmetHours = Field(default_factory=UnmetHours)
    envelope_opaque: List[EnvelopeSurface] = Field(default_factory=list)
    envelope_windows: List[WindowSurface] = Field(default_factory=list)
    zones: List[ZoneEnergy] = Field(default_factory=list)
    flats: List[FlatEnergy] = Field(default_factory=list)
