"""Curated-resource records attached to nodes, and the match nobody can check.

Papers are prose, so a proposal drawn from one cites a sentence a reviewer
reads and judges. A UniProt entry is a curated fact table: nothing in it is
invented, and re-reading it settles nothing. The risk moves — from "did the
model make this up" to **"is this the right record"** — and that risk is
sharp, because a wrong record is a page of true statements about something
else.

The very first probe written against UniProt demonstrated it. Asked for
`BRCA1`, the top hit was:

    Q6UWZ7 — BRCA1-A complex subunit Abraxas 1   (gene: ABRAXAS1)

a different protein, ranked first because its *name contains* the query.
Attaching its function text to a node called BRCA1 would have produced an
annotation both entirely true and entirely wrong.

Hence the shape these tests pin: exact field-qualified lookups only, a miss
rather than a near-miss, verified nodes only, and a human decision before
anything reaches the node.
"""

from __future__ import annotations

import json

import pytest

from ontologylab.connectors.resources import (
    MYGENE_RESOURCE,
    UNIPROT_RESOURCE,
    ResourceMatch,
    build_mygene_url,
    build_uniprot_url,
    parse_mygene,
    parse_uniprot,
)
from ontologylab.enrichment import enrich
from ontologylab.kgstore import KGStore
from ontologylab.models import ProposedEntity, SourceSpan

# Trimmed to the fields the builders request.
UNIPROT_BRCA1 = json.dumps(
    {
        "results": [
            {
                "primaryAccession": "P38398",
                "genes": [{"geneName": {"value": "BRCA1"}}],
                "proteinDescription": {
                    "recommendedName": {
                        "fullName": {
                            "value": "Breast cancer type 1 susceptibility protein"
                        }
                    }
                },
                "organism": {"scientificName": "Homo sapiens"},
                "comments": [
                    {
                        "commentType": "FUNCTION",
                        "texts": [{"value": "E3 ubiquitin-protein ligase."}],
                    }
                ],
            }
        ]
    }
)

# The real hazard, in the shape the API actually returned it.
UNIPROT_NEAR_MISS = json.dumps(
    {
        "results": [
            {
                "primaryAccession": "Q6UWZ7",
                "genes": [{"geneName": {"value": "ABRAXAS1"}}],
                "proteinDescription": {
                    "recommendedName": {
                        "fullName": {"value": "BRCA1-A complex subunit Abraxas 1"}
                    }
                },
            }
        ]
    }
)

MYGENE_BRCA1 = json.dumps(
    {
        "hits": [
            {
                "symbol": "BRCA1",
                "name": "BRCA1 DNA repair associated",
                "summary": "This gene encodes a 190 kD nuclear phosphoprotein.",
                "entrezgene": "672",
            }
        ]
    }
)


def _store(tmp_path) -> KGStore:
    return KGStore.open(tmp_path / "kg.sqlite")


def _verified_node(store: KGStore, name: str) -> str:
    text = f"{name} appears here."
    doc, _ = store.insert_document(
        source_kind="upload",
        source_uri=f"u://{name}",
        title="t",
        raw_text=text,
        content_hash=name,
    )
    store.insert_proposed(
        [
            ProposedEntity(
                id=name,
                entity_type="Concept",
                name=name,
                confidence=0.9,
                source_span=SourceSpan(start=0, end=len(name)),
            )
        ],
        [],
        source_doc_id=doc.id,
        extractor_engine="mock",
        extractor_model=None,
        prompt_version="v1",
    )
    node_id = [
        item["id"] for item in store.pending_review(kind="node") if item["label"] == name
    ][0]
    store.approve(node_id)
    return node_id


# --------------------------------------------------------------------------
# The lookup refuses to guess
# --------------------------------------------------------------------------


def test_the_query_is_field_qualified_not_free_text() -> None:
    """A bare term is what returned ABRAXAS1 for BRCA1."""
    url = build_uniprot_url("BRCA1")

    assert "gene_exact%3ABRCA1" in url
    assert "organism_id%3A9606" in url, "symbols collide across organisms"
    assert "reviewed%3Atrue" in url, "TrEMBL adds isoform fragments sharing a symbol"
    assert build_mygene_url("BRCA1").count("symbol%3ABRCA1") == 1


