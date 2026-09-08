"""Research broadening enriches each fetched work at most once per run."""

from __future__ import annotations

from dataclasses import replace

from ontologylab import research_run as research_run_module
from ontologylab import research_spec
from ontologylab.connectors import paper_api
from tests.test_research_run import (
    _axis,
    _axis_fetch,
    _client,
    _install_planner,
    _need,
    _paper,
    _planned_reading,
    _run,
)


def test_broadening_reuses_prior_fulltext_enrichment(
    tmp_path,
    monkeypatch,
) -> None:
    first = _need(
        research_spec.EvidenceNeedKind.MECHANISM,
        "hardening mechanism",
    )
    second = _need(
        research_spec.EvidenceNeedKind.RESULT,
        "survival outcome",
    )
    _install_planner(
        monkeypatch,
        _planned_reading(
            (first, second),
            (
                _axis("process", "first broadening query", (first.need_id,)),
                _axis("outcome", "second broadening query", (second.need_id,)),
            ),
        ),
    )
    fake_fetch = _axis_fetch(
        {
            "first broadening query": [
                replace(
                    _paper("crossref", "10.1/first"),
                    fulltext_url="https://www.ebi.ac.uk/europepmc/webservices/rest/first/fullTextXML",
                )
            ],
            "second broadening query": [
                replace(
                    _paper("crossref", "10.1/second"),
                    fulltext_url="https://www.ebi.ac.uk/europepmc/webservices/rest/second/fullTextXML",
                )
            ],
        }
    )
    monkeypatch.setattr(research_run_module, "fetch_sources", fake_fetch)
    enrichment_calls: list[tuple[str | None, ...]] = []

    def observe_enrichment(documents):
        enrichment_calls.append(tuple(document.doi for document in documents))
        return documents, {
            "eligible": len(documents),
            "fetched": len(documents),
            "too_short": 0,
            "failed": 0,
        }

    monkeypatch.setattr(
        research_run_module,
        "enrich_with_fulltext",
        observe_enrichment,
    )

    job = _run(
        _client(tmp_path),
        sources=["crossref"],
        max_queries=2,
        fulltext=True,
    )

    assert job.status == "complete", job.error
    assert enrichment_calls == [
        ("10.1/first",),
        ("10.1/second",),
    ]


def test_broadening_fetches_newly_available_fulltext_for_the_same_work(
    tmp_path,
    monkeypatch,
) -> None:
    need = _need(research_spec.EvidenceNeedKind.MECHANISM, "full text mechanism")
    _install_planner(
        monkeypatch,
        _planned_reading(
            (need,),
            (
                _axis("initial", "initial abstract query", (need.need_id,)),
                _axis("fulltext", "new fulltext query", (need.need_id,)),
            ),
        ),
    )
    original = _paper("crossref", "10.1/shared", content_kind="abstract")
    fulltext_url = (
        "https://www.ebi.ac.uk/europepmc/webservices/rest/PMC123/fullTextXML"
    )
    later = replace(original, fulltext_url=fulltext_url)
    source_fetch = _axis_fetch({
        "initial abstract query": [original],
        "new fulltext query": [later],
    })
    monkeypatch.setattr(research_run_module, "fetch_sources", source_fetch)
    fetched: list[str] = []

    def fulltext(url: str) -> str:
        fetched.append(url)
        return "<article><body><p>" + (
            "The PaymentGateway validates cards through the FraudDetector. "
        ) * 40 + "</p></body></article>"

    monkeypatch.setattr(paper_api, "_http_get_text", fulltext)
    job = _run(
        _client(tmp_path), sources=["crossref"], max_queries=2, fulltext=True,
    )
    assert [call[1] for call in source_fetch.calls] == [
        "initial abstract query", "new fulltext query",
    ]
    assert fetched == [fulltext_url], "a cached abstract must not hide a newly available body"
    assert job.status == "complete", job.error
    assert job.totals["nodes_new"] > 0


def test_broadening_does_not_retry_the_same_failed_fulltext_route(
    tmp_path,
    monkeypatch,
) -> None:
    need = _need(research_spec.EvidenceNeedKind.MECHANISM, "full text mechanism")
    _install_planner(
        monkeypatch,
        _planned_reading(
            (need,),
            (
                _axis("initial", "first failed route", (need.need_id,)),
                _axis("retry", "second query same route", (need.need_id,)),
            ),
        ),
    )
    url = "https://www.ebi.ac.uk/europepmc/webservices/rest/PMC123/fullTextXML"
    document = replace(
        _paper("crossref", "10.1/shared", content_kind="abstract"),
        fulltext_url=url,
    )
    source_fetch = _axis_fetch({
        "first failed route": [document],
        "second query same route": [document],
    })
    monkeypatch.setattr(research_run_module, "fetch_sources", source_fetch)
    fetched: list[str] = []

    def refuse_fulltext(request_url: str) -> str:
        fetched.append(request_url)
        raise OSError("controlled fulltext failure")

    monkeypatch.setattr(paper_api, "_http_get_text", refuse_fulltext)
    job = _run(
        _client(tmp_path), sources=["crossref"], max_queries=2, fulltext=True,
    )
    assert len(source_fetch.calls) == 2
    assert fetched == [url], "broadening must not retry a previously failed route"
    assert job.status == "failed"
