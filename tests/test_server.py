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


def test_settings_put_roundtrips(tmp_path: Path, monkeypatch) -> None:
    # save_settings/load_settings persist to a module-level ROOT path; isolate
    # it to tmp so the PUT roundtrip never touches the real settings file.
    from ontologylab.server import settings as settings_mod

    settings_file = tmp_path / "settings.json"
    monkeypatch.setattr(
        settings_mod, "_settings_path", lambda root=None: settings_file
    )

    client = _client(tmp_path)
    payload = {
        "default_engine": "claude",
        "default_model": "claude-sonnet-4-5",
        "data_dir": str(tmp_path / "data"),
        "packs_dir": str(tmp_path / "packs"),
    }
    put = client.put("/api/settings", json=payload)
    assert put.status_code == 200
    assert put.json()["default_engine"] == "claude"

    # persisted: a fresh GET reflects the saved values
    got = client.get("/api/settings").json()
    assert got["default_engine"] == "claude"
    assert got["default_model"] == "claude-sonnet-4-5"
    assert got["packs_dir"] == str(tmp_path / "packs")


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


# ---------------------------------------------------------------------------
# Providers (registry HTTP surface — offline; the key never appears in a body)
# ---------------------------------------------------------------------------

_OPENAI_BODY = {
    "id": "orouter",
    "kind": "openai",
    "base_url": "https://openrouter.ai/api/v1",
    "api_key_env": "SRV_OR_KEY",
    "models": ["meta/llama"],
}


def test_providers_empty(tmp_path: Path) -> None:
    client = _client(tmp_path)
    assert client.get("/api/providers").json() == {"providers": []}


def test_provider_add_lists_and_reports_key_present(
    tmp_path: Path, monkeypatch
) -> None:
    client = _client(tmp_path)
    add = client.post("/api/providers", json=_OPENAI_BODY)
    assert add.status_code == 200
    assert add.json()["ok"] is True

    # Without the env var, key_present is False.
    monkeypatch.delenv("SRV_OR_KEY", raising=False)
    listed = client.get("/api/providers").json()["providers"]
    assert len(listed) == 1
    assert listed[0]["id"] == "orouter"
    assert listed[0]["key_present"] is False
    assert listed[0]["api_key_env"] == "SRV_OR_KEY"

    # With it set, key_present flips True — but the value is never returned.
    monkeypatch.setenv("SRV_OR_KEY", "sk-secret")
    listed = client.get("/api/providers").json()["providers"]
    assert listed[0]["key_present"] is True


def test_provider_add_invalid_returns_400(tmp_path: Path) -> None:
    client = _client(tmp_path)
    bad = dict(_OPENAI_BODY, id="BAD ID")
    resp = client.post("/api/providers", json=bad)
    assert resp.status_code == 400
    assert "invalid provider id" in resp.json()["detail"]


def test_provider_delete(tmp_path: Path) -> None:
    client = _client(tmp_path)
    client.post("/api/providers", json=_OPENAI_BODY)
    removed = client.request("DELETE", "/api/providers/orouter").json()
    assert removed == {"ok": True, "removed": True}
    # Idempotent: deleting again reports removed=False, still ok.
    again = client.request("DELETE", "/api/providers/orouter").json()
    assert again == {"ok": True, "removed": False}
    assert client.get("/api/providers").json() == {"providers": []}


def test_provider_test_missing_key_is_clear_not_error(
    tmp_path: Path, monkeypatch
) -> None:
    client = _client(tmp_path)
    client.post("/api/providers", json=_OPENAI_BODY)
    monkeypatch.delenv("SRV_OR_KEY", raising=False)
    res = client.post("/api/providers/orouter/test").json()
    assert res["ok"] is False
    assert "SRV_OR_KEY" in res["error"]


def test_provider_test_with_key_pings_via_monkeypatched_http(
    tmp_path: Path, monkeypatch
) -> None:
    import ontologylab.engines as engines

    client = _client(tmp_path)
    client.post("/api/providers", json=_OPENAI_BODY)
    monkeypatch.setenv("SRV_OR_KEY", "sk-super-secret")

    def fake_post(url, headers, payload, timeout_s):
        assert url.endswith("/chat/completions")
        assert headers["Authorization"] == "Bearer sk-super-secret"
        return {"choices": [{"message": {"content": "pong"}}]}

    monkeypatch.setattr(engines, "_http_post_json", fake_post)
    resp = client.post("/api/providers/orouter/test")
    res = resp.json()
    assert res["ok"] is True
    assert res["sample"] == "pong"
    assert isinstance(res["latency_ms"], int)
    # The key must not appear anywhere in the response body.
    assert "sk-super-secret" not in resp.text


def test_provider_test_unknown_id(tmp_path: Path) -> None:
    client = _client(tmp_path)
    res = client.post("/api/providers/ghost/test").json()
    assert res["ok"] is False
    assert "ghost" in res["error"]
