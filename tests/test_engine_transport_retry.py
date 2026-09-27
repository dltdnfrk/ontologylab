"""Provider retries exercise the real adapter, store, caps, and provenance."""

from __future__ import annotations

import asyncio
import hashlib
from email.message import Message
from email.utils import formatdate
from http.client import RemoteDisconnected
import json
import socket
from types import SimpleNamespace
from urllib.error import HTTPError, URLError

import pytest

from ontologylab import engines, extractor, provenance as provenance_module
from ontologylab.engines import ApiEngine, EngineError, TransientEngineError
from ontologylab.extractor import run_extract_job
from ontologylab.main import build_arg_parser
from ontologylab.provenance import Provenance
from ontologylab.providers import Provider, dedicated_api_key_env
from ontologylab.server.schemas import ExtractRequest
from tests.test_engine_json_retry import GOOD
from tests.test_fulltext_run_budget import CORPUS
from tests.test_partial_chunk_failure import _insert_document, _join


class Clock:
    def __init__(self):
        self.now = 1_800_000_000.0
        self.waits = []

    def time(self):
        return self.now

    async def sleep(self, seconds):
        self.waits.append(seconds)
        self.now += seconds


class Transport:
    """Script only the external wire; count independently of engine usage."""

    def __init__(self, clock):
        self.clock = clock
        self.replies = [RemoteDisconnected("private transport detail"), GOOD]
        self.calls = 0
        self.duration = 0.25

    def post(self, url, headers, body, timeout_s):
        reply = self.replies[min(self.calls, len(self.replies) - 1)]
        self.calls += 1
        self.clock.now += self.duration
        if isinstance(reply, Exception):
            raise reply
        return {"choices": [{"message": {"content": reply}}]}


@pytest.fixture
def api(monkeypatch):
    clock = Clock()
    transport = Transport(clock)
    base = "http://127.0.0.1:12345/v1"
    provider = Provider(
        id="stub", kind="openai", base_url=base,
        api_key_env=dedicated_api_key_env("stub", base), models=("fake-model",),
    )
    monkeypatch.setenv(provider.api_key_env, "fake-key-secret")
    monkeypatch.setattr(engines, "_http_post_json", transport.post)
    monkeypatch.setattr(engines, "time", SimpleNamespace(monotonic=clock.time))
    monkeypatch.setattr(extractor, "time", SimpleNamespace(monotonic=clock.time))
    monkeypatch.setattr(provenance_module, "time", SimpleNamespace(time=clock.time))
    return ApiEngine(provider, clock=clock.time), transport, clock


def drive(store, tmp_path, api, *, cap=60, retries=2, budget=None, abort=None,
          text="AlphaBeta"):
    engine, _, clock = api
    doc, _ = store.insert_document(
        source_kind="upload", source_uri="file:///transport.txt", title="transport",
        raw_text=text, content_hash="sha256:transport",
    )
    outcome = asyncio.run(run_extract_job(
        store, engine=engine, engine_name="api:stub", model="fake-model",
        job_dir=tmp_path / "job", seed=7, doc_ids=[doc.id],
        max_engine_calls=cap, max_transport_retries=retries, time_budget=budget,
        decode_params=None, on_progress=lambda _: None, on_stats=lambda _: None,
        should_abort=abort, sleep=clock.sleep,
    ))
    return outcome, Provenance.resume(str(tmp_path / "job"), seed=7)


def http_error(code, retry_after=None):
    headers = Message()
    if retry_after is not None:
        headers["Retry-After"] = retry_after
    return HTTPError("https://private.invalid/secret", code, "private detail", headers, None)


def test_disconnect_once_then_success_counts_two_requests(store, tmp_path, api):
    # Given: one transport disconnect followed by a usable extraction.
    _, transport, clock = api
    # When: the shared extraction loop handles the actual API adapter.
    outcome, provenance = drive(store, tmp_path, api)
    # Then: a transient failure does not strand the chunk.
    assert not outcome.chunk_failed
    assert transport.calls == provenance.engine_calls == 2
    assert clock.waits == [1.0]
    assert store.conn.execute(
        "SELECT status FROM extraction_chunks"
    ).fetchone()[0] == "succeeded"


@pytest.mark.parametrize("failure", [
    RemoteDisconnected("private detail"), ConnectionResetError("private detail"),
    ConnectionAbortedError("private detail"), TimeoutError("private detail"),
    socket.timeout("private detail"), URLError(ConnectionResetError("private detail")),
    URLError(TimeoutError("private detail")),
    *[http_error(code) for code in (429, 500, 502, 503, 504)],
])
def test_persistent_transient_stops_with_typed_error(store, tmp_path, api, failure):
    # Given
    engine, transport, clock = api
    transport.replies = [failure]
    # When
    outcome, provenance = drive(store, tmp_path, api)
    # Then
    assert outcome.chunk_failed
    assert transport.calls == provenance.engine_calls == 3
    assert clock.waits == [1.0, 2.0]
    assert tuple(store.conn.execute(
        "SELECT status, error_kind FROM extraction_chunks"
    ).fetchone()) == ("failed", "engine_error")
    with pytest.raises(TransientEngineError):
        asyncio.run(engine.generate("private request body"))


