"""JSON transport and retry budgets count actual generate invocations."""

from __future__ import annotations

import asyncio
from email.message import Message
import json
import re
from types import SimpleNamespace
from urllib.error import HTTPError

import pytest

from ontologylab import engines, extractor
from ontologylab.engines import ApiEngine, EngineError, extract_fenced_block
from ontologylab.extractor import (
    Chunk,
    build_extraction_prompt,
    chunk_document,
    parse_and_validate_extraction,
    run_extraction,
)
from ontologylab.provenance import Provenance
from ontologylab.providers import Provider, dedicated_api_key_env
from ontologylab.safety import Caps
from ontologylab.schemas import preset


GOOD = '{"entities": [{"name": "AlphaBeta", "entity_type": "Component"}], "relations": []}'


@pytest.mark.parametrize("raw", [' {"entities": []} \n', "\n[1, {}]\n", '{"code":"```"}'])
def test_bare_json_containers_are_accepted(raw):
    assert json.loads(extract_fenced_block(raw)) == json.loads(raw)


@pytest.mark.parametrize(
    "raw",
    ["", " ", "garbage", '{"entities":', "[1,", "null", "42", '"text"',
     "{} trailing", 'prefix {}', "```json\n{}\n", "```json\n \n```"],
)
def test_empty_non_json_and_non_container_output_is_rejected(raw):
    with pytest.raises(EngineError):
        extract_fenced_block(raw)


def test_fences_keep_precedence_and_other_languages_require_fences():
    assert extract_fenced_block('prefix\n```json\n{"ok": true}\n```') == '{"ok": true}'
    assert extract_fenced_block("```\n[]\n```") == "[]"
    with pytest.raises(EngineError):
        extract_fenced_block("{}", lang="python")


@pytest.mark.parametrize("kind", ["openai", "anthropic"])
@pytest.mark.parametrize("expects_json", [False, True])
def test_json_mode_is_explicit_openai_only_and_preserves_usage(
    monkeypatch, kind, expects_json,
):
    base = "http://127.0.0.1:12345/v1"
    provider = Provider(
        id="stub", kind=kind, base_url=base,
        api_key_env=dedicated_api_key_env("stub", base), models=("fake-model",),
    )
    monkeypatch.setenv(provider.api_key_env, "fake-key")
    requests = []

    def post(url, headers, body, timeout_s):
        requests.append(body)
        if kind == "anthropic":
            return {
                "content": [{"type": "text", "text": GOOD}],
                "usage": {"input_tokens": 11, "output_tokens": 7},
            }
        return {
            "choices": [{"message": {"content": GOOD}}],
            "usage": {"prompt_tokens": 11, "completion_tokens": 7},
        }

    monkeypatch.setattr(engines, "_http_post_json", post)
    engine = ApiEngine(provider, decode_params={"temperature": 0.3})

    raw, usage = asyncio.run(engine.generate(
        "JSON appears here even when the caller wants plain text.",
        expects_json=expects_json,
    ))

    assert len(requests) == 1
    assert requests[0].get("response_format") == (
        {"type": "json_object"} if kind == "openai" and expects_json else None
    )
    assert requests[0]["temperature"] == 0.3
    assert raw == GOOD
    assert usage["decode_params"] == {"temperature": 0.3}
    assert (usage["prompt_tokens"], usage["completion_tokens"]) == (11, 7)
    assert usage["calls"] == 1


def test_api_error_does_not_retry_inside_generate(monkeypatch):
    base = "http://127.0.0.1:12345/v1"
    provider = Provider(
        id="stub", kind="openai", base_url=base,
        api_key_env=dedicated_api_key_env("stub", base), models=("fake-model",),
    )
    monkeypatch.setenv(provider.api_key_env, "fake-key")
    requests = []

    def post(url, headers, body, timeout_s):
        requests.append(body)
        raise HTTPError(url, 503, "unavailable", Message(), None)

    monkeypatch.setattr(engines, "_http_post_json", post)
    with pytest.raises(EngineError, match="HTTP 503"):
        asyncio.run(ApiEngine(provider).generate("JSON", expects_json=True))
    assert len(requests) == 1


class CountingEngine:
    """Count calls independently of usage, repeating the last scripted reply."""

    def __init__(self, replies):
        self.replies = replies
        self.calls = 0

    async def generate(self, prompt, *, model=None):
        reply = self.replies[min(self.calls, len(self.replies) - 1)]
        self.calls += 1
        if isinstance(reply, EngineError):
            raise reply
        return reply, {"elapsed": 999, "decode_params": {"temperature": 0.3}}


def drive(store, tmp_path, engine, *, max_calls=0, text="AlphaBeta", **kwargs):
    doc, _ = store.insert_document(
        source_kind="upload", source_uri="file:///retry.txt", title="retry",
        raw_text=text, content_hash="sha256:retry",
    )
    provenance = Provenance(str(tmp_path / "job"), seed=0)
    caps = Caps(SimpleNamespace(
        iterations=0, time_budget_s=0.0, max_engine_calls=max_calls,
    ))
    outcome = asyncio.run(run_extraction(
        store, engine, provenance, caps, [doc.id],
        extractor_engine="counting", extractor_model="fake-model",
        on_progress=lambda _line: None, on_stats=lambda _stats: None,
        **kwargs,
    ))
    return outcome, provenance


