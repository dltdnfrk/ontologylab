from __future__ import annotations

from dataclasses import FrozenInstanceError

import anyio
import pytest

from ontologylab.engine_requests import (
    EngineRequest,
    EngineTask,
    generate_for_request,
)
from ontologylab.engines import EngineError
from ontologylab.models import Engine


class _LegacyEngine:
    def __init__(self, text: str, usage: dict[str, str | int]) -> None:
        self._text = text
        self.usage = usage
        self.prompts: list[tuple[str, str | None]] = []

    def name(self) -> str:
        return "legacy"

    async def generate(
        self, prompt: str, *, model: str | None = None
    ) -> tuple[str, dict[str, str | int]]:
        self.prompts.append((prompt, model))
        return self._text, self.usage


class _AwareEngine:
    def __init__(self, text: str, usage: dict[str, str | int]) -> None:
        self._text = text
        self.usage = usage
        self.requests: list[EngineRequest] = []
        self.prompts: list[tuple[str, str | None]] = []

    def name(self) -> str:
        return "aware"

    async def generate_request(
        self, request: EngineRequest
    ) -> tuple[str, dict[str, str | int]]:
        self.requests.append(request)
        return self._text, self.usage

    async def generate(
        self, prompt: str, *, model: str | None = None
    ) -> tuple[str, dict[str, str | int]]:
        self.prompts.append((prompt, model))
        return "legacy-path-text", {"calls": 1, "path": "legacy"}


class _FailingAwareEngine:
    def __init__(self, error: BaseException) -> None:
        self._error = error
        self.requests: list[EngineRequest] = []
        self.prompts: list[tuple[str, str | None]] = []

    def name(self) -> str:
        return "aware-fail"

    async def generate_request(
        self, request: EngineRequest
    ) -> tuple[str, dict[str, str | int]]:
        self.requests.append(request)
        raise self._error

    async def generate(
        self, prompt: str, *, model: str | None = None
    ) -> tuple[str, dict[str, str | int]]:
        self.prompts.append((prompt, model))
        return "legacy-fallback-text", {"calls": 1, "path": "legacy"}


def _plan_request() -> EngineRequest:
    return EngineRequest(
        task=EngineTask.RESEARCH_PLAN,
        prompt="research-plan-prompt",
        model="planner-model",
    )


def _dispatch(engine: Engine, request: EngineRequest) -> tuple[str, dict[str, str | int]]:
    return anyio.run(generate_for_request, engine, request)


def test_legacy_engine_receives_exact_prompt_and_model_once() -> None:
    engine = _LegacyEngine("legacy-text", {"calls": 1, "engine": "legacy"})
    request = _plan_request()

    text, usage = _dispatch(engine, request)

    assert engine.prompts == [(request.prompt, request.model)]
    assert text == "legacy-text"
    assert usage["task"] == EngineTask.RESEARCH_PLAN.value


def test_request_aware_engine_receives_exact_request_once_without_legacy_path() -> None:
    engine = _AwareEngine("aware-text", {"calls": 1, "engine": "aware"})
    request = _plan_request()

    text, usage = _dispatch(engine, request)

    assert engine.requests == [request]
    assert engine.requests[0] is request
    assert engine.prompts == []
    assert text == "aware-text"
    assert usage["task"] == EngineTask.RESEARCH_PLAN.value


def test_request_aware_failure_makes_one_call_and_does_not_fallback() -> None:
    error = EngineError("aware-failed")
    engine = _FailingAwareEngine(error)
    request = _plan_request()

    with pytest.raises(EngineError) as caught:
        _dispatch(engine, request)

    assert caught.value is error
    assert engine.requests == [request]
    assert engine.prompts == []


def test_engine_request_is_frozen() -> None:
    request = _plan_request()

    with pytest.raises(FrozenInstanceError):
        type(request).__setattr__(request, "prompt", "mutated")


def test_engine_request_is_slotted() -> None:
    request = _plan_request()

    assert EngineRequest.__slots__ == ("task", "prompt", "model")
    assert not hasattr(request, "__dict__")


def test_engine_task_is_closed_enum() -> None:
    assert list(EngineTask) == [EngineTask.RESEARCH_PLAN]
    assert EngineTask.RESEARCH_PLAN.value == "research_plan"
    with pytest.raises(ValueError):
        EngineTask("extraction")


def test_usage_mapping_is_copied_not_mutated_in_place() -> None:
    engine = _LegacyEngine("legacy-text", {"calls": 1, "engine": "legacy"})
    request = _plan_request()

    _text, usage = _dispatch(engine, request)

    assert usage is not engine.usage
    assert "task" not in engine.usage
    usage["calls"] = 99
    assert engine.usage["calls"] == 1


def test_caller_task_overwrites_forged_engine_task() -> None:
    engine = _AwareEngine("aware-text", {"calls": 1, "task": "forged"})
    request = _plan_request()

    _text, usage = _dispatch(engine, request)

    assert usage["task"] == EngineTask.RESEARCH_PLAN.value
    assert engine.usage["task"] == "forged"


def test_legacy_return_text_and_usage_are_preserved() -> None:
    engine = _LegacyEngine("legacy-text", {"calls": 1, "engine": "legacy"})
    request = _plan_request()

    text, usage = _dispatch(engine, request)

    assert text == "legacy-text"
    assert usage["calls"] == 1
    assert usage["engine"] == "legacy"
    assert usage["task"] == EngineTask.RESEARCH_PLAN.value


def test_request_aware_return_text_and_usage_are_preserved() -> None:
    engine = _AwareEngine("aware-text", {"calls": 1, "engine": "aware"})
    request = _plan_request()

    text, usage = _dispatch(engine, request)

    assert text == "aware-text"
    assert usage["calls"] == 1
    assert usage["engine"] == "aware"
    assert usage["task"] == EngineTask.RESEARCH_PLAN.value
    assert engine.prompts == []
