from __future__ import annotations

import dataclasses
import json
import subprocess
import sys

import anyio
import pytest

from ontologylab import research_plan
from ontologylab.literature import formulate_research_plan
from ontologylab.research_plan import (
    DegradedReason,
    DirectOverrides,
    DuplicateExecutionError,
    NeedLinkedAxis,
    PlanBudgets,
    PlanSnapshot,
    PlanTransitionError,
    authorize_execution,
    broaden_plan,
    canonical_plan_json,
    create_initial_plan,
    retry_plan,
    validate_lineage,
)
from ontologylab.research_spec import JsonObject


def _axis(name: str = "mechanism", need: str = "need-1") -> NeedLinkedAxis:
    return NeedLinkedAxis(
        axis=name, query=f"apple rootstock {name}", terms=("apple rootstock", name),
        need_ids=(need,), dependencies=(),
        source_queries=(("openalex", f"title_and_abstract.search:{name}"),),
    )


def _controls(max_queries: int = 3) -> DirectOverrides:
    return DirectOverrides(
        ("openalex", "pubmed"), 20, max_queries, True, False, 0, 50,
        "claude", "sonnet", 12, 30.0, 7,
    )


def _initial(*, max_queries: int = 3) -> PlanSnapshot:
    return create_initial_plan(
        spec_id="sha256:spec", spec_hash="sha256:spec-hash", axes=(_axis(),),
        source_selection=("openalex", "pubmed"),
        direct_overrides=_controls(max_queries),
        budgets=PlanBudgets(max_queries, 12, 30.0),
    )


def test_snapshot_collections_and_nested_values_are_immutable() -> None:
    # Given
    plan = _initial()
    # When/Then
    with pytest.raises(dataclasses.FrozenInstanceError):
        plan.__setattr__("plan_version", 2)
    assert not hasattr(plan.axes[0].source_queries, "append")


def test_initial_broaden_and_retry_are_parent_linked_and_versioned() -> None:
    # Given
    first = _initial()
    # When
    second = broaden_plan(first, (_axis("outcome", "need-2"),), ("need-2",))
    third = retry_plan(second)
    # Then
    assert (first.plan_version, first.parent_plan_id) == (1, None)
    assert (second.plan_version, second.parent_plan_id) == (2, first.plan_id)
    assert (third.plan_version, third.parent_plan_id) == (3, second.plan_id)
    assert third.retry_of_plan_id == second.plan_id
    assert third.axes == second.axes
    validate_lineage((first, second, third))
    for snapshot in (first, second, third):
        assert research_plan.parse_canonical_plan(canonical_plan_json(snapshot)) == snapshot


def test_degraded_raw_topic_plan_is_visible() -> None:
    # Given/When
    plan = create_initial_plan(
        spec_id="sha256:baseline", spec_hash="sha256:baseline-hash",
        axes=(dataclasses.replace(
            _axis("topic", "general"),
            origin=research_plan.AxisOrigin.RAW_TOPIC_FALLBACK,
        ),),
        source_selection=("openalex",),
        direct_overrides=_controls(1), budgets=PlanBudgets(1, 12, 30.0),
        degraded_reason=DegradedReason.INVALID_OUTPUT,
    )
    # Then
    canonical = canonical_plan_json(plan)
    fetch_calls: list[str] = []
    payload = json.loads(canonical)
    assert payload["degraded_reason"] == "invalid_output"
    assert payload["axes"][0]["origin"] == "raw_topic_fallback"
    with pytest.raises(PlanTransitionError, match="degraded_reason"):
        dataclasses.replace(plan, degraded_reason=None)
    assert fetch_calls == []
    assert canonical_plan_json(plan) == canonical


