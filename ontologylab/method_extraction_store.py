"""Pure occurrence-import and extraction-lifecycle orchestration."""

from __future__ import annotations

from dataclasses import dataclass
import time
from typing import Any, Mapping, NamedTuple, Protocol, Sequence

from ontologylab.method_ir import StatementOccurrence
from ontologylab.method_validation import (
    DocumentRecord, MethodNotFoundError, MethodStateError, MethodValidationError,
    OccurrenceWrite, canonical_json, document_bytes, method_id, nonempty_text,
    sha256_hash, validate_selector,
)


class PolicySnapshotRecord(NamedTuple):
    document_id: str
    document_content_hash: str
    resolution_status: str


@dataclass(frozen=True, slots=True)
class ExtractionRunWrite:
    run_id: str
    workspace_id: str
    document_id: str
    document_content_hash: str
    policy_snapshot_id: str
    extractor_engine: str
    extractor_model: str | None
    prompt_version: str
    decode_params_json: str
    chunk_plan_hash: str
    created_ts: float
    updated_ts: float


@dataclass(frozen=True, slots=True)
class ExtractionChunkWrite:
    run_id: str
    chunk_index: int
    char_offset: int
    content_hash: str


def occurrence_parameters(row: OccurrenceWrite) -> tuple[Any, ...]:
    """Serialize one validated occurrence without exposing SQL."""
    occurrence, selector = row.occurrence, row.occurrence.selector
    return (
        occurrence.id, row.workspace_id, selector.document_id,
        selector.document_content_hash, selector.span_start, selector.span_end,
        selector.selected_text_hash, occurrence.statement_text,
        occurrence.polarity, occurrence.modality,
        canonical_json(occurrence.temporal_scope),
        canonical_json(occurrence.applicability_scope),
        row.extractor_engine, row.extractor_model, row.prompt_version,
        row.decode_params_json, "proposed", row.created_ts,
    )


class ExtractionPersistence(Protocol):
    def document(
        self,
        document_id: str,
    ) -> DocumentRecord | None:
        ...

    def insert_occurrence(self, row: OccurrenceWrite) -> None:
        ...

    def policy_snapshot(
        self,
        snapshot_id: str,
    ) -> PolicySnapshotRecord | None:
        ...

    def insert_extraction_run(
        self, run: ExtractionRunWrite, chunks: Sequence[ExtractionChunkWrite]
    ) -> None:
        ...

    def claim_extraction_run(
        self,
        run_id: str,
        owner_token: str,
        updated_ts: float,
    ) -> bool:
        ...

    def claim_extraction_chunk(
        self,
        run_id: str,
        chunk_index: int,
        owner_token: str,
    ) -> bool:
        ...

    def succeed_extraction_chunk(
        self,
        run_id: str,
        chunk_index: int,
        owner_token: str,
        stats_json: str,
    ) -> bool:
        ...

    def interrupt_extraction_run(
        self,
        run_id: str,
        owner_token: str,
        reason: str,
        updated_ts: float,
    ) -> bool:
        ...

    def interrupt_running_chunks(
        self,
        run_id: str,
        owner_token: str,
    ) -> None:
        ...

    def resume_extraction_run(
        self,
        run_id: str,
        updated_ts: float,
    ) -> bool:
        ...

    def retryable_extraction_chunks(
        self,
        run_id: str,
    ) -> tuple[int, ...]:
        ...

    def fail_extraction_chunk(
        self, run_id: str, chunk_index: int, owner_token: str,
        error_kind: str, error_identity: str,
    ) -> bool:
        ...

    def mark_run_failed_from_chunk(
        self, run_id: str, error_kind: str, error_identity: str, updated_ts: float
    ) -> None:
        ...

    def unfinished_extraction_chunks(self, run_id: str) -> int:
        ...

    def succeed_extraction_run(
        self, run_id: str, owner_token: str, updated_ts: float
    ) -> bool:
        ...

    def fail_extraction_run(
        self, run_id: str, owner_token: str, error_kind: str,
        error_identity: str, updated_ts: float,
    ) -> bool:
        ...


