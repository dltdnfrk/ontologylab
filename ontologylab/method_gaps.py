"""Pure deterministic gap detection over frozen MethodStore snapshots."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from typing import Mapping, Protocol, cast

from ontologylab.method_snapshot import MethodSnapshot

DETECTOR_ID = "ontologylab.method-gaps"
DETECTOR_VERSION = "1"


class GapInputError(ValueError):
    """The frozen snapshot is not a detector input."""


@dataclass(frozen=True, slots=True)
class GapResult:
    gap_id: str
    gap_class: str
    target_fragment_id: str | None
    field_path: str | None
    detector_id: str
    detector_version: str
    input_snapshot_hash: str
    detail: Mapping[str, object]

    def to_dict(self) -> dict[str, object]:
        return {
            "gap_id": self.gap_id,
            "gap_class": self.gap_class,
            "target_fragment_id": self.target_fragment_id,
            "field_path": self.field_path,
            "detector_id": self.detector_id,
            "detector_version": self.detector_version,
            "input_snapshot_hash": self.input_snapshot_hash,
            "detail": dict(self.detail),
        }


@dataclass(frozen=True, slots=True)
class BridgeReadiness:
    bridge_id: str
    ready: bool
    missing: tuple[str, ...]


class GapUpserter(Protocol):
    def upsert_gap(
        self,
        gap_id: str,
        *,
        workspace_id: str,
        gap_class: str,
        target_fragment_id: str | None,
        field_path: str | None,
        detector_id: str,
        detector_version: str,
        input_snapshot_hash: str,
        detail: Mapping[str, object],
    ) -> None: ...


def _canonical(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode()


def _normalize(value: object) -> object:
    if isinstance(value, dict):
        return {str(key): _normalize(item) for key, item in sorted(value.items())}
    if isinstance(value, list):
        items = {_canonical(_normalize(item)): _normalize(item) for item in value}
        return [items[key] for key in sorted(items)]
    return value


def _payload(snapshot: MethodSnapshot) -> dict[str, object]:
    try:
        value = json.loads(snapshot.canonical_json)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise GapInputError("snapshot canonical_json must be valid UTF-8 JSON") from exc
    if not isinstance(value, dict) or not isinstance(value.get("workspace"), dict):
        raise GapInputError("snapshot must contain an object workspace")
    normalized = cast(dict[str, object], _normalize(value))
    normalized["gaps"] = [
        row
        for row in _rows(normalized, "gaps")
        if not (
            row.get("detector_id") == DETECTOR_ID
            and row.get("detector_version") == DETECTOR_VERSION
        )
    ]
    return normalized


def _rows(data: Mapping[str, object], key: str) -> tuple[dict[str, object], ...]:
    value = data.get(key, [])
    if not isinstance(value, list) or not all(isinstance(row, dict) for row in value):
        raise GapInputError(f"snapshot {key} must be a list of objects")
    return tuple(cast(dict[str, object], row) for row in value)


def _row_payload(row: Mapping[str, object], key: str = "payload_json") -> dict[str, object]:
    value = row.get(key, "{}")
    try:
        parsed = json.loads(value) if isinstance(value, str) else value
    except json.JSONDecodeError as exc:
        raise GapInputError(f"{key} must be valid JSON") from exc
    if not isinstance(parsed, dict):
        raise GapInputError(f"{key} must encode an object")
    return cast(dict[str, object], parsed)


def _has_applicability_limits(value: object) -> bool:
    if not isinstance(value, str):
        return False
    try:
        limits = json.loads(value)
    except json.JSONDecodeError:
        return False
    return (
        isinstance(limits, list)
        and bool(limits)
        and all(isinstance(limit, str) and bool(limit.strip()) for limit in limits)
    )


def _known(value: object) -> bool:
    return (
        isinstance(value, dict)
        and value.get("state") == "known"
        and value.get("value") not in (None, "")
    )


def _seed(
    gap_class: str, target: str | None, path: str | None,
    detail: Mapping[str, object],
) -> tuple[str, str | None, str | None, Mapping[str, object]]:
    return gap_class, target, path, detail


def _field_seeds(
    data: Mapping[str, object],
) -> list[
    tuple[str, str | None, str | None, Mapping[str, object]]
]:
    seeds = []
    required = {
        "input": ("name", "type"), "objective": ("description",),
        "step": ("name",), "result": ("name",), "measurement": ("name", "unit"),
    }
    fragments = [row for row in _rows(data, "fragments") if row.get("status") == "accepted"]
    occurrences = {str(row.get("id")): row for row in _rows(data, "occurrences")
                   if row.get("status") == "accepted"}
    resolved = {(row.get("document_id"), row.get("document_content_hash"))
                for row in _rows(data, "policy_snapshots")
                if row.get("resolution_status") == "resolved"}
    supports = {(row.get("fragment_id"), row.get("field_path"))
                for row in _rows(data, "fragment_evidence")
                if row.get("evidence_role") == "supports"
                and (occ := occurrences.get(str(row.get("occurrence_id")))) is not None
                and (occ.get("document_id"), occ.get("document_content_hash")) in resolved}
    for fragment in fragments:
        fragment_id, kind = str(fragment.get("id")), str(fragment.get("kind"))
        payload = _row_payload(fragment)
        for field in required.get(kind, ()):
            if not _known(payload.get(field)):
                seeds.append(_seed(
                    "required_slot_missing",
                    fragment_id,
                    f"/{field}",
                    {"slot": field},
                ))
        if fragment.get("epistemic_class") == "source_supported":
            for field, value in sorted(payload.items()):
                if _known(value) and (fragment_id, f"/{field}") not in supports:
                    seeds.append(_seed(
                        "factual_field_without_evidence",
                        fragment_id,
                        f"/{field}",
                        {"field": field},
                    ))
        if kind == "condition" and not _known(payload.get("criterion")):
            seeds.append(_seed(
                "unmeasurable_condition",
                fragment_id,
                "/criterion",
                {"criterion_state": "not_known"},
            ))
    counters = sorted(
        (str(row.get("fragment_id")), str(row.get("field_path")))
        for row in _rows(data, "fragment_evidence")
        if row.get("evidence_role") == "contradicts"
    )
    for fragment_id, path in counters:
        seeds.append(_seed(
            "explicit_counter_evidence",
            fragment_id,
            path,
            {"evidence_role": "contradicts"},
        ))
    return seeds


def _dependency_cycles(
    nodes: tuple[str, ...],
    edges: tuple[tuple[str, str], ...],
) -> tuple[tuple[str, ...], ...]:
    adjacency: dict[str, list[str]] = {node: [] for node in nodes}
    reverse: dict[str, list[str]] = {node: [] for node in nodes}
    self_loops: set[str] = set()
    for source, target in edges:
        adjacency[source].append(target)
        reverse[target].append(source)
        if source == target:
            self_loops.add(source)

    visited: set[str] = set()
    finish_order: list[str] = []
    for root in sorted(nodes):
        if root in visited:
            continue
        visited.add(root)
        walk_stack: list[tuple[str, int]] = [(root, 0)]
        while walk_stack:
            node, index = walk_stack[-1]
            targets = adjacency[node]
            if index == len(targets):
                finish_order.append(node)
                walk_stack.pop()
                continue
            walk_stack[-1] = (node, index + 1)
            target = targets[index]
            if target not in visited:
                visited.add(target)
                walk_stack.append((target, 0))

    assigned: set[str] = set()
    cycles: list[tuple[str, ...]] = []
    for root in reversed(finish_order):
        if root in assigned:
            continue
        assigned.add(root)
        component: list[str] = []
        component_stack = [root]
        while component_stack:
            node = component_stack.pop()
            component.append(node)
            for target in reverse[node]:
                if target not in assigned:
                    assigned.add(target)
                    component_stack.append(target)
        canonical: tuple[str, ...] = tuple(sorted(component))
        if len(canonical) > 1 or min(component) in self_loops:
            cycles.append(canonical)
    return tuple(sorted(cycles))


def _graph_seeds(
    data: Mapping[str, object],
) -> list[
    tuple[str, str | None, str | None, Mapping[str, object]]
]:
    seeds = []
    fragments = {str(row.get("id")): row for row in _rows(data, "fragments")
                 if row.get("status") == "accepted"}
    links = [row for row in _rows(data, "links") if row.get("status") == "accepted"]
    for link in links:
        missing = sorted(node for node in (str(link.get("src_fragment_id")),
                                           str(link.get("dst_fragment_id")))
                         if node not in fragments)
        if missing:
            seeds.append(_seed(
                "dangling_reference",
                None,
                None,
                {
                    "link_id": str(link.get("id")),
                    "missing": missing,
                },
            ))
    edges = [(str(row.get("src_fragment_id")), str(row.get("dst_fragment_id")))
             for row in links if row.get("kind") in {"requires", "precedes"}
             and row.get("src_fragment_id") in fragments
             and row.get("dst_fragment_id") in fragments]
    for cycle in _dependency_cycles(tuple(fragments), tuple(edges)):
        seeds.append(_seed(
            "step_dependency_cycle", min(cycle), None, {"cycle": list(cycle)}
        ))
    reachable = {node for node, row in fragments.items()
                 if row.get("kind") in {"input", "objective"}
                 or _row_payload(row).get("entry") is True}
    changed = True
    while changed:
        before = len(reachable)
        reachable.update(str(row.get("dst_fragment_id")) for row in links
                         if str(row.get("src_fragment_id")) in reachable)
        changed = len(reachable) != before
    for node, row in sorted(fragments.items()):
        if row.get("kind") in {"step", "result"} and node not in reachable:
            seeds.append(_seed(
                "unreachable_step_or_result",
                node,
                None,
                {"kind": str(row.get("kind"))},
            ))
    for link in links:
        if link.get("kind") != "produces":
            continue
        src, dst = (
            fragments.get(str(link.get("src_fragment_id"))),
            fragments.get(str(link.get("dst_fragment_id"))),
        )
        if src is None or dst is None:
            continue
        output, input_ = _row_payload(src), _row_payload(dst)
        if (
            output.get("output_type")
            and input_.get("input_type")
            and output["output_type"] != input_["input_type"]
        ):
            seeds.append(_seed(
                "type_discontinuity",
                str(dst.get("id")),
                "/input_type",
                {"link_id": str(link.get("id"))},
            ))
        out_unit, in_unit = output.get("output_unit"), input_.get("input_unit")
        if (
            isinstance(out_unit, dict)
            and isinstance(in_unit, dict)
            and out_unit.get("dimension") != in_unit.get("dimension")
        ):
            seeds.append(_seed(
                "unit_dimension_mismatch",
                str(dst.get("id")),
                "/input_unit",
                {"link_id": str(link.get("id"))},
            ))
    return seeds


def _policy_fixture_seeds(
    data: Mapping[str, object],
) -> list[
    tuple[str, str | None, str | None, Mapping[str, object]]
]:
    seeds = []
    policies = _rows(data, "policy_snapshots")
    resolved = {(row.get("document_id"), row.get("document_content_hash")) for row in policies
                if row.get("resolution_status") == "resolved"}
    for row in _rows(data, "occurrences"):
        selector = (row.get("document_id"), row.get("document_content_hash"))
        if row.get("status") == "accepted" and selector not in resolved:
            seeds.append(_seed("stale_selector", None, None, {"occurrence_id": str(row.get("id"))}))
    for row in policies:
        if row.get("resolution_status") != "resolved":
            seeds.append(_seed(
                "blocked_policy",
                None,
                None,
                {
                    "policy_snapshot_id": str(row.get("id")),
                    "status": str(row.get("resolution_status")),
                },
            ))
    workspace = cast(Mapping[str, object], data["workspace"])
    scope = _row_payload(workspace, "scope_json")
    fixtures = scope.get("fixtures", [])
    if not isinstance(fixtures, list) or not all(isinstance(row, dict) for row in fixtures):
        raise GapInputError("workspace scope fixtures must be a list of objects")
    fixture_rows = cast(list[dict[str, object]], fixtures)
    failed = sorted(str(row.get("id")) for row in fixture_rows if row.get("passed") is not True)
    if failed:
        seeds.append(_seed("failed_fixture", None, None, {
            "denominator_total": len(fixture_rows), "failed_fixture_ids": failed,
            "fixture_kinds": sorted({str(row.get("kind")) for row in fixture_rows}),
        }))
    for row in _rows(data, "gaps"):
        if row.get("gap_class") == "open_conflict" and row.get("status") == "open":
            seeds.append(_seed("open_conflict", cast(str | None, row.get("target_fragment_id")),
                               cast(str | None, row.get("field_path")),
                               {"recorded_gap_id": str(row.get("id"))}))
    return seeds


def detect_gaps(snapshot: MethodSnapshot) -> tuple[GapResult, ...]:
    data = _payload(snapshot)
    snapshot_hash = "sha256:" + hashlib.sha256(_canonical(data)).hexdigest()
    seeds = _field_seeds(data) + _graph_seeds(data) + _policy_fixture_seeds(data)
    results = []
    for gap_class, target, path, detail in seeds:
        identity = _canonical([DETECTOR_ID, DETECTOR_VERSION, gap_class, target, path, detail])
        results.append(GapResult(
            "gap:" + hashlib.sha256(identity).hexdigest()[:32], gap_class,
            target, path, DETECTOR_ID, DETECTOR_VERSION, snapshot_hash, detail,
        ))
    unique = {gap.gap_id: gap for gap in results}
    return tuple(sorted(unique.values(), key=lambda gap: (
        gap.gap_class, gap.target_fragment_id or "", gap.field_path or "", gap.gap_id,
    )))


def bridge_readiness(snapshot: MethodSnapshot) -> tuple[BridgeReadiness, ...]:
    data = _payload(snapshot)
    searched = {str(row.get("bridge_id")) for row in _rows(data, "counter_evidence_searches")}
    results = []
    for bridge in _rows(data, "bridges"):
        missing = []
        checks = {
            "accepted_decision": bridge.get("decision_status") == "accepted_as_assumption",
            "bridge_assumption": bridge.get("epistemic_class") == "bridge_assumption",
            "scope": bool(bridge.get("scope")),
            "applicability_limits": _has_applicability_limits(
                bridge.get("limits_json")
            ),
            "falsifier": bool(bridge.get("falsifier")),
            "minimum_validation": bool(bridge.get("minimum_validation")),
            "counter_search_receipt": str(bridge.get("id")) in searched,
        }
        missing.extend(name for name, passed in checks.items() if not passed)
        results.append(BridgeReadiness(str(bridge.get("id")), not missing, tuple(sorted(missing))))
    return tuple(sorted(results, key=lambda result: result.bridge_id))


def upsert_detected_gaps(
    store: GapUpserter, snapshot: MethodSnapshot,
) -> tuple[GapResult, ...]:
    results = detect_gaps(snapshot)
    for gap in results:
        store.upsert_gap(
            gap.gap_id, workspace_id=snapshot.workspace_id,
            gap_class=gap.gap_class, target_fragment_id=gap.target_fragment_id,
            field_path=gap.field_path, detector_id=gap.detector_id,
            detector_version=gap.detector_version,
            input_snapshot_hash=gap.input_snapshot_hash, detail=gap.detail,
        )
    return results
