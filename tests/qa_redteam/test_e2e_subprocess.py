"""True-subprocess E2E runs of `python -m ontologylab.main collect` (offline).

Only paths that need NO network are exercised as real subprocesses (rejection,
unsupported source, argparse errors, --file ingest, --help). Defense in depth:
every subprocess gets dead http(s) proxies pointed at 127.0.0.1:9, so any
accidental network attempt fails fast instead of leaving the sandbox.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from qa_redteam.qa_helpers import list_documents, record_case, record_subprocess

REPO_ROOT = Path(__file__).resolve().parents[2]
VENV_PY = REPO_ROOT / ".venv" / "bin" / "python"

_DEAD_PROXY = "http://127.0.0.1:9"


def run_cli(case_id: str, *argv: str) -> dict:
    env = os.environ.copy()
    env.update(
        http_proxy=_DEAD_PROXY,
        https_proxy=_DEAD_PROXY,
        HTTP_PROXY=_DEAD_PROXY,
        HTTPS_PROXY=_DEAD_PROXY,
        no_proxy="",
        NO_PROXY="",
    )
    full = [str(VENV_PY), "-m", "ontologylab.main", *argv]
    proc = subprocess.run(
        full, capture_output=True, text=True, cwd=str(REPO_ROOT), env=env, timeout=90
    )
    return record_subprocess(case_id, full, proc)


def test_e2e_01_help_exits_zero():
    r = run_cli("E2E-01", "--help")
    record_case(
        id="E2E-01",
        contractRef="C4",
        scenario="subprocess: --help",
        expected="exit 0, usage text",
        actual=f"exit={r['exit_code']}",
        verdict="passed" if r["exit_code"] == 0 and "collect" in r["stdout"] else "failed",
    )
    assert r["exit_code"] == 0


def test_e2e_02_nothing_to_collect(tmp_path):
    r = run_cli("E2E-02", "collect", "--data-dir", str(tmp_path / "d"))
    ok = r["exit_code"] == 2 and "nothing to collect" in r["stdout"]
    record_case(
        id="E2E-02",
        contractRef="C4",
        scenario="subprocess: collect with no sources at all",
        expected="exit 2 with explanation",
        actual=(
            f"exit={r['exit_code']} stdout={r['stdout'].strip()!r} "
            f"(NOTE: explanation goes to STDOUT, not stderr)"
        ),
        verdict="passed" if ok else "failed",
    )
    assert ok


def test_e2e_03_rejected_paper_query(tmp_path):
    r = run_cli(
        "E2E-03", "collect", "--data-dir", str(tmp_path / "d"),
        "--paper-query", "quantum finance",
    )
    ok = r["exit_code"] == 2 and "REJECTED" in r["stderr"]
    record_case(
        id="E2E-03",
        contractRef="C1/C4",
        scenario="subprocess: non-allowlisted paper query 'quantum finance' (dead proxies prove no network needed)",
        expected="exit 2, REJECTED on stderr, before any network call",
        actual=f"exit={r['exit_code']} stderr={r['stderr'].strip()!r}",
        verdict="passed" if ok else "failed",
    )
    assert ok
    assert list_documents(tmp_path / "d") == []


def test_e2e_04_unsupported_crossref(tmp_path):
    r = run_cli(
        "E2E-04", "collect", "--data-dir", str(tmp_path / "d"),
        "--paper-source", "crossref", "--paper-query", "databases",
    )
    ok = r["exit_code"] == 2 and "UNSUPPORTED" in r["stderr"]
    record_case(
        id="E2E-04",
        contractRef="C4",
        scenario="subprocess: allowlisted-but-unimplemented source crossref",
        expected="exit 2, UNSUPPORTED on stderr (UnsupportedPaperSource raised before fetch)",
        actual=f"exit={r['exit_code']} stderr={r['stderr'].strip()!r}",
        verdict="passed" if ok else "failed",
    )
    assert ok


def test_e2e_05_file_ingest_success_and_dedup(tmp_path):
    doc = tmp_path / "note.txt"
    doc.write_text("A small offline ingest fixture about storage engines.\n")
    data = tmp_path / "d"
    r1 = run_cli("E2E-05-run1", "collect", "--data-dir", str(data), "--file", str(doc))
    r2 = run_cli("E2E-05-run2", "collect", "--data-dir", str(data), "--file", str(doc))
    docs = list_documents(data)
    ok = (
        r1["exit_code"] == 0 and "new document" in r1["stdout"]
        and r2["exit_code"] == 0 and "duplicate document" in r2["stdout"]
        and len(docs) == 1 and docs[0].source_kind == "upload"
    )
    record_case(
        id="E2E-05",
        contractRef="C4/C3",
        scenario="subprocess: existing --file path unregressed (success 0 + content-hash dedup on rerun)",
        expected="run1 exit 0 'new document'; run2 exit 0 'duplicate document'; 1 row",
        actual=(
            f"run1 exit={r1['exit_code']}, run2 exit={r2['exit_code']}, "
            f"rows={len(docs)} kind={docs[0].source_kind if docs else None}"
        ),
        verdict="passed" if ok else "failed",
    )
    assert ok


def test_e2e_06_url_rejection_unregressed(tmp_path):
    r = run_cli(
        "E2E-06", "collect", "--data-dir", str(tmp_path / "d"),
        "--url", "https://evil.example.com/paper",
    )
    ok = r["exit_code"] == 2 and "REJECTED" in r["stderr"]
    record_case(
        id="E2E-06",
        contractRef="C4",
        scenario="subprocess: existing --url path unregressed (non-allowlisted host)",
        expected="exit 2, REJECTED on stderr, no network",
        actual=f"exit={r['exit_code']} stderr={r['stderr'].strip()!r}",
        verdict="passed" if ok else "failed",
    )
    assert ok


def test_e2e_07_non_integer_limit(tmp_path):
    r = run_cli(
        "E2E-07", "collect", "--data-dir", str(tmp_path / "d"),
        "--paper-query", "databases", "--limit", "abc",
    )
    ok = r["exit_code"] == 2 and "invalid int value" in r["stderr"]
    record_case(
        id="E2E-07",
        contractRef="C4/limit",
        scenario="subprocess: --limit abc (non-integer)",
        expected="argparse usage error, exit 2, no network",
        actual=f"exit={r['exit_code']} stderr tail={r['stderr'].strip().splitlines()[-1:]!r}",
        verdict="passed" if ok else "failed",
    )
    assert ok


def test_e2e_08_source_injection_subprocess(tmp_path):
    r = run_cli(
        "E2E-08", "collect", "--data-dir", str(tmp_path / "d"),
        "--paper-source", "arxiv OR crossref", "--paper-query", "databases",
    )
    ok = r["exit_code"] == 2 and "REJECTED" in r["stderr"]
    record_case(
        id="E2E-08",
        contractRef="C1/C4",
        scenario="subprocess: --paper-source 'arxiv OR crossref' injection",
        expected="exit 2, REJECTED on stderr",
        actual=f"exit={r['exit_code']} stderr={r['stderr'].strip()!r}",
        verdict="passed" if ok else "failed",
    )
    assert ok


def test_e2e_09_roadmap_flag_shape_agreement(tmp_path):
    """ROADMAP M3 deliverable (docs/ROADMAP.md:156) now documents the shipped
    --paper-query/--paper-source shape; the originally sketched
    --connector/--query shape stays correctly rejected by argparse."""
    r = run_cli(
        "E2E-09", "collect", "--data-dir", str(tmp_path / "d"),
        "--connector", "paper_api", "--query", "databases", "--limit", "5",
    )
    legacy_rejected = r["exit_code"] == 2 and "unrecognized arguments" in r["stderr"]
    roadmap = (REPO_ROOT / "docs" / "ROADMAP.md").read_text(encoding="utf-8")
    documented = 'collect --paper-query "..."' in roadmap
    record_case(
        id="E2E-09",
        contractRef="ROADMAP.md:156 (M3 deliverable CLI shape)",
        scenario="subprocess: probe the legacy --connector/--query shape vs the ROADMAP-documented one",
        expected="plan and code agree on the CLI surface",
        actual=(
            f"exit={r['exit_code']} stderr={r['stderr'].strip()!r} — ROADMAP now "
            f"documents the shipped --paper-query shape (documented={documented}); "
            f"the never-shipped legacy shape is rejected by argparse"
        ),
        verdict="passed" if legacy_rejected and documented else "failed",
    )
    assert legacy_rejected
    assert documented


def test_e2e_10_success_exit_zero_paper_inprocess_already_covered():
    """Sanity: the interpreter used for subprocess runs is the project venv."""
    assert VENV_PY.exists(), f"venv python missing at {VENV_PY}"
    assert sys.version_info >= (3, 11)
