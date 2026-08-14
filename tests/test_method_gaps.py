from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import sys
from typing import Any

import pytest

_ROOT = str(Path(__file__).resolve().parent.parent)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from ontologylab.method_gaps import (
    DETECTOR_ID,
    DETECTOR_VERSION,
    bridge_readiness,
    detect_gaps,
    upsert_detected_gaps,
)
from ontologylab.kgstore import KGStore
from ontologylab.method_ir import (
    BridgeAssumption,
    EpistemicClass,
    canonical_json_bytes,
)
from ontologylab.method_snapshot import MethodSnapshot
from ontologylab.method_store import MethodStore, MethodUnitOfWork

FIXTURES = Path(__file__).parent / "fixtures" / "methodology" / "gaps"
EXPECTED_IDS = {
    "required_slot_missing": "gap:2a2ec3095f3b6d77111e22b58a0190e6",
    "factual_field_without_evidence": "gap:4ff9c525bd61c10e679e540c8e7457a9",
    "dangling_reference": "gap:e64ff6e3ebaba394ded35ea4980b4038",
    "step_dependency_cycle": "gap:435799c01455574c62d5544c43bb0115",
    "unreachable_step_or_result": "gap:2942761f5f21b1b90443367e2bb5ffa8",
    "type_discontinuity": "gap:7607cbf435a74188d8e82bdb16d5c18d",
    "unit_dimension_mismatch": "gap:69174db93cafea995f207990f9496b00",
    "unmeasurable_condition": "gap:9593b1824fbf21557c1df423853bb03f",
    "stale_selector": "gap:ce920f679444a0b9c8b50e8650ea8038",
    "blocked_policy": "gap:60032121f8faac1d1a4c828ccda1e472",
    "failed_fixture": "gap:065a461b107dbdc45c5d0bee47bdb517",
    "explicit_counter_evidence": "gap:584893ddd98afd8da8780b01b10646d4",
    "open_conflict": "gap:a071b7048055cc6d89835fd9b52d1e62",
}


def _load(name: str) -> dict[str, Any]:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def _snapshot(payload: dict[str, Any]) -> MethodSnapshot:
    canonical = canonical_json_bytes(payload)
    return MethodSnapshot(payload["workspace"]["id"], canonical, "sha256:unused")


def _case(gap_class: str) -> MethodSnapshot:
    payload = _load("valid.json")
    patch = _load("cases.json")[gap_class]
    payload.update(patch)
    return _snapshot(payload)


def _dependency_snapshot(
    node_ids: tuple[str, ...],
    edges: tuple[tuple[str, str], ...],
) -> MethodSnapshot:
    payload = _load("valid.json")
    payload["workspace"] = {
        "id": "workspace-dependencies",
        "scope_json": '{"fixtures":[]}',
    }
    payload["occurrences"] = []
    payload["fragments"] = [
        {
            "id": node_id,
            "kind": "step",
            "epistemic_class": "deterministic_derivation",
            "payload_json": json.dumps(
                {
                    "entry": True,
                    "name": {"state": "known", "value": node_id},
                },
                sort_keys=True,
                separators=(",", ":"),
            ),
            "status": "accepted",
        }
        for node_id in node_ids
    ]
    payload["fragment_evidence"] = []
    payload["links"] = [
        {
            "id": f"requires-{source}-{target}",
            "src_fragment_id": source,
            "dst_fragment_id": target,
            "kind": "requires",
            "status": "accepted",
        }
        for source, target in edges
    ]
    payload["policy_snapshots"] = []
    return _snapshot(payload)


