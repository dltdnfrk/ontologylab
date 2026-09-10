"""Materialize verified source and separately derived Task 11 build work."""

from __future__ import annotations

import hashlib
import json
import stat
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Final, TypedDict

from .candidate_build import CandidateRefused, TreeEntry, tree_manifest
from .candidate_deployment_overlay import patch_deployment_builder
from .candidate_source_closure import copy_source_closure, verify_source_closure
from .candidate_tree import sha256_file

BUILD_PATHS: Final = (
    "release/__init__.py",
    "release/mcp-config.json",
    "release/runtime-build.json",
    "release/pyinstaller",
    "release/candidate_build.py",
    "release/candidate_cli.py",
    "release/candidate_deployment_overlay.py",
    "release/candidate_execution.py",
    "release/candidate_license_override.py",
    "release/candidate_licenses.py",
    "release/candidate_package.py",
    "release/candidate_receipt.py",
    "release/candidate_resources.py",
    "release/candidate_source.py",
    "release/candidate_source_closure.py",
    "release/candidate_stage.py",
    "release/candidate_tree.py",
    "release/candidate_types.py",
    "release/licenses",
    "scripts/build-macos-runtime.sh",
    "scripts/build-macos-candidate.sh",
    # The application itself, and the deployment tool bundled through
    # release/pyinstaller/internal_deployment_entry.py. Without these the
    # digest covered only the build harness: a 2026-09-10 change to
    # scripts/internal_deployment.py moved the shipped deploy binary
    # 220f572a -> b1426289 while build_inputs_sha256 stayed 766a61ec, so
    # "same inputs" did not mean "same artifact".
    "ontologylab",
    "scripts/internal_deployment.py",
    "scripts/internal_deployment_cli.py",
    "scripts/internal_deployment_fs.py",
    "scripts/internal_deployment_types.py",
    "scripts/internal_deployment_removal_apply.py",
    "scripts/internal_deployment_removal_prepare.py",
    "LICENSE",
    "README.md",
)
_SWIFT_ANCHOR: Final = '  "$ROOT/launcher/supervisor/StateSupport.swift"\n'
_BASE_SWIFT: Final = frozenset(
    {
        "main.swift",
        "ProcessSupport.swift",
        "Protocol.swift",
        "StateSupport.swift",
        "Supervisor.swift",
    }
)
_TOOL_ANCHOR: Final = '  --with "pyinstaller==$PYINSTALLER_VERSION" \\\n'
_PROVENANCE_ANCHOR: Final = (
    'find "$APP/Contents/Resources/runtime" -type f -name direct_url.json -delete\n'
)
_PROVENANCE_OVERLAY: Final = """find "$APP/Contents/Resources/runtime" -type f \\
  \\( -name direct_url.json -o -name RECORD -o -name uv_cache.json \\) -delete
"""
_VENV_GATE: Final = """if grep -R -a -l -F '/.venv/' "$APP" | grep -q .; then
  echo "runtime_build_refused member=venv_path detail=payload" >&2
  exit 1
fi
"""


class OverlayManifest(TypedDict):
    schema: str
    source_script_sha256: str
    generator_sha256: str
    uv_lock_sha256: str
    typer_version: str
    extra_swift_sources: list[str]
    supervisor_inventory_sha256: str
    overlay_sha256: str
    overlay_bytes: int
    overlay_mode: str


@dataclass(frozen=True, slots=True)
class StageLayout:
    """Verified immutable source plus separately generated mutable build work."""

    source_root: Path
    build_root: Path
    builder: Path
    overlay_manifest_path: Path
    overlay: OverlayManifest


def _sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _record(path: Path, rel: str) -> TreeEntry:
    return {
        "path": rel,
        "kind": "file",
        "bytes": path.stat().st_size,
        "mode": oct(stat.S_IMODE(path.stat().st_mode)),
        "sha256": sha256_file(path),
    }


def _typer_version(root: Path) -> str:
    lock = tomllib.loads((root / "uv.lock").read_text(encoding="utf-8"))
    packages = lock.get("package")
    if not isinstance(packages, list):
        raise CandidateRefused("lock_packages", "uv.lock")
    versions = [
        item.get("version")
        for item in packages
        if isinstance(item, dict) and item.get("name") == "typer"
    ]
    if len(versions) != 1 or not isinstance(versions[0], str):
        raise CandidateRefused("lock_package", "typer")
    return versions[0]


def _extra_swift(root: Path) -> list[str]:
    return sorted(
        path.name
        for path in (root / "launcher" / "supervisor").glob("*.swift")
        if path.name not in _BASE_SWIFT and path.name != "Package.swift"
    )


def patched_builder(root: Path) -> bytes:
    """Derive the build script overlay without mutating authoritative source."""
    source = root / "scripts" / "build-macos-runtime.sh"
    text = source.read_text(encoding="utf-8")
    if any(
        text.count(anchor) != 1
        for anchor in (
            _SWIFT_ANCHOR,
            _TOOL_ANCHOR,
            _PROVENANCE_ANCHOR,
            _VENV_GATE,
        )
    ):
        raise CandidateRefused("builder_overlay_anchor", str(source))
    tool_overlay = _TOOL_ANCHOR + f'  --with "typer=={_typer_version(root)}" \\\n'
    swift_lines = [
        '  "$ROOT/launcher/supervisor/StateSupport.swift"',
        *(f'  "$ROOT/launcher/supervisor/{name}"' for name in _extra_swift(root)),
    ]
    patched = (
        text.replace(_SWIFT_ANCHOR, " \\\n".join(swift_lines) + "\n")
        .replace(_TOOL_ANCHOR, tool_overlay)
        .replace(_PROVENANCE_ANCHOR, _PROVENANCE_OVERLAY)
        .replace(_VENV_GATE, "")
    )
    return patch_deployment_builder(patched).encode()


