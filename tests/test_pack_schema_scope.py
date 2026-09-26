"""Pack schema selection must cover graph, ontology, and completeness."""

from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

from ontologylab.kgstore import KGStore
from ontologylab.models import ProposedEntity, ProposedRelation
from ontologylab.mcp_server import PackSession
from ontologylab.packbuilder import (
    IncompleteExtractionError,
    SchemaVersionSelectionError,
    _prepare_publishable_ontology,
    build_pack,
)


def seed_two_versions(kg: Path) -> tuple[int, int]:
    """Create duplicate reviewed identities and complete streams in two versions."""
    store = KGStore.open(kg)
    versions = [store.active_schema_version()["id"]]
    try:
        for index in range(2):
            if index:
                versions.append(store.install_schema(
                    label="components-v2", description="Second version",
                    entity_types=[{"name": "Component", "attributes": {}}],
                    relation_types=[{
                        "name": "uses", "domain_type": "Component",
                        "range_type": "Component", "directed": True,
                    }],
                ))
            version = versions[-1]
            doc, _ = store.insert_document(
                source_kind="upload", source_uri=f"file:///v{version}.txt",
                title=f"v{version}", raw_text="Gateway uses Limiter.",
                content_hash=f"sha256:version-{version}",
            )
            store.insert_proposed(
                [
                    ProposedEntity(id=f"gateway-{version}", entity_type="Component",
                                   name="Gateway", aliases=["Entry"]),
                    ProposedEntity(id=f"limiter-{version}", entity_type="Component",
                                   name="Limiter", aliases=["Throttle"]),
                ],
                [ProposedRelation(
                    id=f"uses-{version}", relation_type="uses",
                    src_entity_id=f"gateway-{version}",
                    dst_entity_id=f"limiter-{version}",
                )],
                source_doc_id=doc.id, extractor_engine="mock",
                extractor_model="scope-model", prompt_version="scope-v1",
            )
            store.bulk_approve(by="scope-reviewer")
            term = store.create_ontology_term(
                preferred_label="Gateway concept", language="en",
                definition="Reviewed routing concept.", schema_version_id=version,
                reviewer="scope-reviewer", provenance="scope-fixture",
            )
            store.add_term_alias(
                term_id=term, label="Entry concept", language="en",
                reviewer="scope-reviewer", provenance="scope-fixture",
            )
            store.add_term_xref(
                term_id=term, authority="Example", external_id=f"term-{version}",
                mapping_predicate="exact", source_uri="https://example.org/term",
                source_version="1", retrieved_at=1.0, confidence=1.0,
                reviewer="scope-reviewer", license_gate="identifier-only",
            )
            store.conn.execute(
                "INSERT INTO extraction_runs "
                "(id, document_id, document_content_hash, schema_version_id, "
                "extractor_engine, extractor_model, prompt_version, decode_params, "
                "chunk_plan_hash, status, created_ts, updated_ts, finished_ts) "
                "VALUES (?, ?, ?, ?, 'mock', 'scope-model', 'scope-v1', 'null', "
                "'scope-plan', 'complete', 1, 1, 1)",
                (f"run-{version}", doc.id, doc.content_hash, version),
            )
            store.conn.execute(
                "INSERT INTO extraction_chunks "
                "(run_id, chunk_index, char_offset, content_hash, status) "
                "VALUES (?, 0, 0, 'scope-chunk', 'succeeded')",
                (f"run-{version}",),
            )
            store.conn.commit()
    finally:
        store.close()
    return versions[0], versions[1]


