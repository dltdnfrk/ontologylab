"""The research run: one topic, one job, collect then extract.

Collect and extract were two screens with nothing to decide between them —
extraction always ran over every document — so the split cost the operator a
step and bought nothing. Joining them also lets phase two extract exactly
what phase one collected, which is where the token saving is: the standing
`unprocessed_doc_ids` query is global and would pull in older documents and
any concurrent run's documents on this topic's budget.

Nothing here reaches the network. `fetch_sources` is replaced with a fake at
its own boundary, so everything below it — dedupe, insertion, the extraction
loop, cancellation, provenance — is the real thing.

What must not regress:

* `status` stays `running | complete | failed | cancelled`. The dashboard
  detects completion by the `prev === "running"` edge, so a fourth value
  like "collecting" would silently kill the completion banner and the
  automatic review-queue refresh. Phase lives in its own field.
* Gates answer in the request, not in the worker. `Job` has `error: str` and
  nowhere to put an `error_kind`.
"""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from ontologylab import paths
from ontologylab.connectors.base import RawDocument, normalize_doi
from ontologylab.connectors.paper_api import (
    SOURCE_ORDER,
    SourceFailure,
    available_sources,
)
from ontologylab.kgstore import KGStore
from ontologylab.server import jobs as jobs_module
from ontologylab.server import routes
from ontologylab.server.app import create_app
from ontologylab.server.jobs import TERMINAL_STATUSES

TOPIC = "fluorescent probe spectral overlap"

ABSTRACT = (
    "The PaymentGateway validates cards through the FraudDetector. "
    "The FraudDetector reports to the RiskEngine. "
) * 40


def _paper(source: str, doi: str | None, *, extra: str = "") -> RawDocument:
    # `normalize_doi` here because the five real parsers apply it before
    # constructing a RawDocument — `dedupe_key` compares `self.doi` as given.
    # A fake that skipped it would be testing a shape no connector produces.
    return RawDocument(
        source_kind="paper_api",
        source_uri=f"https://example.invalid/{source}/{doi or 'none'}",
        title=f"A study from {source}",
        raw_text=ABSTRACT + extra,
        doi=normalize_doi(doi),
    )


def _fake_fetch(batches, failures=()):
    """Stand in for `fetch_sources` at its own boundary — nothing below it."""

    async def _fetch(sources, query, limit=None, data_dir=None):
        _fetch.calls.append((tuple(sources), query, limit))
        return list(batches), list(failures)

    _fetch.calls = []
    return _fetch


def _client(tmp_path: Path) -> TestClient:
    data_dir = tmp_path / "data"
    routes.attach_data_dir(data_dir)
    return TestClient(create_app(data_dir=data_dir))


