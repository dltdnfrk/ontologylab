"""Typed compiler-receipt, gate-row, and release persistence contracts."""

from __future__ import annotations

from dataclasses import replace
import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Any

import pytest

from ontologylab.kgstore import KGStore
from ontologylab.main import main
from ontologylab.method_ir import (
    EpistemicClass,
    EvidenceRole,
    FieldEvidence,
    FragmentKind,
    MethodFragment,
    TypedValue,
    ValueKind,
    ValueState,
    canonical_json_bytes,
)
from ontologylab.method_release_store import canonical_release_envelope
from ontologylab.method_store import (
    MethodConflictError,
    MethodStateError,
    MethodStore,
    MethodUnitOfWork,
    MethodValidationError,
)
from ontologylab.method_snapshot import (
    CompilationGateResult,
    CompilerAcceptedObject,
    CompilerPolicySnapshot,
    CompilerReceipt,
    CompilerReplayKindCount,
    CompilerReplayResult,
    GateId,
    canonical_compiler_receipt,
)
from ontologylab.method_compiler_contract import (
    COMPILER_REASON_CATALOG_VERSION,
    COMPILER_REPLAY_KINDS,
    replay_receipt_hash,
)
from tests.test_method_store import _bootstrap, _occurrence, _seed


METHOD_JSON = {
    "id": "method-1",
    "schema_version": "method-v1",
    "version": 1,
}
SOURCE_INDEX = ({"field": "temperature", "occurrence_id": "occ-1"},)
REVIEW_RECEIPT = {"reviewer": "reviewer-1", "decision": "approved"}
EXPECTED_REASON_CATALOG = {
    GateId.G0: (
        "rights-ambiguous",
        "rights-denied",
        "rights-unresolved",
    ),
    GateId.G1: (
        "mismatched-selector",
        "missing-source-anchor",
        "stale-source-anchor",
    ),
    GateId.G2: (
        "bridge-as-verified-evidence",
        "epistemic-class-mixed",
    ),
    GateId.G3: (
        "fabricated-value",
        "invalid-dimension",
        "invalid-reference",
        "invalid-unit",
        "unsupported-schema-keyword",
    ),
    GateId.G4: (
        "dangling-reference",
        "input-output-discontinuity",
        "step-dependency-cycle",
        "unreachable-output",
    ),
    GateId.G5: (
        "blocking-conflict",
        "unscoped-conflict",
    ),
    GateId.G6: (
        "missing-human-decision",
        "self-approval",
    ),
    GateId.G7: (
        "expected-error-omitted",
        "fixture-failed",
        "invalid-replay-fixture",
        "no-output-omitted",
        "replay-limit-exceeded",
        "unknown-output-omitted",
    ),
    GateId.G8: (
        "canonical-artifact-hash-mismatch",
        "receipt-binding-mismatch",
        "release-not-immutable",
    ),
}


def _hash(value: Any) -> str:
    return "sha256:" + hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _receipt(
    *,
    attempt_id: str = "attempt-1",
    release_id: str = "release-1",
    input_snapshot_hash: str = "sha256:" + "1" * 64,
    failed_gate: GateId | None = None,
) -> CompilerReceipt:
    gates = tuple(
        CompilationGateResult(
            gate_id,
            gate_id is not failed_gate,
            (
                ()
                if gate_id is not failed_gate
                else (EXPECTED_REASON_CATALOG[gate_id][0],)
            ),
        )
        for gate_id in GateId
    )
    fixture_set_hash = "sha256:" + "4" * 64
    replay_kind_counts = tuple(
        CompilerReplayKindCount(kind, 0, 0)
        for kind in COMPILER_REPLAY_KINDS
    )
    receipt = CompilerReceipt(
        attempt_id=attempt_id,
        release_id=release_id,
        workspace_id="workspace-1",
        release_version=1,
        method_schema_version="method-v1",
        compiler_version="method-compiler-v1",
        input_snapshot_hash=input_snapshot_hash,
        policy_snapshots=(
            CompilerPolicySnapshot("snapshot-1", "1"),
        ),
        accepted_objects=(
            CompilerAcceptedObject(
                "occ-1",
                "sha256:" + "2" * 64,
                "sha256:" + "3" * 64,
            ),
        ),
        method_json_hash=_hash(METHOD_JSON),
        source_index_hash=_hash(SOURCE_INDEX),
        fixture_set_hash=fixture_set_hash,
        reason_catalog_version=COMPILER_REASON_CATALOG_VERSION,
        replay_fixture_count=0,
        replay_result_count=0,
        replay_kind_counts=replay_kind_counts,
        replay_results=(),
        replay_receipt_hash=replay_receipt_hash(
            fixture_set_hash,
            0,
            0,
            replay_kind_counts,
            (),
        ),
        gates=gates,
        assumption_gap_inventory_hash="sha256:" + "5" * 64,
        reviewer_receipt_hash=_hash(REVIEW_RECEIPT),
        passed=failed_gate is None,
        content_hash=None,
    )
    if failed_gate is None:
        return canonical_release_envelope(
            METHOD_JSON, SOURCE_INDEX, receipt
        ).receipt
    return receipt


def _record(method: MethodStore, receipt: CompilerReceipt) -> None:
    method.record_compilation_attempt(receipt)


