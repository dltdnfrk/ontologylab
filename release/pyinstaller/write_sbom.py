"""Generate deterministic SBOM and third-party license inventory."""

from __future__ import annotations

import argparse
import importlib.metadata
import json
import shutil
from pathlib import Path
from typing import TypedDict


class Component(TypedDict):
    name: str
    version: str
    license: str


def write_sbom(runtime: Path, project_license: Path, version: str) -> None:
    """Inventory bundled dist-info metadata and copy available license texts."""
    internal = runtime / "_internal"
    license_root = runtime / "licenses"
    license_root.mkdir()
    shutil.copy2(project_license, license_root / "ontologylab-MIT.txt")
    components: list[Component] = [
        {"name": "ontologylab", "version": version, "license": "MIT"}
    ]
    copied = ["licenses/ontologylab-MIT.txt"]
    for metadata_dir in sorted(internal.glob("*.dist-info")):
        metadata_path = metadata_dir / "METADATA"
        if not metadata_path.is_file():
            continue
        fields: dict[str, str] = {}
        for line in metadata_path.read_text(
            encoding="utf-8", errors="replace"
        ).splitlines():
            if ": " in line:
                key, value = line.split(": ", 1)
                fields.setdefault(key, value)
        name = fields.get("Name", metadata_dir.name.rsplit("-", 1)[0])
        version = fields.get("Version", "unknown")
        components.append(
            {
                "name": name,
                "version": version,
                "license": fields.get("License", "declared-in-metadata"),
            }
        )
        try:
            distribution = importlib.metadata.distribution(name)
        except importlib.metadata.PackageNotFoundError:
            continue
        for entry in distribution.files or ():
            filename = Path(str(entry)).name.lower()
            if not filename.startswith(("license", "copying", "notice")):
                continue
            source = Path(str(distribution.locate_file(entry)))
            if not source.is_file():
                continue
            destination = license_root / f"{name}-{version}-{Path(str(entry)).name}"
            shutil.copy2(source, destination)
            copied.append(destination.relative_to(runtime).as_posix())
    payload = {
        "components": sorted(
            components, key=lambda item: (item["name"].lower(), item["version"])
        ),
        "format": "CycloneDX-compatible-component-inventory",
        "licenses": sorted(set(copied)),
        "schema": "ontologylab.runtime-sbom.v1",
    }
    (runtime / "sbom.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("runtime", type=Path)
    parser.add_argument("project_license", type=Path)
    parser.add_argument("version")
    args = parser.parse_args()
    write_sbom(args.runtime, args.project_license, args.version)


if __name__ == "__main__":
    main()
