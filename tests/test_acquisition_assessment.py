from __future__ import annotations

from pathlib import Path

import pytest

from ontologylab.connectors.base import RawDocument
from ontologylab.connectors.paper_api import SourceFailure
from ontologylab.research_assessment import (
    AcquisitionInput,
    AcquisitionRecommendation,
    AcquisitionStopReason,
    assess_acquisition,
)
from ontologylab.research_plan import (
    NeedLinkedAxis,
    PlanBudgets,
    PlanSnapshot,
    create_initial_plan,
)
from ontologylab.research_spec import (
    ContentClass,
    EvidenceNeed,
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
from tests.research_contract_fixtures import load_fixture

_OMISSION_FIXTURE = Path(__file__).parent / "fixtures/research/controlled-omission.jsonl"


def _need(
    kind: EvidenceNeedKind,
    description: str,
    *,
    mandatory: bool = True,
) -> EvidenceNeed:
    return build_evidence_need(
        EvidenceNeedDraft(kind, description, mandatory, None)
    )


def _spec(needs: tuple[EvidenceNeed, ...]) -> ResearchSpec:
    return build_research_spec(
        ResearchSpecDraft(
            schema_version="research-spec-v1",
            parent_spec_id=None,
            origin=ResearchOrigin.DIRECT_API,
            goal="controlled acquisition fixture",
            explicit_constraints=(),
            evidence_needs=needs,
            assumptions=(),
            interaction_policy=InteractionPolicy.NEVER,
            source_eligibility_policy=SourceEligibilityPolicy(),
        )
    )


def _axis(name: str, need: EvidenceNeed) -> NeedLinkedAxis:
    return NeedLinkedAxis(
        axis=name,
        query=f"fixture {name}",
        terms=(name,),
        need_ids=(need.need_id,),
        dependencies=(),
        source_queries=(("crossref", f"fixture {name}"),),
    )


def _plan(
    spec: ResearchSpec,
    axes: tuple[NeedLinkedAxis, ...],
) -> PlanSnapshot:
    controls = ResearchExecutionControls(
        sources=("crossref",),
        limit=5,
        max_queries=max(1, len(axes) + 1),
        fulltext=True,
        citation_expansion=False,
        citation_seed_count=0,
        citation_limit=0,
        engine="mock",
        model=None,
        max_engine_calls=3,
        time_budget=30.0,
        seed=7,
    )
    return create_initial_plan(
        spec_id=spec.spec_id,
        spec_hash=research_spec_hash(spec),
        axes=axes,
        source_selection=controls.sources,
        direct_overrides=controls,
        budgets=PlanBudgets(controls.max_queries, 3, 30.0),
    )


def _document(
    suffix: str,
    content_kind: ContentClass,
    axis: str,
    *,
    retracted: bool = False,
    sources: tuple[str, ...] = ("crossref",),
) -> RawDocument:
    return RawDocument(
        source_kind="paper_api",
        source_uri=f"https://doi.org/10.1000/{suffix}",
        title=f"Fixture {suffix}",
        raw_text=f"Fixture {suffix}\n\nObserved material for {axis}.",
        doi=f"10.1000/{suffix}",
        source=sources[0],
        content_kind=content_kind.value,
        retracted=retracted,
        year=2025,
        venue=f"Venue {suffix}",
        all_sources=sources,
        search_axes=(axis,),
    )


def _assessment(
    spec: ResearchSpec,
    plan: PlanSnapshot,
    documents: tuple[RawDocument, ...],
    *,
    failures: tuple[SourceFailure, ...] = (),
    remaining_axis_slots: int = 0,
    remaining_broaden_slots: int = 0,
):
    return assess_acquisition(
        AcquisitionInput(
            spec=spec,
            plan=plan,
            documents=documents,
            source_failures=failures,
            remaining_unique_axis_slots=remaining_axis_slots,
            remaining_broaden_slots=remaining_broaden_slots,
        )
    )


def test_all_24_controlled_omissions_follow_the_binding_decision_table() -> None:
    rows = load_fixture(_OMISSION_FIXTURE)

    observed: list[tuple[str, str | None]] = []
    for row in rows:
        raw_kind = row["mandatory_need_kind"]
        corpus_state = row["corpus_state"]
        broaden_available = row["broaden_available"]
        remaining_axis = row["remaining_axis"]
        expected_recommendation = row["expected_recommendation"]
        expected_stop_reason = row["expected_stop_reason"]
        assert isinstance(raw_kind, str)
        assert isinstance(corpus_state, str)
        assert isinstance(broaden_available, bool)
        assert isinstance(remaining_axis, bool)
        assert isinstance(expected_recommendation, str)
        assert expected_stop_reason is None or isinstance(expected_stop_reason, str)
        mandatory = _need(EvidenceNeedKind(raw_kind), f"required {raw_kind}")
        optional = _need(
            EvidenceNeedKind.CONTEXT,
            f"adjacent context for {raw_kind}",
            mandatory=False,
        )
        spec = _spec((mandatory, optional))
        plan = _plan(spec, (_axis("target", mandatory), _axis("adjacent", optional)))
        if corpus_state == "covered_fulltext":
            documents = (_document("covered", ContentClass.FULLTEXT, "target"),)
        elif corpus_state == "partial_fulltext":
            documents = (_document("partial", ContentClass.FULLTEXT, "adjacent"),)
        elif corpus_state == "metadata_only":
            documents = (_document("metadata", ContentClass.METADATA_ONLY, "target"),)
        else:
            pytest.fail(f"unexpected controlled fixture state: {corpus_state}")
        assessment = _assessment(
            spec,
            plan,
            documents,
            remaining_axis_slots=int(remaining_axis),
            remaining_broaden_slots=int(broaden_available),
        )
        actual = (
            assessment.recommendation.value,
            assessment.stop_reason.value if assessment.stop_reason else None,
        )
        observed.append(actual)
        assert actual == (expected_recommendation, expected_stop_reason), row["id"]

    assert len(observed) == 24


def test_complementary_fulltext_occupies_each_mandatory_need() -> None:
    mechanism = _need(EvidenceNeedKind.MECHANISM, "mechanism evidence")
    method = _need(EvidenceNeedKind.METHOD, "method evidence")
    spec = _spec((mechanism, method))
    plan = _plan(spec, (_axis("mechanism", mechanism), _axis("method", method)))
    documents = (
        _document(
            "mechanism",
            ContentClass.FULLTEXT,
            "mechanism",
            sources=("crossref", "pubmed"),
        ),
        _document("method", ContentClass.FULLTEXT, "method", sources=("openalex",)),
    )

    assessment = _assessment(spec, plan, documents)

    assert assessment.recommendation is AcquisitionRecommendation.EXTRACT
    assert assessment.stop_reason is None
    assert [item.occupied for item in assessment.need_occupancy] == [True, True]
    assert [
        item.eligible_documents[0].document_id
        for item in assessment.need_occupancy
    ] == ["doi:10.1000/mechanism", "doi:10.1000/method"]
    assert all(
        item.eligible_documents[0].content_class is ContentClass.FULLTEXT
        for item in assessment.need_occupancy
    )
    dimensions = assessment.overlap_and_diversity
    assert dimensions.document_count == 2
    assert dimensions.distinct_source_count == 3
    assert dimensions.documents_with_multiple_sources == 1
    assert dimensions.redundant_source_observation_count == 1
    assert dimensions.distinct_search_axis_count == 2
    assert dimensions.marginal_unique_eligible_document_count == 2


def test_metadata_mechanism_is_unoccupied_and_partial_fulltext_exhausts_budget() -> None:
    mechanism = _need(EvidenceNeedKind.MECHANISM, "mechanism evidence")
    context = _need(EvidenceNeedKind.CONTEXT, "context evidence", mandatory=False)
    spec = _spec((mechanism, context))
    plan = _plan(spec, (_axis("mechanism", mechanism), _axis("context", context)))

    metadata = _assessment(
        spec,
        plan,
        (_document("metadata-mechanism", ContentClass.METADATA_ONLY, "mechanism"),),
    )
    partial = _assessment(
        spec,
        plan,
        (_document("partial-context", ContentClass.FULLTEXT, "context"),),
    )

    assert metadata.need_occupancy[0].occupied is False
    assert metadata.recommendation is AcquisitionRecommendation.STOP
    assert metadata.stop_reason is AcquisitionStopReason.NO_USABLE_SOURCE
    assert partial.need_occupancy[0].occupied is False
    assert partial.recommendation is AcquisitionRecommendation.EXTRACT
    assert partial.stop_reason is AcquisitionStopReason.BUDGET_EXHAUSTED


def test_optional_unmet_need_never_forces_broaden() -> None:
    mechanism = _need(EvidenceNeedKind.MECHANISM, "mandatory mechanism")
    safety = _need(EvidenceNeedKind.SAFETY, "optional safety", mandatory=False)
    spec = _spec((mechanism, safety))
    plan = _plan(spec, (_axis("mechanism", mechanism), _axis("safety", safety)))

    assessment = _assessment(
        spec,
        plan,
        (_document("mechanism-only", ContentClass.FULLTEXT, "mechanism"),),
        remaining_axis_slots=1,
        remaining_broaden_slots=1,
    )

    assert assessment.recommendation is AcquisitionRecommendation.EXTRACT
    assert assessment.stop_reason is None
    assert assessment.need_occupancy[1].occupied is False
