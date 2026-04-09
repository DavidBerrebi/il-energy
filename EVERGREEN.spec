# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_submodules

hiddenimports = ['il_energy.cli', 'il_energy.simulation.runner', 'il_energy.simulation.idf_parser', 'il_energy.simulation.sql_parser', 'il_energy.simulation.idf_object_parser', 'il_energy.simulation.idf_v89_converter', 'il_energy.postprocessing.metrics', 'il_energy.postprocessing.normalizer', 'il_energy.postprocessing.zone_aggregator', 'il_energy.rating.calculator', 'il_energy.reference.generator', 'il_energy.reference.box_generator', 'il_energy.report.generator', 'il_energy.report.idf_class_registry', 'il_energy.report.idf_object_report', 'il_energy.envelope.h_value', 'il_energy.envelope.report_h', 'il_energy.envelope.report_1045', 'il_energy.envelope.idf_surface_parser', 'il_energy.analysis.windows', 'il_energy.config', 'il_energy.models', 'il_energy.exceptions', 'click', 'pydantic', 'yaml', 'weasyprint']
hiddenimports += collect_submodules('il_energy')
hiddenimports += collect_submodules('tkinterweb')
hiddenimports += collect_submodules('tkmacosx')


a = Analysis(
    ['/Users/davidberrebi/Desktop/EnergyGreen/ClaudeCodeProj/src/il_energy/gui.py'],
    pathex=['/Users/davidberrebi/Desktop/EnergyGreen/ClaudeCodeProj/src'],
    binaries=[],
    datas=[('/Users/davidberrebi/Desktop/EnergyGreen/ClaudeCodeProj/standards', 'standards')],
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='EVERGREEN',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='EVERGREEN',
)
app = BUNDLE(
    coll,
    name='EVERGREEN.app',
    icon=None,
    bundle_identifier=None,
)