def _stored_bridge_snapshot(
    tmp_path: Path,
    limits: tuple[str, ...],
) -> MethodSnapshot:
    store = KGStore.open(tmp_path / "kg.sqlite")
    try:
        with MethodUnitOfWork(store.conn) as uow:
            method = MethodStore(store.conn, uow)
            method.create_workspace(
                "workspace-bridge",
                name="Bridge readiness",
                objective="Resolve one explicit gap",
                scope={"documents": "all"},
                created_by="reviewer",
            )
            method.upsert_gap(
                "gap-bridge",
                workspace_id="workspace-bridge",
                gap_class="required_slot_missing",
                target_fragment_id=None,
                field_path=None,
                detector_id="review-seed",
                detector_version="1",
                input_snapshot_hash="sha256:" + "0" * 64,
                detail={"reason": "missing field"},
            )
            method.propose_bridge(
                "workspace-bridge",
                BridgeAssumption(
                    "bridge-ready",
                    "gap-bridge",
                    "A bounded assumption",
                    ("Reviewed by an operator",),
                    "laboratory",
                    limits,
                    "A blank result falsifies it",
                    "Replay one fixture",
                    "pending",
                    EpistemicClass.BRIDGE_ASSUMPTION,
                ),
                generator="human",
                model=None,
                prompt_version="review-v1",
            )
            method.record_counter_evidence_search(
                "search-bridge",
                workspace_id="workspace-bridge",
                gap_id="gap-bridge",
                bridge_id="bridge-ready",
                query="counter evidence",
                scope={"documents": "all"},
                corpus_snapshot_hash="sha256:" + "1" * 64,
                result_occurrence_ids=(),
                searched_by="reviewer",
            )
            method.decide(
                "bridge",
                "bridge-ready",
                "accepted_as_assumption",
                reviewer="reviewer",
                note="Explicitly accepted",
                review_event_id="review-bridge",
            )
        with MethodUnitOfWork(store.conn) as uow:
            return MethodStore(store.conn, uow).read_snapshot(
                "workspace-bridge"
            )
    finally:
        store.close()


@pytest.mark.parametrize("gap_class", tuple(EXPECTED_IDS))
def test_detector_emits_exact_stable_identity_and_valid_abstains(
    gap_class: str,
) -> None:
    positive = (
        _snapshot(_load("cycle.json"))
        if gap_class == "step_dependency_cycle"
        else _case(gap_class)
    )

    result = [gap for gap in detect_gaps(positive) if gap.gap_class == gap_class]
    abstention = [gap for gap in detect_gaps(_snapshot(_load("valid.json")))
                  if gap.gap_class == gap_class]

    assert [gap.gap_id for gap in result] == [EXPECTED_IDS[gap_class]]
    assert abstention == []
    assert result[0].detector_id == DETECTOR_ID
    assert result[0].detector_version == DETECTOR_VERSION
    assert result[0].input_snapshot_hash.startswith("sha256:")


def test_fixture_denominator_includes_error_no_output_and_unknown_rows() -> None:
    result = next(
        gap for gap in detect_gaps(_case("failed_fixture"))
        if gap.gap_class == "failed_fixture"
    )

    assert result.detail["denominator_total"] == 4
    assert result.detail["failed_fixture_ids"] == ["no-output"]
    assert result.detail["fixture_kinds"] == [
        "expected_error", "expected_no_output", "normal", "unknown"
    ]


def test_shuffled_and_repeated_inputs_keep_hashes_ids_and_order() -> None:
    payload = _load("cycle.json")
    original = detect_gaps(_snapshot(payload))
    shuffled = deepcopy(payload)
    for key in ("fragments", "links"):
        shuffled[key] = list(reversed(shuffled[key])) + shuffled[key]

    repeated = detect_gaps(_snapshot(shuffled))

    assert repeated == original


def test_bridge_evidence_never_anchors_a_source_supported_fact() -> None:
    payload = _load("valid.json")
    payload.update(_load("cases.json")["factual_field_without_evidence"])
    payload["bridges"] = [{
        "id": "bridge-1", "gap_id": "gap-1",
        "decision_status": "accepted_as_assumption",
        "epistemic_class": "bridge_assumption", "scope": "laboratory",
        "limits_json": "[\"single instrument\"]", "falsifier": "blank fails",
        "minimum_validation": "replay fixture"
    }]
    payload["bridge_evidence"] = [{
        "id": "bridge-evidence-1", "bridge_id": "bridge-1",
        "occurrence_id": "occurrence-1", "evidence_role": "supports"
    }]

    classes = {gap.gap_class for gap in detect_gaps(_snapshot(payload))}

    assert "factual_field_without_evidence" in classes


