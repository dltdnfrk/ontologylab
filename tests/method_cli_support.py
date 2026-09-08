"""Real Method import fixtures and transparent error-layer observations."""

from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path
import sqlite3
from types import TracebackType
from typing import Any

import pytest

from ontologylab.kgstore import KGStore
from ontologylab.method_ir import FieldEvidence, canonical_json_bytes, parse_method
from ontologylab.method_store import MethodStore, MethodUnitOfWork
from tests.test_method_store import _bootstrap, _occurrence, _seed


def seed_fragment_import(root: Path) -> dict[str, Any]:
    store, document, text, _ = _seed(root)
    try:
        _bootstrap(store, document)
        with MethodUnitOfWork(store.conn) as uow:
            MethodStore(store.conn, uow).import_occurrence(
                "workspace-1", _occurrence(document, text),
                extractor_engine="offline-import", extractor_model=None,
                prompt_version="method-occurrence-v1", decode_params={},
            )
    finally:
        store.close()
    fixture = Path(__file__).parent / "fixtures/methodology/method-v1-valid.json"
    payload = json.loads(fixture.read_text(encoding="utf-8"))
    payload["fragments"][0]["payload"]["temperature"]["value"] = 80.0
    payload["source_index"] = []
    return payload


def seed_bridge_fragment(root: Path, payload: dict[str, Any]) -> None:
    bridge_input = {**payload, "field_evidence": []}
    bridge_input["fragments"][0]["epistemic_class"] = "bridge_assumption"
    bridge = next(
        fragment for fragment in parse_method(bridge_input).fragments
        if fragment.id == "step-z"
    )
    store = KGStore.open(root / "kg.sqlite")
    try:
        with MethodUnitOfWork(store.conn) as uow:
            MethodStore(store.conn, uow).propose_fragment(
                "workspace-1", bridge,
                generator="human-import", parser_version="method-v1",
            )
    finally:
        store.close()


def fragment_argv(root: Path, payload: dict[str, Any]) -> tuple[str, ...]:
    path = root / "fragments.json"
    path.write_bytes(canonical_json_bytes(payload))
    return (
        "method", "fragment-import", "--workspace-id", "workspace-1",
        "--file", str(path), "--data-dir", str(root),
    )


def import_state(root: Path) -> dict[str, Any]:
    conn = sqlite3.connect(root / "kg.sqlite")
    try:
        return {
            "fragments": conn.execute(
                "SELECT id,status,epistemic_class,payload_json "
                "FROM method_fragment ORDER BY id"
            ).fetchall(),
            "evidence": conn.execute(
                "SELECT id,fragment_id,field_path,occurrence_id,evidence_role "
                "FROM method_fragment_evidence ORDER BY id"
            ).fetchall(),
            "occurrences": conn.execute(
                "SELECT id,status FROM statement_occurrence ORDER BY id"
            ).fetchall(),
            "authority_counts": tuple(
                conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                for table in (
                    "method_review_event", "method_compilation_attempt",
                    "method_compilation_gate", "method_release",
                )
            ),
            "graph": tuple(
                conn.execute(f"SELECT * FROM {table} ORDER BY id").fetchall()
                for table in ("nodes", "edges")
            ),
        }
    finally:
        conn.close()


@dataclass
class ImportCalls:
    evidence_ids: list[str] = field(default_factory=list)
    persisted_ids: list[str] = field(default_factory=list)
    failures: list[Exception] = field(default_factory=list)
    exit_errors: list[BaseException | None] = field(default_factory=list)


def observe_import(monkeypatch: pytest.MonkeyPatch) -> ImportCalls:
    calls = ImportCalls()
    original_add = MethodStore.add_fragment_evidence
    original_exit = MethodUnitOfWork.__exit__

    def add(owner: MethodStore, evidence: FieldEvidence) -> None:
        calls.evidence_ids.append(evidence.id)
        try:
            original_add(owner, evidence)
        except Exception as error:
            calls.failures.append(error)
            raise
        calls.persisted_ids.append(evidence.id)

    def exit_uow(
        owner: MethodUnitOfWork,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        calls.exit_errors.append(exc)
        original_exit(owner, exc_type, exc, traceback)

    monkeypatch.setattr(MethodStore, "add_fragment_evidence", add)
    monkeypatch.setattr(MethodUnitOfWork, "__exit__", exit_uow)
    return calls
