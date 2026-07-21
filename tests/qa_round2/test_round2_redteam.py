"""Round-2 adversarial probes for the FIXED paper_api contract (F1-F6).

Independent of round 1 (tests/qa_redteam). Every fetch-dependent path
monkeypatches the two seams (paper_api._http_get_text, web_crawl._fetch_url);
subprocess runs use dead proxies and only exercise network-free paths.
"""

from __future__ import annotations

import re
from urllib.error import HTTPError, URLError

import pytest

import ontologylab.connectors.allowlist as allowlist
import ontologylab.connectors.paper_api as pa
import ontologylab.main as olmain
import qa_round2.fixtures_r2 as fx
from qa_round2.r2_helpers import (
    REPO_ROOT,
    check_case,
    list_documents,
    provenance_steps,
    run_main_inprocess,
    run_main_subprocess,
)

ALLOWED_URL = "https://docs.python.org/3/library/sqlite3.html"
DENIED_URL = "https://evil.example/malware"
ALLOWED_QUERY = "databases"
DENIED_QUERY = "https://evil.example/exfil"  # URL-shaped: rejected by validation


def _collect(case_id, data_dir, *extra):
    return run_main_inprocess(
        case_id, ["collect", "--data-dir", str(data_dir), *extra]
    )


def _patch_feed(monkeypatch, body, seen=None):
    def fake_fetch(url):
        if seen is not None:
            seen.append(url)
        return body

    monkeypatch.setattr(pa, "_http_get_text", fake_fetch)


def _clean(r):
    """No traceback, no uncaught exception, in either stream."""
    return (
        r["exception"] is None
        and "Traceback" not in r["stderr"]
        and "Traceback" not in r["stdout"]
    )


# ---------------------------------------------------------------------------
# F2 — mixed-run pre-validation: zero I/O before any gate failure
# ---------------------------------------------------------------------------


def test_r2_f2_01_allowed_url_denied_query_zero_io(tmp_path, net_trap):
    with check_case(
        "R2-F2-01",
        "F2",
        "mixed run: --url <allowlisted> --paper-query <denied>; both fetch "
        "seams booby-trapped with AssertionError",
        "exit 2 REJECTED, zero trap trips (no fetch of the allowlisted URL "
        "before the denied query is gated)",
    ) as obs:
        r = _collect(
            "R2-F2-01", tmp_path / "d",
            "--url", ALLOWED_URL, "--paper-query", DENIED_QUERY,
        )
        obs["actual"] = (
            f"exit={r['exit_code']} trips={net_trap} "
            f"stderr={r['stderr'].strip()!r}"
        )
        assert r["exit_code"] == 2
        assert "REJECTED" in r["stderr"]
        assert net_trap == {"paper": 0, "web": 0}
        assert _clean(r)


def test_r2_f2_02_denied_url_allowed_query_zero_io(tmp_path, net_trap):
    with check_case(
        "R2-F2-02",
        "F2",
        "mixed run, reversed gating order: --url <denied-host> "
        "--paper-query <allowlisted>; both seams booby-trapped",
        "exit 2 REJECTED, zero trap trips both ways",
    ) as obs:
        r = _collect(
            "R2-F2-02", tmp_path / "d",
            "--url", DENIED_URL, "--paper-query", ALLOWED_QUERY,
        )
        obs["actual"] = (
            f"exit={r['exit_code']} trips={net_trap} "
            f"stderr={r['stderr'].strip()!r}"
        )
        assert r["exit_code"] == 2
        assert "REJECTED" in r["stderr"]
        assert net_trap == {"paper": 0, "web": 0}
        assert _clean(r)


def test_r2_f2_03_non_allowlisted_source_zero_io(tmp_path, net_trap):
    with check_case(
        "R2-F2-03",
        "F2",
        "mixed run: --url <allowlisted> --paper-source semantic-scholar "
        "(NOT allowlisted) --paper-query <allowlisted>; seams trapped",
        "exit 2 REJECTED, zero trap trips (pre-validation catches the "
        "non-allowlisted source before ANY network I/O)",
    ) as obs:
        r = _collect(
            "R2-F2-03", tmp_path / "d",
            "--url", ALLOWED_URL,
            "--paper-source", "semantic-scholar", "--paper-query", ALLOWED_QUERY,
        )
        obs["actual"] = (
            f"exit={r['exit_code']} trips={net_trap} "
            f"stderr={r['stderr'].strip()!r}"
        )
        assert r["exit_code"] == 2
        assert "REJECTED" in r["stderr"]
        assert net_trap == {"paper": 0, "web": 0}
        assert _clean(r)


