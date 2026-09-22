from __future__ import annotations

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
        "ontologylab.engines.resolve_engine",
        lambda *args, **kwargs: engine,
    )
    client = TestClient(create_app(data_dir=data_dir))
    original = [
        "This study investigates breast cancer treatment.",
        "ovarian tumor tissue",
    ]

    response = client.post(
        "/api/translate",
        json={
            "action": "translate_visible",
            "texts": original,
            "engine": "claude",
        },
    )

    assert response.status_code == 200
    assert response.json() == {
        "translations": ["유방암 치료 연구입니다.", "난소 종양 조직"]
    }
    assert original[0] in engine.prompt
    assert original[1] in engine.prompt
    assert "JSON" in engine.prompt


def test_translate_does_not_walk_fallback_engines(
    tmp_path: Path, monkeypatch
) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    working = _BareTranslationEngine()
    attempts: list[str] = []

    def fake_resolve_engine(name: str, *args, **kwargs):
        attempts.append(name)
        return _UnavailableEngine() if name == "claude" else working

    monkeypatch.setattr("ontologylab.engines.resolve_engine", fake_resolve_engine)
    client = TestClient(create_app(data_dir=data_dir))

    response = client.post(
        "/api/translate",
        json={
            "action": "translate_visible",
            "texts": [
                "This study investigates breast cancer treatment.",
                "ovarian tumor tissue",
            ],
            "engine": "claude",
        },
    )

    assert attempts == ["claude"] and response.status_code == 502, (
        attempts,
        response.status_code,
    )


