"""Normalize signing-variant Mach-O bytes for reproducibility comparison."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import TypedDict


class ManifestFile(TypedDict):
    path: str
    bytes: int
    sha256: str
    kind: str


def normalize(source: Path, output: Path) -> None:
    """Keep payload hashes except Mach-O bytes changed by ad-hoc signing/UUIDs."""
    payload = json.loads(source.read_text(encoding="utf-8"))
    files: list[ManifestFile] = payload["files"]
    for entry in files:
        if entry["path"] in payload["inventories"]["mach_o"]:
            entry["bytes"] = 0
            entry["sha256"] = "unsigned-mach-o"
    output.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    normalize(args.source, args.output)


if __name__ == "__main__":
    main()
