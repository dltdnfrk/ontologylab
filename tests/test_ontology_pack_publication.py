"""Reviewed, license-gated ontology publication through packs and MCP."""

from __future__ import annotations

import asyncio
import hashlib
import shutil
import sqlite3
import time
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

from ontologylab.kgstore import KGStore, KGStoreError
from ontologylab.mcp_server import PackSession, build_mcp_app
from ontologylab.models import OntologyTerm, ProposedEntity, TermAlias, TermXref
from ontologylab.ontology_schema import local_term_iri
from ontologylab.packbuilder import PackBuildError, build_pack, list_packs


def _build(kg: Path, packs: Path, name: str):
    return build_pack(
        kg, packs, name, allow_incomplete_extraction=True,
        incomplete_extraction_intent="synthetic ontology publication fixture",
    )


def _add_xref(store: KGStore, term_id: str, external_id: str, gate: str) -> str:
    version = None if gate == "deny-text" else "2026-08"
    return store.add_term_xref(
        term_id=term_id, authority="ExampleAuthority", external_id=external_id,
        mapping_predicate="close", source_uri=f"https://registry.example/{external_id}",
        source_version=version, valid_from=1_700_000_000.0 if version is None else None,
        valid_to=1_800_000_000.0 if version is None else None,
        retrieved_at=1_786_233_600.0, confidence=0.8,
        reviewer="xref-reviewer-1", license_gate=gate,
    )


def _raw_xref(store: KGStore, term_id: str, **changes: object) -> str:
    xref_id = str(uuid4())
    row: dict[str, object] = {
        "id": xref_id, "term_id": term_id, "authority": "RawAuthority",
        "external_id": xref_id, "mapping_predicate": "exact",
        "source_uri": f"https://registry.example/{xref_id}", "source_version": "v1",
        "valid_from": None, "valid_to": None, "retrieved_at": 1_786_233_600.0,
        "confidence": 0.7, "reviewer": "raw-reviewer", "lifecycle": "active",
        "replacement_xref_id": None, "change_reason": None, "license_gate": "allow",
        "created_ts": time.time(), "updated_ts": time.time()}
    row.update(changes)
    columns = tuple(row)
    store.conn.execute(
        f"INSERT INTO term_xref ({', '.join(columns)}) "
        f"VALUES ({', '.join('?' for _ in columns)})",
        tuple(row[column] for column in columns),
    )
    return xref_id