def test_real_degraded_adapter_cannot_hide_its_reason() -> None:
    class InvalidEngine:
        async def generate(
            self, prompt: str, *, model: str | None = None,
        ) -> tuple[str, JsonObject]:
            del prompt, model
            return "```json\nnot json\n```", {}

    reading, _usage = anyio.run(
        lambda: formulate_research_plan(
            "raw topic", InvalidEngine(), sources=("openalex",), max_queries=1,
        )
    )
    plan = create_initial_plan(
        spec_id="sha256:baseline", spec_hash="sha256:baseline",
        axes=reading.axes, source_selection=("openalex",),
        direct_overrides=_controls(1), budgets=PlanBudgets(1, 12, 30.0),
        degraded_reason=reading.degraded_reason,
    )
    fetch_calls: list[str] = []

    stripped_axes = tuple(
        dataclasses.replace(axis, origin=research_plan.AxisOrigin.PLANNED)
        for axis in plan.axes
    )
    with pytest.raises(PlanTransitionError, match="fallback provenance"):
        dataclasses.replace(plan, axes=stripped_axes, degraded_reason=None)
    with pytest.raises(PlanTransitionError, match="degraded_reason"):
        dataclasses.replace(plan, degraded_reason=None)
    public = {field.name: getattr(plan, field.name) for field in dataclasses.fields(plan)
              if not field.name.startswith("_")}
    with pytest.raises(PlanTransitionError, match="factory capability"):
        PlanSnapshot(**public)
    public["axes"] = stripped_axes
    public["degraded_reason"] = None
    with pytest.raises(PlanTransitionError, match="factory capability"):
        PlanSnapshot(**public)
    assert research_plan.parse_canonical_plan(canonical_plan_json(plan)) == plan
    assert fetch_calls == []


def test_normal_public_reconstruction_fails_but_canonical_factory_round_trips() -> None:
    plan = _initial()
    public = {field.name: getattr(plan, field.name) for field in dataclasses.fields(plan)
              if not field.name.startswith("_")}

    with pytest.raises(PlanTransitionError, match="factory capability"):
        PlanSnapshot(**public)
    restored = research_plan.parse_canonical_plan(canonical_plan_json(plan))
    assert restored == plan
    assert canonical_plan_json(restored) == canonical_plan_json(plan)


def test_duplicate_execution_requires_an_explicit_retry_snapshot() -> None:
    # Given
    plan = _initial()
    executed = authorize_execution(plan, ())
    fetch_calls: list[str] = []
    # When/Then
    with pytest.raises(DuplicateExecutionError):
        authorize_execution(plan, executed)
    assert fetch_calls == []
    retry = retry_plan(plan)
    assert authorize_execution(retry, executed) == (plan.plan_id, retry.plan_id)


@pytest.mark.parametrize(
    "mutation",
    ["gap", "fork", "cycle", "retry_source", "retry_model", "retry_seed"],
)
def test_invalid_lineage_is_refused(mutation: str) -> None:
    # Given
    first = _initial()
    second = broaden_plan(first, (_axis("outcome", "need-2"),), ("need-2",))
    # When
    if mutation == "gap":
        broken = dataclasses.replace(second, plan_version=3)
    elif mutation == "fork":
        broken = retry_plan(first)
    elif mutation == "cycle":
        broken = dataclasses.replace(second, parent_plan_id=second.plan_id)
    else:
        retry = retry_plan(second)
        if mutation == "retry_source":
            controls = dataclasses.replace(retry.direct_overrides, sources=("pubmed",))
        elif mutation == "retry_model":
            controls = dataclasses.replace(retry.direct_overrides, model="changed")
        else:
            controls = dataclasses.replace(retry.direct_overrides, seed=99)
        broken = dataclasses.replace(retry, direct_overrides=controls)
    # Then
    with pytest.raises(PlanTransitionError):
        validate_lineage((first, second, broken))


def test_transition_bounds_and_axis_overflow_are_refused() -> None:
    # Given
    first = _initial(max_queries=2)
    second = broaden_plan(first, (_axis("outcome", "need-2"),), ("need-2",))
    # When/Then
    with pytest.raises(PlanTransitionError, match="broaden"):
        broaden_plan(second, (_axis("safety", "need-3"),), ("need-3",), (first, second))
    retry = retry_plan(second)
    with pytest.raises(PlanTransitionError, match="retry"):
        retry_plan(retry, (first, second, retry))
    with pytest.raises(PlanTransitionError, match="max_queries"):
        broaden_plan(first, (_axis("outcome", "need-2"), _axis("safety", "need-3")), ("need-2", "need-3"))


def test_whole_lineage_rejects_second_retry_and_sealed_duplicate_broaden() -> None:
    first = _initial(max_queries=3)
    first_retry = retry_plan(first)
    broadened = broaden_plan(
        first_retry, (_axis("outcome", "need-2"),), ("need-2",),
        (first, first_retry),
    )

    with pytest.raises(PlanTransitionError, match="retry"):
        retry_plan(broadened, (first, first_retry, broadened))
    forged_retry = research_plan._seal(dataclasses.replace(
        broadened, parent_plan_id=broadened.plan_id,
        plan_version=4, retry_of_plan_id=broadened.plan_id,
    ))
    with pytest.raises(PlanTransitionError, match="retry"):
        validate_lineage((first, first_retry, broadened, forged_retry))

    duplicate = research_plan._seal(dataclasses.replace(
        broadened, axes=first.axes, retry_of_plan_id=None,
    ))
    with pytest.raises(PlanTransitionError, match="novel"):
        validate_lineage((first, first_retry, duplicate))


