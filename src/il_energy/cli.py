"""CLI entry point for il-energy."""

from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import click

from il_energy.config import EnergyPlusConfig, detect_zone_from_epw
from il_energy.models import SimulationRequest
from il_energy.postprocessing.metrics import extract_metrics
from il_energy.postprocessing.zone_aggregator import aggregate_zones_to_flats, assign_orientations_from_windows, override_floor_types_from_surfaces
from il_energy.rating.calculator import compare_simulations, compute_ip, compute_unit_ratings, grade_from_ip
from il_energy.reference.box_generator import generate_reference_box_idf
from il_energy.reference.generator import generate_reference_idf
from il_energy.report.generator import generate_residential_report
from il_energy.simulation.runner import run_simulation
from il_energy.simulation.si5282_preprocessor import apply_si5282_reference_conditions


from il_energy.constants import (
    DEFAULT_COP,
    REFERENCE_BOX_AREA_M2,
    REF_WINDOW_SHGC,
    REF_WINDOW_U_W_M2K,
    SMALL_UNIT_FACTOR,
    SMALL_UNIT_THRESHOLD_M2,
)

# Reference window material values per SI 5282 Part 1, Table ג-1
_REF_WINDOW_U = {"A": REF_WINDOW_U_W_M2K, "B": REF_WINDOW_U_W_M2K, "C": REF_WINDOW_U_W_M2K}
_REF_WINDOW_SHGC = {"A": REF_WINDOW_SHGC, "B": REF_WINDOW_SHGC, "C": REF_WINDOW_SHGC}


def _replace_window_materials(idf_text: str, climate_zone: str) -> str:
    """Replace all WindowMaterial:SimpleGlazingSystem U-Factor and SHGC with
    SI 5282 Table ג-1 reference values in-place.

    All window constructions get the same reference values, preserving the
    window geometry (area) and orientations unchanged.
    """
    u_ref = _REF_WINDOW_U[climate_zone]
    shgc_ref = _REF_WINDOW_SHGC[climate_zone]

    def _patch_block(m: re.Match) -> str:
        block = m.group(0)
        # Replace U-Factor field (2nd numeric field after Name)
        block = re.sub(
            r"(WindowMaterial:SimpleGlazingSystem,.*?;)",
            lambda b: _patch_simple_glazing(b.group(1), u_ref, shgc_ref),
            block,
            flags=re.DOTALL,
        )
        return block

    # Replace U and SHGC in each SimpleGlazingSystem block
    return re.sub(
        r"WindowMaterial:SimpleGlazingSystem,.*?;",
        lambda m: _patch_simple_glazing(m.group(0), u_ref, shgc_ref),
        idf_text,
        flags=re.DOTALL,
    )


def _patch_simple_glazing(block: str, u_ref: float, shgc_ref: float) -> str:
    """Patch a single WindowMaterial:SimpleGlazingSystem block.

    The IDF object format is:
        WindowMaterial:SimpleGlazingSystem,
            <Name>,          !- Name
            <U-Factor>,      !- U-Factor {W/m2-K}
            <SHGC>,          !- Solar Heat Gain Coefficient
            [<VT>];          !- Visible Transmittance (optional)
    """
    lines = block.split("\n")
    field_idx = 0  # tracks comma-separated fields after the object type
    result = []
    for line in lines:
        # Count commas/semicolons to know which field we're on
        stripped = line.strip()
        if re.match(r"WindowMaterial:SimpleGlazingSystem\s*,", stripped, re.IGNORECASE):
            result.append(line)
            continue
        # Each non-comment line with a value is a field
        if stripped and not stripped.startswith("!"):
            val_match = re.match(r"^(\s*)([^,;!]+)([,;])(.*)", line)
            if val_match:
                indent, val, sep, rest = val_match.groups()
                field_idx += 1
                if field_idx == 1:  # Name — keep
                    result.append(line)
                elif field_idx == 2:  # U-Factor
                    result.append(f"{indent}{u_ref}{sep}{rest}")
                elif field_idx == 3:  # SHGC
                    result.append(f"{indent}{shgc_ref}{sep}{rest}")
                else:
                    result.append(line)
                continue
        result.append(line)
    return "\n".join(result)


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


