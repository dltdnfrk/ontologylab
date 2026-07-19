"""Working-DB contention must surface as a retryable 503, never a raw 500.

The extraction job (server/jobs.py) writes data/kg.sqlite from a daemon
thread while dashboard requests write the same file. WAL + sqlite's busy
timeout serialize them, but a write that waits out the timeout raises
OperationalError("database is locked"). Before this handler existed that
escaped as an unhandled 500 with a raw sqlite message.
"""

from __future__ import annotations

import sqlite3
import threading

import pytest

from ontologylab.kgstore import KGStore
from ontologylab.paths import kg_db_path

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from ontologylab.server.app import create_app  # noqa: E402


@pytest.fixture()
def client(tmp_path):
    app = create_app(data_dir=tmp_path / "data", packs_dir=tmp_path / "packs")
    with TestClient(app) as tc:
        yield tc


def test_locked_database_returns_retryable_503(client, monkeypatch):
    def locked(self, **kwargs):
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(KGStore, "pending_review", locked)
    res = client.get("/api/proposals")

    assert res.status_code == 503
    assert res.headers.get("Retry-After") == "2"
    body = res.json()
    assert body["ok"] is False and body["error_kind"] == "busy"
    assert "busy" in body["detail"].lower()
    # the raw sqlite phrasing is not echoed at the user
    assert "database is locked" not in body["detail"].lower()


def test_other_operational_errors_are_redacted_500(client, monkeypatch):
    """A genuine fault must not leak table/column names to the client."""
    def broken(self, **kwargs):
        raise sqlite3.OperationalError("no such column: nodes.secret_column")

    monkeypatch.setattr(KGStore, "pending_review", broken)
    res = client.get("/api/proposals")

    assert res.status_code == 500
    body = res.json()
    assert body["error_kind"] == "storage"
    assert "secret_column" not in body["detail"]
    assert "nodes" not in body["detail"]


def test_write_route_contention_also_handled(client, monkeypatch):
    """Not just reads — an approve landing mid-extraction gets the same 503."""
    def locked(self, *args, **kwargs):
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(KGStore, "approve", locked)
    res = client.post("/api/proposals/approve", json={"id": "whatever"})

    assert res.status_code == 503
    assert res.json()["error_kind"] == "busy"


def test_concurrent_writers_do_not_corrupt_the_store(tmp_path):
    """Two real threads writing the same working DB must both land their rows
    (WAL + busy timeout), not raise or lose data."""
    db = kg_db_path(tmp_path / "data")
    seed = KGStore.open(db)
    doc, _ = seed.insert_document(
        source_kind="upload", source_uri="file:///x", title="x",
        raw_text="contention probe", content_hash="sha256:conc",
    )
    doc_id = doc.id
    seed.close()

    errors: list[BaseException] = []

    def writer(tag: str) -> None:
        # sqlite connections are thread-bound: open fresh inside the thread,
        # exactly like server/jobs.py does.
        store = KGStore.open(db)
        try:
            for i in range(12):
                store.insert_document(
                    source_kind="upload",
                    source_uri=f"file:///{tag}-{i}",
                    title=f"{tag}-{i}",
                    raw_text=f"row {tag} {i}",
                    content_hash=f"sha256:{tag}-{i}",
                )
        except BaseException as exc:  # noqa: BLE001 - recorded for assertion
            errors.append(exc)
        finally:
            store.close()

    threads = [threading.Thread(target=writer, args=(t,)) for t in ("a", "b")]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert errors == []
    check = KGStore.open(db)
    try:
        # 1 seed + 12 + 12, all durable
        assert len(check.list_documents()) == 25
        assert check.get_document(doc_id).title == "x"
    finally:
        check.close()
