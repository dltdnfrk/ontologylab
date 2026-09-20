"""Competency questions bound to a schema version, and their coverage check.

competency.py pins three frozen pipeline gates; schema CQs are the
design-time counterpart — the questions a schema version must be able to
answer. A CQ declares the term names it depends on; check_schema_cqs
reports coverage so a schema that cannot express its own questions fails
loudly instead of drifting.
"""

from __future__ import annotations

import pytest

from ontologylab.kgstore import KGStoreError, UnknownItem


def _schema(store):
    return store.install_schema(
        label="cq-test",
        description="",
        entity_types=[
            {"name": "Gene", "description": "", "attributes": {}},
            {"name": "Disease", "description": "", "attributes": {}},
        ],
        relation_types=[
            {"name": "causes", "description": "", "domain_type": "Gene",
             "range_type": "Disease", "directed": True},
        ],
    )


def test_add_and_list_cqs(store):
    sv = _schema(store)
    cq = store.add_schema_cq(
        "Which genes cause which diseases?",
        requires=["Gene", "causes", "Disease"],
        reviewer="tester",
        provenance="test",
    )
    assert cq["schema_version_id"] == sv
    listed = store.list_schema_cqs()
    assert [c["question"] for c in listed] == [
        "Which genes cause which diseases?"
    ]
    assert listed[0]["requires"] == ["Gene", "causes", "Disease"]


def test_coverage_check_passes_when_terms_exist(store):
    _schema(store)
    store.add_schema_cq(
        "Which genes cause which diseases?",
        requires=["Gene", "causes", "Disease"],
        reviewer="tester",
        provenance="test",
    )
    out = store.check_schema_cqs()
    assert out["covered"] == 1 and out["total"] == 1
    assert out["questions"][0]["covered"] is True


def test_coverage_check_reports_missing_terms(store):
    _schema(store)
    store.add_schema_cq(
        "Which drugs treat which diseases?",
        requires=["Drug", "treats", "Disease"],
        reviewer="tester",
        provenance="test",
    )
    out = store.check_schema_cqs()
    assert out["covered"] == 0
    assert out["questions"][0]["missing"] == ["Drug", "treats"]


def test_unscoped_cq_is_uncovered(store):
    _schema(store)
    store.add_schema_cq(
        "What is in the graph?",
        reviewer="tester",
        provenance="test",
    )
    out = store.check_schema_cqs()
    assert out["questions"][0]["covered"] is False
    assert out["questions"][0]["reason"] == "unscoped"


def test_empty_question_rejected(store):
    _schema(store)
    with pytest.raises(KGStoreError):
        store.add_schema_cq("  ", reviewer="t", provenance="t")


def test_unknown_version_rejected(store):
    _schema(store)
    with pytest.raises(UnknownItem):
        store.add_schema_cq(
            "q", schema_version_id=9999, reviewer="t", provenance="t"
        )
    with pytest.raises(UnknownItem):
        store.list_schema_cqs(schema_version_id=9999)