def _preprocess_proposed_idf(idf_path: Path, output_dir: Path) -> tuple:
    """Apply SI 5282 reference conditions to IDF and write preprocessed copy.

    Returns (preprocessed_idf_text, preprocessed_idf_path).
    """
    idf_raw = idf_path.read_text(encoding="latin-1")
    idf_preprocessed = apply_si5282_reference_conditions(idf_raw)
    preprocessed_idf_path = output_dir / "proposed_si5282.idf"
    preprocessed_idf_path.write_text(idf_preprocessed, encoding="latin-1")
    click.echo(f"   Preprocessed IDF written to: {preprocessed_idf_path}\n")
    return idf_preprocessed, preprocessed_idf_path


def _run_proposed_and_aggregate(preprocessed_idf_path: Path, epw_path: Path,
                                 output_dir: Path, config, cop: float):
    """Run proposed simulation, extract metrics, compute EPdes, aggregate flats.

    Returns (proposed_result, proposed_metrics, flats, ep_des_kwh_m2, conditioned_area_m2).
    """
    proposed_dir = output_dir / "proposed"
    proposed_request = SimulationRequest(
        idf_path=preprocessed_idf_path, epw_path=epw_path, output_dir=proposed_dir,
    )
    proposed_result = run_simulation(
        proposed_request, config,
        stdout_callback=lambda line: click.echo(f"   EP> {line}", nl=False),
    )
    click.echo(f"   done (exit code {proposed_result.return_code})")

    proposed_metrics = extract_metrics(proposed_result.sql_path)
    conditioned_area_m2 = proposed_metrics.building_area.conditioned_m2
    if conditioned_area_m2 <= 0:
        click.echo("Error: proposed building has zero conditioned area.", err=True)
        sys.exit(1)

    # EPdes uses zone-level sensible HVAC only (excludes EP 25.2 latent loads).
    hvac_thermal_kwh = sum(
        zone.cooling_kwh + zone.heating_kwh for zone in proposed_metrics.zones
    )
    ep_des_kwh_m2 = hvac_thermal_kwh / cop / conditioned_area_m2

    click.echo(f"   Conditioned area: {conditioned_area_m2:.1f} m²")
    click.echo(f"   HVAC thermal: {hvac_thermal_kwh / conditioned_area_m2:.2f} kWh/m²/yr")
    click.echo(f"   EPdes (HVAC/COP/area): {ep_des_kwh_m2:.2f} kWh/m²/yr\n")

    # Aggregate zones → flats; classify floor types before EPref lookup so
    # penthouse units get the correct "top" EPref rather than "middle".
    flats = aggregate_zones_to_flats(proposed_metrics.zones)
    override_floor_types_from_surfaces(flats, proposed_metrics.envelope_opaque)
    assign_orientations_from_windows(flats, proposed_metrics.envelope_windows)

    return proposed_result, proposed_metrics, flats, ep_des_kwh_m2, conditioned_area_m2


def _compute_epref_tabulated(zone_table: dict, flats) -> tuple:
    """Build EPref lookups from tabulated SI 5282 values.

    Returns (ep_ref_by_floor_type, ep_ref_by_flat_id).
    """
    ep_ref_by_floor_type: dict = {}
    ep_ref_by_flat_id: dict = {}
    small_unit_threshold = zone_table.get("small_unit_threshold_m2", SMALL_UNIT_THRESHOLD_M2)

    for floor_type in ("ground", "middle", "top"):
        floor_type_data = zone_table.get(floor_type)
        if floor_type_data:
            ep_ref_by_floor_type[floor_type] = floor_type_data.get("standard", 0.0)

    for flat in flats:
        if flat.floor_area_m2 <= 0:
            continue
        floor_type_data = zone_table.get(flat.floor_type) or {}
        if flat.floor_area_m2 <= small_unit_threshold and "small_le50m2" in floor_type_data:
            ep_ref_by_flat_id[flat.flat_id] = floor_type_data["small_le50m2"]
        else:
            ep_ref_by_flat_id[flat.flat_id] = floor_type_data.get("standard", 0.0)

    for floor_type, ep_ref_value in ep_ref_by_floor_type.items():
        click.echo(f"   EPref({floor_type}) = {ep_ref_value:.2f} kWh/m²/yr  [tabulated]")

    return ep_ref_by_floor_type, ep_ref_by_flat_id


