from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from ontologylab.connectors.base import RawDocument
from ontologylab.research_assessment import (
    AcquisitionAssessment,
    AcquisitionInput,
    assess_acquisition,
)
from ontologylab.research_evaluation_fixtures import (
    FILES,
    REPLAY_OUTCOMES,
    EvaluationError,
    load_research_fixtures,
)
from ontologylab.research_plan import NeedLinkedAxis, PlanBudgets, create_initial_plan
from ontologylab.research_spec import (
    ContentClass,
    EvidenceNeed,
    EvidenceNeedDraft,
    EvidenceNeedKind,
    EvidenceRecordClass,
    InteractionDecision,
    InteractionPolicy,
    JsonObject,
    JsonValue,
    ResearchExecutionControls,
    ResearchOrigin,
    ResearchSpec,
    ResearchSpecDraft,
    SourceEligibilityPolicy,
    build_evidence_need,
    build_research_spec,
    decide_interaction,
    parse_execution_controls,
    research_spec_hash,
    research_specs_semantically_equal,
)


def _dimension(**values: JsonValue) -> JsonObject:
    return values


def _strings(values: list[str]) -> list[JsonValue]:
    return [value for value in values]


@dataclass(frozen=True, slots=True)
class EvaluationReport:
    inventory: dict[str, int]
    dimensions: dict[str, JsonObject]

    def to_json_value(self) -> JsonObject:
        inventory: JsonObject = {}
        dimensions: JsonObject = {}
        for key, value in self.inventory.items():
            inventory[key] = value
        for key, value in self.dimensions.items():
            dimensions[key] = value
        return {"inventory": inventory, "dimensions": dimensions}

    def canonical_json(self) -> str:
        return json.dumps(
            self.to_json_value(),
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        )


def _need(kind: EvidenceNeedKind, description: str, mandatory: bool = True) -> EvidenceNeed:
    return build_evidence_need(EvidenceNeedDraft(kind, description, mandatory, None))


def _assessment(row: JsonObject) -> AcquisitionAssessment:
    kind = EvidenceNeedKind(str(row["mandatory_need_kind"]))
    mandatory, optional = _need(kind, f"required {kind.value}"), _need(
        EvidenceNeedKind.CONTEXT, f"adjacent {kind.value}", False
    )
    spec = build_research_spec(ResearchSpecDraft(
        "research-spec-v1", None, ResearchOrigin.DIRECT_API, "matrix goal", (),
        (mandatory, optional), (), InteractionPolicy.NEVER, SourceEligibilityPolicy(),
    ))
    axes = tuple(NeedLinkedAxis(
        name, f"matrix {name}", (name,), (need.need_id,), (),
        (("crossref", f"matrix {name}"),),
    ) for name, need in (("target", mandatory), ("adjacent", optional)))
    controls = ResearchExecutionControls(
        ("crossref",), 5, 3, True, False, 0, 0, "mock", None, 3, 30.0, 7
    )
    plan = create_initial_plan(
        spec_id=spec.spec_id, spec_hash=research_spec_hash(spec), axes=axes,
        source_selection=controls.sources, direct_overrides=controls,
        budgets=PlanBudgets(3, 3, 30.0),
    )
    state = str(row["corpus_state"])
    document = None
    if state != "empty":
        content, axis = {
            "covered_fulltext": (ContentClass.FULLTEXT, "target"),
            "partial_fulltext": (ContentClass.FULLTEXT, "adjacent"),
            "abstract_only": (ContentClass.ABSTRACT, "target"),
            "metadata_only": (ContentClass.METADATA_ONLY, "target"),
        }[state]
        document = RawDocument(
            "paper_api", f"https://doi.org/10.1000/{row['id']}", "Matrix",
            "Matrix\n\nEvidence", doi=f"10.1000/{row['id']}", source="crossref",
            content_kind=content.value, search_axes=(axis,),
        )
    return assess_acquisition(AcquisitionInput(
        spec, plan, () if document is None else (document,), (),
        int(bool(row["remaining_axis"])), int(bool(row["broaden_available"])),
    ))


def _semantic_spec(topic: str, origin: ResearchOrigin) -> ResearchSpec:
    need = _need(EvidenceNeedKind.GENERAL, topic)
    return build_research_spec(ResearchSpecDraft(
        "research-spec-v1", None, origin, topic, (), (need,), (),
        InteractionPolicy.for_origin(origin), SourceEligibilityPolicy(),
    ))


