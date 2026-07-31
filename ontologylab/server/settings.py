"""Persistent local settings, engine availability, and cost aggregation."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from ontologylab.engines import resolve_available
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


def _settings_path(data_dir: Path | None = None) -> Path:
    """Where settings live for a given data directory.

    Settings belong beside the data they configure. This used to derive the
    path from `ROOT` regardless of `--data-dir`, which split every install
    that passes one — and the launcher always does, because
    `move-data-out-of-icloud.sh` moves the data out of ~/Documents. The
    result was a server reading `~/Library/.../kg.sqlite` while its settings
    came from `<repo>/data/settings.json`, and the two files diverged in
    ordinary use: an address saved in the browser landed next to a knowledge
    graph the server was not using.
    """
    base = default_data_dir() if data_dir is None else Path(data_dir)
    return base / _SETTINGS_FILENAME


def _legacy_settings_path() -> Path:
    """The pre-fix location, read once so nobody loses their settings.

    Never written. An install that saves anything gets a file in the right
    place, and this stops being consulted the moment that happens.
    """
    return default_data_dir(ROOT) / _SETTINGS_FILENAME


def default_settings() -> Settings:
    return Settings(
        default_engine=DEFAULT_ENGINE,
        default_model=DEFAULT_MODEL,
        data_dir=str(default_data_dir()),
        packs_dir=str(default_packs_dir()),
    )


def _read(path: Path) -> Settings | None:
    if not path.exists():
        return None
    try:
        return Settings(**json.loads(path.read_text(encoding="utf-8")))
    except (json.JSONDecodeError, OSError, TypeError, ValueError):
        return None


def load_settings(data_dir: Path | None = None) -> Settings:
    """Settings for `data_dir`, falling back to the old shared location.

    The fallback is what keeps this change from silently resetting an
    existing install to defaults on the first run after upgrading.
    """
    found = _read(_settings_path(data_dir))
    if found is None and Path(data_dir or default_data_dir()) != default_data_dir(ROOT):
        found = _read(_legacy_settings_path())
    return found if found is not None else default_settings()


def apply_to_environment(settings: Settings) -> None:
    """Export the settings that connectors read from the environment.

    One explicit bridge, rather than letting `connectors` import this
    module. The dependency runs server -> connectors everywhere else, and
    reversing it for one value made every source lookup read a file shared
    by every process on the machine — saving the address once in the
    browser was enough to change what unrelated code saw.

    Only set when present: an absent setting must not clear a variable the
    operator exported on purpose for this run.
    """
    from ontologylab.connectors.paper_api import SEARXNG_URL_ENV

    if settings.searxng_url:
        os.environ[SEARXNG_URL_ENV] = settings.searxng_url


def save_settings(settings: Settings, data_dir: Path | None = None) -> Settings:
    path = _settings_path(data_dir)
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
                # The same lookup the engine itself uses. A bare shutil.which
                # here answered a different question than the one the caller
                # is asking — "is it on PATH" rather than "can this server run
                # it" — and under launchd's PATH those diverge. Every CLI
                # engine then reported unavailable, the browser disabled them
                # in every picker, and the chat composer's engine fell through
                # to mock: the one engine that finds nothing in a biomedical
                # abstract. Nothing errored. The extraction simply came back
                # empty, which is also what a hard paper looks like.
                available=resolve_available(cli_name),
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
