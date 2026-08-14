#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""Usage: qa_method_gaps.py --cycle CYCLE --valid VALID [--malformed BAD]."""

from __future__ import annotations

import argparse
import ast
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import tokenize
from typing import Any

_ROOT = str(Path(__file__).resolve().parent.parent)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from ontologylab.kgstore import KGStore
from ontologylab.method_gaps import (
    DETECTOR_ID,
    DETECTOR_VERSION,
    GapInputError,
    bridge_readiness,
    detect_gaps,
    upsert_detected_gaps,
)
from ontologylab.method_ir import (
    BridgeAssumption,
    EpistemicClass,
    canonical_json_bytes,
)
from ontologylab.method_snapshot import MethodSnapshot
from ontologylab.method_store import MethodStore, MethodUnitOfWork

_GRAPH_CASES = ("deep-chain", "branching-dag", "self-loop", "multi-scc")
_OWNED_PYTHON = (
    "ontologylab/method_gaps.py",
    "scripts/qa_method_gaps.py",
    "tests/test_method_gaps.py",
)


def _read_snapshot(path: Path) -> MethodSnapshot:
    try:
        raw = path.read_text(encoding="utf-8")
        payload = json.loads(raw)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise GapInputError(f"fixture is not readable JSON: {path}") from exc
    if not isinstance(payload, dict):
        raise GapInputError("fixture root must be an object")
    workspace = payload.get("workspace")
    if not isinstance(workspace, dict) or not isinstance(workspace.get("id"), str):
        raise GapInputError("fixture workspace.id must be a string")
    canonical = canonical_json_bytes(payload)
    return MethodSnapshot(workspace["id"], canonical, "sha256:fixture")


def _inner(path: Path) -> int:
    try:
        results = [gap.to_dict() for gap in detect_gaps(_read_snapshot(path))]
    except GapInputError as exc:
        print(json.dumps(
            {"error": {"type": "GapInputError", "message": str(exc)}},
            sort_keys=True,
        ), file=sys.stderr)
        return 2
    print(json.dumps(results, sort_keys=True))
    return 1 if results else 0


def _dependency_snapshot(case: str) -> MethodSnapshot:
    if case == "deep-chain":
        nodes = tuple(f"step-{index:04d}" for index in range(1_200))
        edges = list(zip(nodes, nodes[1:]))
    elif case == "branching-dag":
        layers = tuple(
            tuple(f"step-{layer}-{branch}" for branch in range(4))
            for layer in range(32)
        )
        nodes = ("step-root",) + tuple(
            node for layer in layers for node in layer
        )
        edges = [("step-root", node) for node in layers[0]]
        for sources, targets in zip(layers, layers[1:]):
            edges.extend(
                (source, target)
                for source in sources
                for target in targets
            )
    elif case == "self-loop":
        nodes = ("step-self",)
        edges = [("step-self", "step-self")]
    elif case == "multi-scc":
        nodes = (
            "step-a",
            "step-b",
            "step-c",
            "step-d",
            "step-e",
            "step-f",
        )
        edges = [
            ("step-a", "step-b"),
            ("step-b", "step-a"),
            ("step-b", "step-d"),
            ("step-c", "step-c"),
            ("step-d", "step-e"),
            ("step-e", "step-f"),
            ("step-f", "step-d"),
        ]
    else:
        raise GapInputError(f"unknown graph case: {case}")

    payload = {
        "workspace": {
            "id": f"workspace-{case}",
            "scope_json": '{"fixtures":[]}',
        },
        "fragments": [
            {
                "id": node,
                "kind": "step",
                "epistemic_class": "deterministic_derivation",
                "payload_json": json.dumps(
                    {
                        "entry": True,
                        "name": {"state": "known", "value": node},
                    },
                    sort_keys=True,
                    separators=(",", ":"),
                ),
                "status": "accepted",
            }
            for node in nodes
        ],
        "links": [
            {
                "id": f"requires-{source}-{target}",
                "src_fragment_id": source,
                "dst_fragment_id": target,
                "kind": "requires",
                "status": "accepted",
            }
            for source, target in edges
        ],
    }
    canonical = canonical_json_bytes(payload)
    return MethodSnapshot(
        f"workspace-{case}",
        canonical,
        "sha256:manual-graph-probe",
    )


def _inner_graph(case: str) -> int:
    results = [gap.to_dict() for gap in detect_gaps(
        _dependency_snapshot(case)
    )]
    print(json.dumps(results, sort_keys=True))
    return 1 if results else 0


