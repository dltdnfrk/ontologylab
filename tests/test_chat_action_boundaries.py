"""Entity HTTP/chat actions agree on stored facts, limits and refusals."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from ontologylab import enrichment, paths
from ontologylab.connectors.resources import (
    RESOURCE_ORDER,
    UNIPROT_RESOURCE,
    ResourceError,
    ResourceMatch,
)
from ontologylab.intent import Intent
from ontologylab.kgstore import KGStore, KGStoreError
from ontologylab.server.app import create_app
from tests.factories import make_entity

SECRET = "action-secret-must-not-surface-91ab"


@pytest.fixture
def data_dir(tmp_path: Path) -> Path:
    return tmp_path / "data"


@pytest.fixture
def client(tmp_path: Path, data_dir: Path) -> Iterator[TestClient]:
    with TestClient(create_app(
        data_dir=data_dir, packs_dir=tmp_path / "packs"
    )) as test_client:
        yield test_client


def _seed_node(data_dir: Path, name: str, *, verified: bool = False) -> str:
    store = KGStore.open(paths.kg_db_path(data_dir))
    try:
        doc, _ = store.insert_document(
            source_kind="upload", source_uri=f"file:///{name}.txt",
            title=name, raw_text=f"{name} appears here.", content_hash=name,
        )
        entity = make_entity(name)
        store.insert_proposed(
            [entity], [], source_doc_id=doc.id,
            extractor_engine="mock", prompt_version="extract-v1",
        )
        if verified:
            store.approve(entity.id)
        return entity.id
    finally:
        store.close()


def _classify(monkeypatch: pytest.MonkeyPatch, action: str, **params: str) -> None:
    async def classify(message, engine, model=None):
        return Intent(action, params=params, reading="action boundary")

    monkeypatch.setattr("ontologylab.intent.classify", classify)


def test_nonempty_search_matches_http_and_chat(client, monkeypatch, data_dir: Path) -> None:
    verified = _seed_node(data_dir, "RateLimiter", verified=True)
    proposed = _seed_node(data_dir, "RateLimiterCandidate")
    _classify(monkeypatch, "search_entities", query="RateLimiter")

    direct = client.get("/api/search", params={"q": "RateLimiter", "limit": 8})
    chat = client.post("/api/chat", json={"message": "find RateLimiter", "engine": "mock"})

    assert direct.status_code == chat.status_code == 200
    expected = [
        {"id": verified, "name": "RateLimiter", "entity_type": "Component",
         "status": "verified", "score": None},
        {"id": proposed, "name": "RateLimiterCandidate", "entity_type": "Component",
         "status": "proposed", "score": None},
    ]
    assert direct.json() == {"results": expected}
    body = chat.json()
    assert body["result"] == {"kind": "search", "query": "RateLimiter", "results": expected}
    assert body["steps"][-1] == {
        "tool": "store", "action": "search", "status": "ok", "detail": "2",
    }
    limited = client.get("/api/search", params={"q": "RateLimiter", "limit": 1})
    assert limited.json() == {"results": expected[:1]}


def test_search_applies_http_default_and_chat_limit_to_real_rows(client, monkeypatch, data_dir: Path) -> None:
    for index in range(12):
        _seed_node(data_dir, f"RateLimiter{index:02}")
    _classify(monkeypatch, "search_entities", query="RateLimiter")

    default = client.get("/api/search", params={"q": "RateLimiter"})
    all_rows = client.get("/api/search", params={"q": "RateLimiter", "limit": 25})
    chat = client.post("/api/chat", json={"message": "find RateLimiter", "engine": "mock"})

    assert len(all_rows.json()["results"]) == 12
    assert len(default.json()["results"]) == 8
    assert chat.json()["result"]["results"] == default.json()["results"]


def test_missing_search_is_empty_but_absent_query_is_blocked(client, monkeypatch, data_dir: Path) -> None:
    _seed_node(data_dir, "RateLimiter")
    _classify(monkeypatch, "search_entities", query="missing")
    direct = client.get("/api/search", params={"q": "missing"})
    chat = client.post("/api/chat", json={"message": "find missing", "engine": "mock"})
    assert direct.json() == {"results": []}
    assert chat.json()["result"] == {"kind": "search", "query": "missing", "results": []}

    _classify(monkeypatch, "search_entities", query=" ")
    blocked = client.post("/api/chat", json={"message": "find", "engine": "mock"}).json()
    assert blocked["result"]["kind"] == "blocked"
    assert blocked["result"]["error_kind"] == "shape"
    assert blocked["steps"][-1]["status"] == "failed"
    assert blocked["steps"][-1]["detail"] == "no_query"


@pytest.mark.parametrize("transport", ["http", "chat"])
def test_enrichment_proposes_only_for_verified_nodes(client, monkeypatch, transport, data_dir: Path) -> None:
    verified = _seed_node(data_dir, "BRCA1", verified=True)
    _seed_node(data_dir, "TP53")
    seen = []

    def lookup(resource, name):
        seen.append((resource, name))
        if resource != UNIPROT_RESOURCE:
            return None
        return ResourceMatch(
            resource=resource, external_id="P38398",
            record_url="https://www.uniprot.org/uniprotkb/P38398",
            matched_name="BRCA1", facts={"function": "E3 ubiquitin-protein ligase."},
        )

    monkeypatch.setattr(enrichment, "lookup", lookup)
    _classify(monkeypatch, "enrich")
    response = (
        client.post("/api/enrich", params={"limit": 1})
        if transport == "http"
        else client.post("/api/chat", json={"message": "enrich", "engine": "mock"})
    )
    assert response.status_code == 200
    body = response.json()
    report = body if transport == "http" else body["result"]
    assert report["ok"] is True
    assert report["nodes_considered"] == 1
    assert report["proposed"] == report["matched"] == 1
    assert report["lookups"] == len(RESOURCE_ORDER)
    assert report["failures"] == []
    assert seen == [(resource, "BRCA1") for resource in RESOURCE_ORDER]
    if transport == "chat":
        assert report["kind"] == "enrich"
        assert body["steps"][-1] == {
            "tool": "resources", "action": "lookup", "status": "ok", "detail": "1",
        }

    store = KGStore.open(paths.kg_db_path(data_dir))
    try:
        [annotation] = store.annotations_pending()
        assert annotation["node_id"] == verified
        assert annotation["resource"] == UNIPROT_RESOURCE
        assert annotation["status"] == "proposed"
        row = store.conn.execute(
            "SELECT status, properties_json FROM nodes WHERE id = ?", (verified,)
        ).fetchone()
        assert tuple(row) == ("verified", "{}")
    finally:
        store.close()


def test_empty_enrichment_agrees_across_http_and_chat(client, monkeypatch) -> None:
    def unexpected_lookup(*_args):
        raise AssertionError("an empty store must not access a resource")

    monkeypatch.setattr(enrichment, "lookup", unexpected_lookup)
    _classify(monkeypatch, "enrich")
    direct = client.post("/api/enrich").json()
    chat = client.post("/api/chat", json={"message": "enrich", "engine": "mock"}).json()

    assert direct["ok"] is True
    assert direct["nodes_considered"] == direct["lookups"] == direct["proposed"] == 0
    assert direct["failures"] == []
    assert chat["result"] == {"kind": "enrich", **direct}
    assert chat["steps"][-1]["status"] == "ok"


def test_enrichment_refusal_is_not_success(client, monkeypatch) -> None:
    def refuse(*_args, **_kwargs):
        raise ResourceError("lookup failed https://example.invalid/?key=" + SECRET)

    monkeypatch.setattr(enrichment, "enrich", refuse)
    _classify(monkeypatch, "enrich")
    direct = client.post("/api/enrich", params={"limit": 1})
    chat = client.post("/api/chat", json={"message": "enrich", "engine": "mock"})
    expected = {"ok": False, "error_kind": "failed", "detail": "enrichment failed: ResourceError"}

    assert direct.status_code == chat.status_code == 200
    assert direct.json() == expected
    assert SECRET not in direct.text + chat.text
    body = chat.json()
    assert body["result"] == {"kind": "blocked", **expected}
    assert body["steps"][-1] == {
        "tool": "resources", "action": "lookup", "status": "failed", "detail": "failed",
    }
    [turn] = client.get("/api/chat/history").json()["turns"]
    assert turn["result"] == body["result"]
    assert turn["steps"] == body["steps"]


@pytest.mark.parametrize(
    ("method", "path", "params"),
    [
        ("GET", "/api/search", {}),
        ("GET", "/api/search", {"q": ""}),
        ("GET", "/api/search", {"q": "x" * 201}),
        ("GET", "/api/search", {"q": "RateLimiter", "limit": 0}),
        ("GET", "/api/search", {"q": "RateLimiter", "limit": 26}),
        ("POST", "/api/enrich", {"limit": 0}),
        ("POST", "/api/enrich", {"limit": 501}),
    ],
)
def test_http_parameter_validation_remains_at_the_adapter(client, method, path, params) -> None:
    response = client.request(method, path, params=params)
    assert response.status_code == 422
    assert response.json()["detail"]
    assert all("input" not in item and "ctx" not in item for item in response.json()["detail"])


def test_search_domain_failure_remains_an_empty_result(client, monkeypatch) -> None:
    def fail_query(*_args, **_kwargs):
        raise KGStoreError(SECRET)

    monkeypatch.setattr(KGStore, "name_search", fail_query)
    _classify(monkeypatch, "search_entities", query="RateLimiter")
    direct = client.get("/api/search", params={"q": "RateLimiter"})
    chat = client.post("/api/chat", json={"message": "find", "engine": "mock"})
    assert direct.status_code == chat.status_code == 200
    assert direct.json() == {"results": []}
    assert chat.json()["result"]["results"] == []
    assert SECRET not in direct.text + chat.text


@pytest.mark.parametrize("action", ["search_entities", "enrich"])
@pytest.mark.parametrize(
    ("message", "status", "kind"),
    [("database is locked", 503, "busy"), ("no such table", 500, "storage")],
)
def test_store_open_failures_keep_http_middleware_contract(
    client, monkeypatch, action, message, status, kind
) -> None:
    def fail_open(_cls, *_args, **_kwargs):
        raise sqlite3.OperationalError(message + " " + SECRET)

    monkeypatch.setattr(KGStore, "open", classmethod(fail_open))
    _classify(monkeypatch, action, query="RateLimiter")
    direct = (
        client.get("/api/search", params={"q": "RateLimiter"})
        if action == "search_entities" else client.post("/api/enrich")
    )
    chat = client.post("/api/chat", json={"message": "act", "engine": "mock"})
    for response in (direct, chat):
        assert response.status_code == status
        assert response.json()["ok"] is False
        assert response.json()["error_kind"] == kind
        assert SECRET not in response.text
        assert response.headers.get("Retry-After") == ("2" if status == 503 else None)
