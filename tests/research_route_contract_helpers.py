from __future__ import annotations

import json

from ontologylab import research_spec
from ontologylab.server import schemas


def execution_controls(
    values: research_spec.JsonObject | None = None,
) -> research_spec.ResearchExecutionControls:
    payload: research_spec.JsonObject = {
        "sources": ["crossref"],
        "limit": 7,
        "max_queries": 2,
        "fulltext": False,
        "citation_expansion": False,
        "citation_seed_count": 1,
        "citation_limit": 9,
        "engine": "mock",
        "model": "contract-model",
        "max_engine_calls": 3,
        "time_budget": 45.0,
        "seed": 17,
    }
    if values is not None:
        payload.update(values)
    return research_spec.parse_execution_controls(json.dumps(payload))


def build_start_input(
    *,
    topic: str,
    origin: research_spec.ResearchOrigin,
    decision: research_spec.InteractionDecision,
    controls: research_spec.ResearchExecutionControls | None = None,
) -> schemas.ResearchStartInput:
    execution = controls or execution_controls()
    return schemas.build_research_start_input(
        topic=topic,
        origin=origin,
        interaction_decision=decision,
        sources=execution.sources,
        limit=execution.limit,
        max_queries=execution.max_queries,
        fulltext=execution.fulltext,
        citation_expansion=execution.citation_expansion,
        citation_seed_count=execution.citation_seed_count,
        citation_limit=execution.citation_limit,
        engine=execution.engine,
        model=execution.model,
        max_engine_calls=execution.max_engine_calls,
        time_budget=execution.time_budget,
        seed=execution.seed,
    )
