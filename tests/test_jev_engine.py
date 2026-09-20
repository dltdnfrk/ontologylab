"""JevEngine: the decision-engine adapter for TypeSafe Jev (kind="jev").

Offline tests — the urllib POST helper is monkeypatched, no provider is ever
contacted. The contract under test: judge() sends one Noul question per item
against a shared state, returns {id: {score, rationale}} on the critic's
advisory 0..1 scale, and generate() refuses loudly because Jev cannot
produce text.
"""

from __future__ import annotations

import asyncio

import pytest

import ontologylab.engines as engines
from ontologylab.critic import JEV_CRITIC_PROMPT_VERSION, critic_review
from ontologylab.engines import EngineError, JevEngine, get_engine
from ontologylab.providers import Provider, add_provider
from tests.conftest import insert, make_entity, make_relation

_KEY = "jev-test-key-do-not-leak"


def _jev() -> Provider:
    return Provider(
        id="typesafe",
        kind="jev",
        base_url="https://api.typesafe.ai/v1",
        api_key_env="TYPESAFE_API_KEY",
        models=("jev-latest",),
    )


def _capture(monkeypatch, response):
    """Monkeypatch the POST helper; return a dict that records the call args."""
    seen: dict = {}

    def fake_post(url, headers, payload, timeout_s):
        seen["url"] = url
        seen["headers"] = headers
        seen["payload"] = payload
        return response

    monkeypatch.setattr(engines, "_http_post_json", fake_post)
    return seen


def _noul_response(scores: dict[str, float]) -> dict:
    return {
        "model": "jev-latest",
        "answers": {
            qid: {"type": "noul", "noul": p} for qid, p in scores.items()
        },
        "usage": {"input_tokens": 10, "output_tokens": 4},
    }


def test_judge_sends_one_noul_per_item_against_shared_state(monkeypatch):
    monkeypatch.setenv("TYPESAFE_API_KEY", _KEY)
    seen = _capture(monkeypatch, _noul_response({"n1": 0.9, "n2": 0.2}))
    items = [
        {"id": "n1", "kind": "node", "type": "Component",
         "label": "RateLimiter", "evidence": ">>>RateLimiter<<<"},
        {"id": "n2", "kind": "node", "type": "Component",
         "label": "SuspiciousFragment", "evidence": ">>>frag<<<"},
    ]
    out = asyncio.run(JevEngine(_jev()).judge(items))

    assert seen["url"] == "https://api.typesafe.ai/v1/systemone"
    assert seen["headers"]["Authorization"] == f"Bearer {_KEY}"
    body = seen["payload"]
    assert body["model"] == "jev-latest"
    assert body["state"]["items"] == items
    assert set(body["questions"]) == {"n1", "n2"}
    assert all(q["type"] == "noul" for q in body["questions"].values())
    assert "n1" in body["questions"]["n1"]["instructions"]
    assert out == {
        "n1": {"score": 0.9, "rationale": None},
        "n2": {"score": 0.2, "rationale": None},
    }


def test_judge_drops_missing_and_malformed_answers(monkeypatch):
    monkeypatch.setenv("TYPESAFE_API_KEY", _KEY)
    _capture(
        monkeypatch,
        {
            "answers": {
                "n1": {"type": "noul", "noul": 1.7},   # clamped
                "n2": {"type": "choice", "choice": "x"},  # wrong type
                "n3": {"type": "noul", "noul": "high"},   # non-numeric
                # n4 absent entirely
            }
        },
    )
    items = [{"id": f"n{i}", "kind": "node", "type": "T",
              "label": f"L{i}", "evidence": "e"} for i in range(1, 5)]
    out = asyncio.run(JevEngine(_jev()).judge(items))
    assert out == {"n1": {"score": 1.0, "rationale": None}}


def test_judge_drops_nonfinite_noul(monkeypatch):
    """NaN/inf are not evidence — a non-finite answer is dropped, not clamped."""
    monkeypatch.setenv("TYPESAFE_API_KEY", _KEY)
    _capture(
        monkeypatch,
        {"answers": {"n1": {"type": "noul", "noul": float("nan")},
                     "n2": {"type": "noul", "noul": 0.5}}},
    )
    items = [{"id": f"n{i}", "kind": "node", "type": "T",
              "label": f"L{i}", "evidence": "e"} for i in (1, 2)]
    out = asyncio.run(JevEngine(_jev()).judge(items))
    assert out == {"n2": {"score": 0.5, "rationale": None}}


def test_judge_requires_a_key(monkeypatch):
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    with pytest.raises(EngineError, match="TYPESAFE_API_KEY"):
        asyncio.run(JevEngine(_jev()).judge(
            [{"id": "n1", "kind": "node", "type": "T",
              "label": "L", "evidence": "e"}]
        ))


def test_judge_rejects_a_missing_answers_object(monkeypatch):
    monkeypatch.setenv("TYPESAFE_API_KEY", _KEY)
    _capture(monkeypatch, {"model": "jev-latest"})
    with pytest.raises(EngineError, match="answers"):
        asyncio.run(JevEngine(_jev()).judge(
            [{"id": "n1", "kind": "node", "type": "T",
              "label": "L", "evidence": "e"}]
        ))


def test_generate_refuses_loudly():
    with pytest.raises(EngineError, match="cannot generate text"):
        asyncio.run(JevEngine(_jev()).generate("extract this"))


def test_get_engine_returns_jev_for_jev_kind(tmp_path, monkeypatch):
    add_provider(tmp_path, _jev())
    engine = get_engine("api:typesafe", data_dir=tmp_path)
    assert isinstance(engine, JevEngine)
    assert engine.name() == "api:typesafe"
    assert engine.critic_prompt_version == JEV_CRITIC_PROMPT_VERSION


def test_get_engine_rejects_decode_params_for_jev(tmp_path):
    add_provider(tmp_path, _jev())
    with pytest.raises(EngineError, match="sampling"):
        get_engine("api:typesafe", data_dir=tmp_path,
                   decode_params={"temperature": 0.2})


def test_critic_review_scores_via_judge_without_a_prompt(store, doc):
    """A judge-capable engine scores the same pending items and lands in the
    same critic_reviews stream — under its own prompt_version."""
    gateway = make_entity("ApiGateway")
    limiter = make_entity("RateLimiter")
    insert(store, doc, [gateway, limiter],
           [make_relation(gateway, limiter)])

    class FakeJudge:
        critic_prompt_version = JEV_CRITIC_PROMPT_VERSION

        def name(self):
            return "api:typesafe"

        async def judge(self, items, *, model=None):
            return {
                i["id"]: {"score": 0.42, "rationale": None} for i in items
            }

    stats = asyncio.run(critic_review(store, FakeJudge()))
    assert stats["scored"] == 3  # 2 nodes + 1 edge
    assert stats["batches_failed"] == 0
    rows = store.pending_review(order="critic")
    assert all(r["critic_score"] == 0.42 for r in rows)
    assert all(r["critic_engine"] == "api:typesafe" for r in rows)
