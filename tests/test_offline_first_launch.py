"""Task 6: first launch and passive dashboard behavior are offline by contract."""

from __future__ import annotations

import subprocess
from pathlib import Path

from fastapi.testclient import TestClient

from ontologylab import sources as sources_module
from ontologylab.server import settings
from ontologylab.server.app import create_app
from ontologylab.sources import Source, add_source

ROOT = Path(__file__).resolve().parents[1]


def test_browser_localizer_makes_no_request_until_explicit_action() -> None:
    # Given one English text node in a fully loaded dashboard document
    script = r"""
const fs = require("fs");
const vm = require("vm");
let requests = [];
const text = {
  nodeType: 3,
  nodeValue: "This study investigates breast cancer treatment.",
  isConnected: true,
  parentElement: {closest: () => null},
};
let walked = false;
const document = {
  readyState: "complete",
  body: {nodeType: 1},
  createTreeWalker: () => ({
    nextNode: () => walked ? null : (walked = true, text),
  }),
  addEventListener: () => {},
};
const window = {
  document,
  Node: {TEXT_NODE: 3, ELEMENT_NODE: 1},
  NodeFilter: {SHOW_TEXT: 4},
  MutationObserver: function () { this.observe = () => {}; },
  localStorage: {getItem: () => null, setItem: () => {}},
  setTimeout: (callback) => { callback(); return 1; },
  fetch: async (url) => {
    requests.push(url);
    return {ok: true, json: async () => ({translations: ["번역"]})};
  },
  console: {warn: () => {}},
};
vm.runInNewContext(
  fs.readFileSync("ontologylab/web/localize.js", "utf8"),
  {window, console}
);
setImmediate(() => process.stdout.write(JSON.stringify(requests)));
"""

    # When the localizer initializes without a user translation action
    result = subprocess.run(
        ["node", "-e", script],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    # Then it makes no HTTP request at all, including no loopback translation call
    assert result.returncode == 0, result.stderr
    assert result.stdout == "[]"


def test_app_construction_does_not_touch_keychain_migration(
    tmp_path: Path, monkeypatch
) -> None:
    # Given a fresh desktop data directory and a credential trap
    calls: list[Path] = []
    monkeypatch.setattr(
        sources_module,
        "migrate_source_keychain_accounts",
        lambda data_dir: calls.append(Path(data_dir)),
    )

    # When the passive application surface is constructed
    create_app(data_dir=tmp_path / "data", packs_dir=tmp_path / "packs")

    # Then no credential operation runs before an explicit credential action
    assert calls == []


def test_passive_source_inventory_does_not_resolve_credentials(
    tmp_path: Path, monkeypatch
) -> None:
    # Given a generated source registry row carrying a stale Keychain locator
    data_dir = tmp_path / "data"
    add_source(
        data_dir,
        Source(
            id="openalex",
            role="literature",
            keychain_account="ontologylab.source.openalex",
        ),
    )
    monkeypatch.setattr(
        "ontologylab.connectors.paper_api.resolve_source_key",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("passive credential resolution")
        ),
    )
    monkeypatch.setattr(
        "ontologylab.sources.resolve_source_key",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("passive credential resolution")
        ),
    )
    client = TestClient(create_app(data_dir=data_dir, packs_dir=tmp_path / "packs"))

    # When passive settings and source tabs inventory local configuration
    paper_sources = client.get("/api/paper-sources")
    connected_sources = client.get("/api/sources")

    # Then both reads settle without invoking Keychain
    assert paper_sources.status_code == 200
    assert connected_sources.status_code == 200


def test_fresh_dashboard_settings_choose_available_mock_offline() -> None:
    # Given no persisted settings or configured live provider
    # When the dashboard asks for first-run defaults and engine ordering
    defaults = settings.default_settings()
    engines = settings.engines()

    # Then mock is the canonical available first-run engine
    assert defaults.default_engine == "mock"
    assert defaults.default_model is None
    assert engines[0].name == "mock"
    assert engines[0].available is True


def test_translation_route_requires_typed_explicit_action(
    tmp_path: Path, monkeypatch
) -> None:
    # Given a live engine that would translate if dispatched
    calls: list[str] = []

    class TranslationEngine:
        async def generate(
            self, prompt: str, *, model: str | None = None
        ) -> tuple[str, dict[str, int]]:
            del model
            calls.append(prompt)
            return '["번역"]', {"calls": 1}

    monkeypatch.setattr(
        "ontologylab.engines.resolve_engine",
        lambda *_args, **_kwargs: TranslationEngine(),
    )
    client = TestClient(
        create_app(data_dir=tmp_path / "data", packs_dir=tmp_path / "packs")
    )

    # When a passive/legacy caller omits the explicit action discriminator
    response = client.post(
        "/api/translate",
        json={"texts": ["English prose"], "engine": "claude"},
    )

    # Then parsing refuses before engine dispatch
    assert response.status_code == 422
    assert calls == []


def test_explicit_live_translation_fails_offline_without_dispatch_or_mutation(
    tmp_path: Path, monkeypatch
) -> None:
    # Given an explicitly selected live CLI engine under the offline kill switch
    data_dir = tmp_path / "data"
    monkeypatch.setenv("ONTOLOGYLAB_OFFLINE", "1")
    monkeypatch.setattr(
        "ontologylab.engines._run_subprocess",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("offline translation spawned a live CLI")
        ),
    )
    client = TestClient(create_app(data_dir=data_dir, packs_dir=tmp_path / "packs"))
    before = client.get("/api/documents").json()

    # When the user explicitly asks for live translation
    response = client.post(
        "/api/translate",
        json={
            "action": "translate_visible",
            "texts": ["English prose remains evidence."],
            "engine": "claude",
        },
    )

    # Then the typed request fails honestly before process/network dispatch
    assert response.json() == {
        "ok": False,
        "error_kind": "offline",
        "detail": "오프라인 모드에서는 실시간 번역 엔진을 사용할 수 없습니다.",
    }
    assert response.status_code == 200
    assert client.get("/api/documents").json() == before


def test_passive_packs_read_reports_unbundled_gate_without_crashing(
    tmp_path: Path, monkeypatch
) -> None:
    # Given an installed runtime layout with no competency gold fixtures
    monkeypatch.setattr(
        "ontologylab.server.routes._competency_gold_dir", lambda: None
    )
    client = TestClient(
        create_app(data_dir=tmp_path / "data", packs_dir=tmp_path / "packs")
    )

    # When the packs tab reads passively
    packs = client.get("/api/packs")
    receipt = client.get("/api/packs/competency")

    # Then both succeed and say "not bundled" — never a 500, never a fake PASS/FAIL
    assert packs.status_code == 200
    comp = packs.json()["competency"]
    assert comp == {"available": False, "reason": "fixtures_not_bundled"}
    assert receipt.status_code == 200
    assert receipt.json() == comp


def test_mock_cannot_be_misrepresented_as_live_translation(
    tmp_path: Path,
) -> None:
    # Given the offline mock engine selected in a translation request
    client = TestClient(
        create_app(data_dir=tmp_path / "data", packs_dir=tmp_path / "packs")
    )

    # When the explicit action names mock instead of a live translation engine
    response = client.post(
        "/api/translate",
        json={
            "action": "translate_visible",
            "texts": ["English prose"],
            "engine": "mock",
        },
    )

    # Then boundary parsing refuses instead of claiming translated output
    assert response.status_code == 422
