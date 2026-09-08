from __future__ import annotations

import pytest

from tests.post_extraction_assessment_fixtures import (
    _api,
    _assessment,
    _fact,
    _linked_assessment,
    _rule,
)


def test_unmappable_fact_kind_is_not_assessed() -> None:
    fact = _fact(fact_kind="annotation")
    result = _linked_assessment(fact)

    assert result.records[0].support_state.value == "not_assessed"
    assert result.records[0].contradiction_state.value == "not_assessed"
    assert "unmappable_fact_kind" in result.records[0].reason_codes


def test_unsupported_semantic_key_is_not_a_contradiction() -> None:
    fact = _fact(field_key="undeclared")
    result = _linked_assessment(fact, rules=(_rule(),))

    assert result.records[0].support_state.value == "receipt_linked"
    assert result.records[0].contradiction_state.value == "not_assessed"
    assert "unsupported_semantic_key" in result.records[0].reason_codes


def test_schema_without_explicit_single_value_is_not_assessed() -> None:
    fact = _fact()
    result = _linked_assessment(fact)

    assert result.records[0].contradiction_state.value == "not_assessed"
    assert "single_value_schema_missing" in result.records[0].reason_codes


def test_distinct_non_null_single_values_are_potential_conflicts() -> None:
    left = _fact("fact-a", value="10")
    right = _fact("fact-b", value="20")
    result = _linked_assessment(left, right, rules=(_rule(),))

    assert {row.contradiction_state.value for row in result.records} == {
        "potential_conflict",
    }
    assert all("distinct_single_values" in row.reason_codes for row in result.records)


def test_rule_and_claim_keys_use_the_same_normalization() -> None:
    left = _fact("fact-a", value="10", type_name="Measurement")
    right = _fact("fact-b", value="20", type_name=" measurement ")
    result = _linked_assessment(left, right, rules=(_rule(),))

    assert {row.contradiction_state.value for row in result.records} == {
        "potential_conflict",
    }


def test_relation_target_variation_is_never_a_contradiction() -> None:
    left = _fact(
        "edge-a", fact_kind="edge", subject_key="assay",
        target_key="target-a", field_key="unit", value="mg",
        location="qualifier",
    )
    right = _fact(
        "edge-b", fact_kind="edge", subject_key="assay",
        target_key="target-b", field_key="unit", value="kg",
        location="qualifier",
    )
    result = _linked_assessment(
        left, right,
        rules=(_rule(fact_kind="edge", location="qualifier", key="unit"),),
    )

    assert {row.contradiction_state.value for row in result.records} == {
        "not_observed",
    }


@pytest.mark.parametrize(
    ("left_value", "right_value", "location"),
    [(None, "20", "property"), ("yes", "no", "model_opinion")],
)
def test_absence_and_model_opinion_are_never_contradictions(
    left_value: str | None, right_value: str, location: str,
) -> None:
    left = _fact("fact-a", value=left_value, location=location)
    right = _fact("fact-b", value=right_value, location=location)
    result = _linked_assessment(
        left, right, rules=(_rule(location=location),),
    )

    assert all(
        row.contradiction_state.value != "potential_conflict"
        for row in result.records
    )


def test_aggregate_order_and_json_are_canonical() -> None:
    left, right = _fact("fact-a"), _fact("fact-b")
    forward = _linked_assessment(left, right, rules=(_rule(),))
    reverse = _linked_assessment(right, left, rules=(_rule(),))

    assert forward == reverse
    assert _api().post_extraction_assessment_value(forward) == (
        _api().post_extraction_assessment_value(reverse)
    )
    assert forward.assessment_hash.startswith("sha256:")


def test_duplicate_semantic_fields_have_order_independent_fact_hash() -> None:
    api = _api()
    left = _fact()
    forward = api.FactRow(
        left.fact_kind,
        left.fact_id,
        left.schema_version_id,
        left.type_name,
        left.subject_key,
        left.target_key,
        left.source_document_id,
        (
            api.SemanticField("property", "dose", "10"),
            api.SemanticField("property", "dose", "20"),
        ),
    )
    reverse = api.FactRow(
        left.fact_kind,
        left.fact_id,
        left.schema_version_id,
        left.type_name,
        left.subject_key,
        left.target_key,
        left.source_document_id,
        tuple(reversed(forward.fields)),
    )

    first = _assessment((forward,)).records[0]
    second = _assessment((reverse,)).records[0]
    assert first.fact_hash == second.fact_hash
