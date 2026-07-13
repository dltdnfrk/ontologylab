"""Adversarial in-process CLI/red-team cases for the paper_api change set.

Every fetch-dependent path monkeypatches paper_api._fetch_atom (the sole
network touchpoint); the autouse conftest guard makes any real socket
attempt an immediate failure.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET

import pytest

import qa_redteam.fixtures_atom as fx
import ontologylab.connectors.paper_api as pa
from qa_redteam.qa_helpers import (
    list_documents,
    read_raw_text,
    record_case,
    run_main_inprocess,
)


def _collect(case_id, data_dir, *extra):
    return run_main_inprocess(case_id, ["collect", "--data-dir", str(data_dir), *extra])


def _patch_feed(monkeypatch, body, seen=None):
    def fake_fetch(url):
        if seen is not None:
            seen.append(url)
        return body

    monkeypatch.setattr(pa, "_fetch_atom", fake_fetch)


def _boom_fetch(monkeypatch):
    def boom(url):  # pragma: no cover - must never be reached
        raise AssertionError(f"network touchpoint reached for {url!r}")

    monkeypatch.setattr(pa, "_fetch_atom", boom)


# ---------------------------------------------------------------------------
# C1 — deny-by-default allowlist / injection
# ---------------------------------------------------------------------------


def test_rt_c1_01_substring_or_query_rejected(tmp_path, monkeypatch):
    _boom_fetch(monkeypatch)
    r = _collect("RT-C1-01", tmp_path / "d", "--paper-query", "databases OR secrets")
    record_case(
        id="RT-C1-01",
        contractRef="C1",
        scenario="query 'databases OR secrets' (allowlisted term as substring only)",
        expected="REJECTED, exit 2, zero network touchpoints",
        actual=f"exit={r['exit_code']} stderr={r['stderr'].strip()!r}",
        verdict="passed" if r["exit_code"] == 2 and "REJECTED" in r["stderr"] else "failed",
    )
    assert r["exit_code"] == 2
    assert "REJECTED" in r["stderr"]


def test_rt_c1_02_case_whitespace_normalization_asymmetry(tmp_path, monkeypatch):
    """'  DataBases  ' passes the allowlist (strip+lower); fetch now strips
    the query ONCE, so allowlist check and URL are built from the same
    stripped text (case still preserved in the URL). Prove encoding safety."""
    seen: list[str] = []
    _patch_feed(monkeypatch, fx.GOOD_FEED, seen)
    r = _collect("RT-C1-02", tmp_path / "d", "--paper-query", "  DataBases  ")
    assert r["exit_code"] == 0
    (url,) = seen
    assert url == pa._build_query_url("DataBases", 5)
    # quote_plus-encoded: no raw spaces, no raw '&' or '=' from the query part
    query_part = url.split("search_query=all:")[1].split("&start=")[0]
    assert query_part == "DataBases"
    ok = " " not in query_part and "&" not in query_part
    record_case(
        id="RT-C1-02",
        contractRef="C1",
        scenario="query '  DataBases  ' — fetch strips once; allowlist additionally lowercases for matching",
        expected="either canonicalized or safely URL-encoded; no injection surface",
        actual=f"query stripped in fetch before allowlist+URL; URL sends quote_plus(stripped)={query_part!r} (safe encoding, case preserved)",
        verdict="passed" if ok else "failed",
    )
    assert ok


def test_rt_c1_03_source_injection_rejected(tmp_path, monkeypatch):
    _boom_fetch(monkeypatch)
    r = _collect(
        "RT-C1-03", tmp_path / "d",
        "--paper-source", "arxiv OR crossref", "--paper-query", "databases",
    )
    record_case(
        id="RT-C1-03",
        contractRef="C1",
        scenario="--paper-source 'arxiv OR crossref' (injection through source field)",
        expected="REJECTED, exit 2, before any network",
        actual=f"exit={r['exit_code']} stderr={r['stderr'].strip()!r}",
        verdict="passed" if r["exit_code"] == 2 and "REJECTED" in r["stderr"] else "failed",
    )
    assert r["exit_code"] == 2
    assert "REJECTED" in r["stderr"]


def test_rt_c1_04_url_injection_via_query(tmp_path, monkeypatch):
    _boom_fetch(monkeypatch)
    r = _collect(
        "RT-C1-04", tmp_path / "d", "--paper-query", "databases&max_results=9999"
    )
    rejected = r["exit_code"] == 2 and "REJECTED" in r["stderr"]
    # Defense-in-depth proof: even if the allowlist ever admitted it, the
    # query is quote_plus-encoded so '&'/'=' cannot split URL parameters.
    url = pa._build_query_url("databases&max_results=9999", 5)
    encoded_safely = "%26" in url and url.count("max_results=") == 1
    record_case(
        id="RT-C1-04",
        contractRef="C1",
        scenario="query 'databases&max_results=9999' (URL parameter injection attempt)",
        expected="rejected by allowlist OR safely URL-encoded (prove which)",
        actual=(
            f"REJECTED by allowlist (exit={r['exit_code']}); additionally "
            f"_build_query_url percent-encodes '&' -> {url!r}"
        ),
        verdict="passed" if rejected and encoded_safely else "failed",
    )
    assert rejected
    assert encoded_safely


def test_rt_c1_05_empty_query_rejected(tmp_path, monkeypatch):
    _boom_fetch(monkeypatch)
    r = _collect("RT-C1-05", tmp_path / "d", "--paper-query", "")
    record_case(
        id="RT-C1-05",
        contractRef="C1",
        scenario="empty query string ''",
        expected="REJECTED, exit 2 (empty string is not on the positive list)",
        actual=f"exit={r['exit_code']} stderr={r['stderr'].strip()!r}",
        verdict="passed" if r["exit_code"] == 2 and "REJECTED" in r["stderr"] else "failed",
    )
    assert r["exit_code"] == 2
    assert "REJECTED" in r["stderr"]


def test_rt_c1_06_unicode_homoglyph_rejected(tmp_path, monkeypatch):
    _boom_fetch(monkeypatch)
    homoglyph = "d\u0430tabases"  # Cyrillic 'а'
    r = _collect("RT-C1-06", tmp_path / "d", "--paper-query", homoglyph)
    record_case(
        id="RT-C1-06",
        contractRef="C1",
        scenario="unicode homoglyph query 'dаtabases' (Cyrillic а)",
        expected="REJECTED — exact-match positive list must not fold homoglyphs",
        actual=f"exit={r['exit_code']} stderr={r['stderr'].strip()!r}",
        verdict="passed" if r["exit_code"] == 2 and "REJECTED" in r["stderr"] else "failed",
    )
    assert r["exit_code"] == 2


def test_rt_c1_07_uppercase_source_rejected(tmp_path, monkeypatch):
    """Source matching is exact (no strip/lower) while query IS normalized —
    asymmetric, but asymmetry errs on the deny side, so it is safe."""
    _boom_fetch(monkeypatch)
    r = _collect(
        "RT-C1-07", tmp_path / "d", "--paper-source", "ARXIV",
        "--paper-query", "databases",
    )
    record_case(
        id="RT-C1-07",
        contractRef="C1",
        scenario="--paper-source 'ARXIV' (uppercase; source is NOT normalized unlike query)",
        expected="deny-by-default: unknown-cased source rejected before network",
        actual=f"exit={r['exit_code']} stderr={r['stderr'].strip()!r}",
        verdict="passed" if r["exit_code"] == 2 and "REJECTED" in r["stderr"] else "failed",
    )
    assert r["exit_code"] == 2


# ---------------------------------------------------------------------------
# C2 — malformed Atom XML must fail loudly or skip safely, never insert garbage
# ---------------------------------------------------------------------------


def test_rt_c2_01_truncated_xml_clean_fetch_failed_no_rows(tmp_path, monkeypatch):
    _patch_feed(monkeypatch, fx.TRUNCATED_FEED)
    data = tmp_path / "d"
    r = _collect("RT-C2-01", data, "--paper-query", "databases")
    docs = list_documents(data)
    clean = (
        r["exception"] is None
        and r["exit_code"] == 2
        and "FETCH FAILED" in r["stderr"]
    )
    record_case(
        id="RT-C2-01",
        contractRef="C2",
        scenario="truncated (not well-formed) Atom XML from the API",
        expected="clean CLI failure (exit 2, FETCH FAILED on stderr); zero rows inserted",
        actual=(
            f"exit={r['exit_code']} exception={r['exception']!r} "
            f"stderr={r['stderr'].strip()!r}; rows inserted={len(docs)} "
            f"(ParseError now handled in cmd_collect, no raw traceback)"
        ),
        verdict="passed" if clean and not docs else "failed",
    )
    assert clean
    assert docs == []


def test_rt_c2_02_wrong_namespace_no_rows(tmp_path, monkeypatch):
    _patch_feed(monkeypatch, fx.WRONG_NAMESPACE_FEED)
    data = tmp_path / "d"
    r = _collect("RT-C2-02", data, "--paper-query", "databases")
    docs = list_documents(data)
    ok = (
        r["exit_code"] == 0
        and "no documents matched" in r["stdout"]
        and not docs
    )
    record_case(
        id="RT-C2-02",
        contractRef="C2",
        scenario="well-formed feed in a non-Atom namespace",
        expected="no entries parsed; no garbage rows; informative empty-result exit 0",
        actual=(
            f"0 entries -> 'no documents matched' exit={r['exit_code']}; rows={len(docs)} "
            f"(inputs WERE supplied, so an empty feed is an empty result, not the "
            f"'nothing to collect' usage error)"
        ),
        verdict="passed" if ok else "failed",
    )
    assert ok


def test_rt_c2_03_deeply_nested_small_no_rows(tmp_path, monkeypatch):
    _patch_feed(monkeypatch, fx.DEEP_NESTED_FEED)
    data = tmp_path / "d"
    r = _collect("RT-C2-03", data, "--paper-query", "databases")
    docs = list_documents(data)
    # parse success -> empty-result exit 0; parser refusal -> clean exit 2
    safe = r["exception"] is None and r["exit_code"] in (0, 2) and not docs
    record_case(
        id="RT-C2-03",
        contractRef="C2",
        scenario=f"deeply nested ({fx._DEPTH} levels) but small XML document",
        expected="parser survives (empty result, exit 0) or fails cleanly (exit 2); zero rows, no traceback",
        actual=f"exit={r['exit_code']} exception={r['exception']!r} rows={len(docs)}",
        verdict="passed" if safe else "failed",
    )
    assert safe


def test_rt_c2_04_entry_without_id_never_inserted(tmp_path, monkeypatch):
    """Regression guard: an entry with title+abstract but no <id> element
    (no source_uri -> no provenance) must never become a document row."""
    _patch_feed(monkeypatch, fx.NO_ID_ENTRY_FEED)
    data = tmp_path / "d"
    r = _collect("RT-C2-04", data, "--paper-query", "databases")
    docs = list_documents(data)
    record_case(
        id="RT-C2-04",
        contractRef="C2",
        scenario="Atom entry with title+summary but NO <id> element",
        expected="entry skipped in parse_atom; NO row inserted (empty feed -> exit 0)",
        actual=(
            f"exit={r['exit_code']}; {len(docs)} row(s) inserted; "
            f"source_uri values={[d.source_uri for d in docs]!r}"
        ),
        verdict="passed" if not docs and r["exit_code"] == 0 else "failed",
    )
    assert r["exit_code"] == 0
    assert docs == [], "provenance gap regressed: id-less entry was inserted"


def test_rt_c2_05_html_error_pages(tmp_path, monkeypatch):
    # (a) well-formed HTML: parses as XML, zero Atom entries, no rows, exit 0
    data_a = tmp_path / "a"
    _patch_feed(monkeypatch, fx.HTML_ERROR_WELLFORMED)
    ra = _collect("RT-C2-05a", data_a, "--paper-query", "databases")
    docs_a = list_documents(data_a)
    # (b) real-world malformed HTML: ParseError -> clean FETCH FAILED exit 2
    data_b = tmp_path / "b"
    _patch_feed(monkeypatch, fx.HTML_ERROR_MALFORMED)
    rb = _collect("RT-C2-05b", data_b, "--paper-query", "databases")
    docs_b = list_documents(data_b)
    ok = (
        ra["exit_code"] == 0 and not docs_a
        and rb["exception"] is None
        and rb["exit_code"] == 2
        and "FETCH FAILED" in rb["stderr"]
        and not docs_b
    )
    record_case(
        id="RT-C2-05",
        contractRef="C2",
        scenario="API returns an HTML error page (well-formed and malformed variants)",
        expected="no garbage rows; clean empty result (exit 0) or clean FETCH FAILED (exit 2)",
        actual=(
            f"well-formed: exit={ra['exit_code']} rows={len(docs_a)}; "
            f"malformed: exit={rb['exit_code']} stderr={rb['stderr'].strip()!r} rows={len(docs_b)}"
        ),
        verdict="passed" if ok else "failed",
    )
    assert ok


def test_rt_c2_06_small_internal_entity_expansion(tmp_path, monkeypatch):
    _patch_feed(monkeypatch, fx.ENTITY_FEED)
    data = tmp_path / "d"
    r = _collect("RT-C2-06", data, "--paper-query", "databases")
    docs = list_documents(data)
    if docs:
        raw = read_raw_text(data, docs[0])
        detail = f"1 row inserted; expanded summary present={'expandme' in raw}"
        safe = r["exit_code"] == 0 and len(docs) == 1 and raw.strip()
    else:
        detail = f"no rows; exception={r['exception']!r}"
        safe = r["exception"] is not None
    record_case(
        id="RT-C2-06",
        contractRef="C2",
        scenario="small internal DTD entity expansion (&b; -> 4x 'expandme')",
        expected="either parser refuses DTD entities loudly, or expands a bounded small doc safely",
        actual=f"exit={r['exit_code']} {detail}",
        verdict="passed" if safe else "failed",
    )
    assert safe


def test_rt_c2_07_no_empty_raw_text_row_possible(tmp_path, monkeypatch):
    """Whitespace-only title AND summary entries are skipped in parse_atom."""
    docs = pa.parse_atom(fx.GOOD_FEED)
    assert all(d.raw_text.strip() for d in docs)
    empty_skipped = len(
        pa.parse_atom(
            '<feed xmlns="http://www.w3.org/2005/Atom">'
            "<entry><id>x</id><title>  </title><summary>\n</summary></entry></feed>"
        )
    ) == 0
    record_case(
        id="RT-C2-07",
        contractRef="C2",
        scenario="entry with whitespace-only title AND summary",
        expected="skipped; never yields an empty-raw_text RawDocument",
        actual=f"degenerate entry skipped={empty_skipped}",
        verdict="passed" if empty_skipped else "failed",
    )
    assert empty_skipped


# ---------------------------------------------------------------------------
# C3 — content-hash dedup
# ---------------------------------------------------------------------------


def test_rt_c3_01_identical_recollect_dedups(tmp_path, monkeypatch):
    _patch_feed(monkeypatch, fx.GOOD_FEED)
    data = tmp_path / "d"
    r1 = _collect("RT-C3-01-run1", data, "--paper-query", "databases")
    r2 = _collect("RT-C3-01-run2", data, "--paper-query", "databases")
    docs = list_documents(data)
    ok = (
        r1["exit_code"] == 0 and r2["exit_code"] == 0
        and len(docs) == 2
        and "(0 new)" in r2["stdout"]
        and r2["stdout"].count("duplicate document") == 2
    )
    record_case(
        id="RT-C3-01",
        contractRef="C3",
        scenario="same allowlisted query collected twice with an identical feed",
        expected="second run dedups via content_hash: still 2 rows, 0 new",
        actual=(
            f"run1 exit={r1['exit_code']}, run2 exit={r2['exit_code']}, "
            f"rows={len(docs)}, run2 stdout={r2['stdout'].strip()!r}"
        ),
        verdict="passed" if ok else "failed",
    )
    assert ok


def test_rt_c3_02_different_source_uri_same_text_dedups(tmp_path, monkeypatch):
    _patch_feed(monkeypatch, fx.GOOD_FEED)
    data = tmp_path / "d"
    _collect("RT-C3-02-run1", data, "--paper-query", "databases")
    _patch_feed(monkeypatch, fx.GOOD_FEED_ALT_IDS)
    r2 = _collect("RT-C3-02-run2", data, "--paper-query", "databases")
    docs = list_documents(data)
    uris = sorted(d.source_uri for d in docs)
    deduped = len(docs) == 2 and all(u.startswith("http://arxiv.org/") for u in uris)
    mirror_uri_lost = "mirror.example" not in r2["stdout"]
    record_case(
        id="RT-C3-02",
        contractRef="C3",
        scenario="second collect: DIFFERENT source_uri (mirror ids), byte-identical title+abstract text",
        expected="document what happens under content-hash dedup vs kgstore.insert_document semantics",
        actual=(
            f"deduped to {len(docs)} rows keeping the ORIGINAL source_uri {uris!r}; "
            f"matches kgstore.insert_document (UNIQUE(content_hash), existing row "
            f"returned, created=False). NOTE: the alternate source_uri is never "
            f"persisted anywhere — CLI output and provenance log echo the ORIGINAL "
            f"uri (alternate-provenance loss, mirror uri absent from run2 stdout={mirror_uri_lost})"
        ),
        verdict="passed" if deduped else "failed",
    )
    assert deduped
    assert mirror_uri_lost


# ---------------------------------------------------------------------------
# C4 / limit boundary (in-process half; subprocess half in test_e2e_subprocess)
# ---------------------------------------------------------------------------


def test_rt_lim_01_limit_clamping(tmp_path, monkeypatch):
    results = {}
    for lim, expected in (("0", 1), ("-5", 1), ("999", 25), ("25", 25), ("1", 1)):
        seen: list[str] = []
        _patch_feed(monkeypatch, fx.GOOD_FEED, seen)
        r = _collect(
            f"RT-LIM-01[{lim}]", tmp_path / f"d{lim}",
            "--paper-query", "databases", "--limit", lim,
        )
        (url,) = seen
        got = int(url.split("max_results=")[1])
        results[lim] = (r["exit_code"], got, expected)
    ok = all(code == 0 and got == exp for code, got, exp in results.values())
    record_case(
        id="RT-LIM-01",
        contractRef="C4/limit",
        scenario="--limit boundary values 0, -5, 999, 25, 1",
        expected="clamped to 1..25 (0->1, -5->1, 999->25); exit 0",
        actual={k: f"exit={c} max_results={g} (expected {e})" for k, (c, g, e) in results.items()},
        verdict="passed" if ok else "failed",
    )
    assert ok


def test_rt_c4_07_paper_success_persists_contracted_rows(tmp_path, monkeypatch):
    _patch_feed(monkeypatch, fx.GOOD_FEED)
    data = tmp_path / "d"
    r = _collect("RT-C4-07", data, "--paper-query", "databases")
    docs = list_documents(data)
    ok = (
        r["exit_code"] == 0
        and len(docs) == 2
        and all(d.source_kind == "paper_api" for d in docs)
        and all(read_raw_text(data, d).strip() for d in docs)
        and all(d.content_hash.startswith("sha256:") for d in docs)
    )
    # provenance log exists for the collect job
    prov_events = list((data / "jobs").rglob("provenance.jsonl"))
    record_case(
        id="RT-C4-07",
        contractRef="C2/C4",
        scenario="happy-path paper collect (faked feed): row contract check",
        expected="exit 0; rows source_kind='paper_api', non-empty raw_text, sha256 content_hash, provenance logged",
        actual=(
            f"exit={r['exit_code']} rows={len(docs)} "
            f"kinds={sorted({d.source_kind for d in docs})} "
            f"provenance_files={len(prov_events)}"
        ),
        verdict="passed" if ok and prov_events else "failed",
    )
    assert ok
    assert prov_events, "no provenance.jsonl written for collect job"
