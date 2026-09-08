from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from ontologylab.connectors.base import RawDocument
from ontologylab.literature import corpus_summary
from ontologylab.literature_artifacts import write_corpus_artifacts
from ontologylab.post_extraction_assessment import post_extraction_assessment_value
from ontologylab.post_extraction_types import (
    AdvisoryRecord,
    ContradictionState,
    PostExtractionAssessment,
    SupportState,
)
from ontologylab.research_artifacts import ResearchArtifactStore
from ontologylab.research_assessment import (
    AcquisitionInput,
    acquisition_assessment_value,
    assess_acquisition,
)
from ontologylab.research_plan import (
    AxisOrigin,
    DegradedReason,
    NeedLinkedAxis,
    PlanBudgets,
    create_initial_plan,
)
from ontologylab.research_spec import (
    ContentClass,
    EvidenceNeedDraft,
    EvidenceNeedKind,
    InteractionPolicy,
    JsonObject,
    ResearchExecutionControls,
    ResearchOrigin,
    ResearchSpecDraft,
    SourceEligibilityPolicy,
    build_evidence_need,
    build_research_spec,
    research_spec_hash,
)
from ontologylab.server.app import create_app
from ontologylab.server.jobs import Job


def _research_surface(
    tmp_path: Path, *, degraded: bool, partial: bool
) -> tuple[TestClient, str, JsonObject, Path]:
    data_dir = tmp_path / ("degraded-data" if degraded else "partial-data")
    job_id = "research-surface"
    job_dir = data_dir / "jobs" / job_id
    job_dir.mkdir(parents=True)
    mechanism = build_evidence_need(
        EvidenceNeedDraft(
            EvidenceNeedKind.MECHANISM,
            "mechanism <img src=x onerror=alert(1)>",
            True,
            ContentClass.FULLTEXT,
        )
    )
    context = build_evidence_need(
        EvidenceNeedDraft(
            EvidenceNeedKind.CONTEXT,
            "context evidence",
            False,
            ContentClass.ABSTRACT,
        )
    )
    spec = build_research_spec(
        ResearchSpecDraft(
            "research-spec-v1",
            None,
            ResearchOrigin.DIRECT_API,
            "surface <script>window.pwned=true</script>",
            (),
            (mechanism, context),
            ("assume <svg onload=alert(1)>",),
            InteractionPolicy.NEVER,
            SourceEligibilityPolicy(),
        )
    )
    axis = NeedLinkedAxis(
        "context",
        "surface context",
        ("surface",),
        (context.need_id,),
        (),
        (("crossref", "surface context"),),
        (
            AxisOrigin.RAW_TOPIC_FALLBACK
            if degraded
            else AxisOrigin.PLANNED
        ),
    )
    controls = ResearchExecutionControls(
        ("crossref",), 5, 1, False, False, 0, 0, "mock", None, 2, 30.0, 9
    )
    plan = create_initial_plan(
        spec_id=spec.spec_id,
        spec_hash=research_spec_hash(spec),
        axes=(axis,),
        source_selection=controls.sources,
        direct_overrides=controls,
        budgets=PlanBudgets(1, 2, 30.0),
        degraded_reason=DegradedReason.INVALID_OUTPUT if degraded else None,
    )
    documents = (
        RawDocument(
            source_kind="paper_api",
            source_uri="https://doi.org/10.1000/surface",
            title="Surface fixture",
            raw_text="Surface fixture\n\nContext evidence.",
            doi="10.1000/surface",
            source="crossref",
            content_kind=ContentClass.FULLTEXT.value,
            search_axes=("context",),
        ),
    )
    assessment = assess_acquisition(
        AcquisitionInput(spec, plan, documents, (), 0, 0)
    )
    acquisition = acquisition_assessment_value(assessment)
    if not partial:
        acquisition["stop_reason"] = None

    records = (
        AdvisoryRecord(
            "external </div><script>alert(1)</script>",
            "node",
            "revision",
            "sha256:" + "1" * 64,
            ("citation-1",),
            ("run-1",),
            ("chunk-1",),
            SupportState.RECEIPT_LINKED,
            ContradictionState.POTENTIAL_CONFLICT,
            ("distinct_single_values",),
        ),
    )
    post = post_extraction_assessment_value(
        PostExtractionAssessment(records, "sha256:" + "2" * 64)
    )
    artifacts = ResearchArtifactStore(job_dir)
    artifacts.write_spec(spec)
    artifacts.write_plan(plan)
    artifacts.write_acquisition(plan, acquisition)
    artifacts.write_post_extraction(plan, post)
    replay = artifacts.load()
    write_corpus_artifacts(
        job_dir,
        documents,
        corpus_summary(
            raw_count=1,
            documents=list(documents),
            queries=[],
            assessment=acquisition,
        ),
    )

    bootstrap = create_app(data_dir=data_dir)
    bootstrap.state.jobs.persist(
        Job(
            job_id=job_id,
            kind="research",
            engine="mock",
            model=None,
            started_ts=1.0,
            finished_ts=2.0,
            status="complete",
            phase="extract",
            ask=spec.goal,
            research_pointers=replay.pointers(),
        )
    )
    client = TestClient(create_app(data_dir=data_dir))
    return client, job_id, acquisition, job_dir
