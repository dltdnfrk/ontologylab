"""Immutable, content-addressed research plans and bounded transitions."""

from __future__ import annotations

import hashlib
import json
import unicodedata
from dataclasses import asdict, dataclass, field, replace
from enum import StrEnum
from typing import Final, TypeAlias

from ontologylab import research_spec

PLAN_SCHEMA_VERSION: Final = 1


class DegradedReason(StrEnum):
    UNAVAILABLE = "planner_unavailable"
    ENGINE_ERROR = "planner_error"
    INVALID_OUTPUT = "invalid_output"


class PlanTransitionError(Exception):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class DuplicateExecutionError(Exception):
    def __init__(self, plan_id: str) -> None:
        super().__init__(plan_id)
        self.plan_id = plan_id


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise PlanTransitionError(message)


class AxisOrigin(StrEnum):
    PLANNED = "planned"
    RAW_TOPIC_FALLBACK = "raw_topic_fallback"


class _PlanCapability:
    def __init__(self, fallback: bool) -> None:
        self.fallback = fallback


_PLANNED_CAPABILITY = _PlanCapability(False)
_FALLBACK_CAPABILITY = _PlanCapability(True)


@dataclass(frozen=True, slots=True)
class NeedLinkedAxis:
    axis: str
    query: str
    terms: tuple[str, ...]
    need_ids: tuple[str, ...]
    dependencies: tuple[str, ...]
    source_queries: tuple[tuple[str, str], ...]
    origin: AxisOrigin = AxisOrigin.PLANNED

    def __post_init__(self) -> None:
        values = (self.axis, self.query, *self.terms, *self.need_ids, *self.dependencies,
                  *(value for pair in self.source_queries for value in pair))
        _require(all(isinstance(value, str) for value in values), "axis fields must be strings")
        _require(bool(self.axis and self.query and self.need_ids), "axis, query, and need_ids must be non-empty")
        _require(len(set(self.need_ids)) == len(self.need_ids), "axis need_ids must be unique")
        _require(len({source for source, _ in self.source_queries}) == len(self.source_queries), "axis source queries must be unique")


def _identity(value: str) -> str:
    return unicodedata.normalize("NFC", " ".join(value.split())).casefold()


def _axis_key(axis: NeedLinkedAxis) -> str:
    return _identity(axis.axis)


def _query_keys(axis: NeedLinkedAxis) -> set[tuple[str, str]]:
    return {(_identity(source), _identity(query)) for source, query in axis.source_queries}


DirectOverrides: TypeAlias = research_spec.ResearchExecutionControls


@dataclass(frozen=True, slots=True)
class PlannerReading:
    goal: str
    evidence_needs: tuple[research_spec.EvidenceNeed, ...]
    assumptions: tuple[str, ...]
    axes: tuple[NeedLinkedAxis, ...]
    degraded_reason: DegradedReason | None


@dataclass(frozen=True, slots=True)
class PlanBudgets:
    max_queries: int
    max_engine_calls: int
    time_budget: float

    def __post_init__(self) -> None:
        _require(not isinstance(self.max_queries, bool) and self.max_queries > 0, "max_queries must be a positive integer")
        _require(not isinstance(self.max_engine_calls, bool) and self.max_engine_calls > 0, "max_engine_calls must be a positive integer")
        _require(not isinstance(self.time_budget, bool) and self.time_budget > 0, "time_budget must be positive")


@dataclass(frozen=True, slots=True)
class StoppingPolicy:
    max_broaden_steps: int = 1
    max_retries_per_plan: int = 1
    linear_lineage: bool = True

    def __post_init__(self) -> None:
        _require((self.max_broaden_steps, self.max_retries_per_plan, self.linear_lineage) == (1, 1, True), "stopping policy v1 is fixed")