def _compute_epref_by_simulation(flats, zone: str, epw_path: Path,
                                  output_dir: Path, config, cop: float) -> tuple:
    """Run 12 reference box simulations (3 floor types × 4 orientations).

    Returns (ep_ref_by_floor_type, ep_ref_by_flat_id, ref_hvac_by_floor_type).
    """
    # SI 5282 Appendix ג: fixed 100 m² box, 4 orientations averaged.
    # Small units (≤50 m²) use a multiplier instead of a smaller box because
    # the standard fixes occupancy at 4 persons regardless of area.
    orientations = {"S": 0.0, "W": 90.0, "N": 180.0, "E": 270.0}
    floor_types = sorted({flat.floor_type for flat in flats if flat.floor_area_m2 > 0})

    click.echo(
        f"3. Running reference boxes — {len(floor_types)} floor types "
        f"× 4 orientations = {len(floor_types) * 4} runs "
        f"(100 m² fixed box per SI 5282 Appendix ג)..."
    )

    ep_ref_by_floor_type: dict = {}
    ep_ref_by_flat_id: dict = {}
    ref_hvac_by_floor_type: dict = {}

    for floor_type in floor_types:
        hvac_per_orientation = []
        for orientation_label, north_axis_deg in orientations.items():
            ref_idf_path = (output_dir / "reference_boxes"
                            / f"refbox_{floor_type}_{orientation_label}.idf")
            ref_output_dir = (output_dir / "reference_boxes"
                              / f"refbox_{floor_type}_{orientation_label}")
            ref_idf_path.parent.mkdir(parents=True, exist_ok=True)

            generate_reference_box_idf(
                ref_idf_path, climate_zone=zone,
                north_axis_deg=north_axis_deg, floor_type=floor_type,
                floor_area_m2=REFERENCE_BOX_AREA_M2,
            )
            ref_request = SimulationRequest(
                idf_path=ref_idf_path, epw_path=epw_path, output_dir=ref_output_dir,
            )
            try:
                ref_result = run_simulation(
                    ref_request, config,
                    stdout_callback=lambda line: click.echo(f"   EP> {line}", nl=False),
                )
            except Exception as exc:
                click.echo(f"   Reference box {floor_type}/{orientation_label} failed: {exc}", err=True)
                sys.exit(1)

            ref_metrics = extract_metrics(ref_result.sql_path)
            hvac_thermal_kwh = ref_metrics.end_uses.heating_kwh + ref_metrics.end_uses.cooling_kwh
            hvac_per_orientation.append(hvac_thermal_kwh)
            click.echo(
                f"   [{floor_type}/{orientation_label}] HVAC: {hvac_thermal_kwh:.1f} kWh "
                f"({hvac_thermal_kwh / REFERENCE_BOX_AREA_M2:.2f} kWh/m²)"
            )

        avg_hvac_kwh = sum(hvac_per_orientation) / len(hvac_per_orientation)
        ep_ref_by_floor_type[floor_type] = avg_hvac_kwh / cop / REFERENCE_BOX_AREA_M2
        ref_hvac_by_floor_type[floor_type] = dict(zip(orientations.keys(), hvac_per_orientation))
        click.echo(f"   EPref({floor_type}) = {ep_ref_by_floor_type[floor_type]:.2f} kWh/m²/yr")

    for flat in flats:
        if flat.floor_area_m2 <= 0:
            continue
        base_epref = ep_ref_by_floor_type.get(flat.floor_type, 0.0)
        # Middle-floor small units get the SI 5282 Annex ג small-unit multiplier
        if flat.floor_type == "middle" and flat.floor_area_m2 <= SMALL_UNIT_THRESHOLD_M2:
            ep_ref_by_flat_id[flat.flat_id] = base_epref * SMALL_UNIT_FACTOR
        else:
            ep_ref_by_flat_id[flat.flat_id] = base_epref

    return ep_ref_by_floor_type, ep_ref_by_flat_id, ref_hvac_by_floor_type


