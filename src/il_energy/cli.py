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
    # Derive dominant glazing orientation per flat from window azimuths.
    assign_orientations_from_windows(flats, proposed_metrics.envelope_windows)

    # ── 3. EPref — tabulated (Zone B) or reference-box simulation (Zones A/C) ─
    ep_ref_values_path = Path(__file__).parent.parent.parent / "standards" / "si5282" / "ep_ref_values.json"
    with open(ep_ref_values_path, encoding="utf-8") as _f:
        _ep_ref_data = json.load(_f)
    zone_table = (_ep_ref_data.get("zones") or {}).get(zone)

    ep_ref_by_flat_id: dict = {}
    ep_ref_by_floor_type: dict = {}
    ref_hvac_by_ft: dict = {}

    if zone_table and not simulate_epref:
        # ── Tabulated EPref (per SI 5282 Part 1, 2024 amendment) ──
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
        # SI 5282 Appendix ג defines the reference unit as a fixed 100 m² box.
        # Small units (≤50 m²) are not simulated separately; instead a standard-defined
        # multiplier is applied to the 100 m² EPref.  Simulating a 50 m² box gives
        # incorrect results because occupancy is fixed at 4 persons (per Table ג-2),
        # doubling occupant density and artificially inflating EPref.
        #
        # Small-unit multiplier for middle-floor units (≤50 m²):
        #   1.18 = 44.89 / 38.04  (SI 5282 Part 1, 2024, Annex ג tabulated values)
        SMALL_THRESHOLD = 50.0
        SMALL_UNIT_FACTOR = 44.89 / 38.04  # applies to middle-floor only
        BOX_STANDARD = 100.0
        orientations = {"S": 0.0, "W": 90.0, "N": 180.0, "E": 270.0}
        floor_types = sorted({f.floor_type for f in flats if f.floor_area_m2 > 0})
        n_runs = len(floor_types) * 4
        click.echo(f"3. Running reference boxes — {len(floor_types)} floor types "
                   f"× 4 orientations = {n_runs} runs (100 m² fixed box per SI 5282 Appendix ג)...")

        # ep_ref_cache[floor_type] → EPref kWh/m²/yr  (100 m² box)
        ep_ref_cache: dict[str, float] = {}

        for ft in floor_types:
            hvac_vals = []
            for label, north_axis in orientations.items():
                ref_idf_path = out_path / "reference_boxes" / f"refbox_{ft}_{label}.idf"
                ref_out_dir  = out_path / "reference_boxes" / f"refbox_{ft}_{label}"
                ref_idf_path.parent.mkdir(parents=True, exist_ok=True)
                generate_reference_box_idf(ref_idf_path, climate_zone=zone,
                                           north_axis_deg=north_axis, floor_type=ft,
                                           floor_area_m2=BOX_STANDARD)
                req = SimulationRequest(idf_path=ref_idf_path, epw_path=epw_path,
                                        output_dir=ref_out_dir)
                try:
                    res = run_simulation(req, config)
                except Exception as e:
                    click.echo(f"   Reference box {ft}/{label} failed: {e}", err=True)
                    sys.exit(1)
                m = extract_metrics(res.sql_path)
                hvac_thermal = m.end_uses.heating_kwh + m.end_uses.cooling_kwh
                hvac_vals.append(hvac_thermal)
                click.echo(f"   [{ft}/{label}] HVAC: {hvac_thermal:.1f} kWh "
                           f"({hvac_thermal / BOX_STANDARD:.2f} kWh/m²)")
            avg_hvac = sum(hvac_vals) / len(hvac_vals)
            ep_ref_cache[ft] = avg_hvac / COP / BOX_STANDARD
            ref_hvac_by_ft[ft] = dict(zip(orientations.keys(), hvac_vals))
            click.echo(f"   EPref({ft}) = {ep_ref_cache[ft]:.2f} kWh/m²/yr")

        # Build per-flat EPref; middle-floor small units (≤50 m²) get a multiplier
        for flat in flats:
            if flat.floor_area_m2 <= 0:
                continue
            base_epref = ep_ref_cache.get(flat.floor_type, 0.0)
            if flat.floor_type == "middle" and flat.floor_area_m2 <= SMALL_THRESHOLD:
                ep_ref_by_flat_id[flat.flat_id] = base_epref * SMALL_UNIT_FACTOR
            else:
                ep_ref_by_flat_id[flat.flat_id] = base_epref

        # Floor-type EPref for building-level display (100 m² box, no small-unit adjustment)
        for ft in floor_types:
            ep_ref_by_floor_type[ft] = ep_ref_cache[ft]

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

    # Write run metadata for traceability
    run_info = {
        "run_timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "standard": "SI 5282 Part 1 (2024)",
        "climate_zone": zone,
        "idf": str(idf_path),
        "epw": str(epw_path),
        "energyplus_version": "25.2",
        "grade": grade_info["grade"],
        "ep_des_kwh_m2": round(ep_des, 2),
        "ep_ref_kwh_m2": round(ep_ref, 2),
        "ip_percent": round(ip_percent, 1),
    }
    with open(out_path / "run_info.json", "w", encoding="utf-8") as f:
        json.dump(run_info, f, indent=2)

    # ── 6. Professional report ────────────────────────────────────────────────
    click.echo("\n6. Generating professional report...")
    project_name = idf_path.stem
    try:
        report_paths = generate_residential_report(
            rating_result=result,
            output=proposed_metrics,
            output_dir=out_path,
            project_name=project_name,
        )
        click.echo(f"   ✓ {report_paths['report_md'].name}")
        click.echo(f"   ✓ {report_paths['units_csv'].name}")
        click.echo(f"   ✓ {report_paths['windows_csv'].name}")
        if "report_pdf" in report_paths:
            click.echo(f"   ✓ {report_paths['report_pdf'].name}")
    except Exception as e:
        click.echo(f"   Report generation failed: {e}", err=True)

    # ── 7. ReportH — envelope H-indicator compliance ──────────────────────────
    click.echo("\n7. Generating ReportH (envelope H-value compliance)...")
    try:
        from il_energy.envelope.idf_surface_parser import parse_frame_conductances
        from il_energy.envelope.h_value import compute_h_value_units
        from il_energy.envelope.report_h import generate_report_h

        frame_conds = parse_frame_conductances(idf_preprocessed)
        click.echo(f"   Frame conductances parsed: {len(frame_conds)} entries")

        h_units = compute_h_value_units(
            proposed_metrics, flats, frame_conds, building_type="new"
        )
        click.echo(f"   H-value units computed: {len(h_units)}")
        pass_n = sum(1 for hu in h_units if hu.passes)
        fail_n = len(h_units) - pass_n
        click.echo(f"   Pass: {pass_n}  Fail: {fail_n}")

        h_paths = generate_report_h(
            h_units,
            output_dir=out_path,
            project_name=project_name,
            climate_zone=zone,
            building_type="new",
        )
        click.echo(f"   ✓ {h_paths['h_values_csv'].name}")
        if "report_h_pdf" in h_paths:
            click.echo(f"   ✓ {h_paths['report_h_pdf'].name}")
        else:
            click.echo(f"   ✓ {h_paths['report_h_html'].name} (HTML only — install WeasyPrint for PDF)")
    except Exception as e:
        click.echo(f"   ReportH generation failed: {e}", err=True)

    # ── 8. Report 1045 — SI 1045 construction thermal insulation ─────────────
    click.echo("\n8. Generating Report 1045 (SI 1045 thermal insulation)...")
    try:
        from il_energy.simulation.sql_parser import SQLParser
        from il_energy.envelope.report_1045 import generate_report_1045

        with SQLParser(proposed_result.sql_path) as parser:
            assemblies = parser.parse_construction_assemblies()
        click.echo(f"   Construction assemblies parsed: {len(assemblies)}")

        r1045_paths = generate_report_1045(
            assemblies,
            output_dir=out_path,
            project_name=project_name,
            climate_zone=zone,
        )
        if "pdf" in r1045_paths:
            click.echo(f"   \u2713 {r1045_paths['pdf'].name}")
        else:
            click.echo(f"   \u2713 {r1045_paths['html'].name} (HTML only)")
    except Exception as e:
        click.echo(f"   Report 1045 generation failed: {e}", err=True)

    # ── 9. Full IDF object reports (Evergreen-parity) ─────────────────────────
    click.echo("\n9. Generating full IDF object reports...")
    try:
        from il_energy.simulation.idf_object_parser import parse_idf_objects, extract_idf_version
        from il_energy.report.idf_object_report import generate_all_idf_object_reports
        import shutil

        idf_objects = parse_idf_objects(idf_preprocessed)
        idf_version = extract_idf_version(idf_preprocessed)
        idf_filename = idf_path.name

        full_dir = out_path / "full"
        generated = generate_all_idf_object_reports(
            idf_objects,
            output_dir=full_dir,
            idf_filename=idf_filename,
            idf_version=idf_version,
        )
        click.echo(f"   {len(generated)} IDF object reports written to: {full_dir}")

        # Copy residential_report.pdf as _Results.pdf into full/
        results_src = out_path / "residential_report.pdf"
        if results_src.exists():
            shutil.copy2(results_src, full_dir / "_Results.pdf")
            click.echo(f"   ✓ _Results.pdf")
    except Exception as e:
        click.echo(f"   Full IDF object reports failed: {e}", err=True)


if __name__ == "__main__":
    main()
