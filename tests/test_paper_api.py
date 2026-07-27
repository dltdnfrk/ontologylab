"""Paper-API connector: offline tests (every network call is monkeypatched)."""

import asyncio

import pytest

from ontologylab import paths
from ontologylab.connectors.allowlist import NotAllowlisted
from ontologylab.connectors.paper_api import (
    PaperApiConnector,
    _build_crossref_url,
    _build_query_url,
    parse_atom,
    parse_crossref,
)
from ontologylab.kgstore import KGStore
from ontologylab.main import main

ATOM_FIXTURE = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <title>ArXiv Query: search_query=all:databases</title>
  <entry>
    <id>http://arxiv.org/abs/2401.00001v1</id>
    <title>Consensus  Protocols for
      Distributed Key-Value Stores</title>
    <summary>We survey quorum-based consensus protocols and evaluate their
      latency/availability trade-offs in replicated key-value stores.</summary>
  </entry>
  <entry>
    <id>http://arxiv.org/abs/2402.00002v2</id>
    <title>Learned Cost Models for Query Optimizers</title>
    <summary>A study of cardinality-estimation errors and how learned cost
      models change join-order selection in relational query optimizers.</summary>
  </entry>
  <entry>
    <id>http://arxiv.org/abs/2403.00003v1</id>
    <title>  </title>
    <summary>  </summary>
  </entry>
