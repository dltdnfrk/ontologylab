"""Advisory entity enrichment (science-skills slice 2).

A proposed entity's name is looked up in the registry its kind maps to
(UniProt for Gene/Protein, PubChem for Drug, ClinVar for Variant), and
what the registry says is stored beside the review evidence so the human
can confirm the entity is real before approving. Advisory only: nothing
here can change a status.

These tests pin the lookups (with the network boundary stubbed), the
type mapping, the store round-trip, and the API surface.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from ontologylab.connectors import registry_lookup
from ontologylab.connectors.registry_lookup import (
    REGISTRY_FOR_TYPE,
    lookup_entity,
    lookup_uniprot,
    lookup_pubchem,
    lookup_clinvar,
)
from ontologylab.kgstore import KGStore
from ontologylab.models import ProposedEntity

UNIPROT_HIT = """{"results": [{
  "primaryAccession": "Q86YC2",
  "proteinDescription": {"recommendedName": {
    "fullName": {"value": "Partner and localizer of BRCA2"}
  }},
  "genes": [{"geneName": {"value": "PALB2"}}],
  "organism": {"scientificName": "Homo sapiens"}
}]}"""

PUBCHEM_HIT = """{"PropertyTable": {"Properties": [
  {"CID": 23725625, "Title": "Olaparib", "MolecularFormula": "C24H23FN4O3"}
]}}"""

CLINVAR_ESEARCH = '{"esearchresult": {"idlist": ["17672"]}}'
CLINVAR_SUMMARY = """{"result": {"17672": {
  "title": "BRCA2 c.5946delT (p.Ser1982fs)",
  "gene_name": ["BRCA2"]
}}}"""


def _monkey_http(monkeypatch, responses: dict[str, str]) -> None:
    """Serve fixed bodies per URL substring, in the style of the fan-out tests."""

    def fake(url: str) -> bytes:
        for needle, body in responses.items():
            if needle in url:
                return body.encode()
        raise AssertionError(f"unexpected URL: {url}")

    monkeypatch.setattr(registry_lookup, "_get", fake)


def test_type_mapping_is_fixed_per_kind() -> None:
    assert REGISTRY_FOR_TYPE == {
        "Gene": "uniprot",
        "Protein": "uniprot",
        "Drug": "pubchem",
        "Variant": "clinvar",
    }


def test_uniprot_lookup_extracts_accession_and_description(monkeypatch) -> None:
    _monkey_http(monkeypatch, {"rest.uniprot.org": UNIPROT_HIT})
    hit = lookup_uniprot("BRCA2")
    assert hit.registry == "uniprot"
    assert hit.identifier == "Q86YC2"
    assert hit.label == "Partner and localizer of BRCA2"
    assert "Homo sapiens" in hit.description
    assert hit.error == ""


def test_pubchem_lookup_extracts_cid_and_formula(monkeypatch) -> None:
    _monkey_http(monkeypatch, {"pubchem.ncbi.nlm.nih.gov": PUBCHEM_HIT})
    hit = lookup_pubchem("Olaparib")
    assert hit.registry == "pubchem"
    assert hit.identifier == "23725625"
    assert hit.label == "Olaparib"
    assert "C24H23FN4O3" in hit.description


def test_clinvar_lookup_uses_esearch_then_esummary(monkeypatch) -> None:
    _monkey_http(
        monkeypatch,
        {"esearch.fcgi": CLINVAR_ESEARCH, "esummary.fcgi": CLINVAR_SUMMARY},
    )
    hit = lookup_clinvar("BRCA2 c.5946delT")
    assert hit.registry == "clinvar"
    assert hit.identifier == "17672"
    assert "c.5946delT" in hit.label
    assert "BRCA2" in hit.description


def test_uniprot_lookup_unwraps_the_value_wrapped_full_name(monkeypatch) -> None:
    """The live API wraps i18n strings as {'value': ...} — the smoke test
    hit the old fixture's flat string and crashed the store write with a
    dict bound to a TEXT column. This pins the real shape end to end.
    """
    _monkey_http(monkeypatch, {"rest.uniprot.org": UNIPROT_HIT})
    hit = lookup_uniprot("BRCA2")
    assert hit.identifier == "Q86YC2"
    assert hit.label == "Partner and localizer of BRCA2"
    assert hit.description == "PALB2 · Homo sapiens"
    assert hit.error == ""

    # and a dict fullName must never reach the store as a label
    assert isinstance(hit.label, str)


def test_lookup_entity_maps_kind_to_registry(monkeypatch) -> None:
    _monkey_http(
        monkeypatch,
        {
            "rest.uniprot.org": UNIPROT_HIT,
            "pubchem.ncbi.nlm.nih.gov": PUBCHEM_HIT,
            "esearch.fcgi": CLINVAR_ESEARCH,
            "esummary.fcgi": CLINVAR_SUMMARY,
        },
    )
    assert lookup_entity("BRCA2", "Gene")[0].registry == "uniprot"
    assert lookup_entity("Olaparib", "Drug")[0].registry == "pubchem"
    assert lookup_entity("BRCA2 c.5946delT", "Variant")[0].registry == "clinvar"
    # Kinds without a registry are skipped, not invented
    assert lookup_entity("breast cancer", "Disease") == []


def test_a_failed_lookup_carries_the_failure_key(monkeypatch) -> None:
    def fake(url: str) -> bytes:
        raise ValueError("timeout")

    monkeypatch.setattr(registry_lookup, "_get", fake)
    (hit,) = lookup_entity("BRCA2", "Gene")
    assert hit.error == "timeout"
    assert hit.identifier == ""


def _store(tmp_path: Path) -> KGStore:
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    return KGStore.open(data_dir / "kg.sqlite")


def test_enrichment_store_roundtrip_and_replace(tmp_path: Path) -> None:
    store = _store(tmp_path)
    ts = time.time()
    store.upsert_enrichment(
        node_id="n1", registry="uniprot", identifier="P51587",
        label="BRCA2", description="Homo sapiens", fetched_ts=ts,
    )
    rows = store.list_enrichments("n1")
    assert len(rows) == 1
    assert rows[0]["identifier"] == "P51587"

    store.upsert_enrichment(
        node_id="n1", registry="uniprot", identifier="NEW",
        label="BRCA2", description="", fetched_ts=ts + 1,
    )
    rows = store.list_enrichments("n1")
    assert len(rows) == 1
    assert rows[0]["identifier"] == "NEW", "a re-run replaces the earlier answer"
    assert store.list_enrichments("n2") == []
    store.close()


def test_enrich_api_stores_and_returns(monkeypatch, tmp_path: Path) -> None:
    from fastapi.testclient import TestClient

    from ontologylab.server.app import create_app

    _monkey_http(
        monkeypatch,
        {
            "rest.uniprot.org": UNIPROT_HIT,
            "pubchem.ncbi.nlm.nih.gov": PUBCHEM_HIT,
            "esearch.fcgi": CLINVAR_ESEARCH,
            "esummary.fcgi": CLINVAR_SUMMARY,
        },
    )
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    store = KGStore.open(data_dir / "kg.sqlite")
    doc, _ = store.insert_document(
        source_kind="upload", source_uri="file:///t", title="T",
        raw_text="BRCA2 loss drives PARP resistance.", content_hash="enr-h1",
    )
    store.insert_proposed(
        [ProposedEntity(id="n_brca2", entity_type="Gene", name="BRCA2")],
        [],
        source_doc_id=doc.id,
        extractor_engine="mock",
    )
    store.close()
    client = TestClient(create_app(data_dir=data_dir))

    resp = client.post("/api/review/n_brca2/enrich")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["enrichments"][0]["registry"] == "uniprot"
    assert body["enrichments"][0]["identifier"] == "Q86YC2"

    got = client.get("/api/enrichments/n_brca2").json()
    assert got["enrichments"][0]["label"] == "Partner and localizer of BRCA2"
    # advisory: approving is still the only status change, and a GET is read-only
    assert client.get("/api/enrichments/unknown-node").status_code == 200
    assert client.post("/api/review/unknown-node/enrich").status_code == 404


def test_enrich_api_skips_kinds_without_a_registry(
    monkeypatch, tmp_path: Path
) -> None:
    from fastapi.testclient import TestClient

    from ontologylab.server.app import create_app

    data_dir = tmp_path / "data"
    data_dir.mkdir()
    store = KGStore.open(data_dir / "kg.sqlite")
    doc, _ = store.insert_document(
        source_kind="upload", source_uri="file:///t", title="T",
        raw_text="breast cancer", content_hash="enr-h2",
    )
    store.insert_proposed(
        [ProposedEntity(id="n_dis", entity_type="Disease", name="breast cancer")],
        [],
        source_doc_id=doc.id,
        extractor_engine="mock",
    )
    store.close()
    client = TestClient(create_app(data_dir=data_dir))

    body = client.post("/api/review/n_dis/enrich").json()
    assert body["enrichments"] == []
