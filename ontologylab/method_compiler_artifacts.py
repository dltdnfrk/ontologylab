"""Canonical Method, source-index, receipt, hash, and envelope assembly."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence, cast

from ontologylab.method_compiler_contract import (
    COMPILER_REASON_CATALOG_VERSION,
    CompilationGateResult,
    CompilerAcceptedObject,
    CompilerPolicySnapshot,
    CompilerReceipt,
)
from ontologylab.method_compiler_gates import (
    canonical_hash,
    json_list,
    json_object,
    snapshot_rows,
)
from ontologylab.method_compiler_replay import ReplayReceipt
from ontologylab.method_ir import canonical_json_bytes
from ontologylab.method_release_validation import canonical_release_envelope
from ontologylab.method_snapshot import MethodSnapshot


COMPILER_VERSION = "method-compiler-v1"


@dataclass(frozen=True, slots=True)
class ArtifactSelection:
    attempt_id: str
    release_id: str
    method_id: str
    release_version: int


@dataclass(frozen=True, slots=True)
class MethodArtifacts:
    method: dict[str, Any]
    source_index: tuple[dict[str, Any], ...]
    review_receipt: dict[str, Any]


@dataclass(frozen=True, slots=True)
class CompilerArtifacts:
    method: dict[str, Any]
    source_index: tuple[dict[str, Any], ...]
    review_receipt: dict[str, Any]
    receipt: CompilerReceipt | None
    method_json: bytes
    source_index_json: bytes
    canonical_envelope: bytes
    content_hash: str | None


def _sources(
    data: Mapping[str, Any],
    method_id: str,
    fragments: Sequence[Mapping[str, Any]],
    evidence: Sequence[Mapping[str, Any]],
) -> tuple[dict[str, Any], ...]:
    occurrences = {
        str(row.get("id")): row
        for row in snapshot_rows(data, "occurrences")
    }
    reviews = {
        (
            str(row.get("subject_kind")),
            str(row.get("subject_id")),
        ): str(row.get("id"))
        for row in snapshot_rows(data, "review_events")
    }
    fragments_by_id = {
        str(row["id"]): row
        for row in fragments
    }
    sources: list[dict[str, Any]] = []
    for row in evidence:
        occurrence_id = str(row["occurrence_id"])
        fragment_id = str(row["fragment_id"])
        occurrence = occurrences.get(occurrence_id)
        fragment = fragments_by_id.get(fragment_id)
        if occurrence is None or fragment is None:
            continue
        sources.append({
            "id": "source-" + str(row["id"]),
            "method_id": method_id,
            "field_path": (
                f"/fragments/{fragment_id}/payload"
                + str(row["field_path"])
            ),
            "document_id": str(occurrence.get("document_id")),
            "document_content_hash": str(
                occurrence.get("document_content_hash")
            ),
            "span_start": int(occurrence.get("span_start", 0)),
            "span_end": int(occurrence.get("span_end", 0)),
            "selected_text_hash": str(
                occurrence.get("selected_text_hash")
            ),
            "evidence_role": str(row["role"]),
            "epistemic_class": fragment["epistemic_class"],
            "occurrence_id": occurrence_id,
            "receipt_ref": reviews.get(
                ("occurrence", occurrence_id),
                "missing-review",
            ),
        })
    return tuple(sorted(sources, key=lambda row: str(row["id"])))


def build_method(
    data: Mapping[str, Any],
    selection: ArtifactSelection | None,
    gates: Sequence[CompilationGateResult],
) -> MethodArtifacts:
    workspace_value = data.get("workspace")
    workspace = (
        cast(Mapping[str, Any], workspace_value)
        if isinstance(workspace_value, dict)
        else {}
    )
    method_id = (
        selection.method_id
        if selection is not None
        else str(workspace.get("id"))
    )
    version = (
        selection.release_version
        if selection is not None
        else 1
    )
    fragments = [{
        "id": str(row.get("id")),
        "kind": str(row.get("kind")),
        "epistemic_class": str(row.get("epistemic_class")),
        "payload": json_object(row.get("payload_json")),
    } for row in snapshot_rows(data, "fragments")
        if row.get("status") == "accepted"]
    evidence = [{
        "id": str(row.get("id")),
        "fragment_id": str(row.get("fragment_id")),
        "field_path": str(row.get("field_path")),
        "occurrence_id": str(row.get("occurrence_id")),
        "role": str(row.get("evidence_role")),
    } for row in snapshot_rows(data, "fragment_evidence")]
    links = [{
        "id": str(row.get("id")),
        "src_fragment_id": str(row.get("src_fragment_id")),
        "dst_fragment_id": str(row.get("dst_fragment_id")),
        "kind": str(row.get("kind")),
    } for row in snapshot_rows(data, "links")
        if row.get("status") == "accepted"]
    gaps = [{
        "id": str(row.get("id")),
        "gap_class": str(row.get("gap_class")),
        "status": str(row.get("status")),
        "target_fragment_id": row.get("target_fragment_id"),
        "field_path": row.get("field_path"),
    } for row in snapshot_rows(data, "gaps")
        if row.get("status") in {"open", "waived"}]
    bridges = [{
        "id": str(row.get("id")),
        "gap_id": str(row.get("gap_id")),
        "hypothesis": str(row.get("hypothesis")),
        "assumptions": json_list(row.get("assumptions_json")),
        "scope": str(row.get("scope")),
        "limits": json_list(row.get("limits_json")),
        "falsifier": str(row.get("falsifier")),
        "minimum_validation": str(row.get("minimum_validation")),
        "decision_status": str(row.get("decision_status")),
        "epistemic_class": "bridge_assumption",
    } for row in snapshot_rows(data, "bridges")
        if row.get("decision_status") == "accepted_as_assumption"]
    reviews = [{
        "id": str(row.get("id")),
        "subject_kind": str(row.get("subject_kind")),
        "subject_id": str(row.get("subject_id")),
        "decision": str(row.get("decision")),
        "reviewer": str(row.get("reviewer")),
        "note": str(row.get("note")),
    } for row in snapshot_rows(data, "review_events")]
    source_index = _sources(data, method_id, fragments, evidence)
    method = {
        "schema_version": "method-v1",
        "id": method_id,
        "version": version,
        "name": str(workspace.get("name", method_id)),
        "fragments": fragments,
        "field_evidence": evidence,
        "links": links,
        "gaps": gaps,
        "bridge_assumptions": bridges,
        "review_receipts": reviews,
        "gate_results": [{
            "gate": gate.gate_id.value,
            "passed": gate.passed,
            "reasons": list(gate.reasons),
        } for gate in gates],
        "source_index": list(source_index),
        "release": {
            "id": (
                selection.release_id
                if selection is not None
                else None
            ),
            "content_hash": None,
        },
    }
    review_receipt = {
        "decisions": reviews,
        "workspace_id": str(workspace.get("id")),
    }
    return MethodArtifacts(method, source_index, review_receipt)


def _accepted_objects(
    data: Mapping[str, Any],
) -> tuple[CompilerAcceptedObject, ...]:
    objects: list[CompilerAcceptedObject] = []
    for name, status_field, accepted in (
        ("occurrences", "status", {"accepted"}),
        ("fragments", "status", {"accepted"}),
        ("links", "status", {"accepted"}),
        (
            "bridges",
            "decision_status",
            {"accepted_as_assumption"},
        ),
    ):
        for row in snapshot_rows(data, name):
            if row.get(status_field) in accepted:
                objects.append(CompilerAcceptedObject(
                    str(row.get("id")),
                    canonical_hash(row),
                    canonical_hash([name, row]),
                ))
    return tuple(sorted(objects, key=lambda row: row.object_id))


def _policy_snapshots(
    data: Mapping[str, Any],
) -> tuple[CompilerPolicySnapshot, ...]:
    policies = {
        str(row.get("id")): row
        for row in snapshot_rows(data, "source_policies")
    }
    return tuple(sorted(
        (
            CompilerPolicySnapshot(
                str(row.get("id")),
                str(
                    policies
                    .get(str(row.get("source_policy_id")), {})
                    .get("policy_version", "unknown")
                ),
            )
            for row in snapshot_rows(data, "policy_snapshots")
        ),
        key=lambda row: row.snapshot_id,
    ))


def normalized_snapshot_hash(data: Mapping[str, Any]) -> str:
    normalized = {
        key: (
            sorted(
                value,
                key=lambda row: (
                    str(row.get("id"))
                    if isinstance(row, dict)
                    else canonical_json_bytes(row).decode("utf-8")
                ),
            )
            if isinstance(value, list)
            else value
        )
        for key, value in data.items()
    }
    return canonical_hash(normalized)


def assemble_artifacts(
    data: Mapping[str, Any],
    snapshot: MethodSnapshot,
    selection: ArtifactSelection | None,
    gates: Sequence[CompilationGateResult],
    replay: ReplayReceipt,
) -> CompilerArtifacts:
    built = build_method(data, selection, gates)
    method = built.method
    source_index = built.source_index
    method_json = canonical_json_bytes(method)
    source_json = canonical_json_bytes(source_index)
    if selection is None:
        envelope = canonical_json_bytes({
            "method_json": method,
            "source_index": source_index,
        })
        return CompilerArtifacts(
            method,
            source_index,
            built.review_receipt,
            None,
            method_json,
            source_json,
            envelope,
            None,
        )
    inventory = {
        "bridges": method["bridge_assumptions"],
        "gaps": method["gaps"],
        "operator_constraints": [
            row
            for row in method["fragments"]
            if row["epistemic_class"] == "operator_constraint"
        ],
    }
    passed = all(gate.passed for gate in gates)
    receipt = CompilerReceipt(
        selection.attempt_id,
        selection.release_id,
        snapshot.workspace_id,
        selection.release_version,
        "method-v1",
        COMPILER_VERSION,
        snapshot.content_hash,
        _policy_snapshots(data),
        _accepted_objects(data),
        canonical_hash(method),
        canonical_hash(source_index),
        replay.fixture_set_hash,
        COMPILER_REASON_CATALOG_VERSION,
        replay.fixture_count,
        replay.result_count,
        replay.kind_counts,
        replay.results,
        replay.receipt_hash,
        tuple(gates),
        canonical_hash(inventory),
        canonical_hash(built.review_receipt),
        passed,
        None,
    )
    content_hash = None
    if passed:
        canonical = canonical_release_envelope(
            method,
            source_index,
            receipt,
        )
        receipt = canonical.receipt
        content_hash = canonical.content_hash
    envelope = canonical_json_bytes({
        "method_json": method,
        "source_index": source_index,
        "receipt": receipt,
    })
    return CompilerArtifacts(
        method,
        source_index,
        built.review_receipt,
        receipt,
        canonical_json_bytes(method),
        source_json,
        envelope,
        content_hash,
    )