</feed>
"""


def run_cli(*argv) -> int:
    with pytest.raises(SystemExit) as exc:
        main(list(argv))
    return exc.value.code


def test_parse_atom_extracts_entries_and_skips_degenerate():
    docs = parse_atom(ATOM_FIXTURE)
    assert len(docs) == 2  # empty-title-AND-empty-summary entry skipped
    for doc in docs:
        assert doc.source_kind == "paper_api"
        assert doc.source_uri.startswith("http://arxiv.org/abs/")
        assert doc.raw_text.strip()
        assert doc.title in doc.raw_text
    first, second = docs
    # whitespace-normalized title, raw_text = title + blank line + abstract
    assert first.title == "Consensus Protocols for Distributed Key-Value Stores"
    assert "quorum-based consensus protocols" in first.raw_text
    assert second.title == "Learned Cost Models for Query Optimizers"
    assert "cardinality-estimation errors" in second.raw_text
    assert second.source_uri == "http://arxiv.org/abs/2402.00002v2"


CROSSREF_FIXTURE = """{
  "status": "ok",
  "message": {
    "items": [
      {
        "DOI": "10.1145/1327452.1327492",
        "URL": "https://doi.org/10.1145/1327452.1327492",
        "title": ["MapReduce: simplified data processing on large clusters"],
        "abstract": "<jats:p>MapReduce is a <jats:italic>programming model</jats:italic> for processing large data sets.</jats:p>"
      },
      {
        "DOI": "10.1109/tse.1976.233837",
        "title": ["A Complexity Measure"],
        "abstract": "Describes a graph-theoretic complexity measure for programs."
      },
      {
        "DOI": "10.0/no-title-no-abstract"
      }
    ]
  }
}"""


def test_parse_crossref_extracts_items_and_strips_markup():
    docs = parse_crossref(CROSSREF_FIXTURE)
    assert len(docs) == 2  # third item: no title AND no abstract -> skipped
    first, second = docs
    assert first.source_kind == "paper_api"
    assert first.title == "MapReduce: simplified data processing on large clusters"
    # JATS markup stripped to plain text
    assert "<jats:" not in first.raw_text
    assert "programming model for processing" in first.raw_text
    assert first.source_uri == "https://doi.org/10.1145/1327452.1327492"
    # second item has no URL -> source_uri synthesized from DOI
    assert second.source_uri == "https://doi.org/10.1109/tse.1976.233837"


def test_parse_crossref_rejects_bad_json():
    with pytest.raises(ValueError):
        parse_crossref("not json at all")


def test_fetch_crossref_source_uses_json_endpoint(monkeypatch):
    import ontologylab.connectors.paper_api as pa

    seen_urls: list[str] = []

    def fake_fetch(url):
        seen_urls.append(url)
        return CROSSREF_FIXTURE

    monkeypatch.setattr(pa, "_http_get_text", fake_fetch)
    docs = asyncio.run(
        PaperApiConnector().fetch(
            {"source": "crossref", "query": "databases", "limit": 3}
        )
    )
    assert len(docs) == 2
    (url,) = seen_urls
    assert url == _build_crossref_url("databases", 3)
    assert "api.crossref.org/works" in url
    assert "rows=3" in url


def test_fetch_crossref_still_allowlist_gated(monkeypatch):
    import ontologylab.connectors.paper_api as pa

    def boom(url):  # pragma: no cover
        raise AssertionError("network I/O attempted for non-allowlisted query")

    monkeypatch.setattr(pa, "_http_get_text", boom)
    with pytest.raises(NotAllowlisted):
        asyncio.run(
            PaperApiConnector().fetch(
                {"source": "crossref", "query": "https://evil.example/x"}
            )
        )


def test_fetch_checks_allowlist_before_any_io(monkeypatch):
    """fetch() must raise NotAllowlisted without ever touching the network."""
    import ontologylab.connectors.paper_api as pa

    def boom(url):  # pragma: no cover - must not be reached
        raise AssertionError("network I/O attempted for non-allowlisted query")

    monkeypatch.setattr(pa, "_http_get_text", boom)
    connector = PaperApiConnector()

    with pytest.raises(NotAllowlisted):
        asyncio.run(connector.fetch({"source": "arxiv", "query": "https://evil.example/x"}))
    with pytest.raises(NotAllowlisted):
        asyncio.run(
            connector.fetch({"source": "unknown-source", "query": "databases"})
        )


def test_fetch_allowlisted_query_parses_and_clamps_limit(monkeypatch):
    import ontologylab.connectors.paper_api as pa

    seen_urls: list[str] = []

    def fake_fetch(url):
        seen_urls.append(url)
        return ATOM_FIXTURE

    monkeypatch.setattr(pa, "_http_get_text", fake_fetch)
    connector = PaperApiConnector()
    assert connector.name() == "paper_api"

    docs = asyncio.run(
        connector.fetch({"source": "arxiv", "query": "databases", "limit": 999})
    )
    assert len(docs) == 2
    assert {d.source_kind for d in docs} == {"paper_api"}
    (url,) = seen_urls
    assert url == _build_query_url("databases", 25)  # 999 clamped to 25
    assert "search_query=all:databases" in url
    assert "max_results=25" in url

    # lower bound clamp
    seen_urls.clear()
    asyncio.run(connector.fetch({"query": "databases", "limit": 0}))
    assert "max_results=1" in seen_urls[0]


def test_cli_collect_paper_query_inserts_and_dedups(tmp_path, monkeypatch):
    import ontologylab.connectors.paper_api as pa

    monkeypatch.setattr(pa, "_http_get_text", lambda url: ATOM_FIXTURE)
    data = str(tmp_path / "data")

    assert run_cli("collect", "--data-dir", data, "--paper-query", "databases") == 0
    # rerun: identical content hashes -> dedup, no new documents
    assert run_cli("collect", "--data-dir", data, "--paper-query", "databases") == 0

    store = KGStore.open(paths.kg_db_path(tmp_path / "data"))
    try:
        docs = store.list_documents()
    finally:
        store.close()
    assert len(docs) == 2
    assert {d.source_kind for d in docs} == {"paper_api"}


def test_cli_collect_rejects_non_allowlisted_paper_query(tmp_path, capsys, monkeypatch):
    import ontologylab.connectors.paper_api as pa

    def boom(url):  # pragma: no cover - must not be reached
        raise AssertionError("network I/O attempted for non-allowlisted query")

    monkeypatch.setattr(pa, "_http_get_text", boom)
    code = run_cli(
        "collect", "--data-dir", str(tmp_path / "data"),
        "--paper-query", "https://evil.example/x",
    )
    assert code == 2
    assert "REJECTED" in capsys.readouterr().err


def test_cli_collect_crossref_source_inserts_documents(
    tmp_path, capsys, monkeypatch
):
    """crossref is now a real fetcher: an allowlisted query ingests rows."""
    import ontologylab.connectors.paper_api as pa

    monkeypatch.setattr(pa, "_http_get_text", lambda url: CROSSREF_FIXTURE)
    data = str(tmp_path / "data")
    code = run_cli(
        "collect", "--data-dir", data,
        "--paper-source", "crossref", "--paper-query", "databases",
    )
    assert code == 0
    store = KGStore.open(paths.kg_db_path(tmp_path / "data"))
    try:
        docs = store.list_documents()
        assert len(docs) == 2
        assert all(d.source_kind == "paper_api" for d in docs)
    finally:
        store.close()


def test_check_source_implemented_still_guards_unimplemented():
    """The UNSUPPORTED guard remains for any future source added to the
    allowlist before a fetcher exists (all current sources are implemented)."""
    from ontologylab.connectors.paper_api import (
        IMPLEMENTED_SOURCES,
        UnsupportedPaperSource,
        check_source_implemented,
    )

    assert IMPLEMENTED_SOURCES == frozenset({
        # keyless
        "arxiv", "crossref", "openalex", "semanticscholar", "europepmc",
        "clinicaltrials",
        # publisher APIs (keyed) — implemented, but only queryable once a
        # credential is connected; see `available_sources`.
        "elsevier", "springer", "core",
    })
    with pytest.raises(UnsupportedPaperSource):
        check_source_implemented("not-a-real-source")


NO_ID_ENTRY_FIXTURE = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <title>Orphan Without Identifier</title>
    <summary>Has a title and a summary but no id element at all.</summary>
  </entry>
</feed>
"""

