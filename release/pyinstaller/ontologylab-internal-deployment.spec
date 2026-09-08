# -*- mode: python ; coding: utf-8 -*-
"""Pinned thin-arm64 standalone internal deployment executable."""

from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_data_files, copy_metadata

ROOT = Path(SPECPATH).parents[1]
ENTRY = ROOT / "release" / "pyinstaller" / "internal_deployment_entry.py"

pydantic_datas, pydantic_binaries, pydantic_hidden = collect_all("pydantic")
datas = collect_data_files("ontologylab", include_py_files=False) + pydantic_datas
datas += copy_metadata("ontologylab", recursive=True)
datas += copy_metadata("pydantic", recursive=True)

analysis = Analysis(
    [str(ENTRY)],
    pathex=[str(ROOT)],
    binaries=pydantic_binaries,
    datas=datas,
    hiddenimports=pydantic_hidden,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
volatile_metadata = {"RECORD", "direct_url.json", "uv_cache.json"}
analysis.datas = [
    item for item in analysis.datas if Path(item[0]).name not in volatile_metadata
]
pyz = PYZ(analysis.pure)
executable = EXE(
    pyz,
    analysis.scripts,
    analysis.binaries,
    analysis.datas,
    [],
    name="ontologylab-internal-deploy",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    target_arch="arm64",
    codesign_identity=None,
    entitlements_file=None,
)
