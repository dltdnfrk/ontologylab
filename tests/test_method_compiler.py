"""Pure non-compensatory Method compiler contracts."""

from __future__ import annotations

import builtins
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from typing import Any, Mapping, cast

import pytest

from ontologylab.method_compiler import (
    CompilationResult,
    CompileSelection,
    compile_method,
    validate_final_artifacts,
)
from ontologylab.method_compiler_artifacts import COMPILER_VERSION
from ontologylab.method_compiler_contract import (
    COMPILER_REASON_CATALOG,
    COMPILER_REASON_CATALOG_VERSION,
    CompilerReplayKindCount,
    CompilerReplayResult,
    GateId,
    replay_receipt_hash,
)
from ontologylab.method_compiler_replay import (
    MAX_REPLAY_BYTES,
    MAX_REPLAY_FIXTURES,
    MAX_REPLAY_ID_BYTES,
    MAX_REPLAY_POINTER_TOKENS,
    MAX_REPLAY_ROWS,
    MAX_REPLAY_VALUE_DEPTH,
    evaluate_replay,
)
from ontologylab.method_ir import (
    IRValidationError,
    canonical_json_bytes,
    parse_method,
)
from ontologylab.method_snapshot import MethodSnapshot


ROOT = Path(__file__).resolve().parent.parent
FIXTURES = ROOT / "tests" / "fixtures" / "methodology"
REPLAY = FIXTURES / "replay"
GOLD = ROOT / "tests" / "gold" / "methodology" / "compiler-gates.json"
HASH = "sha256:" + "a" * 64
KINDS = ("expected_output", "expected_error", "expected_no_output", "unknown")


def _hash(value: object) -> str:
    return "sha256:" + hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _raw_hash(value: str) -> str:
    return "sha256:" + hashlib.sha256(value.encode()).hexdigest()


def _fixture(name: str) -> dict[str, Any]:
    return json.loads((REPLAY / name).read_text())


