"""Typed extraction-to-ontology proposals through the real web API.

An extracted row is evidence for a vocabulary proposal, never authority to
publish one.  These tests keep the conversion deterministic and make the
second, human verification gate observable in both the API and the SPA.
"""

from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from ontologylab.kgstore import KGStore
from ontologylab.models import OntologyCandidate, ProposedEntity, ProposedRelation
from ontologylab.proposals import build_ontology_proposals, candidate_from_dict
from ontologylab.server.app import create_app

PREVIEW = "/api/ontology/proposals/preview"
VERIFY = "/api/ontology/proposals/verify"
REVIEW = {"reviewer": "curator-7", "provenance": "curation:p1-d"}


def _client(tmp_path: Path) -> tuple[TestClient, Path]:
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    return TestClient(create_app(data_dir=data_dir)), data_dir / "kg.sqlite"


def _xref(**over: Any) -> dict[str, Any]:
    value: dict[str, Any] = {
        "authority": "AGROVOC",
        "external_id": "c_12345",
        "mapping_predicate": "close",
        "source_uri": "https://registry.example/c_12345",
        "source_version": "2026-08",
        "valid_from": None,
        "valid_to": None,
        "retrieved_at": 1_786_233_600.0,
        "confidence": 0.8,
        "license_gate": "identifier-only",
        "lifecycle": "active",
        "replacement_xref_id": None,
        "change_reason": None,
    }
    return {**value, **over}


def _candidate(candidate_id: str, **over: Any) -> dict[str, Any]:
    value: dict[str, Any] = {
        "id": candidate_id,
        "source_kind": "entity",
        "source_id": candidate_id,
        "source_status": "proposed",
        "source_verified_by": None,
        "source_verified_at": None,
        "schema_version_id": 1,
        "type_name": "Disease",
        "preferred_label": "Leaf blight",
        "language": "en",
        "definition": "A disease characterized by blighted leaves.",
        "aliases": ["Foliar blight"],
        "qualifiers": {"evidence_level": "field", "replicates": 3},
        "lifecycle": "active",
        "replacement_term_id": None,
        "change_reason": None,
        "xrefs": [_xref()],
        "source_doc_id": "doc-1",
        "source_span": {"start": 10, "end": 25},
    }
    return {**value, **over}


def _seed_qualified_extraction(db_path: Path) -> tuple[str, str]:
    store = KGStore.open(db_path)
    try:
        schema_id = store.install_schema(
            label="proposal-fixture-v1",
            description="typed ontology proposal fixture",
            entity_types=[
                {
                    "name": "Disease",
                    "description": "A plant disease.",
                    "attributes": {
                        "definition": {"type": "string", "required": False}
                    },
                }
            ],
            relation_types=[
                {
                    "name": "affects",
                    "description": "A disease affects another disease.",
                    "domain_type": "Disease",
                    "range_type": "Disease",
                    "directed": True,
                    "qualifiers": {
                        "evidence_level": {
                            "type": "string",
                            "enum": ["field", "laboratory"],
                            "required": False,
                        }
                    },
                }
            ],
        )
        doc, _ = store.insert_document(
            source_kind="upload",
            source_uri="file:///proposal.txt",
            title="proposal fixture",
            raw_text="Leaf blight affects leaf spot in field trials.",
            content_hash="sha256:proposal-fixture",
        )
        left = ProposedEntity(
            id="candidate-leaf-blight",
            entity_type="Disease",
            name="Leaf blight",
            properties={"definition": "A disease causing blighted leaves."},
        )
        right = ProposedEntity(
            id="candidate-leaf-spot",
            entity_type="Disease",
            name="Leaf spot",
            properties={"definition": "A disease causing leaf spots."},
        )
        relation = ProposedRelation(
            id="candidate-affects",
            relation_type="affects",
            src_entity_id=left.id,
            dst_entity_id=right.id,
            qualifiers={"evidence_level": "field"},
        )
        store.insert_proposed(
            [left, right],
            [relation],
            source_doc_id=doc.id,
            extractor_engine="mock",
        )
        assert schema_id == store.active_schema_version()["id"]
        return left.id, relation.id
    finally:
        store.close()


