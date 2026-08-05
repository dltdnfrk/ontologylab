from __future__ import annotations

import subprocess
from pathlib import Path

from fastapi.testclient import TestClient

from ontologylab.server.app import create_app


class _TranslationEngine:
    def __init__(self) -> None:
        self.prompt = ""

    async def generate(
        self, prompt: str, *, model: str | None = None
    ) -> tuple[str, dict[str, int]]:
        self.prompt = prompt
        return (
            '```json\n["유방암 치료 연구입니다.", "난소 종양 조직"]\n```',
            {"calls": 1},
        )


class _UnavailableEngine:
    async def generate(
        self, prompt: str, *, model: str | None = None
    ) -> tuple[str, dict[str, int]]:
        raise RuntimeError("engine unavailable")


class _BareTranslationEngine(_TranslationEngine):
    async def generate(
        self, prompt: str, *, model: str | None = None
    ) -> tuple[str, dict[str, int]]:
        self.prompt = prompt
        return (
            '["유방암 치료 연구입니다.", "난소 종양 조직"]',
            {"calls": 1},
        )


def test_translate_route_returns_korean_without_mutating_input(
    tmp_path: Path, monkeypatch
) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    engine = _TranslationEngine()
    monkeypatch.setattr(
        "ontologylab.engines.get_engine",
        lambda *args, **kwargs: engine,
    )
    client = TestClient(create_app(data_dir=data_dir))
    original = [
        "This study investigates breast cancer treatment.",
        "ovarian tumor tissue",
    ]

    response = client.post(
        "/api/translate",
        json={"texts": original, "engine": "claude"},
    )

    assert response.status_code == 200
    assert response.json() == {
        "translations": ["유방암 치료 연구입니다.", "난소 종양 조직"]
    }
    assert original[0] in engine.prompt
    assert original[1] in engine.prompt
    assert "JSON" in engine.prompt


def test_translate_route_falls_back_to_next_available_engine(
    tmp_path: Path, monkeypatch
) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    working = _BareTranslationEngine()
    attempts: list[str] = []

    def fake_get_engine(name: str, *args, **kwargs):
        attempts.append(name)
        return _UnavailableEngine() if name == "claude" else working

    monkeypatch.setattr("ontologylab.engines.get_engine", fake_get_engine)
    client = TestClient(create_app(data_dir=data_dir))

    response = client.post(
        "/api/translate",
        json={
            "texts": [
                "This study investigates breast cancer treatment.",
                "ovarian tumor tissue",
            ]
        },
    )

    assert response.status_code == 200, (response.json(), attempts)
    assert attempts == ["claude", "codex"]


def test_browser_localizer_targets_prose_not_identifiers() -> None:
    repo = Path(__file__).resolve().parents[1]
    script = """
const localizer = require("./web/localize.js");
const cases = [
  ["This study investigates breast cancer treatment.", true],
  ["ovarian tumor tissue", true],
  ["germline BRCA-1/2 mutations · 승인하면 함께 승인돼요", true],
  ["BRCA-1/2", false],
  ["associated_with", false],
  ["이미 한국어입니다", false],
];
for (const [text, expected] of cases) {
  if (localizer.shouldTranslate(text) !== expected) {
    throw new Error(`${text}: expected ${expected}`);
  }
}
const labels = [
  ["expressed_in", "발현 위치"],
  ["PARP-inhibitors", "PARP 억제제"],
  ["Platinum", "백금"],
  ["apoptosis", "세포자멸사"],
  ["cancer", "암"],
  ["pseudo-senescence", "유사 노화"],
  ["senescence", "세포 노화"],
  ["spliceosome", "스플라이소솜"],
  ["Assay", "분석법"],
  ["CellLine", "세포주"],
  ["Disease", "질환"],
  ["Drug", "약물"],
  ["Gene", "유전자"],
  ["Pathway", "경로"],
  ["Protein", "단백질"],
  ["Variant", "변이"],
  ["paper_api", "논문 API"],
  ["BRCA-1/2", "BRCA-1/2"],
];
for (const [value, expected] of labels) {
  if (localizer.ontologyLabelKo(value) !== expected) {
    throw new Error(`${value}: expected ${expected}`);
  }
}
"""

    result = subprocess.run(
        ["node", "-e", script],
        cwd=repo,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr


def test_browser_ui_utils_strip_markup_and_avoid_graph_label_collisions() -> None:
    repo = Path(__file__).resolve().parents[1]
    script = r"""
const ui = require("./web/ui-utils.js");
if (ui.plainText("<i>BRCA1</i> &amp; <b>PARP</b>") !== "BRCA1 & PARP") {
  throw new Error("document markup leaked");
}
if (Math.abs(ui.graphLabelFontSize(0.25) * 0.25 - 11) > 0.001) {
  throw new Error("graph labels shrink with the fitted graph");
}
const labels = ui.visibleGraphLabelIds(
  [
    {id: "selected", name: "Selected node", x: 100, y: 100, degree: 1},
    {id: "overlap", name: "Overlapping node", x: 100, y: 100, degree: 20},
    {
      id: "spaced",
      name: "Spaced node with full readable name",
      x: 360,
      y: 260,
      degree: 2,
    },
  ],
  {x: 0, y: 0, k: 1},
  {w: 640, h: 480},
  "selected"
);
if (!labels.includes("selected") || !labels.includes("spaced")) {
  throw new Error("readable labels were hidden");
}
if (labels.includes("overlap")) {
  throw new Error("colliding label remained visible");
}
"""

    result = subprocess.run(
        ["node", "-e", script],
        cwd=repo,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr


def test_graph_and_document_renderers_use_localized_safe_labels() -> None:
    root = Path(__file__).resolve().parents[1]
    app = (root / "web" / "app.js").read_text(encoding="utf-8")
    index = (root / "web" / "index.html").read_text(encoding="utf-8")

    assert "uiUtils.visibleGraphLabelIds" in app
    assert "label.style.fontSize =" in app
    assert "label.textContent = ontologyLabelKo(n.name);" in app
    assert "ontologyLabelKo(type)" in app
    assert "plainDocumentTitle(doc.title" in app
    assert "data-sync-title-aria" in app
    assert "/static/ui-utils.js" in index


def test_browser_chat_session_rotates_without_deleting_history() -> None:
    repo = Path(__file__).resolve().parents[1]
    script = """
const createChatSession = require("./web/chat-session.js");
const values = ["session-a", "session-b"];
const memory = new Map();
const root = {
  crypto: { randomUUID: () => values.shift() },
  sessionStorage: {
    getItem: (key) => memory.get(key) || null,
    setItem: (key, value) => memory.set(key, value),
  },
};
const session = createChatSession(root);
if (session.current() !== "session-a") throw new Error("missing initial session");
if (!session.startsNewOnEntry("sources", "home")) {
  throw new Error("research-to-home did not start a session");
}
if (session.startsNewOnEntry("home", "sources")) {
  throw new Error("leaving home started a session");
}
if (session.startsNewOnEntry(null, "home")) {
  throw new Error("initial render started a second session");
}
if (session.historyPath() !== "/api/chat/history?session_id=session-a") {
  throw new Error("history is not scoped");
}
const payload = session.attach({ message: "첫 작업" });
if (payload.session_id !== "session-a") throw new Error("message is not scoped");
if (session.startNew() !== "session-b") throw new Error("session did not rotate");
if (memory.size !== 1) throw new Error("starting a session deleted stored data");
"""

    result = subprocess.run(
        ["node", "-e", script],
        cwd=repo,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
