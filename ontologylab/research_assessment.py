from __future__ import annotations

import hashlib
import json
import unicodedata
from collections.abc import Sequence
from dataclasses import asdict, dataclass, replace
from enum import StrEnum, unique
from typing import Final, Literal

from ontologylab import research_plan, research_spec
from ontologylab.connectors.base import RawDocument, normalize_doi
from ontologylab.connectors.paper_api import SourceFailure

ASSESSMENT_SCHEMA_VERSION: Final = "acquisition-assessment-v1"


@unique
class AcquisitionRecommendation(StrEnum):
    EXTRACT = "extract"
    BROADEN = "broaden"
    STOP = "stop"


@unique
class AcquisitionStopReason(StrEnum):
    NO_USABLE_SOURCE = "no_usable_source"
    BUDGET_EXHAUSTED = "budget_exhausted"


class AssessmentInputError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class EligibleDocument:
    document_id: str
    content_class: research_spec.ContentClass


@dataclass(frozen=True, slots=True)
class NeedOccupancy:
    need_id: str
    kind: research_spec.EvidenceNeedKind
    mandatory: bool
    minimum_content: research_spec.ContentClass
    occupied: bool
    eligible_documents: tuple[EligibleDocument, ...]


@dataclass(frozen=True, slots=True)
class SourceFailureSummary:
    source: str
    kind: str


@dataclass(frozen=True, slots=True)
class AccessClassCounts:
    unknown: int
    metadata_only: int
    abstract: int
    fulltext: int


@dataclass(frozen=True, slots=True)
class OverlapAndDiversity:
    document_count: int
    eligible_document_count: int
    fulltext_candidate_count: int
    distinct_source_count: int
    documents_with_multiple_sources: int
    redundant_source_observation_count: int
    distinct_search_axis_count: int
    marginal_unique_eligible_document_count: int


@dataclass(frozen=True, slots=True)
class PotentialConflictIndicator:
    indicator: Literal["retracted_record"]
    document_id: str


@dataclass(frozen=True, slots=True)
class AcquisitionInput:
    spec: research_spec.ResearchSpec
    plan: research_plan.PlanSnapshot
    documents: tuple[RawDocument, ...]
    source_failures: tuple[SourceFailure, ...]
    remaining_unique_axis_slots: int
    remaining_broaden_slots: int
    prior_lineage: tuple[research_plan.PlanSnapshot, ...] = ()


@dataclass(frozen=True, slots=True)
class AcquisitionAssessment:
    schema_version: str
    assessment_event_id: str
    spec_id: str
    plan_id: str
    recommendation: AcquisitionRecommendation
    stop_reason: AcquisitionStopReason | None
    need_occupancy: tuple[NeedOccupancy, ...]
    source_failures: tuple[SourceFailureSummary, ...]
    degraded: bool
    access_class_counts: AccessClassCounts
    overlap_and_diversity: OverlapAndDiversity
    potential_conflict_indicators: tuple[PotentialConflictIndicator, ...]


def classify_document_content(document: RawDocument) -> research_spec.ContentClass:
    if document.content_kind:
        try:
            return research_spec.ContentClass(document.content_kind)
        except ValueError:
            return research_spec.ContentClass.UNKNOWN
    text = " ".join(document.raw_text.split())
    if document.source_kind != "paper_api":
        return (
            research_spec.ContentClass.FULLTEXT
            if text
            else research_spec.ContentClass.METADATA_ONLY
        )
    if not text:
        return research_spec.ContentClass.METADATA_ONLY
    title = " ".join((document.title or "").split())
    if title and text.casefold() == title.casefold():
        return research_spec.ContentClass.METADATA_ONLY
    return research_spec.ContentClass.ABSTRACT


def document_identity(document: RawDocument) -> str:
    doi = normalize_doi(document.doi)
    return f"doi:{doi}" if doi else f"uri:{document.source_uri}"


def is_document_eligible(
    need: research_spec.EvidenceNeed,
    document: RawDocument,
    policy: research_spec.SourceEligibilityPolicy,
) -> bool:
    record = research_spec.EvidenceRecordClass(
        classify_document_content(document),
        document.retracted is True,
    )
    return policy.is_eligible(need.minimum_content, record)


def summarize_source_failures(
    failures: Sequence[SourceFailure],
) -> tuple[bool, tuple[SourceFailureSummary, ...]]:
    summaries = tuple(sorted(
        {SourceFailureSummary(item.source, item.kind) for item in failures},
        key=lambda item: (item.source, item.kind),
    ))
    return bool(summaries), summaries


def count_access_classes(documents: Sequence[RawDocument]) -> AccessClassCounts:
    counts = {content: 0 for content in research_spec.ContentClass}
    for document in documents:
        counts[classify_document_content(document)] += 1
    return AccessClassCounts(
        counts[research_spec.ContentClass.UNKNOWN],
        counts[research_spec.ContentClass.METADATA_ONLY],
        counts[research_spec.ContentClass.ABSTRACT],
        counts[research_spec.ContentClass.FULLTEXT],
    )


def _document_axes(document: RawDocument) -> frozenset[str]:
    values = document.search_axes or (
        (document.search_axis,) if document.search_axis else ()
    )
    return frozenset(values)


