"""Offline smoke test for the ontologylab local web server."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_ROOT = str(Path(__file__).resolve().parent.parent)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

try:
    from fastapi.testclient import TestClient
except ImportError:  # pragma: no cover
    TestClient = None  # type: ignore[assignment]

if TestClient is None:
    pytest.skip("fastapi is not installed", allow_module_level=True)

from ontologylab.kgstore import KGStore  # noqa: E402
from ontologylab.models import ProposedEntity  # noqa: E402
from ontologylab.server.app import create_app  # noqa: E402


def _client(tmp_path: Path) -> TestClient:
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    store = KGStore.open(data_dir / "kg.sqlite")
    doc, _ = store.insert_document(
        source_kind="upload",
        source_uri="file:///t.txt",
        title="t",
        raw_text="Alpha component",
        content_hash="srv-h1",
    )
    store.insert_proposed(
        [ProposedEntity(id="n_alpha", entity_type="Component", name="Alpha")],
        [],
        source_doc_id=doc.id,
        extractor_engine="mock",
    )
    store.close()
    return TestClient(create_app(data_dir=data_dir))


def test_engines_lists_mock(tmp_path: Path) -> None:
    client = _client(tmp_path)
    resp = client.get("/api/engines")
    assert resp.status_code == 200
    by_name = {e["name"]: e for e in resp.json()}
    assert by_name["mock"]["available"] is True


def test_settings_and_cost(tmp_path: Path) -> None:
    client = _client(tmp_path)
    assert client.get("/api/settings").status_code == 200
    assert client.get("/api/cost").status_code == 200


def test_proposals_list_approve_reject(tmp_path: Path) -> None:
    client = _client(tmp_path)
    listed = client.get("/api/proposals")
    assert listed.status_code == 200
    body = listed.json()
    assert body["count"] >= 1
    item_id = body["items"][0]["id"]

    # second proposed node for reject path
    from ontologylab.paths import kg_db_path

    data_dir = tmp_path / "data"
    store = KGStore.open(kg_db_path(data_dir))
    doc = store.list_documents()[0]
    store.insert_proposed(
        [ProposedEntity(id="n_beta", entity_type="Concept", name="Beta")],
        [],
        source_doc_id=doc.id,
        extractor_engine="mock",
    )
    store.close()

    ok = client.post("/api/proposals/approve", json={"id": item_id})
    assert ok.status_code == 200
    assert ok.json()["ok"] is True

    rej = client.post("/api/proposals/reject", json={"id": "n_beta"})
    assert rej.status_code == 200

    after = client.get("/api/proposals").json()
    ids = {i["id"] for i in after["items"]}
    assert item_id not in ids
    assert "n_beta" not in ids


def test_index_serves_html(tmp_path: Path) -> None:
    client = _client(tmp_path)
    resp = client.get("/")
    assert resp.status_code == 200
    assert "ontologylab" in resp.text.lower()