def _release(method: MethodStore, receipt: CompilerReceipt) -> None:
    method.insert_release(
        method_id="method-1",
        method_json=METHOD_JSON,
        source_index=SOURCE_INDEX,
        compiler_receipt=receipt,
        review_receipt=REVIEW_RECEIPT,
    )


def _bound_receipt(
    store: Any, receipt: CompilerReceipt,
) -> CompilerReceipt:
    with MethodUnitOfWork(store.conn) as uow:
        snapshot = MethodStore(store.conn, uow).read_compilation_snapshot(
            "workspace-1"
        )
    unbound = replace(
        receipt,
        input_snapshot_hash=snapshot.content_hash,
        content_hash=None,
    )
    if unbound.passed:
        return canonical_release_envelope(
            METHOD_JSON, SOURCE_INDEX, unbound
        ).receipt
    return unbound


def _ordinary_release_rows(
    receipt: CompilerReceipt | None = None,
) -> dict[str, Any]:
    payload = json.loads(
        canonical_compiler_receipt(receipt or _receipt()).json
    )
    receipt_payload = {key: value for key, value in payload.items()
                       if key != "content_hash"}
    payload["content_hash"] = _hash({
        "method_json": METHOD_JSON,
        "source_index": SOURCE_INDEX,
        "receipt": receipt_payload,
    })
    receipt_json = canonical_json_bytes(payload).decode()
    receipt_hash = _hash(payload)
    gate_receipt = canonical_json_bytes({
        gate["gate_id"]: gate["passed"] for gate in payload["gates"]
    }).decode()
    return {
        "payload": payload,
        "gates": [
            [
                payload["attempt_id"],
                payload["workspace_id"],
                gate["gate_id"],
                int(gate["passed"]),
                canonical_json_bytes(gate["reasons"]).decode(),
                receipt_hash,
                receipt_json,
            ]
            for gate in payload["gates"]
        ],
        "attempt": [
            payload["attempt_id"],
            payload["workspace_id"],
            payload["release_id"],
            payload["compiler_version"],
            payload["input_snapshot_hash"],
            int(payload["passed"]),
            gate_receipt,
            receipt_json,
            receipt_hash,
            1.0,
        ],
        "release": [
            payload["release_id"],
            payload["workspace_id"],
            "method-1",
            payload["release_version"],
            canonical_json_bytes(METHOD_JSON).decode(),
            canonical_json_bytes(SOURCE_INDEX).decode(),
            payload["content_hash"],
            payload["compiler_version"],
            payload["input_snapshot_hash"],
            gate_receipt,
            canonical_json_bytes(REVIEW_RECEIPT).decode(),
            receipt_json,
            receipt_hash,
            payload["attempt_id"],
            1.0,
        ],
    }


def _rebuild_ordinary_rows(
    rows: dict[str, Any], *, content_hash: str | None = None,
) -> None:
    payload = rows["payload"]
    receipt = {key: value for key, value in payload.items()
               if key != "content_hash"}
    payload["content_hash"] = content_hash or _hash({
            "method_json": METHOD_JSON,
            "source_index": SOURCE_INDEX,
            "receipt": receipt,
        })
    receipt_json = canonical_json_bytes(payload).decode()
    receipt_hash = _hash(payload)
    gate_receipt = canonical_json_bytes({
        gate["gate_id"]: gate["passed"] for gate in payload["gates"]
    }).decode()
    rows["gates"] = [
        [
            payload["attempt_id"],
            payload["workspace_id"],
            gate["gate_id"],
            int(gate["passed"]),
            canonical_json_bytes(gate["reasons"]).decode(),
            receipt_hash,
            receipt_json,
        ]
        for gate in payload["gates"]
    ]
    rows["attempt"][2:9] = [
        payload["release_id"],
        payload["compiler_version"],
        payload["input_snapshot_hash"],
        int(payload["passed"]),
        gate_receipt,
        receipt_json,
        receipt_hash,
    ]
    rows["release"][0] = payload["release_id"]
    rows["release"][3] = payload["release_version"]
    rows["release"][6:14] = [
        payload["content_hash"],
        payload["compiler_version"],
        payload["input_snapshot_hash"],
        gate_receipt,
        canonical_json_bytes(REVIEW_RECEIPT).decode(),
        receipt_json,
        receipt_hash,
        payload["attempt_id"],
    ]


def _insert_ordinary_rows(conn: sqlite3.Connection, rows: dict[str, Any]) -> None:
    for gate in rows["gates"]:
        conn.execute(
            "INSERT INTO method_compilation_gate VALUES (?,?,?,?,?,?,?)",
            gate,
        )
    conn.execute(
        "INSERT INTO method_compilation_attempt VALUES "
        "(?,?,?,?,?,?,?,?,?,?)",
        rows["attempt"],
    )
    conn.execute(
        "INSERT INTO method_release VALUES "
        "(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        rows["release"],
    )


def _valid_ordinary_rows(store: Any) -> dict[str, Any]:
    with MethodUnitOfWork(store.conn) as uow:
        snapshot = MethodStore(store.conn, uow).read_compilation_snapshot(
            "workspace-1"
        )
    return _ordinary_release_rows(
        _receipt(input_snapshot_hash=snapshot.content_hash)
    )


