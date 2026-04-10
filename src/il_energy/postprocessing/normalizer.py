"""Energy normalization — convert units and compute per-m² metrics."""

from __future__ import annotations

from il_energy.constants import GJ_TO_KWH, J_TO_KWH
from il_energy.models import EnergyEndUse, NormalizedMetrics


def joules_to_kwh(joules: float) -> float:
    """Convert Joules to kWh."""
    return joules * J_TO_KWH


def gj_to_kwh(gj: float) -> float:
    """Convert GJ to kWh."""
    return gj * GJ_TO_KWH


def compute_normalized_metrics(
    end_uses: EnergyEndUse,
    conditioned_area_m2: float,
) -> NormalizedMetrics:
    """Compute Energy Use Intensity (EUI) metrics per m².

    If conditioned_area_m2 is 0, all EUI values will be 0.
    """
    if conditioned_area_m2 <= 0:
        return NormalizedMetrics()

    return NormalizedMetrics(
        total_eui_kwh_m2=end_uses.total_kwh / conditioned_area_m2,
        heating_eui_kwh_m2=end_uses.heating_kwh / conditioned_area_m2,
        cooling_eui_kwh_m2=end_uses.cooling_kwh / conditioned_area_m2,
        lighting_eui_kwh_m2=(end_uses.interior_lighting_kwh + end_uses.exterior_lighting_kwh) / conditioned_area_m2,
        equipment_eui_kwh_m2=end_uses.interior_equipment_kwh / conditioned_area_m2,
    )
