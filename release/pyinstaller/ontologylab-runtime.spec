# -*- mode: python ; coding: utf-8 -*-
"""Pinned arm64 onedir specification; paths derive only from this file."""

from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_data_files, collect_submodules, copy_metadata

ROOT = Path(SPECPATH).parents[1]
ENTRY = ROOT / "release" / "pyinstaller" / "runtime_entry.py"

binaries = []
datas = collect_data_files("ontologylab", include_py_files=False)
hiddenimports = collect_submodules("ontologylab")

for package in (
    "fastapi",
    "httptools",
    "igraph",
    "leidenalg",
    "mcp",
    "pydantic",
    "sqlite_vec",
    "starlette",
    "uvicorn",
    "uvloop",
    "watchfiles",
    "websockets",
):
    package_datas, package_binaries, package_hidden = collect_all(package)
    datas += package_datas
    binaries += package_binaries
    hiddenimports += package_hidden

for distribution in (
    "fastapi",
    "mcp",
    "pydantic",
    "python-igraph",
    "leidenalg",
    "sqlite-vec",
    "starlette",
    "uvicorn",
):
    datas += copy_metadata(distribution, recursive=True)

analysis = Analysis(
    [str(ENTRY)],
    pathex=[str(ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=sorted(set(hiddenimports)),
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["sentence_transformers", "torch", "transformers"],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(analysis.pure)
executable = EXE(
    pyz,
    analysis.scripts,
    [],
    exclude_binaries=True,
    name="ontologylab-runtime",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    target_arch="arm64",
    codesign_identity=None,
    entitlements_file=None,
)
collect = COLLECT(
    executable,
    analysis.binaries,
    analysis.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="ontologylab-runtime",
)
