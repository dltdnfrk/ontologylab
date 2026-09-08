"""Pin PyInstaller zip containers to stored members and a fixed 1980 timestamp."""

from __future__ import annotations

import argparse
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Final

_ZIP_TIMESTAMP: Final = (1980, 1, 1, 0, 0, 0)


@dataclass(frozen=True, slots=True)
class ZipRewriteError(Exception):
    member: str
    detail: str

    def __str__(self) -> str:
        return f"zip_rewrite_refused member={self.member} detail={self.detail}"


def rewrite_zip(path: Path) -> None:
    """Rewrite one zip with stored members, sorted names, and a fixed timestamp."""
    try:
        with zipfile.ZipFile(path) as archive:
            names = tuple(sorted(archive.namelist()))
            payloads = tuple((name, archive.read(name)) for name in names)
    except zipfile.BadZipFile as error:
        raise ZipRewriteError(path.as_posix(), str(error)) from error
    staged = path.with_name(f"{path.name}.rewritten")
    with zipfile.ZipFile(
        staged, "w", compression=zipfile.ZIP_STORED, allowZip64=False
    ) as archive:
        for name, payload in payloads:
            info = zipfile.ZipInfo(filename=name, date_time=_ZIP_TIMESTAMP)
            info.compress_type = zipfile.ZIP_STORED
            info.create_system = 3
            archive.writestr(info, payload)
    staged.replace(path)


def rewrite_payload_zips(root: Path) -> None:
    """Rewrite every zip under an assembled onedir runtime tree."""
    for path in sorted(item for item in root.rglob("*.zip") if item.is_file()):
        rewrite_zip(path)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("root", type=Path)
    args = parser.parse_args()
    rewrite_payload_zips(args.root)


if __name__ == "__main__":
    main()
