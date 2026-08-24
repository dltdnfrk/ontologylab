"""Verify, copy, and reverify an immutable pack serving snapshot."""

from __future__ import annotations

import json
import os
import shutil
import stat
import tempfile
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Final, assert_never

from ontologylab.kgstore import KGStore, KGStoreError
from ontologylab.pack_verifier import (
    JsonValue,
    PackSchemaVersion,
    PackVerifyCode,
    PackVerifyRefused,
    verify_pack,
)

_PREFIX: Final = "ontologylab-pack-"


class PackIntegrityError(KGStoreError):
    """Raised when a pack fails verified snapshot activation.

    Two shapes: the packed bytes do not match the receipt, or the pack
    carries no usable receipt. The hash is an integrity receipt, not a
    signature.
    """


@dataclass(frozen=True, slots=True)
class VerifiedPackSnapshot:
    pack_id: str
    content_hash: str
    pack_schema_version: PackSchemaVersion
    integrity_level: str
    serving_root: Path
    sqlite_path: Path
    manifest: Mapping[str, JsonValue]

    def open_store(self) -> KGStore:
        return KGStore.open(self.sqlite_path, read_only=True, immutable=True)

    def close(self) -> None:
        if self.serving_root.exists():
            shutil.rmtree(self.serving_root)


def _wrap(pack_id: str, refused: PackVerifyRefused) -> PackIntegrityError:
    detail = str(refused)
    match refused.code:
        case PackVerifyCode.TAMPERED_ARTIFACT:
            message = (
                f"pack {pack_id!r} failed integrity verification: {detail} "
                "hash mismatch"
            )
        case (
            PackVerifyCode.FORGED_HASH
            | PackVerifyCode.INVALID_MANIFEST
            | PackVerifyCode.MISSING_ARTIFACT
        ):
            message = (
                f"pack {pack_id!r} is unverifiable: {detail}; rebuild the pack "
                "so its integrity can be verified at load time"
            )
        case PackVerifyCode.SYMLINK:
            message = (
                f"pack {pack_id!r} has a symlinked {refused.path or 'artifact'}; "
                "active packs must be exact physical pack files"
            )
        case PackVerifyCode.HARDLINK:
            message = (
                f"pack {pack_id!r} has a hard-linked {refused.path or 'artifact'}"
            )
        case (
            PackVerifyCode.EXTRA_ARTIFACT
            | PackVerifyCode.PATH_MISMATCH
            | PackVerifyCode.WRITABLE
            | PackVerifyCode.ORIGINAL_INODE
            | PackVerifyCode.FORGED_COUNTS
            | PackVerifyCode.SELF_REFERENCE
        ):
            message = (
                f"pack {pack_id!r} failed integrity verification: {detail}"
            )
        case unreachable:
            assert_never(unreachable)
    return PackIntegrityError(message)


def _copy_tree(source: Path, dest: Path) -> None:
    for dirpath, dirnames, filenames in os.walk(source, followlinks=False):
        base = Path(dirpath)
        rel_base = base.relative_to(source)
        for name in (*dirnames, *filenames):
            child = base / name
            rel = (rel_base / name).as_posix()
            if child.is_symlink():
                raise PackIntegrityError(
                    f"pack {source.name!r} failed integrity verification: "
                    f"symlink ({rel})"
                )
        for name in dirnames:
            (dest / rel_base / name).mkdir(parents=True, exist_ok=True)
        for name in filenames:
            child = base / name
            target = dest / rel_base / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(child, target, follow_symlinks=False)
            os.chmod(target, stat.S_IMODE(child.lstat().st_mode))


def _lock_serving(root: Path) -> None:
    for dirpath, _dirnames, filenames in os.walk(root, followlinks=False):
        for name in filenames:
            path = Path(dirpath) / name
            os.chmod(path, stat.S_IMODE(path.stat().st_mode) & ~0o222)


def _load_manifest(path: Path, pack_id: str) -> dict[str, JsonValue]:
    try:
        loaded: JsonValue = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PackIntegrityError(
            f"pack {pack_id!r} is unverifiable: no readable manifest.json "
            f"({exc}); rebuild the pack to generate an integrity receipt"
        ) from exc
    if not isinstance(loaded, dict):
        raise PackIntegrityError(
            f"pack {pack_id!r} is unverifiable: invalid_manifest; rebuild "
            "the pack so its integrity can be verified at load time"
        )
    return loaded


def activate_pack(
    pack_dir: Path,
    *,
    working: Path | None = None,
) -> VerifiedPackSnapshot:
    """Verify source bytes, copy them, reverify the copy, then hand it over."""
    source = Path(pack_dir)
    pack_id = source.name
    if source.is_symlink():
        raise PackIntegrityError(
            f"pack {pack_id!r} has a symlinked pack directory; "
            "active packs must be exact physical pack files"
        )
    if not source.is_dir():
        raise PackIntegrityError(
            f"pack {pack_id!r} is unverifiable: pack directory not found; "
            "rebuild the pack so its integrity can be verified at load time"
        )
    try:
        first = verify_pack(source, working=working)
    except PackVerifyRefused as refused:
        raise _wrap(pack_id, refused) from refused
    parent = Path(tempfile.mkdtemp(prefix=f"{_PREFIX}{os.getpid()}-"))
    serving = parent / first.pack_id
    ready = False
    try:
        serving.mkdir()
        _copy_tree(source, serving)
        try:
            copied = verify_pack(serving, working=source)
        except PackVerifyRefused as refused:
            raise _wrap(pack_id, refused) from refused
        if (
            copied.pack_id != first.pack_id
            or copied.pack_content_hash != first.pack_content_hash
        ):
            raise PackIntegrityError(
                f"pack {pack_id!r} failed integrity verification: copied "
                "identity mismatch"
            )
        manifest = _load_manifest(serving / "manifest.json", copied.pack_id)
        _lock_serving(serving)
        ready = True
        return VerifiedPackSnapshot(
            pack_id=copied.pack_id,
            content_hash=copied.pack_content_hash,
            pack_schema_version=copied.pack_schema_version,
            integrity_level=copied.integrity_level,
            serving_root=parent,
            sqlite_path=serving / "pack.sqlite",
            manifest=manifest,
        )
    finally:
        if not ready:
            shutil.rmtree(parent, ignore_errors=True)


def inspect_verified_manifest(
    pack_dir: Path,
    *,
    working: Path | None = None,
) -> dict[str, JsonValue]:
    """Return the verified manifest and drop the temporary serving copy."""
    snapshot = activate_pack(pack_dir, working=working)
    try:
        return dict(snapshot.manifest)
    finally:
        snapshot.close()


@contextmanager
def opened_verified_pack(
    pack_dir: Path,
    *,
    working: Path | None = None,
) -> Iterator[tuple[VerifiedPackSnapshot, KGStore]]:
    """Activate a snapshot, open its store, and release both on exit."""
    snapshot = activate_pack(pack_dir, working=working)
    try:
        store = snapshot.open_store()
        try:
            yield snapshot, store
        finally:
            store.close()
    finally:
        snapshot.close()
