"""Research-run source status surfacing (GAP-O4).

The collect fan-out already logged every source event; what the screen
never saw was the aggregate. Each job now carries a structured per-source
status (running/ok/failed + failure kind) fed by the same callback that
records steps, and the job detail renders it as badges with an
all-sources-failed banner.

These tests pin the backend contract: partial failure surfaces per-source
status and the failure kind, and an all-failed fan-out leaves the store
untouched while still reporting every source as failed.
"""

from __future__ import annotations

from html.parser import HTMLParser
import json
from pathlib import Path
import re

from fastapi import FastAPI
from fastapi.testclient import TestClient

from ontologylab import research_run as research_run_module
from ontologylab.connectors.base import RawDocument, normalize_doi
from ontologylab.connectors.paper_api import SourceFailure
from ontologylab.research_assessment import summarize_source_failures
from ontologylab.server.app import create_app
from ontologylab.server.jobs import TERMINAL_STATUSES

TOPIC = "fluorescent probe spectral overlap"

ABSTRACT = (
    "The PaymentGateway validates cards through the FraudDetector. "
) * 40


def _paper(source: str, doi: str | None) -> RawDocument:
    return RawDocument(
        source_kind="paper_api",
        source_uri=f"https://example.invalid/{source}/{doi or 'none'}",
        title=f"A study from {source}",
        raw_text=ABSTRACT,
        doi=normalize_doi(doi),
    )


def _fake_fetch(batches, failures=()):
    async def _fetch(
        sources,
        query,
        limit=None,
        data_dir=None,
        on_event=None,
        source_queries=None,
        search_axis="",
        query_terms=(),
    ):
        del source_queries, search_axis, query_terms
        if on_event is not None:
            for name in sources:
                on_event("source_start", name, None)
            for name, docs in batches:
                on_event("source_ok", name, len(docs))
            for failure in failures:
                on_event("source_failed", failure.source, failure.kind)
        return list(batches), list(failures)

    return _fetch


def _client(tmp_path: Path) -> TestClient:
    data_dir = tmp_path / "data"
    return TestClient(create_app(data_dir=data_dir))


def _run(client: TestClient, **body):
    # sources are pinned so the fake fetch's start/ok/failed events cover
    # exactly the set the run is asked about — with the default (all
    # sources), sources outside the fake's batches would stay "running".
    payload = {"topic": TOPIC, "engine": "mock", "sources": ["arxiv", "crossref"], **body}
    started = client.post("/api/research", json=payload).json()
    assert started.get("ok") is True, started
    app = client.app
    assert isinstance(app, FastAPI)
    job = app.state.jobs.get(started["job_id"])
    assert job is not None and job._thread is not None
    job._thread.join(timeout=30)
    assert not job._thread.is_alive()
    assert job.status in TERMINAL_STATUSES
    return job