def publication_versions(pack: Path) -> dict[str, list[int]]:
    """Inspect independent published tables, including indirect version owners."""
    queries = {
        "schema_version": "SELECT id FROM schema_version",
        **{
            table: f"SELECT DISTINCT schema_version_id FROM {table}"
            for table in ("entity_type", "relation_type", "nodes", "edges", "ontology_term")
        },
        "node_aliases": (
            "SELECT DISTINCT n.schema_version_id FROM node_aliases a "
            "JOIN nodes n ON n.id = a.node_id"
        ),
        "citations": (
            "SELECT n.schema_version_id FROM citations c JOIN nodes n "
            "ON c.kind = 'node' AND c.item_id = n.id UNION "
            "SELECT e.schema_version_id FROM citations c JOIN edges e "
            "ON c.kind = 'edge' AND c.item_id = e.id"
        ),
        **{
            table: f"SELECT DISTINCT t.schema_version_id FROM {table} a "
                   "JOIN ontology_term t ON t.id = a.term_id"
            for table in ("term_alias", "term_xref")
        },
    }
    with sqlite3.connect(pack / "pack.sqlite") as conn:
        return {
            table: sorted(row[0] for row in conn.execute(query))
            for table, query in queries.items()
        }


def test_default_publishes_only_active_version(tmp_path: Path) -> None:
    kg, packs = tmp_path / "kg.sqlite", tmp_path / "packs"
    _old, active = seed_two_versions(kg)

    manifest = build_pack(kg, packs, "active")

    pack = packs / manifest.pack_id
    published = publication_versions(pack)
    assert published == {table: [active] for table in published}
    assert manifest.included_schema_version_ids == [active]
    schema = json.loads((pack / "schema.json").read_text())
    assert set(schema["schemas"]) == {str(active)}
    assert manifest.counts["nodes_verified"] == 2
    assert manifest.counts["edges_verified"] == 1
    assert manifest.extraction_completeness is not None
    assert manifest.extraction_completeness["relevant_stream_count"] == 1


@pytest.mark.parametrize("selection", ["old", "all"])
def test_explicit_selection_preserves_exact_versions(tmp_path: Path, selection: str) -> None:
    kg, packs = tmp_path / "kg.sqlite", tmp_path / "packs"
    old, active = seed_two_versions(kg)
    selected = (old,) if selection == "old" else (old, active)
    with sqlite3.connect(kg) as conn:
        before = list(conn.iterdump())

    manifest = build_pack(kg, packs, selection, schema_version_ids=selected)

    pack = packs / manifest.pack_id
    published = publication_versions(pack)
    assert published == {table: list(selected) for table in published}
    assert manifest.included_schema_version_ids == list(selected)
    schema = json.loads((pack / "schema.json").read_text())
    assert set(schema["schemas"]) == {str(version) for version in selected}
    with sqlite3.connect(kg) as conn:
        assert list(conn.iterdump()) == before
    session = PackSession(packs)
    try:
        session.load_pack(manifest.pack_id)
        assert session.get_schema()["schema_version_id"] == selected[-1]
        for version in selected:
            assert session.get_schema(schema_version_id=version)["schema_version_id"] == version
    finally:
        session.close()


def test_published_version_set_excludes_unselected_ontology_terms(tmp_path: Path) -> None:
    kg = tmp_path / "kg.sqlite"
    _old, active = seed_two_versions(kg)
    with sqlite3.connect(":memory:") as conn:
        conn.row_factory = sqlite3.Row
        conn.execute("CREATE TABLE schema_version (id INTEGER PRIMARY KEY)")
        conn.execute("INSERT INTO schema_version VALUES (?)", (active,))
        conn.execute("ATTACH DATABASE ? AS live", (str(kg),))

        _prepare_publishable_ontology(conn)

        published_versions = {
            row[0] for row in conn.execute(
                "SELECT DISTINCT t.schema_version_id FROM live.ontology_term t "
                "JOIN publishable_ontology_term_id p ON p.id = t.id"
            )
        }
        assert published_versions == {active}


