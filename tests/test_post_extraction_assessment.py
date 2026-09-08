from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from ontologylab.citation_ids import fact_revision_id
from tests import post_extraction_contradiction_cases as contradiction_cases
from tests.post_extraction_assessment_fixtures import (
    _api,
    _assessment,
    _fact,
    _linked_assessment,
    _linked_rows,
    _rule,
)

test_absence_and_model_opinion_are_never_contradictions = (
    contradiction_cases.test_absence_and_model_opinion_are_never_contradictions
)
test_aggregate_order_and_json_are_canonical = (
    contradiction_cases.test_aggregate_order_and_json_are_canonical
)
test_distinct_non_null_single_values_are_potential_conflicts = (
    contradiction_cases.test_distinct_non_null_single_values_are_potential_conflicts
)
test_duplicate_semantic_fields_have_order_independent_fact_hash = (
    contradiction_cases.test_duplicate_semantic_fields_have_order_independent_fact_hash
)
test_relation_target_variation_is_never_a_contradiction = (
    contradiction_cases.test_relation_target_variation_is_never_a_contradiction
)
test_rule_and_claim_keys_use_the_same_normalization = (
    contradiction_cases.test_rule_and_claim_keys_use_the_same_normalization
)
test_schema_without_explicit_single_value_is_not_assessed = (
    contradiction_cases.test_schema_without_explicit_single_value_is_not_assessed
)
test_unmappable_fact_kind_is_not_assessed = (
    contradiction_cases.test_unmappable_fact_kind_is_not_assessed
)
test_unsupported_semantic_key_is_not_a_contradiction = (
    contradiction_cases.test_unsupported_semantic_key_is_not_a_contradiction
)


def test_receipt_linked_record_is_canonical_and_immutable() -> None:
    fact = _fact()
    result = _linked_assessment(fact, rules=(_rule(),))
    record = result.records[0]

    assert record.support_state.value == "receipt_linked"
    assert record.contradiction_state.value == "not_observed"
    assert record.fact_revision == fact_revision_id("node", "fact-a")
    assert record.fact_hash.startswith("sha256:")
    assert record.citation_receipt_ids == ("citation-fact-a",)
    assert record.extraction_run_receipt_ids == ("run-fact-a",)
    assert record.extraction_chunk_receipt_ids == ("chunk-fact-a",)
    with pytest.raises(FrozenInstanceError):
        record.support_state = _api().SupportState.NOT_ASSESSED


def test_missing_citation_is_explicit_receipt_missing() -> None:
    result = _assessment((_fact(),), rules=(_rule(),))

    assert result.records[0].support_state.value == "receipt_missing"
    assert result.records[0].contradiction_state.value == "not_assessed"
    assert "citation_receipt_missing" in result.records[0].reason_codes


def test_stale_fact_revision_is_not_assessed() -> None:
    fact = _fact()
    citation, run, chunk, document = _linked_rows(fact)
    api = _api()
    stale = api.CitationRow(
        receipt_id=citation.receipt_id,
        fact_kind=citation.fact_kind,
        fact_id=citation.fact_id,
        fact_revision="sha256:stale",
        representation_id=citation.representation_id,
        representation_content_hash=citation.representation_content_hash,
        run_receipt_id=citation.run_receipt_id,
        chunk_receipt_id=citation.chunk_receipt_id,
    )

    result = _assessment(
        (fact,), citations=(stale,), runs=(run,), chunks=(chunk,),
        documents=(document,),
    )

    assert result.records[0].support_state.value == "not_assessed"
    assert "stale_fact_revision" in result.records[0].reason_codes


def test_current_citation_survives_an_ignored_stale_citation() -> None:
    fact = _fact()
    citation, run, chunk, document = _linked_rows(fact)
    api = _api()
    stale = api.CitationRow(
        "citation-stale",
        citation.fact_kind,
        citation.fact_id,
        "sha256:stale",
        citation.representation_id,
        citation.representation_content_hash,
        citation.run_receipt_id,
        citation.chunk_receipt_id,
    )

    result = _assessment(
        (fact,),
        citations=(stale, citation),
        runs=(run,),
        chunks=(chunk,),
        documents=(document,),
    )

    record = result.records[0]
    assert record.support_state.value == "receipt_linked"
    assert record.citation_receipt_ids == (citation.receipt_id,)


def test_duplicate_authoritative_receipt_ids_fail_closed() -> None:
    fact = _fact()
    citation, run, chunk, document = _linked_rows(fact)
    api = _api()
    conflicting = api.RunReceiptRow(
        run.receipt_id,
        "different-document",
        run.document_content_hash,
    )

    result = _assessment(
        (fact,),
        citations=(citation,),
        runs=(run, conflicting),
        chunks=(chunk,),
        documents=(document,),
    )

    record = result.records[0]
    assert record.support_state.value == "not_assessed"
    assert "duplicate_receipt_id" in record.reason_codes


@pytest.mark.parametrize(
    ("missing", "reason"),
    [("run", "run_receipt_missing"), ("chunk", "chunk_receipt_missing")],
)
def test_missing_extraction_binding_is_not_assessed(
    missing: str, reason: str,
) -> None:
    fact = _fact()
    citation, run, chunk, document = _linked_rows(fact)

    result = _assessment(
        (fact,),
        citations=(citation,),
        runs=() if missing == "run" else (run,),
        chunks=() if missing == "chunk" else (chunk,),
        documents=(document,),
    )

    assert result.records[0].support_state.value == "not_assessed"
    assert reason in result.records[0].reason_codes


def test_cross_representation_binding_is_not_assessed() -> None:
    fact = _fact()
    citation, run, chunk, document = _linked_rows(fact)
    api = _api()
    cross_bound = api.RunReceiptRow(
        receipt_id=run.receipt_id,
        representation_id="different-document",
        document_content_hash=run.document_content_hash,
    )

    result = _assessment(
        (fact,), citations=(citation,), runs=(cross_bound,), chunks=(chunk,),
        documents=(document,),
    )

    assert result.records[0].support_state.value == "not_assessed"
    assert "run_binding_mismatch" in result.records[0].reason_codes


def test_receipt_inventory_drift_fails_closed() -> None:
    fact = _fact()
    citation, run, chunk, document = _linked_rows(fact)

    result = _assessment(
        (fact,), citations=(citation,), runs=(run,), chunks=(chunk,),
        documents=(document,), root_after="inventory-changed",
    )

    assert result.records[0].support_state.value == "not_assessed"
    assert "receipt_inventory_drift" in result.records[0].reason_codes
