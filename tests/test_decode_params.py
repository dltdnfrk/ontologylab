"""Selectable sampling parameters, per provider kind, recorded on the row.

Pinning temperature in code fixed one thing and broke another: a fixed
value needs no record, but a *selectable* one does. The moment a run can
choose its sampler, (engine, model, prompt_version) stops naming the
distribution again — so the chosen parameters travel with the row.

Which keys are legal is a property of the provider's API, not of this
codebase: Anthropic takes top_k and refuses seed, OpenAI-compatible
endpoints (OpenAI, xAI, OpenRouter, a local Ollama) take seed and refuse
top_k. Sending an unsupported key is a 400 from the provider, so it is
refused here instead.
"""

from __future__ import annotations

import asyncio
import json
import sqlite3

import pytest

import ontologylab.engines as engines
from ontologylab.engines import ApiEngine, EngineError, get_engine
from ontologylab.evaluation import store_view
from ontologylab.kgstore import KGStore
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
        id="oai",
        kind="openai",
        base_url="https://api.openai.com/v1",
        api_key_env="OAI_KEY",
        models=("gpt-5.6",),
    )


def _xai() -> Provider:
    return Provider(
        id="xai",
        kind="openai",
        base_url="https://api.x.ai/v1",
        api_key_env="XAI_KEY",
        models=("grok-4",),
    )


def _response_for(kind: str) -> dict:
    if kind == "anthropic":
        return {"content": [{"type": "text", "text": "x"}]}
    return {"choices": [{"message": {"role": "assistant", "content": "x"}}]}


def _capture(monkeypatch, provider: Provider):
    seen: dict = {}

    def fake_post(url, headers, payload, timeout_s):
        seen["payload"] = payload
        return _response_for(provider.kind)

    monkeypatch.setattr(engines, "_http_post_json", fake_post)
    return seen


# ---------------------------------------------------------------------------
# Every provider kind, and selection
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "provider, env",
    [(_anthropic(), "ANTH_KEY"), (_openai(), "OAI_KEY"), (_xai(), "XAI_KEY")],
    ids=["anthropic", "openai", "xai"],
)
def test_every_provider_kind_sends_the_default_pinned_temperature(
    monkeypatch, provider, env
) -> None:
    monkeypatch.setenv(env, _KEY)
    seen = _capture(monkeypatch, provider)

    asyncio.run(ApiEngine(provider).generate("hi"))

    assert seen["payload"]["temperature"] == 0.0


@pytest.mark.parametrize(
    "provider, env",
    [(_anthropic(), "ANTH_KEY"), (_openai(), "OAI_KEY"), (_xai(), "XAI_KEY")],
    ids=["anthropic", "openai", "xai"],
)
def test_every_provider_kind_honours_a_chosen_temperature(
    monkeypatch, provider, env
) -> None:
    monkeypatch.setenv(env, _KEY)
    seen = _capture(monkeypatch, provider)

    _, usage = asyncio.run(
        ApiEngine(provider, decode_params={"temperature": 0.7}).generate("hi")
    )

    assert seen["payload"]["temperature"] == 0.7
    assert usage["decode_params"] == {"temperature": 0.7}


def test_top_p_is_selectable_alongside_temperature(monkeypatch) -> None:
    monkeypatch.setenv("XAI_KEY", _KEY)
    provider = _xai()
    seen = _capture(monkeypatch, provider)

    asyncio.run(
        ApiEngine(
            provider, decode_params={"temperature": 0.2, "top_p": 0.9}
        ).generate("hi")
    )

    assert seen["payload"]["temperature"] == 0.2
    assert seen["payload"]["top_p"] == 0.9


# ---------------------------------------------------------------------------
# What each kind's API actually accepts
# ---------------------------------------------------------------------------


def test_anthropic_takes_top_k(monkeypatch) -> None:
    monkeypatch.setenv("ANTH_KEY", _KEY)
    provider = _anthropic()
    seen = _capture(monkeypatch, provider)

    asyncio.run(ApiEngine(provider, decode_params={"top_k": 5}).generate("hi"))

    assert seen["payload"]["top_k"] == 5


def test_openai_kind_refuses_top_k_instead_of_sending_a_400() -> None:
    with pytest.raises(EngineError) as exc:
        ApiEngine(_xai(), decode_params={"top_k": 5})

    assert "top_k" in str(exc.value)
    assert "openai" in str(exc.value)


def test_openai_kind_takes_seed(monkeypatch) -> None:
    monkeypatch.setenv("OAI_KEY", _KEY)
    provider = _openai()
    seen = _capture(monkeypatch, provider)

    asyncio.run(ApiEngine(provider, decode_params={"seed": 11}).generate("hi"))

    assert seen["payload"]["seed"] == 11


def test_anthropic_refuses_seed() -> None:
    with pytest.raises(EngineError) as exc:
        ApiEngine(_anthropic(), decode_params={"seed": 11})

    assert "seed" in str(exc.value)


def test_an_unknown_decode_parameter_is_refused() -> None:
    with pytest.raises(EngineError) as exc:
        ApiEngine(_anthropic(), decode_params={"tempreature": 0.5})

    assert "tempreature" in str(exc.value)


