#!/usr/bin/env python3
"""Manual QA driver for the Task 1 KG-only / lifecycle baseline.

Drives real ``KGStore`` and ``ExtractionState`` surfaces against a disposable
SQLite database, proving commit visibility, rollback visibility, exact failure
identity, document content-hash provenance, and Unicode character-span
handling through independent observer connections.

Ownership rules:
  * the target database and its sidecars must not exist beforehand; if any
    exists the script exits 2 without mutating anything;
  * only paths this process created are removed, always in ``finally``;
  * a non-zero exit is produced when any check or cleanup fails.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ontologylab.extraction_state import ExtractionState  # noqa: E402
from ontologylab.extractor import Chunk  # noqa: E402
from ontologylab.kgstore import KGStore  # noqa: E402
from ontologylab.models import ProposedEntity, SourceSpan  # noqa: E402

SIDECAR_SUFFIXES = ("-wal", "-shm", "-journal")
UNICODE_TEXT = "Le débit → RateLimiter protège l'API."
UNICODE_TERM = "RateLimiter"


def owned_paths(database: Path) -> list[Path]:
    """Every path this script may create for ``database``."""
    return [database] + [
        database.with_name(database.name + suffix)
        for suffix in SIDECAR_SUFFIXES
    ]


def preflight(database: Path) -> list[str]:
    """Return existing collisions among the target and declared sidecars."""
    return [str(path) for path in owned_paths(database) if path.exists()]


def _document(store: KGStore, text: str, name: str, owned: list[Path]):
    content_hash = "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()
    document, created = store.insert_document(
        source_kind="upload",
        source_uri=f"file:///{name}.txt",
        title=name,
        raw_text=text,
        content_hash=content_hash,
    )
    if not created:
        raise AssertionError("disposable database was not empty")
    # Record exactly the raw-text path this process caused KGStore to create;
    # the shared documents/ root itself is never assumed to be ours.
    owned.append(store.db_path.parent / document.raw_text_path)
    return document


def _propose(store: KGStore, document, node_id: str, span: SourceSpan, **kw):
    return store.insert_proposed(
        [
            ProposedEntity(
                id=node_id,
                entity_type="Component",
                name=UNICODE_TERM,
                source_span=span,
            )
        ],
        [],
        source_doc_id=document.id,
        extractor_engine="qa-baseline",
        **kw,
    )


def _claim(state: ExtractionState, store: KGStore, document, text: str):
    chunk = Chunk(index=0, char_offset=0, text=text)
    plan = state.plan(
        document.id,
        [chunk],
        schema_version_id=store.active_schema_version()["id"],
        engine="qa-baseline",
        model=None,
        prompt_version="qa-baseline-v1",
        decode_params=None,
    )
    if not state.claim(plan.run_id, chunk.index):
        raise AssertionError("could not claim the qa chunk")
    return plan, chunk


def _observe(database: Path, sql: str, params: tuple = ()):  # independent conn
    observer = sqlite3.connect(database)
    try:
        return observer.execute(sql, params).fetchone()
    finally:
        observer.close()


def run_success_case(database: Path, checks: dict, owned: list[Path]) -> None:
    store = KGStore.open(database)
    try:
        document = _document(store, UNICODE_TEXT, "qa-success", owned)
        raw_bytes = (store.db_path.parent / document.raw_text_path).read_bytes()
        digest = hashlib.sha256(raw_bytes).hexdigest()
        checks["content_hash_matches_raw_bytes"] = (
            document.content_hash == "sha256:" + digest
        )

        decoded = raw_bytes.decode("utf-8")
        char_start = decoded.index(UNICODE_TERM)
        char_end = char_start + len(UNICODE_TERM)
        byte_start = len(decoded[:char_start].encode("utf-8"))
        checks["char_span_selects_term"] = (
            decoded[char_start:char_end] == UNICODE_TERM
        )
        checks["char_offset_is_not_byte_offset"] = byte_start != char_start
        checks["byte_span_selects_term"] = raw_bytes[
            byte_start:byte_start + len(UNICODE_TERM.encode("utf-8"))
        ] == UNICODE_TERM.encode("utf-8")

        with ExtractionState(store.conn) as state:
            plan, chunk = _claim(state, store, document, UNICODE_TEXT)
            stats = _propose(
                store, document, "qa-success-node",
                SourceSpan(char_start, char_end), commit=False,
            )
            checks["uncommitted_node_invisible_to_observer"] = _observe(
                database, "SELECT 1 FROM nodes WHERE id = 'qa-success-node'"
            ) is None

            state.succeeded(plan.run_id, chunk.index, stats)

            row = _observe(
                database,
                "SELECT source_doc_id FROM nodes WHERE id = 'qa-success-node'",
            )
            status = _observe(
                database,
                "SELECT status FROM extraction_chunks WHERE run_id = ? "
                "AND chunk_index = ?",
                (plan.run_id, chunk.index),
            )
            checks["committed_node_visible_to_observer"] = (
                row is not None and row[0] == document.id
            )
            checks["success_marker_visible_to_observer"] = (
                status is not None and status[0] == "succeeded"
            )
            span_row = _observe(
                database,
                "SELECT source_span FROM nodes WHERE id = 'qa-success-node'",
            )
            stored = json.loads(span_row[0])
            checks["stored_span_is_character_span"] = (
                stored["start"],
                stored["end"],
            ) == (char_start, char_end)
    finally:
        store.close()


def run_failure_case(database: Path, checks: dict, owned: list[Path]) -> None:
    store = KGStore.open(database)
    try:
        text = "RateLimiter protects the API."
        document = _document(store, text, "qa-failure", owned)
        with ExtractionState(store.conn) as state:
            plan, chunk = _claim(state, store, document, text)
            _propose(
                store, document, "qa-rollback-node",
                SourceSpan(0, len(UNICODE_TERM)), commit=False,
            )
            state.failed(plan.run_id, chunk.index, "qa_baseline_failure")

            checks["rolled_back_node_absent_for_observer"] = _observe(
                database, "SELECT 1 FROM nodes WHERE id = 'qa-rollback-node'"
            ) is None
            chunk_row = _observe(
                database,
                "SELECT status, error_kind FROM extraction_chunks "
                "WHERE run_id = ? AND chunk_index = ?",
                (plan.run_id, chunk.index),
            )
            run_row = _observe(
                database,
                "SELECT status FROM extraction_runs WHERE id = ?",
                (plan.run_id,),
            )
            # Exact failure identity, not merely "a failure happened".
            checks["exact_failure_identity_visible"] = tuple(chunk_row) == (
                "failed", "qa_baseline_failure",
            )
            checks["run_marked_failed_for_observer"] = (
                run_row is not None and run_row[0] == "failed"
            )
    finally:
        store.close()


def table_inventory(database: Path) -> list[str]:
    observer = sqlite3.connect(f"file:{database}?mode=ro", uri=True)
    try:
        return sorted(
            row[0]
            for row in observer.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        )
    finally:
        observer.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", required=True, type=Path)
    args = parser.parse_args(argv)
    database: Path = args.database

    collisions = preflight(database)
    if collisions:
        print(json.dumps({
            "status": "REFUSED",
            "reason": "target_or_sidecar_exists",
            "collisions": collisions,
            "mutated": False,
        }, indent=2, sort_keys=True))
        return 2

    checks: dict[str, bool] = {}
    created: list[str] = []
    owned_docs: list[Path] = []
    failure: str | None = None
    # KGStore writes raw documents under <database.parent>/documents. Record
    # whether that root already existed so cleanup can distinguish a root this
    # run created (removable when empty) from a shared/pre-existing one.
    doc_root = database.parent / "documents"
    doc_root_pre_existed = doc_root.exists()
    try:
        database.parent.mkdir(parents=True, exist_ok=True)
        run_success_case(database, checks, owned_docs)
        run_failure_case(database, checks, owned_docs)
        tables = table_inventory(database)
        created = [
            str(p)
            for p in owned_paths(database) + owned_docs
            if p.exists()
        ]
        checks["live_store_has_no_method_tables"] = not [
            t for t in tables if t.startswith(("method", "compiled_"))
        ]
    except Exception as exc:  # noqa: BLE001 - reported, never swallowed
        failure = f"{type(exc).__name__}: {exc}"
        tables = []
    finally:
        removed, leaked = [], []
        for path in owned_paths(database):
            if path.exists():
                try:
                    path.unlink()
                    removed.append(str(path))
                except OSError as exc:  # pragma: no cover - reported below
                    leaked.append(f"{path}: {exc}")
        for raw_path in owned_docs:
            try:
                if raw_path.is_file():
                    raw_path.unlink()
                    removed.append(str(raw_path))
                # Only the per-document directory this run created is removed,
                # and only when empty; the shared documents/ root is left as is.
                if raw_path.parent.is_dir() and not any(
                    raw_path.parent.iterdir()
                ):
                    raw_path.parent.rmdir()
                    removed.append(str(raw_path.parent))
            except OSError as exc:  # pragma: no cover - reported below
                leaked.append(f"{raw_path}: {exc}")
        # Remove the documents root only when this run created it and nothing
        # else is inside. A pre-existing or non-empty root is never touched.
        if not doc_root_pre_existed and doc_root.is_dir():
            try:
                if not any(doc_root.iterdir()):
                    doc_root.rmdir()
                    removed.append(str(doc_root))
            except OSError as exc:  # pragma: no cover - reported below
                leaked.append(f"{doc_root}: {exc}")

    residue = [
        str(p) for p in owned_paths(database) + owned_docs if p.exists()
    ]
    checks["owned_artifacts_absent_after_cleanup"] = not residue and not leaked
    # Truthful root accounting: a root we created must be gone; a root that
    # pre-existed must still be there.
    checks["documents_root_state_is_truthful"] = (
        doc_root.exists() if doc_root_pre_existed else not doc_root.exists()
    )
    ok = failure is None and all(checks.values())
    result = {
        "status": "PASS" if ok else "FAIL",
        "pid": os.getpid(),
        "database": str(database),
        "created_paths": created,
        "removed_paths": removed,
        "residue": residue,
        "leaked": leaked,
        "documents_root": str(doc_root),
        "documents_root_pre_existed": doc_root_pre_existed,
        "documents_root_exists_after": doc_root.exists(),
        "error": failure,
        "checks": dict(sorted(checks.items())),
        "table_inventory": tables,
        "table_count": len(tables),
    }
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
