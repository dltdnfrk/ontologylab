"""W11 entity-centric review: one entity's mentions + relations in one view."""

from __future__ import annotations

import pytest

from ontologylab.kgstore import KGStore, KGStoreError, UnknownItem, span_excerpt
from tests.conftest import insert, make_entity, make_relation


def _ids(store: KGStore, *names: str) -> list[str]:
    return [
        store.conn.execute(
            "SELECT id FROM nodes WHERE name = ?", (name,)
        ).fetchone()["id"]
        for name in names
    ]


def _seed(store, doc):
    gateway = make_entity("ApiGateway")
    limiter = make_entity("RateLimiter", aliases=["limiter"])
    cache = make_entity("SessionCache")
    insert(
        store, doc,
        [gateway, limiter, cache],
        [make_relation(gateway, limiter),          # in-edge for limiter
         make_relation(limiter, cache)],           # out-edge for limiter
    )
    return _ids(store, "ApiGateway", "RateLimiter", "SessionCache")


# ---------------------------------------------------------------------------
# span_excerpt (shared helper)
# ---------------------------------------------------------------------------


def test_span_excerpt_marks_span_and_bounds():
    text = "The ApiGateway forwards requests to the RateLimiter downstream."
    excerpt = span_excerpt(text, {"start": 4, "end": 14}, context_chars=8)
    assert ">>>ApiGateway<<<" in excerpt
    assert excerpt.startswith("The ")
    assert span_excerpt(text, None) == ""
    assert span_excerpt("", {"start": 0, "end": 3}) == ""
    assert span_excerpt(text, {"start": 10, "end": 5}) == ""


# ---------------------------------------------------------------------------
# entity_review_context
# ---------------------------------------------------------------------------


def test_context_bundles_mentions_relations_directions(store, doc):
    _gw, limiter_id, _c = _seed(store, doc)
    ctx = store.entity_review_context(limiter_id)

    assert ctx["entity"]["name"] == "RateLimiter"
    assert ctx["counts"]["mentions"] == 1
    mention = ctx["mentions"][0]
    assert ">>>" in mention["excerpt"] and "<<<" in mention["excerpt"]
    assert mention["doc_title"] == "notes"

    assert ctx["counts"]["relations_proposed"] == 2
    by_dir = {r["direction"]: r for r in ctx["relations"]}
    assert by_dir["in"]["other"]["name"] == "ApiGateway"
    assert by_dir["out"]["other"]["name"] == "SessionCache"
    assert all(r["other"]["status"] == "proposed" for r in ctx["relations"])


def test_context_counts_second_mention(store, doc):
    _gw, limiter_id, _c = _seed(store, doc)
    doc2, _ = store.insert_document(
        source_kind="upload", source_uri="file:///other.md", title="other",
        raw_text="RateLimiter again", content_hash="sha256:other",
    )
    insert(store, doc2, [make_entity("RateLimiter")])
    ctx = store.entity_review_context(limiter_id)
    assert ctx["counts"]["mentions"] == 2
    assert {m["doc_title"] for m in ctx["mentions"]} == {"notes", "other"}


def test_context_excludes_rejected_relations(store, doc):
    _gw, limiter_id, _c = _seed(store, doc)
    edge_id = store.conn.execute("SELECT id FROM edges LIMIT 1").fetchone()["id"]
    store.reject(edge_id, by="tester")
    ctx = store.entity_review_context(limiter_id)
    assert len(ctx["relations"]) == 1
    assert all(r["id"] != edge_id for r in ctx["relations"])


def test_context_attaches_critic_and_merge_candidates(store, doc):
    import asyncio

    from ontologylab.critic import critic_review
    from ontologylab.engines import MockEngine
    from ontologylab.merge import scan_merge_candidates

    _gw, limiter_id, _c = _seed(store, doc)
    insert(store, doc, [make_entity("RateLimiterz")])
    asyncio.run(critic_review(store, MockEngine()))
    scan_merge_candidates(store)

    ctx = store.entity_review_context(limiter_id)
    assert ctx["critic"]["score"] == 0.9 and ctx["critic"]["engine"] == "mock"
    assert all(r["critic_score"] is not None for r in ctx["relations"])
    (cand,) = ctx["merge_candidates"]
    assert cand["other"]["name"] == "RateLimiterz"
    assert cand["reasons"]


def test_context_rejects_edge_ids_and_unknown(store, doc):
    _seed(store, doc)
    edge_id = store.conn.execute("SELECT id FROM edges LIMIT 1").fetchone()["id"]
    with pytest.raises(KGStoreError, match="nodes"):
        store.entity_review_context(edge_id)
    with pytest.raises(UnknownItem):
        store.entity_review_context("no-such-id")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def test_cli_entity_by_name(store, doc, tmp_path, capsys):
    from ontologylab.main import main

    _seed(store, doc)
    data_dir = str(store.db_path.parent)
    with pytest.raises(SystemExit) as exc:
        main(["entity", "RateLimiter", "--data-dir", data_dir])
    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert "RateLimiter  [Component/proposed]" in out
    assert "MENTIONS (1):" in out
    assert "-[uses]-> SessionCache" in out
    assert "<-[uses]- ApiGateway" in out


def test_cli_entity_unknown_name(store, doc, capsys):
    from ontologylab.main import main

    _seed(store, doc)
    with pytest.raises(SystemExit) as exc:
        main(["entity", "NoSuchThing",
              "--data-dir", str(store.db_path.parent)])
    assert exc.value.code == 2


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------


@pytest.fixture()
def client(tmp_path):
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from ontologylab.server.app import create_app

    app = create_app(data_dir=tmp_path / "data", packs_dir=tmp_path / "packs")
    with TestClient(app) as tc:
        yield tc


def test_entity_review_api(client, tmp_path):
    from ontologylab.paths import kg_db_path

    store = KGStore.open(kg_db_path(tmp_path / "data"))
    doc, _ = store.insert_document(
        source_kind="upload", source_uri="file:///x", title="x",
        raw_text="ApiGateway uses RateLimiter", content_hash="sha256:x",
    )
    gateway = make_entity("ApiGateway")
    limiter = make_entity("RateLimiter")
    insert(store, doc, [gateway, limiter], [make_relation(gateway, limiter)])
    limiter_id = _ids(store, "RateLimiter")[0]
    edge_id = store.conn.execute("SELECT id FROM edges LIMIT 1").fetchone()["id"]
    store.close()

    res = client.get(f"/api/entity/{limiter_id}/review")
    assert res.status_code == 200
    ctx = res.json()
    assert ctx["entity"]["name"] == "RateLimiter"
    assert ctx["relations"][0]["direction"] == "in"

    assert client.get("/api/entity/nope/review").status_code == 404
    assert client.get(f"/api/entity/{edge_id}/review").status_code == 400