@pytest.mark.parametrize("blocked", ["old", "active"])
@pytest.mark.parametrize("selection", ["default", "old", "all"])
@pytest.mark.parametrize("state", ["failed", "unknown"])
def test_completeness_checks_only_selected_streams(
    tmp_path: Path, blocked: str, selection: str, state: str,
) -> None:
    kg, packs = tmp_path / "kg.sqlite", tmp_path / "packs"
    old, active = seed_two_versions(kg)
    blocked_id = old if blocked == "old" else active
    selected = {"default": (active,), "old": (old,), "all": (old, active)}[selection]
    with sqlite3.connect(kg) as conn:
        if state == "failed":
            conn.execute(
                "UPDATE extraction_runs SET status = 'failed' WHERE schema_version_id = ?",
                (blocked_id,),
            )
        else:
            conn.execute(
                "UPDATE extraction_runs SET extractor_model = 'other' "
                "WHERE schema_version_id = ?", (blocked_id,),
            )
    scope = None if selection == "default" else selected

    if blocked_id in selected:
        with pytest.raises(IncompleteExtractionError) as error:
            build_pack(kg, packs, "blocked", schema_version_ids=scope)
        summary = error.value.summary
        assert summary["relevant_stream_count"] == len(selected)
        blockers = summary["unknown_streams"] + summary["incomplete_streams"]
        assert {row["schema_version_id"] for row in blockers} == {blocked_id}
        assert not packs.exists()
    else:
        manifest = build_pack(kg, packs, "complete", schema_version_ids=scope)
        assert manifest.extraction_completeness is not None
        assert manifest.extraction_completeness["status"] == "complete"
        assert manifest.extraction_completeness["relevant_stream_count"] == 1


@pytest.mark.parametrize("selection", [(), (999999,)])
def test_invalid_version_selection_is_typed_and_unpublished(
    tmp_path: Path, selection: tuple[int, ...],
) -> None:
    kg, packs = tmp_path / "kg.sqlite", tmp_path / "packs"
    seed_two_versions(kg)

    with pytest.raises(SchemaVersionSelectionError) as error:
        build_pack(kg, packs, "invalid", schema_version_ids=selection)

    assert error.value.code == "invalid_schema_version_ids"
    assert error.value.schema_version_ids == selection
    assert not packs.exists()


@pytest.mark.parametrize("selection", ["default", "all", "old", "repeated"])
def test_cli_reports_the_versions_it_actually_publishes(tmp_path: Path, selection: str) -> None:
    kg, packs = tmp_path / "kg.sqlite", tmp_path / "packs"
    old, active = seed_two_versions(kg)
    flags = {
        "default": [], "all": ["--all-schema-versions"],
        "old": ["--schema-version", str(old)],
        "repeated": ["--schema-version", str(active), "--schema-version", str(old)],
    }[selection]
    expected = {"default": [active], "all": [old, active],
                "old": [old], "repeated": [old, active]}[selection]

    result = subprocess.run(
        [sys.executable, "-m", "ontologylab.main", "pack", "--name", selection,
         "--data-dir", str(tmp_path), "--packs-dir", str(packs), *flags],
        capture_output=True, text=True, timeout=30,
    )

    assert result.returncode == 0, result.stderr
    [pack] = list(packs.iterdir())
    manifest = json.loads((pack / "manifest.json").read_text())
    assert manifest["included_schema_version_ids"] == expected
    published = publication_versions(pack)
    assert published == {table: expected for table in published}
    assert json.dumps(expected) in result.stdout
    counts_start, counts_end = result.stdout.index("{"), result.stdout.rindex("}") + 1
    assert json.loads(result.stdout[counts_start:counts_end]) == manifest["counts"]


@pytest.mark.parametrize("flags", [
    ["--schema-version", "999999"],
    ["--schema-version", "1", "--all-schema-versions"],
])
def test_cli_refusal_never_reports_success(tmp_path: Path, flags: list[str]) -> None:
    packs = tmp_path / "packs"
    seed_two_versions(tmp_path / "kg.sqlite")

    result = subprocess.run(
        [sys.executable, "-m", "ontologylab.main", "pack", "--name", "invalid",
         "--data-dir", str(tmp_path), "--packs-dir", str(packs), *flags],
        capture_output=True, text=True, timeout=30,
    )

    assert result.returncode == 2
    assert result.stdout == ""
    assert not packs.exists()
    expected = "not allowed with argument" if "--all-schema-versions" in flags else "invalid_schema_version_ids"
    assert expected in result.stderr
