"""Paper-API connector: offline tests (every network call is monkeypatched)."""

import asyncio

import pytest

from ontologylab import paths
from ontologylab.connectors.allowlist import NotAllowlisted
from ontologylab.connectors.paper_api import (
    PaperApiConnector,
    _build_query_url,
    parse_atom,
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


def test_fetch_checks_allowlist_before_any_io(monkeypatch):
    """fetch() must raise NotAllowlisted without ever touching the network."""
    import ontologylab.connectors.paper_api as pa

    def boom(url):  # pragma: no cover - must not be reached
        raise AssertionError("network I/O attempted for non-allowlisted query")

    monkeypatch.setattr(pa, "_fetch_atom", boom)
    connector = PaperApiConnector()

    with pytest.raises(NotAllowlisted):
        asyncio.run(connector.fetch({"source": "arxiv", "query": "quantum finance"}))
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

    monkeypatch.setattr(pa, "_fetch_atom", fake_fetch)
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

    monkeypatch.setattr(pa, "_fetch_atom", lambda url: ATOM_FIXTURE)
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

    monkeypatch.setattr(pa, "_fetch_atom", boom)
    code = run_cli(
        "collect", "--data-dir", str(tmp_path / "data"),
        "--paper-query", "quantum finance",
    )
    assert code == 2
    assert "REJECTED" in capsys.readouterr().err


def test_cli_collect_unimplemented_allowlisted_source_exits_cleanly(
    tmp_path, capsys, monkeypatch
):
    """Allowlisted-but-unimplemented source (crossref) must exit 2, not traceback."""
    import ontologylab.connectors.paper_api as pa

    def boom(url):  # pragma: no cover - must not be reached
        raise AssertionError("network I/O attempted for unimplemented source")

    monkeypatch.setattr(pa, "_fetch_atom", boom)
    code = run_cli(
        "collect", "--data-dir", str(tmp_path / "data"),
        "--paper-source", "crossref", "--paper-query", "databases",
    )
    assert code == 2
    assert "UNSUPPORTED" in capsys.readouterr().err


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

    monkeypatch.setattr(pa, "_fetch_atom", fake_fetch)
    asyncio.run(PaperApiConnector().fetch({"query": "  databases  "}))
    (url,) = seen_urls
    assert url == _build_query_url("databases", 5)  # stripped, not padded


def test_cli_collect_inputs_supplied_zero_documents_exits_zero(
    tmp_path, capsys, monkeypatch
):
    """Allowlisted query + degenerate-only feed: informative message, exit 0."""
    import ontologylab.connectors.paper_api as pa

    monkeypatch.setattr(pa, "_fetch_atom", lambda url: DEGENERATE_ONLY_FIXTURE)
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

    monkeypatch.setattr(pa, "_fetch_atom", boom)
    monkeypatch.setattr(wc, "_fetch_url", boom)

    # allowlisted URL first + non-allowlisted paper query second -> REJECTED
    code = run_cli(
        "collect", "--data-dir", str(tmp_path / "d1"),
        "--url", "https://docs.python.org/3/library/sqlite3.html",
        "--paper-query", "quantum finance",
    )
    assert code == 2
    assert "REJECTED" in capsys.readouterr().err

    # allowlisted query first + unimplemented source -> UNSUPPORTED, no fetch
    code = run_cli(
        "collect", "--data-dir", str(tmp_path / "d2"),
        "--url", "https://docs.python.org/3/library/sqlite3.html",
        "--paper-source", "crossref", "--paper-query", "databases",
    )
    assert code == 2
    assert "UNSUPPORTED" in capsys.readouterr().err


def test_cli_collect_fetch_failures_exit_cleanly(tmp_path, capsys, monkeypatch):
    """URLError and Atom ParseError end as FETCH FAILED + exit 2, no traceback."""
    import ontologylab.connectors.paper_api as pa
    from urllib.error import URLError

    def network_down(url):
        raise URLError("connection refused")

    monkeypatch.setattr(pa, "_fetch_atom", network_down)
    code = run_cli(
        "collect", "--data-dir", str(tmp_path / "d1"),
        "--paper-query", "databases",
    )
    assert code == 2
    assert "FETCH FAILED" in capsys.readouterr().err

    monkeypatch.setattr(pa, "_fetch_atom", lambda url: "<feed>truncated")
    code = run_cli(
        "collect", "--data-dir", str(tmp_path / "d2"),
        "--paper-query", "databases",
    )
    assert code == 2
    assert "FETCH FAILED" in capsys.readouterr().err