def _inner_store(path: Path) -> int:
    store = KGStore.open(path)
    try:
        with MethodUnitOfWork(store.conn) as uow:
            method = MethodStore(store.conn, uow)
            method.create_workspace(
                "workspace-store-probe",
                name="Store probe",
                objective="Observe gap detector convergence",
                scope={"fixtures": []},
                created_by="reviewer",
            )
            for suffix, limits in (
                ("empty", ()),
                ("full", ("single instrument",)),
            ):
                gap_id = f"gap-{suffix}"
                bridge_id = f"bridge-{suffix}"
                method.upsert_gap(
                    gap_id,
                    workspace_id="workspace-store-probe",
                    gap_class="required_slot_missing",
                    target_fragment_id=None,
                    field_path=None,
                    detector_id="review-seed",
                    detector_version="1",
                    input_snapshot_hash="sha256:" + "3" * 64,
                    detail={"bridge": suffix},
                )
                method.propose_bridge(
                    "workspace-store-probe",
                    BridgeAssumption(
                        bridge_id,
                        gap_id,
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
                    f"search-{suffix}",
                    workspace_id="workspace-store-probe",
                    gap_id=gap_id,
                    bridge_id=bridge_id,
                    query="counter evidence",
                    scope={"documents": "all"},
                    corpus_snapshot_hash="sha256:" + "4" * 64,
                    result_occurrence_ids=(),
                    searched_by="reviewer",
                )
                method.decide(
                    "bridge",
                    bridge_id,
                    "accepted_as_assumption",
                    reviewer="reviewer",
                    note="Explicitly accepted",
                    review_event_id=f"review-{bridge_id}",
                )
            for gap_id in (
                "source-open",
                "source-waived",
                "source-resolved",
            ):
                method.upsert_gap(
                    gap_id,
                    workspace_id="workspace-store-probe",
                    gap_class="open_conflict",
                    target_fragment_id=None,
                    field_path=None,
                    detector_id=f"{DETECTOR_ID}.human-review",
                    detector_version=DETECTOR_VERSION,
                    input_snapshot_hash="sha256:" + "5" * 64,
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
            first_snapshot = method.read_snapshot("workspace-store-probe")
            first = upsert_detected_gaps(method, first_snapshot)
        with MethodUnitOfWork(store.conn) as uow:
            method = MethodStore(store.conn, uow)
            second_snapshot = method.read_snapshot("workspace-store-probe")
            second = upsert_detected_gaps(method, second_snapshot)
        with MethodUnitOfWork(store.conn) as uow:
            third_snapshot = MethodStore(store.conn, uow).read_snapshot(
                "workspace-store-probe"
            )
    finally:
        store.close()

    payload = json.loads(third_snapshot.canonical_json)
    readiness = {
        row.bridge_id: row for row in bridge_readiness(third_snapshot)
    }
    bridge_rows = {row["id"]: row for row in payload["bridges"]}
    gap_rows = {row["id"]: row for row in payload["gaps"]}
    own_rows = [
        row
        for row in payload["gaps"]
        if row.get("detector_id") == DETECTOR_ID
        and row.get("detector_version") == DETECTOR_VERSION
    ]
    malformed_ready = []
    for raw_limits in (
        "",
        " ",
        "not-json",
        "{}",
        "null",
        "[]",
        '[""]',
        '[" "]',
        "[1]",
    ):
        malformed_payload = json.loads(third_snapshot.canonical_json)
        bridge = next(
            row
            for row in malformed_payload["bridges"]
            if row["id"] == "bridge-full"
        )
        bridge["limits_json"] = raw_limits
        canonical = canonical_json_bytes(malformed_payload)
        malformed = MethodSnapshot(
            third_snapshot.workspace_id,
            canonical,
            "sha256:malformed-probe",
        )
        observed = {
            row.bridge_id: row for row in bridge_readiness(malformed)
        }["bridge-full"]
        malformed_ready.append({
            "limits_json": raw_limits,
            "ready": observed.ready,
            "missing": observed.missing,
        })

    third = detect_gaps(third_snapshot)
    assertions_passed = (
        bridge_rows["bridge-empty"]["limits_json"] == "[]"
        and bridge_rows["bridge-full"]["limits_json"]
        == '["single instrument"]'
        and readiness["bridge-empty"].ready is False
        and readiness["bridge-empty"].missing
        == ("applicability_limits",)
        and readiness["bridge-full"].ready is True
        and first == second == third
        and len(first) == 1
        and first[0].detail == {"recorded_gap_id": "source-open"}
        and len(own_rows) == 1
        and gap_rows["source-open"]["status"] == "open"
        and gap_rows["source-waived"]["status"] == "waived"
        and gap_rows["source-resolved"]["status"]
        == "resolved_by_evidence"
        and all(not row["ready"] for row in malformed_ready)
        and all(
            row["missing"] == ("applicability_limits",)
            for row in malformed_ready
        )
    )
    receipt = {
        "assertions_passed": assertions_passed,
        "bridge_readiness": {
            key: {"ready": value.ready, "missing": value.missing}
            for key, value in sorted(readiness.items())
        },
        "detector_results": [gap.to_dict() for gap in third],
        "malformed_limits": malformed_ready,
        "observer_rows": [
            {
                "id": row["id"],
                "status": row["status"],
                "detector_id": row["detector_id"],
                "detector_version": row["detector_version"],
                "input_snapshot_hash": row["input_snapshot_hash"],
            }
            for row in sorted(payload["gaps"], key=lambda row: row["id"])
        ],
        "passes_equal": first == second == third,
    }
    print(json.dumps(receipt, sort_keys=True))
    return 0 if assertions_passed else 1


def _capture(arguments: list[str], timeout: float) -> dict[str, Any]:
    try:
        completed = subprocess.run(
            [sys.executable, __file__, *arguments],
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
            env={"PYTHONDONTWRITEBYTECODE": "1", "PYTHONPATH": "."},
        )
    except subprocess.TimeoutExpired:
        return {"status": "timeout", "output": None, "stderr": "timed out"}
    try:
        output = json.loads(completed.stdout)
    except json.JSONDecodeError:
        output = None
    return {
        "status": completed.returncode,
        "output": output,
        "stderr": completed.stderr.strip(),
    }


def _static_scan() -> int:
    reports = {}
    product_forbidden_imports = set()
    product_sql_calls = set()
    for relative in _OWNED_PYTHON:
        source = (Path(_ROOT) / relative).read_text(encoding="utf-8")
        tree = ast.parse(source)
        comments = [
            token.string
            for token in tokenize.generate_tokens(
                iter(source.splitlines(keepends=True)).__next__
            )
            if token.type == tokenize.COMMENT
        ]
        suppressions = [
            comment
            for comment in comments
            if any(
                marker in comment.lower()
                for marker in ("noqa", "type: ignore", "pyright: ignore")
            )
        ]
        dynamic_calls = sorted({
            node.func.id
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id in {"compile", "eval", "exec"}
        })
        cycle_recursion = []
        nested_cycle_functions = []
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if node.name not in {"_dependency_cycles", "_graph_seeds"}:
                continue
            nested_cycle_functions.extend(
                child.name
                for child in node.body
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef))
            )
            if any(
                isinstance(child, ast.Call)
                and isinstance(child.func, ast.Name)
                and child.func.id == node.name
                for child in ast.walk(node)
            ):
                cycle_recursion.append(node.name)
        reports[relative] = {
            "ast_statement_count": sum(
                isinstance(node, ast.stmt) for node in ast.walk(tree)
            ),
            "cycle_recursion": sorted(cycle_recursion),
            "dynamic_calls": dynamic_calls,
            "nested_cycle_functions": sorted(nested_cycle_functions),
            "suppression_comments": suppressions,
        }
        if relative != "ontologylab/method_gaps.py":
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                product_forbidden_imports.update(
                    alias.name.split(".", maxsplit=1)[0]
                    for alias in node.names
                    if alias.name.split(".", maxsplit=1)[0]
                    in {"anthropic", "httpx", "openai", "requests", "sqlite3"}
                )
            if isinstance(node, ast.ImportFrom) and node.module:
                root = node.module.split(".", maxsplit=1)[0]
                if root in {
                    "anthropic",
                    "httpx",
                    "openai",
                    "requests",
                    "sqlite3",
                }:
                    product_forbidden_imports.add(root)
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr in {
                    "connect",
                    "execute",
                    "executemany",
                    "executescript",
                }
            ):
                product_sql_calls.add(node.func.attr)

    assertions_passed = (
        all(
            report["ast_statement_count"] <= 250
            and report["cycle_recursion"] == []
            and report["dynamic_calls"] == []
            and report["nested_cycle_functions"] == []
            and report["suppression_comments"] == []
            for report in reports.values()
        )
        and not product_forbidden_imports
        and not product_sql_calls
    )
    print(json.dumps({
        "assertions_passed": assertions_passed,
        "files": reports,
        "product_forbidden_imports": sorted(product_forbidden_imports),
        "product_sql_calls": sorted(product_sql_calls),
    }, sort_keys=True))
    return 0 if assertions_passed else 1