def test_collapse_is_order_independent_and_preserves_typed_evidence(
    tmp_path: Path,
) -> None:
    """Equivalent candidates collapse once without dropping qualifiers/xrefs."""
    store = KGStore.open(tmp_path / "kg.sqlite")
    try:
        schema_id = store.active_schema_version()["id"]
        first = candidate_from_dict(
            _candidate(
                "candidate-b",
                schema_version_id=schema_id,
                aliases=["Foliar blight", "Leaf scorch"],
            )
        )
        second = candidate_from_dict(
            _candidate(
                "candidate-a",
                schema_version_id=schema_id,
                aliases=["Leaf scorch", "Foliar blight"],
                qualifiers={"replicates": 3, "evidence_level": "field"},
            )
        )
        assert isinstance(first, OntologyCandidate)

        forward = build_ontology_proposals(store, [first, second])
        reverse = build_ontology_proposals(store, [second, first, first])
    finally:
        store.close()

    assert [asdict(item) for item in forward] == [asdict(item) for item in reverse]
    assert len(forward) == 1
    proposal = forward[0]
    assert proposal.source_candidate_ids == ("candidate-a", "candidate-b")
    assert proposal.aliases == ("Foliar blight", "Leaf scorch")
    assert proposal.qualifiers == {"evidence_level": "field", "replicates": 3}
    assert len(proposal.xrefs) == 1
    assert proposal.requires_human_verification is True
    assert proposal.verification is None


def test_real_extraction_preview_propagates_qualifiers_and_verification_state(
    tmp_path: Path,
) -> None:
    client, db_path = _client(tmp_path)
    node_id, edge_id = _seed_qualified_extraction(db_path)
    with KGStore.open(db_path) as store:
        store.approve(node_id, by="source-curator")

    first = client.post(PREVIEW, json={"source_ids": [edge_id, node_id, edge_id]})
    second = client.post(PREVIEW, json={"source_ids": [node_id, edge_id]})

    assert first.status_code == second.status_code == 200
    assert first.json() == second.json()
    body = first.json()
    relation = next(c for c in body["candidates"] if c["source_kind"] == "relation")
    assert relation["qualifiers"] == {"evidence_level": "field"}
    assert relation["source_status"] == "proposed"
    assert relation["source_verified_by"] is None
    entity = next(c for c in body["candidates"] if c["source_kind"] == "entity")
    assert entity["source_status"] == "verified"
    assert entity["source_verified_by"] == "source-curator"
    assert entity["source_verified_at"] > 0
    assert body["count"] == len(body["proposals"]) == 2

    node_proposal = next(
        p for p in body["proposals"] if p["preferred_label"] == "Leaf blight"
    )
    verified = client.post(
        VERIFY,
        json={"proposal": node_proposal, "verification": REVIEW},
    )

    assert verified.status_code == 200
    result = verified.json()
    assert result["ok"] is True and result["created"] is True
    assert result["proposal"]["requires_human_verification"] is False
    metadata = result["proposal"]["verification"]
    assert metadata["decision"] == "approved"
    assert metadata["reviewer"] == REVIEW["reviewer"]
    assert metadata["provenance"] == REVIEW["provenance"]
    assert metadata["verified_at"] > 0
    with KGStore.open(db_path) as store:
        term = store.get_ontology_term(result["term"]["id"])
    assert (term["reviewer"], term["provenance"]) == (
        REVIEW["reviewer"], REVIEW["provenance"]
    )