def test_r2_f2_04_identical_values_at_both_check_sites(tmp_path, monkeypatch):
    """CLI must pass the SAME (source, query) argv values to pre-validation
    and to the in-fetch defense-in-depth check (connector strips once)."""
    calls: list[tuple[str, str, str]] = []

    def spy_preval(source, query):
        calls.append(("pre-validation", source, query))
        return allowlist.check_paper_query(source, query)

    def spy_infetch(source, query):
        calls.append(("in-fetch", source, query))
        return allowlist.check_paper_query(source, query)

    monkeypatch.setattr(olmain, "check_paper_query", spy_preval)
    monkeypatch.setattr(pa, "check_paper_query", spy_infetch)
    _patch_feed(monkeypatch, fx.GOOD_FEED)

    with check_case(
        "R2-F2-04",
        "F2",
        "spy on both check_paper_query call sites during a passing run with "
        "padded query '  DataBases  '",
        "both sites see the same source and the same query text modulo the "
        "connector's single canonical strip; no divergence is craftable via "
        "the CLI",
    ) as obs:
        r = _collect(
            "R2-F2-04", tmp_path / "d",
            "--paper-query", "  DataBases  ",
        )
        obs["actual"] = f"exit={r['exit_code']} check-site calls={calls!r}"
        assert r["exit_code"] == 0
        sites = {c[0] for c in calls}
        assert sites == {"pre-validation", "in-fetch"}
        (pre,) = [c for c in calls if c[0] == "pre-validation"]
        (fetch,) = [c for c in calls if c[0] == "in-fetch"]
        assert pre[1] == fetch[1] == "arxiv"
        # CLI hands the identical argv string to both paths; the connector
        # strips exactly once before its check + URL build.
        assert pre[2] == "  DataBases  "
        assert fetch[2] == pre[2].strip() == "DataBases"


# ---------------------------------------------------------------------------
# F3 — fetch/parse failures: clean FETCH FAILED, exit 2, provenance, never
#      a traceback; non-URLError OSError takes the 'collect failed' branch
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "case_id, exc_factory, scenario",
    [
        (
            "R2-F3-01",
            lambda: HTTPError(
                "https://export.arxiv.org/api/query", 503,
                "Service Unavailable", None, None,
            ),
            "_http_get_text raises HTTPError 503 (URLError subclass)",
        ),
        (
            "R2-F3-02",
            lambda: URLError("connection refused"),
            "_http_get_text raises bare URLError",
        ),
        (
            "R2-F3-03",
            lambda: URLError(TimeoutError("timed out")),
            "_http_get_text raises URLError wrapping TimeoutError",
        ),
    ],
)
def test_r2_f3_fetch_errors_clean(tmp_path, monkeypatch, case_id, exc_factory,
                                  scenario):
    def raising_fetch(url):
        raise exc_factory()

    monkeypatch.setattr(pa, "_http_get_text", raising_fetch)
    with check_case(
        case_id,
        "F3",
        scenario,
        "clean 'FETCH FAILED' on stderr, exit 2, collect.fetch_failed "
        "provenance, never a traceback",
    ) as obs:
        d = tmp_path / "d"
        r = _collect(case_id, d, "--paper-query", ALLOWED_QUERY)
        steps = provenance_steps(d)
        obs["actual"] = (
            f"exit={r['exit_code']} stderr={r['stderr'].strip()!r} "
            f"provenance={steps}"
        )
        assert r["exit_code"] == 2
        assert "FETCH FAILED" in r["stderr"]
        assert _clean(r)
        assert "collect.fetch_failed" in steps


def test_r2_f3_04_parse_error_clean(tmp_path, monkeypatch):
    _patch_feed(monkeypatch, fx.TRUNCATED_FEED)
    with check_case(
        "R2-F3-04",
        "F3",
        "fetch returns truncated (not well-formed) Atom body -> ParseError",
        "clean 'FETCH FAILED' stderr, exit 2, collect.fetch_failed "
        "provenance, no traceback",
    ) as obs:
        d = tmp_path / "d"
        r = _collect("R2-F3-04", d, "--paper-query", ALLOWED_QUERY)
        steps = provenance_steps(d)
        obs["actual"] = (
            f"exit={r['exit_code']} stderr={r['stderr'].strip()!r} "
            f"provenance={steps}"
        )
        assert r["exit_code"] == 2
        assert "FETCH FAILED" in r["stderr"]
        assert _clean(r)
        assert "collect.fetch_failed" in steps


