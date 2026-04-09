"""Tests for il_energy.simulation.idf_parser."""

import pytest
from pathlib import Path

from il_energy.simulation.idf_parser import _has_object, ensure_sql_output


class TestHasObject:
    """Test IDF object type detection."""

    def test_finds_output_sqlite(self):
        content = "Output:SQLite,\n  SimpleAndTabular;\n"
        assert _has_object(content, "Output:SQLite") is True

    def test_case_insensitive(self):
        content = "output:sqlite,\n  SimpleAndTabular;\n"
        assert _has_object(content, "Output:SQLite") is True

    def test_not_found(self):
        content = "Version, 25.2;\n"
        assert _has_object(content, "Output:SQLite") is False

    def test_ignores_comments(self):
        content = "! Output:SQLite,\n  SimpleAndTabular;\n"
        assert _has_object(content, "Output:SQLite") is False


class TestEnsureSqlOutput:
    """Test IDF preparation with output injection."""

    def test_injects_missing_objects(self, tmp_path):
        idf = tmp_path / "test.idf"
        idf.write_text("Version, 25.2;\n", encoding="utf-8")
        result = ensure_sql_output(idf)
        content = result.read_text(encoding="utf-8")
        assert "Output:SQLite" in content
        assert "Output:Table:SummaryReports" in content
        assert "Zone Ideal Loads Supply Air Sensible Heating Energy" in content
        assert "Zone Ideal Loads Supply Air Sensible Cooling Energy" in content
        # Should be a temp copy, not the original
        assert result != idf

    def test_preserves_existing_objects(self, tmp_path):
        idf = tmp_path / "test.idf"
        content = (
            "Version, 25.2;\n"
            "Output:SQLite,\n  SimpleAndTabular;\n"
            "Output:Table:SummaryReports,\n  AllSummary;\n"
            "OutputControl:Table:Style,\n  Comma;\n"
            "Output:Variable,*,Zone Ideal Loads Supply Air Sensible Heating Energy,Annual;\n"
            "Output:Variable,*,Zone Ideal Loads Supply Air Sensible Cooling Energy,Annual;\n"
        )
        idf.write_text(content, encoding="utf-8")
        result = ensure_sql_output(idf)
        # No modifications needed → returns original path
        assert result == idf

    def test_missing_file_raises(self, tmp_path):
        missing = tmp_path / "nonexistent.idf"
        with pytest.raises(Exception):
            ensure_sql_output(missing)

    def test_version_9_triggers_conversion(self, tmp_path):
        idf = tmp_path / "test.idf"
        idf.write_text("Version, 9.4;\n\nBuildingSurface:Detailed,\n  WALL1,\n  Wall,\n  Construction1,\n  ZONE1,\n  Outdoors,\n  ,\n  SunExposed,\n  WindExposed,\n  0.5,\n  4;\n", encoding="utf-8")
        result = ensure_sql_output(idf)
        content = result.read_text(encoding="utf-8")
        # Version should be bumped to 25.2
        assert "25.2" in content
