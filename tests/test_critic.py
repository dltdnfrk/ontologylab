"""W8 critic triage: advisory pre-scores sort the queue, never decide it."""

from __future__ import annotations

import asyncio

import pytest

from ontologylab.critic import (
    CRITIC_PROMPT_VERSION,
    build_critic_prompt,
    critic_review,
    parse_critic,
)
from ontologylab.engines import EngineError, MockEngine
from tests.conftest import insert, make_entity, make_relation


def run(coro):
    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------


def test_parse_critic_validates_and_clamps():
    raw = """```json
[
  {"id": "a", "score": 0.8, "rationale": "supported"},
  {"id": "b", "score": 1.7},
  {"id": "unknown", "score": 0.5},
  {"id": "c", "score": "high"},
  "not-an-object"
]
```"""
    reviews = parse_critic(raw, {"a", "b", "c"})
    assert reviews["a"] == {"score": 0.8, "rationale": "supported"}
    assert reviews["b"]["score"] == 1.0  # clamped
    assert "unknown" not in reviews
    assert "c" not in reviews  # non-numeric score dropped


def test_parse_critic_rejects_garbage():
    with pytest.raises(EngineError):
        parse_critic("no fence here", {"a"})
    with pytest.raises(EngineError):
        parse_critic("```json\n{\"not\": \"a list\"}\n```", {"a"})


# ---------------------------------------------------------------------------
# Mock engine round trip
# ---------------------------------------------------------------------------


def test_mock_engine_scores_critic_prompt():
    items = [
        {"id": "n1", "kind": "node", "type": "Component",
         "label": "RateLimiter", "confidence": 0.9, "evidence": "..."},
        {"id": "n2", "kind": "node", "type": "Component",
         "label": "SuspiciousFragment", "confidence": 0.9, "evidence": "..."},
    ]
    raw, _usage = run(MockEngine().generate(build_critic_prompt(items)))
    reviews = parse_critic(raw, {"n1", "n2"})
    assert reviews["n1"]["score"] == 0.9
    assert reviews["n2"]["score"] == 0.15


# ---------------------------------------------------------------------------
# critic_review pipeline
# ---------------------------------------------------------------------------


def _seed(store, doc):
    gateway = make_entity("ApiGateway")
    suspicious = make_entity("SuspiciousFragment")
    limiter = make_entity("RateLimiter")
    insert(store, doc, [gateway, suspicious, limiter],
           [make_relation(gateway, limiter)])
    return gateway, suspicious, limiter


def test_critic_review_scores_and_flags_disagreement(store, doc):
    _seed(store, doc)
    stats = run(critic_review(store, MockEngine()))
    assert stats["candidates"] == 4  # 3 nodes + 1 edge
    assert stats["scored"] == 4
    assert stats["disagreements"] == 1  # conf 0.9 vs critic 0.15
    assert stats["batches_failed"] == 0

    rows = store.pending_review(order="critic")
    # lowest critic score first
    assert rows[0]["label"] == "SuspiciousFragment"
    assert rows[0]["critic_score"] == 0.15
    assert rows[0]["critic_disagreement"] is True
    assert rows[0]["critic_engine"] == "mock"
    assert all(r["critic_score"] is not None for r in rows)
    assert sum(1 for r in rows if r["critic_disagreement"]) == 1


def test_critic_review_is_idempotent_per_engine(store, doc):
    _seed(store, doc)
    run(critic_review(store, MockEngine()))
    stats = run(critic_review(store, MockEngine()))
    assert stats["candidates"] == 0 and stats["scored"] == 0


def test_critic_never_changes_status(store, doc):
    _seed(store, doc)
    before = store.counts()
    run(critic_review(store, MockEngine()))
    after = store.counts()
    assert before == after  # advisory only: zero status transitions
    assert after["nodes_verified"] == 0 and after["nodes_rejected"] == 0


def test_critic_fails_open_on_engine_error(store, doc):
    _seed(store, doc)

    class ExplodingEngine:
        def name(self):
            return "exploding"

        async def generate(self, prompt, *, model=None):
            raise EngineError("boom")

    stats = run(critic_review(store, ExplodingEngine()))
    assert stats["scored"] == 0
    assert stats["batches_failed"] >= 1
    assert stats["errors"]
    # queue still works, just unscored
    rows = store.pending_review(order="critic")
    assert all(r["critic_score"] is None for r in rows)


def test_unscored_items_sort_last_in_critic_order(store, doc):
    _seed(store, doc)
    run(critic_review(store, MockEngine(), limit=1))  # score only first node
    rows = store.pending_review(order="critic")
    assert rows[0]["critic_score"] is not None
    assert rows[-1]["critic_score"] is None


def test_edge_labels_use_endpoint_names(store, doc):
    from ontologylab.critic import _pending_items

    _seed(store, doc)
    items = _pending_items(store, engine_name="mock", limit=10)
    edge_items = [i for i in items if i["kind"] == "edge"]
    assert len(edge_items) == 1
    assert "ApiGateway" in edge_items[0]["label"]
    assert "RateLimiter" in edge_items[0]["label"]


def test_evidence_excerpt_marks_span(store, doc):
    from ontologylab.critic import _pending_items

    insert(store, doc, [make_entity("ApiGateway",
                                    source_span=None)])
    # span-less rows still produce an item, with empty evidence
    items = _pending_items(store, engine_name="mock", limit=10)
    assert items[0]["evidence"] == ""


def test_rescoring_upserts_single_row(store, doc):
    _seed(store, doc)
    node_id = store.conn.execute(
        "SELECT id FROM nodes WHERE name = 'RateLimiter'"
    ).fetchone()["id"]
    store.record_critic_review(
        "node", node_id, engine="mock", model=None,
        prompt_version=CRITIC_PROMPT_VERSION, score=0.4, rationale="first",
    )
    store.record_critic_review(
        "node", node_id, engine="mock", model=None,
        prompt_version=CRITIC_PROMPT_VERSION, score=0.6, rationale="second",
    )
    rows = store.conn.execute(
        "SELECT * FROM critic_reviews WHERE item_id = ?", (node_id,)
    ).fetchall()
    assert len(rows) == 1 and rows[0]["score"] == 0.6


# ---------------------------------------------------------------------------
# API surface
# ---------------------------------------------------------------------------


@pytest.fixture()
def client(tmp_path):
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from ontologylab.server.app import create_app

    app = create_app(data_dir=tmp_path / "data", packs_dir=tmp_path / "packs")
    with TestClient(app) as tc:
        yield tc


def test_critic_api_run_and_order(client, tmp_path):
    from ontologylab.kgstore import KGStore
    from ontologylab.paths import kg_db_path

    store = KGStore.open(kg_db_path(tmp_path / "data"))
    doc, _ = store.insert_document(
        source_kind="upload", source_uri="file:///x", title="x",
        raw_text="ApiGateway SuspiciousFragment", content_hash="sha256:x",
    )
    insert(store, doc, [make_entity("ApiGateway"),
                        make_entity("SuspiciousFragment")])
    store.close()

    res = client.post("/api/critic/run", json={"engine": "mock"})
    assert res.status_code == 200
    body = res.json()
    assert body["ok"] is True and body["scored"] == 2

    res = client.get("/api/proposals?order=critic")
    items = res.json()["items"]
    assert items[0]["label"] == "SuspiciousFragment"
    assert items[0]["critic_disagreement"] is True