def test_partial_failure_surfaces_per_source_status(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(
        research_run_module,
        "fetch_sources",
        _fake_fetch(
            [("arxiv", [_paper("arxiv", "10.1/a")])],
            failures=[SourceFailure("crossref", "boom", "fetch_failed")],
        ),
    )
    job = _run(_client(tmp_path))

    assert set(job.sources) == {"arxiv", "crossref"}
    assert job.sources["arxiv"]["status"] == "ok"
    assert job.sources["crossref"]["status"] == "failed"
    assert job.sources["crossref"]["detail"] == "fetch_failed"

    # the aggregate the UI derives: one answered, one failed
    statuses = [s["status"] for s in job.sources.values()]
    assert statuses.count("ok") == 1
    assert statuses.count("failed") == 1


def test_all_sources_failed_reports_every_source_and_leaves_store_untouched(
    tmp_path, monkeypatch
) -> None:
    from ontologylab.server import jobs as jobs_module

    monkeypatch.setattr(
        research_run_module,
        "fetch_sources",
        _fake_fetch(
            [],
            failures=[
                SourceFailure("arxiv", "down", "fetch_failed"),
                SourceFailure("crossref", "401", "refused"),
            ],
        ),
    )
    client = _client(tmp_path)
    before = client.get("/api/proposals?limit=1").json()["counts"]
    job = _run(client)

    # Every source failed: that is a failed run, not a clean end. Storing
    # `complete` painted "리서치 완료!" over a run that produced nothing.
    assert job.status == "failed"
    assert job.error == jobs_module.NO_SOURCES_SUMMARY
    assert set(job.sources) == {"arxiv", "crossref"}
    assert all(s["status"] == "failed" for s in job.sources.values())

    after = client.get("/api/proposals?limit=1").json()["counts"]
    assert after == before, "an all-failed run must not add documents or proposals"


def test_as_status_carries_the_sources_shape(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(
        research_run_module,
        "fetch_sources",
        _fake_fetch(
            [("arxiv", [_paper("arxiv", "10.1/b")])],
            failures=[SourceFailure("crossref", "down", "fetch_failed")],
        ),
    )
    job = _run(_client(tmp_path))

    payload = job.as_status()
    assert payload["sources"][0] == {"name": "arxiv", "status": "ok", "detail": "1"}
    assert payload["sources"][1] == {"name": "crossref", "status": "failed", "detail": "fetch_failed"}


def test_the_job_api_response_carries_sources(tmp_path, monkeypatch) -> None:
    """The JobStatus response model must not silently drop `sources`.

    Pydantic filters unknown fields out of response models — the job
    builds the list, and without a declared field the browser never sees
    it, which is the exact gap the badge band exists to close.
    """
    monkeypatch.setattr(
        research_run_module,
        "fetch_sources",
        _fake_fetch(
            [("arxiv", [_paper("arxiv", "10.1/c")])],
            failures=[SourceFailure("crossref", "boom", "fetch_failed")],
        ),
    )
    client = _client(tmp_path)
    job = _run(client)

    body = client.get(f"/api/jobs/{job.job_id}").json()
    by_name = {s["name"]: s for s in body["sources"]}
    assert by_name["arxiv"]["status"] == "ok"
    assert by_name["crossref"]["status"] == "failed"


def test_the_ui_renders_badges_and_an_all_failed_banner() -> None:
    """Execute the shipped renderer; localized prose is not the contract."""
    from ontologylab import web_assets
    from tests.test_ui_failure_honesty import _harness, _run_js

    markup = web_assets.read_asset_text("index.html")

    class SourceHTML(HTMLParser):
        def __init__(self) -> None:
            super().__init__()
            self.elements: list[tuple[str, dict[str, str | None]]] = []
            self.aggregate = ""
            self.in_aggregate = False

        def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
            attributes = dict(attrs)
            self.elements.append((tag, attributes))
            if "src-aggregate" in (attributes.get("class") or "").split():
                self.in_aggregate = True

        def handle_endtag(self, tag: str) -> None:
            if tag == "div":
                self.in_aggregate = False

        def handle_data(self, data: str) -> None:
            if self.in_aggregate:
                self.aggregate += data

    page = SourceHTML()
    page.feed(markup)
    hosts = [attrs for _, attrs in page.elements if attrs.get("id") == "job-sources"]
    assert len(hosts) == 1
    initial_hidden = "hidden" in (hosts[0].get("class") or "").split()
    cases = [
        ("empty", []),
        ("all-failed", [
            {"name": "arxiv", "status": "failed", "detail": "fetch_failed"},
            {"name": "crossref", "status": "failed", "detail": "unconfigured"},
        ]),
        ("partial-after-failure", [
            {"name": "arxiv", "status": "ok", "detail": "1"},
            {"name": "crossref", "status": "failed", "detail": "fetch_failed"},
        ]),
        ("running", [
            {"name": "arxiv", "status": "ok", "detail": "1"},
            {"name": "crossref", "status": "running"},
        ]),
        ("all-ok", [
            {"name": "arxiv", "status": "ok", "detail": "1"},
            {"name": "crossref", "status": "ok", "detail": "2"},
        ]),
        ("escaped", [
            {"name": "<img src=x onerror=boom>", "status": "failed",
             "detail": "<svg onload=boom>"},
        ]),
        ("empty-after-results", []),
    ]
    script = _harness(
        "renderJobSources", "escapeHtml",
        # Localization is deliberately not pinned; escaping is shipped code.
        extra='var FAIL_KO = {}; function toolKo(value) { return String(value); }',
    )
    script += "\nhidden['#job-sources'] = " + json.dumps(initial_hidden) + ";\n"
    script += "var cases = " + json.dumps(cases) + ";\n"
    script += """
var frames = cases.map(function (entry) {
  renderJobSources({sources: entry[1]});
  return {name: entry[0], hidden: hidden["#job-sources"], html: shown["#job-sources"] || ""};
});
console.log(JSON.stringify({frames: frames}));
"""
    frames = _run_js(script)["frames"]
    assert len(frames) == len(cases)
    for (name, sources), frame in zip(cases, frames, strict=True):
        assert frame["name"] == name
        assert frame["hidden"] is (not sources), name
        if not sources:
            continue
        rendered = SourceHTML()
        rendered.feed(frame["html"])
        classes = [
            (attrs.get("class") or "").split() for _, attrs in rendered.elements
        ]
        counts = {
            status: sum(source["status"] == status for source in sources)
            for status in ("ok", "failed", "running")
        }
        assert sum("src-badge" in names for names in classes) == len(sources), name
        for status, count in counts.items():
            assert sum("src-" + status in names for names in classes) == count, name
        assert sum("src-allfailed" in names for names in classes) == (
            1 if counts["failed"] == len(sources) else 0
        ), name
        expected_counts = [len(sources), counts["ok"]]
        expected_counts.extend(
            counts[status] for status in ("failed", "running") if counts[status]
        )
        assert [int(value) for value in re.findall(r"\d+", rendered.aggregate)] == expected_counts
        assert not any(tag in {"img", "svg", "script"} for tag, _ in rendered.elements)
        assert not any(key.startswith("on") for _, attrs in rendered.elements for key in attrs)


def test_assessment_failure_surface_keeps_kind_but_not_external_error_text() -> None:
    failures = [
        SourceFailure(
            "crossref",
            "HTTP 401 https://source.invalid/?api_key=do-not-copy",
            "fetch_failed",
        )
    ]

    degraded, summaries = summarize_source_failures(failures)

    assert degraded is True
    assert [(item.source, item.kind) for item in summaries] == [
        ("crossref", "fetch_failed")
    ]
    assert not hasattr(summaries[0], "error")
