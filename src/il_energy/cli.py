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


if __name__ == "__main__":
    main()