def _dimensions(
    documents: tuple[RawDocument, ...],
    occupancy: tuple[NeedOccupancy, ...],
) -> OverlapAndDiversity:
    source_sets = [
        frozenset(document.all_sources or ((document.source,) if document.source else ()))
        for document in documents
    ]
    axes = [_document_axes(document) for document in documents]
    eligible_ids = {
        item.document_id
        for need in occupancy
        for item in need.eligible_documents
    }
    fulltext_ids = {
        item.document_id
        for need in occupancy
        for item in need.eligible_documents
        if item.content_class is research_spec.ContentClass.FULLTEXT
    }
    sole_ids = {
        need.eligible_documents[0].document_id
        for need in occupancy
        if len(need.eligible_documents) == 1
    }
    observations = sum(len(values) for values in source_sets)
    return OverlapAndDiversity(
        document_count=len(documents),
        eligible_document_count=len(eligible_ids),
        fulltext_candidate_count=len(fulltext_ids),
        distinct_source_count=len(set().union(*source_sets)) if source_sets else 0,
        documents_with_multiple_sources=sum(len(values) > 1 for values in source_sets),
        redundant_source_observation_count=max(0, observations - len(documents)),
        distinct_search_axis_count=len(set().union(*axes)) if axes else 0,
        marginal_unique_eligible_document_count=len(sole_ids),
    )


def assess_acquisition(inputs: AcquisitionInput) -> AcquisitionAssessment:
    if inputs.plan.spec_id != inputs.spec.spec_id:
        raise AssessmentInputError("plan and spec IDs do not match")
    if inputs.plan.spec_hash != research_spec.research_spec_hash(inputs.spec):
        raise AssessmentInputError("plan and spec hashes do not match")
    if inputs.remaining_unique_axis_slots < 0 or inputs.remaining_broaden_slots < 0:
        raise AssessmentInputError("remaining slots must be non-negative")
    plans = (*inputs.prior_lineage, inputs.plan)
    research_plan.validate_lineage(plans)
    documents = tuple(sorted(inputs.documents, key=document_identity))
    occupancy: list[NeedOccupancy] = []
    for need in inputs.spec.evidence_needs:
        need_axes = {axis.axis for plan in plans for axis in plan.axes if need.need_id in axis.need_ids}
        eligible = tuple(
            EligibleDocument(document_identity(document), classify_document_content(document))
            for document in documents
            if need_axes & _document_axes(document)
            and is_document_eligible(need, document, inputs.spec.source_eligibility_policy)
        )
        occupancy.append(NeedOccupancy(
            need.need_id, need.kind, need.mandatory, need.minimum_content,
            bool(eligible), eligible,
        ))
    occupied = tuple(occupancy)
    missing_mandatory = any(item.mandatory and not item.occupied for item in occupied)
    dimensions = _dimensions(documents, occupied)
    if not missing_mandatory and dimensions.fulltext_candidate_count:
        recommendation = AcquisitionRecommendation.EXTRACT
        stop_reason = None
    elif (
        missing_mandatory
        and inputs.remaining_unique_axis_slots > 0
        and inputs.remaining_broaden_slots > 0
    ):
        recommendation = AcquisitionRecommendation.BROADEN
        stop_reason = None
    elif dimensions.fulltext_candidate_count:
        recommendation = AcquisitionRecommendation.EXTRACT
        stop_reason = AcquisitionStopReason.BUDGET_EXHAUSTED
    else:
        recommendation = AcquisitionRecommendation.STOP
        stop_reason = AcquisitionStopReason.NO_USABLE_SOURCE
    degraded, failures = summarize_source_failures(inputs.source_failures)
    indicators = tuple(
        PotentialConflictIndicator(
            "retracted_record", document_identity(document)
        )
        for document in documents
        if document.retracted is True
    )
    draft = AcquisitionAssessment(
        ASSESSMENT_SCHEMA_VERSION, "", inputs.spec.spec_id, inputs.plan.plan_id,
        recommendation, stop_reason, occupied, failures, degraded,
        count_access_classes(documents), dimensions, indicators,
    )
    return replace(draft, assessment_event_id=_assessment_id(draft))


def acquisition_assessment_value(
    assessment: AcquisitionAssessment, *, include_id: bool = True,
) -> research_spec.JsonObject:
    payload = asdict(assessment)
    if not include_id:
        del payload["assessment_event_id"]
    return payload


def _canonical(payload: research_spec.JsonObject) -> bytes:
    text = json.dumps(
        payload, ensure_ascii=False, allow_nan=False, sort_keys=True,
        separators=(",", ":"),
    )
    return unicodedata.normalize("NFC", text).encode()


def _assessment_id(assessment: AcquisitionAssessment) -> str:
    return "sha256:" + hashlib.sha256(
        _canonical(acquisition_assessment_value(assessment, include_id=False))
    ).hexdigest()


def canonical_acquisition_assessment(assessment: AcquisitionAssessment) -> bytes:
    if assessment.assessment_event_id != _assessment_id(assessment):
        raise AssessmentInputError("assessment event ID does not match content")
    return _canonical(acquisition_assessment_value(assessment))
