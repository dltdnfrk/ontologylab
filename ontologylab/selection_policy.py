"""F9 ranking: ready > usable full text > grade > source > stage > length > hash."""

from __future__ import annotations

from typing import assert_never

from ontologylab.selection_types import (
    NOT_READY,
    ContentKind,
    EvidenceGrade,
    InventoryEntry,
    PolicyVersion,
    PublicationStage,
    ReadyState,
    RepresentationCandidate,
    SourceTier,
)


def parse_ready_state(raw: str) -> ReadyState:
    try:
        return ReadyState(raw)
    except ValueError:
        return ReadyState.OTHER


def parse_kind(raw: str) -> ContentKind:
    try:
        return ContentKind(raw)
    except ValueError:
        return ContentKind.METADATA_ONLY


def parse_grade(raw: str) -> EvidenceGrade:
    try:
        return EvidenceGrade(raw)
    except ValueError:
        return EvidenceGrade.D


def parse_stage(raw: str) -> PublicationStage:
    try:
        return PublicationStage(raw)
    except ValueError:
        return PublicationStage.UNKNOWN


def parse_source(raw: str) -> SourceTier:
    try:
        return SourceTier(raw) if raw else SourceTier.OTHER
    except ValueError:
        return SourceTier.OTHER


def ready_rank(state: ReadyState) -> int:
    match state:
        case ReadyState.READY:
            return 0
        case ReadyState.STAGED | ReadyState.QUARANTINED | ReadyState.OTHER:
            return 1
        case unreachable:
            assert_never(unreachable)


def usable_full_text_rank(kind: ContentKind) -> int:
    match kind:
        case ContentKind.FULLTEXT:
            return 0
        case ContentKind.ABSTRACT:
            return 1
        case ContentKind.EXCERPT:
            return 2
        case ContentKind.METADATA_ONLY:
            return 3
        case unreachable:
            assert_never(unreachable)


def grade_rank(grade: EvidenceGrade) -> int:
    match grade:
        case EvidenceGrade.A:
            return 0
        case EvidenceGrade.B:
            return 1
        case EvidenceGrade.C:
            return 2
        case EvidenceGrade.D:
            return 3
        case unreachable:
            assert_never(unreachable)


def source_rank(source: SourceTier) -> int:
    match source:
        case SourceTier.PUBLISHER | SourceTier.PMC:
            return 0
        case SourceTier.REGISTRY:
            return 1
        case SourceTier.AGGREGATOR:
            return 2
        case SourceTier.WEB | SourceTier.UPLOAD | SourceTier.SAMPLE:
            return 3
        case SourceTier.OTHER:
            return 4
        case unreachable:
            assert_never(unreachable)


def stage_rank(stage: PublicationStage) -> int:
    match stage:
        case PublicationStage.PUBLISHED:
            return 0
        case PublicationStage.ACCEPTED:
            return 1
        case PublicationStage.SUBMITTED:
            return 2
        case PublicationStage.UNKNOWN:
            return 3
        case unreachable:
            assert_never(unreachable)


def policy_parts(policy: PolicyVersion) -> tuple[str, ...]:
    match policy:
        case PolicyVersion.V1:
            return (
                str(policy),
                "ready",
                "usable_full_text",
                "grade",
                "source",
                "stage",
                "length",
                "lexical_hash",
            )
        case PolicyVersion.V2:
            return (
                str(policy),
                "ready",
                "stage",
                "usable_full_text",
                "grade",
                "source",
                "length",
                "lexical_hash",
            )
        case unreachable:
            assert_never(unreachable)


def sort_key(
    entry: InventoryEntry, policy: PolicyVersion,
) -> tuple[int, int, int, int, int, int, str]:
    match policy:
        case PolicyVersion.V1:
            return (
                entry.ready_rank,
                entry.usable_full_text_rank,
                entry.grade_rank,
                entry.source_rank,
                entry.stage_rank,
                -entry.byte_length,
                entry.content_hash,
            )
        case PolicyVersion.V2:
            return (
                entry.ready_rank,
                entry.stage_rank,
                entry.usable_full_text_rank,
                entry.grade_rank,
                entry.source_rank,
                -entry.byte_length,
                entry.content_hash,
            )
        case unreachable:
            assert_never(unreachable)


def inventory_entry(candidate: RepresentationCandidate) -> InventoryEntry:
    state = parse_ready_state(candidate.state)
    rejection = None if state is ReadyState.READY else NOT_READY
    return InventoryEntry(
        representation_id=candidate.representation_id,
        ready_rank=ready_rank(state),
        usable_full_text_rank=usable_full_text_rank(parse_kind(candidate.kind)),
        grade_rank=grade_rank(parse_grade(candidate.evidence_grade)),
        source_rank=source_rank(parse_source(candidate.source)),
        stage_rank=stage_rank(parse_stage(candidate.stage)),
        byte_length=candidate.byte_length,
        content_hash=candidate.content_hash,
        rejection_reason=rejection,
    )


def select_winner(
    inventory: tuple[InventoryEntry, ...],
    policy: PolicyVersion,
) -> InventoryEntry | None:
    ready = tuple(
        entry for entry in inventory if entry.rejection_reason is None
    )
    if not ready:
        return None
    winner = min(ready, key=lambda entry: sort_key(entry, policy))
    match policy:
        case PolicyVersion.V1:
            if winner.usable_full_text_rank != 0:
                return None
            return winner
        case PolicyVersion.V2:
            return winner
        case unreachable:
            assert_never(unreachable)
