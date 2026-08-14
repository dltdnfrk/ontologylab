"""Pure independent G0-G6 and G8 compiler gates."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Iterable, Mapping, cast

from ontologylab.method_compiler_contract import (
    COMPILER_REASON_CATALOG,
    CompilationGateResult,
    GateId,
)
from ontologylab.method_gaps import _dependency_cycles
from ontologylab.method_ir import canonical_json_bytes
from ontologylab.method_snapshot import MethodSnapshot
from ontologylab.method_validation import MethodValidationError


_UNIT_DIMENSIONS = {
    "degC": "temperature",
    "g": "mass",
    "h": "time",
    "kg": "mass",
    "mL": "volume",
    "min": "time",
    "s": "time",
}


def canonical_hash(value: object) -> str:
    return "sha256:" + hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def raw_text_hash(value: str) -> str:
    return "sha256:" + hashlib.sha256(value.encode()).hexdigest()


def snapshot_data(snapshot: MethodSnapshot) -> dict[str, Any]:
    try:
        data = json.loads(snapshot.canonical_json)
    except (TypeError, json.JSONDecodeError) as error:
        raise MethodValidationError(
            "invalid compilation snapshot JSON"
        ) from error
    if not isinstance(data, dict) or canonical_hash(data) != snapshot.content_hash:
        raise MethodValidationError("compilation snapshot hash mismatch")
    return data


def snapshot_rows(
    data: Mapping[str, Any],
    name: str,
) -> tuple[dict[str, Any], ...]:
    rows = data.get(name, [])
    if (
        not isinstance(rows, list)
        or any(not isinstance(row, dict) for row in rows)
    ):
        raise MethodValidationError(f"snapshot {name} must be rows")
    return tuple(sorted(
        cast(list[dict[str, Any]], rows),
        key=lambda row: str(row.get("id")),
    ))


def json_object(value: object) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    if not isinstance(value, str):
        return {}
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return dict(parsed) if isinstance(parsed, dict) else {}


def json_list(value: object) -> list[Any]:
    if isinstance(value, list):
        return list(value)
    if not isinstance(value, str):
        return []
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return []
    return list(parsed) if isinstance(parsed, list) else []


def gate_result(
    gate_id: GateId,
    reasons: Iterable[str],
) -> CompilationGateResult:
    canonical = tuple(sorted(set(reasons)))
    if any(
        reason not in COMPILER_REASON_CATALOG[gate_id]
        for reason in canonical
    ):
        raise MethodValidationError(
            f"{gate_id.value} produced an unknown reason"
        )
    return CompilationGateResult(gate_id, not canonical, canonical)


def _source_state(
    data: Mapping[str, Any],
) -> tuple[set[str], set[str]]:
    current_sources = {
        str(row.get("document_id"))
        + ":"
        + str(row.get("document_content_hash"))
        for row in snapshot_rows(data, "policy_snapshots")
    }
    accepted = {
        str(row.get("id"))
        for row in snapshot_rows(data, "occurrences")
        if row.get("status") == "accepted"
    }
    stale = {
        str(row.get("id"))
        for row in snapshot_rows(data, "occurrences")
        if row.get("status") == "stale"
        or (
            row.get("status") == "accepted"
            and (
                str(row.get("document_id"))
                + ":"
                + str(row.get("document_content_hash"))
            )
            not in current_sources
        )
    }
    return accepted, stale


def _g0(data: Mapping[str, Any]) -> CompilationGateResult:
    reasons: list[str] = []
    snapshots = snapshot_rows(data, "policy_snapshots")
    source_keys = {
        (
            str(row.get("document_id")),
            str(row.get("document_content_hash")),
        )
        for row in snapshot_rows(data, "occurrences")
        if row.get("status") == "accepted"
    }
    source_bindings: dict[tuple[str, str], int] = {}
    for row in snapshots:
        source = (
            str(row.get("document_id")),
            str(row.get("document_content_hash")),
        )
        source_bindings[source] = source_bindings.get(source, 0) + 1
        status = row.get("resolution_status")
        if status == "denied":
            reasons.append("rights-denied")
        elif status == "ambiguous":
            reasons.append("rights-ambiguous")
        elif status != "resolved":
            reasons.append("rights-unresolved")
    if any(count != 1 for count in source_bindings.values()):
        reasons.append("rights-ambiguous")
    if any(source not in source_bindings for source in source_keys):
        reasons.append("rights-unresolved")
    policies = {
        str(row.get("id")): row
        for row in snapshot_rows(data, "source_policies")
    }
    for snapshot in snapshots:
        policy = policies.get(str(snapshot.get("source_policy_id")))
        if policy is None:
            reasons.append("rights-unresolved")
        elif (
            policy.get("allowed_extract") not in (True, 1)
            or policy.get("allowed_pack") not in (True, 1)
        ):
            reasons.append("rights-denied")
        else:
            processors = json_list(policy.get("allowed_processors_json"))
            regions = json_list(policy.get("allowed_regions_json"))
            if (
                any(type(item) is not str for item in processors)
                or any(type(item) is not str for item in regions)
                or "local" not in processors
                or "local" not in regions
            ):
                reasons.append("rights-denied")
    return gate_result(GateId.G0, reasons)


def _g1(data: Mapping[str, Any]) -> CompilationGateResult:
    accepted, stale = _source_state(data)
    occurrence_rows = {
        str(row.get("id")): row
        for row in snapshot_rows(data, "occurrences")
    }
    reasons: list[str] = []
    for evidence in snapshot_rows(data, "fragment_evidence"):
        occurrence_id = str(evidence.get("occurrence_id"))
        occurrence = occurrence_rows.get(occurrence_id)
        if occurrence_id not in accepted:
            reasons.append("missing-source-anchor")
        if occurrence_id in stale:
            reasons.append("stale-source-anchor")
        if occurrence is None:
            continue
        text = occurrence.get("statement_text")
        start = occurrence.get("span_start")
        end = occurrence.get("span_end")
        if (
            not isinstance(text, str)
            or not isinstance(start, int)
            or not isinstance(end, int)
            or end - start != len(text)
            or occurrence.get("selected_text_hash") != raw_text_hash(text)
        ):
            reasons.append("mismatched-selector")
    supports = {
        (str(row.get("fragment_id")), str(row.get("field_path")))
        for row in snapshot_rows(data, "fragment_evidence")
        if row.get("evidence_role") == "supports"
        and str(row.get("occurrence_id")) in accepted
    }
    for fragment in snapshot_rows(data, "fragments"):
        if (
            fragment.get("status") != "accepted"
            or fragment.get("epistemic_class") != "source_supported"
        ):
            continue
        payload = json_object(fragment.get("payload_json"))
        for field, value in payload.items():
            if (
                isinstance(value, dict)
                and value.get("state") == "known"
                and (
                    str(fragment.get("id")),
                    f"/{field}",
                )
                not in supports
            ):
                reasons.append("missing-source-anchor")
    return gate_result(GateId.G1, reasons)


def _g2(data: Mapping[str, Any]) -> CompilationGateResult:
    bridge_ids = {
        str(row.get("id"))
        for row in snapshot_rows(data, "bridges")
    }
    bridge_fragments = {
        str(row.get("id"))
        for row in snapshot_rows(data, "fragments")
        if row.get("epistemic_class") == "bridge_assumption"
    }
    reasons: list[str] = []
    for row in snapshot_rows(data, "fragment_evidence"):
        if (
            row.get("evidence_role") == "supports"
            and str(row.get("fragment_id")) in bridge_fragments
        ):
            reasons.extend(
                (
                    "bridge-as-verified-evidence",
                    "epistemic-class-mixed",
                )
            )
    for row in snapshot_rows(data, "bridge_evidence"):
        if (
            str(row.get("bridge_id")) in bridge_ids
            and row.get("evidence_role") == "supports"
        ):
            reasons.append("bridge-as-verified-evidence")
    return gate_result(GateId.G2, reasons)


def _walk(value: object) -> Iterable[tuple[str, object]]:
    if isinstance(value, dict):
        for key, item in value.items():
            yield key, item
            yield from _walk(item)
    elif isinstance(value, list):
        for item in value:
            yield from _walk(item)


def _g3(data: Mapping[str, Any]) -> CompilationGateResult:
    fragment_ids = {
        str(row.get("id"))
        for row in snapshot_rows(data, "fragments")
    }
    occurrence_ids = {
        str(row.get("id"))
        for row in snapshot_rows(data, "occurrences")
    }
    reasons: list[str] = []
    for evidence in snapshot_rows(data, "fragment_evidence"):
        if (
            str(evidence.get("fragment_id")) not in fragment_ids
            or str(evidence.get("occurrence_id")) not in occurrence_ids
        ):
            reasons.append("invalid-reference")
    for link in snapshot_rows(data, "links"):
        if (
            str(link.get("src_fragment_id")) not in fragment_ids
            or str(link.get("dst_fragment_id")) not in fragment_ids
        ):
            reasons.append("invalid-reference")
    for fragment in snapshot_rows(data, "fragments"):
        payload = json_object(fragment.get("payload_json"))
        if not payload and fragment.get("payload_json") not in ("{}", {}):
            reasons.append("unsupported-schema-keyword")
        for key, value in _walk(payload):
            if (
                key.endswith("_id")
                and isinstance(value, str)
                and value not in fragment_ids
            ):
                reasons.append("invalid-reference")
            if (
                isinstance(value, dict)
                and {"symbol", "dimension"} <= set(value)
            ):
                expected = _UNIT_DIMENSIONS.get(str(value.get("symbol")))
                if expected is None:
                    reasons.append("invalid-unit")
                elif value.get("dimension") != expected:
                    reasons.append("invalid-dimension")
            if (
                isinstance(value, dict)
                and value.get("state") != "known"
                and "value" in value
            ):
                reasons.append("fabricated-value")
    return gate_result(GateId.G3, reasons)


def _g4(data: Mapping[str, Any]) -> CompilationGateResult:
    fragments = {
        str(row.get("id")): row
        for row in snapshot_rows(data, "fragments")
        if row.get("status") == "accepted"
    }
    links = [
        row
        for row in snapshot_rows(data, "links")
        if row.get("status") == "accepted"
    ]
    reasons: list[str] = []
    for link in links:
        if (
            str(link.get("src_fragment_id")) not in fragments
            or str(link.get("dst_fragment_id")) not in fragments
        ):
            reasons.append("dangling-reference")
    edges = tuple(
        (
            str(row.get("src_fragment_id")),
            str(row.get("dst_fragment_id")),
        )
        for row in links
        if row.get("kind") in {"produces", "requires", "precedes"}
        and str(row.get("src_fragment_id")) in fragments
        and str(row.get("dst_fragment_id")) in fragments
    )
    if _dependency_cycles(tuple(fragments), edges):
        reasons.append("step-dependency-cycle")
    reachable = {
        node
        for node, row in fragments.items()
        if row.get("kind") in {"input", "objective"}
        or json_object(row.get("payload_json")).get("entry") is True
    }
    changed = True
    while changed:
        before = len(reachable)
        reachable.update(
            str(row.get("dst_fragment_id"))
            for row in links
            if str(row.get("src_fragment_id")) in reachable
        )
        changed = len(reachable) != before
    if any(
        row.get("kind") == "result" and node not in reachable
        for node, row in fragments.items()
    ):
        reasons.append("unreachable-output")
    for link in links:
        if link.get("kind") != "produces":
            continue
        source = fragments.get(str(link.get("src_fragment_id")))
        target = fragments.get(str(link.get("dst_fragment_id")))
        if source is None or target is None:
            continue
        output = json_object(source.get("payload_json"))
        input_ = json_object(target.get("payload_json"))
        if (
            output.get("output_type")
            and input_.get("input_type")
            and output["output_type"] != input_["input_type"]
        ):
            reasons.append("input-output-discontinuity")
        output_unit = output.get("output_unit")
        input_unit = input_.get("input_unit")
        if (
            isinstance(output_unit, dict)
            and isinstance(input_unit, dict)
            and output_unit.get("dimension")
            != input_unit.get("dimension")
        ):
            reasons.append("input-output-discontinuity")
    return gate_result(GateId.G4, reasons)


def _g5(data: Mapping[str, Any]) -> CompilationGateResult:
    reasons: list[str] = []
    for gap in snapshot_rows(data, "gaps"):
        if (
            gap.get("gap_class") != "open_conflict"
            or gap.get("status") != "open"
        ):
            continue
        reasons.append("blocking-conflict")
        scope = json_object(gap.get("detail_json")).get("scope")
        if not isinstance(scope, str) or not scope.strip():
            reasons.append("unscoped-conflict")
    return gate_result(GateId.G5, reasons)


def _g6(data: Mapping[str, Any]) -> CompilationGateResult:
    reviews = snapshot_rows(data, "review_events")
    decisions: dict[tuple[str, str], list[Mapping[str, Any]]] = {}
    for row in reviews:
        key = (
            str(row.get("subject_kind")),
            str(row.get("subject_id")),
        )
        decisions.setdefault(key, []).append(row)
    workspace = str(
        cast(Mapping[str, Any], data.get("workspace", {})).get("id")
    )
    expected = [
        (
            (kind, str(row.get("id"))),
            str(row.get("status")),
        )
        for kind, name in (
            ("occurrence", "occurrences"),
            ("fragment", "fragments"),
            ("link", "links"),
        )
        for row in snapshot_rows(data, name)
    ] + [
        (
            ("bridge", str(row.get("id"))),
            str(row.get("decision_status")),
        )
        for row in snapshot_rows(data, "bridges")
    ] + [
        (("gap", str(row.get("id"))), str(row.get("status")))
        for row in snapshot_rows(data, "gaps")
        if row.get("status") in {
            "resolved_by_evidence",
            "addressed_by_assumption",
            "waived",
        }
    ]
    reasons: list[str] = []
    if any(
        len(decisions.get(item, ())) != 1
        or decisions[item][0].get("decision") != status
        or not str(decisions[item][0].get("reviewer", "")).strip()
        or not str(decisions[item][0].get("note", "")).strip()
        or str(
            decisions[item][0].get("workspace_id", workspace)
        ) != workspace
        for item, status in expected
    ):
        reasons.append("missing-human-decision")
    if any(
        not str(row.get("reviewer", "")).strip()
        or not (
            str(row.get("reviewer")).lower() in {"human", "reviewer"}
            or str(row.get("reviewer")).lower().startswith(("human-", "reviewer-"))
            or str(row.get("reviewer")).lower().endswith("-reviewer")
        )
        or any(
            token in str(row.get("reviewer")).lower()
            for token in ("agent", "compiler", "critic", "model")
        )
        for row in reviews
    ):
        reasons.append("self-approval")
    return gate_result(GateId.G6, reasons)


def g8(
    method: Mapping[str, Any],
    release_id: str | None,
    integrity: Mapping[str, Any],
) -> CompilationGateResult:
    reasons: list[str] = []
    if (
        "expected_method_hash" in integrity
        and integrity["expected_method_hash"] != canonical_hash(method)
    ):
        reasons.append("canonical-artifact-hash-mismatch")
    if (
        release_id is not None
        and "expected_release_id" in integrity
        and integrity["expected_release_id"] != release_id
    ):
        reasons.append("receipt-binding-mismatch")
    if integrity.get("immutable") is False:
        reasons.append("release-not-immutable")
    return gate_result(GateId.G8, reasons)


def evaluate_source_gates(
    data: Mapping[str, Any],
) -> tuple[CompilationGateResult, ...]:
    return (
        _g0(data),
        _g1(data),
        _g2(data),
        _g3(data),
        _g4(data),
        _g5(data),
        _g6(data),
    )