def test_r2_f3_05_web_crawl_urlerror_clean(tmp_path, monkeypatch):
    import ontologylab.connectors.web_crawl as wc

    def raising_fetch(url):
        raise URLError("name or service not known")

    monkeypatch.setattr(wc, "_fetch_url", raising_fetch)
    with check_case(
        "R2-F3-05",
        "F3",
        "web loop: web_crawl._fetch_url raises URLError on an allowlisted URL",
        "same clean handling: 'FETCH FAILED' stderr, exit 2, "
        "collect.fetch_failed provenance, no traceback",
    ) as obs:
        d = tmp_path / "d"
        r = _collect("R2-F3-05", d, "--url", ALLOWED_URL)
        steps = provenance_steps(d)
        obs["actual"] = (
            f"exit={r['exit_code']} stderr={r['stderr'].strip()!r} "
            f"provenance={steps}"
        )
        assert r["exit_code"] == 2
        assert "FETCH FAILED" in r["stderr"]
        assert _clean(r)
        assert "collect.fetch_failed" in steps


def test_r2_f3_06_oserror_not_urlerror_hits_collect_failed(tmp_path,
                                                           monkeypatch):
    def raising_fetch(url):
        raise PermissionError("operation not permitted")

    monkeypatch.setattr(pa, "_http_get_text", raising_fetch)
    with check_case(
        "R2-F3-06",
        "F3",
        "exception-ordering probe: _http_get_text raises PermissionError "
        "(OSError but NOT URLError)",
        "hits the 'collect failed' branch (collect.failed provenance), NOT "
        "'FETCH FAILED', exit 2, never a traceback",
    ) as obs:
        d = tmp_path / "d"
        r = _collect("R2-F3-06", d, "--paper-query", ALLOWED_QUERY)
        steps = provenance_steps(d)
        obs["actual"] = (
            f"exit={r['exit_code']} stderr={r['stderr'].strip()!r} "
            f"provenance={steps}"
        )
        assert r["exit_code"] == 2
        assert "collect failed" in r["stderr"]
        assert "FETCH FAILED" not in r["stderr"]
        assert _clean(r)
        assert "collect.failed" in steps
        assert "collect.fetch_failed" not in steps


# ---------------------------------------------------------------------------
# F1 — id-less entries never inserted; zero-doc runs exit 0
# ---------------------------------------------------------------------------


def test_r2_f1_01_no_id_feed_zero_rows_exit_0(tmp_path, monkeypatch):
    _patch_feed(monkeypatch, fx.NO_ID_FEED)
    with check_case(
        "R2-F1-01",
        "F1",
        "feed whose only entry has no <id>",
        "0 rows inserted, exit 0, 'no documents matched' message",
    ) as obs:
        d = tmp_path / "d"
        r = _collect("R2-F1-01", d, "--paper-query", ALLOWED_QUERY)
        docs = list_documents(d)
        obs["actual"] = (
            f"exit={r['exit_code']} rows={len(docs)} "
            f"stdout={r['stdout'].strip()!r}"
        )
        assert r["exit_code"] == 0
        assert "no documents matched" in r["stdout"]
        assert docs == []
        assert _clean(r)


def test_r2_f1_02_mixed_feed_only_valid_entry_inserted(tmp_path, monkeypatch):
    _patch_feed(monkeypatch, fx.MIXED_ID_FEED)
    with check_case(
        "R2-F1-02",
        "F1",
        "feed with 1 valid entry + 1 id-less entry",
        "exactly 1 row inserted (the id-bearing entry), exit 0, "
        "'new document' printed",
    ) as obs:
        d = tmp_path / "d"
        r = _collect("R2-F1-02", d, "--paper-query", ALLOWED_QUERY)
        docs = list_documents(d)
        obs["actual"] = (
            f"exit={r['exit_code']} rows={len(docs)} "
            f"uris={[doc.source_uri for doc in docs]} "
            f"stdout={r['stdout'].strip()!r}"
        )
        assert r["exit_code"] == 0
        assert "new document" in r["stdout"]
        assert len(docs) == 1
        assert docs[0].source_uri == "http://arxiv.org/abs/9102.00001v1"
        assert _clean(r)


# ---------------------------------------------------------------------------
# F4 — https endpoint; single canonical strip visible in the built URL
# ---------------------------------------------------------------------------


