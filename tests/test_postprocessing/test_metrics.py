"""Tests for the metrics extraction module."""

from il_energy.postprocessing.metrics import extract_metrics


class TestExtractMetrics:
    def test_extract_from_fixture(self, sample_sql_path):
        output = extract_metrics(sample_sql_path)

        assert output.site_energy_kwh > 0
        assert output.building_area.total_m2 > 0
        assert len(output.envelope_opaque) == 5
        assert len(output.zones) == 1
        assert output.metadata.ep_version != ""
