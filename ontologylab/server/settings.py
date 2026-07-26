"""Persistent local settings, engine availability, and cost aggregation."""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

from ontologylab.paths import (
    DEFAULT_ENGINE,
    DEFAULT_MODEL,
    ROOT,
    default_data_dir,
    default_packs_dir,
)
from ontologylab.server.schemas import CostSummary, EngineInfo, Settings

_ENGINE_CLI_NAMES: dict[str, str] = {
    "claude": "claude",
    "codex": "codex",
    "gemini": "gemini",
}

_DEFAULT_MODELS: dict[str, str | None] = {
    "claude": DEFAULT_MODEL,
    "codex": None,
    "gemini": None,
    "mock": None,
}

_SETTINGS_FILENAME = "settings.json"


def _settings_path(root: Path = ROOT) -> Path:
    return default_data_dir(root) / _SETTINGS_FILENAME


def default_settings() -> Settings:
    return Settings(
        default_engine=DEFAULT_ENGINE,
        default_model=DEFAULT_MODEL,
        data_dir=str(default_data_dir()),
        packs_dir=str(default_packs_dir()),
    )


def load_settings(root: Path = ROOT) -> Settings:
    path = _settings_path(root)
    if not path.exists():
        return default_settings()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        return Settings(**raw)
    except (json.JSONDecodeError, OSError, TypeError, ValueError):
        return default_settings()


def save_settings(settings: Settings, root: Path = ROOT) -> Settings:
    path = _settings_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(".json.tmp")
    tmp_path.write_text(
        json.dumps(settings.model_dump(), indent=2), encoding="utf-8"
    )
    tmp_path.replace(path)
    return settings


def engines() -> list[EngineInfo]:
    infos: list[EngineInfo] = [
        EngineInfo(name="mock", available=True, default_model=None)
    ]
    for name, cli_name in _ENGINE_CLI_NAMES.items():
        infos.append(
            EngineInfo(
                name=name,
                available=shutil.which(cli_name) is not None,
                default_model=_DEFAULT_MODELS.get(name),
            )
        )
    return infos


def _iter_provenance_entries(job_dir: Path) -> list[dict[str, Any]]:
    jsonl_path = job_dir / "provenance.jsonl"
    if not jsonl_path.exists():
        return []
    entries: list[dict[str, Any]] = []
    try:
        with jsonl_path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    entries.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    except OSError:
        return []
    return entries


def cost_summary(root: Path = ROOT, data_dir: Path | None = None) -> CostSummary:
    """Aggregate engine-call counts across <data_dir>/jobs/*/provenance.jsonl.

    `data_dir` wins when given. Deriving the location from `root` alone was
    wrong for every install that passes `--data-dir`, which is the shipped
    launchd agent's configuration: the server wrote its jobs to Application
    Support and this function read the repository's own `data/`, so the cost
    screen reported a directory the running server never touched — usually
    zero, and never the number the operator was looking for.
    """
    jobs_dir = (Path(data_dir) if data_dir is not None else default_data_dir(root)) / "jobs"
    total_calls = 0
    total_elapsed_s = 0.0
    per_engine: dict[str, dict[str, float]] = {}

    if not jobs_dir.exists():
        return CostSummary(
            total_engine_calls=0, total_elapsed_s=0.0, per_engine={}
        )

    for job_dir in sorted(jobs_dir.iterdir()):
        if not job_dir.is_dir():
            continue
        for entry in _iter_provenance_entries(job_dir):
            payload = entry.get("payload") or {}
            if not payload.get("engine_call"):
                continue
            # provenance.track_engine_call nests the engine name inside
            # usage_meta (the engine's own usage dict) — payload["engine"]
            # is never written, so read the nested key first.
            engine_name = (
                (payload.get("usage_meta") or {}).get("engine")
                or payload.get("engine")
                or "unknown"
            )
            elapsed = float(payload.get("elapsed_s") or 0.0)
            total_calls += 1
            total_elapsed_s += elapsed
            bucket = per_engine.setdefault(
                str(engine_name), {"engine_calls": 0, "elapsed_s": 0.0}
            )
            bucket["engine_calls"] += 1
            bucket["elapsed_s"] += elapsed

    return CostSummary(
        total_engine_calls=total_calls,
        total_elapsed_s=total_elapsed_s,
        per_engine=per_engine,
    )
