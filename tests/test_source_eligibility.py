from __future__ import annotations

import json
from pathlib import Path

import pytest

from ontologylab.connectors.base import RawDocument
from ontologylab.connectors.paper_api import SourceFailure
from ontologylab.ingestion import item_from_raw
from ontologylab.research_assessment import (
    AcquisitionRecommendation,
    AcquisitionStopReason,
    canonical_acquisition_assessment,
    classify_document_content,
    is_document_eligible,
)
from ontologylab.research_spec import (
    ContentClass,
    EvidenceNeedDraft,
    EvidenceNeedKind,
    SourceEligibilityPolicy,
    build_evidence_need,
)
from tests.research_contract_fixtures import load_fixture
from tests.test_acquisition_assessment import (
    _assessment,
    _axis,
    _need,
    _plan,
    _spec,
)
from tests.test_acquisition_assessment import _document as _assessed_document

_ELIGIBILITY_FIXTURE = (
    Path(__file__).parent / "fixtures/research/source-eligibility.jsonl"
)


def _document(
    content_kind: str,
    *,
    retracted: bool = False,
    source_kind: str = "paper_api",
    title: str | None = "Boundary paper",
    text: str = "Boundary paper\n\nAn abstract.",
) -> RawDocument:
    return RawDocument(
        source_kind=source_kind,
        source_uri="https://doi.org/10.1000/boundary",
        title=title,
        raw_text=text,
        doi="10.1000/boundary",
        source="crossref",
        content_kind=content_kind,
        retracted=retracted,
    )


def test_every_source_eligibility_fixture_boundary_matches() -> None:
    rows = load_fixture(_ELIGIBILITY_FIXTURE)
    policy = SourceEligibilityPolicy()

    observed: list[bool] = []
    for row in rows:
        raw_kind = row["need_kind"]
        raw_content = row["content_kind"]
        retracted = row["retracted"]
        expected = row["expected_eligible"]
        assert isinstance(raw_kind, str)
        assert isinstance(raw_content, str)
        assert isinstance(retracted, bool)
        assert isinstance(expected, bool)
        kind = EvidenceNeedKind(raw_kind)
        need = build_evidence_need(
            EvidenceNeedDraft(kind, f"fixture {kind.value}", True, None)
        )
        actual = is_document_eligible(
            need,
            _document(raw_content, retracted=retracted),
            policy,
        )
        observed.append(actual)
        assert actual is expected, row["id"]

    assert len(observed) == 18


@pytest.mark.parametrize(
    ("document", "expected"),
    [
        (_document("", text="Boundary paper"), ContentClass.METADATA_ONLY),
        (_document("", text="  Boundary paper  \n\n  "), ContentClass.METADATA_ONLY),
        (
            _document("", text="Boundary paper\n\nAn abstract remains."),
            ContentClass.ABSTRACT,
        ),
        (
            _document("", title=None, text="An untitled abstract."),
            ContentClass.ABSTRACT,
        ),
        (
            _document("", source_kind="upload", text="Uploaded prose"),
            ContentClass.FULLTEXT,
        ),
        (_document("", source_kind="upload", text=""), ContentClass.METADATA_ONLY),
        (_document("not-a-content-class"), ContentClass.UNKNOWN),
        (_document("unknown"), ContentClass.UNKNOWN),
        (_document("fulltext", text="Boundary paper"), ContentClass.FULLTEXT),
    ],
)
def test_blank_and_malformed_content_boundaries_are_classified_conservatively(
    document: RawDocument,
    expected: ContentClass,
) -> None:
    assert classify_document_content(document) is expected


def test_ingestion_uses_the_same_paper_and_non_paper_boundary() -> None:
    title_only = item_from_raw(
        _document("", text="Boundary paper"),
        operation_id="title-only",
    )
    abstract = item_from_raw(
        _document("", text="Boundary paper\n\nActual abstract."),
        operation_id="abstract",
    )
    upload = item_from_raw(
        _document("", source_kind="upload", text="Uploaded prose"),
        operation_id="upload",
    )

    assert title_only.content_kind == "metadata_only"
    assert abstract.content_kind == "abstract"
    assert upload.content_kind == "fulltext"


def test_source_failures_without_documents_are_explicitly_degraded() -> None:
    mechanism = _need(EvidenceNeedKind.MECHANISM, "mechanism evidence")
    spec = _spec((mechanism,))
    plan = _plan(spec, (_axis("mechanism", mechanism),))
    secret = "https://source.invalid/?api_key=do-not-copy"

    assessment = _assessment(
        spec,
        plan,
        (),
        failures=(SourceFailure("crossref", secret, "fetch_failed"),),
    )
    payload = json.loads(canonical_acquisition_assessment(assessment))

    assert assessment.degraded is True
    assert assessment.source_failures[0].source == "crossref"
    assert assessment.source_failures[0].kind == "fetch_failed"
    assert assessment.recommendation is AcquisitionRecommendation.STOP
    assert assessment.stop_reason is AcquisitionStopReason.NO_USABLE_SOURCE
    assert secret not in json.dumps(payload)


def test_conflict_indicators_are_retraction_only_not_semantic_judgment() -> None:
    mechanism = _need(EvidenceNeedKind.MECHANISM, "mechanism evidence")
    spec = _spec((mechanism,))
    plan = _plan(spec, (_axis("mechanism", mechanism),))
    documents = (
        _assessed_document("active", ContentClass.FULLTEXT, "mechanism"),
        _assessed_document(
            "retracted",
            ContentClass.FULLTEXT,
            "mechanism",
            retracted=True,
        ),
        RawDocument(
            source_kind="paper_api",
            source_uri="https://doi.org/10.1000/opposite",
            title="Opposite result",
            raw_text="Opposite result\n\nThe intervention had the opposite result.",
            doi="10.1000/opposite",
            source="pubmed",
            content_kind="fulltext",
            retracted=False,
            search_axes=("mechanism",),
        ),
    )

    assessment = _assessment(spec, plan, documents)

    assert [item.indicator for item in assessment.potential_conflict_indicators] == [
        "retracted_record"
    ]
    assert assessment.potential_conflict_indicators[0].document_id == (
        "doi:10.1000/retracted"
    )


def test_assessment_identity_is_content_addressed_without_completeness_scalar() -> None:
    mechanism = _need(EvidenceNeedKind.MECHANISM, "mechanism evidence")
    spec = _spec((mechanism,))
    plan = _plan(spec, (_axis("mechanism", mechanism),))
    document = _assessed_document(
        "identity",
        ContentClass.FULLTEXT,
        "mechanism",
    )

    first = _assessment(spec, plan, (document,))
    second = _assessment(spec, plan, (document,))
    changed = _assessment(
        spec,
        plan,
        (document,),
        failures=(SourceFailure("pubmed", "down", "fetch_failed"),),
    )
    payload = canonical_acquisition_assessment(first)

    assert first.assessment_event_id == second.assessment_event_id
    assert first.assessment_event_id != changed.assessment_event_id
    assert payload == canonical_acquisition_assessment(second)
    assert first.assessment_event_id.startswith("sha256:")
    forbidden = (b"complete", b"sufficient", b"disproven", b"score")
    assert all(term not in payload for term in forbidden)