def _snapshot(case: dict[str, Any]) -> MethodSnapshot:
    data = json.loads((FIXTURES / "gaps" / "valid.json").read_text())
    override = case["overrides"]
    data["workspace"].update(
        name="Method",
        method_schema_version="method-v1",
    )
    occurrence = data["occurrences"][0]
    occurrence.update(
        span_start=0,
        span_end=len(occurrence["statement_text"]),
        selected_text_hash=_raw_hash(occurrence["statement_text"]),
    )
    policy = data["policy_snapshots"][0]
    policy.update(
        source_policy_id=override.get(
            "snapshot_source_policy_id",
            "policy-1",
        ),
        resolution_status=override.get("policy_status", "resolved"),
    )
    data["source_policies"] = [{
        "id": "policy-1",
        "policy_version": "1",
        "allowed_extract": override.get("allowed_extract", 1),
        "allowed_pack": override.get("allowed_pack", 1),
        "allowed_processors_json": json.dumps(
            override.get("allowed_processors", ["local"]),
            separators=(",", ":"),
        ),
        "allowed_regions_json": json.dumps(
            override.get("allowed_regions", ["local"]),
            separators=(",", ":"),
        ),
    }]
    if override.get("missing_policy"):
        data["source_policies"] = []
    if override.get("missing_policy_snapshot"):
        data["policy_snapshots"] = []
    if override.get("duplicate_policy_snapshot"):
        data["policy_snapshots"].append({
            **policy,
            "id": "policy-snapshot-duplicate",
        })
    step = next(row for row in data["fragments"] if row["id"] == "step-1")
    step["epistemic_class"] = (
        "bridge_assumption"
        if override.get("bridge_as_evidence")
        else "source_supported"
    )
    data["fragment_evidence"] = [{
        "id": "evidence-1",
        "fragment_id": "step-1",
        "field_path": "/name",
        "occurrence_id": occurrence["id"],
        "evidence_role": "supports",
    }]
    if override.get("stale_source"):
        occurrence["document_content_hash"] = "sha256:" + "b" * 64
    if override.get("invalid_unit") or override.get("invalid_dimension"):
        payload = json.loads(data["fragments"][0]["payload_json"])
        payload["bad_unit"] = {"dimension": "volume", "symbol": "bogus"}
        payload["bad_dimension"] = {"dimension": "mass", "symbol": "mL"}
        payload["missing_ref_id"] = "missing"
        data["fragments"][0]["payload_json"] = json.dumps(
            payload, sort_keys=True, separators=(",", ":")
        )
    if override.get("cycle"):
        data["links"].append({
            "id": "link-cycle",
            "src_fragment_id": "step-1",
            "dst_fragment_id": "input-1",
            "kind": "precedes",
            "status": "accepted",
        })
    if override.get("discontinuity"):
        result = next(
            row for row in data["fragments"] if row["id"] == "result-1"
        )
        payload = json.loads(result["payload_json"])
        payload["input_type"] = "other"
        result["payload_json"] = json.dumps(
            payload, sort_keys=True, separators=(",", ":")
        )
    data["gaps"] = []
    if override.get("blocking_conflict"):
        data["gaps"].append({
            "id": "gap-blocking",
            "gap_class": "open_conflict",
            "target_fragment_id": "step-1",
            "field_path": None,
            "detail_json": '{"scope":"compatible"}',
            "status": "open",
        })
    if override.get("unscoped_conflict"):
        data["gaps"].append({
            "id": "gap-unscoped",
            "gap_class": "open_conflict",
            "target_fragment_id": "step-1",
            "field_path": None,
            "detail_json": "{}",
            "status": "open",
        })
    decisions = [
        ("occurrence", row["id"], row["status"])
        for row in data["occurrences"]
    ] + [
        (kind, row["id"], row["status"])
        for kind in ("fragment", "link")
        for row in data[f"{kind}s"]
    ]
    data["review_events"] = [{
        "id": f"review-{subject}",
        "subject_kind": kind,
        "subject_id": subject,
        "decision": decision,
        "reviewer": "reviewer-1",
        "note": "approved",
        "workspace_id": data["workspace"]["id"],
    } for kind, subject, decision in decisions]
    if override.get("pending_proposal"):
        step["status"] = "proposed"
    if override.get("missing_decision") or override.get("pending_proposal"):
        data["review_events"] = [
            row for row in data["review_events"]
            if row["subject_id"] != "step-1"
        ]
    if override.get("self_approval"):
        data["review_events"][0]["reviewer"] = "method-compiler-v1"
    if override.get("agent_reviewer"):
        data["review_events"][0]["reviewer"] = "agent-1"
    canonical = canonical_json_bytes(data)
    return MethodSnapshot(data["workspace"]["id"], canonical, _hash(data))


def _compile(name: str):
    case = _fixture(name)
    return compile_method(
        _snapshot(case),
        CompileSelection("attempt-1", "release-1", "method-1", 1),
        case["fixtures"],
    )


@pytest.mark.parametrize(
    "name",
    [
        "gate-all-clear.json",
        "gate-g0-rights.json",
        "gate-g1-stale-source.json",
        "gate-g2-bridge-evidence.json",
        "gate-g3-structure.json",
        "gate-g4-graph.json",
        "gate-g5-conflicts.json",
        "gate-g6-decisions.json",
        "gate-g7-replay.json",
    ],
)
def test_each_named_gate_fixture_has_exact_independent_result(name: str) -> None:
    case = _fixture(name)
    result = _compile(name)
    failed = [gate.gate_id.value for gate in result.gates if not gate.passed]
    reasons = {
        gate.gate_id.value: list(gate.reasons)
        for gate in result.gates if gate.reasons
    }
    assert failed == case["expected"]["failed_gates"]
    assert reasons == case["expected"]["reasons"]
    assert tuple(gate.gate_id for gate in result.gates) == tuple(GateId)
    assert result.passed is (not failed)


def test_gold_catalog_is_exact_shared_reason_catalog() -> None:
    gold = json.loads(GOLD.read_text())
    assert gold["catalog_version"] == COMPILER_REASON_CATALOG_VERSION
    assert gold["gates"] == {
        gate.value: list(COMPILER_REASON_CATALOG[gate])
        for gate in GateId
    }