def test_bridge_readiness_requires_complete_counter_search_and_permanent_type() -> None:
    payload = _load("valid.json")
    payload["bridges"] = [{
        "id": "bridge-ready", "gap_id": "gap-1",
        "decision_status": "accepted_as_assumption",
        "epistemic_class": "bridge_assumption", "scope": "laboratory",
        "limits_json": "[\"single instrument\"]", "falsifier": "blank fails",
        "minimum_validation": "replay fixture"
    }]
    payload["counter_evidence_searches"] = [{
        "id": "search-1", "bridge_id": "bridge-ready", "gap_id": "gap-1"
    }]
    ready = bridge_readiness(_snapshot(payload))
    payload["counter_evidence_searches"] = []
    missing_search = bridge_readiness(_snapshot(payload))
    payload["bridges"][0]["epistemic_class"] = "source_supported"
    promoted = bridge_readiness(_snapshot(payload))

    assert [(row.bridge_id, row.ready) for row in ready] == [
        ("bridge-ready", True)
    ]
    assert missing_search[0].ready is False
    assert promoted[0].ready is False


@pytest.mark.parametrize(
    ("limits", "stored_json", "ready", "missing"),
    [
        ((), "[]", False, ("applicability_limits",)),
        (
            ("single instrument",),
            '["single instrument"]',
            True,
            (),
        ),
    ],
)
def test_typed_store_bridge_limits_are_parsed_semantically(
    tmp_path: Path,
    limits: tuple[str, ...],
    stored_json: str,
    ready: bool,
    missing: tuple[str, ...],
) -> None:
    snapshot = _stored_bridge_snapshot(tmp_path, limits)
    payload = json.loads(snapshot.canonical_json)
    readiness = bridge_readiness(snapshot)

    assert payload["bridges"][0]["limits_json"] == stored_json
    assert [(row.bridge_id, row.ready, row.missing) for row in readiness] == [
        ("bridge-ready", ready, missing)
    ]


@pytest.mark.parametrize(
    "limits_json",
    ["", " ", "not-json", "{}", "null", "[]", '[""]', '[" "]', "[1]"],
)
def test_bridge_limits_malformed_non_list_or_blank_fail_closed(
    limits_json: str,
) -> None:
    payload = _load("valid.json")
    payload["bridges"] = [{
        "id": "bridge-invalid-limits",
        "gap_id": "gap-1",
        "decision_status": "accepted_as_assumption",
        "epistemic_class": "bridge_assumption",
        "scope": "laboratory",
        "limits_json": limits_json,
        "falsifier": "blank fails",
        "minimum_validation": "replay fixture",
    }]
    payload["counter_evidence_searches"] = [{
        "id": "search-1",
        "bridge_id": "bridge-invalid-limits",
        "gap_id": "gap-1",
    }]

    readiness = bridge_readiness(_snapshot(payload))

    assert [
        (row.bridge_id, row.ready, row.missing) for row in readiness
    ] == [
        (
            "bridge-invalid-limits",
            False,
            ("applicability_limits",),
        )
    ]


def test_real_store_detector_converges_without_self_seeding(
    tmp_path: Path,
) -> None:
    store = KGStore.open(tmp_path / "kg.sqlite")
    try:
        with MethodUnitOfWork(store.conn) as uow:
            method = MethodStore(store.conn, uow)
            method.create_workspace(
                "workspace-convergence",
                name="Convergent detector",
                objective="Preserve reviewed conflicts",
                scope={"fixtures": []},
                created_by="reviewer",
            )
            for gap_id in ("source-open", "source-waived", "source-resolved"):
                method.upsert_gap(
                    gap_id,
                    workspace_id="workspace-convergence",
                    gap_class="open_conflict",
                    target_fragment_id=None,
                    field_path=None,
                    detector_id=f"{DETECTOR_ID}.human-review",
                    detector_version=DETECTOR_VERSION,
                    input_snapshot_hash="sha256:" + "2" * 64,
                    detail={"source": gap_id},
                )
            method.decide(
                "gap",
                "source-waived",
                "waived",
                reviewer="reviewer",
                note="Known and waived",
                review_event_id="review-waived",
            )
            method.decide(
                "gap",
                "source-resolved",
                "resolved_by_evidence",
                reviewer="reviewer",
                note="Resolved with evidence",
                review_event_id="review-resolved",
            )
        with MethodUnitOfWork(store.conn) as uow:
            method = MethodStore(store.conn, uow)
            first_snapshot = method.read_snapshot("workspace-convergence")
            first = upsert_detected_gaps(method, first_snapshot)
        with MethodUnitOfWork(store.conn) as uow:
            method = MethodStore(store.conn, uow)
            second_snapshot = method.read_snapshot("workspace-convergence")
            second = upsert_detected_gaps(method, second_snapshot)
        with MethodUnitOfWork(store.conn) as uow:
            third_snapshot = MethodStore(store.conn, uow).read_snapshot(
                "workspace-convergence"
            )
    finally:
        store.close()

    payload = json.loads(third_snapshot.canonical_json)
    stored = {row["id"]: row for row in payload["gaps"]}
    reviews = {
        (row["id"], row["subject_id"], row["decision"])
        for row in payload["review_events"]
    }

    assert [(gap.gap_class, gap.detail) for gap in first] == [
        ("open_conflict", {"recorded_gap_id": "source-open"})
    ]
    assert second == first
    assert detect_gaps(third_snapshot) == first
    assert stored["source-open"]["status"] == "open"
    assert stored["source-open"]["detector_id"] == (
        f"{DETECTOR_ID}.human-review"
    )
    assert stored["source-waived"]["status"] == "waived"
    assert stored["source-resolved"]["status"] == "resolved_by_evidence"
    assert stored[first[0].gap_id]["detector_id"] == DETECTOR_ID
    assert stored[first[0].gap_id]["detector_version"] == DETECTOR_VERSION
    assert reviews == {
        ("review-waived", "source-waived", "waived"),
        (
            "review-resolved",
            "source-resolved",
            "resolved_by_evidence",
        ),
    }


