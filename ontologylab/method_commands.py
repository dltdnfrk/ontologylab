"""Pure Method proposal and human-decision orchestration."""

from __future__ import annotations

from dataclasses import dataclass
import time, uuid
from typing import Any, Literal, Mapping, Protocol, Sequence

from ontologylab.method_ir import (
    BridgeAssumption, FieldEvidence, MethodFragment, MethodLink,
)
from ontologylab.method_validation import (
    BridgeWrite, CounterSearchWrite, FragmentEvidenceWrite, FragmentWrite,
    GapWrite, LinkWrite,
    MethodConflictError, MethodNotFoundError, MethodStateError,
    MethodValidationError, ReviewEventWrite, canonical_json, method_id,
    nonempty_text, sha256_hash,
)

DecisionKind = Literal["occurrence", "fragment", "link", "bridge", "gap"]


@dataclass(frozen=True, slots=True)
class DecisionSubject:
    workspace_id: str
    status: str


class CommandPersistence(Protocol):
    def ensure_active(self) -> None:
        ...

    def workspace_exists(self, workspace_id: str) -> bool:
        ...

    def insert_fragment(self, row: FragmentWrite) -> None:
        ...

    def fragment_epistemic(self, fragment_id: str) -> str | None:
        ...

    def insert_fragment_evidence(
        self,
        row: FragmentEvidenceWrite,
    ) -> None:
        ...

    def insert_link(self, row: LinkWrite) -> None:
        ...

    def gap_workspace(self, gap_id: str) -> str | None:
        ...

    def fragment_workspace(self, fragment_id: str) -> str | None:
        ...

    def upsert_gap_row(self, row: GapWrite) -> None:
        ...

    def insert_bridge(self, row: BridgeWrite) -> None:
        ...

    def insert_counter_search(
        self,
        row: CounterSearchWrite,
    ) -> None:
        ...

    def decision_subject(
        self, kind: DecisionKind, subject_id: str
    ) -> DecisionSubject | None: ...
    def bridge_has_counter_search(
        self, workspace_id: str, bridge_id: str
    ) -> bool: ...
    def insert_review_event(self, row: ReviewEventWrite) -> None:
        ...
    def apply_decision(
        self, kind: DecisionKind, subject_id: str, expected: str, decision: str
    ) -> bool: ...


