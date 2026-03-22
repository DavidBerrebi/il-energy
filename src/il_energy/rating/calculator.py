"""SI 5282 rating calculation — compute IP and determine energy grade."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List, Optional

from il_energy.exceptions import ILEnergyError
from il_energy.models import SimulationOutput


def compute_ip(proposed_eui: float, reference_eui: float) -> float:
    """Compute Improvement Percentage (IP).

    IP = (EUI_reference - EUI_proposed) / EUI_reference * 100

    Args:
        proposed_eui: Proposed building EUI (kWh/m²/yr).
        reference_eui: Reference building EUI (kWh/m²/yr).

    Returns:
        IP percentage. May be negative if proposed is worse than reference.
    """
    if reference_eui <= 0:
        return 0.0
    return (reference_eui - proposed_eui) / reference_eui * 100.0


def grade_from_ip(ip_percent: float) -> Dict[str, object]:
    """Look up SI 5282 grade based on IP percentage.

    Loads `standards/si5282/rating_thresholds.json` and returns the matching grade.

    Args:
        ip_percent: Improvement percentage.

    Returns:
        dict with keys: grade, name_en, name_he, score, ip_range.
    """
    thresholds_path = Path(__file__).parent.parent.parent.parent / "standards" / "si5282" / "rating_thresholds.json"

    if not thresholds_path.is_file():
        raise ILEnergyError(f"Rating thresholds not found: {thresholds_path}")

    with open(thresholds_path, encoding="utf-8") as f:
        data = json.load(f)

    grades = data.get("rating_grades", [])
    if not grades:
        raise ILEnergyError("No rating grades defined in thresholds.json")

    # Iterate from best to worst, return first match
    for grade_def in grades:
        if "min_ip_percent" in grade_def:
            if ip_percent >= grade_def["min_ip_percent"]:
                return {
                    "grade": grade_def.get("grade", ""),
                    "name_en": grade_def.get("name_en", ""),
                    "name_he": grade_def.get("name_he", ""),
                    "score": grade_def.get("score", 0),
                    "ip_range": f">= {grade_def['min_ip_percent']}%",
                }
        elif "below_ip_percent" in grade_def:
            if ip_percent < grade_def["below_ip_percent"]:
                return {
                    "grade": grade_def.get("grade", ""),
                    "name_en": grade_def.get("name_en", ""),
                    "name_he": grade_def.get("name_he", ""),
                    "score": grade_def.get("score", -1),
                    "ip_range": f"< {grade_def['below_ip_percent']}%",
                }

    # Fallback to worst grade
    return {
        "grade": "F",
        "name_en": "Below Base",
        "name_he": "לא עומד",
        "score": -1,
        "ip_range": "< -10%",
    }


class ComparisonNotAvailableError(ILEnergyError):
    """Raised when required data for comparison is missing."""


def compare_simulations(
    proposed: SimulationOutput,
    reference: SimulationOutput,
    climate_zone: str = "B",
) -> Dict[str, object]:
    """Compare proposed and reference simulation outputs.

    Computes IP, determines grade, and builds H-value (EUI) comparison table.

    Args:
        proposed: SimulationOutput from proposed building simulation.
        reference: SimulationOutput from reference building simulation.
        climate_zone: Climate zone for metadata.

    Returns:
        dict with keys:
            - climate_zone
            - conditioned_area_m2
            - proposed: {site_kwh, eui_kwh_m2}
            - reference: {site_kwh, eui_kwh_m2}
            - ip_percent
            - grade (dict with grade, name_en, name_he, score)
            - h_values (list of end-use comparisons)
            - reference_u_values_estimated (bool)
            - notes (list of strings)

    Raises:
        ComparisonNotAvailableError: If required metrics are missing.
    """
    cond_area = proposed.building_area.conditioned_m2

    if cond_area <= 0:
        raise ComparisonNotAvailableError(
            "Proposed building has zero or negative conditioned area. "
            "Cannot compute normalized metrics."
        )

    proposed_eui = proposed.site_energy_kwh / cond_area if cond_area > 0 else 0.0
    reference_eui = reference.site_energy_kwh / cond_area if cond_area > 0 else 0.0

    ip_percent = compute_ip(proposed_eui, reference_eui)
    grade_info = grade_from_ip(ip_percent)

    # Build H-value table (end-uses normalized per m²)
    h_values: List[Dict[str, object]] = []

    # HVAC summary
    h_values.append({
        "end_use": "Cooling",
        "proposed_kwh_m2": proposed.end_uses.cooling_kwh / cond_area,
        "reference_kwh_m2": reference.end_uses.cooling_kwh / cond_area,
        "delta_kwh_m2": (reference.end_uses.cooling_kwh - proposed.end_uses.cooling_kwh) / cond_area,
    })
    h_values.append({
        "end_use": "Heating",
        "proposed_kwh_m2": proposed.end_uses.heating_kwh / cond_area,
        "reference_kwh_m2": reference.end_uses.heating_kwh / cond_area,
        "delta_kwh_m2": (reference.end_uses.heating_kwh - proposed.end_uses.heating_kwh) / cond_area,
    })

    hvac_total_delta = (
        (reference.end_uses.heating_kwh + reference.end_uses.cooling_kwh)
        - (proposed.end_uses.heating_kwh + proposed.end_uses.cooling_kwh)
    ) / cond_area
    h_values.append({
        "end_use": "HVAC Total",
        "proposed_kwh_m2": (proposed.end_uses.heating_kwh + proposed.end_uses.cooling_kwh) / cond_area,
        "reference_kwh_m2": (reference.end_uses.heating_kwh + reference.end_uses.cooling_kwh) / cond_area,
        "delta_kwh_m2": hvac_total_delta,
    })

    # Interior Lighting
    h_values.append({
        "end_use": "Interior Lighting",
        "proposed_kwh_m2": proposed.end_uses.interior_lighting_kwh / cond_area,
        "reference_kwh_m2": reference.end_uses.interior_lighting_kwh / cond_area,
        "delta_kwh_m2": (reference.end_uses.interior_lighting_kwh - proposed.end_uses.interior_lighting_kwh) / cond_area,
    })

    # Interior Equipment
    h_values.append({
        "end_use": "Interior Equipment",
        "proposed_kwh_m2": proposed.end_uses.interior_equipment_kwh / cond_area,
        "reference_kwh_m2": reference.end_uses.interior_equipment_kwh / cond_area,
        "delta_kwh_m2": (reference.end_uses.interior_equipment_kwh - proposed.end_uses.interior_equipment_kwh) / cond_area,
    })

    # Total Site Energy
    h_values.append({
        "end_use": "Total Site Energy",
        "proposed_kwh_m2": proposed_eui,
        "reference_kwh_m2": reference_eui,
        "delta_kwh_m2": reference_eui - proposed_eui,
    })

    notes: List[str] = [
        f"Reference U-values from SI 5282 Part 1, Table G-1 (February 2023), Zone {climate_zone}.",
        "Reference building uses proposed geometry with standard reference constructions (commercial approximation).",
        "Residential standard (Part 1) specifies a 100 m2 box reference unit — see reference/generator.py for details.",
    ]

    return {
        "climate_zone": climate_zone,
        "conditioned_area_m2": cond_area,
        "proposed": {
            "site_kwh": proposed.site_energy_kwh,
            "eui_kwh_m2": proposed_eui,
        },
        "reference": {
            "site_kwh": reference.site_energy_kwh,
            "eui_kwh_m2": reference_eui,
        },
        "ip_percent": ip_percent,
        "grade": grade_info,
        "h_values": h_values,
        "reference_u_values_estimated": False,
        "notes": notes,
    }
