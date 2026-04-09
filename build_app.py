"""Build macOS .app bundle for EVERGREEN EnergyPlus Simulator."""

import PyInstaller.__main__
import os

ROOT = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(ROOT, "src")
STANDARDS = os.path.join(ROOT, "standards")

PyInstaller.__main__.run([
    os.path.join(SRC, "il_energy", "gui.py"),
    "--name", "EVERGREEN",
    "--windowed",                   # .app bundle, no terminal
    "--onedir",                     # faster startup than --onefile
    "--noconfirm",                  # overwrite previous build
    # Include the entire il_energy package
    "--paths", SRC,
    # Bundle standards JSON data files
    "--add-data", f"{STANDARDS}:standards",
    # Collect all submodules
    "--collect-submodules", "il_energy",
    "--collect-submodules", "tkinterweb",
    "--collect-submodules", "tkmacosx",
    # Hidden imports the bundler might miss
    "--hidden-import", "il_energy.cli",
    "--hidden-import", "il_energy.simulation.runner",
    "--hidden-import", "il_energy.simulation.idf_parser",
    "--hidden-import", "il_energy.simulation.sql_parser",
    "--hidden-import", "il_energy.simulation.idf_object_parser",
    "--hidden-import", "il_energy.simulation.idf_v89_converter",
    "--hidden-import", "il_energy.postprocessing.metrics",
    "--hidden-import", "il_energy.postprocessing.normalizer",
    "--hidden-import", "il_energy.postprocessing.zone_aggregator",
    "--hidden-import", "il_energy.rating.calculator",
    "--hidden-import", "il_energy.reference.generator",
    "--hidden-import", "il_energy.reference.box_generator",
    "--hidden-import", "il_energy.report.generator",
    "--hidden-import", "il_energy.report.idf_class_registry",
    "--hidden-import", "il_energy.report.idf_object_report",
    "--hidden-import", "il_energy.envelope.h_value",
    "--hidden-import", "il_energy.envelope.report_h",
    "--hidden-import", "il_energy.envelope.report_1045",
    "--hidden-import", "il_energy.envelope.idf_surface_parser",
    "--hidden-import", "il_energy.analysis.windows",
    "--hidden-import", "il_energy.config",
    "--hidden-import", "il_energy.models",
    "--hidden-import", "il_energy.exceptions",
    "--hidden-import", "click",
    "--hidden-import", "pydantic",
    "--hidden-import", "yaml",
    "--hidden-import", "weasyprint",
])
