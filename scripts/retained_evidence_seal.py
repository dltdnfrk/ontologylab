"""Deterministic lstat-based retained evidence node sealing."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import stat
import sys
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from scripts.internal_deployment_types import DeploymentRefused

_DOMAIN = b"ontologylab.retained-evidence-node.v1\0"


class EvidenceNodeFields(BaseModel):
    """Canonical identity fields for one retained filesystem node."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_id: Literal["ontologylab.retained-evidence-node.v1"] = Field(
        alias="schema"
    )
    path: str
    node_type: Literal["file", "directory", "symlink"]
    mode: str
    content_sha256: str
    link_target_base64: str
    target_scope: Literal["none", "internal", "absolute", "escaping"]


class EvidenceNode(EvidenceNodeFields):
    """Canonical node identity plus its domain-separated digest."""

    node_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


def _with_digest(fields: EvidenceNodeFields) -> EvidenceNode:
    canonical = json.dumps(
        fields.model_dump(by_alias=True, mode="json"),
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return EvidenceNode(
        **fields.model_dump(by_alias=True, mode="python"),
        node_sha256=hashlib.sha256(_DOMAIN + canonical).hexdigest(),
    )


def _symlink_scope(
    root: Path, path: Path, target: str
) -> Literal["internal", "absolute", "escaping"]:
    if os.path.isabs(target):
        return "absolute"
    projected = Path(os.path.normpath(path.parent / target))
    return "internal" if projected.is_relative_to(root) else "escaping"


def _node(root: Path, path: Path) -> EvidenceNode:
    info = os.lstat(path)
    relative = path.relative_to(root).as_posix()
    mode = oct(stat.S_IMODE(info.st_mode))
    if stat.S_ISREG(info.st_mode):
        content = hashlib.sha256(path.read_bytes()).hexdigest()
        return _with_digest(
            EvidenceNodeFields(
                schema="ontologylab.retained-evidence-node.v1",
                path=relative,
                node_type="file",
                mode=mode,
                content_sha256=content,
                link_target_base64="",
                target_scope="none",
            )
        )
    if stat.S_ISDIR(info.st_mode):
        return _with_digest(
            EvidenceNodeFields(
                schema="ontologylab.retained-evidence-node.v1",
                path=relative,
                node_type="directory",
                mode=mode,
                content_sha256="",
                link_target_base64="",
                target_scope="none",
            )
        )
    if stat.S_ISLNK(info.st_mode):
        target = os.readlink(path)
        encoded = base64.b64encode(os.fsencode(target)).decode("ascii")
        return _with_digest(
            EvidenceNodeFields(
                schema="ontologylab.retained-evidence-node.v1",
                path=relative,
                node_type="symlink",
                mode=mode,
                content_sha256="",
                link_target_base64=encoded,
                target_scope=_symlink_scope(root, path, target),
            )
        )
    raise DeploymentRefused(f"retained_evidence_special_node:{relative}")


def retained_nodes(
    root: Path, excluded_relative: Path | None = None
) -> tuple[EvidenceNode, ...]:
    """Enumerate every in-scope descendant once without following symlinks."""
    try:
        canonical_root = root.resolve(strict=True)
    except OSError as exc:
        raise DeploymentRefused("retained_evidence_root") from exc
    if not canonical_root.is_dir() or root.is_symlink():
        raise DeploymentRefused("retained_evidence_root")
    if excluded_relative is not None and (
        excluded_relative.is_absolute() or ".." in excluded_relative.parts
    ):
        raise DeploymentRefused("retained_evidence_exclusion")
    paths: list[Path] = []
    for current, directories, files in os.walk(canonical_root, followlinks=False):
        current_path = Path(current)
        paths.extend(current_path / name for name in directories)
        paths.extend(current_path / name for name in files)
    if excluded_relative is not None:
        paths = [
            path
            for path in paths
            if not path.relative_to(canonical_root).is_relative_to(
                excluded_relative
            )
        ]
    return tuple(_node(canonical_root, path) for path in sorted(paths))


def write_node_manifest(
    root: Path, output: Path, excluded_relative: Path | None = None
) -> tuple[EvidenceNode, ...]:
    """Write an external manifest covering files, directories, and symlink nodes."""
    try:
        output_parent = output.parent.resolve(strict=True)
        canonical_root = root.resolve(strict=True)
    except OSError as exc:
        raise DeploymentRefused("retained_evidence_path") from exc
    output_inside_root = output_parent == canonical_root or output_parent.is_relative_to(
        canonical_root
    )
    output_is_excluded = (
        excluded_relative is not None
        and output.is_relative_to(canonical_root / excluded_relative)
    )
    if output_inside_root and not output_is_excluded:
        raise DeploymentRefused("retained_evidence_manifest_scope")
    nodes = retained_nodes(canonical_root, excluded_relative)
    payload = b"".join(
        node.model_dump_json(by_alias=True).encode() + b"\n" for node in nodes
    )
    try:
        descriptor = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o444)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        descriptor = os.open(output_parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    except OSError as exc:
        raise DeploymentRefused("retained_evidence_manifest_write") from exc
    return nodes


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ontologylab-retained-evidence-seal")
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--exclude-relative", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        nodes = write_node_manifest(
            args.root, args.output, args.exclude_relative
        )
    except DeploymentRefused as exc:
        print(str(exc), file=sys.stderr)
        return 2
    print(
        json.dumps(
            {
                "directories": sum(node.node_type == "directory" for node in nodes),
                "files": sum(node.node_type == "file" for node in nodes),
                "nodes": len(nodes),
                "symlinks": sum(node.node_type == "symlink" for node in nodes),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
