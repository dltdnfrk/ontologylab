"""Staged Representation file lifecycle (Wave 2.1 Step 6B / F4).

DB authority stores the immutable final relative path
``documents/{representation_id}/raw.txt`` from the first insert. Bytes live
in an operation-owned staging file until atomic rename + directory fsync
and a short ready transaction. Readers consume ready files only.
"""

from __future__ import annotations

import hashlib
import os
import re
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal


RecoveryClass = Literal["absent", "finalizable", "valid-ready", "quarantined"]
RepresentationState = Literal["staged", "ready", "quarantined"]
Failpoint = Callable[[str], None]
STAGED: RepresentationState = "staged"
READY: RepresentationState = "ready"
QUARANTINED: RepresentationState = "quarantined"
_SAFE_OPERATION = re.compile(r"[^A-Za-z0-9._-]+")


class FileLifecycleError(Exception):
    """Typed file-lifecycle failure."""


class PathEscapeError(FileLifecycleError):
    """Caller path is absolute, traverses, or leaves the staging root."""


class FileNotReady(FileLifecycleError):
    """Readers may consume ready Representation bytes only."""


class FileIntegrityError(FileLifecycleError):
    """Missing or hash-mismatched bytes; never accepted as ready."""

    def __init__(self, reason: str, message: str | None = None) -> None:
        self.reason = reason
        super().__init__(message or reason)


@dataclass(frozen=True, slots=True)
class RecoveryDecision:
    classification: RecoveryClass
    representation_id: str | None
    reason: str | None = None
    raw_text_path: str | None = None
    state: str | None = None


