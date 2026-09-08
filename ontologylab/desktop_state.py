"""Canonical mutable-state paths for the macOS desktop app."""

from __future__ import annotations

import os
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from ontologylab.paths import ROOT, icloud_sync_reason

_DIRECTORY_MODE: Final = 0o700


@dataclass(frozen=True, slots=True)
class DesktopStateRefused(Exception):
    member: str

    def __str__(self) -> str:
        return f"desktop state refused: {self.member}"


@dataclass(frozen=True, slots=True)
class SuppliedDesktopPaths:
    data_dir: Path
    packs_dir: Path
    logs_dir: Path
    runtime_dir: Path


@dataclass(frozen=True, slots=True)
class DesktopPaths:
    """All read-only and mutable locations used by a bundled desktop process."""

    home: Path
    resources_dir: Path
    application_support_dir: Path
    data_dir: Path
    packs_dir: Path
    backups_dir: Path
    logs_dir: Path
    cache_dir: Path
    runtime_dir: Path

    @classmethod
    def for_home(cls, home: Path, resources_dir: Path) -> DesktopPaths:
        """Derive the one supported macOS per-user layout without resolving links."""
        canonical_home = Path(os.path.abspath(home.expanduser()))
        application_support = canonical_home / "Library/Application Support/ontologylab"
        cache = canonical_home / "Library/Caches/ontologylab"
        return cls(
            home=canonical_home,
            resources_dir=Path(os.path.abspath(resources_dir.expanduser())),
            application_support_dir=application_support,
            data_dir=application_support / "data",
            packs_dir=application_support / "packs",
            backups_dir=application_support / "backups",
            logs_dir=canonical_home / "Library/Logs/ontologylab",
            cache_dir=cache,
            runtime_dir=cache / "runtime",
        )

    @property
    def mutable_directories(self) -> tuple[Path, ...]:
        return (
            self.application_support_dir,
            self.data_dir,
            self.packs_dir,
            self.backups_dir,
            self.logs_dir,
            self.cache_dir,
            self.runtime_dir,
        )

    def require_supplied_paths(self, paths: SuppliedDesktopPaths) -> None:
        """Refuse supervisor fields that disagree with the canonical contract."""
        supplied = (
            ("data_dir", paths.data_dir, self.data_dir),
            ("packs_dir", paths.packs_dir, self.packs_dir),
            ("logs_dir", paths.logs_dir, self.logs_dir),
            ("runtime_dir", paths.runtime_dir, self.runtime_dir),
        )
        for member, value, expected in supplied:
            if Path(os.path.abspath(value.expanduser())) != expected:
                raise DesktopStateRefused(member=member)
        self.preflight()

    def preflight(self) -> None:
        """Validate every existing target before any mutable directory is created."""
        checkout = ROOT.resolve(strict=False)
        resolved_home = self.home.resolve(strict=False)
        if resolved_home == checkout or checkout in resolved_home.parents:
            raise DesktopStateRefused(member="checkout_write")
        try:
            if stat.S_ISLNK(self.home.lstat().st_mode):
                raise DesktopStateRefused(member="symlink")
        except FileNotFoundError:
            pass
        except OSError as exc:
            raise DesktopStateRefused(member="path_access") from exc
        for directory in self.mutable_directories:
            if icloud_sync_reason(directory, home=self.home) is not None:
                raise DesktopStateRefused(member="icloud")
            self._refuse_symlink_components(directory)
            if directory.exists():
                if not directory.is_dir():
                    raise DesktopStateRefused(member="path_type")
                if stat.S_IMODE(directory.stat().st_mode) != _DIRECTORY_MODE:
                    raise DesktopStateRefused(member="permissions")
        resources = self.resources_dir.resolve(strict=False)
        for directory in self.mutable_directories:
            resolved = directory.resolve(strict=False)
            if resolved == resources or resources in resolved.parents:
                raise DesktopStateRefused(member="bundle_write")
            if ".venv" in resolved.parts:
                raise DesktopStateRefused(member="venv_write")

    def prepare(self) -> None:
        """Create the preflighted app-specific directories with mode 0700."""
        self.preflight()
        try:
            for directory in self.mutable_directories:
                directory.mkdir(parents=True, exist_ok=True, mode=_DIRECTORY_MODE)
                directory.chmod(_DIRECTORY_MODE)
        except OSError as exc:
            raise DesktopStateRefused(member="unwritable") from exc

    def _refuse_symlink_components(self, path: Path) -> None:
        try:
            relative = path.relative_to(self.home)
        except ValueError as exc:
            raise DesktopStateRefused(member="outside_home") from exc
        current = self.home
        for part in relative.parts:
            current /= part
            try:
                mode = current.lstat().st_mode
            except FileNotFoundError:
                continue
            except OSError as exc:
                raise DesktopStateRefused(member="path_access") from exc
            if stat.S_ISLNK(mode):
                raise DesktopStateRefused(member="symlink")