def _seed_ontology(store: KGStore) -> SimpleNamespace:
    schema_id = store.active_schema_version()["id"]
    old_term = store.create_ontology_term(
        preferred_label="Leaf blight", language="en", schema_version_id=schema_id,
        definition="A reviewed local disease concept.", reviewer="term-reviewer-1",
        provenance="curation:local",
    )
    alias_one = store.add_term_alias(
        term_id=old_term, label="Blighted leaf", language="en",
        reviewer="alias-reviewer-1", provenance="curation:alias-1",
    )
    store.rename_ontology_term(
        old_term, preferred_label="Foliar blight", language="en",
        reviewer="term-reviewer-2", provenance="curation:rename",
    )
    alias_two = store.list_term_aliases(old_term)[-1]["id"]
    new_term = store.change_ontology_term_meaning(
        old_term, preferred_label="Foliar blight syndrome", language="en",
        definition="A reviewed local syndrome concept.",
        change_reason="The reviewed meaning broadened.", reviewer="term-reviewer-3",
        provenance="curation:meaning-change",
    )
    deprecated_term = store.create_ontology_term(
        preferred_label="Historic blight", language="en", schema_version_id=schema_id,
        definition="A reviewed historic local concept.", reviewer="term-reviewer-1",
        provenance="curation:historic",
    )
    store.set_ontology_term_lifecycle(
        deprecated_term, lifecycle="deprecated", change_reason="No longer current.",
        reviewer="term-reviewer-2", provenance="curation:deprecation")
    allow_old = _add_xref(store, old_term, "ALLOW-OLD", "allow")
    allow_new = _add_xref(store, old_term, "ALLOW-NEW", "allow")
    identifier_only = _add_xref(store, old_term, "IDENTIFIER-ONLY", "identifier-only")
    deny_text = _add_xref(store, new_term, "DENY-TEXT", "deny-text")
    store.set_term_xref_lifecycle(
        allow_old, lifecycle="replaced", replacement_xref_id=allow_new,
        change_reason="The authority replaced this identifier.", reviewer="xref-reviewer-2",
    )
    store.set_term_xref_lifecycle(
        identifier_only, lifecycle="deprecated", change_reason="Registry retired it.",
        reviewer="xref-reviewer-2",
    )

    now = time.time()
    unreviewed_term = str(uuid4())
    store.conn.execute(
        "INSERT INTO ontology_term (id, iri, preferred_label, language, definition, "
        "lifecycle, schema_version_id, reviewer, provenance, created_ts, updated_ts) "
        "VALUES (?, ?, 'Unreviewed term', 'en', 'UNREVIEWED_TERM_SECRET', "
        "'active', ?, '', '', ?, ?)",
        (unreviewed_term, local_term_iri(unreviewed_term), schema_id, now, now),
    )
    unreviewed_alias = str(uuid4())
    store.conn.execute(
        "INSERT INTO term_alias (id, term_id, label, language, alias_kind, reviewer, "
        "provenance, created_ts) VALUES (?, ?, 'UNREVIEWED_ALIAS_SECRET', 'en', "
        "'alternative', '', '', ?)", (unreviewed_alias, old_term, now),
    )
    store.conn.execute("PRAGMA ignore_check_constraints=ON")
    corruptions = (
        {"authority": ""}, {"external_id": ""}, {"mapping_predicate": "invalid"},
        {"source_uri": ""}, {"source_version": "", "valid_from": None, "valid_to": None},
        {"retrieved_at": "not-a-time"}, {"confidence": 2.0}, {"reviewer": ""},
        {"lifecycle": "invalid"}, {"license_gate": "invalid"},
    )
    malformed = tuple(_raw_xref(store, old_term, **change) for change in corruptions)
    _raw_xref(store, unreviewed_term)
    store.conn.execute("PRAGMA ignore_check_constraints=OFF")
    store.conn.commit()
    names = "schema_id old_term new_term deprecated_term allow_old allow_new identifier_only deny_text unreviewed_term unreviewed_alias"
    values = (schema_id, old_term, new_term, deprecated_term, allow_old, allow_new, identifier_only, deny_text, unreviewed_term, unreviewed_alias)
    return SimpleNamespace(**dict(zip(names.split(), values)),
                           alias_ids=(alias_one, alias_two), malformed_xrefs=malformed)


def test_existing_graph_copy_counts_and_hash_are_unchanged(tmp_path: Path) -> None:
    kg, packs = tmp_path / "kg.sqlite", tmp_path / "packs"
    store = KGStore.open(kg)
    doc, _ = store.insert_document(
        source_kind="upload", source_uri="file:///publication.txt", title="publication",
        raw_text="ReviewedNode ProposedNode", content_hash="publication-graph-v1",
    )
    stats = store.insert_proposed(
        [ProposedEntity(id="reviewed", entity_type="Component", name="ReviewedNode"),
         ProposedEntity(id="proposed", entity_type="Component", name="ProposedNode")],
        [], source_doc_id=doc.id, extractor_engine="mock",
    )
    reviewed_id, proposed_id = stats["id_map"]["reviewed"], stats["id_map"]["proposed"]
    store.approve(reviewed_id, by="graph-reviewer")
    store.close()
    manifest = _build(kg, packs, "characterization")
    pack_path = packs / manifest.pack_id / "pack.sqlite"
    with sqlite3.connect(pack_path) as conn:
        assert conn.execute("SELECT id FROM nodes").fetchall() == [(reviewed_id,)]
        assert conn.execute("SELECT 1 FROM nodes WHERE id = ?", (proposed_id,)).fetchone() is None
    assert (manifest.counts["nodes_verified"], manifest.counts["edges_verified"]) == (1, 0)
    assert manifest.content_hash == "sha256:" + hashlib.sha256(pack_path.read_bytes()).hexdigest()