def content_hash_for(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def final_raw_text_path(representation_id: str) -> str:
    return f"documents/{representation_id}/raw.txt"


def store_root_from_conn(conn: sqlite3.Connection) -> Path:
    row = conn.execute("PRAGMA database_list").fetchone()
    if row is None or not row[2]:
        raise FileLifecycleError("connection has no file-backed store root")
    return Path(row[2]).parent


def safe_operation_id(operation_id: str) -> str:
    cleaned = _SAFE_OPERATION.sub("_", operation_id.strip()) or "operation"
    if cleaned in {".", ".."}:
        cleaned = "operation"
    return cleaned


def operation_staging_root(store_root: Path, operation_id: str) -> Path:
    root = Path(store_root) / "staging" / safe_operation_id(operation_id)
    staging = (Path(store_root) / "staging").resolve()
    resolved = Path(store_root).joinpath("staging", safe_operation_id(operation_id))
    if not _is_contained(resolved.resolve(strict=False), staging):
        raise PathEscapeError("operation staging root escapes store staging")
    return root


def _is_contained(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _fsync_path(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def contained_documents_path(store_root: Path, raw_text_path: str) -> Path:
    if not raw_text_path or not raw_text_path.strip():
        raise PathEscapeError("empty raw_text_path rejected")
    raw = Path(raw_text_path)
    if raw.is_absolute():
        raise PathEscapeError("absolute path rejected")
    if ".." in raw.parts:
        raise PathEscapeError("parent traversal rejected")
    documents = (Path(store_root) / "documents").resolve()
    candidate = Path(store_root) / raw
    resolved = candidate.resolve()
    if candidate.is_symlink() and not _is_contained(resolved, documents):
        raise PathEscapeError("symlink escape rejected")
    if not _is_contained(resolved, documents):
        raise PathEscapeError("raw_text_path escapes documents/")
    return resolved


def contain_source_path(
    store_root: Path, operation_id: str, caller_path: str
) -> Path:
    if not caller_path or not caller_path.strip():
        raise PathEscapeError("empty path rejected")
    raw = Path(caller_path)
    if raw.is_absolute():
        raise PathEscapeError("absolute path rejected")
    if ".." in raw.parts:
        raise PathEscapeError("parent traversal rejected")

    staging = operation_staging_root(store_root, operation_id)
    staging.mkdir(parents=True, exist_ok=True)
    staging_resolved = staging.resolve()
    store_candidate = Path(store_root) / raw
    if store_candidate.exists() or store_candidate.is_symlink():
        resolved = store_candidate.resolve()
        if not _is_contained(resolved, staging_resolved):
            raise PathEscapeError("source path outside operation staging root")
    candidate = staging / raw
    if candidate.is_symlink():
        resolved = candidate.resolve()
        if not _is_contained(resolved, staging_resolved):
            raise PathEscapeError("symlink escape rejected")
        return resolved
    resolved = candidate.resolve(strict=False)
    if not _is_contained(resolved, staging_resolved):
        raise PathEscapeError("source path outside operation staging root")
    return resolved


def stage_bytes(
    store_root: Path,
    operation_id: str,
    representation_id: str,
    data: bytes,
) -> Path:
    staging = operation_staging_root(store_root, operation_id)
    staging.mkdir(parents=True, exist_ok=True)
    path = staging / f"{representation_id}.part"
    if not _is_contained(path.resolve(strict=False), staging.resolve()):
        raise PathEscapeError("staging path escapes operation staging root")
    with path.open("wb") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())
    _fsync_path(staging)
    return path


def _as_bytes(raw_text: bytes | str) -> bytes:
    if isinstance(raw_text, bytes):
        return raw_text
    return raw_text.encode("utf-8")


def prepare_representation_payload(
    store_root: Path,
    operation_id: str,
    representation_id: str,
    *,
    raw_text: bytes | str | None,
    raw_text_path: str,
) -> Path | None:
    """Stage operation-owned bytes. Never persist the caller path."""
    if raw_text_path:
        contain_source_path(store_root, operation_id, raw_text_path)
    data: bytes | None
    if raw_text is not None:
        data = _as_bytes(raw_text)
    elif raw_text_path:
        source = contain_source_path(store_root, operation_id, raw_text_path)
        if source.is_file():
            data = source.read_bytes()
        else:
            data = None
    else:
        data = None
    if data is None:
        return None
    return stage_bytes(store_root, operation_id, representation_id, data)


def find_staging_file(store_root: Path, representation_id: str) -> Path | None:
    staging = Path(store_root) / "staging"
    if not staging.is_dir():
        return None
    matches = sorted(staging.glob(f"*/{representation_id}.part"))
    return matches[0] if matches else None


def _row(
    conn: sqlite3.Connection, representation_id: str
) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT id, content_hash, raw_text_path, representation_state "
        "FROM documents WHERE id = ?",
        (representation_id,),
    ).fetchone()


def _hash_file(path: Path) -> str | None:
    try:
        return content_hash_for(path.read_bytes())
    except OSError:
        return None


def _final_abs(store_root: Path, raw_text_path: str) -> Path | None:
    try:
        return contained_documents_path(store_root, raw_text_path)
    except PathEscapeError:
        return None


def classify_representation(
    conn: sqlite3.Connection,
    store_root: Path,
    representation_id: str,
) -> RecoveryDecision:
    row = _row(conn, representation_id)
    if row is None:
        return RecoveryDecision(
            classification="absent",
            representation_id=representation_id,
        )
    state = str(row["representation_state"])
    raw_text_path = str(row["raw_text_path"])
    expected = str(row["content_hash"])
    if state == QUARANTINED:
        return RecoveryDecision(
            classification="quarantined",
            representation_id=representation_id,
            reason="already_quarantined",
            raw_text_path=raw_text_path,
            state=state,
        )
    if not raw_text_path and state == READY:
        return RecoveryDecision(
            classification="valid-ready",
            representation_id=representation_id,
            reason="metadata_only",
            raw_text_path=raw_text_path,
            state=state,
        )

    final_abs = _final_abs(store_root, raw_text_path)
    if final_abs is None:
        return RecoveryDecision(
            classification="quarantined",
            representation_id=representation_id,
            reason="path_escape",
            raw_text_path=raw_text_path,
            state=state,
        )
    staged = find_staging_file(store_root, representation_id)
    final_hash = _hash_file(final_abs) if final_abs.is_file() else None
    staged_hash = _hash_file(staged) if staged is not None and staged.is_file() else None

    if state == READY:
        if final_hash == expected:
            return RecoveryDecision(
                classification="valid-ready",
                representation_id=representation_id,
                raw_text_path=raw_text_path,
                state=state,
            )
        reason = "missing_bytes" if final_hash is None else "hash_mismatch"
        return RecoveryDecision(
            classification="quarantined",
            representation_id=representation_id,
            reason=reason,
            raw_text_path=raw_text_path,
            state=state,
        )

    if staged_hash == expected or final_hash == expected:
        return RecoveryDecision(
            classification="finalizable",
            representation_id=representation_id,
            raw_text_path=raw_text_path,
            state=state,
        )
    reason = "missing_bytes" if staged_hash is None and final_hash is None else "hash_mismatch"
    return RecoveryDecision(
        classification="quarantined",
        representation_id=representation_id,
        reason=reason,
        raw_text_path=raw_text_path,
        state=state,
    )


def quarantine_representation(
    conn: sqlite3.Connection, representation_id: str
) -> None:
    owned = not conn.in_transaction
    if owned:
        conn.execute("BEGIN IMMEDIATE")
    try:
        conn.execute(
            "UPDATE documents SET representation_state = ? "
            "WHERE id = ? AND representation_state != ?",
            (QUARANTINED, representation_id, QUARANTINED),
        )
        if owned:
            conn.commit()
    except BaseException:
        if owned and conn.in_transaction:
            conn.rollback()
        raise


def _mark_ready(
    conn: sqlite3.Connection, representation_id: str, raw_text_path: str
) -> None:
    owned = not conn.in_transaction
    if owned:
        conn.execute("BEGIN IMMEDIATE")
    try:
        conn.execute(
            "UPDATE documents SET representation_state = ? "
            "WHERE id = ? AND representation_state = ? AND raw_text_path = ?",
            (READY, representation_id, STAGED, raw_text_path),
        )
        if owned:
            conn.commit()
    except BaseException:
        if owned and conn.in_transaction:
            conn.rollback()
        raise


def finalize_representation(
    conn: sqlite3.Connection,
    store_root: Path,
    representation_id: str,
    *,
    failpoint: Failpoint | None = None,
) -> RecoveryDecision:
    decision = classify_representation(conn, store_root, representation_id)
    if decision.classification == "valid-ready":
        return decision
    if decision.classification != "finalizable":
        if decision.state in {STAGED, READY}:
            quarantine_representation(conn, representation_id)
        raise FileIntegrityError(decision.reason or "not_finalizable")

    raw_text_path = decision.raw_text_path or final_raw_text_path(representation_id)
    final_abs = contained_documents_path(store_root, raw_text_path)
    staged = find_staging_file(store_root, representation_id)
    if failpoint is not None:
        failpoint("before_rename")
    if not final_abs.is_file():
        if staged is None or not staged.is_file():
            quarantine_representation(conn, representation_id)
            raise FileIntegrityError("missing_bytes")
        final_abs.parent.mkdir(parents=True, exist_ok=True)
        _fsync_path(final_abs.parent.parent if final_abs.parent.parent.exists() else store_root)
        os.replace(staged, final_abs)
    if failpoint is not None:
        failpoint("after_rename")
    _fsync_path(final_abs)
    _fsync_path(final_abs.parent)
    documents = Path(store_root) / "documents"
    if documents.is_dir():
        _fsync_path(documents)
    if failpoint is not None:
        failpoint("after_directory_fsync")
    if content_hash_for(final_abs.read_bytes()) != str(
        _row(conn, representation_id)["content_hash"]  # type: ignore[index]
    ):
        quarantine_representation(conn, representation_id)
        raise FileIntegrityError("hash_mismatch")
    if failpoint is not None:
        failpoint("before_ready")
    _mark_ready(conn, representation_id, raw_text_path)
    return classify_representation(conn, store_root, representation_id)


def _cleanup_absent_staging(
    store_root: Path, known_ids: set[str]
) -> list[RecoveryDecision]:
    decisions: list[RecoveryDecision] = []
    staging = Path(store_root) / "staging"
    if not staging.is_dir():
        return decisions
    for part in sorted(staging.glob("*/*.part")):
        representation_id = part.stem
        if representation_id in known_ids:
            continue
        part.unlink(missing_ok=True)
        try:
            part.parent.rmdir()
        except OSError:
            pass
        decisions.append(
            RecoveryDecision(
                classification="absent",
                representation_id=representation_id,
                reason="orphan_staging",
            )
        )
    return decisions


def reconcile_files(
    conn: sqlite3.Connection,
    store_root: Path | None = None,
    *,
    failpoint: Failpoint | None = None,
) -> tuple[RecoveryDecision, ...]:
    root = store_root if store_root is not None else store_root_from_conn(conn)
    rows = conn.execute(
        "SELECT id FROM documents "
        "WHERE work_id IS NOT NULL AND ("
        "representation_state = ? "
        "OR (raw_text_path LIKE 'documents/%' AND length(content_hash) = 71)"
        ") "
        "ORDER BY id",
        (STAGED,),
    ).fetchall()
    known = {str(row[0]) for row in rows}
    decisions: list[RecoveryDecision] = []
    for row in rows:
        representation_id = str(row[0])
        classified = classify_representation(conn, root, representation_id)
        if classified.classification == "finalizable":
            decisions.append(
                finalize_representation(
                    conn, root, representation_id, failpoint=failpoint
                )
            )
            continue
        if (
            classified.classification == "quarantined"
            and classified.state != QUARANTINED
        ):
            quarantine_representation(conn, representation_id)
            decisions.append(
                classify_representation(conn, root, representation_id)
            )
            continue
        decisions.append(classified)
    decisions.extend(_cleanup_absent_staging(root, known))
    return tuple(decisions)


def read_ready_text(
    conn: sqlite3.Connection,
    store_root: Path,
    representation_id: str,
) -> str:
    row = _row(conn, representation_id)
    if row is None:
        raise FileNotReady(f"unknown representation {representation_id}")
    if str(row["representation_state"]) != READY:
        raise FileNotReady(
            f"representation {representation_id} is {row['representation_state']}"
        )
    path = contained_documents_path(store_root, str(row["raw_text_path"]))
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise FileIntegrityError("missing_bytes") from exc
    if content_hash_for(data) != str(row["content_hash"]):
        raise FileIntegrityError("hash_mismatch")
    return data.decode("utf-8")


def ready_byte_length(store_root: Path, raw_text_path: str, state: str) -> int:
    if state != READY:
        return 0
    try:
        path = contained_documents_path(store_root, raw_text_path)
    except PathEscapeError:
        return 0
    try:
        return path.stat().st_size if path.is_file() else 0
    except OSError:
        return 0


__all__ = [
    "FileIntegrityError",
    "FileLifecycleError",
    "FileNotReady",
    "PathEscapeError",
    "QUARANTINED",
    "READY",
    "RecoveryDecision",
    "STAGED",
    "classify_representation",
    "contain_source_path",
    "contained_documents_path",
    "content_hash_for",
    "final_raw_text_path",
    "finalize_representation",
    "find_staging_file",
    "operation_staging_root",
    "prepare_representation_payload",
    "quarantine_representation",
    "read_ready_text",
    "ready_byte_length",
    "reconcile_files",
    "stage_bytes",
    "store_root_from_conn",
]