def test_lifecycle_and_close_xref_map_without_merging_local_identity(
    tmp_path: Path,
) -> None:
    client, db_path = _client(tmp_path)
    store = KGStore.open(db_path)
    try:
        schema_id = store.active_schema_version()["id"]
        replacement_id = store.create_ontology_term(
            preferred_label="Foliar disease",
            language="en",
            definition="A broad disease concept.",
            schema_version_id=schema_id,
            reviewer="seed-reviewer",
            provenance="curation:seed",
        )
        old_xref_id = store.add_term_xref(
            term_id=replacement_id,
            reviewer="seed-reviewer",
            **_xref(),
        )
        before = store.conn.execute("SELECT COUNT(*) FROM ontology_term").fetchone()[0]
    finally:
        store.close()

    candidate = _candidate(
        "candidate-close-match",
        schema_version_id=schema_id,
        preferred_label="Distinct leaf syndrome",
        lifecycle="replaced",
        replacement_term_id=replacement_id,
        change_reason="The reviewed concept is broader.",
    )
    preview = client.post(PREVIEW, json={"candidates": [candidate]})

    assert preview.status_code == 200
    proposal = preview.json()["proposals"][0]
    assert proposal["action"] == "create"
    assert proposal["target_term_id"] is None
    applied = client.post(VERIFY, json={"proposal": proposal, "verification": REVIEW})

    assert applied.status_code == 200
    new_id = applied.json()["term"]["id"]
    assert new_id != replacement_id
    with KGStore.open(db_path) as store:
        assert store.conn.execute("SELECT COUNT(*) FROM ontology_term").fetchone()[0] == before + 1
        new_term = store.get_ontology_term(new_id)
        assert (new_term["lifecycle"], new_term["replacement_term_id"]) == (
            "replaced", replacement_id,
        )
        new_xrefs = store.list_term_xrefs(new_id)
        assert len(new_xrefs) == 1
        assert new_xrefs[0]["mapping_predicate"] == "close"
        assert new_xrefs[0]["id"] != old_xref_id
        assert len(store.list_term_xrefs(replacement_id)) == 1


def test_stale_proposal_and_malformed_requests_have_stable_typed_4xx(
    tmp_path: Path,
) -> None:
    client, db_path = _client(tmp_path)
    with KGStore.open(db_path) as store:
        schema_id = store.active_schema_version()["id"]
    preview = client.post(
        PREVIEW,
        json={"candidates": [_candidate("candidate-stale", schema_version_id=schema_id)]},
    )
    assert preview.status_code == 200
    proposal = preview.json()["proposals"][0]
    accepted = client.post(
        VERIFY, json={"proposal": proposal, "verification": REVIEW}
    )
    assert accepted.status_code == 200

    stale = client.post(VERIFY, json={"proposal": proposal, "verification": REVIEW})
    unknown = client.post(PREVIEW, json={"source_ids": ["not-an-artifact"]})
    malformed = client.post(
        PREVIEW,
        json={"candidates": [_candidate("bad", aliases=["valid", 7])]},
    )
    no_reviewer = client.post(
        VERIFY,
        json={"proposal": proposal, "verification": {"provenance": "curation:x"}},
    )
    invalid_json = client.post(
        PREVIEW,
        content="{",
        headers={"Content-Type": "application/json"},
    )

    assert (
        stale.status_code,
        unknown.status_code,
        malformed.status_code,
        no_reviewer.status_code,
        invalid_json.status_code,
    ) == (409, 404, 400, 400, 400)
    for response in (stale, unknown, malformed, no_reviewer, invalid_json):
        detail = response.json()["detail"]
        assert set(detail) == {"ok", "error_kind", "field", "detail"}
        assert detail["ok"] is False
        assert isinstance(detail["error_kind"], str) and detail["error_kind"]
        assert isinstance(detail["field"], str) and detail["field"]
        assert isinstance(detail["detail"], str) and detail["detail"]


def test_spa_exposes_preview_and_human_verify_actions(tmp_path: Path) -> None:
    client, _ = _client(tmp_path)

    script = client.get("/static/app.js")

    assert script.status_code == 200
    assert 'data-ontology-proposal-preview' in script.text
    assert 'data-ontology-proposal-verify' in script.text
    assert PREVIEW in script.text and VERIFY in script.text
    proposal_renderer = script.text.split(
        "async function previewOntologyProposal", 1
    )[1].split("async function loadEntityPanel", 1)[0]
    assert "innerHTML" not in proposal_renderer
    assert "textContent" in proposal_renderer