def _compilation_row_counts(
    conn: sqlite3.Connection,
) -> tuple[int, int, int]:
    return tuple(
        conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        for table in (
            "method_compilation_attempt",
            "method_compilation_gate",
            "method_release",
        )
    )


def test_ordinary_sql_rejects_unknown_reason_code(tmp_path: Path) -> None:
    store, document, _, _ = _seed(tmp_path)
    try:
        _bootstrap(store, document)
        rows = _valid_ordinary_rows(store)
        rows["payload"]["gates"][0]["reasons"] = ["unknown-reason-code"]
        _rebuild_ordinary_rows(rows)

        with pytest.raises(sqlite3.IntegrityError):
            with store.conn:
                _insert_ordinary_rows(store.conn, rows)

        assert _compilation_row_counts(store.conn) == (0, 0, 0)
    finally:
        store.close()


def test_complete_receipt_persists_exact_attempt_and_nine_bound_gates(
    tmp_path: Path,
) -> None:
    store, document, _, _ = _seed(tmp_path)
    receipt = _receipt(failed_gate=GateId.G4)
    try:
        _bootstrap(store, document)
        receipt = _bound_receipt(store, receipt)
        canonical = canonical_compiler_receipt(receipt)
        with MethodUnitOfWork(store.conn) as uow:
            _record(MethodStore(store.conn, uow), receipt)

        attempt = store.conn.execute(
            "SELECT compiler_receipt_json, compiler_receipt_hash, "
            "gate_receipt_json, passed FROM method_compilation_attempt "
            "WHERE id=?",
            (receipt.attempt_id,),
        ).fetchone()
        assert tuple(attempt) == (
            canonical.json,
            canonical.receipt_hash,
            canonical.gate_summary_json,
            0,
        )
        gates = tuple(
            tuple(row)
            for row in store.conn.execute(
                "SELECT attempt_id, workspace_id, gate_id, passed, "
                "reasons_json, compiler_receipt_hash "
                "FROM method_compilation_gate WHERE attempt_id=? "
                "ORDER BY gate_id",
                (receipt.attempt_id,),
            )
        )
        assert gates == tuple(
            (
                receipt.attempt_id,
                receipt.workspace_id,
                gate.gate_id.value,
                int(gate.passed),
                canonical_json_bytes(gate.reasons).decode("utf-8"),
                canonical.receipt_hash,
            )
            for gate in receipt.gates
        )
    finally:
        store.close()


@pytest.mark.parametrize(
    "invalid_receipt",
    [
        {f"G{index}": True for index in range(9)},
        {
            f"G{index}": {"passed": True, "reasons": []}
            for index in range(9)
        },
    ],
)
def test_untyped_bool_or_nested_gate_mappings_are_rejected(
    tmp_path: Path, invalid_receipt: Any,
) -> None:
    store, document, _, _ = _seed(tmp_path)
    try:
        _bootstrap(store, document)
        with pytest.raises(MethodValidationError, match="CompilerReceipt"):
            with MethodUnitOfWork(store.conn) as uow:
                MethodStore(store.conn, uow).record_compilation_attempt(
                    invalid_receipt
                )
        assert store.conn.execute(
            "SELECT COUNT(*) FROM method_compilation_attempt"
        ).fetchone()[0] == 0
    finally:
        store.close()


def test_receipt_requires_exact_ordered_g0_through_g8(tmp_path: Path) -> None:
    store, document, _, _ = _seed(tmp_path)
    receipt = _receipt()
    try:
        _bootstrap(store, document)
        with pytest.raises(MethodValidationError, match="G0-G8"):
            with MethodUnitOfWork(store.conn) as uow:
                _record(
                    MethodStore(store.conn, uow),
                    replace(receipt, gates=receipt.gates[:8]),
                )
        assert store.conn.execute(
            "SELECT COUNT(*) FROM method_compilation_gate"
        ).fetchone()[0] == 0
    finally:
        store.close()


def test_receipt_reason_codes_are_canonical_machine_codes() -> None:
    receipt = _receipt(failed_gate=GateId.G4)
    invalid_gate = replace(receipt.gates[4], reasons=("Bad reason",))
    with pytest.raises(MethodValidationError, match="unknown code"):
        canonical_compiler_receipt(replace(
            receipt,
            gates=receipt.gates[:4] + (invalid_gate,) + receipt.gates[5:],
        ))


@pytest.mark.parametrize(
    "mutation",
    (
        "catalog",
        "fixture-count",
        "result-count",
        "kind-count",
        "result",
        "replay-hash",
    ),
)
def test_receipt_rejects_each_replay_and_catalog_binding_mutation(
    mutation: str,
) -> None:
    receipt = _receipt()
    if mutation == "catalog":
        altered = replace(receipt, reason_catalog_version="other")
    elif mutation == "fixture-count":
        altered = replace(receipt, replay_fixture_count=1)
    elif mutation == "result-count":
        altered = replace(receipt, replay_result_count=1)
    elif mutation == "kind-count":
        kind = receipt.replay_kind_counts[0]
        altered = replace(
            receipt,
            replay_kind_counts=(
                replace(kind, fixture_count=1),
                *receipt.replay_kind_counts[1:],
            ),
        )
    elif mutation == "result":
        altered = replace(
            receipt,
            replay_results=(
                CompilerReplayResult(
                    "fixture-1",
                    "expected_output",
                    False,
                ),
            ),
        )
    else:
        altered = replace(
            receipt,
            replay_receipt_hash="sha256:" + "0" * 64,
        )
    with pytest.raises(MethodValidationError):
        canonical_compiler_receipt(altered)


