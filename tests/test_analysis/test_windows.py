"""Tests for il_energy.analysis.windows."""

import csv
from io import StringIO
from pathlib import Path

import pytest

from il_energy.analysis.windows import (
    _flat_floor,
    _flat_unit_number,
    _orientation_label,
    build_window_records,
    window_summary_by_flat,
    write_windows_csv,
)
from il_energy.models import (
    BuildingArea,
    EnergyEndUse,
    EnvelopeSurface,
    SimulationOutput,
    WindowSurface,
    ZoneEnergy,
)


class TestOrientationLabel:
    """Test azimuth → 8-direction compass conversion."""

    def test_north(self):
        assert _orientation_label(0.0) == "N"
        assert _orientation_label(350.0) == "N"

    def test_northeast(self):
        assert _orientation_label(45.0) == "NE"

    def test_east(self):
        assert _orientation_label(90.0) == "E"

    def test_south(self):
        assert _orientation_label(180.0) == "S"

    def test_west(self):
        assert _orientation_label(270.0) == "W"

    def test_none_returns_empty(self):
        assert _orientation_label(None) == ""


class TestFlatHelpers:
    """Test flat_id parsing helpers."""

    def test_unit_number_nili(self):
        assert _flat_unit_number("00X1") == "1"
        assert _flat_unit_number("06X2") == "2"

    def test_flat_floor_nili(self):
        assert _flat_floor("00X1") == "00"
        assert _flat_floor("06X2") == "06"

    def test_unit_number_non_standard(self):
        assert _flat_unit_number("FF01") == "FF01"

    def test_flat_floor_non_standard(self):
        assert _flat_floor("FF01") == ""


class TestBuildWindowRecords:
    """Test window record construction from SimulationOutput."""

    def _make_output(self):
        return SimulationOutput(
            building_area=BuildingArea(total_m2=200.0, conditioned_m2=200.0),
            end_uses=EnergyEndUse(),
            zones=[
                ZoneEnergy(zone_name="00X1:LIVING", floor_area_m2=80.0),
                ZoneEnergy(zone_name="00X1:SERVICE", floor_area_m2=30.0),
            ],
            envelope_opaque=[
                EnvelopeSurface(
                    name="WALL1", zone="00X1:LIVING", adjacency="Exterior",
                    u_factor_w_m2k=1.2, gross_area_m2=20.0, tilt_deg=90.0,
                ),
            ],
            envelope_windows=[
                WindowSurface(
                    name="WIN1", zone="00X1:LIVING", construction="DblGlz",
                    glass_area_m2=4.0, u_factor_w_m2k=2.5, shgc=0.63,
                    visible_transmittance=0.61, azimuth_deg=180.0,
                ),
            ],
        )

    def test_produces_opaque_and_window_records(self):
        output = self._make_output()
        records = build_window_records(output)
        opaque = [r for r in records if not r["_is_window"]]
        windows = [r for r in records if r["_is_window"]]
        assert len(opaque) == 1
        assert len(windows) == 1

    def test_window_record_fields(self):
        output = self._make_output()
        records = build_window_records(output)
        win_rec = [r for r in records if r["_is_window"]][0]
        assert win_rec["Surface Name"] == "WIN1"
        assert win_rec["Construction"] == "DblGlz"
        assert win_rec["Um"] == "2.50"
        assert win_rec["Glass SHGC"] == "0.63"
        assert win_rec["Floor Name"] == "00"
        assert win_rec["Unit Name"] == "1"

    def test_wwr_calculation(self):
        output = self._make_output()
        records = build_window_records(output)
        win_rec = [r for r in records if r["_is_window"]][0]
        # Wall gross = 20.0, window glass = 4.0, total wall+window = 24.0
        # WWR = 4.0 / 24.0 ≈ 0.17 (rounded to 2 decimals in CSV)
        assert float(win_rec["WWR"]) == pytest.approx(4.0 / 24.0, abs=0.01)

    def test_sorted_by_flat_then_name(self):
        output = self._make_output()
        records = build_window_records(output)
        flat_ids = [r["_flat_id"] for r in records]
        names = [r["Surface Name"] for r in records]
        assert flat_ids == sorted(flat_ids)


class TestWindowSummaryByFlat:
    """Test per-flat window aggregation."""

    def test_area_weighted_averages(self):
        records = [
            {
                "_is_window": True, "_flat_id": "00X1",
                "Area (Net) {m2}": "4.00", "Um": "2.50", "Glass SHGC": "0.60",
                "Window Orientation": "180", "WWR": "0.20",
            },
            {
                "_is_window": True, "_flat_id": "00X1",
                "Area (Net) {m2}": "6.00", "Um": "3.00", "Glass SHGC": "0.70",
                "Window Orientation": "90", "WWR": "0.20",
            },
        ]
        summary = window_summary_by_flat(records)
        s = summary["00X1"]
        assert s["window_count"] == 2
        assert s["total_glass_area_m2"] == pytest.approx(10.0)
        # Area-weighted U = (2.5*4 + 3.0*6) / 10 = 2.8
        assert s["avg_u"] == pytest.approx(2.8)
        # Area-weighted SHGC = (0.6*4 + 0.7*6) / 10 = 0.66
        assert s["avg_shgc"] == pytest.approx(0.66)

    def test_opaque_records_excluded(self):
        records = [
            {"_is_window": False, "_flat_id": "00X1", "Area (Net) {m2}": "20.00"},
        ]
        summary = window_summary_by_flat(records)
        assert len(summary) == 0


class TestWriteWindowsCsv:
    """Test CSV output format."""

    def test_writes_correct_columns(self, tmp_path):
        records = [
            {
                "Floor Name": "00", "Unit Name": "1", "Unit Orientation": "",
                "Unit Area {m2}": "100.00", "Surface Name": "WIN1",
                "Construction": "DblGlz", "Adjacency": "Exterior",
                "Area (Net) {m2}": "4.00", "Um": "2.50",
                "Glass SHGC": "0.63", "Glass Visible Transmittance": "0.61",
                "Window Shading Control": "", "Window Orientation": "180",
                "WWR": "0.20", "_flat_id": "00X1", "_is_window": True,
            },
        ]
        out_path = tmp_path / "windows.csv"
        write_windows_csv(records, out_path)

        content = out_path.read_text(encoding="utf-8")
        reader = csv.DictReader(StringIO(content))
        rows = list(reader)
        assert len(rows) == 1
        assert rows[0]["Surface Name"] == "WIN1"
        # Internal fields should not appear
        assert "_flat_id" not in reader.fieldnames
        assert "_is_window" not in reader.fieldnames
