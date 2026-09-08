"""Refuse wrong-architecture or externally resolved Mach-O payloads."""

from __future__ import annotations

import argparse
import json
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Final, TypedDict

_MAGICS: Final = {
    b"\xcf\xfa\xed\xfe",
    b"\xfe\xed\xfa\xcf",
    b"\xca\xfe\xba\xbe",
    b"\xbe\xba\xfe\xca",
    b"\xca\xfe\xba\xbf",
    b"\xbf\xba\xfe\xca",
}
_ALLOWED_ABSOLUTE: Final = ("/System/Library/", "/usr/lib/")


@dataclass(frozen=True, slots=True)
class MachOInspectionError(Exception):
    member: str
    detail: str

    def __str__(self) -> str:
        return f"macho_inspection_refused member={self.member} detail={self.detail}"


class MachORecord(TypedDict):
    path: str
    architecture: str
    dependencies: list[str]


def _run(*args: str) -> str:
    try:
        return subprocess.run(args, check=True, capture_output=True, text=True).stdout
    except subprocess.CalledProcessError as exc:
        raise MachOInspectionError(args[0], exc.stderr.strip()) from None


def inspect(root: Path, output: Path) -> tuple[MachORecord, ...]:
    """Inspect every Mach-O and write a deterministic dependency inventory."""
    records: list[MachORecord] = []
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        with path.open("rb") as handle:
            if handle.read(4) not in _MAGICS:
                continue
        rel = path.relative_to(root).as_posix()
        architecture = _run("/usr/bin/lipo", "-archs", str(path)).strip()
        if architecture != "arm64":
            raise MachOInspectionError(rel, f"architecture={architecture}")
        lines = _run("/usr/bin/otool", "-L", str(path)).splitlines()[1:]
        dependencies = sorted(line.strip().split(" (", 1)[0] for line in lines)
        for dependency in dependencies:
            if dependency.startswith("/") and not dependency.startswith(
                _ALLOWED_ABSOLUTE
            ):
                raise MachOInspectionError(rel, f"external_dependency={dependency}")
        records.append(
            {"path": rel, "architecture": architecture, "dependencies": dependencies}
        )
    if not records:
        raise MachOInspectionError("payload", "no_mach_o")
    payload = {
        "architecture": "arm64",
        "files": records,
        "schema": "ontologylab.runtime-native-inventory.v1",
    }
    output.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return tuple(records)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("root", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    print(len(inspect(args.root, args.output)))


if __name__ == "__main__":
    main()
