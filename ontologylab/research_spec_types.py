from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum, unique
from typing import Final, TypeAlias, assert_never

JsonValue: TypeAlias = (
    str | int | float | bool | None | list["JsonValue"] | dict[str, "JsonValue"]
)
JsonObject: TypeAlias = dict[str, JsonValue]
_CONTROL_FIELDS: Final = (
    "sources", "limit", "max_queries", "fulltext", "citation_expansion",
    "citation_seed_count", "citation_limit", "engine", "model",
    "max_engine_calls", "time_budget", "seed",
)


@unique
class EvidenceNeedKind(StrEnum):
    GENERAL = "general"
    BIBLIOGRAPHIC_EXISTENCE = "bibliographic_existence"
    CONTEXT = "context"
    MECHANISM = "mechanism"
    METHOD = "method"
    RESULT = "result"
    SAFETY = "safety"
    TRIAL = "trial"


@unique
class ContentClass(StrEnum):
    UNKNOWN = "unknown"
    METADATA_ONLY = "metadata_only"
    ABSTRACT = "abstract"
    FULLTEXT = "fulltext"


@unique
class ResearchOrigin(StrEnum):
    CHAT = "chat"
    DIRECT_API = "direct_api"


@unique
class InteractionPolicy(StrEnum):
    CHAT_SELECTIVE = "chat_selective"
    NEVER = "never"

    @classmethod
    def for_origin(cls, origin: ResearchOrigin) -> InteractionPolicy:
        match origin:
            case ResearchOrigin.CHAT:
                return cls.CHAT_SELECTIVE
            case ResearchOrigin.DIRECT_API:
                return cls.NEVER
            case unreachable:
                assert_never(unreachable)


@unique
class InteractionDecision(StrEnum):
    EXECUTE = "execute"
    DECOMPOSE = "decompose"
    CLARIFY = "clarify"
    ABSTAIN = "abstain"


@dataclass(frozen=True, slots=True)
class ResearchSpecParseError(Exception):
    path: str
    code: str

    def __str__(self) -> str:
        return f"{self.path}: {self.code}"


@dataclass(frozen=True, slots=True)
class EvidenceNeedDraft:
    kind: EvidenceNeedKind
    description: str
    mandatory: bool
    minimum_content_override: ContentClass | None


@dataclass(frozen=True, slots=True)
class EvidenceNeed:
    need_id: str
    kind: EvidenceNeedKind
    description: str
    mandatory: bool
    minimum_content: ContentClass


@dataclass(frozen=True, slots=True)
class EvidenceRecordClass:
    content_class: ContentClass
    retracted: bool


@dataclass(frozen=True, slots=True)
class SourceEligibilityPolicy:
    policy_version: str = "source-eligibility-v1"

    def minimum_content(self, kind: EvidenceNeedKind) -> ContentClass:
        match kind:
            case EvidenceNeedKind.BIBLIOGRAPHIC_EXISTENCE:
                return ContentClass.METADATA_ONLY
            case EvidenceNeedKind.CONTEXT:
                return ContentClass.ABSTRACT
            case (EvidenceNeedKind.GENERAL | EvidenceNeedKind.MECHANISM |
                  EvidenceNeedKind.METHOD | EvidenceNeedKind.RESULT |
                  EvidenceNeedKind.SAFETY | EvidenceNeedKind.TRIAL):
                return ContentClass.FULLTEXT
            case unreachable:
                assert_never(unreachable)

    def is_eligible(
        self,
        requirement: ContentClass,
        record: EvidenceRecordClass,
    ) -> bool:
        content = record.content_class
        if record.retracted or content is ContentClass.UNKNOWN:
            return False
        rank = {
            ContentClass.METADATA_ONLY: 1,
            ContentClass.ABSTRACT: 2,
            ContentClass.FULLTEXT: 3,
        }
        return rank[content] >= rank[requirement]


@dataclass(frozen=True, slots=True)
class ResearchExecutionControls:
    sources: tuple[str, ...]
    limit: int
    max_queries: int
    fulltext: bool
    citation_expansion: bool
    citation_seed_count: int
    citation_limit: int
    engine: str
    model: str | None
    max_engine_calls: int
    time_budget: float
    seed: int

    @staticmethod
    def field_names() -> tuple[str, ...]:
        return _CONTROL_FIELDS

    def to_json_value(self) -> JsonObject:
        return {
            "sources": list(self.sources), "limit": self.limit,
            "max_queries": self.max_queries, "fulltext": self.fulltext,
            "citation_expansion": self.citation_expansion,
            "citation_seed_count": self.citation_seed_count,
            "citation_limit": self.citation_limit, "engine": self.engine,
            "model": self.model, "max_engine_calls": self.max_engine_calls,
            "time_budget": self.time_budget, "seed": self.seed,
        }


@dataclass(frozen=True, slots=True)
class ResearchSpecDraft:
    schema_version: str
    parent_spec_id: str | None
    origin: ResearchOrigin
    goal: str
    explicit_constraints: tuple[str, ...]
    evidence_needs: tuple[EvidenceNeed, ...]
    assumptions: tuple[str, ...]
    interaction_policy: InteractionPolicy
    source_eligibility_policy: SourceEligibilityPolicy


@dataclass(frozen=True, slots=True)
class ResearchSpec:
    schema_version: str
    spec_id: str
    parent_spec_id: str | None
    origin: ResearchOrigin
    goal: str
    explicit_constraints: tuple[str, ...]
    evidence_needs: tuple[EvidenceNeed, ...]
    assumptions: tuple[str, ...]
    interaction_policy: InteractionPolicy
    source_eligibility_policy: SourceEligibilityPolicy
