"""SI 5282 rating calculation — compute IP and determine energy grade."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List, Optional

from il_energy.exceptions import ILEnergyError
from il_energy.models import FlatEnergy, SimulationOutput


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


def compute_unit_ratings(
    flats: List[FlatEnergy],
    ep_ref_by_floor_type: Dict[str, float],
    cop: float = 3.0,
    ep_ref_by_flat_id: Optional[Dict[str, float]] = None,
) -> List[Dict[str, object]]:
    """Compute per-unit SI 5282 Part 1 ratings.

    Args:
        flats: Aggregated flat energy data (from zone_aggregator).
        ep_ref_by_floor_type: EPref [kWh/m²/yr electrical] keyed by floor type
            ("ground", "middle", "top").  Used as fallback when ep_ref_by_flat_id
            is not provided or the flat is not in it.
        cop: HVAC coefficient of performance (default 3.0).
        ep_ref_by_flat_id: Per-flat EPref [kWh/m²/yr electrical] keyed by flat_id.
            When provided, takes precedence over ep_ref_by_floor_type for matching
            flats (reference building geometry approach).

    Returns:
        List of dicts, one per flat, sorted by flat_id:
            flat_id, floor_number, floor_type, area_m2,
            cooling_kwh, heating_kwh, hvac_kwh,
            ep_des_kwh_m2, ep_ref_kwh_m2, ip_percent, grade (dict)
    """
    results = []
    for flat in sorted(flats, key=lambda f: f.flat_id):
        if flat.floor_area_m2 <= 0:
            continue
        hvac_kwh = flat.cooling_kwh + flat.heating_kwh
        ep_des = hvac_kwh / cop / flat.floor_area_m2
        if ep_ref_by_flat_id and flat.flat_id in ep_ref_by_flat_id:
            ep_ref = ep_ref_by_flat_id[flat.flat_id]
        else:
            ep_ref = ep_ref_by_floor_type.get(flat.floor_type,
                     ep_ref_by_floor_type.get("middle", 0.0))
        ip = compute_ip(ep_des, ep_ref)
        results.append({
            "flat_id": flat.flat_id,
            "floor_number": flat.floor_number,
            "floor_type": flat.floor_type,
            "orientation": flat.orientation,
            "area_m2": flat.floor_area_m2,
            "cooling_kwh": flat.cooling_kwh,
            "heating_kwh": flat.heating_kwh,
            "hvac_kwh": hvac_kwh,
            "cop": cop,
            "ep_des_kwh_m2": ep_des,
            "ep_ref_kwh_m2": ep_ref,
            "ip_percent": ip,
            "grade": grade_from_ip(ip),
        })
    return results


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
