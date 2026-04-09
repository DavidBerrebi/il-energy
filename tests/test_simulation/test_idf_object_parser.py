"""Tests for il_energy.simulation.idf_object_parser."""

import pytest

from il_energy.simulation.idf_object_parser import (
    IDFField,
    IDFObject,
    extract_idf_version,
    parse_idf_objects,
)


class TestParseIdfObjects:
    """Test IDF text → structured object parsing."""

    def test_single_object(self):
        text = "Version, 25.2;\n"
        result = parse_idf_objects(text)
        assert "Version" in result
        assert len(result["Version"]) == 1
        assert result["Version"][0].fields[0].value == "25.2"

    def test_multiline_object(self):
        text = (
            "Material,\n"
            "  Concrete,            !- Name\n"
            "  MediumRough,         !- Roughness\n"
            "  0.2,                 !- Thickness {m}\n"
            "  1.7,                 !- Conductivity {W/m-K}\n"
            "  2300;                !- Density {kg/m3}\n"
        )
        result = parse_idf_objects(text)
        assert "Material" in result
        obj = result["Material"][0]
        assert len(obj.fields) == 5
        assert obj.fields[0].value == "Concrete"
        assert obj.fields[0].name == "Name"
        assert obj.fields[2].value == "0.2"
        assert obj.fields[2].name == "Thickness"
        assert obj.fields[2].unit == "m"

    def test_multiple_objects_same_class(self):
        text = (
            "Material, Concrete, Rough, 0.2, 1.7, 2300;\n"
            "Material, Insulation, Smooth, 0.05, 0.04, 30;\n"
        )
        result = parse_idf_objects(text)
        assert len(result["Material"]) == 2

    def test_comments_only_lines_skipped(self):
        text = (
            "! This is a comment\n"
            "Version, 25.2;\n"
        )
        result = parse_idf_objects(text)
        assert "Version" in result

    def test_empty_input(self):
        result = parse_idf_objects("")
        assert result == {}


class TestExtractIdfVersion:
    """Test IDF version string extraction."""

    def test_standard_format(self):
        assert extract_idf_version("Version, 25.2;") == "25.2"

    def test_with_trailing_dot(self):
        assert extract_idf_version("Version, 9.4.;") == "9.4"

    def test_embedded_in_file(self):
        text = "! Some comment\nVersion,\n  25.2;\n\nMaterial, Concrete;\n"
        assert extract_idf_version(text) == "25.2"

    def test_not_found(self):
        assert extract_idf_version("Material, Concrete;") == ""

    def test_case_insensitive(self):
        assert extract_idf_version("version, 8.9;") == "8.9"
