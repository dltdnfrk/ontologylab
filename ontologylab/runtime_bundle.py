"""Relocatable runtime preflight and bundled surface dispatcher."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path, PurePosixPath
from typing import Annotated, Final, Literal, assert_never

from pydantic import BaseModel, ConfigDict, Field, ValidationError

_MANIFEST: Final = "runtime-manifest.json"
_MANIFEST_DIGEST: Final = "runtime-manifest.sha256"
_SCHEMA: Final = "ontologylab.runtime-manifest.v1"
_FORBIDDEN: Final = (
    b"/" + b"Users" + b"/",
    b"." + b"venv",
    b"/opt/" + b"homebrew",
    b"/usr/" + b"local/",
)


@dataclass(frozen=True, slots=True)
class RuntimePreflightError(Exception):
    """A typed refusal raised before any bundled surface starts."""

    code: str
    member: str

    def __str__(self) -> str:
        return f"runtime_preflight_refused code={self.code} member={self.member}"


class RuntimeSurface(StrEnum):
    """Installed product surfaces carried by the shared bootloader."""

    CLI = "cli"
    SERVER = "server"
    MCP = "mcp"
    DESKTOP = "desktop"


class RuntimeFile(BaseModel):
    """One content-pinned file in the onedir payload."""

    model_config = ConfigDict(frozen=True, strict=True, extra="forbid")

    path: str
    bytes: Annotated[int, Field(ge=0)]
    sha256: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
    kind: Literal["data", "executable", "license", "mach-o", "native", "static"]


class RuntimeInventories(BaseModel):
    """Machine-consumed subsets of the complete file inventory."""

    model_config = ConfigDict(frozen=True, strict=True, extra="forbid")

    licenses: tuple[str, ...]
    mach_o: tuple[str, ...]
    native_extensions: tuple[str, ...]
    static_assets: tuple[str, ...]


class RuntimeManifest(BaseModel):
    """Validated boundary model for a shipped onedir payload."""

    model_config = ConfigDict(frozen=True, strict=True, extra="forbid")

    schema_name: Literal["ontologylab.runtime-manifest.v1"] = Field(alias="schema")
    version: str
    architecture: Literal["arm64"]
    format: Literal["onedir"]
    build_contract_sha256: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
    files: tuple[RuntimeFile, ...]
    inventories: RuntimeInventories
    required_modules: tuple[str, ...]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_relative(raw: str) -> Path:
    rel = PurePosixPath(raw)
    if not raw or rel.is_absolute() or ".." in rel.parts or "\\" in raw:
        raise RuntimePreflightError("unsafe_path", raw)
    return Path(*rel.parts)


def runtime_root() -> Path:
    """Resolve the onedir root from the bootloader, never the checkout."""
    return Path(sys.executable).resolve().parent


def preflight(root: Path | None = None) -> RuntimeManifest:
    """Verify the signed-by-digest manifest and every declared payload byte."""
    payload_root = runtime_root() if root is None else root.resolve()
    manifest_path = payload_root / _MANIFEST
    digest_path = payload_root / _MANIFEST_DIGEST
    try:
        raw = manifest_path.read_bytes()
        expected_digest = digest_path.read_text(encoding="ascii").strip()
    except OSError as exc:
        raise RuntimePreflightError("manifest_missing", exc.filename or _MANIFEST) from None
    except UnicodeError:
        raise RuntimePreflightError("manifest_malformed", _MANIFEST_DIGEST) from None
    if any(marker in raw for marker in _FORBIDDEN):
        raise RuntimePreflightError("absolute_path", _MANIFEST)
    if hashlib.sha256(raw).hexdigest() != expected_digest:
        raise RuntimePreflightError("manifest_digest", _MANIFEST)
    try:
        manifest = RuntimeManifest.model_validate_json(raw)
    except (ValidationError, ValueError, json.JSONDecodeError):
        raise RuntimePreflightError("manifest_malformed", _MANIFEST) from None
    if manifest.schema_name != _SCHEMA:
        raise RuntimePreflightError("manifest_schema", manifest.schema_name)
    seen: set[str] = set()
    for entry in manifest.files:
        rel = _safe_relative(entry.path)
        if entry.path in seen:
            raise RuntimePreflightError("duplicate_path", entry.path)
        seen.add(entry.path)
        target = payload_root / rel
        if not target.is_file():
            raise RuntimePreflightError("file_missing", entry.path)
        if target.stat().st_size != entry.bytes or _sha256(target) != entry.sha256:
            raise RuntimePreflightError("file_mutated", entry.path)
    for module in manifest.required_modules:
        if importlib.util.find_spec(module) is None:
            raise RuntimePreflightError("module_missing", module)
    for required in (
        *manifest.inventories.licenses,
        *manifest.inventories.mach_o,
        *manifest.inventories.native_extensions,
        *manifest.inventories.static_assets,
    ):
        if required not in seen:
            raise RuntimePreflightError("inventory_missing", required)
    return manifest


def main() -> None:
    """Preflight once, then dispatch the requested installed product surface."""
    preflight()
    raw_command = sys.argv[1] if len(sys.argv) > 1 else RuntimeSurface.CLI.value
    try:
        command = RuntimeSurface(raw_command)
    except ValueError:
        raise RuntimePreflightError("unknown_surface", raw_command) from None
    sys.argv = [sys.argv[0], *sys.argv[2:]]
    match command:
        case RuntimeSurface.CLI:
            from ontologylab.main import main as entry
        case RuntimeSurface.SERVER:
            from ontologylab.serve import main as entry
        case RuntimeSurface.MCP:
            from ontologylab.mcp_server import main as entry
        case RuntimeSurface.DESKTOP:
            from ontologylab.serve_desktop import main as entry
        case unreachable:
            assert_never(unreachable)
    entry()


if __name__ == "__main__":
    main()