def test_multiple_failures_evaluate_every_gate_without_score_or_any() -> None:
    case = _fixture("gate-noncompensatory.json")
    result = _compile("gate-noncompensatory.json")
    assert [gate.gate_id.value for gate in result.gates] == [
        gate.value for gate in GateId
    ]
    assert [
        gate.gate_id.value for gate in result.gates if not gate.passed
    ] == case["expected"]["failed_gates"]
    assert result.passed is False
    assert not hasattr(result, "score")


def test_replay_denominator_covers_all_kinds_without_execution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def forbidden(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("declarative replay tried to execute")

    for name in ("exec", "eval", "compile", "__import__"):
        monkeypatch.setattr(builtins, name, forbidden)
    result = _compile("gate-all-clear.json")
    assert result.replay_receipt.fixture_count == 4
    assert result.replay_receipt.result_count == 4
    assert tuple(
        row.kind for row in result.replay_receipt.kind_counts
    ) == KINDS
    assert sum(
        row.passed_count for row in result.replay_receipt.kind_counts
    ) == 4


def test_unordered_permutations_produce_identical_artifacts() -> None:
    case = _fixture("gate-all-clear.json")
    snapshot = _snapshot(case)
    payload = json.loads(snapshot.canonical_json)
    for value in payload.values():
        if isinstance(value, list):
            value.reverse()
    permuted = replace(
        snapshot,
        canonical_json=canonical_json_bytes(payload),
        content_hash=_hash(payload),
    )
    selection = CompileSelection("attempt-1", "release-1", "method-1", 1)
    first = compile_method(snapshot, selection, case["fixtures"])
    second = compile_method(permuted, selection, reversed(case["fixtures"]))
    assert first.canonical_envelope == second.canonical_envelope


def test_two_processes_produce_byte_identical_artifacts() -> None:
    code = (
        "from tests.test_method_compiler import _compile;"
        "print(_compile('gate-all-clear.json').canonical_envelope.decode())"
    )
    command = [sys.executable, "-c", code]
    assert subprocess.check_output(command, cwd=ROOT) == subprocess.check_output(
        command, cwd=ROOT
    )


def test_no_explicit_selection_builds_preview_without_release() -> None:
    case = _fixture("gate-all-clear.json")
    result = compile_method(_snapshot(case), None, case["fixtures"])
    assert result.release_id is None
    assert result.receipt is None


def test_g1_uses_raw_selected_text_hash_not_json_string_hash() -> None:
    case = _fixture("gate-all-clear.json")
    snapshot = _snapshot(case)
    accepted = compile_method(snapshot, None, case["fixtures"])
    assert accepted.gates[1].passed

    data = json.loads(snapshot.canonical_json)
    occurrence = data["occurrences"][0]
    occurrence["selected_text_hash"] = _hash(occurrence["statement_text"])
    canonical = canonical_json_bytes(data)
    mismatched = compile_method(
        MethodSnapshot(snapshot.workspace_id, canonical, _hash(data)),
        None,
        case["fixtures"],
    )
    assert mismatched.gates[1].reasons == ("mismatched-selector",)


@pytest.mark.parametrize(
    ("override", "reason"),
    (
        ({"policy_status": "denied"}, "rights-denied"),
        ({"policy_status": "ambiguous"}, "rights-ambiguous"),
        ({"policy_status": "discovery_only"}, "rights-unresolved"),
        ({"allowed_extract": 0}, "rights-denied"),
        ({"allowed_pack": 0}, "rights-denied"),
        ({"allowed_processors": ["remote"]}, "rights-denied"),
        ({"allowed_regions": ["remote"]}, "rights-denied"),
        ({"allowed_processors": [1, "local"]}, "rights-denied"),
        ({"allowed_regions": [True, "local"]}, "rights-denied"),
        ({"missing_policy": True}, "rights-unresolved"),
        ({"missing_policy_snapshot": True}, "rights-unresolved"),
        (
            {"snapshot_source_policy_id": "policy-other"},
            "rights-unresolved",
        ),
        (
            {"duplicate_policy_snapshot": True},
            "rights-ambiguous",
        ),
    ),
)
def test_g0_requires_each_release_rights_axis(
    override: dict[str, Any],
    reason: str,
) -> None:
    case = _fixture("gate-all-clear.json")
    case["overrides"] = override
    result = compile_method(_snapshot(case), None, case["fixtures"])
    assert result.gates[0].reasons == (reason,)


def test_g8_validates_final_artifacts_and_full_receipt_bindings() -> None:
    case = _fixture("gate-all-clear.json")
    snapshot = _snapshot(case)
    selection = CompileSelection("attempt-1", "release-1", "method-1", 1)
    result = compile_method(snapshot, selection, case["fixtures"])
    receipt = result.receipt
    assert receipt is not None
    assert validate_final_artifacts(
        result,
        snapshot,
        selection,
        immutable=True,
    ).passed

    replay_result = result.replay_receipt.results[0]
    mutations = (
        replace(result, method_json={**result.method_json, "id": "other"}),
        replace(result, source_index=()),
        replace(result, method_json_bytes=b"{}"),
        replace(result, source_index_bytes=b"[]"),
        replace(result, canonical_envelope=b"{}"),
        replace(result, content_hash="sha256:" + "0" * 64),
        replace(
            result,
            receipt=replace(receipt, release_id="other-release"),
        ),
        replace(
            result,
            receipt=replace(
                receipt,
                fixture_set_hash="sha256:" + "0" * 64,
            ),
        ),
        replace(
            result,
            receipt=replace(
                receipt,
                replay_fixture_count=receipt.replay_fixture_count + 1,
            ),
        ),
        replace(
            result,
            receipt=replace(
                receipt,
                replay_result_count=receipt.replay_result_count + 1,
            ),
        ),
        replace(
            result,
            receipt=replace(
                receipt,
                replay_receipt_hash="sha256:" + "0" * 64,
            ),
        ),
        replace(
            result,
            receipt=replace(
                receipt,
                gates=(
                    replace(receipt.gates[0], passed=False),
                    *receipt.gates[1:],
                ),
            ),
        ),
        replace(
            result,
            receipt=replace(
                receipt,
                policy_snapshots=(),
            ),
        ),
        replace(
            result,
            receipt=replace(
                receipt,
                accepted_objects=(),
            ),
        ),
        replace(
            result,
            receipt=replace(
                receipt,
                assumption_gap_inventory_hash="sha256:" + "0" * 64,
            ),
        ),
        replace(
            result,
            receipt=replace(
                receipt,
                reviewer_receipt_hash="sha256:" + "0" * 64,
            ),
        ),
        replace(
            result,
            receipt=replace(receipt, reason_catalog_version="other"),
        ),
        replace(
            result,
            receipt=replace(
                receipt,
                input_snapshot_hash="sha256:" + "0" * 64,
            ),
        ),
        replace(
            result,
            receipt=replace(receipt, compiler_version="other"),
        ),
        replace(
            result,
            receipt=replace(receipt, method_schema_version="other"),
        ),
        replace(result, receipt=replace(receipt, release_version=2)),
        replace(
            result,
            replay_receipt=replace(
                result.replay_receipt,
                results=(
                    replace(replay_result, passed=not replay_result.passed),
                    *result.replay_receipt.results[1:],
                ),
            ),
        ),
        replace(result, receipt=None),
    )
    for mutated in mutations:
        assert not validate_final_artifacts(
            mutated,
            snapshot,
            selection,
            immutable=True,
        ).passed
    assert validate_final_artifacts(
        result,
        snapshot,
        selection,
        immutable=False,
    ).reasons == ("release-not-immutable",)


def test_g8_is_mandatory_for_blocked_selected_compiles() -> None:
    case = _fixture("gate-g0-rights.json")
    result = compile_method(
        _snapshot(case),
        CompileSelection("attempt-1", "release-1", "method-1", 1),
        case["fixtures"],
    )
    assert [gate.gate_id for gate in result.gates] == list(GateId)
    assert result.gates[-1].passed
    assert result.receipt is not None
    assert result.receipt.gates[-1] == result.gates[-1]


def test_selected_compile_invokes_mandatory_final_g8_validator(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import ontologylab.method_compiler as compiler

    called = 0
    original = compiler.validate_final_artifacts

    def observe(
        result: CompilationResult,
        snapshot: MethodSnapshot,
        selection: CompileSelection,
        *,
        immutable: bool,
    ):
        nonlocal called
        called += 1
        return original(
            result,
            snapshot,
            selection,
            immutable=immutable,
        )

    monkeypatch.setattr(compiler, "validate_final_artifacts", observe)
    _compile("gate-all-clear.json")
    assert called == 1


def test_receipt_binds_catalog_and_complete_replay_results() -> None:
    result = _compile("gate-all-clear.json")
    receipt = result.receipt
    replay = result.replay_receipt
    assert receipt is not None
    assert receipt.reason_catalog_version == COMPILER_REASON_CATALOG_VERSION
    assert receipt.replay_fixture_count == replay.fixture_count
    assert receipt.replay_result_count == replay.result_count
    assert receipt.replay_kind_counts == replay.kind_counts
    assert receipt.replay_results == replay.results
    assert receipt.replay_receipt_hash == replay.receipt_hash
    mutated = (
        replace(replay.results[0], passed=not replay.results[0].passed),
        *replay.results[1:],
    )
    assert replay_receipt_hash(
        replay.fixture_set_hash,
        replay.fixture_count,
        replay.result_count,
        replay.kind_counts,
        mutated,
    ) != replay.receipt_hash
    assert all(
        type(row) is CompilerReplayKindCount for row in replay.kind_counts
    )
    assert all(type(row) is CompilerReplayResult for row in replay.results)


def _nested_value(depth: int) -> object:
    value: object = "leaf"
    for _ in range(depth):
        value = [value]
    return value


def _error_fixture(
    fixture_id: object,
    path: object = "/missing",
) -> dict[str, Any]:
    return {
        "id": fixture_id,
        "kind": "expected_error",
        "query": {"op": "get", "path": path},
    }


def _replay_reasons(
    fixtures: object,
    method: Mapping[str, Any] | None = None,
) -> tuple[str, ...]:
    rows = cast("Any", fixtures)
    _, gate = evaluate_replay(method or {}, rows)
    return gate.reasons


def test_replay_rejects_unknown_ops_types_escapes_and_id_collisions() -> None:
    invalid = (
        [_error_fixture("exec") | {"query": {"op": "exec", "path": "/"}}],
        [_error_fixture("numeric-path", 1)],
        [{
            "id": "list-field",
            "kind": "expected_no_output",
            "query": {
                "op": "select",
                "path": "/rows",
                "where": {},
                "field": [],
            },
        }],
        [{
            "id": "list-where",
            "kind": "expected_no_output",
            "query": {
                "op": "select",
                "path": "/rows",
                "where": [],
                "field": "/id",
            },
        }],
        [_error_fixture("bad-escape", "/bad~2token")],
        [_error_fixture("same"), _error_fixture("same")],
        [_error_fixture("é"), _error_fixture("e\u0301")],
        [_error_fixture(1)],
    )
    for fixtures in invalid:
        assert _replay_reasons(fixtures) == ("invalid-replay-fixture",)


def test_replay_comparison_preserves_exact_json_scalar_types() -> None:
    fixtures = [{
        "id": "bool-is-not-int",
        "kind": "expected_output",
        "expected": 1,
        "query": {"op": "get", "path": "/flag"},
    }]
    assert _replay_reasons(
        fixtures,
        {"flag": True},
    ) == (
        "expected-error-omitted",
        "fixture-failed",
        "no-output-omitted",
        "unknown-output-omitted",
    )

    select = [{
        "id": "bool-filter-is-not-int-filter",
        "kind": "expected_no_output",
        "query": {
            "op": "select",
            "path": "/rows",
            "where": {"id": True},
            "field": "/id",
        },
    }]
    receipt, gate = evaluate_replay({"rows": [{"id": 1}]}, select)
    assert receipt.results[0].passed
    assert "fixture-failed" not in gate.reasons


def test_replay_limits_accept_boundary_and_reject_boundary_plus_one() -> None:
    fixture_boundary = [
        _error_fixture(f"fixture-{index}")
        for index in range(MAX_REPLAY_FIXTURES)
    ]
    assert "replay-limit-exceeded" not in _replay_reasons(fixture_boundary)
    assert _replay_reasons(
        [*fixture_boundary, _error_fixture("fixture-over")]
    ) == ("replay-limit-exceeded",)

    id_boundary = "a" * MAX_REPLAY_ID_BYTES
    assert "replay-limit-exceeded" not in _replay_reasons(
        [_error_fixture(id_boundary)]
    )
    assert _replay_reasons(
        [_error_fixture(id_boundary + "a")]
    ) == ("replay-limit-exceeded",)

    path_boundary = "/" + "/".join(
        "a" for _ in range(MAX_REPLAY_POINTER_TOKENS)
    )
    assert "replay-limit-exceeded" not in _replay_reasons(
        [_error_fixture("pointer-boundary", path_boundary)]
    )
    assert _replay_reasons(
        [_error_fixture("pointer-over", path_boundary + "/a")]
    ) == ("replay-limit-exceeded",)

    value_fixture = {
        "id": "value-boundary",
        "kind": "expected_output",
        "expected": _nested_value(MAX_REPLAY_VALUE_DEPTH - 3),
        "query": {"op": "get", "path": "/missing"},
    }
    assert "replay-limit-exceeded" not in _replay_reasons([value_fixture])
    value_fixture["expected"] = _nested_value(MAX_REPLAY_VALUE_DEPTH - 2)
    assert _replay_reasons([value_fixture]) == ("replay-limit-exceeded",)

    rows = [{"id": index} for index in range(MAX_REPLAY_ROWS)]
    select = [{
        "id": "row-boundary",
        "kind": "expected_no_output",
        "query": {
            "op": "select",
            "path": "/rows",
            "where": {"id": -1},
            "field": "/id",
        },
    }]
    assert "replay-limit-exceeded" not in _replay_reasons(
        select,
        {"rows": rows},
    )
    assert _replay_reasons(
        select,
        {"rows": [*rows, {"id": MAX_REPLAY_ROWS}]},
    ) == ("replay-limit-exceeded",)

    byte_fixture = {
        "id": "byte-boundary",
        "kind": "expected_output",
        "expected": "",
        "query": {"op": "get", "path": "/missing"},
    }
    base_size = len(canonical_json_bytes([byte_fixture]))
    byte_fixture["expected"] = "a" * (MAX_REPLAY_BYTES - base_size)
    assert "replay-limit-exceeded" not in _replay_reasons([byte_fixture])
    byte_fixture["expected"] += "a"
    assert _replay_reasons([byte_fixture]) == ("replay-limit-exceeded",)


def test_replay_rejects_extreme_inputs_without_recursion_or_execution() -> None:
    assert _replay_reasons(
        [_error_fixture("x" * 100_000)]
    ) == ("replay-limit-exceeded",)
    assert _replay_reasons(
        [_error_fixture(f"row-{index}") for index in range(10_000)]
    ) == ("replay-limit-exceeded",)
    assert _replay_reasons(
        [{
            "id": "deep",
            "kind": "expected_output",
            "expected": _nested_value(5_000),
            "query": {"op": "get", "path": "/missing"},
        }]
    ) == ("replay-limit-exceeded",)


@pytest.mark.parametrize(
    "override",
    (
        {"pending_proposal": True},
        {"agent_reviewer": True},
    ),
)
def test_g6_requires_terminal_named_human_decisions(
    override: dict[str, Any],
) -> None:
    case = _fixture("gate-all-clear.json")
    case["overrides"] = override
    result = compile_method(_snapshot(case), None, case["fixtures"])
    assert not result.gates[6].passed


@pytest.mark.parametrize(
    "mutation",
    ("empty-note", "wrong-decision", "wrong-workspace", "duplicate-review"),
)
def test_g6_validates_review_content_and_exact_workspace(
    mutation: str,
) -> None:
    case = _fixture("gate-all-clear.json")
    snapshot = _snapshot(case)
    data = json.loads(snapshot.canonical_json)
    review = next(
        row for row in data["review_events"]
        if row["subject_id"] == "step-1"
    )
    if mutation == "empty-note":
        review["note"] = ""
    elif mutation == "wrong-decision":
        review["decision"] = "rejected"
    elif mutation == "wrong-workspace":
        review["workspace_id"] = "other"
    else:
        data["review_events"].append({**review, "id": "duplicate-review"})
    canonical = canonical_json_bytes(data)
    result = compile_method(
        MethodSnapshot(snapshot.workspace_id, canonical, _hash(data)),
        None,
        case["fixtures"],
    )
    assert result.gates[6].reasons == ("missing-human-decision",)


# Every field ``method_ir_codec.parse_method`` accepts at the document root.
_METHOD_V1_FIELDS = frozenset({
    "schema_version", "id", "version", "name", "fragments", "field_evidence",
    "links", "gaps", "bridge_assumptions", "review_receipts", "gate_results",
    "source_index", "release",
})


def _typed_snapshot(case: dict[str, Any]) -> MethodSnapshot:
    """A snapshot whose payloads match what ``propose_fragment`` persists.

    Fragments reach the store as ``canonical_json`` of a parsed
    ``MethodFragment``, so every payload value is a TypedValue. The gate
    fixtures hand-write a looser shape that no import path can produce, so
    retype them here: this test is about IR conformance, not gate outcomes.
    """
    snapshot = _snapshot(case)
    data = json.loads(snapshot.canonical_json)
    for fragment in data["fragments"]:
        payload = json.loads(fragment["payload_json"])
        fragment["payload_json"] = json.dumps(
            {key: {"state": "unknown", "kind": "string"} for key in payload},
            sort_keys=True,
            separators=(",", ":"),
        )
    canonical = canonical_json_bytes(data)
    return MethodSnapshot(data["workspace"]["id"], canonical, _hash(data))


def test_compiled_artifact_conforms_to_the_method_v1_ir_schema() -> None:
    """The compiler stamps its artifact ``method-v1``; this checks the claim.

    Nothing in the product ever fed a compiled artifact back through the
    method-v1 parser, so the emitter and the codec could drift apart while
    both kept the name. They have not: the artifact's root is the codec's
    field set exactly, and a compile over production-shaped payloads parses
    as ``MethodIR``.

    ``release`` is the one deliberate divergence and it is structural, not an
    oversight. The artifact's own hash is ``canonical_hash(method)``, so the
    document cannot carry it without hashing itself; the compiler emits a
    stub and the release record holds the real receipt. Completing that stub
    from values the compiler already has is the entire delta, which is why
    the stub is asserted before the completion rather than glossed over.
    """
    case = _fixture("gate-all-clear.json")
    snapshot = _typed_snapshot(case)
    result = compile_method(
        snapshot,
        CompileSelection("attempt-1", "release-1", "method-1", 1),
        case["fixtures"],
    )
    artifact = dict(result.method_json)
    assert set(artifact) == _METHOD_V1_FIELDS
    assert artifact["schema_version"] == "method-v1"
    assert {gate["gate"] for gate in artifact["gate_results"]} == {
        f"G{index}" for index in range(9)
    }

    assert artifact["release"] == {"id": "release-1", "content_hash": None}
    with pytest.raises(IRValidationError, match=r"\$\.release"):
        parse_method(dict(artifact))

    assert result.content_hash is not None
    artifact["release"] = {
        "id": "release-1",
        "workspace_id": snapshot.workspace_id,
        "version": 1,
        "compiler_version": COMPILER_VERSION,
        "content_hash": result.content_hash,
    }
    parsed = parse_method(artifact)
    assert parsed.schema_version == "method-v1"
    assert {fragment.id for fragment in parsed.fragments} == {
        row["id"] for row in result.method_json["fragments"]
    }