def _print_rating_table(unit_ratings: list, ep_des_kwh_m2: float,
                         ep_ref_kwh_m2: float, ip_percent: float,
                         grade_info: dict, zone: str, conditioned_area_m2: float) -> None:
    """Print building-level and per-unit rating summary to console."""
    click.echo("=" * 80)
    click.echo("SI 5282 PART 1 RESIDENTIAL ENERGY RATING")
    click.echo("=" * 80)
    click.echo(f"\nClimate Zone: {zone}")
    click.echo(f"Conditioned Area: {conditioned_area_m2:.1f} m²\n")
    click.echo(f"EPdes (proposed HVAC/COP/area):  {ep_des_kwh_m2:8.2f} kWh/m²/yr")
    click.echo(f"EPref (reference box avg/COP):   {ep_ref_kwh_m2:8.2f} kWh/m²/yr")
    click.echo(f"\nIMPROVEMENT PERCENTAGE (IP): {ip_percent:+.1f}%")
    click.echo(f"GRADE: {grade_info['grade']} ({grade_info['name_en']} / {grade_info['name_he']})")

    if not unit_ratings:
        return

    click.echo(f"\n{'─'*80}")
    click.echo(f"PER-UNIT RATINGS ({len(unit_ratings)} units)")
    click.echo(f"{'─'*80}")
    click.echo(f"{'Unit':<12} {'Floor':<7} {'Type':<8} {'Area':>6} {'EPdes':>7} {'EPref':>7} {'IP%':>7} {'Grade':<8}")
    click.echo(f"{'─'*80}")
    grade_counts: dict = {}
    for unit_rating in unit_ratings:
        grade_letter = unit_rating['grade']['grade']
        grade_counts[grade_letter] = grade_counts.get(grade_letter, 0) + 1
        click.echo(
            f"{unit_rating['flat_id']:<12} {str(unit_rating['floor_number']):<7} "
            f"{unit_rating['floor_type']:<8} {unit_rating['area_m2']:>6.1f} "
            f"{unit_rating['ep_des_kwh_m2']:>7.2f} {unit_rating['ep_ref_kwh_m2']:>7.2f} "
            f"{unit_rating['ip_percent']:>+7.1f} {grade_letter:<8}"
        )
    click.echo(f"{'─'*80}")
    click.echo("Grade distribution: " + "  ".join(
        f"{grade}:{count}" for grade, count in sorted(grade_counts.items())
    ))


def _generate_all_reports(
    rating_result: dict,
    proposed_metrics,
    flats,
    idf_preprocessed: str,
    idf_path: Path,
    output_dir: Path,
    project_name: str,
    zone: str,
    proposed_sql_path: Path,
) -> None:
    """Generate PDF report, H-value compliance, SI 1045, and IDF object reports."""
    # Professional PDF report
    click.echo("\n6. Generating professional report...")
    try:
        report_paths = generate_residential_report(
            rating_result=rating_result,
            output=proposed_metrics,
            output_dir=output_dir,
            project_name=project_name,
        )
        click.echo(f"   ✓ {report_paths['report_md'].name}")
        click.echo(f"   ✓ {report_paths['units_csv'].name}")
        click.echo(f"   ✓ {report_paths['windows_csv'].name}")
        if "report_pdf" in report_paths:
            click.echo(f"   ✓ {report_paths['report_pdf'].name}")
    except Exception as exc:
        click.echo(f"   Report generation failed: {exc}", err=True)

    # Envelope H-indicator compliance
    click.echo("\n7. Generating ReportH (envelope H-value compliance)...")
    try:
        from il_energy.envelope.idf_surface_parser import parse_frame_conductances
        from il_energy.envelope.h_value import compute_h_value_units
        from il_energy.envelope.report_h import generate_report_h

        frame_conductances = parse_frame_conductances(idf_preprocessed)
        click.echo(f"   Frame conductances parsed: {len(frame_conductances)} entries")

        h_units = compute_h_value_units(
            proposed_metrics, flats, frame_conductances, building_type="new",
        )
        pass_count = sum(1 for h_unit in h_units if h_unit.passes)
        click.echo(f"   H-value units computed: {len(h_units)}  Pass: {pass_count}  Fail: {len(h_units) - pass_count}")

        h_paths = generate_report_h(
            h_units, output_dir=output_dir, project_name=project_name,
            climate_zone=zone, building_type="new",
        )
        click.echo(f"   ✓ {h_paths['h_values_csv'].name}")
        if "report_h_pdf" in h_paths:
            click.echo(f"   ✓ {h_paths['report_h_pdf'].name}")
        else:
            click.echo(f"   ✓ {h_paths['report_h_html'].name} (HTML only — install WeasyPrint for PDF)")
    except Exception as exc:
        click.echo(f"   ReportH generation failed: {exc}", err=True)

    # SI 1045 thermal insulation report
    click.echo("\n8. Generating Report 1045 (SI 1045 thermal insulation)...")
    try:
        from il_energy.simulation.sql_parser import SQLParser
        from il_energy.envelope.report_1045 import generate_report_1045

        with SQLParser(proposed_sql_path) as parser:
            assemblies = parser.parse_construction_assemblies()
        click.echo(f"   Construction assemblies parsed: {len(assemblies)}")

        r1045_paths = generate_report_1045(
            assemblies, output_dir=output_dir, project_name=project_name, climate_zone=zone,
        )
        key = "pdf" if "pdf" in r1045_paths else "html"
        suffix = "" if key == "pdf" else " (HTML only)"
        click.echo(f"   ✓ {r1045_paths[key].name}{suffix}")
    except Exception as exc:
        click.echo(f"   Report 1045 generation failed: {exc}", err=True)

    # Full IDF object reports (Evergreen-parity)
    click.echo("\n9. Generating full IDF object reports...")
    try:
        import shutil
        from il_energy.simulation.idf_object_parser import extract_idf_version, parse_idf_objects
        from il_energy.report.idf_object_report import generate_all_idf_object_reports

        idf_objects = parse_idf_objects(idf_preprocessed)
        idf_version = extract_idf_version(idf_preprocessed)
        full_dir = output_dir / "full"
        generated = generate_all_idf_object_reports(
            idf_objects, output_dir=full_dir,
            idf_filename=idf_path.name, idf_version=idf_version,
        )
        click.echo(f"   {len(generated)} IDF object reports written to: {full_dir}")

        results_pdf = output_dir / "residential_report.pdf"
        if results_pdf.exists():
            shutil.copy2(results_pdf, full_dir / "_Results.pdf")
            click.echo("   ✓ _Results.pdf")
    except Exception as exc:
        click.echo(f"   Full IDF object reports failed: {exc}", err=True)


