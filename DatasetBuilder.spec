# -*- mode: python ; coding: utf-8 -*-
"""Сборка Dataset Builder v2 в папку dist/DatasetBuilderV2 (one-dir)."""
from PyInstaller.building.api import COLLECT, EXE, PYZ
from PyInstaller.building.build_main import Analysis
from PyInstaller.utils.hooks import collect_data_files

datas = []
datas += collect_data_files("qfluentwidgets")
datas += collect_data_files("docx")

a = Analysis(
    ["run_gui.py"],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=["odf", "openpyxl", "docx", "qfluentwidgets"],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["torch", "sklearn", "scipy", "matplotlib", "transformers",
              "pandas", "pyarrow", "sympy", "numpy", "regex", "anyio",
              "narwhals", "cloudpickle", "fsspec", "jinja2", "pytest",
              "rich", "pygments", "py"],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="DatasetBuilderV2",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
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
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="DatasetBuilderV2",
)
