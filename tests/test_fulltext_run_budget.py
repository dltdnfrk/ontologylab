"""Full-corpus budget checks use an advancing clock, never provider calls."""

from __future__ import annotations

import asyncio
from contextlib import closing
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from ontologylab import extractor, provenance
from ontologylab.extractor import chunk_document, run_extract_job
from ontologylab.kgstore import KGStore
from ontologylab.main import build_arg_parser
from ontologylab.server.schemas import ExtractRequest

CORPUS = Path(__file__).parent / "gold/agrochem-polarity/sources/full"


class Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def time(self) -> float:
        return self.now


class SlowEngine:
    """Spend a full request timeout; optionally require each parse retry."""

    def __init__(self, clock: Clock, *, retry: bool, timeout: float = 300.0) -> None:
        self.clock = clock
        self.retry = retry
        self._timeout_s = timeout
        self.calls = 0

    async def generate(self, prompt: str, *, model: str | None = None):
        self.calls += 1
        self.clock.now += self._timeout_s
        raw = "malformed" if self.retry and self.calls % 2 else "{}"
        return raw, {}


def drive_corpus(
    tmp_path: Path, monkeypatch, request: ExtractRequest, *,
    retry: bool, timeout: float = 300.0,
):
    clock = Clock()
    monkeypatch.setattr(provenance, "time", SimpleNamespace(time=clock.time))
    monkeypatch.setattr(extractor, "time", SimpleNamespace(monotonic=clock.time))
    engine = SlowEngine(clock, retry=retry, timeout=timeout)
    with closing(KGStore.open(tmp_path / "kg.sqlite")) as store:
        ids = []
        for path in sorted(CORPUS.glob("PMC*.txt")):
            text = path.read_text(encoding="utf-8")
            doc, _ = store.insert_document(
                source_kind="upload", source_uri=path.as_uri(), title=path.stem,
                raw_text=text,
                content_hash="sha256:" + hashlib.sha256(text.encode()).hexdigest(),
            )
            ids.append(doc.id)
        outcome = asyncio.run(run_extract_job(
            store, engine=engine, engine_name="fake", model="fake",
            job_dir=tmp_path / "job", seed=7, doc_ids=ids,
            max_engine_calls=request.max_engine_calls, time_budget=request.time_budget,
            decode_params=None, on_progress=lambda _line: None,
            on_stats=lambda _stats: None, should_abort=None,
        ))
        counts = dict(store.conn.execute(
            "SELECT status, COUNT(*) FROM extraction_chunks GROUP BY status"
        ).fetchall())
    status = json.loads((tmp_path / "job/status.json").read_text())
    return outcome, engine.calls, counts, status


def test_sixty_three_chunk_plan_fits_three_capped_runs(tmp_path, monkeypatch) -> None:
    # Given: the frozen five-paper corpus, unchanged chunker, and one retry
    # on EVERY chunk at the full provider timeout (not the measured mean).
    chunks = [len(chunk_document(path.read_text())) for path in sorted(CORPUS.glob("PMC*.txt"))]
    assert chunks == [4, 4, 4, 5, 4]
    completed = 0
    for run in range(3):
        request = ExtractRequest(max_engine_calls=60)
        # When: use the same shared job entry as HTTP and CLI.
        outcome, calls, counts, status = drive_corpus(
            tmp_path / str(run), monkeypatch, request, retry=True,
        )
        # Then: all 21 chunks complete in 42 requests, independently capped.
        assert outcome == "" and not outcome.chunk_failed
        assert counts == {"succeeded": 21}
        assert calls == status["engine_calls"] == 42
        assert calls <= 60
        completed += counts["succeeded"]
    assert completed == 63


def test_explicit_short_budget_is_not_silently_extended(tmp_path, monkeypatch) -> None:
    # Given / When: the trial's explicit 600-second limit remains binding.
    outcome, calls, counts, _ = drive_corpus(
        tmp_path, monkeypatch, ExtractRequest(max_engine_calls=60, time_budget=600),
        retry=False,
    )
    # Then
    assert "time budget reached" in outcome
    assert calls == counts["succeeded"] == 2


def test_automatic_time_budget_does_not_relax_request_cap(tmp_path, monkeypatch) -> None:
    # Given / When: too few requests to complete the corpus, even without retry.
    outcome, calls, counts, status = drive_corpus(
        tmp_path, monkeypatch, ExtractRequest(max_engine_calls=5), retry=False,
    )
    # Then: the sixth request must not start.
    assert "engine call cap reached" in outcome
    assert calls == status["engine_calls"] == counts["succeeded"] == 5


def test_automatic_budget_uses_configured_request_timeout(tmp_path, monkeypatch) -> None:
    # Given / When: a caller selected a timeout longer than the engine default.
    outcome, calls, counts, _ = drive_corpus(
        tmp_path, monkeypatch, ExtractRequest(max_engine_calls=60),
        retry=True, timeout=600.0,
    )
    # Then: the wall cap must scale with it, not with a stale constant.
    assert outcome == ""
    assert calls == 42
    assert counts == {"succeeded": 21}


@pytest.mark.parametrize("seconds", [None, 600.0])
def test_cli_and_http_agree_on_automatic_or_explicit_budget(seconds) -> None:
    # Given / When: both entry surfaces select the same budget mode.
    args = ["extract"] + ([] if seconds is None else ["--time-budget", str(seconds)])
    cli = build_arg_parser().parse_args(args)
    http = ExtractRequest() if seconds is None else ExtractRequest(time_budget=seconds)
    # Then
    assert cli.time_budget == http.time_budget == seconds
