"""claims_for / find_contradictions / compare_claims over a real built pack."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from ontologylab.kgstore import KGStore
from ontologylab.mcp_server import PackSession, build_mcp_app
from ontologylab.models import ProposedEntity, ProposedRelation
from ontologylab.packbuilder import build_pack
from ontologylab.schemas import preset


def _entity(eid: str, etype: str, name: str, **props) -> ProposedEntity:
    return ProposedEntity(id=eid, entity_type=etype, name=name, properties=props)


def _controls(rid: str, src: str, dst: str, polarity: str) -> ProposedRelation:
    return ProposedRelation(
        id=rid, relation_type="controls", src_entity_id=src, dst_entity_id=dst,
        qualifiers={"polarity": polarity},
    )


def _paper(store: KGStore, tag: str):
    doc, _ = store.insert_document(
        source_kind="upload", source_uri=f"https://doi.org/10.1/{tag}", title=tag,
        raw_text=f"Paper {tag} on Fluopyram and Botrytis", content_hash=f"sha256:{tag}",
    )
    return doc


@pytest.fixture()
def session(tmp_path: Path):
    kg = tmp_path / "kg.sqlite"
    store = KGStore.open(kg)
    schema = preset("agrochem-v2")
    store.install_schema(
        label=schema["label"], description=schema["description"],
        entity_types=schema["entity_types"], relation_types=schema["relation_types"],
    )
    papers = {tag: _paper(store, tag) for tag in ("a", "b", "c", "d")}
    fluo = ("fluo", "ActiveIngredient", "Fluopyram")
    boscalid = ("bosc", "ActiveIngredient", "Boscalid")
    botrytis = ("botr", "Pathogen", "Botrytis cinerea")
    alternaria = ("alt", "Pathogen", "Alternaria solani")
    batches = [
        ("a", [fluo, botrytis], [_controls("e1", "fluo", "botr", "supports")]),
        ("b", [fluo, botrytis], [_controls("e2", "fluo", "botr", "no_effect")]),
        ("c", [fluo, boscalid, botrytis, alternaria], [
            _controls("e3", "fluo", "alt", "supports"),
            _controls("e4", "bosc", "botr", "supports"),
            _controls("e5", "bosc", "botr", "refutes"),
        ]),
        ("d", [boscalid, alternaria], [
            _controls("e6", "bosc", "alt", "refutes"),
            _controls("e7", "bosc", "alt", "no_effect"),
        ]),
    ]
    for tag, ents, rels in batches:
        store.insert_proposed(
            [_entity(*e) for e in ents], rels,
            source_doc_id=papers[tag].id, extractor_engine="mock",
        )
    for table in ("nodes", "edges"):
        for (item,) in store.conn.execute(
            f"SELECT id FROM {table} WHERE status='proposed'"
        ).fetchall():
            store.approve(item)
    ids = dict(store.conn.execute("SELECT name, id FROM nodes").fetchall())
    store.close()
    manifest = build_pack(
        kg, tmp_path / "packs", name="claims", allow_incomplete_extraction=True,
        incomplete_extraction_intent="claims fixture",
    )
    pack_session = PackSession(tmp_path / "packs")
    pack_session.load_pack(manifest.pack_id)
    yield pack_session, ids
    pack_session.close()


def test_claims_for_returns_both_polarities_with_evidence(session) -> None:
    pack, ids = session
    result = pack.claims_for(subject_id=ids["Fluopyram"], object_id=ids["Botrytis cinerea"])
    assert result["count"] == 2
    assert result["polarity_counts"]["supports"] == 1
    assert result["polarity_counts"]["no_effect"] == 1
    claim = result["claims"][0]
    assert claim["origin"] == "extracted" and claim["status"] == "verified"
    assert claim["evidence"]["source_uri"].startswith("https://doi.org/10.1/")
    assert claim["evidence"]["retrieved_at"] is not None
    assert result["pack"]["pack_id"]


def test_claims_for_filters_by_polarity(session) -> None:
    pack, ids = session
    only_null = pack.claims_for(subject_id=ids["Fluopyram"], polarity="no_effect")
    assert [c["object"]["name"] for c in only_null["claims"]] == ["Botrytis cinerea"]


def test_claims_for_rejects_unscoped_and_unknown_polarity(session) -> None:
    pack, ids = session
    with pytest.raises(ValueError):
        pack.claims_for()
    with pytest.raises(ValueError):
        pack.claims_for(subject_id=ids["Fluopyram"], polarity="maybe")


def test_find_contradictions_reports_only_polarity_conflicts(session) -> None:
    pack, _ids = session
    result = pack.find_contradictions()
    pairs = sorted(
        (c["subject"]["name"], c["object"]["name"]) for c in result["contradictions"]
    )
    # Boscalid->Alternaria has two claims, but both oppose: no conflict.
    assert pairs == [("Boscalid", "Botrytis cinerea"), ("Fluopyram", "Botrytis cinerea")]
    fluo = next(c for c in result["contradictions"] if c["subject"]["name"] == "Fluopyram")
    assert [c["polarity"] for c in fluo["opposing"]] == ["no_effect"]


def test_compare_claims_aligns_by_relation_and_object(session) -> None:
    pack, ids = session
    result = pack.compare_claims(ids["Fluopyram"], ids["Boscalid"])
    by_object = {s["object"]["name"]: s for s in result["shared"]}
    assert set(by_object) == {"Botrytis cinerea", "Alternaria solani"}
    # Fluopyram: supports + no_effect on Botrytis; Boscalid: supports + refutes.
    assert by_object["Botrytis cinerea"]["agree"] is False
    assert len(by_object["Botrytis cinerea"]["b"]) == 2
    # Fluopyram supports Alternaria; Boscalid refutes and finds no effect.
    assert by_object["Alternaria solani"]["agree"] is False
    assert result["disagreements"] == 2
    assert result["only_a"] == [] and result["only_b"] == []


def test_tools_are_registered_on_both_backends(session) -> None:
    pack, _ids = session
    for backend in ("stdlib", "auto"):
        app = build_mcp_app(pack, backend=backend)
        names = {tool.name for tool in asyncio.run(app.list_tools())}
        assert {"claims_for", "find_contradictions", "compare_claims"} <= names