def test_an_exact_record_becomes_a_match() -> None:
    match = parse_uniprot(UNIPROT_BRCA1, "BRCA1")

    assert match is not None
    assert match.external_id == "P38398"
    assert match.record_url == "https://www.uniprot.org/uniprotkb/P38398"
    assert match.matched_name == "Breast cancer type 1 susceptibility protein"
    assert "ubiquitin" in match.facts["function"]


def test_a_record_that_merely_mentions_the_name_is_not_a_match() -> None:
    """The measured failure, pinned.

    Q6UWZ7's *name* contains "BRCA1"; its gene is ABRAXAS1. The parser
    re-checks the gene against what was asked for, so a resource that
    ignored the field qualifier cannot slip a near-match past it.
    """
    assert parse_uniprot(UNIPROT_NEAR_MISS, "BRCA1") is None


def test_mygene_confirms_the_symbol_it_returns() -> None:
    assert parse_mygene(MYGENE_BRCA1, "BRCA1").external_id == "672"
    assert parse_mygene(MYGENE_BRCA1, "TP53") is None, "wrong symbol, not a match"


def test_no_hits_is_a_miss_not_an_error() -> None:
    assert parse_uniprot('{"results": []}', "NOSUCHGENE") is None
    assert parse_mygene('{"hits": []}', "NOSUCHGENE") is None


# --------------------------------------------------------------------------
# Which nodes get looked up
# --------------------------------------------------------------------------


def test_only_verified_nodes_are_enriched(tmp_path) -> None:
    """A proposal may be rejected within the hour; enriching it spends
    requests on a name that may never become part of the graph."""
    store = _store(tmp_path)
    try:
        _verified_node(store, "BRCA1")
        doc, _ = store.insert_document(
            source_kind="upload",
            source_uri="u://p",
            title="t",
            raw_text="TP53 here.",
            content_hash="p",
        )
        store.insert_proposed(
            [
                ProposedEntity(
                    id="p1",
                    entity_type="Concept",
                    name="TP53",
                    confidence=0.9,
                    source_span=SourceSpan(start=0, end=4),
                )
            ],
            [],
            source_doc_id=doc.id,
            extractor_engine="mock",
            extractor_model=None,
            prompt_version="v1",
        )

        seen: list[str] = []

        def fake(resource, name):
            seen.append(name)
            return None

        enrich(store, resources=[UNIPROT_RESOURCE], lookup_fn=fake)

        assert seen == ["BRCA1"], "the unapproved TP53 must not be looked up"
    finally:
        store.close()


def test_a_resource_failure_skips_that_node_only(tmp_path) -> None:
    """One resource being down is not a reason to abandon the pass."""
    store = _store(tmp_path)
    try:
        _verified_node(store, "BRCA1")
        _verified_node(store, "TP53")

        def fake(resource, name):
            if name == "BRCA1":
                raise RuntimeError("resource exploded")
            return ResourceMatch(
                resource=resource,
                external_id="P04637",
                record_url="https://example.invalid/P04637",
                matched_name="Cellular tumor antigen p53",
            )

        report = enrich(store, resources=[UNIPROT_RESOURCE], lookup_fn=fake)

        assert report.matched == 1
        assert report.proposed == 1
        assert len(report.failures) == 1
        assert "BRCA1" in report.failures[0]
    finally:
        store.close()


# --------------------------------------------------------------------------
# The queue, and what approval does
# --------------------------------------------------------------------------


def test_the_queue_shows_both_names_so_the_match_can_be_judged(tmp_path) -> None:
    """The reviewer's whole job is comparing what we called it with what the
    resource calls it. A row showing only the latter asks them to confirm a
    match they cannot see."""
    store = _store(tmp_path)
    try:
        node_id = _verified_node(store, "BRCA1")
        store.upsert_annotation(
            node_id=node_id,
            resource=UNIPROT_RESOURCE,
            external_id="P38398",
            record_url="https://www.uniprot.org/uniprotkb/P38398",
            matched_name="Breast cancer type 1 susceptibility protein",
            facts={"organism": "Homo sapiens"},
        )

        [row] = store.annotations_pending()

        assert row["node_name"] == "BRCA1"
        assert row["matched_name"] == "Breast cancer type 1 susceptibility protein"
        assert row["record_url"].endswith("P38398")
        assert row["facts"]["organism"] == "Homo sapiens"
    finally:
        store.close()


