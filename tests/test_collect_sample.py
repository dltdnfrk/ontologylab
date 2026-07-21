"""POST /api/collect/sample — bundled onboarding document (따라하기 step 1).

Pins: offline static ingest, idempotence on content_hash, and that the
bundled text is actually extractable by the mock engine (CamelCase-rich),
so the onboarding journey can fill the review queue without network.
"""

from __future__ import annotations

from pathlib import Path

import pytest


def _client(tmp_path: Path):
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from ontologylab.server.app import create_app

    return TestClient(
        create_app(data_dir=tmp_path / "data", packs_dir=tmp_path / "packs")
    )


def test_sample_collect_is_idempotent(tmp_path):
    client = _client(tmp_path)

    first = client.post("/api/collect/sample")
    assert first.status_code == 200
    body = first.json()
    assert body["ok"] is True and body["created"] is True
    assert body["title"].startswith("샘플")

    again = client.post("/api/collect/sample")
    assert again.json()["created"] is False  # same content hash → dedup
    assert again.json()["document_id"] == body["document_id"]

    docs = client.get("/api/documents").json()["documents"]
    assert len(docs) == 1
    assert docs[0]["source_uri"] == "sample://onboarding/order-system"


def test_sample_doc_extracts_with_mock_engine(tmp_path):
    from ontologylab.kgstore import KGStore
    from ontologylab.main import main
    from ontologylab.paths import kg_db_path

    client = _client(tmp_path)
    assert client.post("/api/collect/sample").json()["ok"] is True

    with pytest.raises(SystemExit) as exc:
        main([
            "extract", "--engine", "mock",
            "--data-dir", str(tmp_path / "data"),
        ])
    assert exc.value.code == 0

    store = KGStore.open(kg_db_path(tmp_path / "data"), read_only=True)
    try:
        names = {
            r["name"]
            for r in store.conn.execute(
                "SELECT name FROM nodes WHERE status='proposed'"
            ).fetchall()
        }
    finally:
        store.close()
    # the sample is written so mock's CamelCase extractor finds real entities
    assert {"OrderApp", "KitchenDisplay", "PaymentGateway"} <= names