@pytest.mark.parametrize("failure", [
    *[http_error(code) for code in (400, 401, 403, 404, 422, 501)],
    URLError("name resolution failed"), OSError("private detail"),
    ConnectionRefusedError("private detail"), ValueError("private detail"),
    json.JSONDecodeError("private detail", "secret-body", 0),
])
def test_non_transient_is_not_retried(store, tmp_path, api, failure):
    # Given
    _, transport, clock = api
    transport.replies = [failure, GOOD]
    # When
    outcome, provenance = drive(store, tmp_path, api)
    # Then
    assert outcome.chunk_failed
    assert transport.calls == provenance.engine_calls == 1
    assert clock.waits == []
    log = provenance.jsonl_path.read_text()
    assert all(secret not in log for secret in (
        "fake-key-secret", "private detail", "private.invalid", "secret-body",
    ))


@pytest.mark.parametrize("cap", [1, 2])
def test_retries_stop_at_request_cap_and_match_status(store, tmp_path, api, cap):
    # Given
    _, transport, clock = api
    transport.replies = [RemoteDisconnected("private detail")]
    # When
    outcome, provenance = drive(store, tmp_path, api, cap=cap)
    # Then: count from independent wire observations, JSONL, and terminal snapshot.
    assert "engine call cap reached" in outcome
    assert outcome.chunk_failed
    records = [json.loads(line) for line in provenance.jsonl_path.read_text().splitlines()]
    calls = [row for row in records if row["payload"].get("engine_call")]
    status = json.loads(provenance.status_path.read_text())
    assert transport.calls == len(calls) == status["engine_calls"] == cap
    assert status["per_step"]["extract"]["calls"] == cap
    assert status["engine_elapsed_s"] == cap * 0.25
    assert clock.waits == [1.0] * (cap - 1)


@pytest.mark.parametrize("header, expected", [
    ("999", 8.0), ("3", 3.0), ("0", 1.0), ("-3", 1.0),
    ("invalid", 1.0), ("nan", 1.0), ("inf", 1.0),
    (formatdate(1_800_000_099, usegmt=True), 8.0),
    (formatdate(1_800_000_005, usegmt=True), 4.75),
])
def test_retry_after_uses_fake_clock_and_is_capped(store, tmp_path, api, header, expected):
    # Given
    _, transport, clock = api
    transport.replies = [http_error(429, header), GOOD]
    # When
    outcome, _ = drive(store, tmp_path, api)
    # Then
    assert not outcome.chunk_failed
    assert transport.calls == 2
    assert clock.waits == [expected]


@pytest.mark.parametrize("retries, waits", [(0, []), (1, [1.0]), (5, [1, 2, 4, 8, 8])])
def test_configured_retry_limit_and_exponential_cap(store, tmp_path, api, retries, waits):
    # Given
    _, transport, clock = api
    transport.replies = [RemoteDisconnected("private detail")]
    # When
    outcome, provenance = drive(store, tmp_path, api, retries=retries)
    # Then
    assert outcome.chunk_failed
    assert transport.calls == provenance.engine_calls == retries + 1
    assert clock.waits == waits


def test_parse_retry_does_not_reset_transport_allowance(store, tmp_path, api):
    # Given: two transient retries split across the two allowed parse attempts.
    _, transport, clock = api
    transport.replies = [
        RemoteDisconnected(""), "garbage", RemoteDisconnected(""), RemoteDisconnected(""), GOOD,
    ]
    # When
    outcome, provenance = drive(store, tmp_path, api)
    # Then: the third transient cannot get another retry.
    assert outcome.chunk_failed
    assert transport.calls == provenance.engine_calls == 4
    assert clock.waits == [1, 2]


@pytest.mark.parametrize("stop", ["time", "cancel"])
def test_stop_is_rechecked_after_backoff(store, tmp_path, api, stop):
    # Given
    _, transport, clock = api
    abort = (lambda: "cancelled" if clock.waits else "") if stop == "cancel" else None
    # When
    outcome, provenance = drive(
        store, tmp_path, api, budget=1.0 if stop == "time" else None, abort=abort,
    )
    # Then
    assert ("time budget reached" if stop == "time" else "cancelled") in outcome
    assert transport.calls == provenance.engine_calls == 1
    assert clock.waits == [1]