@pytest.mark.parametrize(
    ("reasons", "message"),
    [
        (("unknown-reason-code",), "unknown"),
        (("missing-source-anchor",), "not valid for G4"),
        (("dependency cycle found",), "unknown"),
        (
            ("dangling-reference", "dangling-reference"),
            "sorted unique",
        ),
        (
            ("unreachable-output", "dangling-reference"),
            "sorted unique",
        ),
        ((), "failed gate requires reasons"),
    ],
)
def test_receipt_rejects_invalid_g4_reason_sets(
    reasons: tuple[str, ...],
    message: str,
) -> None:
    receipt = _receipt(failed_gate=GateId.G4)
    invalid_gate = replace(receipt.gates[4], reasons=reasons)
    with pytest.raises(MethodValidationError, match=message):
        canonical_compiler_receipt(
            replace(
                receipt,
                gates=receipt.gates[:4] + (invalid_gate,) + receipt.gates[5:],
            )
        )


def test_passing_gate_requires_empty_reasons() -> None:
    receipt = _receipt()
    invalid_gate = replace(
        receipt.gates[4],
        reasons=("dangling-reference",),
    )
    with pytest.raises(MethodValidationError, match="passing gate"):
        canonical_compiler_receipt(
            replace(
                receipt,
                gates=receipt.gates[:4] + (invalid_gate,) + receipt.gates[5:],
            )
        )


def test_every_passing_gate_accepts_exact_empty_reasons() -> None:
    for gate_id in GateId:
        receipt = _receipt()
        gate_index = tuple(GateId).index(gate_id)
        valid_gate = replace(
            receipt.gates[gate_index],
            reasons=(),
        )
        canonical_compiler_receipt(
            replace(
                receipt,
                gates=(
                    receipt.gates[:gate_index]
                    + (valid_gate,)
                    + receipt.gates[gate_index + 1:]
                ),
            )
        )


def test_compiler_reason_catalog_is_complete_and_gate_specific() -> None:
    from ontologylab.method_compiler_contract import (
        COMPILER_REASON_CATALOG,
        COMPILER_REASON_CATALOG_VERSION,
    )

    assert COMPILER_REASON_CATALOG_VERSION == "method-compiler-reasons-v1"
    assert COMPILER_REASON_CATALOG == EXPECTED_REASON_CATALOG
    all_codes = [
        code
        for codes in COMPILER_REASON_CATALOG.values()
        for code in codes
    ]
    assert len(all_codes) == len(set(all_codes))


@pytest.mark.parametrize(
    ("gate_id", "reason"),
    [
        (gate_id, reason)
        for gate_id, reasons in EXPECTED_REASON_CATALOG.items()
        for reason in reasons
    ],
)
def test_every_catalog_reason_can_describe_its_failed_gate(
    gate_id: GateId,
    reason: str,
) -> None:
    receipt = _receipt(failed_gate=gate_id)
    gate_index = tuple(GateId).index(gate_id)
    valid_gate = replace(receipt.gates[gate_index], reasons=(reason,))
    canonical_compiler_receipt(
        replace(
            receipt,
            gates=(
                receipt.gates[:gate_index]
                + (valid_gate,)
                + receipt.gates[gate_index + 1:]
            ),
        )
    )


def test_release_persists_full_canonical_envelope_and_receipt(
    tmp_path: Path,
) -> None:
    store, document, _, _ = _seed(tmp_path)
    receipt = _receipt()
    try:
        _bootstrap(store, document)
        receipt = _bound_receipt(store, receipt)
        envelope = canonical_release_envelope(METHOD_JSON, SOURCE_INDEX, receipt)
        with MethodUnitOfWork(store.conn) as uow:
            method = MethodStore(store.conn, uow)
            _record(method, receipt)
            _release(method, receipt)

        row = store.conn.execute(
            "SELECT canonical_json, source_index_json, content_hash, "
            "compiler_receipt_json, compiler_receipt_hash, attempt_id, "
            "input_snapshot_hash, compiler_version, gate_receipt_json "
            "FROM method_release WHERE id=?",
            (receipt.release_id,),
        ).fetchone()
        canonical = canonical_compiler_receipt(receipt)
        assert tuple(row) == (
            envelope.method_json,
            envelope.source_index,
            envelope.content_hash,
            canonical.json,
            canonical.receipt_hash,
            receipt.attempt_id,
            receipt.input_snapshot_hash,
            receipt.compiler_version,
            canonical.gate_summary_json,
        )
        assert envelope.content_hash != _hash(METHOD_JSON)
    finally:
        store.close()


