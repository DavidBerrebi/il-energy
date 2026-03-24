"""CLI entry point for il-energy."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import click

from il_energy.config import EnergyPlusConfig, detect_zone_from_epw
from il_energy.models import SimulationRequest
from il_energy.postprocessing.metrics import extract_metrics
from il_energy.postprocessing.zone_aggregator import aggregate_zones_to_flats, override_floor_types_from_surfaces
from il_energy.rating.calculator import compare_simulations, compute_ip, compute_unit_ratings, grade_from_ip
from il_energy.reference.box_generator import generate_reference_box_idf
from il_energy.reference.generator import generate_reference_idf
from il_energy.report.generator import generate_residential_report
from il_energy.simulation.runner import run_simulation
from il_energy.simulation.si5282_preprocessor import apply_si5282_reference_conditions


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
@click.option("--zone", default=None, help="SI 5282 climate zone (A/B/C). Auto-detected from EPW if omitted.")
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

    if zone is None:
        zone = detect_zone_from_epw(epw_path)
        click.echo(f"Climate zone auto-detected from EPW: {zone}")

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
@click.option("--zone", default=None, help="SI 5282 climate zone (A/B/C). Auto-detected from EPW if omitted.")
def compare_residential(idf: str, epw: str, output_dir: str, zone: str):
    """SI 5282 Part 1 residential comparison using the standard reference unit.

    Runs the proposed building simulation and the standardized 100 m² reference
    box (3 floor types × 4 orientations = 12 runs), computes EPref per floor type
    and EPdes as HVAC-thermal / COP, then calculates IP and energy grade.

    EPref(ft) = average(HVAC_thermal_N + E + S + W) / 4 / 100 m² / COP(3.0)
    EPdes = (proposed_cooling + proposed_heating) / COP / conditioned_area
    IP    = (EPref - EPdes) / EPref * 100 %
    """
    COP = 3.0
    BOX_AREA = 100.0  # m²

    idf_path = Path(idf).resolve()
    epw_path = Path(epw).resolve()
    out_path = Path(output_dir).resolve()
    out_path.mkdir(parents=True, exist_ok=True)

    if zone is None:
        zone = detect_zone_from_epw(epw_path)
        click.echo(f"Climate zone auto-detected from EPW: {zone}")

    click.echo(f"SI 5282 Part 1 Residential Comparison (Zone {zone})")
    click.echo(f"  Proposed IDF: {idf_path}")
    click.echo(f"  Weather: {epw_path}")
    click.echo(f"  Output: {out_path}\n")

    try:
        config = EnergyPlusConfig()
    except Exception as e:
        click.echo(f"Configuration error: {e}", err=True)
        sys.exit(1)

    # ── 1. Apply SI 5282 reference conditions ────────────────────────────────
    click.echo("1. Applying SI 5282 reference operating conditions...")
    with open(idf_path, encoding="latin-1") as f:
        idf_raw = f.read()
    idf_preprocessed = apply_si5282_reference_conditions(idf_raw)
    preprocessed_idf_path = out_path / "proposed_si5282.idf"
    with open(preprocessed_idf_path, "w", encoding="latin-1") as f:
        f.write(idf_preprocessed)
    click.echo(f"   Preprocessed IDF written to: {preprocessed_idf_path}\n")

    # ── 2. Proposed building simulation ─────────────────────────────────────
    click.echo("2. Running proposed building simulation (with SI 5282 conditions)...")
    proposed_dir = out_path / "proposed"
    proposed_req = SimulationRequest(idf_path=preprocessed_idf_path, epw_path=epw_path, output_dir=proposed_dir)
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

    # Compute EPdes from zone-level sensible HVAC (matches EP 9.x / EVERGREEN).
    # EP 25.2 end_uses totals include latent dehumidification loads that EP 9.x
    # did not compute; zone sums use sensible rates (see sql_parser Strategy 2).
    flats_for_ep = proposed_metrics.zones  # ZoneEnergy list (sensible only)
    hvac_proposed = (
        sum(z.cooling_kwh for z in flats_for_ep)
        + sum(z.heating_kwh for z in flats_for_ep)
    )
    ep_des = hvac_proposed / COP / cond_area  # kWh/m²/yr electrical

    click.echo(f"   Conditioned area: {cond_area:.1f} m²")
    click.echo(f"   HVAC thermal: {hvac_proposed / cond_area:.2f} kWh/m²/yr")
    click.echo(f"   EPdes (HVAC/COP/area): {ep_des:.2f} kWh/m²/yr\n")

    # ── 3. Reference box — 3 floor types × 4 orientations (12 runs) ─────────
    click.echo("3. Running reference unit (100 m² box) — 3 floor types × 4 orientations...")
    orientations = {"S": 0.0, "W": 90.0, "N": 180.0, "E": 270.0}
    floor_types_ref = ["ground", "middle", "top"]
    ep_ref_by_floor_type: dict = {}
    ref_hvac_by_ft: dict = {}

    for ft in floor_types_ref:
        hvac_values_ft = []
        for label, north_axis in orientations.items():
            ref_idf_path = out_path / f"refbox_{ft}_{label}.idf"
            ref_out_dir = out_path / f"refbox_{ft}_{label}"
            generate_reference_box_idf(ref_idf_path, climate_zone=zone,
                                       north_axis_deg=north_axis, floor_type=ft)
            req = SimulationRequest(idf_path=ref_idf_path, epw_path=epw_path, output_dir=ref_out_dir)
            try:
                res = run_simulation(req, config)
            except Exception as e:
                click.echo(f"   Reference box {ft}/{label} failed: {e}", err=True)
                sys.exit(1)
            m = extract_metrics(res.sql_path)
            hvac_thermal = m.end_uses.heating_kwh + m.end_uses.cooling_kwh
            hvac_values_ft.append(hvac_thermal)
            click.echo(f"   [{ft}/{label}] HVAC thermal: {hvac_thermal:.1f} kWh  "
                       f"({hvac_thermal / BOX_AREA:.2f} kWh/m²)")
        avg_hvac_ft = sum(hvac_values_ft) / len(hvac_values_ft)
        ep_ref_by_floor_type[ft] = avg_hvac_ft / COP / BOX_AREA
        ref_hvac_by_ft[ft] = dict(zip(orientations.keys(), hvac_values_ft))
        click.echo(f"   EPref({ft}) = {ep_ref_by_floor_type[ft]:.2f} kWh/m²/yr")

    # Building-level EPref uses middle floor (most common for multi-story buildings)
    ep_ref = ep_ref_by_floor_type["middle"]
    click.echo(f"\n   EPref building-level (middle floor avg): {ep_ref:.2f} kWh/m²/yr\n")

    # ── 4. Building-level rating ──────────────────────────────────────────────
    ip_percent = compute_ip(ep_des, ep_ref)
    grade_info = grade_from_ip(ip_percent)

    click.echo("=" * 80)
    click.echo("SI 5282 PART 1 RESIDENTIAL ENERGY RATING")
    click.echo("=" * 80)
    click.echo(f"\nClimate Zone: {zone}")
    click.echo(f"Conditioned Area: {cond_area:.1f} m²\n")
    click.echo(f"EPdes (proposed HVAC/COP/area):  {ep_des:8.2f} kWh/m²/yr")
    click.echo(f"EPref (reference box avg/COP):   {ep_ref:8.2f} kWh/m²/yr")
    click.echo(f"\nIMPROVEMENT PERCENTAGE (IP): {ip_percent:+.1f}%")
    click.echo(f"GRADE: {grade_info['grade']} ({grade_info['name_en']} / {grade_info['name_he']})")

    # ── 5. Per-unit rating ────────────────────────────────────────────────────
    flats = aggregate_zones_to_flats(proposed_metrics.zones)
    override_floor_types_from_surfaces(flats, proposed_metrics.envelope_opaque)
    unit_ratings = compute_unit_ratings(flats, ep_ref_by_floor_type, cop=COP)

    if unit_ratings:
        click.echo(f"\n{'─'*80}")
        click.echo(f"PER-UNIT RATINGS ({len(unit_ratings)} units)")
        click.echo(f"{'─'*80}")
        click.echo(f"{'Unit':<12} {'Floor':<7} {'Type':<8} {'Area':>6} {'EPdes':>7} {'EPref':>7} {'IP%':>7} {'Grade':<8}")
        click.echo(f"{'─'*80}")
        grade_counts: dict = {}
        for u in unit_ratings:
            g = u['grade']['grade']
            grade_counts[g] = grade_counts.get(g, 0) + 1
            click.echo(
                f"{u['flat_id']:<12} {str(u['floor_number']):<7} {u['floor_type']:<8} "
                f"{u['area_m2']:>6.1f} {u['ep_des_kwh_m2']:>7.2f} {u['ep_ref_kwh_m2']:>7.2f} "
                f"{u['ip_percent']:>+7.1f} {g:<8}"
            )
        click.echo(f"{'─'*80}")
        click.echo("Grade distribution: " + "  ".join(f"{g}:{n}" for g, n in sorted(grade_counts.items())))

    result = {
        "standard": "SI 5282 Part 1",
        "climate_zone": zone,
        "conditioned_area_m2": cond_area,
        "ep_des_kwh_m2": ep_des,
        "ep_ref_kwh_m2": ep_ref,
        "ep_ref_by_floor_type": ep_ref_by_floor_type,
        "ip_percent": ip_percent,
        "grade": grade_info,
        "ref_box_hvac_by_floor_type": ref_hvac_by_ft,
        "cop": COP,
        "reference_unit_area_m2": BOX_AREA,
        "unit_ratings": unit_ratings,
        "notes": [
            "EPdes = (cooling + heating kWh) / COP / conditioned area",
            "EPref = average of 4 orientations (N/E/S/W) / COP / 100 m² per floor type",
            "Building-level EPref uses middle floor type",
            "Reference unit per SI 5282 Part 1 Appendix ג, Table ג-1",
        ],
    }
    json_path = out_path / "residential_rating.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, default=str)
    click.echo(f"\nResults written to: {json_path}")

    # ── 6. Professional report ────────────────────────────────────────────────
    click.echo("\n6. Generating professional report...")
    try:
        project_name = idf_path.stem
        report_paths = generate_residential_report(
            rating_result=result,
            output=proposed_metrics,
            output_dir=out_path,
            project_name=project_name,
        )
        click.echo(f"   ✓ {report_paths['report_md'].name}")
        click.echo(f"   ✓ {report_paths['units_csv'].name}")
        click.echo(f"   ✓ {report_paths['windows_csv'].name}")
    except Exception as e:
        click.echo(f"   Report generation failed: {e}", err=True)


if __name__ == "__main__":
    main()
