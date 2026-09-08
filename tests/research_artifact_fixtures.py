from __future__ import annotations

from ontologylab.research_plan import (
    NeedLinkedAxis,
    PlanBudgets,
    PlanSnapshot,
    broaden_plan,
    create_initial_plan,
)
from ontologylab.research_spec import (
    ContentClass,
    EvidenceNeedDraft,
    EvidenceNeedKind,
    InteractionPolicy,
    ResearchExecutionControls,
    ResearchOrigin,
    ResearchSpec,
    ResearchSpecDraft,
    SourceEligibilityPolicy,
    build_evidence_need,
    build_research_spec,
    research_spec_hash,
)


def research_spec() -> ResearchSpec:
    need = build_evidence_need(
        EvidenceNeedDraft(
            EvidenceNeedKind.MECHANISM,
            "rootstock disease mechanism",
            True,
            ContentClass.FULLTEXT,
        )
    )
    return build_research_spec(
        ResearchSpecDraft(
            "research-spec-v1",
            None,
            ResearchOrigin.DIRECT_API,
            "compare rootstock disease resistance",
            ("peer reviewed",),
            (need,),
            ("cultivar is known",),
            InteractionPolicy.NEVER,
            SourceEligibilityPolicy(),
        )
    )


def initial_plan(spec: ResearchSpec) -> PlanSnapshot:
    need_id = spec.evidence_needs[0].need_id
    axis = NeedLinkedAxis(
        "mechanism",
        "rootstock resistance mechanism",
        ("rootstock",),
        (need_id,),
        (),
        (("crossref", "rootstock resistance mechanism"),),
    )
    return create_initial_plan(
        spec_id=spec.spec_id,
        spec_hash=research_spec_hash(spec),
        axes=(axis,),
        source_selection=("crossref",),
        direct_overrides=ResearchExecutionControls(
            ("crossref",), 10, 2, True, False, 0, 5, "mock", None, 4, 30.0, 7
        ),
        budgets=PlanBudgets(2, 4, 30.0),
    )


def broadened_plan(root: PlanSnapshot, need_id: str) -> PlanSnapshot:
    axis = NeedLinkedAxis(
        "field evidence",
        "rootstock resistance field evidence",
        ("field",),
        (need_id,),
        (),
        (("crossref", "rootstock resistance field evidence"),),
    )
    return broaden_plan(root, (axis,), (need_id,))