def _await_terminal(job, timeout: float = 30.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline and job.status not in TERMINAL_STATUSES:
        time.sleep(0.02)


def _run(client: TestClient, **body):
    payload = {"topic": TOPIC, "engine": "mock", **body}
    started = client.post("/api/research", json=payload).json()
    assert started.get("ok") is True, started
    job = routes._registry().get(started["job_id"])
    _await_terminal(job)
    return job


def _provenance(data_dir: Path) -> list[dict]:
    lines = []
    for path in data_dir.rglob("provenance.jsonl"):
        for raw in path.read_text(encoding="utf-8").splitlines():
            if raw.strip():
                lines.append(json.loads(raw))
    return lines


def _steps(data_dir: Path) -> list[str]:
    return [line.get("step") for line in _provenance(data_dir)]


# --------------------------------------------------------------------------
# The happy path
# --------------------------------------------------------------------------


def test_a_topic_becomes_documents_and_then_proposals(tmp_path, monkeypatch) -> None:
    data_dir = tmp_path / "data"
    monkeypatch.setattr(
        jobs_module,
        "fetch_sources",
        _fake_fetch([("crossref", [_paper("crossref", "10.1/a")])]),
    )
    client = _client(tmp_path)

    job = _run(client)

    assert job.status == "complete"
    store = KGStore.open(paths.kg_db_path(data_dir))
    try:
        docs = store.list_documents()
        nodes = store.conn.execute("SELECT COUNT(*) FROM nodes").fetchone()[0]
    finally:
        store.close()
    assert len(docs) == 1, "the collected document was not stored"
    assert nodes > 0, "extraction never ran on what was collected"
    assert job.totals["nodes_new"] == nodes


def test_the_job_is_one_job_not_two(tmp_path, monkeypatch) -> None:
    """Two jobs would mean two entries in the listing and two cost rows."""
    monkeypatch.setattr(
        jobs_module,
        "fetch_sources",
        _fake_fetch([("crossref", [_paper("crossref", "10.1/a")])]),
    )
    client = _client(tmp_path)

    _run(client)

    listed = client.get("/api/jobs").json()["jobs"]
    assert len(listed) == 1
    assert listed[0]["kind"] == "research"


def test_both_phases_report_progress(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(
        jobs_module,
        "fetch_sources",
        _fake_fetch([("crossref", [_paper("crossref", "10.1/a")])]),
    )
    client = _client(tmp_path)

    job = _run(client)

    log = "\n".join(job.progress)
    assert "collect phase started" in log
    assert "extract phase started" in log
    assert "research done" in log


def test_the_status_vocabulary_is_unchanged(tmp_path, monkeypatch) -> None:
    """A fourth value breaks `applyJobs`' running→terminal edge detection.

    That edge is what raises the completion banner and reloads the review
    queue, and it fails silently — the run works, the screen just never
    updates again.
    """
    monkeypatch.setattr(
        jobs_module,
        "fetch_sources",
        _fake_fetch([("crossref", [_paper("crossref", "10.1/a")])]),
    )
    client = _client(tmp_path)

    job = _run(client)

    assert job.status in {"running", "complete", "failed", "cancelled"}


def test_the_phase_is_reported_separately_from_the_status(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setattr(
        jobs_module,
        "fetch_sources",
        _fake_fetch([("crossref", [_paper("crossref", "10.1/a")])]),
    )
    client = _client(tmp_path)
    job = _run(client)

    listed = client.get("/api/jobs").json()["jobs"][0]
    single = client.get(f"/api/jobs/{job.job_id}").json()

    assert listed["phase"] == "extract"
    assert single["phase"] == "extract", "response_model dropped the field"


def test_duplicates_across_sources_collapse_to_one_document(
    tmp_path, monkeypatch
) -> None:
    """Five sources answering about one paper must not store five rows."""
    data_dir = tmp_path / "data"
    monkeypatch.setattr(
        jobs_module,
        "fetch_sources",
        _fake_fetch(
            [
                ("crossref", [_paper("crossref", "10.1/same")]),
                ("openalex", [_paper("openalex", "10.1/SAME", extra=" More.")]),
                ("europepmc", [_paper("europepmc", "10.1/same")]),
            ]
        ),
    )
    client = _client(tmp_path)

    _run(client)

    store = KGStore.open(paths.kg_db_path(data_dir))
    try:
        docs = store.list_documents()
    finally:
        store.close()
    assert len(docs) == 1, f"{len(docs)} rows stored for one paper"


def test_every_implemented_source_is_queried_by_default(
    tmp_path, monkeypatch
) -> None:
    fake = _fake_fetch([("crossref", [_paper("crossref", "10.1/a")])])
    monkeypatch.setattr(jobs_module, "fetch_sources", fake)
    client = _client(tmp_path)

    _run(client)

    [(sources, query, _limit)] = fake.calls
    assert set(sources) == set(available_sources()), (
        'an unconnected publisher source must not be queried'
    )
    assert query == TOPIC


def test_an_explicit_source_list_is_respected(tmp_path, monkeypatch) -> None:
    fake = _fake_fetch([("arxiv", [_paper("arxiv", None)])])
    monkeypatch.setattr(jobs_module, "fetch_sources", fake)
    client = _client(tmp_path)

    _run(client, sources=["arxiv"])

    [(sources, _query, _limit)] = fake.calls
    assert sources == ("arxiv",)


# --------------------------------------------------------------------------
# Phase two extracts what phase one collected — and nothing else
# --------------------------------------------------------------------------


def test_older_documents_are_not_extracted_on_this_run(
    tmp_path, monkeypatch
) -> None:
    """The token-waste guard, and the reason `doc_ids` is passed explicitly.

    `unprocessed_doc_ids` is a global query. A pre-existing unextracted
    document would be swept into this topic's budget — and with a real
    provider that is money spent on something nobody asked for.
    """
    data_dir = tmp_path / "data"
    store = KGStore.open(paths.kg_db_path(data_dir))
    try:
        stale, _ = store.insert_document(
            source_kind="upload",
            source_uri="file:///old.md",
            title="old",
            raw_text="The LegacyBilling module talks to the OldLedger. " * 40,
            content_hash="sha256:" + "b" * 64,
        )
    finally:
        store.close()

    monkeypatch.setattr(
        jobs_module,
        "fetch_sources",
        _fake_fetch([("crossref", [_paper("crossref", "10.1/new")])]),
    )
    client = _client(tmp_path)

    _run(client)

    extracted = {
        line["payload"]["doc_id"]
        for line in _provenance(data_dir)
        if line.get("step") == "extract.doc"
    }
    assert stale.id not in extracted, "an older document was extracted too"
    assert len(extracted) == 1


def test_the_extraction_budget_is_not_spent_by_the_collect_phase(
    tmp_path, monkeypatch
) -> None:
    """`Caps` reads the clock from the job's provenance, which starts early.

    Five sources at a 30s timeout would otherwise exhaust a short extraction
    budget before the first chunk, and the run would report itself out of
    time having extracted nothing.
    """
    data_dir = tmp_path / "data"

    async def _slow_fetch(sources, query, limit=None, data_dir=None):
        time.sleep(1.1)
        return [("crossref", [_paper("crossref", "10.1/a")])], []

    monkeypatch.setattr(jobs_module, "fetch_sources", _slow_fetch)
    client = _client(tmp_path)

    job = _run(client, time_budget=1.0)

    assert job.status == "complete"
    assert job.totals["nodes_new"] > 0, (
        "collect time consumed the extraction budget: the run stored "
        "documents and then extracted none of them"
    )
    ends = [
        line["payload"].get("stopped")
        for line in _provenance(data_dir)
        if line.get("step") == "research.end"
    ]
    assert ends == [""], f"extraction stopped early: {ends}"


# --------------------------------------------------------------------------
# Partial failure
# --------------------------------------------------------------------------


def test_one_dead_source_does_not_discard_the_others(tmp_path, monkeypatch) -> None:
    """Semantic Scholar 429s unauthenticated clients aggressively."""
    data_dir = tmp_path / "data"
    monkeypatch.setattr(
        jobs_module,
        "fetch_sources",
        _fake_fetch(
            [("crossref", [_paper("crossref", "10.1/a")])],
            [SourceFailure("semanticscholar", "HTTP 429", "fetch_failed")],
        ),
    )
    client = _client(tmp_path)

    job = _run(client)

    assert job.status == "complete"
    store = KGStore.open(paths.kg_db_path(data_dir))
    try:
        assert len(store.list_documents()) == 1
    finally:
        store.close()
    assert any("semanticscholar did not answer" in line for line in job.progress)


def test_a_failing_source_does_not_leak_its_error_text_to_the_browser(
    tmp_path, monkeypatch
) -> None:
    """H2 reaches here: a paper API's error carries the request URL."""
    secret = "https://api.elsevier.com/?apiKey=ELS-never-shown"
    monkeypatch.setattr(
        jobs_module,
        "fetch_sources",
        _fake_fetch(
            [("crossref", [_paper("crossref", "10.1/a")])],
            [SourceFailure("crossref", f"HTTP 500 from {secret}", "fetch_failed")],
        ),
    )
    client = _client(tmp_path)

    job = _run(client)

    assert secret not in json.dumps(job.as_status())
    assert "apiKey" not in json.dumps(job.as_status())
    # The full text is still recoverable on disk.
    assert secret in json.dumps(_provenance(tmp_path / "data"))


def test_all_sources_failing_is_a_finished_job_not_a_crash(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setattr(
        jobs_module,
        "fetch_sources",
        _fake_fetch([], [SourceFailure(name, "HTTP 429", "fetch_failed")
                         for name in available_sources()]),
    )
    client = _client(tmp_path)

    job = _run(client)

    assert job.status == "complete"
    assert job.error is None
    assert any("no source answered" in line for line in job.progress)


# --------------------------------------------------------------------------
# Gates answer in the request thread
# --------------------------------------------------------------------------


def test_an_oversized_topic_is_rejected_before_a_job_exists(tmp_path) -> None:
    client = _client(tmp_path)

    body = client.post("/api/research", json={"topic": "q" * 5000}).json()

    assert body["ok"] is False
    assert body["error_kind"] == "rejected"
    assert client.get("/api/jobs").json()["jobs"] == [], "a job was created anyway"


def test_a_topic_that_is_a_url_is_rejected(tmp_path) -> None:
    client = _client(tmp_path)

    body = client.post(
        "/api/research", json={"topic": "https://evil.example.com/x"}
    ).json()

    assert body["error_kind"] == "rejected"


def test_an_unknown_source_is_rejected(tmp_path) -> None:
    client = _client(tmp_path)

    body = client.post(
        "/api/research", json={"topic": TOPIC, "sources": ["evilsource"]}
    ).json()

    assert body["error_kind"] == "rejected"


def test_a_rejected_topic_is_still_recorded(tmp_path) -> None:
    """A boundary refusal has to leave a trace even though nothing ran."""
    client = _client(tmp_path)

    client.post("/api/research", json={"topic": "q" * 5000}).json()

    assert "research.rejected" in _steps(tmp_path / "data")


def test_offline_refuses_once_not_five_times(tmp_path, monkeypatch) -> None:
    """H3: under `return_exceptions=True` a kill switch reads as five
    unrelated source failures unless it is checked before the fan-out."""
    monkeypatch.setenv("ONTOLOGYLAB_OFFLINE", "1")
    client = _client(tmp_path)

    body = client.post("/api/research", json={"topic": TOPIC}).json()

    assert body["ok"] is False
    assert body["error_kind"] == "offline"
    assert client.get("/api/jobs").json()["jobs"] == []


def test_an_allowlist_violation_answers_before_offline_does(
    tmp_path, monkeypatch
) -> None:
    """Offline is the normal resting state; if it answered first, boundary
    violations would go unrecorded for as long as the kill switch is on."""
    monkeypatch.setenv("ONTOLOGYLAB_OFFLINE", "1")
    client = _client(tmp_path)

    body = client.post(
        "/api/research", json={"topic": TOPIC, "sources": ["evilsource"]}
    ).json()

    assert body["error_kind"] == "rejected"
    assert "research.rejected" in _steps(tmp_path / "data")


def test_the_offline_refusal_is_a_200_not_a_500(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("ONTOLOGYLAB_OFFLINE", "1")
    client = _client(tmp_path)

    assert client.post("/api/research", json={"topic": TOPIC}).status_code == 200


# --------------------------------------------------------------------------
# One at a time
# --------------------------------------------------------------------------


def test_a_second_research_run_is_refused_while_one_is_going(
    tmp_path, monkeypatch
) -> None:
    """Two runs on one topic pay twice for the same extraction."""
    gate = threading.Event()

    async def _held_fetch(sources, query, limit=None, data_dir=None):
        gate.wait(20)
        return [("crossref", [_paper("crossref", "10.1/a")])], []

    monkeypatch.setattr(jobs_module, "fetch_sources", _held_fetch)
    client = _client(tmp_path)

    first = client.post("/api/research", json={"topic": TOPIC}).json()
    second = client.post("/api/research", json={"topic": TOPIC}).json()
    gate.set()

    assert first["ok"] is True
    assert second["ok"] is False
    assert second["error_kind"] == "busy"
    assert second["job_id"] == first["job_id"], "the caller is told which run"
    _await_terminal(routes._registry().get(first["job_id"]))


def test_a_new_run_is_allowed_once_the_previous_one_finishes(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setattr(
        jobs_module,
        "fetch_sources",
        _fake_fetch([("crossref", [_paper("crossref", "10.1/a")])]),
    )
    client = _client(tmp_path)
    _run(client)

    second = client.post("/api/research", json={"topic": TOPIC}).json()

    assert second["ok"] is True
    _await_terminal(routes._registry().get(second["job_id"]))


def test_an_extraction_job_does_not_block_a_research_run(
    tmp_path, monkeypatch
) -> None:
    """The guard is about duplicate research, not about serialising the server."""
    monkeypatch.setattr(
        jobs_module,
        "fetch_sources",
        _fake_fetch([("crossref", [_paper("crossref", "10.1/a")])]),
    )
    client = _client(tmp_path)
    client.post("/api/extract", json={"engine": "mock"})

    body = client.post("/api/research", json={"topic": TOPIC}).json()

    assert body["ok"] is True
    _await_terminal(routes._registry().get(body["job_id"]))


# --------------------------------------------------------------------------
# Cancellation reaches phase one (M6)
# --------------------------------------------------------------------------


def test_cancelling_during_collect_stops_before_anything_is_stored(
    tmp_path, monkeypatch
) -> None:
    """The gap the plan named: the old checkpoint was in the chunk loop only,
    so a run cancelled during collect ignored it for the whole fetch."""
    data_dir = tmp_path / "data"
    entered = threading.Event()
    release = threading.Event()

    async def _held_fetch(sources, query, limit=None, data_dir=None):
        entered.set()
        release.wait(20)
        return [("crossref", [_paper("crossref", "10.1/a")])], []

    monkeypatch.setattr(jobs_module, "fetch_sources", _held_fetch)
    client = _client(tmp_path)

    job_id = client.post("/api/research", json={"topic": TOPIC}).json()["job_id"]
    assert entered.wait(20)
    client.post(f"/api/jobs/{job_id}/cancel")
    release.set()
    job = routes._registry().get(job_id)
    _await_terminal(job)

    assert job.status == "cancelled"
    store = KGStore.open(paths.kg_db_path(data_dir))
    try:
        assert store.list_documents() == [], "documents were stored after cancelling"
    finally:
        store.close()
    assert "extract.doc" not in _steps(data_dir), "extraction ran anyway"


def test_a_cancelled_research_run_is_not_reported_complete(
    tmp_path, monkeypatch
) -> None:
    entered = threading.Event()
    release = threading.Event()

    async def _held_fetch(sources, query, limit=None, data_dir=None):
        entered.set()
        release.wait(20)
        return [("crossref", [_paper("crossref", "10.1/a")])], []

    monkeypatch.setattr(jobs_module, "fetch_sources", _held_fetch)
    client = _client(tmp_path)

    job_id = client.post("/api/research", json={"topic": TOPIC}).json()["job_id"]
    entered.wait(20)
    client.post(f"/api/jobs/{job_id}/cancel")
    release.set()
    job = routes._registry().get(job_id)
    _await_terminal(job)

    assert job.status == "cancelled"
    assert job.error is None


# --------------------------------------------------------------------------
# Bookkeeping (M2, cost accounting, totals)
# --------------------------------------------------------------------------


def test_the_topic_is_bounded_in_the_permanent_record(tmp_path, monkeypatch) -> None:
    """M2 applies to the research run's own log line too."""
    monkeypatch.setattr(
        jobs_module,
        "fetch_sources",
        _fake_fetch([("crossref", [_paper("crossref", "10.1/a")])]),
    )
    client = _client(tmp_path)
    huge = "topic " * 200  # over MAX_PAPER_QUERY_LEN but a valid shape

    body = client.post("/api/research", json={"topic": huge}).json()

    assert body["error_kind"] == "rejected"
    assert huge not in json.dumps(_provenance(tmp_path / "data"))


def test_a_research_run_is_counted_by_the_cost_summary(
    tmp_path, monkeypatch
) -> None:
    """`cost_summary` globs every job dir; `research-*` must be picked up.

    This asserts against the *attached* data dir. The first version of this
    test asserted `total_engine_calls > 0` and passed for the wrong reason:
    `/api/cost` was reading the repository's own `data/`, which happened to
    hold real runs from manual testing. Run the suite from a clean worktree
    and it failed — the endpoint had never once looked at the directory the
    server was actually writing to.
    """
    monkeypatch.setattr(
        jobs_module,
        "fetch_sources",
        _fake_fetch([("crossref", [_paper("crossref", "10.1/a")])]),
    )
    client = _client(tmp_path)
    before = client.get("/api/cost").json()
    assert before["total_engine_calls"] == 0, (
        f"a fresh data dir already reports cost {before}; /api/cost is "
        f"reading somewhere other than the attached directory"
    )

    _run(client)

    summary = client.get("/api/cost").json()
    assert summary["total_engine_calls"] > 0, f"research run not counted: {summary}"
    assert "mock" in summary["per_engine"], summary


def test_a_totals_key_the_extractor_never_reports_does_not_kill_the_run(
    tmp_path, monkeypatch
) -> None:
    """`for key in job.totals: job.totals[key] += stats[key]` raised KeyError
    for any key `insert_proposed` does not report.

    A research run is the reason this stops being hypothetical: the obvious
    next counter is a document count, which belongs to phase one and can
    never appear in an extraction's stats. And the failure is not confined
    to bookkeeping — `_run`'s broad except turns any exception into a failed
    job, so the documents phase one already committed would be reported as
    lost work.

    The key is added to the live job during the collect phase, which is
    exactly when a phase-one counter would appear. Patching `_new_totals`
    does not work: the dataclass captured the factory at class-definition
    time, so the module attribute is no longer the one `Job()` calls.
    """
    entered = threading.Event()
    release = threading.Event()

    async def _held_fetch(sources, query, limit=None, data_dir=None):
        entered.set()
        release.wait(20)
        return [("crossref", [_paper("crossref", "10.1/a")])], []

    monkeypatch.setattr(jobs_module, "fetch_sources", _held_fetch)
    client = _client(tmp_path)

    job_id = client.post("/api/research", json={"topic": TOPIC}).json()["job_id"]
    job = routes._registry().get(job_id)
    assert entered.wait(20)
    with job._lock:
        job.totals["documents_collected"] = 0
    release.set()
    _await_terminal(job)

    assert job.status == "complete", f"a bookkeeping key failed the run: {job.error}"
    assert job.totals["nodes_new"] > 0, "extraction did not run"
    assert job.totals["documents_collected"] == 0


def test_the_job_dir_is_named_for_the_stage_not_the_topic(
    tmp_path, monkeypatch
) -> None:
    """M1: a topic string must never become a path component."""
    monkeypatch.setattr(
        jobs_module,
        "fetch_sources",
        _fake_fetch([("crossref", [_paper("crossref", "10.1/a")])]),
    )
    client = _client(tmp_path)

    job = _run(client)

    assert job.job_id.startswith("research-")
    assert TOPIC.split()[0] not in job.job_id
    assert (paths.jobs_dir(tmp_path / "data") / job.job_id).is_dir()


@pytest.mark.parametrize("topic", ["../../escape", "a/b", "topic\x00null"])
def test_a_path_shaped_topic_never_reaches_the_filesystem(tmp_path, topic) -> None:
    client = _client(tmp_path)
    before = set((tmp_path / "data").rglob("*")) if (tmp_path / "data").exists() else set()

    client.post("/api/research", json={"topic": topic})

    created = set((tmp_path / "data").rglob("*")) - before
    escaped = [p for p in created if "escape" in p.name or "null" in p.name]
    assert not escaped, f"a topic became a path: {escaped}"