def test_r2_f4_01_built_url_https():
    with check_case(
        "R2-F4-01",
        "F4",
        "unit: _build_query_url output scheme/host",
        "URL starts with https://export.arxiv.org/api/query",
    ) as obs:
        url = pa._build_query_url("databases", 5)
        obs["actual"] = f"url={url!r}"
        assert url.startswith("https://export.arxiv.org/api/query?")


def test_r2_f4_02_padded_query_stripped_once_end_to_end(tmp_path, monkeypatch):
    seen: list[str] = []
    _patch_feed(monkeypatch, fx.GOOD_FEED, seen)
    with check_case(
        "R2-F4-02",
        "F4",
        "end-to-end padded query '  DataBases  ' (strips+lowers to an "
        "allowlisted term)",
        "SUCCEEDS (exit 0); fetched URL is https and its query part is the "
        "stripped 'DataBases' — no '++DataBases++' round-1 artifact",
    ) as obs:
        r = _collect("R2-F4-02", tmp_path / "d", "--paper-query", "  DataBases  ")
        obs["actual"] = f"exit={r['exit_code']} urls={seen!r}"
        assert r["exit_code"] == 0
        (url,) = seen
        assert url.startswith("https://")
        query_part = url.split("search_query=all:")[1].split("&start=")[0]
        assert query_part == "DataBases"
        assert "+" not in query_part and "%20" not in query_part
        assert url == pa._build_query_url("DataBases", pa.DEFAULT_LIMIT)


# ---------------------------------------------------------------------------
# F5 — regression matrix (subprocess with dead proxies; success paths
#      in-process with patched seams)
# ---------------------------------------------------------------------------


def test_r2_f5_01_help_exit_0():
    with check_case(
        "R2-F5-01", "F5", "subprocess: ontologylab --help",
        "exit 0, usage text printed",
    ) as obs:
        r = run_main_subprocess("R2-F5-01", ["--help"])
        obs["actual"] = f"exit={r['exit_code']} stdout[:60]={r['stdout'][:60]!r}"
        assert r["exit_code"] == 0
        assert "usage:" in r["stdout"]


def test_r2_f5_02_no_inputs_exit_2(tmp_path):
    with check_case(
        "R2-F5-02", "F5", "subprocess: collect with no inputs at all",
        "exit 2 with 'nothing to collect' usage error",
    ) as obs:
        r = run_main_subprocess(
            "R2-F5-02", ["collect", "--data-dir", str(tmp_path / "d")]
        )
        obs["actual"] = f"exit={r['exit_code']} stdout={r['stdout'].strip()!r}"
        assert r["exit_code"] == 2
        assert "nothing to collect" in r["stdout"] + r["stderr"]


def test_r2_f5_03_file_new_then_duplicate(tmp_path):
    note = tmp_path / "note.md"
    note.write_text("# Round two\n\nA small ingest fixture.\n", encoding="utf-8")
    d = tmp_path / "d"
    with check_case(
        "R2-F5-03", "F5",
        "subprocess: collect --file twice into the same data dir",
        "first run exit 0 'new document'; second run exit 0 'duplicate "
        "document'",
    ) as obs:
        r1 = run_main_subprocess(
            "R2-F5-03a", ["collect", "--data-dir", str(d), "--file", str(note)]
        )
        r2 = run_main_subprocess(
            "R2-F5-03b", ["collect", "--data-dir", str(d), "--file", str(note)]
        )
        obs["actual"] = (
            f"run1 exit={r1['exit_code']} stdout={r1['stdout'].strip()!r}; "
            f"run2 exit={r2['exit_code']} stdout={r2['stdout'].strip()!r}"
        )
        assert r1["exit_code"] == 0 and "new document" in r1["stdout"]
        assert r2["exit_code"] == 0 and "duplicate document" in r2["stdout"]
        assert len(list_documents(d)) == 1


def test_r2_f5_04_denied_url_rejected(tmp_path):
    with check_case(
        "R2-F5-04", "F5", "subprocess: collect --url with denied host",
        "exit 2, REJECTED on stderr, no traceback",
    ) as obs:
        r = run_main_subprocess(
            "R2-F5-04",
            ["collect", "--data-dir", str(tmp_path / "d"), "--url", DENIED_URL],
        )
        obs["actual"] = f"exit={r['exit_code']} stderr={r['stderr'].strip()!r}"
        assert r["exit_code"] == 2
        assert "REJECTED" in r["stderr"]
        assert "Traceback" not in r["stderr"]