class MethodCommands:
    """Public Method commands over explicit typed persistence operations."""

    _command_persistence: CommandPersistence

    def _workspace(self, workspace_id: str) -> str:
        self._command_persistence.ensure_active()
        workspace_id = method_id(workspace_id)
        if not self._command_persistence.workspace_exists(workspace_id):
            raise MethodNotFoundError(f"unknown workspace {workspace_id!r}")
        return workspace_id

    def propose_fragment(
        self, workspace_id: str, fragment: MethodFragment, *,
        generator: str, parser_version: str,
    ) -> None:
        workspace_id = self._workspace(workspace_id)
        self._command_persistence.insert_fragment(FragmentWrite(
            method_id(fragment.id),
            workspace_id,
            fragment.kind.value,
            fragment.epistemic_class.value,
            canonical_json(fragment.payload),
            nonempty_text("generator", generator),
            nonempty_text("parser_version", parser_version),
            "proposed",
            time.time(),
        ))

    def add_fragment_evidence(self, evidence: FieldEvidence) -> None:
        self._command_persistence.ensure_active()
        fragment_id = method_id(evidence.fragment_id)
        epistemic_class = self._command_persistence.fragment_epistemic(fragment_id)
        if epistemic_class is None:
            raise MethodNotFoundError(f"unknown fragment {fragment_id!r}")
        if (
            epistemic_class == "bridge_assumption"
            and evidence.role.value == "supports"
        ):
            raise MethodValidationError(
                "bridge assumption cannot have supporting fragment evidence"
            )
        self._command_persistence.insert_fragment_evidence(
            FragmentEvidenceWrite(
                method_id(evidence.id),
                fragment_id,
                nonempty_text("field_path", evidence.field_path),
                method_id(evidence.occurrence_id),
                evidence.role.value,
                time.time(),
            )
        )

    def propose_link(
        self, workspace_id: str, link: MethodLink, *,
        provenance: Mapping[str, Any],
    ) -> None:
        workspace_id = self._workspace(workspace_id)
        self._command_persistence.insert_link(LinkWrite(
            method_id(link.id),
            workspace_id,
            method_id(link.src_fragment_id),
            method_id(link.dst_fragment_id),
            link.kind.value,
            canonical_json(provenance),
            "proposed",
            time.time(),
        ))

    def upsert_gap(
        self, gap_id: str, *, workspace_id: str, gap_class: str,
        target_fragment_id: str | None, field_path: str | None,
        detector_id: str, detector_version: str, input_snapshot_hash: str,
        detail: Mapping[str, Any],
    ) -> None:
        workspace_id = self._workspace(workspace_id)
        gap_id = method_id(gap_id)
        existing_workspace = self._command_persistence.gap_workspace(gap_id)
        if existing_workspace is not None and existing_workspace != workspace_id:
            raise MethodStateError("gap cannot be upserted across workspaces")
        if target_fragment_id is not None:
            target_fragment_id = method_id(target_fragment_id)
            if (
                self._command_persistence.fragment_workspace(target_fragment_id)
                != workspace_id
            ):
                raise MethodValidationError(
                    "gap target must exist in the same workspace"
                )
        now = time.time()
        self._command_persistence.upsert_gap_row(GapWrite(
            gap_id,
            workspace_id,
            nonempty_text("gap_class", gap_class),
            target_fragment_id,
            field_path,
            nonempty_text("detector_id", detector_id),
            nonempty_text("detector_version", detector_version),
            sha256_hash("input_snapshot_hash", input_snapshot_hash),
            canonical_json(detail),
            now,
            now,
        ))

    def propose_bridge(
        self, workspace_id: str, bridge: BridgeAssumption, *,
        generator: str, model: str | None, prompt_version: str,
    ) -> None:
        workspace_id = self._workspace(workspace_id)
        if bridge.epistemic_class.value != "bridge_assumption":
            raise MethodValidationError(
                "bridge epistemic class must remain bridge_assumption"
            )
        if bridge.decision_status != "pending":
            raise MethodValidationError("bridge proposal must start pending")
        self._command_persistence.insert_bridge(BridgeWrite(
            method_id(bridge.id),
            workspace_id,
            method_id(bridge.gap_id),
            nonempty_text("hypothesis", bridge.hypothesis),
            canonical_json(bridge.assumptions),
            nonempty_text("scope", bridge.scope),
            canonical_json(bridge.limits),
            nonempty_text("falsifier", bridge.falsifier),
            nonempty_text("minimum_validation", bridge.minimum_validation),
            "pending",
            bridge.epistemic_class.value,
            nonempty_text("generator", generator),
            model,
            nonempty_text("prompt_version", prompt_version),
            time.time(),
        ))

    def record_counter_evidence_search(
        self, search_id: str, *, workspace_id: str, gap_id: str,
        bridge_id: str, query: str, scope: Mapping[str, Any],
        corpus_snapshot_hash: str, result_occurrence_ids: Sequence[str],
        searched_by: str,
    ) -> None:
        self._command_persistence.ensure_active()
        self._command_persistence.insert_counter_search(CounterSearchWrite(
            method_id(search_id),
            method_id(workspace_id),
            method_id(gap_id),
            method_id(bridge_id),
            nonempty_text("query", query),
            canonical_json(scope),
            sha256_hash("corpus_snapshot_hash", corpus_snapshot_hash),
            canonical_json(tuple(result_occurrence_ids)),
            nonempty_text("searched_by", searched_by),
            time.time(),
        ))

    def decide(
        self, subject_kind: str, subject_id: str, decision: str, *,
        reviewer: str, note: str, review_event_id: str | None = None,
    ) -> None:
        self._command_persistence.ensure_active()
        reviewer = nonempty_text("reviewer", reviewer)
        note = nonempty_text("note", note)
        match subject_kind:
            case "occurrence":
                kind: DecisionKind = "occurrence"
                expected, allowed = "proposed", {"accepted", "rejected", "stale"}
            case "fragment":
                kind = "fragment"
                expected, allowed = "proposed", {"accepted", "rejected", "stale"}
            case "link":
                kind = "link"
                expected, allowed = "proposed", {"accepted", "rejected"}
            case "bridge":
                kind = "bridge"
                expected = "pending"
                allowed = {"accepted_as_assumption", "rejected", "superseded"}
            case "gap":
                kind = "gap"
                expected = "open"
                allowed = {
                    "resolved_by_evidence", "addressed_by_assumption", "waived"
                }
            case _:
                raise MethodValidationError(
                    "unknown Method decision subject kind"
                )
        subject_id = method_id(subject_id)
        subject = self._command_persistence.decision_subject(kind, subject_id)
        if subject is None:
            raise MethodNotFoundError(f"unknown {subject_kind} {subject_id!r}")
        if decision not in allowed:
            raise MethodValidationError(f"invalid {subject_kind} decision")
        if subject.status != expected:
            raise MethodStateError(
                f"{subject_kind} decision is already terminal"
            )
        if (
            kind == "bridge"
            and decision == "accepted_as_assumption"
            and not self._command_persistence.bridge_has_counter_search(
                subject.workspace_id, subject_id
            )
        ):
            raise MethodStateError(
                "bridge acceptance requires a matching counter-evidence search"
            )
        event_id = method_id(review_event_id or uuid.uuid4().hex)
        self._command_persistence.insert_review_event(ReviewEventWrite(
            event_id,
            subject.workspace_id,
            kind,
            subject_id,
            decision,
            reviewer,
            note,
            time.time(),
        ))
        if not self._command_persistence.apply_decision(
            kind, subject_id, expected, decision
        ):
            raise MethodConflictError("Method decision lost a concurrent race")