@pytest.mark.parametrize(
    "replies, expected_calls",
    [([GOOD], 1), (["garbage", GOOD], 2), (["", GOOD], 2),
     (['{"entities":', GOOD], 2)],
)
def test_bare_json_and_one_parse_retry_succeed(
    store, tmp_path, replies, expected_calls,
):
    engine = CountingEngine(replies)
    outcome, provenance = drive(store, tmp_path, engine)
    assert outcome == ""
    assert not outcome.chunk_failed
    assert engine.calls == provenance.engine_calls == expected_calls
    assert store.conn.execute(
        "SELECT status FROM extraction_runs"
    ).fetchone()[0] == "complete"
    row = store.conn.execute(
        "SELECT name, prompt_version, decode_params, status FROM nodes"
    ).fetchone()
    assert tuple(row) == ("AlphaBeta", "extract-v8", '{"temperature":0.3}', "proposed")
    assert store.conn.execute(
        "SELECT prompt_version FROM extraction_runs"
    ).fetchone()[0] == "extract-v8"


@pytest.mark.parametrize("raw", ["garbage", "", '{"entities":', "[]"])
def test_two_malformed_replies_fail_without_a_third_attempt(store, tmp_path, raw):
    engine = CountingEngine([raw])
    outcome, provenance = drive(store, tmp_path, engine)
    assert outcome == ""
    assert outcome.chunk_failed
    assert engine.calls == provenance.engine_calls == 2
    assert store.conn.execute("SELECT COUNT(*) FROM nodes").fetchone()[0] == 0
    assert tuple(store.conn.execute(
        "SELECT status, error_kind FROM extraction_chunks"
    ).fetchone()) == ("failed", "parse_rejected")


def test_budget_one_refuses_retry_after_malformed_reply(store, tmp_path):
    engine = CountingEngine(["garbage", GOOD])
    outcome, provenance = drive(store, tmp_path, engine, max_calls=1)
    assert "engine call cap reached" in outcome
    assert engine.calls == provenance.engine_calls == 1
    assert outcome.chunk_failed


def test_budget_four_caps_three_repeatedly_malformed_chunks(store, tmp_path):
    text = "AlphaBeta " * 2500
    assert len(chunk_document(text)) == 3
    engine = CountingEngine(["garbage"])
    outcome, provenance = drive(
        store, tmp_path, engine, max_calls=4, text=text,
    )
    assert "engine call cap reached" in outcome
    assert engine.calls == provenance.engine_calls == 4
    assert [row[0] for row in store.conn.execute(
        "SELECT status FROM extraction_chunks ORDER BY chunk_index"
    )] == ["failed", "failed", "pending"]


def test_raising_calls_spend_budget_and_record_measured_elapsed(
    store, tmp_path, monkeypatch,
):
    ticks = iter([10.0, 10.25, 11.0, 11.25, 12.0, 12.25])
    monkeypatch.setattr(extractor, "time", SimpleNamespace(monotonic=lambda: next(ticks)))
    engine = CountingEngine([EngineError("synthetic provider failure")])
    outcome, provenance = drive(
        store, tmp_path, engine, max_calls=1, text="AlphaBeta " * 2500,
    )
    assert "engine call cap reached" in outcome
    assert engine.calls == provenance.engine_calls == 1
    assert provenance.engine_elapsed_s == 0.25
    status = json.loads(provenance.status_path.read_text())
    assert status["engine_calls"] == 1
    entries = [json.loads(line) for line in provenance.jsonl_path.read_text().splitlines()]
    calls = [entry["payload"] for entry in entries if entry["step"] == "extract"]
    assert calls == [{
        "engine_call": True, "elapsed_s": 0.25,
        "usage_meta": {"error": "engine_error"},
    }]


def test_raising_retry_is_counted_but_not_retried_again(store, tmp_path):
    engine = CountingEngine(["garbage", EngineError("synthetic failure"), GOOD])
    outcome, provenance = drive(store, tmp_path, engine)
    assert outcome.chunk_failed
    assert engine.calls == provenance.engine_calls == 2
    assert tuple(store.conn.execute(
        "SELECT status, error_kind FROM extraction_chunks"
    ).fetchone()) == ("failed", "engine_error")


def test_abort_is_checked_before_parse_retry(store, tmp_path):
    engine = CountingEngine(["garbage", GOOD])
    outcome, provenance = drive(
        store, tmp_path, engine,
        should_abort=lambda: "cancelled" if engine.calls else "",
    )
    assert outcome == "cancelled"
    assert engine.calls == provenance.engine_calls == 1
    assert store.conn.execute(
        "SELECT status FROM extraction_runs"
    ).fetchone()[0] == "cancelled"


def test_polarity_example_parses_with_declared_agrochem_v2_qualifiers(store):
    schema = preset("agrochem-v2")
    store.install_schema(
        label=schema["label"], description=schema["description"],
        entity_types=schema["entity_types"], relation_types=schema["relation_types"],
    )
    text = "Fluopyram had no significant effect on Botrytis. Boscalid suppressed Botrytis."
    prompt = build_extraction_prompt(store.get_schema(), text)
    examples = [json.loads(block) for block in re.findall(r"```json\n(.*?)```", prompt, re.S)]
    polarity_examples = [
        example for example in examples
        if any("polarity" in rel.get("qualifiers", {}) for rel in example["relations"])
    ]
    assert len(polarity_examples) == 1
    result = parse_and_validate_extraction(
        json.dumps(polarity_examples[0]), store.get_schema(), Chunk(0, 0, text),
    )
    assert result.warnings == []
    assert len(result.entities) == 3
    assert [rel.relation_type for rel in result.relations] == ["controls", "controls"]
    assert [rel.qualifiers for rel in result.relations] == [
        {"polarity": "no_effect"}, {"polarity": "supports"},
    ]
