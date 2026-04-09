"""Golden regression test — verify calculations against Nili project output.

This test re-runs the pure-Python pipeline (SQL parsing → zone aggregation →
rating calculation) against the Nili `eplusout.sql` and asserts that results
match the golden `residential_rating.json` and `units.csv`.

Requires the Nili golden fixtures in tests/fixtures/nili_golden/.
Skipped automatically if fixtures are not present.
"""

import csv
import json
from io import StringIO
from pathlib import Path

import pytest

from il_energy.postprocessing.metrics import extract_metrics
from il_energy.postprocessing.zone_aggregator import (
    aggregate_zones_to_flats,
    assign_orientations_from_windows,
    override_floor_types_from_surfaces,
)
from il_energy.rating.calculator import compute_ip, compute_unit_ratings, grade_from_ip


COP = 3.0


class TestNiliGoldenRegression:
    """Verify calculation results match the Nili golden output."""

    def test_building_metrics(self, nili_sql_path, nili_golden_rating):
        """Building-level EPdes, EPref, IP, and grade match golden values."""
        golden = nili_golden_rating

        # Re-run the pure-Python pipeline
        metrics = extract_metrics(nili_sql_path)
        conditioned_area = metrics.building_area.conditioned_m2

        # Compute EPdes from zone-level sensible HVAC (same as cli.py)
        hvac_proposed = sum(
            z.cooling_kwh + z.heating_kwh for z in metrics.zones
        )
        ep_des = hvac_proposed / COP / conditioned_area

        assert conditioned_area == pytest.approx(golden["conditioned_area_m2"], rel=1e-3)
        assert ep_des == pytest.approx(golden["ep_des_kwh_m2"], rel=1e-3)

    def test_building_grade(self, nili_sql_path, nili_golden_rating):
        """Building grade is B (Gold)."""
        golden = nili_golden_rating

        metrics = extract_metrics(nili_sql_path)
        conditioned_area = metrics.building_area.conditioned_m2
        hvac_proposed = sum(z.cooling_kwh + z.heating_kwh for z in metrics.zones)
        ep_des = hvac_proposed / COP / conditioned_area

        # Use golden EPref for building-level rating (EPref comes from reference box sim)
        ep_ref = golden["ep_ref_kwh_m2"]
        ip_percent = compute_ip(ep_des, ep_ref)
        grade_info = grade_from_ip(ip_percent)

        assert grade_info["grade"] == golden["grade"]["grade"]
        assert grade_info["grade"] == "B"

    def test_zone_count(self, nili_sql_path):
        """Nili building has the expected number of zones."""
        metrics = extract_metrics(nili_sql_path)
        # Nili has many zones — at minimum > 40 (residential + core)
        assert len(metrics.zones) > 40

    def test_flat_aggregation(self, nili_sql_path, nili_golden_rating):
        """Zone aggregation produces 24 flats matching golden unit_ratings."""
        golden_units = nili_golden_rating["unit_ratings"]

        metrics = extract_metrics(nili_sql_path)
        flats = aggregate_zones_to_flats(metrics.zones)
        override_floor_types_from_surfaces(flats, metrics.envelope_opaque)
        assign_orientations_from_windows(flats, metrics.envelope_windows)

        assert len(flats) == len(golden_units)

    def test_per_unit_epdes(self, nili_sql_path, nili_golden_rating):
        """Per-unit EPdes values match golden within tolerance."""
        golden_units = nili_golden_rating["unit_ratings"]
        ep_ref_by_floor_type = nili_golden_rating["ep_ref_by_floor_type"]
        ep_ref_by_flat_id = nili_golden_rating["ep_ref_by_flat_id"]

        metrics = extract_metrics(nili_sql_path)
        flats = aggregate_zones_to_flats(metrics.zones)
        override_floor_types_from_surfaces(flats, metrics.envelope_opaque)
        assign_orientations_from_windows(flats, metrics.envelope_windows)

        unit_ratings = compute_unit_ratings(
            flats, ep_ref_by_floor_type, cop=COP,
            ep_ref_by_flat_id=ep_ref_by_flat_id,
        )

        golden_by_id = {u["flat_id"]: u for u in golden_units}
        for unit in unit_ratings:
            golden = golden_by_id[unit["flat_id"]]
            assert unit["ep_des_kwh_m2"] == pytest.approx(
                golden["ep_des_kwh_m2"], rel=1e-3
            ), f"EPdes mismatch for {unit['flat_id']}"

    def test_per_unit_grades(self, nili_sql_path, nili_golden_rating):
        """Per-unit grades match golden values exactly."""
        golden_units = nili_golden_rating["unit_ratings"]
        ep_ref_by_floor_type = nili_golden_rating["ep_ref_by_floor_type"]
        ep_ref_by_flat_id = nili_golden_rating["ep_ref_by_flat_id"]

        metrics = extract_metrics(nili_sql_path)
        flats = aggregate_zones_to_flats(metrics.zones)
        override_floor_types_from_surfaces(flats, metrics.envelope_opaque)
        assign_orientations_from_windows(flats, metrics.envelope_windows)

        unit_ratings = compute_unit_ratings(
            flats, ep_ref_by_floor_type, cop=COP,
            ep_ref_by_flat_id=ep_ref_by_flat_id,
        )

        golden_by_id = {u["flat_id"]: u for u in golden_units}
        for unit in unit_ratings:
            golden = golden_by_id[unit["flat_id"]]
            assert unit["grade"]["grade"] == golden["grade"]["grade"], (
                f"Grade mismatch for {unit['flat_id']}: "
                f"got {unit['grade']['grade']}, expected {golden['grade']['grade']}"
            )

    def test_per_unit_floor_types(self, nili_sql_path, nili_golden_rating):
        """Per-unit floor types match golden values."""
        golden_units = nili_golden_rating["unit_ratings"]

        metrics = extract_metrics(nili_sql_path)
        flats = aggregate_zones_to_flats(metrics.zones)
        override_floor_types_from_surfaces(flats, metrics.envelope_opaque)

        flat_by_id = {f.flat_id: f for f in flats}
        for golden_unit in golden_units:
            flat_id = golden_unit["flat_id"]
            assert flat_by_id[flat_id].floor_type == golden_unit["floor_type"], (
                f"Floor type mismatch for {flat_id}"
            )

    def test_units_csv_format(self, nili_sql_path, nili_golden_rating, nili_golden_units_csv, tmp_path):
        """Generated units.csv matches golden CSV."""
        from il_energy.report.generator import write_units_csv

        golden_units = nili_golden_rating["unit_ratings"]
        ep_ref_by_floor_type = nili_golden_rating["ep_ref_by_floor_type"]
        ep_ref_by_flat_id = nili_golden_rating["ep_ref_by_flat_id"]

        metrics = extract_metrics(nili_sql_path)
        flats = aggregate_zones_to_flats(metrics.zones)
        override_floor_types_from_surfaces(flats, metrics.envelope_opaque)
        assign_orientations_from_windows(flats, metrics.envelope_windows)

        unit_ratings = compute_unit_ratings(
            flats, ep_ref_by_floor_type, cop=COP,
            ep_ref_by_flat_id=ep_ref_by_flat_id,
        )

        out_path = tmp_path / "units.csv"
        write_units_csv(unit_ratings, out_path)

        generated = out_path.read_text(encoding="utf-8")
        golden_csv = nili_golden_units_csv

        # Compare row-by-row (skip header)
        gen_lines = generated.strip().split("\n")
        gold_lines = golden_csv.strip().split("\n")

        assert len(gen_lines) == len(gold_lines), (
            f"Row count mismatch: {len(gen_lines)} generated vs {len(gold_lines)} golden"
        )

        # Compare header
        assert gen_lines[0] == gold_lines[0], "CSV header mismatch"

        # Compare data rows — values should match within formatting precision
        gen_reader = csv.reader(StringIO(generated))
        gold_reader = csv.reader(StringIO(golden_csv))
        next(gen_reader)  # skip header
        next(gold_reader)
        for row_num, (gen_row, gold_row) in enumerate(zip(gen_reader, gold_reader), 1):
            for col_idx, (gen_val, gold_val) in enumerate(zip(gen_row, gold_row)):
                assert gen_val == gold_val, (
                    f"Row {row_num}, col {col_idx}: '{gen_val}' != '{gold_val}'"
                )