def test_a_repeated_lookup_refreshes_rather_than_duplicates(tmp_path) -> None:
    """Two rows for one (node, resource) would cost the reviewer an extra
    rejection and let them approve a record the resource has replaced."""
    store = _store(tmp_path)
    try:
        node_id = _verified_node(store, "BRCA1")
        first, created_a = store.upsert_annotation(
            node_id=node_id, resource=UNIPROT_RESOURCE, external_id="P38398",
            record_url="u", matched_name="old name", facts={},
        )
        second, created_b = store.upsert_annotation(
            node_id=node_id, resource=UNIPROT_RESOURCE, external_id="P38398",
            record_url="u", matched_name="new name", facts={},
        )

        assert first == second
        assert (created_a, created_b) == (True, False)
        assert store.annotation_counts()["proposed"] == 1
        assert store.annotations_pending()[0]["matched_name"] == "new name"
    finally:
        store.close()


def test_approval_writes_the_facts_under_the_resource_name(tmp_path) -> None:
    """Attribution survives. A flat merge into properties would lose which
    resource said what, and let two resources overwrite each other."""
    store = _store(tmp_path)
    try:
        node_id = _verified_node(store, "BRCA1")
        annotation_id, _ = store.upsert_annotation(
            node_id=node_id, resource=UNIPROT_RESOURCE, external_id="P38398",
            record_url="https://www.uniprot.org/uniprotkb/P38398",
            matched_name="Breast cancer type 1 susceptibility protein",
            facts={"function": "E3 ubiquitin-protein ligase."},
        )

        assert store.decide_annotation(annotation_id, accept=True, by="tester")

        props = json.loads(
            store.conn.execute(
                "SELECT properties_json FROM nodes WHERE id = ?", (node_id,)
            ).fetchone()[0]
        )
        assert props[UNIPROT_RESOURCE]["external_id"] == "P38398"
        assert props[UNIPROT_RESOURCE]["record_url"].endswith("P38398")
        assert "ubiquitin" in props[UNIPROT_RESOURCE]["function"]
    finally:
        store.close()


def test_rejection_leaves_the_node_untouched(tmp_path) -> None:
    store = _store(tmp_path)
    try:
        node_id = _verified_node(store, "BRCA1")
        annotation_id, _ = store.upsert_annotation(
            node_id=node_id, resource=UNIPROT_RESOURCE, external_id="P38398",
            record_url="u", matched_name="wrong record", facts={"function": "x"},
        )

        assert store.decide_annotation(annotation_id, accept=False)

        props = json.loads(
            store.conn.execute(
                "SELECT properties_json FROM nodes WHERE id = ?", (node_id,)
            ).fetchone()[0]
        )
        assert UNIPROT_RESOURCE not in props
        assert store.annotation_counts()["rejected"] == 1
    finally:
        store.close()


def test_a_decision_is_not_overwritten_by_a_later_lookup(tmp_path) -> None:
    """Approval is the one thing this table exists to record. A refresh that
    reset it would make the decision unstable — and could swap the record
    out from under an approval a person already gave."""
    store = _store(tmp_path)
    try:
        node_id = _verified_node(store, "BRCA1")
        annotation_id, _ = store.upsert_annotation(
            node_id=node_id, resource=UNIPROT_RESOURCE, external_id="P38398",
            record_url="u", matched_name="right record", facts={},
        )
        store.decide_annotation(annotation_id, accept=True)

        store.upsert_annotation(
            node_id=node_id, resource=UNIPROT_RESOURCE, external_id="SOMETHING-ELSE",
            record_url="u2", matched_name="different record", facts={},
        )

        row = store.conn.execute(
            "SELECT status, external_id FROM annotations WHERE id = ?",
            (annotation_id,),
        ).fetchone()
        assert row["status"] == "verified"
        assert row["external_id"] == "P38398"
    finally:
        store.close()


def test_deciding_twice_is_refused(tmp_path) -> None:
    store = _store(tmp_path)
    try:
        node_id = _verified_node(store, "BRCA1")
        annotation_id, _ = store.upsert_annotation(
            node_id=node_id, resource=MYGENE_RESOURCE, external_id="672",
            record_url="u", matched_name="n", facts={},
        )

        assert store.decide_annotation(annotation_id, accept=True)
        assert not store.decide_annotation(annotation_id, accept=False)
    finally:
        store.close()


def test_an_unknown_resource_is_refused_before_any_request(tmp_path) -> None:
    store = _store(tmp_path)
    try:
        with pytest.raises(Exception):
            enrich(store, resources=["not-a-resource"])
    finally:
        store.close()
