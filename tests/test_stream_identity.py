"""Stream identity: what produced a row, and scoring one producer at a time.

Two holes with one shape. A row records (engine, model, prompt_version) as
if that triple named the distribution it came from, but the decode
parameters were never sent — the provider's default temperature (1.0 for
both kinds) was silently in force, so the same triple meant different
samplers on different days. And the evaluation harness could not filter by
that triple at all, so two extractors writing into one store were scored
as one number.
"""

from __future__ import annotations

import asyncio
import json

import pytest

import ontologylab.engines as engines
from ontologylab.engines import ApiEngine
from ontologylab.evaluation import evaluate_store, load_gold, store_view
from ontologylab.providers import Provider
from tests.conftest import make_entity, make_relation

_KEY = "sk-live-do-not-leak"


def _anthropic() -> Provider:
    return Provider(
        id="anth",
        kind="anthropic",
        base_url="https://api.anthropic.com/v1",
        api_key_env="ANTH_KEY",
        models=("claude-fable-5",),
    )


def _openai() -> Provider:
    return Provider(
        id="orouter",
        kind="openai",
        base_url="https://openrouter.ai/api/v1",
        api_key_env="OR_KEY",
        models=("meta/llama",),
    )


def _capture(monkeypatch, response):
    seen: dict = {}

    def fake_post(url, headers, payload, timeout_s):
        seen["payload"] = payload
        return response

    monkeypatch.setattr(engines, "_http_post_json", fake_post)
    return seen


# ---------------------------------------------------------------------------
# Decode parameters
# ---------------------------------------------------------------------------


def test_anthropic_body_pins_the_sampling_temperature(monkeypatch) -> None:
    monkeypatch.setenv("ANTH_KEY", _KEY)
    seen = _capture(monkeypatch, {"content": [{"type": "text", "text": "x"}]})

    asyncio.run(ApiEngine(_anthropic()).generate("hi"))

    assert seen["payload"]["temperature"] == 0.0


def test_openai_body_pins_the_sampling_temperature(monkeypatch) -> None:
    monkeypatch.setenv("OR_KEY", _KEY)
    seen = _capture(
        monkeypatch,
        {"choices": [{"message": {"role": "assistant", "content": "x"}}]},
    )

    asyncio.run(ApiEngine(_openai()).generate("hi"))

    assert seen["payload"]["temperature"] == 0.0


def test_usage_meta_reports_the_decode_parameters_that_were_sent(
    monkeypatch,
) -> None:
    """Provenance records usage_meta verbatim, so the params must be in it.

    Recording the engine and model without the sampler is the gap: a run
    cannot be compared to another run whose temperature it does not know.
    """
    monkeypatch.setenv("ANTH_KEY", _KEY)
    _capture(monkeypatch, {"content": [{"type": "text", "text": "x"}]})

    _, usage = asyncio.run(ApiEngine(_anthropic()).generate("hi"))

    assert usage["decode_params"] == {"temperature": 0.0}


def test_decode_params_are_not_claimed_to_be_bit_determinism() -> None:
    """T=0 is a request, not a guarantee (batching, MoE routing, FP order).

    Pins the honesty of the name: the key says what was *requested*.
    """
    assert "requested" in engines.DECODE_PARAMS_NOTE.lower()


# ---------------------------------------------------------------------------
# Scoring one stream at a time
# ---------------------------------------------------------------------------


def _seed_two_streams(store, doc):
    """One entity+edge per extractor stream, disjoint names."""
    mock_a, mock_b = make_entity("MockAlpha"), make_entity("MockBeta")
    store.insert_proposed(
        [mock_a, mock_b],
        [make_relation(mock_a, mock_b, "uses")],
        source_doc_id=doc.id,
        extractor_engine="mock",
        extractor_model=None,
        prompt_version="extract-v1",
    )
    claude_a, claude_b = make_entity("ClaudeAlpha"), make_entity("ClaudeBeta")
    store.insert_proposed(
        [claude_a, claude_b],
        [make_relation(claude_a, claude_b, "uses")],
        source_doc_id=doc.id,
        extractor_engine="claude",
        extractor_model="claude-fable-5",
        prompt_version="extract-v2",
    )


def test_store_view_without_a_filter_still_sees_every_stream(store, doc) -> None:
    _seed_two_streams(store, doc)

    entities, triples = store_view(store)

    assert {"mockalpha", "mockbeta", "claudealpha", "claudebeta"} <= entities
    assert len(triples) == 2


def test_store_view_scopes_entities_and_triples_to_one_engine(store, doc) -> None:
    _seed_two_streams(store, doc)

    entities, triples = store_view(store, engine="claude")

    assert entities == {"claudealpha", "claudebeta"}
    assert triples == {("claudealpha", "uses", "claudebeta")}


def test_store_view_scopes_to_a_prompt_version(store, doc) -> None:
    _seed_two_streams(store, doc)

    entities, _ = store_view(store, prompt_version="extract-v1")

    assert entities == {"mockalpha", "mockbeta"}


def test_store_view_scopes_to_a_model(store, doc) -> None:
    _seed_two_streams(store, doc)

    entities, _ = store_view(store, model="claude-fable-5")

    assert entities == {"claudealpha", "claudebeta"}


def _gold(tmp_path, entities=(), triples=()):
    path = tmp_path / "gold.json"
    path.write_text(
        json.dumps(
            {
                "entities": [{"name": name} for name in entities],
                "triples": [
                    {"src": s, "relation": r, "dst": d} for s, r, d in triples
                ],
            }
        ),
        encoding="utf-8",
    )
    return load_gold(path)


def test_two_extractors_in_one_store_are_scored_separately(
    tmp_path, store, doc
) -> None:
    """The defect: without a filter, one engine's hits mask the other's misses."""
    _seed_two_streams(store, doc)
    gold = _gold(tmp_path, entities=["ClaudeAlpha", "ClaudeBeta"])

    mixed = evaluate_store(store, gold)
    scoped = evaluate_store(store, gold, engine="claude")

    assert mixed.entity["precision"] == pytest.approx(0.5)
    assert scoped.entity["precision"] == pytest.approx(1.0)
    assert scoped.entity["recall"] == pytest.approx(1.0)


def test_report_records_which_stream_it_scored(tmp_path, store, doc) -> None:
    _seed_two_streams(store, doc)
    gold = _gold(tmp_path, entities=["ClaudeAlpha"])

    report = evaluate_store(
        store, gold, engine="claude", model="claude-fable-5",
        prompt_version="extract-v2",
    )

    assert report.stream == {
        "engine": "claude",
        "model": "claude-fable-5",
        "prompt_version": "extract-v2",
        "decode_params": None,
    }
    assert report.to_dict()["stream"]["engine"] == "claude"


def test_unfiltered_report_says_so_instead_of_implying_one_stream(
    tmp_path, store, doc
) -> None:
    _seed_two_streams(store, doc)
    gold = _gold(tmp_path, entities=["ClaudeAlpha"])

    report = evaluate_store(store, gold)

    assert report.stream == {
        "engine": None,
        "model": None,
        "prompt_version": None,
        "decode_params": None,
    }
