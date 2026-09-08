"""Machine-readable prompt contract for combined research planning."""

from __future__ import annotations

import json
import re

RESEARCH_PLAN_MARKER_OPEN = "<research-plan>"
RESEARCH_PLAN_MARKER_CLOSE = "</research-plan>"

_RESEARCH_PLAN_SECTION_RE = re.compile(
    re.escape(RESEARCH_PLAN_MARKER_OPEN) + r"\n(.*?)\n"
    + re.escape(RESEARCH_PLAN_MARKER_CLOSE),
    re.DOTALL,
)


def prepare_research_plan_prompt(
    base_prompt: str,
    query_markers: tuple[str, str],
) -> str:
    """Retag a query prompt with the combined planner's task contract."""
    query_open, query_close = query_markers
    return (
        base_prompt.replace(
            query_open, RESEARCH_PLAN_MARKER_OPEN,
        ).replace(
            query_close, RESEARCH_PLAN_MARKER_CLOSE,
        )
        + "\nAlso return goal, evidence_needs (need_id, kind, description, "
        "required, minimum_content_class), assumptions, and "
        "need_ids/dependencies on every query."
    )


def mock_research_plan(prompt: str) -> str:
    """Return one valid, deterministic combined research plan."""
    section = _RESEARCH_PLAN_SECTION_RE.search(prompt)
    topic = section.group(1).strip() if section else ""
    goal = topic[:500] or "research topic"
    query = " ".join(topic.split()[:6])[:120].strip() or "research topic"
    terms = query.split()[:2] or ["research"]
    payload = {
        "goal": goal,
        "evidence_needs": [
            {
                "need_id": "primary",
                "kind": "general",
                "description": f"Evidence addressing {goal}"[:500],
                "required": True,
                "minimum_content_class": "fulltext",
            }
        ],
        "assumptions": [],
        "queries": [
            {
                "query": query,
                "axis": "topic",
                "terms": terms,
                "need_ids": ["primary"],
                "dependencies": [],
            }
        ],
        "notes": "Deterministic offline research plan.",
    }
    return (
        "```json\n"
        + json.dumps(payload, ensure_ascii=False, indent=2)
        + "\n```"
    )