def test_failed_attempt_persists_but_cannot_create_release(
    tmp_path: Path,
) -> None:
    store, document, _, _ = _seed(tmp_path)
    receipt = _receipt(failed_gate=GateId.G3)
    try:
        _bootstrap(store, document)
        receipt = _bound_receipt(store, receipt)
        with MethodUnitOfWork(store.conn) as uow:
            _record(MethodStore(store.conn, uow), receipt)
        assert store.conn.execute(
            "SELECT passed FROM method_compilation_attempt WHERE id=?",
            (receipt.attempt_id,),
        ).fetchone()[0] == 0
        assert store.conn.execute(
            "SELECT COUNT(*) FROM method_compilation_gate WHERE attempt_id=?",
            (receipt.attempt_id,),
        ).fetchone()[0] == 9
        with pytest.raises(MethodStateError, match="passed"):
            with MethodUnitOfWork(store.conn) as uow:
                _release(MethodStore(store.conn, uow), receipt)
        assert store.conn.execute(
            "SELECT COUNT(*) FROM method_release"
        ).fetchone()[0] == 0
    finally:
        store.close()


@pytest.mark.parametrize(
    ("table", "trigger_sql"),
    [
        (
            "method_compilation_attempt",
            "CREATE TRIGGER injected_attempt_failure BEFORE INSERT ON "
            "method_compilation_attempt BEGIN SELECT RAISE(ABORT, "
            "'injected attempt failure'); END",
        ),
        (
            "method_compilation_gate",
            "CREATE TRIGGER injected_gate_failure BEFORE INSERT ON "
            "method_compilation_gate WHEN NEW.gate_id='G4' BEGIN "
            "SELECT RAISE(ABORT, 'injected gate failure'); END",
        ),
    ],
)
def test_attempt_or_middle_gate_failure_rolls_back_every_receipt_row(
    tmp_path: Path, table: str, trigger_sql: str,
) -> None:
    store, document, _, _ = _seed(tmp_path)
    receipt = _receipt()
    try:
        _bootstrap(store, document)
        receipt = _bound_receipt(store, receipt)
        store.conn.execute(trigger_sql)
        store.conn.commit()
        with pytest.raises(MethodConflictError):
            with MethodUnitOfWork(store.conn) as uow:
                _record(MethodStore(store.conn, uow), receipt)
        assert store.conn.execute(
            "SELECT COUNT(*) FROM method_compilation_attempt"
        ).fetchone()[0] == 0
        assert store.conn.execute(
            "SELECT COUNT(*) FROM method_compilation_gate"
        ).fetchone()[0] == 0
        assert store.conn.execute(
            f"SELECT name FROM sqlite_master WHERE type='table' AND name='{table}'"
        ).fetchone()[0] == table
    finally:
        store.close()


def test_release_failure_rolls_back_attempt_gates_and_release(
    tmp_path: Path,
) -> None:
    store, document, _, _ = _seed(tmp_path)
    receipt = _receipt()
    try:
        _bootstrap(store, document)
        receipt = _bound_receipt(store, receipt)
        store.conn.execute(
            "CREATE TRIGGER injected_release_failure BEFORE INSERT ON "
            "method_release BEGIN SELECT RAISE(ABORT, "
            "'injected release failure'); END"
        )
        store.conn.commit()
        with pytest.raises(MethodConflictError):
            with MethodUnitOfWork(store.conn) as uow:
                method = MethodStore(store.conn, uow)
                _record(method, receipt)
                _release(method, receipt)
        for table in (
            "method_compilation_attempt",
            "method_compilation_gate",
            "method_release",
        ):
            assert store.conn.execute(
                f"SELECT COUNT(*) FROM {table}"
            ).fetchone()[0] == 0
    finally:
        store.close()


def test_gate_constraints_and_append_only_triggers_block_sql_bypass(
    tmp_path: Path,
) -> None:
    store, document, _, _ = _seed(tmp_path)
    receipt = _receipt(failed_gate=GateId.G5)
    try:
        _bootstrap(store, document)
        receipt = _bound_receipt(store, receipt)
        with MethodUnitOfWork(store.conn) as uow:
            _record(MethodStore(store.conn, uow), receipt)
        canonical = canonical_compiler_receipt(receipt)
        values = (
            receipt.attempt_id,
            receipt.workspace_id,
            "G9",
            1,
            "[]",
            canonical.receipt_hash,
            canonical.json,
        )
        with pytest.raises(sqlite3.IntegrityError):
            store.conn.execute(
                "INSERT INTO method_compilation_gate VALUES (?,?,?,?,?,?,?)",
                values,
            )
        store.conn.rollback()
        with pytest.raises(sqlite3.IntegrityError):
            store.conn.execute(
                "INSERT INTO method_compilation_gate VALUES (?,?,?,?,?,?,?)",
                (
                    receipt.attempt_id,
                    receipt.workspace_id,
                    "G0",
                    1,
                    "[]",
                    canonical.receipt_hash,
                    canonical.json,
                ),
            )
        store.conn.rollback()
        for operation in ("UPDATE", "DELETE"):
            sql = (
                "UPDATE method_compilation_gate SET reasons_json=reasons_json"
                if operation == "UPDATE"
                else "DELETE FROM method_compilation_gate"
            )
            with pytest.raises(sqlite3.IntegrityError, match="append-only"):
                store.conn.execute(sql)
            store.conn.rollback()
    finally:
        store.close()


