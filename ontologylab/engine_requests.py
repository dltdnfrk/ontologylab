"""Compatibility-preserving request-aware engine dispatcher."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Protocol, runtime_checkable

from ontologylab.models import Engine


class EngineTask(StrEnum):
    RESEARCH_PLAN = "research_plan"


@dataclass(frozen=True, slots=True)
class EngineRequest:
    task: EngineTask
    prompt: str
    model: str | None = None


@runtime_checkable
class EngineRequestHandler(Protocol):
    async def generate_request(
        self, request: EngineRequest
    ) -> tuple[str, dict[str, Any]]: ...


async def generate_for_request(
    engine: Engine,
    request: EngineRequest,
) -> tuple[str, dict[str, Any]]:
    """Dispatch one billed generation for an immutable engine request."""
    if isinstance(engine, EngineRequestHandler):
        text, usage = await engine.generate_request(request)
    else:
        text, usage = await engine.generate(
            request.prompt, model=request.model
        )
    copied_usage = dict(usage)
    copied_usage["task"] = request.task.value
    return text, copied_usage