def test_cli_and_http_retry_limits_agree():
    # Given / When
    default_cli = build_arg_parser().parse_args(["extract"])
    override_cli = build_arg_parser().parse_args(["extract", "--max-transport-retries", "0"])
    # Then
    assert default_cli.max_transport_retries == ExtractRequest().max_transport_retries == 2
    assert override_cli.max_transport_retries == ExtractRequest(max_transport_retries=0).max_transport_retries == 0
    with pytest.raises(ValueError):
        ExtractRequest(max_transport_retries=-1)
    with pytest.raises(SystemExit):
        build_arg_parser().parse_args(["extract", "--max-transport-retries", "-1"])


def test_automatic_wall_budget_includes_transports_and_waits(store, tmp_path, api):
    # Given: each request consumes its whole timeout, plus two capped waits.
    engine, transport, clock = api
    engine._timeout_s = transport.duration = 300.0
    transport.replies = [http_error(503, "999"), "garbage", http_error(503, "999"), GOOD]
    # When
    outcome, provenance = drive(store, tmp_path, api)
    # Then: the old two-request automatic wall budget would stop after call 3.
    assert outcome == "" and not outcome.chunk_failed
    assert transport.calls == provenance.engine_calls == 4
    assert clock.waits == [8, 8]


def test_fulltext_transport_retries_consume_eighteen_reserve_slots(store, tmp_path, api):
    # Given: the frozen 21-chunk corpus, one parse retry per chunk, 18 disconnects.
    engine, transport, clock = api
    engine._timeout_s = transport.duration = 300.0
    ids = []
    for path in sorted(CORPUS.glob("PMC*.txt")):
        text = path.read_text()
        doc, _ = store.insert_document(
            source_kind="upload", source_uri=path.as_uri(), title=path.stem,
            raw_text=text, content_hash="sha256:" + hashlib.sha256(text.encode()).hexdigest(),
        )
        ids.append(doc.id)
    transport.replies = []
    for index in range(21):
        if index < 18:
            transport.replies.append(RemoteDisconnected(""))
        transport.replies.extend(["malformed", "{}"])
    # When: all attempts use the unchanged 60-request cap.
    outcome = asyncio.run(run_extract_job(
        store, engine=engine, engine_name="api:stub", model="fake-model",
        job_dir=tmp_path / "job", seed=7, doc_ids=ids, max_engine_calls=60,
        time_budget=None, decode_params=None, on_progress=lambda _: None,
        on_stats=lambda _: None, should_abort=None, sleep=clock.sleep,
    ))
    # Then: no extra requests are minted for recovery.
    status = json.loads((tmp_path / "job/status.json").read_text())
    assert outcome == "" and not outcome.chunk_failed
    assert dict(store.conn.execute(
        "SELECT status, COUNT(*) FROM extraction_chunks GROUP BY status"
    )) == {"succeeded": 21}
    assert transport.calls == status["engine_calls"] == 60
    assert clock.waits == [1.0] * 18


@pytest.mark.parametrize("retries, expected_status, expected_calls", [
    (0, "failed", 1), (2, "complete", 2),
])
def test_http_limit_reaches_worker_and_terminal_counts(
    tmp_path, monkeypatch, api, retries, expected_status, expected_calls,
):
    from fastapi.testclient import TestClient
    from ontologylab.server import jobs
    from ontologylab.server.app import create_app

    # Given: a real HTTP app and worker with only transport and sleep replaced.
    engine, transport, clock = api
    data_dir = tmp_path / "data"
    doc_id = _insert_document(data_dir, "AlphaBeta")
    monkeypatch.setattr(jobs, "resolve_engine", lambda *args, **kwargs: engine)
    real_run = jobs.run_extract_job

    async def run_with_clock(*args, **kwargs):
        return await real_run(*args, **kwargs, sleep=clock.sleep)

    monkeypatch.setattr(jobs, "run_extract_job", run_with_clock)
    app = create_app(data_dir=data_dir, packs_dir=tmp_path / "packs")
    with TestClient(app) as client:
        # When: use the public route, then join the actual worker, never poll.
        response = client.post("/api/extract", json={
            "engine": "api:stub", "model": "fake-model", "doc_ids": [doc_id],
            "max_transport_retries": retries, "max_engine_calls": 2,
        })
        assert response.status_code == 202, response.text
        job_id = response.json()["job_id"]
        job = app.state.jobs.get(job_id)
        _join(job)
        result = client.get(f"/api/jobs/{job_id}").json()
    # Then: HTTP, terminal status, and each independent wire attempt agree.
    records = [json.loads(line) for line in (
        data_dir / "jobs" / job_id / "provenance.jsonl"
    ).read_text().splitlines()]
    status = json.loads((data_dir / "jobs" / job_id / "status.json").read_text())
    assert result["status"] == job.status == expected_status
    assert transport.calls == status["engine_calls"] == expected_calls
    assert len([r for r in records if r["payload"].get("engine_call")]) == expected_calls
