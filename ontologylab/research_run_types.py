"""Domain-owned Research start input and run-service contracts."""

from __future__ import annotations

import unicodedata
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Literal, TypeAlias

from ontologylab.models import Engine
from ontologylab.research_artifact_types import ResearchArtifactPointers
from ontologylab.research_spec import (
    InteractionDecision,
    InteractionPolicy,
    ResearchExecutionControls,
    ResearchOrigin,
    ResearchSpec,
    ResearchSpecDraft,
    ResearchSpecParseError,
    SourceEligibilityPolicy,
    build_research_spec,
)

if TYPE_CHECKING:
    from ontologylab.extractor import ExtractionOutcome
    from ontologylab.research_plan import PlannerReading

ResearchPhase: TypeAlias = Literal["collect", "extract"]
EngineFactory: TypeAlias = Callable[[], Engine]
SourceEventDetail: TypeAlias = str | int | None


@dataclass(frozen=True, slots=True)
class ResearchStartInput:
    topic: str
    origin: ResearchOrigin
    interaction_policy: InteractionPolicy
    interaction_decision: InteractionDecision
    controls: ResearchExecutionControls

    def __post_init__(self) -> None:
        normalized = unicodedata.normalize(
            "NFC", " ".join(self.topic.split())
        )
        object.__setattr__(self, "topic", normalized)
        if self.interaction_policy is not InteractionPolicy.for_origin(
            self.origin
        ):
            raise ResearchSpecParseError(
                "$.interaction_policy", "origin_policy_mismatch"
            )

    @property
    def starts_job(self) -> bool:
        return self.interaction_decision in {
            InteractionDecision.EXECUTE,
            InteractionDecision.DECOMPOSE,
        }

    def compile(self, reading: PlannerReading) -> ResearchSpec:
        if not self.starts_job:
            raise ResearchSpecParseError(
                "$.interaction_decision", "job_not_authorized"
            )
        return build_research_spec(
            ResearchSpecDraft(
                schema_version="research-spec-v1",
                parent_spec_id=None,
                origin=self.origin,
                goal=reading.goal,
                explicit_constraints=(),
                evidence_needs=reading.evidence_needs,
                assumptions=reading.assumptions,
                interaction_policy=self.interaction_policy,
                source_eligibility_policy=SourceEligibilityPolicy(),
            )
        )


def build_research_start_input(
    *,
    topic: str,
    origin: ResearchOrigin,
    interaction_decision: InteractionDecision,
    sources: list[str] | tuple[str, ...],
    limit: int,
    max_queries: int,
    fulltext: bool,
    citation_expansion: bool,
    citation_seed_count: int,
    citation_limit: int,
    engine: str,
    model: str | None,
    max_engine_calls: int,
    time_budget: float,
    seed: int,
) -> ResearchStartInput:
    return ResearchStartInput(
        topic=topic,
        origin=origin,
        interaction_policy=InteractionPolicy.for_origin(origin),
        interaction_decision=interaction_decision,
        controls=ResearchExecutionControls(
            sources=tuple(sources),
            limit=limit,
            max_queries=max_queries,
            fulltext=fulltext,
            citation_expansion=citation_expansion,
            citation_seed_count=citation_seed_count,
            citation_limit=citation_limit,
            engine=engine,
            model=model,
            max_engine_calls=max_engine_calls,
            time_budget=time_budget,
            seed=seed,
        ),
    )


@dataclass(frozen=True, slots=True)
class ResearchRunInput:
    start_input: ResearchStartInput
    data_dir: Path
    job_dir: Path


@dataclass(frozen=True, slots=True)
class ResearchRunCallbacks:
    on_phase: Callable[[ResearchPhase], None]
    on_progress: Callable[[str], None]
    on_source_event: Callable[[str, str, SourceEventDetail], None]
    on_model_resolved: Callable[[str | None], None]
    on_stats: Callable[[Mapping[str, int]], None]
    on_artifacts_changed: Callable[[ResearchArtifactPointers], None]
    abort_reason: Callable[[], str]


@dataclass(frozen=True, slots=True)
class ResearchRunResult:
    extraction_outcome: ExtractionOutcome | None