@dataclass(frozen=True, slots=True)
class PlanSnapshot:
    plan_id: str
    parent_plan_id: str | None
    spec_id: str
    spec_hash: str
    plan_version: int
    axes: tuple[NeedLinkedAxis, ...]
    source_selection: tuple[str, ...]
    direct_overrides: DirectOverrides
    budgets: PlanBudgets
    stopping_policy: StoppingPolicy
    degraded_reason: DegradedReason | None
    retry_of_plan_id: str | None
    _factory_capability: _PlanCapability | None = field(default=None, repr=False, compare=False)

    def __post_init__(self) -> None:
        capability = self._factory_capability
        _require(capability is _PLANNED_CAPABILITY or capability is _FALLBACK_CAPABILITY, "snapshot requires module factory capability")
        identity = (self.plan_id, self.spec_id, self.spec_hash, *self.source_selection)
        _require(all(isinstance(value, str) for value in identity), "plan identity fields must be strings")
        _require((self.parent_plan_id is None or isinstance(self.parent_plan_id, str)) and (self.retry_of_plan_id is None or isinstance(self.retry_of_plan_id, str)), "lineage IDs must be strings or null")
        _require(not isinstance(self.plan_version, bool) and self.plan_version > 0, "plan_version must be positive")
        labels = {_axis_key(axis) for axis in self.axes}
        queries = [key for axis in self.axes for key in _query_keys(axis)]
        _require(bool(self.axes) and len(labels) == len(self.axes) and len(set(queries)) == len(queries), "plan axis labels and source queries must be unique")
        _require(len(set(self.source_selection)) == len(self.source_selection), "source selection must be unique")
        visible = any(axis.origin is AxisOrigin.RAW_TOPIC_FALLBACK for axis in self.axes)
        _require(visible == (self.degraded_reason is not None), "axis origin and degraded_reason must agree")
        _require(capability is not None and capability.fallback == visible, "fallback provenance capability mismatch")


def degraded_reading(topic: str, axis: NeedLinkedAxis, reason: DegradedReason) -> PlannerReading:
    draft = research_spec.EvidenceNeedDraft(research_spec.EvidenceNeedKind.GENERAL, topic, True, research_spec.ContentClass.ABSTRACT)
    need = research_spec.build_evidence_need(draft)
    linked_axis = replace(axis, need_ids=(need.need_id,), origin=AxisOrigin.RAW_TOPIC_FALLBACK)
    return PlannerReading(topic, (need,), (f"planner_degraded:{reason.value}",), (linked_axis,), reason)


def _payload(plan: PlanSnapshot, *, include_id: bool) -> research_spec.JsonObject:
    payload = asdict(plan)
    payload["schema_version"] = PLAN_SCHEMA_VERSION
    del payload["_factory_capability"]
    payload["degraded_reason"] = plan.degraded_reason.value if plan.degraded_reason else None
    if not include_id:
        del payload["plan_id"]
    return payload


def _canonical(payload: research_spec.JsonObject) -> str:
    text = json.dumps(payload, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":"))
    return unicodedata.normalize("NFC", text)


def _plan_id(plan: PlanSnapshot) -> str:
    body = _canonical(_payload(plan, include_id=False)).encode()
    return f"sha256:{hashlib.sha256(body).hexdigest()}"


def _seal(draft: PlanSnapshot) -> PlanSnapshot:
    return replace(draft, plan_id=_plan_id(draft))


def canonical_plan_json(plan: PlanSnapshot) -> str:
    _require(plan.plan_id == _plan_id(plan), "plan_id does not match canonical content")
    return _canonical(_payload(plan, include_id=True))


