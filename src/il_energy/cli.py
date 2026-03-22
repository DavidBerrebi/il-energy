"""CLI entry point for il-energy."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import click

from il_energy.config import EnergyPlusConfig
from il_energy.models import SimulationRequest
from il_energy.postprocessing.metrics import extract_metrics
from il_energy.postprocessing.zone_aggregator import aggregate_zones_to_flats
from il_energy.rating.calculator import compare_simulations, compute_ip, grade_from_ip
from il_energy.reference.box_generator import generate_reference_box_idf
from il_energy.reference.generator import generate_reference_idf
from il_energy.simulation.runner import run_simulation


@click.group()
def main():
    """Israeli Energy Compliance Engine (SI 5282)."""


@main.command()
@click.option("--idf", required=True, type=click.Path(exists=True), help="Path to IDF file")
@click.option("--epw", required=True, type=click.Path(exists=True), help="Path to EPW weather file")
@click.option("--output-dir", required=True, type=click.Path(), help="Output directory")
def run(idf: str, epw: str, output_dir: str):
    """Run EnergyPlus simulation and extract metrics."""
    idf_path = Path(idf).resolve()
    epw_path = Path(epw).resolve()
    out_path = Path(output_dir).resolve()

    click.echo(f"IDF: {idf_path}")
    click.echo(f"EPW: {epw_path}")
    click.echo(f"Output: {out_path}")

    # Run simulation
    click.echo("Running EnergyPlus simulation...")
    try:
        config = EnergyPlusConfig()
        request = SimulationRequest(
            idf_path=idf_path,
            epw_path=epw_path,
            output_dir=out_path,
        )
        result = run_simulation(request, config)
    except Exception as e:
        click.echo(f"Simulation failed: {e}", err=True)
        sys.exit(1)

    click.echo(f"Simulation completed (exit code {result.return_code})")

    # Extract metrics
    click.echo("Extracting metrics from SQL output...")
    output = extract_metrics(result.sql_path)

    # Aggregate zones to flats
    if output.zones:
        output.flats = aggregate_zones_to_flats(output.zones)

    # Write JSON output
    json_path = out_path / "simulation_output.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(output.model_dump(), f, indent=2, default=str)

    click.echo(f"Results written to {json_path}")
    click.echo(f"  Site energy: {output.site_energy_kwh:.1f} kWh")
    click.echo(f"  Building area: {output.building_area.total_m2:.1f} m²")
    click.echo(f"  Conditioned area: {output.building_area.conditioned_m2:.1f} m²")
    click.echo(f"  Zones: {len(output.zones)}")
    click.echo(f"  Flats: {len(output.flats)}")


@main.command()
@click.option("--sql", required=True, type=click.Path(exists=True), help="Path to eplusout.sql")
@click.option("--output", "-o", type=click.Path(), help="Output JSON path (default: stdout)")
def parse(sql: str, output: str):
    """Parse an existing EnergyPlus SQL output without running a simulation."""
    sql_path = Path(sql).resolve()

    result = extract_metrics(sql_path)

    if result.zones:
        result.flats = aggregate_zones_to_flats(result.zones)

    data = json.dumps(result.model_dump(), indent=2, default=str)

    if output:
        Path(output).write_text(data, encoding="utf-8")
        click.echo(f"Results written to {output}")
    else:
        click.echo(data)


@main.command()
@click.option("--idf", required=True, type=click.Path(exists=True), help="Path to proposed IDF file")
@click.option("--epw", required=True, type=click.Path(exists=True), help="Path to EPW weather file")
@click.option("--output-dir", required=True, type=click.Path(), help="Output directory for comparison results")
@click.option("--zone", default="B", help="SI 5282 climate zone (A, B, or C). Default: B")
def compare(idf: str, epw: str, output_dir: str, zone: str):
    """Compare proposed building against SI 5282 reference building.

    Runs EnergyPlus on both proposed and reference IDFs, computes Improvement
    Percentage (IP), determines energy grade (A+ through F), and generates
    H-value (EUI) comparison table.
    """
    idf_path = Path(idf).resolve()
    epw_path = Path(epw).resolve()
    out_path = Path(output_dir).resolve()
    out_path.mkdir(parents=True, exist_ok=True)

    click.echo(f"SI 5282 Comparison (Zone {zone})")
    click.echo(f"  Proposed IDF: {idf_path}")
    click.echo(f"  Weather: {epw_path}")
    click.echo(f"  Output: {out_path}\n")

    try:
        config = EnergyPlusConfig()
    except Exception as e:
        click.echo(f"Configuration error: {e}", err=True)
        sys.exit(1)

    # Run proposed simulation
    click.echo("1. Running proposed building simulation...")
    proposed_dir = out_path / "proposed"
    proposed_request = SimulationRequest(
        idf_path=idf_path,
        epw_path=epw_path,
        output_dir=proposed_dir,
    )
    try:
        proposed_result = run_simulation(proposed_request, config)
    except Exception as e:
        click.echo(f"Proposed simulation failed: {e}", err=True)
        sys.exit(1)
    click.echo(f"   ✓ Simulation completed (exit code {proposed_result.return_code})")

    # Generate reference IDF
    click.echo("\n2. Generating reference building IDF...")
    ref_idf_path = out_path / "reference.idf"
    try:
        gen_result = generate_reference_idf(idf_path, ref_idf_path, climate_zone=zone)
        click.echo(f"   ✓ Reference IDF generated: {ref_idf_path}")
        for const_name, count in gen_result["replacements"].items():
            if count > 0:
                info = gen_result["constructions"][const_name]
                click.echo(
                    f"     • {const_name} → {info['ref_name']} "
                    f"({count} surfaces, U={info['u_target']:.2f} W/m²K)"
                )
    except Exception as e:
        click.echo(f"Reference IDF generation failed: {e}", err=True)
        sys.exit(1)

    # Run reference simulation
    click.echo("\n3. Running reference building simulation...")
    ref_dir = out_path / "reference"
    ref_request = SimulationRequest(
        idf_path=ref_idf_path,
        epw_path=epw_path,
        output_dir=ref_dir,
    )
    try:
        ref_result = run_simulation(ref_request, config)
    except Exception as e:
        click.echo(f"Reference simulation failed: {e}", err=True)
        sys.exit(1)
    click.echo(f"   ✓ Simulation completed (exit code {ref_result.return_code})")

    # Extract and compare metrics
    click.echo("\n4. Extracting metrics and computing IP...")
    try:
        proposed_output = extract_metrics(proposed_result.sql_path)
        reference_output = extract_metrics(ref_result.sql_path)
        comparison = compare_simulations(proposed_output, reference_output, climate_zone=zone)
    except Exception as e:
        click.echo(f"Metrics extraction failed: {e}", err=True)
        sys.exit(1)

    # Print comparison table
    click.echo("\n" + "=" * 80)
    click.echo("SI 5282 ENERGY RATING COMPARISON")
    click.echo("=" * 80)
    click.echo(f"\nClimate Zone: {zone}")
    click.echo(f"Conditioned Area: {comparison['conditioned_area_m2']:.1f} m²\n")

    click.echo("H-VALUES (kWh/m²/yr):")
    click.echo(f"{'End-use':<20} {'Proposed':>12} {'Reference':>12} {'Delta':>12}")
    click.echo("-" * 58)
    for hv in comparison["h_values"]:
        click.echo(
            f"{hv['end_use']:<20} {hv['proposed_kwh_m2']:>12.2f} "
            f"{hv['reference_kwh_m2']:>12.2f} {hv['delta_kwh_m2']:>12.2f}"
        )

    click.echo("\nENERGY RATING:")
    grade = comparison["grade"]
    click.echo(f"  Improvement Percentage (IP):  {comparison['ip_percent']:>6.1f}%")
    click.echo(f"  Grade:                        {grade['grade']} ({grade['name_en']})")
    click.echo(f"  Score:                        {grade['score']}")

    click.echo("\nNOTES:")
    for note in comparison.get("notes", []):
        click.echo(f"  • {note}")

    # Write JSON output
    json_path = out_path / "comparison_result.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(comparison, f, indent=2, default=str)
    click.echo(f"\nResults written to: {json_path}")


@main.command("compare-residential")
@click.option("--idf", required=True, type=click.Path(exists=True), help="Proposed building IDF")
@click.option("--epw", required=True, type=click.Path(exists=True), help="EPW weather file")
@click.option("--output-dir", required=True, type=click.Path(), help="Output directory")
@click.option("--zone", default="B", help="SI 5282 climate zone (A/B/C). Default: B")
@click.option("--floor-type", default="middle",
              type=click.Choice(["middle", "top", "ground", "open"]),
              help="Floor position of typical unit. Default: middle")
def compare_residential(idf: str, epw: str, output_dir: str, zone: str, floor_type: str):
    """SI 5282 Part 1 residential comparison using the standard reference unit.

    Runs the proposed building simulation and the standardized 100 m² reference
    box (4 orientations), computes EPref and EPdes as HVAC-thermal / COP, then
    calculates IP and energy grade.

    EPref = average(HVAC_thermal_N + E + S + W) / 4 / 100 m² / COP(3.0)
    EPdes = (proposed_cooling + proposed_heating) / COP / conditioned_area
    IP    = (EPref - EPdes) / EPref * 100 %
    """
    COP = 3.0
    BOX_AREA = 100.0  # m²

    idf_path = Path(idf).resolve()
    epw_path = Path(epw).resolve()
    out_path = Path(output_dir).resolve()
    out_path.mkdir(parents=True, exist_ok=True)

    click.echo(f"SI 5282 Part 1 Residential Comparison (Zone {zone}, {floor_type} floor)")
    click.echo(f"  Proposed IDF: {idf_path}")
    click.echo(f"  Weather: {epw_path}")
    click.echo(f"  Output: {out_path}\n")

    try:
        config = EnergyPlusConfig()
    except Exception as e:
        click.echo(f"Configuration error: {e}", err=True)
        sys.exit(1)

    # ── 1. Proposed building simulation ─────────────────────────────────────
    click.echo("1. Running proposed building simulation...")
    proposed_dir = out_path / "proposed"
    proposed_req = SimulationRequest(idf_path=idf_path, epw_path=epw_path, output_dir=proposed_dir)
    try:
        proposed_result = run_simulation(proposed_req, config)
    except Exception as e:
        click.echo(f"Proposed simulation failed: {e}", err=True)
        sys.exit(1)
    click.echo(f"   done (exit code {proposed_result.return_code})")

    proposed_metrics = extract_metrics(proposed_result.sql_path)
    cond_area = proposed_metrics.building_area.conditioned_m2
    if cond_area <= 0:
        click.echo("Error: proposed building has zero conditioned area.", err=True)
        sys.exit(1)

    hvac_proposed = proposed_metrics.end_uses.heating_kwh + proposed_metrics.end_uses.cooling_kwh
    ep_des = hvac_proposed / COP / cond_area  # kWh/m²/yr electrical

    click.echo(f"   Conditioned area: {cond_area:.1f} m²")
    click.echo(f"   HVAC thermal: {hvac_proposed / cond_area:.2f} kWh/m²/yr")
    click.echo(f"   EPdes (HVAC/COP/area): {ep_des:.2f} kWh/m²/yr\n")

    # ── 2. Reference box — 4 orientations ───────────────────────────────────
    click.echo("2. Running reference unit (100 m² box) — 4 orientations...")
    orientations = {"S": 0.0, "W": 90.0, "N": 180.0, "E": 270.0}
    ref_hvac_values = []

    for label, north_axis in orientations.items():
        ref_idf_path = out_path / f"refbox_{label}.idf"
        ref_out_dir = out_path / f"refbox_{label}"
        generate_reference_box_idf(ref_idf_path, climate_zone=zone,
                                   north_axis_deg=north_axis, floor_type=floor_type)
        req = SimulationRequest(idf_path=ref_idf_path, epw_path=epw_path, output_dir=ref_out_dir)
        try:
            res = run_simulation(req, config)
        except Exception as e:
            click.echo(f"   Reference box {label} failed: {e}", err=True)
            sys.exit(1)
        m = extract_metrics(res.sql_path)
        hvac_thermal = m.end_uses.heating_kwh + m.end_uses.cooling_kwh
        ref_hvac_values.append(hvac_thermal)
        click.echo(f"   [{label}] HVAC thermal: {hvac_thermal:.1f} kWh  "
                   f"({hvac_thermal / BOX_AREA:.2f} kWh/m²)")

    avg_ref_hvac = sum(ref_hvac_values) / len(ref_hvac_values)
    ep_ref = avg_ref_hvac / COP / BOX_AREA  # kWh/m²/yr electrical
    click.echo(f"\n   EPref (avg HVAC/COP/100m²): {ep_ref:.2f} kWh/m²/yr\n")

    # ── 3. Rating ────────────────────────────────────────────────────────────
    ip_percent = compute_ip(ep_des, ep_ref)
    grade_info = grade_from_ip(ip_percent)

    click.echo("=" * 80)
    click.echo("SI 5282 PART 1 RESIDENTIAL ENERGY RATING")
    click.echo("=" * 80)
    click.echo(f"\nClimate Zone: {zone}  |  Floor type: {floor_type}")
    click.echo(f"Conditioned Area: {cond_area:.1f} m²\n")
    click.echo(f"EPdes (proposed HVAC/COP/area):  {ep_des:8.2f} kWh/m²/yr")
    click.echo(f"EPref (reference box avg/COP):   {ep_ref:8.2f} kWh/m²/yr")
    click.echo(f"\nIMPROVEMENT PERCENTAGE (IP): {ip_percent:+.1f}%")
    click.echo(f"GRADE: {grade_info['grade']} ({grade_info['name_en']} / {grade_info['name_he']})")

    result = {
        "standard": "SI 5282 Part 1",
        "climate_zone": zone,
        "floor_type": floor_type,
        "conditioned_area_m2": cond_area,
        "ep_des_kwh_m2": ep_des,
        "ep_ref_kwh_m2": ep_ref,
        "ip_percent": ip_percent,
        "grade": grade_info,
        "ref_box_hvac_by_orientation": dict(zip(orientations.keys(), ref_hvac_values)),
        "cop": COP,
        "reference_unit_area_m2": BOX_AREA,
        "notes": [
            "EPdes = (cooling + heating kWh) / COP / conditioned area",
            "EPref = average of 4 orientations (N/E/S/W) / COP / 100 m²",
            "Reference unit per SI 5282 Part 1 Appendix ג, Table ג-1",
        ],
    }
    json_path = out_path / "residential_rating.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, default=str)
    click.echo(f"\nResults written to: {json_path}")


if __name__ == "__main__":
    main()