class MethodExtractionStore:
    """Public extraction operations over explicit persistence callbacks."""

    _validation_persistence: Any
    _extraction_persistence: ExtractionPersistence

    def _workspace(self, workspace_id: str) -> str:
        self._validation_persistence.ensure_active()
        workspace_id = method_id(workspace_id)
        if not self._validation_persistence.workspace_exists(workspace_id):
            raise MethodNotFoundError(f"unknown workspace {workspace_id!r}")
        return workspace_id

    def _document_bytes(self, document_id: str, expected_hash: str) -> bytes:
        document_id = method_id(document_id)
        expected_hash = sha256_hash("document_content_hash", expected_hash)
        record = self._extraction_persistence.document(document_id)
        if record is None:
            raise MethodNotFoundError(f"unknown document {document_id!r}")
        return document_bytes(record, expected_hash)

    def import_occurrence(
        self, workspace_id: str, occurrence: StatementOccurrence, *,
        extractor_engine: str, extractor_model: str | None,
        prompt_version: str, decode_params: Mapping[str, Any],
    ) -> None:
        workspace_id = self._workspace(workspace_id)
        selector = occurrence.selector
        raw = self._document_bytes(
            selector.document_id, selector.document_content_hash
        )
        validate_selector(occurrence, raw)
        method_id(occurrence.id)
        self._extraction_persistence.insert_occurrence(OccurrenceWrite(
            workspace_id,
            occurrence,
            nonempty_text("extractor_engine", extractor_engine),
            extractor_model,
            nonempty_text("prompt_version", prompt_version),
            canonical_json(decode_params),
            time.time(),
        ))

    def create_extraction_run(
        self, run_id: str, *, workspace_id: str, document_id: str,
        document_content_hash: str, policy_snapshot_id: str,
        extractor_engine: str, extractor_model: str | None,
        prompt_version: str, decode_params: Mapping[str, Any],
        chunk_plan_hash: str, chunks: Sequence[tuple[int, int, str]],
    ) -> None:
        workspace_id = self._workspace(workspace_id)
        digest = sha256_hash("document_content_hash", document_content_hash)
        policy_snapshot_id = method_id(policy_snapshot_id)
        snapshot = self._extraction_persistence.policy_snapshot(policy_snapshot_id)
        if snapshot is None:
            raise MethodNotFoundError(
                f"unknown policy snapshot {policy_snapshot_id!r}"
            )
        if snapshot.resolution_status != "resolved":
            raise MethodStateError(
                "extraction requires a resolved policy snapshot"
            )
        if (
            snapshot.document_id != document_id
            or snapshot.document_content_hash != digest
        ):
            raise MethodValidationError(
                "extraction does not match its policy snapshot"
            )
        self._document_bytes(document_id, digest)
        run_id = method_id(run_id)
        normalized_chunks: list[ExtractionChunkWrite] = []
        for index, offset, chunk_hash in chunks:
            if (
                isinstance(index, bool) or not isinstance(index, int) or index < 0
                or isinstance(offset, bool) or not isinstance(offset, int)
                or offset < 0
            ):
                raise MethodValidationError(
                    "chunk index and offset must be nonnegative integers"
                )
            normalized_chunks.append(ExtractionChunkWrite(
                run_id, index, offset,
                sha256_hash("chunk content_hash", chunk_hash),
            ))
        now = time.time()
        self._extraction_persistence.insert_extraction_run(ExtractionRunWrite(
            run_id,
            workspace_id,
            method_id(document_id),
            digest,
            policy_snapshot_id,
            nonempty_text("extractor_engine", extractor_engine),
            extractor_model,
            nonempty_text("prompt_version", prompt_version),
            canonical_json(decode_params),
            sha256_hash("chunk_plan_hash", chunk_plan_hash),
            now,
            now,
        ), normalized_chunks)

    def claim_extraction_run(self, run_id: str, *, owner_token: str) -> None:
        self._validation_persistence.ensure_active()
        if not self._extraction_persistence.claim_extraction_run(
            method_id(run_id), nonempty_text("owner_token", owner_token),
            time.time(),
        ):
            raise MethodStateError("extraction run cannot be claimed from its state")

    def claim_extraction_chunk(
        self, run_id: str, chunk_index: int, *, owner_token: str
    ) -> bool:
        self._validation_persistence.ensure_active()
        return self._extraction_persistence.claim_extraction_chunk(
            run_id, chunk_index, owner_token
        )

    def succeed_extraction_chunk(
        self, run_id: str, chunk_index: int, *, owner_token: str,
        stats: Mapping[str, Any],
    ) -> None:
        self._validation_persistence.ensure_active()
        if not self._extraction_persistence.succeed_extraction_chunk(
            run_id, chunk_index, owner_token, canonical_json(stats)
        ):
            raise MethodStateError("extraction chunk success ownership was lost")

    def interrupt_extraction_run(
        self, run_id: str, *, owner_token: str, reason: str
    ) -> None:
        self._validation_persistence.ensure_active()
        if not self._extraction_persistence.interrupt_extraction_run(
            run_id, owner_token, nonempty_text("reason", reason), time.time()
        ):
            raise MethodStateError("extraction run interrupt ownership was lost")
        self._extraction_persistence.interrupt_running_chunks(run_id, owner_token)

    def resume_extraction_run(
        self, run_id: str, *, owner_token: str
    ) -> tuple[int, ...]:
        self._validation_persistence.ensure_active()
        nonempty_text("owner_token", owner_token)
        if not self._extraction_persistence.resume_extraction_run(
            run_id, time.time()
        ):
            raise MethodStateError("extraction run cannot resume")
        return self._extraction_persistence.retryable_extraction_chunks(run_id)

    def fail_extraction_chunk(
        self, run_id: str, chunk_index: int, *, owner_token: str,
        error_kind: str, error_identity: str,
    ) -> None:
        self._validation_persistence.ensure_active()
        error_kind = nonempty_text("error_kind", error_kind)
        error_identity = nonempty_text("error_identity", error_identity)
        if not self._extraction_persistence.fail_extraction_chunk(
            run_id, chunk_index, owner_token, error_kind, error_identity
        ):
            raise MethodStateError("extraction chunk failure ownership was lost")
        self._extraction_persistence.mark_run_failed_from_chunk(
            run_id, error_kind, error_identity, time.time()
        )

    def succeed_extraction_run(self, run_id: str, *, owner_token: str) -> None:
        self._validation_persistence.ensure_active()
        if self._extraction_persistence.unfinished_extraction_chunks(run_id):
            raise MethodStateError("extraction run has unfinished chunks")
        if not self._extraction_persistence.succeed_extraction_run(
            method_id(run_id), owner_token, time.time()
        ):
            raise MethodStateError("extraction run success ownership was lost")

    def fail_extraction_run(
        self, run_id: str, *, owner_token: str,
        error_kind: str, error_identity: str,
    ) -> None:
        self._validation_persistence.ensure_active()
        if not self._extraction_persistence.fail_extraction_run(
            method_id(run_id),
            owner_token,
            nonempty_text("error_kind", error_kind),
            nonempty_text("error_identity", error_identity),
            time.time(),
        ):
            raise MethodStateError("extraction run failure ownership was lost")
        self._extraction_persistence.interrupt_running_chunks(run_id, owner_token)