def test_deep_acyclic_dependency_chain_avoids_python_recursion() -> None:
    node_ids = tuple(f"step-{index:04d}" for index in range(1_200))
    edges = tuple(zip(node_ids, node_ids[1:]))

    cycles = [
        gap for gap in detect_gaps(_dependency_snapshot(node_ids, edges))
        if gap.gap_class == "step_dependency_cycle"
    ]

    assert cycles == []


def test_branching_acyclic_dependency_dag_emits_no_cycle() -> None:
    layers = tuple(
        tuple(f"step-{layer}-{branch}" for branch in range(3))
        for layer in range(8)
    )
    node_ids = ("step-root",) + tuple(
        node for layer in layers for node in layer
    )
    edges = [("step-root", node) for node in layers[0]]
    for sources, targets in zip(layers, layers[1:]):
        edges.extend(
            (source, target)
            for source in sources
            for target in targets
        )

    cycles = [
        gap
        for gap in detect_gaps(
            _dependency_snapshot(node_ids, tuple(edges))
        )
        if gap.gap_class == "step_dependency_cycle"
    ]

    assert cycles == []


def test_multiple_sccs_and_self_loop_emit_canonical_cycles() -> None:
    node_ids = (
        "step-a",
        "step-b",
        "step-c",
        "step-d",
        "step-e",
        "step-f",
    )
    edges = (
        ("step-a", "step-b"),
        ("step-b", "step-a"),
        ("step-b", "step-d"),
        ("step-c", "step-c"),
        ("step-d", "step-e"),
        ("step-e", "step-f"),
        ("step-f", "step-d"),
    )

    original = [
        gap
        for gap in detect_gaps(_dependency_snapshot(node_ids, edges))
        if gap.gap_class == "step_dependency_cycle"
    ]
    shuffled = [
        gap
        for gap in detect_gaps(
            _dependency_snapshot(
                tuple(reversed(node_ids)),
                tuple(reversed(edges)),
            )
        )
        if gap.gap_class == "step_dependency_cycle"
    ]

    assert original == shuffled
    assert [
        (gap.target_fragment_id, gap.detail["cycle"]) for gap in original
    ] == [
        ("step-a", ["step-a", "step-b"]),
        ("step-c", ["step-c"]),
        ("step-d", ["step-d", "step-e", "step-f"]),
    ]


class _RecordingStore:
    def __init__(self) -> None:
        self.rows: list[dict[str, Any]] = []

    def upsert_gap(self, gap_id: str, **values: Any) -> None:
        self.rows.append({"gap_id": gap_id, **values})


def test_rerun_uses_only_typed_decision_preserving_upsert() -> None:
    store = _RecordingStore()

    first = upsert_detected_gaps(store, _snapshot(_load("cycle.json")))
    second = upsert_detected_gaps(store, _snapshot(_load("cycle.json")))

    assert first == second
    assert [row["gap_id"] for row in store.rows] == [
        EXPECTED_IDS["step_dependency_cycle"],
        EXPECTED_IDS["step_dependency_cycle"],
    ]