def test_exact_rows_dependency_order_lifecycle_counts_and_schema_versions(tmp_path: Path) -> None:
    kg, packs = tmp_path / "kg.sqlite", tmp_path / "packs"
    store = KGStore.open(kg)
    seed = _seed_ontology(store)
    expected_term = store.get_ontology_term(seed.old_term)
    expected_xref = store.get_term_xref(seed.allow_old)
    store.close()
    manifest = _build(kg, packs, "ontology")
    pack_path = packs / manifest.pack_id / "pack.sqlite"
    with sqlite3.connect(pack_path) as conn:
        conn.row_factory = sqlite3.Row
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
        assert dict(next(conn.execute(
            "SELECT * FROM ontology_term WHERE id = ?", (seed.old_term,)))) == expected_term
        assert conn.execute("SELECT lifecycle FROM ontology_term WHERE id = ?", (seed.deprecated_term,)).fetchone()[0] == "deprecated"
        assert [row[0] for row in conn.execute("SELECT id FROM term_alias WHERE term_id = ? ORDER BY id", (seed.old_term,))] == sorted(seed.alias_ids)
        assert set(OntologyTerm.__slots__) == {row[1] for row in conn.execute("PRAGMA table_info(ontology_term)")}
        assert set(TermAlias.__slots__) == {row[1] for row in conn.execute("PRAGMA table_info(term_alias)")}
        assert set(TermXref.__slots__) == {row[1] for row in conn.execute("PRAGMA table_info(term_xref)")}
        assert dict(next(conn.execute(
            "SELECT * FROM term_xref WHERE id = ?", (seed.allow_old,)))) == expected_xref
    assert manifest.counts["ontology_terms_reviewed"] >= 3 and (
        manifest.counts["term_aliases_reviewed"], manifest.counts["term_xrefs_reviewed"]) == (2, 4)
    assert seed.schema_id in (manifest.included_schema_version_ids or []) and (manifest.ontology_publication or {})["review_boundary"] == "explicit-current-review-fields-v1"


def test_license_rows_ship_but_malformed_and_unreviewed_dependents_do_not(tmp_path: Path) -> None:
    kg, packs = tmp_path / "kg.sqlite", tmp_path / "packs"
    store = KGStore.open(kg)
    seed = _seed_ontology(store)
    store.close()
    manifest = _build(kg, packs, "licenses")
    pack_path = packs / manifest.pack_id / "pack.sqlite"
    with sqlite3.connect(pack_path) as conn:
        shipped = dict(conn.execute("SELECT id, license_gate FROM term_xref"))
        assert {shipped[xref] for xref in (seed.allow_old, seed.allow_new)} == {"allow"}
        assert shipped[seed.identifier_only] == "identifier-only"
        assert shipped[seed.deny_text] == "deny-text"
        assert seed.unreviewed_term not in {row[0] for row in conn.execute("SELECT id FROM ontology_term")}
        assert seed.unreviewed_alias not in {row[0] for row in conn.execute("SELECT id FROM term_alias")}
        assert not set(seed.malformed_xrefs) & set(shipped)
        columns = {row[1] for row in conn.execute("PRAGMA table_info(term_xref)")}
        assert not {"external_label", "description", "definition", "note"} & columns
    assert b"UNREVIEWED_TERM_SECRET" not in pack_path.read_bytes()