@pytest.mark.parametrize(
    "params",
    [{"temperature": -0.1}, {"temperature": 2.5}, {"top_p": 0.0}, {"top_p": 1.5}],
)
def test_out_of_range_values_are_refused(params) -> None:
    with pytest.raises(EngineError):
        ApiEngine(_anthropic(), decode_params=params)


# ---------------------------------------------------------------------------
# Selection reaches the engine; engines that cannot honour it say so
# ---------------------------------------------------------------------------


def test_get_engine_threads_the_selection_into_the_api_engine(
    monkeypatch, tmp_path
) -> None:
    from ontologylab.providers import add_provider

    add_provider(tmp_path, _xai())
    monkeypatch.setenv("XAI_KEY", _KEY)
    engine = get_engine(
        "api:xai", data_dir=tmp_path, decode_params={"temperature": 0.3}
    )
    seen = _capture(monkeypatch, _xai())

    asyncio.run(engine.generate("hi"))

    assert seen["payload"]["temperature"] == 0.3


@pytest.mark.parametrize("name", ["mock", "claude", "codex", "gemini"])
def test_cli_engines_refuse_a_selection_they_cannot_apply(name) -> None:
    """Silently dropping a requested temperature is the worse failure.

    These adapters shell out to a CLI with no sampling flag, so a chosen
    value could not reach the model. Accepting it would record a parameter
    the run never used.
    """
    with pytest.raises(EngineError) as exc:
        get_engine(name, decode_params={"temperature": 0.5})

    assert name in str(exc.value)


@pytest.mark.parametrize("name", ["mock", "claude", "codex", "gemini"])
def test_cli_engines_still_build_without_a_selection(name) -> None:
    assert get_engine(name) is not None


# ---------------------------------------------------------------------------
# The row carries what produced it
# ---------------------------------------------------------------------------


def _insert(store, doc, names, *, decode_params, engine="api:xai"):
    src, dst = make_entity(names[0]), make_entity(names[1])
    return store.insert_proposed(
        [src, dst],
        [make_relation(src, dst, "uses")],
        source_doc_id=doc.id,
        extractor_engine=engine,
        extractor_model="grok-4",
        prompt_version="extract-v1",
        decode_params=decode_params,
    )


def test_nodes_and_edges_record_the_parameters_they_were_produced_with(
    store, doc
) -> None:
    _insert(store, doc, ("Alpha", "Beta"), decode_params={"temperature": 0.7})

    node_values = {
        row["decode_params"] for row in store.conn.execute(
            "SELECT decode_params FROM nodes"
        )
    }
    edge_values = {
        row["decode_params"] for row in store.conn.execute(
            "SELECT decode_params FROM edges"
        )
    }

    assert node_values == {'{"temperature":0.7}'}
    assert edge_values == {'{"temperature":0.7}'}


def test_stored_parameters_are_key_sorted_so_equal_settings_compare_equal(
    store, doc
) -> None:
    """Dict order must not split one setting into two stored strings."""
    _insert(
        store, doc, ("Alpha", "Beta"),
        decode_params={"top_p": 0.9, "temperature": 0.2},
    )

    stored = store.conn.execute(
        "SELECT decode_params FROM nodes LIMIT 1"
    ).fetchone()["decode_params"]

    assert stored == '{"temperature":0.2,"top_p":0.9}'
    assert json.loads(stored) == {"temperature": 0.2, "top_p": 0.9}


def test_absent_parameters_stay_null_rather_than_an_empty_object(
    store, doc
) -> None:
    """A CLI engine did not choose a sampler; NULL says exactly that."""
    _insert(store, doc, ("Alpha", "Beta"), decode_params=None, engine="claude")

    stored = store.conn.execute(
        "SELECT decode_params FROM nodes LIMIT 1"
    ).fetchone()["decode_params"]

    assert stored is None


def test_an_existing_store_gains_the_column_on_open(tmp_path) -> None:
    db = tmp_path / "kg.sqlite"
    KGStore.open(db).close()
    conn = sqlite3.connect(str(db))
    try:
        conn.execute("ALTER TABLE nodes DROP COLUMN decode_params")
        conn.execute("ALTER TABLE edges DROP COLUMN decode_params")
        conn.commit()
    finally:
        conn.close()

    store = KGStore.open(db)
    try:
        node_columns = {
            row["name"] for row in store.conn.execute("PRAGMA table_info(nodes)")
        }
        edge_columns = {
            row["name"] for row in store.conn.execute("PRAGMA table_info(edges)")
        }
    finally:
        store.close()

    assert "decode_params" in node_columns
    assert "decode_params" in edge_columns


def test_scoring_can_scope_to_one_sampler(store, doc) -> None:
    """Two temperatures in one store are two streams, not one average."""
    _insert(store, doc, ("HotAlpha", "HotBeta"), decode_params={"temperature": 1.0})
    _insert(store, doc, ("ColdAlpha", "ColdBeta"), decode_params={"temperature": 0.0})

    entities, triples = store_view(store, decode_params={"temperature": 0.0})

    assert entities == {"coldalpha", "coldbeta"}
    assert triples == {("coldalpha", "uses", "coldbeta")}