def _outer(
    cycle: Path,
    valid: Path,
    malformed: Path | None,
    timeout: float,
) -> int:
    with tempfile.TemporaryDirectory(prefix="ontologylab-method-gaps-qa-") as root:
        temp_root = Path(root)
        cycle_result = _capture(["--inner", str(cycle)], timeout)
        valid_result = _capture(["--inner", str(valid)], timeout)
        malformed_result = (
            _capture(["--inner", str(malformed)], timeout)
            if malformed is not None
            else None
        )
        graph_results = {
            case: _capture(["--graph", case], timeout)
            for case in _GRAPH_CASES
        }
        store_result = _capture(
            ["--store-probe", str(temp_root / "store.sqlite")],
            timeout,
        )
    cycle_output = cycle_result["output"]
    cycle_ok = (
        cycle_result["status"] == 1
        and isinstance(cycle_output, list)
        and len(cycle_output) == 1
        and cycle_output[0].get("gap_class") == "step_dependency_cycle"
        and isinstance(cycle_output[0].get("detector_id"), str)
        and isinstance(cycle_output[0].get("input_snapshot_hash"), str)
    )
    valid_ok = valid_result["status"] == 0 and valid_result["output"] == []
    malformed_ok = (
        malformed_result is None
        or (
            malformed_result["status"] == 2
            and malformed_result["output"] is None
            and '"type": "GapInputError"' in malformed_result["stderr"]
        )
    )
    self_output = graph_results["self-loop"]["output"]
    multi_output = graph_results["multi-scc"]["output"]
    graph_ok = (
        graph_results["deep-chain"]["status"] == 0
        and graph_results["deep-chain"]["output"] == []
        and graph_results["branching-dag"]["status"] == 0
        and graph_results["branching-dag"]["output"] == []
        and graph_results["self-loop"]["status"] == 1
        and isinstance(self_output, list)
        and [
            row.get("detail", {}).get("cycle") for row in self_output
        ] == [["step-self"]]
        and graph_results["multi-scc"]["status"] == 1
        and isinstance(multi_output, list)
        and [
            row.get("detail", {}).get("cycle") for row in multi_output
        ] == [
            ["step-a", "step-b"],
            ["step-c"],
            ["step-d", "step-e", "step-f"],
        ]
    )
    store_output = store_result["output"]
    store_ok = (
        store_result["status"] == 0
        and isinstance(store_output, dict)
        and store_output.get("assertions_passed") is True
    )
    receipt = {
        "cycle": cycle_result,
        "valid": valid_result,
        "malformed": malformed_result,
        "graphs": graph_results,
        "store": store_result,
        "temp_root": str(temp_root),
        "temp_root_absent": not temp_root.exists(),
        "assertions_passed": (
            cycle_ok
            and valid_ok
            and malformed_ok
            and graph_ok
            and store_ok
            and not temp_root.exists()
        ),
    }
    print(json.dumps(receipt, sort_keys=True))
    return 0 if receipt["assertions_passed"] else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="Manual QA for pure Method gap detection")
    parser.add_argument("--cycle", type=Path)
    parser.add_argument("--valid", type=Path)
    parser.add_argument("--malformed", type=Path)
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--inner", type=Path)
    parser.add_argument("--graph", choices=_GRAPH_CASES)
    parser.add_argument("--store-probe", type=Path)
    parser.add_argument("--static", action="store_true")
    args = parser.parse_args()
    if args.inner is not None:
        return _inner(args.inner)
    if args.graph is not None:
        return _inner_graph(args.graph)
    if args.store_probe is not None:
        return _inner_store(args.store_probe)
    if args.static:
        return _static_scan()
    if args.cycle is None or args.valid is None:
        parser.error("--cycle and --valid are required")
    return _outer(args.cycle, args.valid, args.malformed, args.timeout)


if __name__ == "__main__":
    raise SystemExit(main())