def test_r2_f5_05_limit_abc_argparse_error(tmp_path):
    with check_case(
        "R2-F5-05", "F5", "subprocess: collect --limit abc (non-integer)",
        "argparse usage error, exit 2, no traceback",
    ) as obs:
        r = run_main_subprocess(
            "R2-F5-05",
            [
                "collect", "--data-dir", str(tmp_path / "d"),
                "--paper-query", ALLOWED_QUERY, "--limit", "abc",
            ],
        )
        obs["actual"] = f"exit={r['exit_code']} stderr={r['stderr'].strip()!r}"
        assert r["exit_code"] == 2
        assert "invalid int value" in r["stderr"]
        assert "Traceback" not in r["stderr"]


def test_r2_f5_06_url_success_unregressed(tmp_path, monkeypatch):
    import ontologylab.connectors.web_crawl as wc

    monkeypatch.setattr(wc, "_fetch_url", lambda url: fx.FAKE_HTML_PAGE)
    with check_case(
        "R2-F5-06", "F5",
        "in-process: collect --url <allowlisted> with fake HTML body",
        "exit 0, 'new document' + 'collected 1 document(s) (1 new)'",
    ) as obs:
        d = tmp_path / "d"
        r = _collect("R2-F5-06", d, "--url", ALLOWED_URL)
        obs["actual"] = f"exit={r['exit_code']} stdout={r['stdout'].strip()!r}"
        assert r["exit_code"] == 0
        assert "new document" in r["stdout"]
        assert "collected 1 document(s) (1 new)" in r["stdout"]
        assert len(list_documents(d)) == 1


def test_r2_f5_07_paper_query_success_unregressed(tmp_path, monkeypatch):
    _patch_feed(monkeypatch, fx.GOOD_FEED)
    with check_case(
        "R2-F5-07", "F5",
        "in-process: collect --paper-query databases with 2-entry feed",
        "exit 0, two 'new document' lines, 'collected 2 document(s) (2 new)'",
    ) as obs:
        d = tmp_path / "d"
        r = _collect("R2-F5-07", d, "--paper-query", ALLOWED_QUERY)
        obs["actual"] = f"exit={r['exit_code']} stdout={r['stdout'].strip()!r}"
        assert r["exit_code"] == 0
        assert r["stdout"].count("new document") == 2
        assert "collected 2 document(s) (2 new)" in r["stdout"]
        assert len(list_documents(d)) == 2


# ---------------------------------------------------------------------------
# F6 — ROADMAP M3 documents the shipped CLI shape
# ---------------------------------------------------------------------------


def test_r2_f6_01_roadmap_m3_matches_shipped_cli():
    roadmap = (REPO_ROOT / "docs" / "ROADMAP.md").read_text(encoding="utf-8")
    m3_match = re.search(
        r"## Milestone 3 .*?(?=\n## |\Z)", roadmap, flags=re.DOTALL
    )
    with check_case(
        "R2-F6-01", "F6",
        "docs/ROADMAP.md Milestone 3 deliverables vs shipped CLI",
        "M3 documents 'collect --paper-query' as the CLI shape and no longer "
        "presents the unshipped '--connector paper_api --query' shape as the "
        "deliverable",
    ) as obs:
        assert m3_match, "Milestone 3 section not found"
        m3 = m3_match.group(0)
        cli_lines = [
            line for line in m3.splitlines()
            if "ontologylab.main collect" in line
        ]
        obs["actual"] = (
            f"M3 CLI lines={cli_lines!r}; "
            f"'--connector paper_api --query' present={'--connector paper_api --query' in m3}"
        )
        assert "--paper-query" in m3
        assert cli_lines and all("--paper-query" in ln for ln in cli_lines)
        assert "--connector paper_api --query" not in m3
        # '--connector' may only appear as the explicitly-not-chosen note
        for line in m3.splitlines():
            if "--connector" in line:
                assert "were chosen over" in line or "originally sketched" in line


# ---------------------------------------------------------------------------
# RG — fix-induced regression hunting
# ---------------------------------------------------------------------------


def test_r2_rg_01_paper_rerun_dedupes(tmp_path, monkeypatch):
    _patch_feed(monkeypatch, fx.GOOD_FEED)
    with check_case(
        "R2-RG-01", "regression",
        "same feed collected twice into one data dir (post-F1 insert path)",
        "second run exit 0, all docs 'duplicate', row count stays 2",
    ) as obs:
        d = tmp_path / "d"
        r1 = _collect("R2-RG-01a", d, "--paper-query", ALLOWED_QUERY)
        r2 = _collect("R2-RG-01b", d, "--paper-query", ALLOWED_QUERY)
        obs["actual"] = (
            f"run1 exit={r1['exit_code']}; run2 exit={r2['exit_code']} "
            f"stdout={r2['stdout'].strip()!r}; rows={len(list_documents(d))}"
        )
        assert r1["exit_code"] == 0 and r2["exit_code"] == 0
        assert r2["stdout"].count("duplicate document") == 2
        assert "collected 2 document(s) (0 new)" in r2["stdout"]
        assert len(list_documents(d)) == 2