def test_axis_label_and_source_query_identities_are_independently_novel() -> None:
    first = _initial(max_queries=3)
    same_label = dataclasses.replace(
        _axis("outcome", "need-2"), axis=first.axes[0].axis,
        query="different executable query",
        source_queries=(("openalex", "different executable query"),),
    )
    same_source_query = dataclasses.replace(
        _axis("outcome", "need-2"), source_queries=first.axes[0].source_queries,
    )

    for reused in (same_label, same_source_query):
        with pytest.raises(PlanTransitionError, match="novel"):
            broaden_plan(first, (reused,), ("need-2",))
        valid = broaden_plan(first, (_axis("outcome", "need-2"),), ("need-2",))
        forged = research_plan._seal(dataclasses.replace(valid, axes=(reused,)))
        with pytest.raises(PlanTransitionError, match="novel"):
            validate_lineage((first, forged))


def test_broaden_rejects_reused_axes_and_preserves_overrides() -> None:
    # Given
    first = _initial()
    # When/Then
    with pytest.raises(PlanTransitionError, match="novel"):
        broaden_plan(first, (_axis(),), ("need-1",))
    second = broaden_plan(first, (_axis("outcome", "need-2"),), ("need-2",))
    assert second.direct_overrides == first.direct_overrides


def test_parse_canonical_plan_wraps_unpaired_surrogate_encoding_error() -> None:
    # Given: otherwise canonical plan JSON with a string JSON can decode but UTF-8 cannot encode
    payload = json.loads(canonical_plan_json(_initial()))
    payload["spec_id"] = "\ud800"
    raw = json.dumps(payload, ensure_ascii=False, allow_nan=False, sort_keys=True,
                     separators=(",", ":"))

    # When/Then: the canonical parse boundary converts only that encoding failure
    with pytest.raises(PlanTransitionError, match="^invalid canonical plan$"):
        research_plan.parse_canonical_plan(raw)


def test_parse_canonical_plan_rejects_non_nfc_serialization() -> None:
    # Given
    plan = research_plan._seal(dataclasses.replace(_initial(), spec_id="Café"))
    canonical = canonical_plan_json(plan)
    decomposed = canonical.replace("Café", "Cafe\u0301")
    # When/Then
    for raw in (decomposed, decomposed.encode()):
        with pytest.raises(PlanTransitionError, match="canonical plan"):
            research_plan.parse_canonical_plan(raw)


def test_lineage_rejects_degraded_provenance_change_before_execution() -> None:
    # Given: independently factory-sealed normal and fallback plans with stable controls
    first = _initial(max_queries=2)
    fallback_axis = dataclasses.replace(
        _axis("outcome", "need-2"),
        origin=research_plan.AxisOrigin.RAW_TOPIC_FALLBACK,
    )
    fallback = create_initial_plan(
        spec_id=first.spec_id, spec_hash=first.spec_hash, axes=(fallback_axis,),
        source_selection=first.source_selection,
        direct_overrides=first.direct_overrides, budgets=first.budgets,
        degraded_reason=DegradedReason.INVALID_OUTPUT,
    )
    forged = research_plan._seal(dataclasses.replace(
        fallback, parent_plan_id=first.plan_id, plan_version=2,
    ))
    execution_calls: list[str] = []

    # When/Then: root provenance is immutable across the lineage and execution never starts
    with pytest.raises(PlanTransitionError, match="degraded provenance"):
        validate_lineage((first, forged))
        execution_calls.append(forged.plan_id)
    assert execution_calls == []


def test_canonical_plan_is_identical_in_fresh_processes() -> None:
    # Given
    script = "from tests.test_research_plan import _initial; from ontologylab.research_plan import canonical_plan_json; print(canonical_plan_json(_initial()))"
    # When
    outputs = [subprocess.check_output([sys.executable, "-c", script], text=True) for _ in range(2)]
    # Then
    assert outputs[0] == outputs[1]