@pytest.mark.parametrize("kind", ["term", "xref", "xref-cross-term"])
def test_dangling_publishable_replacements_fail_without_partial_pack(tmp_path: Path, kind: str) -> None:
    kg, packs = tmp_path / f"{kind}.sqlite", tmp_path / f"{kind}-packs"
    store = KGStore.open(kg)
    seed = _seed_ontology(store)
    if kind == "term":
        store.conn.execute("UPDATE ontology_term SET reviewer = '' WHERE id = ?", (seed.new_term,))
    elif kind == "xref":
        store.conn.execute("UPDATE term_xref SET reviewer = '' WHERE id = ?", (seed.allow_new,))
    else:
        store.conn.execute("UPDATE term_xref SET replacement_xref_id = ? WHERE id = ?", (seed.deny_text, seed.allow_old))
    store.conn.commit()
    store.close()
    with pytest.raises(PackBuildError, match="replacement"):
        _build(kg, packs, f"dangling-{kind}")
    assert not packs.exists() or list(packs.iterdir()) == []


def test_resources_are_pack_specific_read_only_and_legacy_safe(tmp_path: Path) -> None:
    kg, packs = tmp_path / "kg.sqlite", tmp_path / "packs"
    store = KGStore.open(kg)
    seed = _seed_ontology(store)
    store.close()
    old = _build(kg, packs, "old")
    store = KGStore.open(kg)
    store.rename_ontology_term(
        seed.new_term, preferred_label="Current syndrome", language="en",
        reviewer="term-reviewer-4", provenance="curation:current",
    )
    store.close()
    new = _build(kg, packs, "new")
    kg.unlink()
    session = PackSession(packs)
    session.load_pack(new.pack_id)
    term = session.resource_term(old.pack_id, seed.new_term)
    assert (term["term"]["preferred_label"], [row["id"] for row in session.resource_term(old.pack_id, seed.old_term)["aliases"]]) == ("Foliar blight syndrome", sorted(seed.alias_ids))
    assert session.resource_xref(old.pack_id, seed.deny_text)["xref"]["license_gate"] == "deny-text"
    app = build_mcp_app(session)
    tools = {tool.name for tool in asyncio.run(app.list_tools())}
    assert tools == {"list_packs", "get_staleness", "load_pack", "get_schema", "entity_lookup", "get_communities", "get_entity", "semantic_search", "graph_query", "traverse_relations", "find_path"}
    templates = {str(item.uriTemplate) for item in asyncio.run(app.list_resource_templates())}
    assert templates == {"pack://{pack_id}/manifest", "pack://{pack_id}/schema", "pack://{pack_id}/entity/{entity_id}", "pack://{pack_id}/term/{term_id}", "pack://{pack_id}/xref/{xref_id}"}

    legacy = packs / "legacy"
    legacy.mkdir()
    shutil.copyfile(packs / old.pack_id / "pack.sqlite", legacy / "pack.sqlite")
    with sqlite3.connect(legacy / "pack.sqlite") as conn:
        conn.execute("DROP TABLE term_xref")
        conn.execute("DROP TABLE term_alias")
        conn.execute("DROP TABLE ontology_term")
    before = (legacy / "pack.sqlite").read_bytes()
    with pytest.raises(KGStoreError, match="predates ontology term publication"):
        session.resource_term("legacy", seed.new_term)
    assert (legacy / "pack.sqlite").read_bytes() == before
    session.close()


def test_finalize_failure_leaves_no_partial_pack(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    kg, packs = tmp_path / "kg.sqlite", tmp_path / "packs"
    KGStore.open(kg).close()
    original = Path.write_text

    def fail_provenance(path: Path, data: str, *args, **kwargs):
        if path.name == "provenance.jsonl":
            assert list_packs(packs) == []
            raise OSError("injected provenance finalization failure")
        return original(path, data, *args, **kwargs)

    monkeypatch.setattr(Path, "write_text", fail_provenance)
    with pytest.raises(OSError, match="injected provenance finalization failure"):
        _build(kg, packs, "interrupted")
    assert not packs.exists() or list(packs.iterdir()) == []