def parse_canonical_plan(raw: str | bytes) -> PlanSnapshot:
    source = raw.decode() if isinstance(raw, bytes) else raw
    try:
        item = json.loads(source)
        controls = research_spec.parse_execution_controls(_canonical(item["direct_overrides"]))
        axes = tuple(NeedLinkedAxis(axis["axis"], axis["query"], tuple(axis["terms"]),
            tuple(axis["need_ids"]), tuple(axis["dependencies"]),
            tuple((pair[0], pair[1]) for pair in axis["source_queries"]), AxisOrigin(axis["origin"])) for axis in item["axes"])
        budget, policy = item["budgets"], item["stopping_policy"]
        reason = None if item["degraded_reason"] is None else DegradedReason(item["degraded_reason"])
        capability = _FALLBACK_CAPABILITY if reason is not None else _PLANNED_CAPABILITY
        plan = PlanSnapshot(item["plan_id"], item["parent_plan_id"], item["spec_id"], item["spec_hash"], item["plan_version"],
            axes, tuple(item["source_selection"]), controls, PlanBudgets(budget["max_queries"], budget["max_engine_calls"], budget["time_budget"]),
            StoppingPolicy(policy["max_broaden_steps"], policy["max_retries_per_plan"], policy["linear_lineage"]), reason, item["retry_of_plan_id"], capability)
    except (KeyError, TypeError, ValueError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise PlanTransitionError("invalid canonical plan") from error
    try:
        canonical = canonical_plan_json(plan)
    except UnicodeEncodeError as error:
        raise PlanTransitionError("invalid canonical plan") from error
    _require(canonical == source, "canonical plan bytes or fields do not match")
    return plan


def create_initial_plan(*, spec_id: str, spec_hash: str, axes: tuple[NeedLinkedAxis, ...], source_selection: tuple[str, ...], direct_overrides: DirectOverrides, budgets: PlanBudgets, degraded_reason: DegradedReason | None = None) -> PlanSnapshot:
    return _seal(PlanSnapshot(
        plan_id="pending", parent_plan_id=None,
        spec_id=unicodedata.normalize("NFC", spec_id),
        spec_hash=unicodedata.normalize("NFC", spec_hash), plan_version=1,
        axes=axes, source_selection=source_selection, direct_overrides=direct_overrides,
        budgets=budgets, stopping_policy=StoppingPolicy(),
        degraded_reason=degraded_reason, retry_of_plan_id=None,
        _factory_capability=_FALLBACK_CAPABILITY if degraded_reason is not None else _PLANNED_CAPABILITY,
    ))


def broaden_plan(prior: PlanSnapshot, axes: tuple[NeedLinkedAxis, ...], unmet_required_need_ids: tuple[str, ...], lineage: tuple[PlanSnapshot, ...] = ()) -> PlanSnapshot:
    history = lineage or (prior,)
    if lineage:
        validate_lineage(history)
    else:
        canonical_plan_json(prior)
    _require(history[-1].plan_id == prior.plan_id, "broaden would fork the linear lineage")
    _require(not any(item.plan_version > 1 and item.retry_of_plan_id is None for item in history), "second broaden is not allowed")
    seen = {_axis_key(axis) for item in history for axis in item.axes}
    seen_queries = {key for item in history for axis in item.axes for key in _query_keys(axis)}
    new_keys = {_axis_key(axis) for axis in axes}
    new_queries = {key for axis in axes for key in _query_keys(axis)}
    _require(bool(axes) and not new_keys & seen and not new_queries & seen_queries, "broaden labels and source queries must be novel")
    unmet = set(unmet_required_need_ids)
    _require(bool(unmet) and not any(not set(axis.need_ids) <= unmet for axis in axes), "broaden axes must cover only unmet required needs")
    _require(len(seen | new_keys) <= prior.budgets.max_queries, "lineage exceeds max_queries unique-axis budget")
    next_axes = tuple(replace(axis, origin=AxisOrigin.RAW_TOPIC_FALLBACK) for axis in axes) if prior.degraded_reason is not None else axes
    return _seal(PlanSnapshot(
        plan_id="pending", parent_plan_id=prior.plan_id, spec_id=prior.spec_id,
        spec_hash=prior.spec_hash, plan_version=prior.plan_version + 1, axes=next_axes,
        source_selection=prior.source_selection, direct_overrides=prior.direct_overrides,
        budgets=prior.budgets, stopping_policy=prior.stopping_policy,
        degraded_reason=prior.degraded_reason, retry_of_plan_id=None,
        _factory_capability=prior._factory_capability,
    ))


def retry_plan(prior: PlanSnapshot, lineage: tuple[PlanSnapshot, ...] = ()) -> PlanSnapshot:
    history = lineage or (prior,)
    if lineage:
        validate_lineage(history)
    else:
        canonical_plan_json(prior)
    _require(history[-1].plan_id == prior.plan_id, "retry would fork the linear lineage")
    retried = prior.retry_of_plan_id is not None or any(
        item.retry_of_plan_id is not None for item in history)
    _require(not retried, "second retry is not allowed")
    return _seal(PlanSnapshot(
        plan_id="pending", parent_plan_id=prior.plan_id, spec_id=prior.spec_id,
        spec_hash=prior.spec_hash, plan_version=prior.plan_version + 1, axes=prior.axes,
        source_selection=prior.source_selection, direct_overrides=prior.direct_overrides,
        budgets=prior.budgets, stopping_policy=prior.stopping_policy,
        degraded_reason=prior.degraded_reason, retry_of_plan_id=prior.plan_id,
        _factory_capability=prior._factory_capability,
    ))


def validate_lineage(lineage: tuple[PlanSnapshot, ...]) -> None:
    _require(bool(lineage), "lineage must not be empty")
    root = lineage[0]
    _require(root.plan_version == 1 and root.parent_plan_id is None and root.retry_of_plan_id is None, "lineage root must be initial v1")
    seen_ids: set[str] = set()
    unique_axes: set[str] = set()
    unique_queries: set[tuple[str, str]] = set()
    broaden_count = 0
    retry_count = 0
    stable_root = (root.spec_id, root.spec_hash, root.source_selection, root.direct_overrides,
        root.budgets, root.stopping_policy, root.degraded_reason)
    for index, plan in enumerate(lineage):
        canonical_plan_json(plan)
        _require(plan.plan_id not in seen_ids, "lineage contains a cycle")
        seen_ids.add(plan.plan_id)
        axis_keys = {_axis_key(axis) for axis in plan.axes}
        query_keys = {key for axis in plan.axes for key in _query_keys(axis)}
        if index == 0:
            unique_axes.update(axis_keys)
            unique_queries.update(query_keys)
            continue
        prior = lineage[index - 1]
        _require(plan.parent_plan_id == prior.plan_id and plan.plan_version == prior.plan_version + 1, "lineage contains a fork or version gap")
        stable = (plan.spec_id, plan.spec_hash, plan.source_selection, plan.direct_overrides,
            plan.budgets, plan.stopping_policy, plan.degraded_reason)
        _require(stable == stable_root, "lineage controls or degraded provenance changed")
        if plan.retry_of_plan_id is None:
            _require(not axis_keys & unique_axes and not query_keys & unique_queries, "broaden labels and source queries must be novel")
            broaden_count += 1
        elif plan.retry_of_plan_id != prior.plan_id or plan.axes != prior.axes:
            raise PlanTransitionError("retry changed its executable projection")
        else:
            retry_count += 1
        unique_axes.update(axis_keys)
        unique_queries.update(query_keys)
    _require(broaden_count <= root.stopping_policy.max_broaden_steps, "second broaden is not allowed")
    _require(retry_count <= root.stopping_policy.max_retries_per_plan, "second retry is not allowed")
    _require(len(unique_axes) <= root.budgets.max_queries, "lineage exceeds max_queries unique-axis budget")


def authorize_execution(plan: PlanSnapshot, executed_plan_ids: tuple[str, ...]) -> tuple[str, ...]:
    canonical_plan_json(plan)
    if plan.plan_id in executed_plan_ids: raise DuplicateExecutionError(plan.plan_id)
    return (*executed_plan_ids, plan.plan_id)
