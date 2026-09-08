"""Dashboard asset authority: one manifest-verified package resource tree.

The shipped dashboard (HTML/JS/CSS/font) lives under ``ontologylab.web`` as
package resources. ``manifest.json`` pins every servable file by path, size,
and SHA-256; :func:`verify_assets` proves the installed tree matches it
exactly — a missing, tampered, or unlisted file fails server startup before
anything is served, in a checkout, a wheel, or a zip alike.

Regenerate the manifest after editing any asset:

    uv run python -m ontologylab.web_assets write-manifest
    uv run python -m ontologylab.web_assets check

Standard library only.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections.abc import Iterator, Mapping
from contextlib import AbstractContextManager
from dataclasses import asdict, dataclass
from importlib import resources
from importlib.resources.abc import Traversable
from pathlib import Path, PurePosixPath
from types import MappingProxyType
from typing import Final, assert_never

ASSET_PACKAGE: Final = "ontologylab.web"
MANIFEST_NAME: Final = "manifest.json"
_MANIFEST_VERSION: Final = 1

# Package-directory members that are not dashboard assets: import
# scaffolding, contributor docs, the manifest itself, OS litter, bytecode.
_NON_ASSET_FILES: Final = frozenset(
    {"__init__.py", "AGENTS.md", MANIFEST_NAME, ".DS_Store"}
)
_NON_ASSET_DIRS: Final = frozenset({"__pycache__"})

_MEDIA_TYPES: Final = {
    ".html": "text/html",
    ".js": "text/javascript",
    ".css": "text/css",
    ".svg": "image/svg+xml",
    ".woff2": "font/woff2",
}

_SHA256_RE: Final = re.compile(r"[0-9a-f]{64}")


class AssetVerificationError(RuntimeError):
    """The dashboard resource tree does not match its manifest."""

    def __init__(self, problems: tuple[str, ...]) -> None:
        """Collect every problem found so one run reports all of them."""
        self.problems = problems
        super().__init__(
            "dashboard asset verification failed: " + "; ".join(problems)
        )


@dataclass(frozen=True, slots=True)
class AssetEntry:
    """One manifest line: a servable asset pinned by content."""

    path: str
    size: int
    sha256: str


@dataclass(frozen=True, slots=True)
class VerifiedAssets:
    """Manifest-pinned asset bytes, proven complete and untampered."""

    entries: tuple[AssetEntry, ...]
    content: Mapping[str, bytes]


@dataclass(frozen=True, slots=True)
class _LiveAsset:
    size: int
    sha256: str
    body: bytes


def resource_root() -> Traversable:
    """Return the shipped dashboard resource tree (``ontologylab.web``)."""
    return resources.files(ASSET_PACKAGE)


def as_local_file(node: Traversable) -> AbstractContextManager[Path]:
    """Give a resource a real filesystem path, lifetime-managed (zip-safe)."""
    return resources.as_file(node)


def _path_is_safe(path: str) -> bool:
    """True iff a manifest path is relative POSIX staying inside the tree."""
    rel = PurePosixPath(path)
    return (
        bool(path)
        and not rel.is_absolute()
        and ".." not in rel.parts
        and "\\" not in path
    )


def _parse_manifest_text(text: str) -> tuple[AssetEntry, ...]:
    """Parse manifest JSON into validated entries or raise one typed error."""
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise AssetVerificationError(
            (f"{MANIFEST_NAME} is not valid JSON: {exc}",)
        ) from None
    if not isinstance(payload, dict):
        raise AssetVerificationError((f"{MANIFEST_NAME} must be a JSON object",))
    if payload.get("version") != _MANIFEST_VERSION:
        raise AssetVerificationError(
            (f"{MANIFEST_NAME} version must be {_MANIFEST_VERSION}",)
        )
    assets = payload.get("assets")
    if not isinstance(assets, list):
        raise AssetVerificationError(
            (f"{MANIFEST_NAME} must carry an assets list",)
        )
    problems: list[str] = []
    entries: list[AssetEntry] = []
    for index, raw in enumerate(assets):
        if not isinstance(raw, dict):
            problems.append(f"manifest asset #{index} is not an object")
            continue
        path = raw.get("path")
        size = raw.get("size")
        sha256 = raw.get("sha256")
        if not isinstance(path, str) or not _path_is_safe(path):
            problems.append(f"unsafe manifest path: {path!r}")
            continue
        if not isinstance(size, int) or isinstance(size, bool) or size < 0:
            problems.append(f"manifest path {path}: invalid size")
            continue
        if not isinstance(sha256, str) or not _SHA256_RE.fullmatch(sha256):
            problems.append(f"manifest path {path}: invalid sha256")
            continue
        entries.append(AssetEntry(path=path, size=size, sha256=sha256))
    if problems:
        raise AssetVerificationError(tuple(problems))
    return tuple(sorted(entries, key=lambda entry: entry.path))


def _iter_asset_files(
    root: Traversable | Path, prefix: str = ""
) -> Iterator[tuple[str, Traversable | Path]]:
    """Yield ``(manifest-relative path, node)`` for every asset file."""
    for child in sorted(root.iterdir(), key=lambda node: node.name):
        if child.name in _NON_ASSET_FILES:
            continue
        rel = f"{prefix}{child.name}"
        if child.is_dir():
            if child.name in _NON_ASSET_DIRS:
                continue
            yield from _iter_asset_files(child, f"{rel}/")
        elif child.is_file():
            yield rel, child


def _live_assets(root: Traversable | Path) -> dict[str, _LiveAsset]:
    live: dict[str, _LiveAsset] = {}
    for rel, node in _iter_asset_files(root):
        body = node.read_bytes()
        live[rel] = _LiveAsset(
            size=len(body), sha256=hashlib.sha256(body).hexdigest(), body=body
        )
    return live


def compute_manifest(root: Traversable | Path) -> tuple[AssetEntry, ...]:
    """Hash every asset file under ``root`` into sorted manifest entries."""
    live = _live_assets(root)
    return tuple(
        AssetEntry(path=path, size=item.size, sha256=item.sha256)
        for path, item in sorted(live.items())
    )


def manifest_entries(root: Traversable | Path) -> tuple[AssetEntry, ...]:
    """Parse and validate the committed manifest under ``root``."""
    try:
        text = (root / MANIFEST_NAME).read_text(encoding="utf-8")
    except (FileNotFoundError, NotADirectoryError, IsADirectoryError):
        raise AssetVerificationError(
            (f"{MANIFEST_NAME} missing from dashboard resource tree",)
        ) from None
    return _parse_manifest_text(text)


def verify_tree(root: Traversable | Path) -> VerifiedAssets:
    """Prove the tree at ``root`` matches its manifest exactly.

    Every manifest entry must exist with the pinned size and SHA-256, and
    every asset file present must be listed — an unlisted addition is a
    second authority and fails the same way a deletion does.
    """
    entries = manifest_entries(root)
    live = _live_assets(root)
    problems: list[str] = []
    expected: dict[str, AssetEntry] = {}
    for entry in entries:
        if entry.path in expected:
            problems.append(f"duplicate manifest path: {entry.path}")
        expected[entry.path] = entry
    for path, entry in expected.items():
        got = live.get(path)
        if got is None:
            problems.append(f"missing asset: {path}")
        elif got.size != entry.size:
            problems.append(
                f"size mismatch: {path} (manifest {entry.size}, tree {got.size})"
            )
        elif got.sha256 != entry.sha256:
            problems.append(f"sha256 mismatch: {path}")
    for path in live:
        if path not in expected:
            problems.append(f"unlisted asset file: {path}")
    if problems:
        raise AssetVerificationError(tuple(problems))
    content: dict[str, bytes] = {
        path: live[path].body for path in expected
    }
    return VerifiedAssets(
        entries=tuple(expected.values()), content=MappingProxyType(content)
    )


def verify_assets() -> VerifiedAssets:
    """Verify the shipped ``ontologylab.web`` tree against its manifest."""
    return verify_tree(resource_root())


def asset_paths() -> tuple[str, ...]:
    """Servable paths from the committed manifest (what /static answers)."""
    return tuple(entry.path for entry in manifest_entries(resource_root()))


def read_asset_bytes(name: str) -> bytes:
    """Read one shipped asset as raw bytes (tests and dev tooling)."""
    rel = PurePosixPath(name)
    if rel.is_absolute() or ".." in rel.parts:
        raise AssetVerificationError((f"unsafe asset name: {name!r}",))
    node = resource_root()
    for part in rel.parts:
        node = node / part
    return node.read_bytes()


def read_asset_text(name: str) -> str:
    """Read one shipped asset as UTF-8 text (tests and dev tooling)."""
    return read_asset_bytes(name).decode("utf-8")


def content_type(path: str) -> str:
    """MIME media type for a manifest-listed asset."""
    suffix = PurePosixPath(path).suffix.lower()
    try:
        return _MEDIA_TYPES[suffix]
    except KeyError:
        raise AssetVerificationError(
            (f"no media type registered for asset: {path}",)
        ) from None


def _manifest_bytes(entries: tuple[AssetEntry, ...]) -> bytes:
    payload = {
        "version": _MANIFEST_VERSION,
        "assets": [asdict(entry) for entry in entries],
    }
    return (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode("utf-8")


def _write_manifest() -> str:
    root = resource_root()
    entries = compute_manifest(root)
    with resources.as_file(root) as local:
        (local / MANIFEST_NAME).write_bytes(_manifest_bytes(entries))
    return f"wrote {MANIFEST_NAME}: {len(entries)} assets"


def main() -> None:
    """CLI: ``check`` fails on a bad tree; ``write-manifest`` regenerates it."""
    parser = argparse.ArgumentParser(
        prog="ontologylab.web_assets",
        description="Verify or regenerate the dashboard asset manifest.",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser(
        "check", help="fail unless the installed tree matches the manifest"
    )
    sub.add_parser(
        "write-manifest", help="regenerate manifest.json from the current tree"
    )
    args = parser.parse_args()
    match args.command:
        case "check":
            try:
                verified = verify_assets()
            except AssetVerificationError as exc:
                parser.exit(1, f"error: {exc}\n")
            print(f"ok: {len(verified.entries)} dashboard assets verified")
        case "write-manifest":
            print(_write_manifest())
        case unreachable:
            assert_never(unreachable)


if __name__ == "__main__":
    main()
