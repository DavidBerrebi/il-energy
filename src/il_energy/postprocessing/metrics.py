"""Build complete SimulationOutput from parsed SQL data."""

from __future__ import annotations

from pathlib import Path

from il_energy.models import SimulationOutput
from il_energy.postprocessing.normalizer import compute_normalized_metrics
from il_energy.simulation.sql_parser import SQLParser, GJ_TO_KWH


def extract_metrics(sql_path: Path) -> SimulationOutput:
    """Extract all metrics from an EnergyPlus SQL output file.

    Returns a fully populated SimulationOutput model.
    """
    with SQLParser(sql_path) as parser:
        metadata = parser.parse_metadata()
        building_area = parser.parse_building_area()
        site_gj = parser.parse_site_energy_gj()
        source_gj = parser.parse_source_energy_gj()
        end_uses = parser.parse_end_uses()
        opaque = parser.parse_opaque_surfaces()
        windows = parser.parse_windows()
        unmet = parser.parse_unmet_hours()
        zones = parser.parse_zone_energy()

    site_kwh = site_gj * GJ_TO_KWH
    source_kwh = source_gj * GJ_TO_KWH

    normalized = compute_normalized_metrics(end_uses, building_area.conditioned_m2)

    return SimulationOutput(
        metadata=metadata,
        building_area=building_area,
        site_energy_kwh=site_kwh,
        source_energy_kwh=source_kwh,
        end_uses=end_uses,
        normalized=normalized,
        unmet_hours=unmet,
        envelope_opaque=opaque,
        envelope_windows=windows,
        zones=zones,
    )
