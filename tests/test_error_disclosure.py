"""What a failure is allowed to say, and when offline refuses.

H2 — `job.error` and the progress log reach the browser through
`as_status()` and the SSE stream. An exception message is written by whoever
raised it, and a paper API's error can carry the request URL, which is where
a publisher key would sit. Only the kind of failure escapes; the text goes to
provenance on disk.

H3 — offline is checked after the allowlist gate and before any fetch. Both
halves of that ordering are load-bearing, and each has its own test below.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from ontologylab.engines import EngineError
from ontologylab.kgstore import KGStore, KGStoreError
from ontologylab.paths import NetworkBlocked
from ontologylab.server import routes
from ontologylab.server.app import create_app
from ontologylab.server.jobs import summarize_failure

SECRET = "ELS-must-never-surface-9f3a"


def _client(tmp_path: Path) -> TestClient:
    data_dir = tmp_path / "data"
    return TestClient(create_app(data_dir=data_dir))


def _provenance_lines(data_dir: Path) -> list[dict]:
    lines: list[dict] = []
    for path in data_dir.rglob("provenance.jsonl"):
        for raw in path.read_text(encoding="utf-8").splitlines():
            if raw.strip():
                lines.append(json.loads(raw))
    return lines


# --------------------------------------------------------------------------
# H2: the summary names a kind, never the text
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("exc", "expected"),
    [
        (NetworkBlocked("blocked: https://api.x/?key=" + SECRET), "offline"),
        (EngineError("claude CLI failed on " + SECRET), "engine"),
        (KGStoreError("UNIQUE failed for " + SECRET), "store"),
        (TimeoutError("timed out fetching " + SECRET), "timed out"),
        (OSError("HTTP 429 from https://api.x/?key=" + SECRET), "network"),
        (ValueError("unparseable: " + SECRET), "ValueError"),
    ],
)
def test_a_summary_names_the_kind_and_quotes_nothing(exc, expected) -> None:
    summary = summarize_failure(exc)

    assert SECRET not in summary
    assert expected in summary


def test_a_summary_is_never_a_function_of_the_message_length() -> None:
    """The real property: the summary does not vary with its input's text.

    Asserting `len(...) < 120` only restated a property of this test's own
    constants — every branch returns a literal. Two messages of wildly
    different length and content must produce the identical summary, which
    is what "quotes nothing" actually means.
    """
    for short, long in (
        (EngineError("x"), EngineError("x" * 4000)),
        (OSError("y"), OSError("y" * 4000)),
        (RuntimeError("z"), RuntimeError("z" * 4000)),
    ):
        assert summarize_failure(short) == summarize_failure(long)


def test_an_unknown_failure_still_names_its_type_not_its_message() -> None:
    class WeirdFailure(RuntimeError):
        pass

    summary = summarize_failure(WeirdFailure("carrying " + SECRET))

    assert "WeirdFailure" in summary
    assert SECRET not in summary


def test_a_real_failing_job_records_only_the_summary(tmp_path, monkeypatch) -> None:
    """Drive `_run`, not `summarize_failure`.

    Every test above calls the summarizer directly, so none of them can tell
    whether it is wired into the path that records a failure. This one makes
    a real job fail with an exception carrying a key and reads back exactly
    what the browser would receive.
    """
    import time as _time

    from ontologylab.server.jobs import JobRegistry

    async def _explode(*args, **kwargs):
        raise OSError(f"HTTP 429 from https://api.elsevier.com/?apiKey={SECRET}")

    monkeypatch.setattr("ontologylab.server.jobs.run_extraction", _explode)
    registry = JobRegistry(tmp_path / "data")
    # A document must exist, or extraction returns before reaching the engine.
    store = KGStore.open(paths_kg(tmp_path))
    try:
        store.insert_document(
            source_kind="upload",
            source_uri="file:///n.md",
            title="n",
            raw_text="Some text to extract.",
            content_hash="sha256:" + "a" * 64,
        )
    finally:
        store.close()

    job = registry.create(
        engine="mock",
        model=None,
        doc_ids=[],
        max_engine_calls=5,
        time_budget=10.0,
        seed=0,
    )
    deadline = _time.monotonic() + 30
    while _time.monotonic() < deadline and job.status == "running":
        _time.sleep(0.05)

    assert job.status == "failed", "the job should have failed"
    status = job.as_status()
    assert SECRET not in json.dumps(status), "the key reached the browser payload"
    assert "api.elsevier.com" not in json.dumps(status)
    # The full text is still recoverable on disk.
    raw = "\n".join(
        json.dumps(line) for line in _provenance_lines(tmp_path / "data")
    )
    assert SECRET in raw, "provenance must keep the untruncated failure"


def paths_kg(tmp_path: Path) -> Path:
    from ontologylab import paths as _paths

    return _paths.kg_db_path(tmp_path / "data")


# --------------------------------------------------------------------------
# H3: the gate order
# --------------------------------------------------------------------------


def test_a_network_collect_is_refused_offline(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("ONTOLOGYLAB_OFFLINE", "1")
    client = _client(tmp_path)

    body = client.post(
        "/api/collect", json={"paper_queries": ["knowledge graphs"]}
    ).json()

    assert body["ok"] is False
    assert body["error_kind"] == "offline"


def test_offline_is_a_refusal_not_a_crash(tmp_path, monkeypatch) -> None:
    """The route promises 200 with a typed error, never a 4xx/5xx.

    Before, `NetworkBlocked` was a `RuntimeError` that no handler caught, so
    an offline collect was a 500.
    """
    monkeypatch.setenv("ONTOLOGYLAB_OFFLINE", "1")
    client = _client(tmp_path)

    response = client.post("/api/collect", json={"paper_queries": ["x"]})

    assert response.status_code == 200


def test_collecting_a_local_file_still_works_offline(tmp_path, monkeypatch) -> None:
    """The kill switch governs egress; reading a local file is not egress."""
    monkeypatch.setenv("ONTOLOGYLAB_OFFLINE", "1")
    notes = tmp_path / "notes.md"
    notes.write_text("A local research note.", encoding="utf-8")
    client = _client(tmp_path)

    body = client.post("/api/collect", json={"files": [str(notes)]}).json()

    assert body["ok"] is True


def test_an_allowlist_violation_is_still_recorded_while_offline(
    tmp_path, monkeypatch
) -> None:
    """The ordering that matters most.

    Offline is the normal resting state, so checking it first would silence
    the audit trail for a security boundary exactly while the system is most
    locked down.
    """
    monkeypatch.setenv("ONTOLOGYLAB_OFFLINE", "1")
    client = _client(tmp_path)

    body = client.post(
        "/api/collect", json={"urls": ["https://evil.example.com/x"]}
    ).json()

    assert body["error_kind"] == "rejected", "the allowlist must answer first"
    events = [line.get("step") for line in _provenance_lines(tmp_path / "data")]
    assert "collect.rejected" in events, "the violation was not recorded"


def test_the_offline_refusal_is_itself_recorded(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("ONTOLOGYLAB_OFFLINE", "1")
    client = _client(tmp_path)

    client.post("/api/collect", json={"paper_queries": ["x"]})

    events = [line.get("step") for line in _provenance_lines(tmp_path / "data")]
    assert "collect.offline" in events


def test_an_oversized_query_is_rejected_before_offline_is_consulted(
    tmp_path, monkeypatch
) -> None:
    """A bad query is actionable; "you are offline" is not the useful answer."""
    monkeypatch.setenv("ONTOLOGYLAB_OFFLINE", "1")
    client = _client(tmp_path)

    body = client.post("/api/collect", json={"paper_queries": ["x" * 5000]}).json()

    assert body["error_kind"] == "rejected"


def test_a_data_dir_file_is_rejected_before_offline_is_consulted(
    tmp_path, monkeypatch
) -> None:
    """C1 and H3 must not shadow each other."""
    monkeypatch.setenv("ONTOLOGYLAB_OFFLINE", "1")
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    secret = data_dir / "sources.json"
    secret.write_text(f'{{"api_key": "{SECRET}"}}', encoding="utf-8")
    client = _client(tmp_path)

    body = client.post("/api/collect", json={"files": [str(secret)]}).json()

    assert body["error_kind"] == "rejected"
    assert SECRET not in json.dumps(body)
