"""Typed scholarly-query planning and citation-neighborhood expansion."""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass

from ontologylab import literature_citations, research_plan, research_spec
from ontologylab.connectors.base import RawDocument
from ontologylab.engine_requests import EngineRequest, EngineTask, generate_for_request
from ontologylab.engines import EngineError, extract_fenced_block
from ontologylab.models import Engine
from ontologylab.research_planner_contract import prepare_research_plan_prompt
from ontologylab.searchquery import (
    DEFAULT_SEARCH_QUERIES,
    MAX_QUERY_LEN,
    MAX_SEARCH_QUERIES,
    MAX_TERMS,
    build_search_queries_prompt,
)

expand_citation_neighborhood = literature_citations.expand_citation_neighborhood
_TRUNCATED_PREFIXES = frozenset({
    "acclimat", "biosynth", "flavono", "hormon", "metabolit", "metabolom", "micropropagat", "phenol", "propagat", "rooting", "transplant",
})
_MAX_PARTS = 4


PlanningEngine = Engine


def _clean(value: research_spec.JsonValue, *, max_length: int = MAX_QUERY_LEN) -> str:
    if not isinstance(value, str):
        return ""
    cleaned = " ".join(value.split())
    return cleaned if 0 < len(cleaned) <= max_length else ""


def _wildcard(term: str) -> str:
    return f"{term}*" if term.casefold() in _TRUNCATED_PREFIXES else term


@dataclass(frozen=True, slots=True)
class ScholarlyQuery:
    """One complementary search axis with source-independent concepts."""

    query: str
    axis: str
    terms: tuple[str, ...]

    def for_source(self, source: str) -> str:
        """Translate concepts into one scholarly API's query dialect."""
        parts = self.terms or (self.query,)
        if source == "openalex":
            joined = " ".join(f'"{part}"' for part in parts)
            return f"title_and_abstract.search:{joined}"
        if source == "pubmed":
            return " AND ".join(
                f"{term}[Title/Abstract]" if term.endswith("*")
                else f'"{part}"[Title/Abstract]'
                for part in parts if (term := _wildcard(part))
            )
        if source == "elsevier":
            return " AND ".join(
                f"TITLE-ABS-KEY({term})" if term.endswith("*")
                else f'TITLE-ABS-KEY("{part}")'
                for part in parts if (term := _wildcard(part))
            )
        if source == "core":
            return " AND ".join(f'"{part}"' for part in parts)
        if source == "springer":
            return f'"{max(parts, key=len)}"'
        if source == "semanticscholar":
            return " ".join(parts)
        return self.query


def parse_scholarly_queries(
    raw_text: str, topic: str, *, max_queries: int = DEFAULT_SEARCH_QUERIES,
) -> tuple[list[ScholarlyQuery], str]:
    """Parse distinct query axes; legacy query-only items remain usable."""
    del topic
    try:
        payload: research_spec.JsonValue = json.loads(extract_fenced_block(raw_text, "json"))
    except json.JSONDecodeError:
        return [], ""
    if not isinstance(payload, dict):
        return [], ""
    items = payload.get("queries")
    if not isinstance(items, list):
        items = [payload]
    cap = max(1, min(max_queries, MAX_SEARCH_QUERIES))
    queries: list[ScholarlyQuery] = []
    seen: set[str] = set()
    for item in items:
        if not isinstance(item, dict):
            continue
        query = _clean(item.get("query"))
        if not query or query.casefold() in seen:
            continue
        raw_terms = item.get("terms")
        values = raw_terms if isinstance(raw_terms, list) else []
        terms = tuple(
            term for value in values if (term := _clean(value, max_length=60))
        )[:_MAX_PARTS]
        if not terms:
            terms = (" ".join(query.split()[:MAX_TERMS]),)
        axis = _clean(item.get("axis"), max_length=40) or "topic"
        queries.append(ScholarlyQuery(query=query, axis=axis, terms=terms))
        seen.add(query.casefold())
        if len(queries) == cap:
            break
    notes = _clean(payload.get("notes"), max_length=200)
    return queries, notes


def _strings(value: research_spec.JsonValue) -> tuple[str, ...] | None:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        return None
    return tuple(item for item in value if isinstance(item, str))