def test_precompilation_snapshot_is_stable_and_full_snapshot_has_outputs(
    tmp_path: Path,
) -> None:
    store, document, _, _ = _seed(tmp_path)
    try:
        _bootstrap(store, document)
        with MethodUnitOfWork(store.conn) as uow:
            method = MethodStore(store.conn, uow)
            before_input = method.read_compilation_snapshot("workspace-1")
            before_full = method.read_snapshot("workspace-1")
        receipt = _receipt(
            input_snapshot_hash=before_input.content_hash,
            failed_gate=GateId.G2,
        )
        with MethodUnitOfWork(store.conn) as uow:
            _record(MethodStore(store.conn, uow), receipt)
        with MethodUnitOfWork(store.conn) as uow:
            method = MethodStore(store.conn, uow)
            after_input = method.read_compilation_snapshot("workspace-1")
            after_full = method.read_snapshot("workspace-1")

        assert after_input == before_input
        assert after_full.content_hash != before_full.content_hash
        payload = json.loads(after_full.canonical_json)
        assert payload["compilation_attempts"][0][
            "compiler_receipt_hash"
        ] == canonical_compiler_receipt(receipt).receipt_hash
        assert [row["gate_id"] for row in payload["compilation_gates"]] == [
            gate.value for gate in GateId
        ]
        assert payload["releases"] == []
    finally:
        store.close()


def test_ordinary_sql_cannot_publish_inconsistent_release(
    tmp_path: Path,
) -> None:
    store, document, _, _ = _seed(tmp_path)
    receipt_hash = "sha256:" + "a" * 64
    snapshot_hash = "sha256:" + "b" * 64
    try:
        _bootstrap(store, document)
        with pytest.raises(sqlite3.IntegrityError):
            with MethodUnitOfWork(store.conn):
                for gate_id in GateId:
                    store.conn.execute(
                        "INSERT INTO method_compilation_gate VALUES "
                        "(?,?,?,?,?,?,?)",
                        (
                            "attempt-bad",
                            "workspace-1",
                            gate_id.value,
                            1,
                            "not-canonical-json",
                            receipt_hash,
                            "plain text, not CompilerReceipt",
                        ),
                    )
                store.conn.execute(
                    "INSERT INTO method_compilation_attempt VALUES "
                    "(?,?,?,?,?,?,?,?,?,?)",
                    (
                        "attempt-bad",
                        "workspace-1",
                        "release-bad",
                        "compiler-unsupported",
                        snapshot_hash,
                        1,
                        "{bad gate summary}",
                        "plain text, not CompilerReceipt",
                        receipt_hash,
                        1.0,
                    ),
                )
                store.conn.execute(
                    "INSERT INTO method_release VALUES "
                    "(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        "release-bad",
                        "workspace-1",
                        "method-bad",
                        1,
                        "{not canonical method}",
                        "[not source index]",
                        "sha256:" + "c" * 64,
                        "compiler-unsupported",
                        snapshot_hash,
                        "{bad gate summary}",
                        "{not review receipt}",
                        "plain text, not CompilerReceipt",
                        receipt_hash,
                        "attempt-bad",
                        1.0,
                    ),
                )

        with MethodUnitOfWork(store.conn) as uow:
            snapshot = MethodStore(store.conn, uow).read_snapshot("workspace-1")
        assert json.loads(snapshot.canonical_json)["releases"] == []
    finally:
        store.close()


@pytest.mark.parametrize(
    "case",
    (
        "unsupported-compiler",
        "noncanonical-reasons",
        "non-json-reasons",
        "partial-receipt",
        "wrong-receipt",
        "unrelated-receipt-hash",
        "unrelated-content-hash",
        "invalid-method-json",
        "invalid-source-json",
        "method-only-envelope",
        "attempt-snapshot-mismatch",
        "forged-snapshot",
        "gate-receipt-mismatch",
        "release-version-mismatch",
        "unrelated-method-id",
        "noncanonical-method-json",
        "noncanonical-source-json",
        "invalid-review-receipt",
    ),
)
def test_ordinary_sql_rejects_semantically_unbound_release_rows(
    tmp_path: Path, case: str,
) -> None:
    store, document, _, _ = _seed(tmp_path)
    try:
        _bootstrap(store, document)
        rows = _valid_ordinary_rows(store)
        if case == "unsupported-compiler":
            rows["payload"]["compiler_version"] = "compiler-unsupported"
            _rebuild_ordinary_rows(rows)
        elif case == "noncanonical-reasons":
            rows["gates"][0][4] = '[ "bad-code" ]'
        elif case == "non-json-reasons":
            rows["gates"][0][4] = "bad-code"
        elif case == "partial-receipt":
            rows["attempt"][7] = "{}"
        elif case == "wrong-receipt":
            rows["attempt"][7] = canonical_json_bytes({
                **rows["payload"], "release_id": "release-wrong",
            }).decode()
        elif case == "unrelated-receipt-hash":
            rows["attempt"][8] = "sha256:" + "a" * 64
            rows["release"][12] = rows["attempt"][8]
            for gate in rows["gates"]:
                gate[5] = rows["attempt"][8]
        elif case == "unrelated-content-hash":
            rows["release"][6] = "sha256:" + "b" * 64
        elif case == "invalid-method-json":
            rows["release"][4] = "{not-json}"
        elif case == "invalid-source-json":
            rows["release"][5] = "[not-json]"
        elif case == "method-only-envelope":
            method_only = _hash(METHOD_JSON)
            _rebuild_ordinary_rows(rows, content_hash=method_only)
        elif case == "attempt-snapshot-mismatch":
            rows["attempt"][4] = "sha256:" + "c" * 64
            rows["release"][8] = rows["attempt"][4]
        elif case == "forged-snapshot":
            rows["payload"]["input_snapshot_hash"] = "sha256:" + "c" * 64
            _rebuild_ordinary_rows(rows)
        elif case == "release-version-mismatch":
            rows["release"][3] = 2
        elif case == "unrelated-method-id":
            rows["release"][2] = "method-unrelated"
        elif case == "noncanonical-method-json":
            rows["release"][4] = json.dumps(METHOD_JSON, indent=2)
        elif case == "noncanonical-source-json":
            rows["release"][5] = json.dumps(SOURCE_INDEX, indent=2)
        elif case == "invalid-review-receipt":
            rows["release"][10] = "[]"
        else:
            rows["attempt"][6] = '{"G0":false}'
            rows["release"][9] = rows["attempt"][6]

        with pytest.raises(sqlite3.IntegrityError):
            with MethodUnitOfWork(store.conn):
                _insert_ordinary_rows(store.conn, rows)
        with MethodUnitOfWork(store.conn) as uow:
            snapshot = MethodStore(store.conn, uow).read_snapshot("workspace-1")
        assert json.loads(snapshot.canonical_json)["releases"] == []
    finally:
        store.close()


