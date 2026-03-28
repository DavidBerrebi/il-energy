"""CLI entry point for il-energy."""

from __future__ import annotations

import json
import re
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


# Reference window material values per SI 5282 Part 1, Table ג-1
_REF_WINDOW_U = {"A": 4.0, "B": 4.0, "C": 4.0}    # W/m²K
_REF_WINDOW_SHGC = {"A": 0.63, "B": 0.63, "C": 0.63}  # Solar Heat Gain Coefficient


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


@main.command("compare-residential")
@click.option("--idf", required=True, type=click.Path(exists=True), help="Proposed building IDF")
@click.option("--epw", required=True, type=click.Path(exists=True), help="EPW weather file")
@click.option("--output-dir", required=True, type=click.Path(), help="Output directory")
@click.option("--zone", default=None, help="SI 5282 climate zone (A/B/C). Auto-detected from EPW if omitted.")
@click.option("--simulate-epref", is_flag=True, default=False,
              help="Force reference-box simulation for EPref instead of tabulated values.")
def compare_residential(idf: str, epw: str, output_dir: str, zone: str, simulate_epref: bool):
    """SI 5282 Part 1 residential comparison using the standard reference unit.

    Runs the proposed building simulation and the standardized 100 m² reference
    box (3 floor types × 4 orientations = 12 runs), computes EPref per floor type
    and EPdes as HVAC-thermal / COP, then calculates IP and energy grade.

    EPref(ft) = average(HVAC_thermal_N + E + S + W) / 4 / 100 m² / COP(3.0)
    EPdes = (proposed_cooling + proposed_heating) / COP / conditioned_area
    IP    = (EPref - EPdes) / EPref * 100 %
    """
    COP = 3.0

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

    # Compute EPdes from zone-level sensible HVAC (sensible-only, per SI 5282).
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

    # ── 2b. Aggregate zones to flats early — needed for per-unit EPref ───────
    flats = aggregate_zones_to_flats(proposed_metrics.zones)
    # Apply roof-ratio override BEFORE EPref lookup so penthouse/setback units
    # get the correct "top" EPref rather than the "middle" value.
    override_floor_types_from_surfaces(flats, proposed_metrics.envelope_opaque)

    # ── 3. EPref — tabulated (Zone B) or reference-box simulation (Zones A/C) ─
    ep_ref_values_path = Path(__file__).parent.parent.parent / "standards" / "si5282" / "ep_ref_values.json"
    with open(ep_ref_values_path, encoding="utf-8") as _f:
        _ep_ref_data = json.load(_f)
    zone_table = (_ep_ref_data.get("zones") or {}).get(zone)

    ep_ref_by_flat_id: dict = {}
    ep_ref_by_floor_type: dict = {}
    ref_hvac_by_ft: dict = {}

    if zone_table and not simulate_epref:
        # ── Tabulated EPref for Zone B (per SI 5282 Part 1, 2024 amendment) ──
        click.echo(f"3. Using tabulated EPref values for Zone {zone} (SI 5282 Part 1)...")
        threshold = zone_table.get("small_unit_threshold_m2", 50)
        for ft in ("ground", "middle", "top"):
            ft_data = zone_table.get(ft)
            if not ft_data:
                continue
            ep_ref_by_floor_type[ft] = ft_data.get("standard", 0.0)
        for flat in flats:
            if flat.floor_area_m2 <= 0:
                continue
            ft_data = zone_table.get(flat.floor_type) or {}
            if flat.floor_area_m2 <= threshold and "small_le50m2" in ft_data:
                ep_ref_by_flat_id[flat.flat_id] = ft_data["small_le50m2"]
            else:
                ep_ref_by_flat_id[flat.flat_id] = ft_data.get("standard", 0.0)
        for ft, val in ep_ref_by_floor_type.items():
            click.echo(f"   EPref({ft}) = {val:.2f} kWh/m²/yr  [tabulated]")
    else:
        # ── Reference-box simulation: 3 floor types × 4 orientations = 12 runs ─
        # Use fixed 100 m² standard box (SI 5282 Appendix ג).
        # Small units (≤50 m²) also run a 50 m² box to get a size-corrected EPref.
        orientations = {"S": 0.0, "W": 90.0, "N": 180.0, "E": 270.0}
        floor_types = sorted({f.floor_type for f in flats if f.floor_area_m2 > 0})
        SMALL_THRESHOLD = 50.0
        BOX_STANDARD = 100.0
        BOX_SMALL = 50.0
        has_small = any(f.floor_area_m2 <= SMALL_THRESHOLD for f in flats if f.floor_area_m2 > 0)
        box_sizes = [BOX_STANDARD] + ([BOX_SMALL] if has_small else [])
        n_runs = len(floor_types) * len(box_sizes) * 4
        click.echo(f"3. Running reference boxes — {len(floor_types)} floor types "
                   f"× {len(box_sizes)} sizes × 4 orientations = {n_runs} runs...")

        # ep_ref_cache[(floor_type, box_size)] → EPref kWh/m²/yr
        ep_ref_cache: dict[tuple, float] = {}

        for ft in floor_types:
            for box_area in box_sizes:
                size_label = f"{int(box_area)}m2"
                hvac_vals = []
                for label, north_axis in orientations.items():
                    ref_idf_path = out_path / f"refbox_{ft}_{size_label}_{label}.idf"
                    ref_out_dir  = out_path / f"refbox_{ft}_{size_label}_{label}"
                    generate_reference_box_idf(ref_idf_path, climate_zone=zone,
                                               north_axis_deg=north_axis, floor_type=ft,
                                               floor_area_m2=box_area)
                    req = SimulationRequest(idf_path=ref_idf_path, epw_path=epw_path,
                                           output_dir=ref_out_dir)
                    try:
                        res = run_simulation(req, config)
                    except Exception as e:
                        click.echo(f"   Reference box {ft}/{size_label}/{label} failed: {e}", err=True)
                        sys.exit(1)
                    m = extract_metrics(res.sql_path)
                    hvac_thermal = m.end_uses.heating_kwh + m.end_uses.cooling_kwh
                    hvac_vals.append(hvac_thermal)
                    click.echo(f"   [{ft}/{size_label}/{label}] HVAC: {hvac_thermal:.1f} kWh "
                               f"({hvac_thermal / box_area:.2f} kWh/m²)")
                avg_hvac = sum(hvac_vals) / len(hvac_vals)
                ep_ref_cache[(ft, box_area)] = avg_hvac / COP / box_area
                ref_hvac_by_ft[f"{ft}_{size_label}"] = dict(zip(orientations.keys(), hvac_vals))
                click.echo(f"   EPref({ft}, {size_label}) = {ep_ref_cache[(ft, box_area)]:.2f} kWh/m²/yr")

        # Build per-flat EPref: small units use the 50 m² box, others use 100 m²
        for flat in flats:
            if flat.floor_area_m2 <= 0:
                continue
            box_size = BOX_SMALL if (has_small and flat.floor_area_m2 <= SMALL_THRESHOLD) else BOX_STANDARD
            ep_ref_by_flat_id[flat.flat_id] = ep_ref_cache[(flat.floor_type, box_size)]

        # Floor-type EPref for building-level display (standard 100 m² box)
        for ft in floor_types:
            ep_ref_by_floor_type[ft] = ep_ref_cache[(ft, BOX_STANDARD)]

    ep_ref = ep_ref_by_floor_type.get("middle", 0.0)
    click.echo(f"\n   EPref building-level (middle floor): {ep_ref:.2f} kWh/m²/yr\n")

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
    unit_ratings = compute_unit_ratings(
        flats, ep_ref_by_floor_type, cop=COP, ep_ref_by_flat_id=ep_ref_by_flat_id
    )

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
        "ep_ref_by_flat_id": ep_ref_by_flat_id,
        "cop": COP,
        "unit_ratings": unit_ratings,
        "notes": [
            "EPdes = (cooling + heating kWh) / COP / conditioned area",
            "EPref = average of 4 orientations (N/E/S/W) / COP / unit_area — run per flat area",
            "Building-level EPref uses middle floor type at representative area",
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