@main.command("compare-residential")
@click.option("--idf", required=True, type=click.Path(exists=True), help="Proposed building IDF")
@click.option("--epw", required=True, type=click.Path(exists=True), help="EPW weather file")
@click.option("--output-dir", required=True, type=click.Path(), help="Output directory")
@click.option("--zone", default=None, help="SI 5282 climate zone (A/B/C). Auto-detected from EPW if omitted.")
@click.option("--simulate-epref", is_flag=True, default=False,
              help="Force reference-box simulation for EPref instead of tabulated values.")
def compare_residential(idf: str, epw: str, output_dir: str, zone: str, simulate_epref: bool):
    """SI 5282 Part 1 residential comparison using the standard reference unit.

    EPref(ft) = average(HVAC_N + E + S + W) / 4 / 100 m² / COP(3.0)
    EPdes     = (zone_cooling + zone_heating) / COP / conditioned_area
    IP        = (EPref - EPdes) / EPref × 100%
    """
    idf_path = Path(idf).resolve()
    epw_path = Path(epw).resolve()
    output_dir_path = Path(output_dir).resolve()
    output_dir_path.mkdir(parents=True, exist_ok=True)

    if zone is None:
        zone = detect_zone_from_epw(epw_path)
        click.echo(f"Climate zone auto-detected from EPW: {zone}")

    click.echo(f"SI 5282 Part 1 Residential Comparison (Zone {zone})")
    click.echo(f"  Proposed IDF: {idf_path}")
    click.echo(f"  Weather: {epw_path}")
    click.echo(f"  Output: {output_dir_path}\n")

    try:
        config = EnergyPlusConfig()
    except Exception as exc:
        click.echo(f"Configuration error: {exc}", err=True)
        sys.exit(1)

    # ── 1. Apply SI 5282 reference conditions ────────────────────────────────
    click.echo("1. Applying SI 5282 reference operating conditions...")
    idf_preprocessed, preprocessed_idf_path = _preprocess_proposed_idf(idf_path, output_dir_path)

    # ── 2. Run proposed simulation + aggregate zones to flats ────────────────
    click.echo("2. Running proposed building simulation (with SI 5282 conditions)...")
    proposed_result, proposed_metrics, flats, ep_des_kwh_m2, conditioned_area_m2 = (
        _run_proposed_and_aggregate(preprocessed_idf_path, epw_path, output_dir_path, config, DEFAULT_COP)
    )

    # ── 3. Compute EPref (tabulated or reference-box simulation) ─────────────
    from il_energy import STANDARDS_DIR
    with open(STANDARDS_DIR / "ep_ref_values.json", encoding="utf-8") as epref_file:
        ep_ref_data = json.load(epref_file)
    zone_table = (ep_ref_data.get("zones") or {}).get(zone)

    ref_hvac_by_floor_type: dict = {}

    if zone_table and not simulate_epref:
        click.echo(f"3. Using tabulated EPref values for Zone {zone} (SI 5282 Part 1)...")
        ep_ref_by_floor_type, ep_ref_by_flat_id = _compute_epref_tabulated(zone_table, flats)
    else:
        ep_ref_by_floor_type, ep_ref_by_flat_id, ref_hvac_by_floor_type = (
            _compute_epref_by_simulation(flats, zone, epw_path, output_dir_path, config, DEFAULT_COP)
        )

    ep_ref_kwh_m2 = ep_ref_by_floor_type.get("middle", 0.0)
    click.echo(f"\n   EPref building-level (middle floor): {ep_ref_kwh_m2:.2f} kWh/m²/yr\n")

    # ── 4 & 5. Building-level + per-unit ratings ──────────────────────────────
    ip_percent = compute_ip(ep_des_kwh_m2, ep_ref_kwh_m2)
    grade_info = grade_from_ip(ip_percent)
    unit_ratings = compute_unit_ratings(
        flats, ep_ref_by_floor_type, cop=DEFAULT_COP, ep_ref_by_flat_id=ep_ref_by_flat_id,
    )
    _print_rating_table(unit_ratings, ep_des_kwh_m2, ep_ref_kwh_m2, ip_percent,
                        grade_info, zone, conditioned_area_m2)

    # ── Write JSON results ────────────────────────────────────────────────────
    rating_result = {
        "standard": "SI 5282 Part 1",
        "climate_zone": zone,
        "conditioned_area_m2": conditioned_area_m2,
        "ep_des_kwh_m2": ep_des_kwh_m2,
        "ep_ref_kwh_m2": ep_ref_kwh_m2,
        "ep_ref_by_floor_type": ep_ref_by_floor_type,
        "ip_percent": ip_percent,
        "grade": grade_info,
        "ref_box_hvac_by_floor_type": ref_hvac_by_floor_type,
        "ep_ref_by_flat_id": ep_ref_by_flat_id,
        "cop": DEFAULT_COP,
        "unit_ratings": unit_ratings,
        "notes": [
            "EPdes = (cooling + heating kWh) / COP / conditioned area",
            "EPref = average of 4 orientations (N/E/S/W) / COP / unit_area",
            "Building-level EPref uses middle floor type at representative area",
            "Reference unit per SI 5282 Part 1 Appendix ג, Table ג-1",
        ],
    }
    json_path = output_dir_path / "residential_rating.json"
    with open(json_path, "w", encoding="utf-8") as json_file:
        json.dump(rating_result, json_file, indent=2, default=str)
    click.echo(f"\nResults written to: {json_path}")

    run_info = {
        "run_timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "standard": "SI 5282 Part 1 (2024)",
        "climate_zone": zone,
        "idf": str(idf_path),
        "epw": str(epw_path),
        "energyplus_version": "25.2",
        "grade": grade_info["grade"],
        "ep_des_kwh_m2": round(ep_des_kwh_m2, 2),
        "ep_ref_kwh_m2": round(ep_ref_kwh_m2, 2),
        "ip_percent": round(ip_percent, 1),
    }
    with open(output_dir_path / "run_info.json", "w", encoding="utf-8") as json_file:
        json.dump(run_info, json_file, indent=2)

    # ── 6–9. Generate all reports ─────────────────────────────────────────────
    project_name = idf_path.stem
    _generate_all_reports(
        rating_result, proposed_metrics, flats, idf_preprocessed,
        idf_path, output_dir_path, project_name, zone, proposed_result.sql_path,
    )


if __name__ == "__main__":
    main()