DEGENERATE_ONLY_FIXTURE = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <title>  </title>
    <summary>
    </summary>
  </entry>
  <entry>
    <title>No Provenance</title>
    <summary>Entry without an id is skipped too.</summary>
  </entry>
</feed>
"""


def test_parse_atom_skips_entry_without_id():
    """No <id> -> no source_uri -> no provenance -> entry must never insert."""
    assert parse_atom(NO_ID_ENTRY_FIXTURE) == []


def test_build_query_url_uses_https():
    assert _build_query_url("databases", 5).startswith(
        "https://export.arxiv.org/api/query?"
    )


def test_fetch_strips_query_before_allowlist_and_url(monkeypatch):
    """The query is stripped ONCE in fetch: allowlist and URL see same text."""
    import ontologylab.connectors.paper_api as pa

    seen_urls: list[str] = []

    def fake_fetch(url):
        seen_urls.append(url)
        return ATOM_FIXTURE

    monkeypatch.setattr(pa, "_http_get_text", fake_fetch)
    asyncio.run(PaperApiConnector().fetch({"query": "  databases  "}))
    (url,) = seen_urls
    assert url == _build_query_url("databases", 5)  # stripped, not padded


def test_cli_collect_inputs_supplied_zero_documents_exits_zero(
    tmp_path, capsys, monkeypatch
):
    """Allowlisted query + degenerate-only feed: informative message, exit 0."""
    import ontologylab.connectors.paper_api as pa

    monkeypatch.setattr(pa, "_http_get_text", lambda url: DEGENERATE_ONLY_FIXTURE)
    data = str(tmp_path / "data")
    code = run_cli("collect", "--data-dir", data, "--paper-query", "databases")
    assert code == 0
    assert "no documents matched" in capsys.readouterr().out

    store = KGStore.open(paths.kg_db_path(tmp_path / "data"))
    try:
        assert store.list_documents() == []
    finally:
        store.close()


def test_cli_collect_mixed_run_validates_all_gates_before_any_fetch(
    tmp_path, capsys, monkeypatch
):
    """One bad input in a mixed run rejects BEFORE any network I/O happens."""
    import ontologylab.connectors.paper_api as pa
    import ontologylab.connectors.web_crawl as wc

    def boom(url):  # pragma: no cover - must not be reached
        raise AssertionError("network I/O attempted despite failed pre-validation")

    monkeypatch.setattr(pa, "_http_get_text", boom)
    monkeypatch.setattr(wc, "_fetch_url", boom)

    # allowlisted URL first + non-allowlisted paper query second -> REJECTED
    code = run_cli(
        "collect", "--data-dir", str(tmp_path / "d1"),
        "--url", "https://docs.python.org/3/library/sqlite3.html",
        "--paper-query", "https://evil.example/x",
    )
    assert code == 2
    assert "REJECTED" in capsys.readouterr().err

    # allowlisted URL first + non-allowlisted SOURCE second -> REJECTED,
    # no fetch (the source gate also runs before any network I/O)
    code = run_cli(
        "collect", "--data-dir", str(tmp_path / "d2"),
        "--url", "https://docs.python.org/3/library/sqlite3.html",
        "--paper-source", "semantic-scholar", "--paper-query", "databases",
    )
    assert code == 2
    assert "REJECTED" in capsys.readouterr().err


def test_cli_collect_fetch_failures_exit_cleanly(tmp_path, capsys, monkeypatch):
    """URLError and Atom ParseError end as FETCH FAILED + exit 2, no traceback."""
    import ontologylab.connectors.paper_api as pa
    from urllib.error import URLError

    def network_down(url):
        raise URLError("connection refused")

    monkeypatch.setattr(pa, "_http_get_text", network_down)
    code = run_cli(
        "collect", "--data-dir", str(tmp_path / "d1"),
        "--paper-query", "databases",
    )
    assert code == 2
    assert "FETCH FAILED" in capsys.readouterr().err

    monkeypatch.setattr(pa, "_http_get_text", lambda url: "<feed>truncated")
    code = run_cli(
        "collect", "--data-dir", str(tmp_path / "d2"),
        "--paper-query", "databases",
    )
    assert code == 2
    assert "FETCH FAILED" in capsys.readouterr().err