def overlay_manifest(root: Path) -> OverlayManifest:
    """Bind overlay bytes to source script, generator, lock, and Swift inputs."""
    overlay = patched_builder(root)
    swift = [f"launcher/supervisor/{name}" for name in _extra_swift(root)]
    inventory = [{"path": rel, "sha256": sha256_file(root / rel)} for rel in swift]
    return {
        "schema": "ontologylab.macos-candidate.build-overlay.v1",
        "source_script_sha256": sha256_file(root / "scripts/build-macos-runtime.sh"),
        "generator_sha256": sha256_file(root / "release/candidate_stage.py"),
        "uv_lock_sha256": sha256_file(root / "uv.lock"),
        "typer_version": _typer_version(root),
        "extra_swift_sources": swift,
        "supervisor_inventory_sha256": _sha256_bytes(
            json.dumps(inventory, sort_keys=True, separators=(",", ":")).encode()
        ),
        "overlay_sha256": _sha256_bytes(overlay),
        "overlay_bytes": len(overlay),
        "overlay_mode": "0o555",
    }


def _manifest_bytes(manifest: OverlayManifest) -> bytes:
    return (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode()


def verify_overlay(layout: StageLayout) -> None:
    """Refuse overlay, options, or bound-manifest drift before execution."""
    expected = overlay_manifest(layout.source_root)
    if layout.overlay != expected:
        raise CandidateRefused("build_overlay_manifest", "generator-inputs")
    if layout.overlay_manifest_path.read_bytes() != _manifest_bytes(expected):
        raise CandidateRefused("build_overlay_manifest", "manifest-bytes")
    if (
        sha256_file(layout.builder) != expected["overlay_sha256"]
        or layout.builder.stat().st_size != expected["overlay_bytes"]
        or oct(stat.S_IMODE(layout.builder.stat().st_mode)) != expected["overlay_mode"]
    ):
        raise CandidateRefused("build_overlay_drift", str(layout.builder))


def build_input_payload(root: Path) -> dict[str, str | list[TreeEntry]]:
    """Inventory source build inputs and separately generated overlay authority."""
    records: list[TreeEntry] = []
    for rel in BUILD_PATHS:
        path = root / rel
        if not path.exists() or path.is_symlink():
            raise CandidateRefused("build_input_missing", rel)
        if path.is_dir():
            records.extend(
                {**item, "path": f"{rel}/{item['path']}"}
                for item in tree_manifest(path)
                if item["kind"] == "file"
            )
        else:
            records.append(_record(path, rel))
    manifest = overlay_manifest(root)
    records.extend(
        (
            {
                "path": "generated/scripts/build-macos-runtime.sh",
                "kind": "file",
                "bytes": manifest["overlay_bytes"],
                "mode": manifest["overlay_mode"],
                "sha256": manifest["overlay_sha256"],
            },
            {
                "path": "generated/build-overlay-manifest.json",
                "kind": "file",
                "bytes": len(_manifest_bytes(manifest)),
                "mode": "0o444",
                "sha256": _sha256_bytes(_manifest_bytes(manifest)),
            },
        )
    )
    return {
        "schema": "ontologylab.macos-candidate.build-inputs.v1",
        "files": sorted(records, key=lambda item: item["path"]),
    }


def _freeze_source(root: Path) -> None:
    for path in sorted(root.rglob("*"), reverse=True):
        path.chmod(0o555 if path.is_dir() or path.stat().st_mode & 0o111 else 0o444)
    root.chmod(0o555)


def derive_build_work(
    authority: Path, source_root: Path, workspace: Path
) -> StageLayout:
    """Verify source first, freeze it, then derive overlay only in build work."""
    verify_source_closure(authority, source_root)
    build_root = workspace / "build_work"
    copy_source_closure(source_root, build_root)
    _freeze_source(source_root)
    builder = build_root / "scripts" / "build-macos-runtime.sh"
    builder.chmod(0o644)
    builder.write_bytes(patched_builder(source_root))
    builder.chmod(0o555)
    manifest = overlay_manifest(source_root)
    manifest_path = workspace / "build-overlay-manifest.json"
    manifest_path.write_bytes(_manifest_bytes(manifest))
    manifest_path.chmod(0o444)
    layout = StageLayout(source_root, build_root, builder, manifest_path, manifest)
    verify_overlay(layout)
    verify_source_closure(authority, source_root)
    return layout


def prepare_stage(root: Path, workspace: Path) -> StageLayout:
    """Create exact immutable source stage before any generated build overlay."""
    source_root = workspace / "source_stage"
    copy_source_closure(root, source_root)
    return derive_build_work(root, source_root, workspace)