def test_r2_rg_02_zero_paper_docs_do_not_swallow_file_input(tmp_path,
                                                            monkeypatch):
    _patch_feed(monkeypatch, fx.NO_ID_FEED)
    note = tmp_path / "note.md"
    note.write_text("# Survivor\n\nFile input alongside empty feed.\n",
                    encoding="utf-8")
    with check_case(
        "R2-RG-02", "regression",
        "mixed run: paper query yields 0 docs (id-less feed) + --file input "
        "in the same run (F1 'no documents matched' path must not swallow "
        "other inputs)",
        "exit 0, file document ingested, NO 'no documents matched' message",
    ) as obs:
        d = tmp_path / "d"
        r = _collect(
            "R2-RG-02", d,
            "--paper-query", ALLOWED_QUERY, "--file", str(note),
        )
        docs = list_documents(d)
        obs["actual"] = (
            f"exit={r['exit_code']} rows={len(docs)} "
            f"stdout={r['stdout'].strip()!r}"
        )
        assert r["exit_code"] == 0
        assert "no documents matched" not in r["stdout"]
        assert len(docs) == 1
        assert docs[0].source_kind == "upload"


def test_r2_rg_03_empty_feed_zero_docs_exit_0(tmp_path, monkeypatch):
    _patch_feed(monkeypatch, fx.EMPTY_FEED)
    with check_case(
        "R2-RG-03", "regression",
        "well-formed feed with zero <entry> elements",
        "exit 0, 'no documents matched', zero rows (F1 zero-doc contract "
        "covers the no-entries case too)",
    ) as obs:
        d = tmp_path / "d"
        r = _collect("R2-RG-03", d, "--paper-query", ALLOWED_QUERY)
        obs["actual"] = (
            f"exit={r['exit_code']} rows={len(list_documents(d))} "
            f"stdout={r['stdout'].strip()!r}"
        )
        assert r["exit_code"] == 0
        assert "no documents matched" in r["stdout"]
        assert list_documents(d) == []


@pytest.mark.parametrize(
    "case_id, cli_limit, expected_max",
    [
        ("R2-RG-04a", "999", 25),
        ("R2-RG-04b", "0", 1),
        ("R2-RG-04c", "-5", 1),
    ],
)
def test_r2_rg_04_limit_clamp_survives(tmp_path, monkeypatch, case_id,
                                       cli_limit, expected_max):
    seen: list[str] = []
    _patch_feed(monkeypatch, fx.GOOD_FEED, seen)
    with check_case(
        case_id, "regression",
        f"--limit {cli_limit} must still clamp to 1..25 in the built URL",
        f"URL max_results={expected_max}",
    ) as obs:
        r = _collect(
            case_id, tmp_path / "d",
            "--paper-query", ALLOWED_QUERY, "--limit", cli_limit,
        )
        obs["actual"] = f"exit={r['exit_code']} urls={seen!r}"
        assert r["exit_code"] == 0
        (url,) = seen
        assert url.endswith(f"&max_results={expected_max}")


# ---------------------------------------------------------------------------
# CTL — instrumentation negative control
# ---------------------------------------------------------------------------


def test_r2_ctl_01_trap_instrument_fires_when_gates_pass(tmp_path, net_trap):
    """Negative control: with every gate passing, the booby-trap MUST trip,
    proving the F2 zero-trip assertions measure a live instrument (not a
    vacuously-untriggered patch)."""
    with check_case(
        "R2-CTL-01", "F2-control",
        "all gates pass (--paper-query databases) with the counting trap "
        "installed",
        "paper trap trips exactly once and surfaces as an AssertionError "
        "(loud), demonstrating the zero-trip F2 probes are meaningful",
    ) as obs:
        r = _collect("R2-CTL-01", tmp_path / "d", "--paper-query", ALLOWED_QUERY)
        obs["actual"] = f"trips={net_trap} exception={r['exception']!r}"
        assert net_trap == {"paper": 1, "web": 0}
        assert r["exception"] is not None
        assert "AssertionError" in r["exception"]
