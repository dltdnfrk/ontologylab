"""Wave 2.1 Step 3 (3C): work serializer + additive /api/works/{id} route.

The serializer is a pure on-read projection: nothing about the preferred
Representation is stored, and the old /api/documents shape is untouched.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from ontologylab.authority_repo import attach_identifier, create_work, record_redirect
from ontologylab.kgstore import KGStore
from ontologylab.work_view import WorkNotFound, work_snapshot


def _work_with_representations(store: KGStore, tmp_path: Path) -> str:
    create_work(store.conn, "work-a")
    for doc_id, body, stage, kind in (
        ("rep-old", "the older abstract", "submitted", "abstract"),
        ("rep-new", "the newer full text body with more content", "published", "fulltext"),
    ):
        target = tmp_path / "documents" / doc_id
        target.mkdir(parents=True, exist_ok=True)
        (target / "raw.txt").write_text(body, encoding="utf-8")
        store.conn.execute(
            "INSERT INTO documents (id, source_kind, source_uri, title, "
            "fetched_ts, content_hash, raw_text_path, work_id, "
            "representation_state) "
            "VALUES (?, 'paper_api', ?, 'paper', 0.0, ?, ?, 'work-a', 'ready')",
            (
                doc_id,
                f"https://doi.org/10.5555/{doc_id}",
                f"sha256:{doc_id}",
                f"documents/{doc_id}/raw.txt",
            ),
        )
        attach_identifier(
            store.conn, work_id="work-a", scheme="doi",
            normalized_value="10.1000/view.a",
            idempotency_key=f"op-{doc_id}",
            representation_id=doc_id, source="crossref",
            evidence_grade="A", stage=stage, content_kind=kind,
        )
    store.conn.execute("COMMIT")
    return "work-a"


def test_snapshot_projects_work_identifiers_observations_and_preferred(
    tmp_path: Path,
) -> None:
    store = KGStore.open(tmp_path / "kg.sqlite")
    try:
        _work_with_representations(store, tmp_path)
        snap = work_snapshot(store.conn, "work-a")
        assert snap["work"]["id"] == "work-a"
        assert snap["work"]["state"] == "active"
        assert [i["normalized_value"] for i in snap["identifiers"]] == [
            "10.1000/view.a"
        ]
        assert len(snap["observations"]) == 2
        assert {r["doc_id"] for r in snap["representations"]} == {
            "rep-old", "rep-new",
        }
        # Hand-computed expectation: published fulltext outranks submitted
        # abstract under the fixed policy - NOT re-derived from the function.
        assert snap["preferred_representation_id"] == "rep-new"
    finally:
        store.close()


def test_preferred_is_computed_on_read_not_stored(tmp_path: Path) -> None:
    """A newly attached better Representation changes the projection: a
    stored pointer could not track this without a write."""
    store = KGStore.open(tmp_path / "kg.sqlite")
    try:
        _work_with_representations(store, tmp_path)
        assert work_snapshot(store.conn, "work-a")[
            "preferred_representation_id"
        ] == "rep-new"
        # Attach an even better candidate: published fulltext from the
        # registry with more bytes beats the current winner.
        target = tmp_path / "documents" / "rep-best"
        target.mkdir(parents=True, exist_ok=True)
        body = "x" * 100
        (target / "raw.txt").write_text(body, encoding="utf-8")
        store.conn.execute(
            "INSERT INTO documents (id, source_kind, source_uri, title, "
            "fetched_ts, content_hash, raw_text_path, work_id, "
            "representation_state) "
            "VALUES ('rep-best', 'paper_api', 'https://doi.org/10.5555/rep-best', "
            "'paper', 0.0, 'sha256:rep-best', 'documents/rep-best/raw.txt', "
            "'work-a', 'ready')"
        )
        attach_identifier(
            store.conn, work_id="work-a", scheme="doi",
            normalized_value="10.1000/view.a",
            idempotency_key="op-rep-best", representation_id="rep-best",
            source="crossref", evidence_grade="A",
            stage="published", content_kind="fulltext",
        )
        snap = work_snapshot(store.conn, "work-a")
        assert snap["preferred_representation_id"] == "rep-best"
    finally:
        store.close()


def test_work_without_representations_yields_null_preferred(
    tmp_path: Path,
) -> None:
    store = KGStore.open(tmp_path / "kg.sqlite")
    try:
        create_work(store.conn, "work-empty")
        snap = work_snapshot(store.conn, "work-empty")
        assert snap["representations"] == []
        assert snap["preferred_representation_id"] is None
    finally:
        store.close()


def test_unknown_work_raises_typed_not_found(tmp_path: Path) -> None:
    store = KGStore.open(tmp_path / "kg.sqlite")
    try:
        with pytest.raises(WorkNotFound):
            work_snapshot(store.conn, "no-such-work")
    finally:
        store.close()


def test_redirect_keeps_original_work_identifiers(tmp_path: Path) -> None:
    """Canonicalization is on read: a merge decision never rewrites the
    original Work's identifier FKs (D09)."""
    store = KGStore.open(tmp_path / "kg.sqlite")
    try:
        create_work(store.conn, "work-a")
        create_work(store.conn, "work-b")
        attach_identifier(
            store.conn, work_id="work-a", scheme="doi",
            normalized_value="10.1000/view.orig", idempotency_key="op-orig",
        )
        record_redirect(
            store.conn, source_work_id="work-a", target_work_id="work-b",
            action="merge", actor="qa", reason="dedupe a into b",
        )
        snap = work_snapshot(store.conn, "work-a")
        assert snap["identifiers"][0]["work_id"] == "work-a"
        assert snap["identifiers"][0]["normalized_value"] == "10.1000/view.orig"
        assert snap["work"]["state"] == "active"
    finally:
        store.close()


def test_api_works_route_serves_the_snapshot_and_typed_404(
    tmp_path: Path,
) -> None:
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from ontologylab.server.app import create_app

    data_dir = tmp_path / "data"
    store = KGStore.open(data_dir / "kg.sqlite")
    try:
        _work_with_representations(store, data_dir)
    finally:
        store.close()

    app = create_app(data_dir=data_dir, packs_dir=tmp_path / "packs")
    with TestClient(app) as client:
        res = client.get("/api/works/work-a")
        assert res.status_code == 200
        body = res.json()
        assert body["work"]["id"] == "work-a"
        assert body["preferred_representation_id"] == "rep-new"
        assert len(body["identifiers"]) == 1
        assert client.get("/api/works/nope").status_code == 404
