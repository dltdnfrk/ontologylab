"""W8 critic triage: advisory pre-scores sort the queue, never decide it."""

from __future__ import annotations

import asyncio

import pytest

from ontologylab.critic import (
    CRITIC_PROMPT_VERSION,
    build_critic_prompt,
    critic_review,
    parse_critic,
    resolve_critic_model,
)
from ontologylab.engines import EngineError, MockEngine
from ontologylab.paths import CRITIC_MODEL, DEFAULT_MODEL
from tests.conftest import insert, make_entity, make_relation


def run(coro):
    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# Critic model tier: advisory triage runs on the cheap Haiku-class model
# ---------------------------------------------------------------------------


def test_resolve_critic_model_defaults_claude_to_cheap_tier():
    # claude engine, no explicit model -> cheap CRITIC_MODEL (not the anchor)
    assert resolve_critic_model("claude", None) == CRITIC_MODEL
    assert CRITIC_MODEL != DEFAULT_MODEL  # it is genuinely a different tier


def test_resolve_critic_model_explicit_always_wins():
    assert resolve_critic_model("claude", "claude-opus-4-8") == "claude-opus-4-8"
    assert resolve_critic_model("mock", "whatever") == "whatever"


def test_resolve_critic_model_leaves_other_engines_alone():
    # non-claude engines resolve their own default (None = engine's default)
    for engine in ("mock", "codex", "gemini"):
        assert resolve_critic_model(engine, None) is None


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


def test_an_uncited_proposal_is_never_sent_to_the_critic(store, doc):
    """The load-bearing one.

    The extractor mints an entity the model named but the source text never
    contained, and marks it by withholding the span; every edge touching
    that endpoint loses its span too. Such an item has no evidence, and this
    critic scores evidence support — there is nothing for it to read.

    Asked anyway, the model does not decline. It answers "no evidence
    provided" and, following a rubric whose lowest band is "evidence
    contradicts it", scores 0.1. That is the same value it gives an
    extraction the evidence flatly refutes, so `order="critic"` interleaves
    the two and the queue reports "suspect" about items nobody could look
    at. Measured on the live store: of 26 items below 0.4, 23 were merely
    un-cited and 3 were real judgements.

    So they are held back before the call — no tokens spent manufacturing a
    verdict — and counted, because a silent drop would read as "clean run".
    """
    cited = make_entity("RateLimiter")
    uncited = make_entity("GhostConcept", source_span=None)
    insert(store, doc, [cited, uncited])

    stats = run(critic_review(store, MockEngine()))

    # Counted as a candidate: it *is* pending review, just not judgeable here.
    assert stats["candidates"] == 2
    assert stats["scored"] == 1
    assert stats["skipped_uncited"] == 1

    scored = {r["label"]: r for r in store.pending_review()}
    assert scored["RateLimiter"]["critic_score"] is not None
    # No score at all — not a low one. A reviewer sorting by critic score
    # must not find this sitting next to a genuine contradiction.
    assert scored["GhostConcept"]["critic_score"] is None
    assert scored["GhostConcept"]["critic_rationale"] is None


def test_an_uncited_proposal_still_reaches_the_human_queue(store, doc):
    """Skipping the critic must not skip the review.

    Nothing becomes knowledge without someone approving it, and an un-cited
    proposal is exactly the kind a person should see — the UI tells them the
    name never appeared in the source. Dropping it from `pending_review` to
    keep the critic's numbers tidy would approve it by omission.
    """
    insert(store, doc, [make_entity("GhostConcept", source_span=None)])
    run(critic_review(store, MockEngine()))

    rows = store.pending_review()

    assert [r["label"] for r in rows] == ["GhostConcept"]
    assert rows[0]["source_span"] is None  # what the UI keys its warning on
    assert not (rows[0]["excerpt"] or "").strip()


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


def test_critic_surfaces_unloadable_docs(store, doc, monkeypatch):
    """A failed document-text load must be visible in stats, not silent.

    Fail-open used to mean "score them anyway": the run completed and wrote
    four scores derived from blank evidence. That kept the run alive at the
    cost of the numbers — a missing raw.txt came back looking like four
    doubtful extractions, indistinguishable from four the evidence actually
    refuted. Fail-open now means the run completes and the items are left
    unscored; `docs_unloadable` still carries the degradation, which is what
    this test was always about.
    """
    _seed(store, doc)

    def boom(_doc_id):
        raise OSError("raw-text file missing")

    monkeypatch.setattr(store, "document_raw_text", boom)

    stats = run(critic_review(store, MockEngine()))
    # The run completes and does not raise — that is the fail-open part.
    assert stats["candidates"] == 4
    assert stats["batches_failed"] == 0
    # No verdict is invented about evidence nobody could read.
    assert stats["scored"] == 0
    assert stats["skipped_uncited"] == 4
    # ...and the degradation is surfaced, not swallowed. `skipped_uncited`
    # alone would read as "the extractor omitted spans"; this says otherwise.
    assert stats["docs_unloadable"] == [doc.id]


def test_docs_unloadable_empty_when_all_docs_load(store, doc):
    _seed(store, doc)
    stats = run(critic_review(store, MockEngine()))
    assert stats["docs_unloadable"] == []


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