def test_ordinary_sql_accepts_only_fully_related_canonical_rows(
    tmp_path: Path,
) -> None:
    store, document, _, _ = _seed(tmp_path)
    try:
        _bootstrap(store, document)
        rows = _valid_ordinary_rows(store)
        with MethodUnitOfWork(store.conn):
            _insert_ordinary_rows(store.conn, rows)
        with MethodUnitOfWork(store.conn) as uow:
            snapshot = MethodStore(store.conn, uow).read_snapshot("workspace-1")
        assert [row["id"] for row in json.loads(
            snapshot.canonical_json
        )["releases"]] == ["release-1"]
    finally:
        store.close()


def _compiler_fixtures(*, passing: bool) -> list[dict[str, Any]]:
    if not passing:
        return [{
            "id": "failed-output",
            "kind": "expected_output",
            "expected": "wrong",
            "query": {
                "op": "get",
                "path": "/id",
            },
        }]
    return [
        {
            "id": "expected-output",
            "kind": "expected_output",
            "expected": "method-1",
            "query": {
                "op": "get",
                "path": "/id",
            },
        },
        {
            "id": "expected-error",
            "kind": "expected_error",
            "query": {
                "op": "get",
                "path": "/does-not-exist",
            },
        },
        {
            "id": "expected-no-output",
            "kind": "expected_no_output",
            "query": {
                "field": "/id",
                "op": "select",
                "path": "/fragments",
                "where": {
                    "id": "absent",
                },
            },
        },
        {
            "id": "unknown-output",
            "kind": "unknown",
            "query": {
                "op": "get",
                "path": "/unknown",
            },
        },
    ]


def test_compiler_caller_persists_failed_attempt_and_nine_gates(
    tmp_path: Path,
) -> None:
    from ontologylab.method_compiler import (
        CompileSelection,
        compile_and_persist,
    )
    store, document, _, _ = _seed(tmp_path)
    try:
        _bootstrap(store, document)
        with MethodUnitOfWork(store.conn) as uow:
            method = MethodStore(store.conn, uow)
            result = compile_and_persist(
                method,
                method.read_compilation_snapshot("workspace-1"),
                CompileSelection("attempt-compiler", "release-blocked", "method-1", 1),
                _compiler_fixtures(passing=False),
            )
        assert result.passed is False
        assert store.conn.execute(
            "SELECT COUNT(*) FROM method_compilation_attempt "
            "WHERE id='attempt-compiler'"
        ).fetchone()[0] == 1
        assert store.conn.execute(
            "SELECT COUNT(*) FROM method_compilation_gate "
            "WHERE attempt_id='attempt-compiler'"
        ).fetchone()[0] == 9
        assert store.conn.execute(
            "SELECT COUNT(*) FROM method_release "
            "WHERE id='release-blocked'"
        ).fetchone()[0] == 0
    finally:
        store.close()