def parse_research_plan(raw_text: str, topic: str, sources: tuple[str, ...], *, max_queries: int) -> research_plan.PlannerReading | None:
    """Parse the strict combined spec-and-plan response."""
    try:
        payload: research_spec.JsonValue = json.loads(extract_fenced_block(raw_text, "json"))
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    goal = _clean(payload.get("goal"), max_length=500)
    raw_needs = payload.get("evidence_needs")
    raw_assumptions = payload.get("assumptions")
    if not goal or not isinstance(raw_needs, list) or not isinstance(raw_assumptions, list):
        return None
    needs: list[research_spec.EvidenceNeed] = []
    aliases: dict[str, str] = {}
    for item in raw_needs:
        if not isinstance(item, dict):
            return None
        alias = _clean(item.get("need_id"), max_length=80)
        description = _clean(item.get("description"), max_length=500)
        required = item.get("required")
        try:
            kind = research_spec.EvidenceNeedKind(_clean(item.get("kind"), max_length=40))
            minimum = research_spec.ContentClass(
                _clean(item.get("minimum_content_class"), max_length=40)
            )
        except ValueError:
            return None
        if not alias or not description or not isinstance(required, bool):
            return None
        need = research_spec.build_evidence_need(
            research_spec.EvidenceNeedDraft(kind, description, required, minimum)
        )
        if alias in aliases or need.need_id in aliases.values():
            return None
        aliases[alias] = need.need_id
        needs.append(need)
    assumptions = tuple(
        item for value in raw_assumptions if (item := _clean(value, max_length=500))
    )
    queries, _notes = parse_scholarly_queries(raw_text, topic, max_queries=max_queries)
    raw_queries = payload.get("queries")
    if not needs or not queries or not isinstance(raw_queries, list) or len(raw_queries) != len(queries):
        return None
    axes: list[research_plan.NeedLinkedAxis] = []
    known_axes: set[str] = set()
    for query, item in zip(queries, raw_queries, strict=True):
        if not isinstance(item, dict):
            return None
        raw_need_ids = _strings(item.get("need_ids"))
        dependencies = _strings(item.get("dependencies"))
        raw_sources = item.get("source_queries", {})
        if raw_need_ids is None or dependencies is None or not isinstance(raw_sources, dict):
            return None
        if any(not isinstance(value, str) for value in raw_sources.values()):
            return None
        need_ids = tuple(aliases.get(value, "") for value in raw_need_ids)
        if not need_ids or any(not value for value in need_ids):
            return None
        if any(dependency not in known_axes for dependency in dependencies):
            return None
        source_queries = tuple(
            (source, query.for_source(source)) for source in sources
        )
        axes.append(research_plan.NeedLinkedAxis(
            query.axis, query.query, query.terms, need_ids, dependencies, source_queries,
        ))
        known_axes.add(query.axis)
    return research_plan.PlannerReading(goal, tuple(needs), assumptions, tuple(axes), None)


def _baseline_reading(topic: str, sources: tuple[str, ...], reason: research_plan.DegradedReason) -> research_plan.PlannerReading:
    query = ScholarlyQuery(topic, "topic", (topic,))
    axis = research_plan.NeedLinkedAxis(
        axis="topic", query=topic, terms=(topic,), need_ids=("pending",),
        dependencies=(),
        source_queries=tuple((source, query.for_source(source)) for source in sources),
    )
    return research_plan.degraded_reading(topic, axis, reason)


async def formulate_research_plan(topic: str, engine: PlanningEngine | None, *, sources: tuple[str, ...], model: str | None = None, max_queries: int = DEFAULT_SEARCH_QUERIES) -> tuple[research_plan.PlannerReading, research_spec.JsonObject]:
    """Make one combined planning call or return a visible typed baseline."""
    if engine is None:
        return _baseline_reading(topic, sources, research_plan.DegradedReason.UNAVAILABLE), {"error": "no engine configured"}
    prompt = prepare_research_plan_prompt(
        build_search_queries_prompt(topic, max_queries),
        ("<query-expansion>", "</query-expansion>"),
    )
    try:
        raw_text, usage = await generate_for_request(engine, EngineRequest(EngineTask.RESEARCH_PLAN, prompt, model))
    except EngineError as exc:
        return _baseline_reading(topic, sources, research_plan.DegradedReason.ENGINE_ERROR), {"error": str(exc)}
    result = dict(usage or {})
    reading = parse_research_plan(raw_text, topic, sources, max_queries=max_queries)
    if reading is None:
        result["error"] = "engine returned an invalid research plan"
        return _baseline_reading(topic, sources, research_plan.DegradedReason.INVALID_OUTPUT), result
    return reading, result


async def formulate_scholarly_queries(
    topic: str,
    engine: PlanningEngine | None,
    *,
    model: str | None = None,
    max_queries: int = DEFAULT_SEARCH_QUERIES,
) -> tuple[list[ScholarlyQuery], research_spec.JsonObject]:
    """Create source-translatable axes; fail open to one raw-topic axis."""
    fallback = [ScholarlyQuery(topic, "topic", (topic,))]
    if engine is None:
        return fallback, {"error": "no engine configured"}
    try:
        raw_text, usage = await engine.generate(
            build_search_queries_prompt(topic, max_queries),
            model=model,
        )
    except EngineError as exc:
        return fallback, {"error": str(exc)}
    result = dict(usage or {})
    queries, notes = parse_scholarly_queries(
        raw_text,
        topic,
        max_queries=max_queries,
    )
    result["notes"] = notes
    if not queries:
        result.setdefault("error", "engine returned no usable queries")
        return fallback, result
    return queries, result


def corpus_summary(
    *, raw_count: int, documents: list[RawDocument],
    queries: list[ScholarlyQuery],
    assessment: research_spec.JsonObject | None = None,
) -> research_spec.JsonObject:
    source_counts: Counter[str] = Counter()
    for document in documents:
        source_counts.update(
            document.all_sources or ((document.source,) if document.source else ())
        )
    summary: research_spec.JsonObject = {
        "raw_documents": raw_count,
        "unique_documents": len(documents),
        "duplicates_removed": max(0, raw_count - len(documents)),
        "corroborated_documents": sum(
            document.source_count >= 2 for document in documents
        ),
        "source_counts": dict(sorted(source_counts.items())),
        "query_axes": [query.axis for query in queries],
    }
    if assessment is not None:
        summary["acquisition_assessment"] = assessment
    return summary
