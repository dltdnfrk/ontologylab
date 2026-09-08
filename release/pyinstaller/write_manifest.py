"""Write deterministic inventories for an assembled PyInstaller onedir tree."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
from typing import Final, TypedDict

_MACHO_MAGICS: Final = {
    b"\xcf\xfa\xed\xfe",
    b"\xfe\xed\xfa\xcf",
    b"\xca\xfe\xba\xbe",
    b"\xbe\xba\xfe\xca",
    b"\xca\xfe\xba\xbf",
    b"\xbf\xba\xfe\xca",
}
_NATIVE_SUFFIXES: Final = (".so", ".dylib")
_STATIC_SUFFIXES: Final = (".html", ".js", ".css", ".woff2", "/manifest.json")


class FileRecord(TypedDict):
    path: str
    bytes: int
    sha256: str
    kind: str


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _is_macho(path: Path) -> bool:
    with path.open("rb") as handle:
        return handle.read(4) in _MACHO_MAGICS


def _kind(rel: str, path: Path, macho: bool) -> str:
    if rel.startswith("licenses/"):
        return "license"
    if "/ontologylab/web/" in f"/{rel}" and rel.endswith(_STATIC_SUFFIXES):
        return "static"
    if rel.endswith(_NATIVE_SUFFIXES):
        return "native"
    if macho:
        return "mach-o"
    if os.access(path, os.X_OK):
        return "executable"
    return "data"


def write_manifest(root: Path, version: str, contract: Path) -> Path:
    """Hash every payload file and emit sorted machine-consumed inventories."""
    records: list[FileRecord] = []
    mach_o: list[str] = []
    native: list[str] = []
    static: list[str] = []
    licenses: list[str] = []
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        rel = path.relative_to(root).as_posix()
        if rel in {"runtime-manifest.json", "runtime-manifest.sha256"}:
            continue
        macho = _is_macho(path)
        kind = _kind(rel, path, macho)
        records.append(
            {
                "path": rel,
                "bytes": path.stat().st_size,
                "sha256": _sha256(path),
                "kind": kind,
            }
        )
        if macho:
            mach_o.append(rel)
        if rel.endswith(_NATIVE_SUFFIXES):
            native.append(rel)
        if "/ontologylab/web/" in f"/{rel}" and rel.endswith(_STATIC_SUFFIXES):
            static.append(rel)
        if rel.startswith("licenses/"):
            licenses.append(rel)
    payload = {
        "architecture": "arm64",
        "build_contract_sha256": _sha256(contract),
        "files": records,
        "format": "onedir",
        "inventories": {
            "licenses": licenses,
            "mach_o": mach_o,
            "native_extensions": native,
            "static_assets": static,
        },
        "required_modules": [
            "ontologylab.main",
            "ontologylab.mcp_server",
            "ontologylab.serve",
            "ontologylab.serve_desktop",
            "ontologylab.web",
        ],
        "schema": "ontologylab.runtime-manifest.v1",
        "version": version,
    }
    target = root / "runtime-manifest.json"
    raw = (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode()
    target.write_bytes(raw)
    (root / "runtime-manifest.sha256").write_text(
        hashlib.sha256(raw).hexdigest() + "\n", encoding="ascii"
    )
    return target


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("root", type=Path)
    parser.add_argument("version")
    parser.add_argument("contract", type=Path)
    args = parser.parse_args()
    print(write_manifest(args.root, args.version, args.contract))


if __name__ == "__main__":
    main()