def test_compiler_g1_accepts_real_persisted_raw_selector_hash(
    tmp_path: Path,
) -> None:
    from ontologylab.method_compiler import compile_method

    store, document, text, _ = _seed(tmp_path)
    try:
        _bootstrap(store, document)
        occurrence = _occurrence(document, text)
        fragment = MethodFragment(
            "fragment-g1",
            FragmentKind.STEP,
            EpistemicClass.SOURCE_SUPPORTED,
            {
                "temperature": TypedValue(
                    ValueState.KNOWN,
                    ValueKind.REAL,
                    80,
                ),
            },
        )
        with MethodUnitOfWork(store.conn) as uow:
            method = MethodStore(store.conn, uow)
            method.import_occurrence(
                "workspace-1",
                occurrence,
                extractor_engine="offline",
                extractor_model=None,
                prompt_version="occurrence-v1",
                decode_params={},
            )
            method.propose_fragment(
                "workspace-1",
                fragment,
                generator="human-import",
                parser_version="method-v1",
            )
            method.add_fragment_evidence(FieldEvidence(
                "evidence-g1",
                "fragment-g1",
                "/temperature",
                occurrence.id,
                EvidenceRole.SUPPORTS,
            ))
            method.decide(
                "occurrence",
                occurrence.id,
                "accepted",
                reviewer="human-1",
                note="exact raw selector",
            )
            method.decide(
                "fragment",
                fragment.id,
                "accepted",
                reviewer="human-1",
                note="field is source supported",
            )
        with MethodUnitOfWork(store.conn) as uow:
            snapshot = MethodStore(
                store.conn,
                uow,
            ).read_compilation_snapshot("workspace-1")
        result = compile_method(
            snapshot,
            None,
            _compiler_fixtures(passing=True),
        )
        assert result.gates[1].passed
    finally:
        store.close()


def test_compile_cli_commits_blocked_outcome_before_exit_two(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    store, document, _, _ = _seed(tmp_path)
    _bootstrap(store, document)
    store.close()
    fixtures = tmp_path / "blocked-fixtures.json"
    fixtures.write_bytes(canonical_json_bytes(
        _compiler_fixtures(passing=False)
    ))

    with pytest.raises(SystemExit) as exit_info:
        main([
            "method",
            "compile",
            "--workspace-id",
            "workspace-1",
            "--fixtures",
            str(fixtures),
            "--attempt-id",
            "attempt-cli-blocked",
            "--release-id",
            "release-cli-blocked",
            "--method-id",
            "method-1",
            "--release-version",
            "1",
            "--data-dir",
            str(tmp_path),
        ])
    assert exit_info.value.code == 2
    assert "failed compiler gates: G7" in capsys.readouterr().err

    reopened = KGStore.open(tmp_path / "kg.sqlite")
    try:
        row = reopened.conn.execute(
            "SELECT passed, compiler_receipt_json "
            "FROM method_compilation_attempt "
            "WHERE id='attempt-cli-blocked'"
        ).fetchone()
        assert row is not None
        assert row[0] == 0
        assert json.loads(row[1])["passed"] is False
        assert reopened.conn.execute(
            "SELECT COUNT(*) FROM method_compilation_gate "
            "WHERE attempt_id='attempt-cli-blocked'"
        ).fetchone()[0] == 9
        assert reopened.conn.execute(
            "SELECT COUNT(*) FROM method_release "
            "WHERE id='release-cli-blocked'"
        ).fetchone()[0] == 0
    finally:
        reopened.close()


def test_compiler_caller_publishes_only_explicit_passing_release(
    tmp_path: Path,
) -> None:
    from ontologylab.method_compiler import (
        CompileSelection,
        compile_and_persist,
    )
    store, document, _, _ = _seed(tmp_path)
    try:
        _bootstrap(store, document)
        with MethodUnitOfWork(store.conn) as uow:
            method = MethodStore(store.conn, uow)
            result = compile_and_persist(
                method,
                method.read_compilation_snapshot("workspace-1"),
                CompileSelection("attempt-compiler", "release-compiler", "method-1", 1),
                _compiler_fixtures(passing=True),
            )
        assert result.passed is True
        row = store.conn.execute(
            "SELECT id, version, content_hash FROM method_release "
            "WHERE id='release-compiler'"
        ).fetchone()
        assert tuple(row[:2]) == ("release-compiler", 1)
        assert row[2] == result.content_hash
    finally:
        store.close()


@pytest.mark.parametrize("seam", ["attempt", "middle-gate", "release"])
def test_compiler_caller_rolls_back_every_injected_persistence_failure(
    tmp_path: Path,
    seam: str,
) -> None:
    from ontologylab.method_compiler import (
        CompileSelection,
        compile_and_persist,
    )
    store, document, _, _ = _seed(tmp_path)
    try:
        _bootstrap(store, document)
        with pytest.raises(RuntimeError, match=seam):
            with MethodUnitOfWork(store.conn) as uow:
                method = MethodStore(store.conn, uow)
                compile_and_persist(
                    method,
                    method.read_compilation_snapshot("workspace-1"),
                    CompileSelection(
                        "attempt-injected",
                        "release-injected",
                        "method-1",
                        1,
                    ),
                    _compiler_fixtures(passing=True),
                    inject_failure=seam,
                )
        assert store.conn.execute(
            "SELECT COUNT(*) FROM method_compilation_attempt "
            "WHERE id='attempt-injected'"
        ).fetchone()[0] == 0
        assert store.conn.execute(
            "SELECT COUNT(*) FROM method_compilation_gate "
            "WHERE attempt_id='attempt-injected'"
        ).fetchone()[0] == 0
        assert store.conn.execute(
            "SELECT COUNT(*) FROM method_release "
            "WHERE id='release-injected'"
        ).fetchone()[0] == 0
    finally:
        store.close()