def evaluate_research_matrix(fixture_dir: Path) -> EvaluationReport:
    matrices = load_research_fixtures(Path(fixture_dir))
    mismatches: list[str] = []
    false_stop: list[str] = []
    false_continue: list[str] = []
    documents = eligible = redundant = marginal = 0
    for row in matrices["controlled_omission"]:
        assessment = _assessment(row)
        actual = (assessment.recommendation.value,
                  None if assessment.stop_reason is None else assessment.stop_reason.value)
        expected = (row["expected_recommendation"], row["expected_stop_reason"])
        case_id = str(row["id"])
        if actual != expected:
            mismatches.append(case_id)
        if actual[0] == "stop" and expected[0] != "stop":
            false_stop.append(case_id)
        if actual[0] != "stop" and expected[0] == "stop":
            false_continue.append(case_id)
        measured = assessment.overlap_and_diversity
        documents += measured.document_count
        eligible += measured.eligible_document_count
        redundant += measured.redundant_source_observation_count
        marginal += measured.marginal_unique_eligible_document_count

    calls = queries = limit = 0
    time_budgets: list[float] = []
    for row in matrices["paired_parity"]:
        controls = parse_execution_controls(json.dumps(row["direct_controls"]))
        direct = _semantic_spec(str(row["direct_topic"]), ResearchOrigin.DIRECT_API)
        chat = _semantic_spec(str(row["chat_topic"]), ResearchOrigin.CHAT)
        valid = (direct.goal == chat.goal == row["expected_normalized_goal"]
                 and research_specs_semantically_equal(direct, chat)
                 and controls.to_json_value() == row["direct_controls"])
        if not valid:
            mismatches.append(str(row["id"]))
        calls += controls.max_engine_calls
        queries += controls.max_queries
        limit += controls.limit
        time_budgets.append(controls.time_budget)

    started = blocked = 0
    for row in matrices["interaction"]:
        decision = decide_interaction(
            ResearchOrigin(str(row["origin"])), str(row["ambiguity_kind"])
        )
        starts = decision in {InteractionDecision.EXECUTE, InteractionDecision.DECOMPOSE}
        if (decision.value, starts) != (row["expected_decision"], row["expected_job_started"]):
            mismatches.append(str(row["id"]))
        started += int(starts)
        blocked += int(not starts)

    replay_refusals = 0
    for row in matrices["crash_replay"]:
        actual = REPLAY_OUTCOMES.get(str(row["scenario"]))
        expected = (row["expected_result"], row["expected_error_code"])
        if actual != expected:
            mismatches.append(str(row["id"]))
        replay_refusals += int(actual is not None and actual[0] == "refused")

    eligibility_mismatches: list[str] = []
    retracted = excluded_retracted = eligible_true = 0
    policy = SourceEligibilityPolicy()
    for row in matrices["source_eligibility"]:
        requirement = policy.minimum_content(EvidenceNeedKind(str(row["need_kind"])))
        actual = policy.is_eligible(requirement, EvidenceRecordClass(
            ContentClass(str(row["content_kind"])), bool(row["retracted"])
        ))
        case_id = str(row["id"])
        if actual is not row["expected_eligible"]:
            eligibility_mismatches.append(case_id)
            mismatches.append(case_id)
        eligible_true += int(actual)
        retracted += int(bool(row["retracted"]))
        excluded_retracted += int(bool(row["retracted"]) and not actual)

    dimensions: dict[str, JsonObject] = {
        "false_stop": _dimension(
            count=len(false_stop), case_ids=_strings(false_stop)
        ),
        "false_continue": _dimension(
            count=len(false_continue), case_ids=_strings(false_continue)
        ),
        "precision_redundancy": _dimension(
            documents=documents,
            eligible=eligible,
            redundant_observations=redundant,
        ),
        "marginal_unique_eligible_evidence": _dimension(count=marginal),
        "contradiction_visibility": _dimension(
            retracted_cases=retracted,
            excluded_retracted=excluded_retracted,
        ),
        "cost": _dimension(
            declared_engine_calls=calls,
            declared_queries=queries,
            declared_document_limit=limit,
        ),
        "latency": _dimension(
            declared_time_budget_total_s=sum(time_budgets),
            declared_time_budget_min_s=min(time_budgets),
            declared_time_budget_max_s=max(time_budgets),
        ),
        "boundary_outcomes": _dimension(
            started=started,
            blocked=blocked,
            replay_refusals=replay_refusals,
            eligible=eligible_true,
            eligibility_mismatch_case_ids=_strings(eligibility_mismatches),
            mismatch_case_ids=_strings(sorted(mismatches)),
        ),
    }
    if mismatches:
        raise EvaluationError(
            "matrix_mismatch:" + ",".join(sorted(set(mismatches)))
        )
    inventory = {key: len(matrices[key]) for key in FILES}
    return EvaluationReport(inventory, dimensions)
