"""Tests for the normalizer module."""

import pytest

from il_energy.models import EnergyEndUse, NormalizedMetrics
from il_energy.postprocessing.normalizer import compute_normalized_metrics, joules_to_kwh, gj_to_kwh


class TestUnitConversion:
    def test_joules_to_kwh(self):
        assert joules_to_kwh(3_600_000) == pytest.approx(1.0)
        assert joules_to_kwh(0) == 0.0

    def test_gj_to_kwh(self):
        assert gj_to_kwh(1.0) == pytest.approx(277.778, abs=0.01)
        assert gj_to_kwh(0) == 0.0


class TestNormalizedMetrics:
    def test_basic_normalization(self):
        end_uses = EnergyEndUse(
            heating_kwh=1000.0,
            cooling_kwh=2000.0,
            interior_lighting_kwh=500.0,
            exterior_lighting_kwh=100.0,
            interior_equipment_kwh=300.0,
            total_kwh=3900.0,
        )
        result = compute_normalized_metrics(end_uses, 100.0)

        assert result.total_eui_kwh_m2 == pytest.approx(39.0)
        assert result.heating_eui_kwh_m2 == pytest.approx(10.0)
        assert result.cooling_eui_kwh_m2 == pytest.approx(20.0)
        assert result.lighting_eui_kwh_m2 == pytest.approx(6.0)
        assert result.equipment_eui_kwh_m2 == pytest.approx(3.0)

    def test_zero_area_returns_zeros(self):
        end_uses = EnergyEndUse(total_kwh=1000.0)
        result = compute_normalized_metrics(end_uses, 0.0)
        assert result.total_eui_kwh_m2 == 0.0

    def test_negative_area_returns_zeros(self):
        end_uses = EnergyEndUse(total_kwh=1000.0)
        result = compute_normalized_metrics(end_uses, -1.0)
        assert result.total_eui_kwh_m2 == 0.0
