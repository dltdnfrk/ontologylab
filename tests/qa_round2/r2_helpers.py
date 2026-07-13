"""Shared helpers/state for the round-2 QA suite (throwaway QA code)."""

from __future__ import annotations

import io
import json
import os
import subprocess
import sys
from contextlib import contextmanager, redirect_stderr, redirect_stdout
from pathlib import Path

from ontologylab import paths
from ontologylab.kgstore import KGStore
from ontologylab.main import main

ARTIFACT_DIR = Path("~/Documents/MUNI/artifacts/ultragoal-g001").expanduser()
REPO_ROOT = Path(__file__).resolve().parents[2]  # ontologylab repo root

TRANSCRIPT: list[dict] = []
CASES: list[dict] = []


def record_case(**case) -> None:
    CASES.append(case)


@contextmanager
def check_case(case_id: str, contract_ref: str, scenario: str, expected: str):
    """Record a pass/fail case verdict around a block of assertions.

    The block stashes its observed behavior into the yielded dict under
    'actual'; any assertion failure inside the block records a failed
    verdict (and re-raises so pytest also reports it).
    """
    obs: dict = {"actual": ""}
    try:
        yield obs
    except BaseException as exc:
        record_case(
            id=case_id,
            contractRef=contract_ref,
            scenario=scenario,
            expectedBehavior=expected,
            actual=obs["actual"] or f"{type(exc).__name__}: {exc}",
            verdict="failed",
        )
        raise
    record_case(
        id=case_id,
        contractRef=contract_ref,
        scenario=scenario,
        expectedBehavior=expected,
        actual=obs["actual"],
        verdict="passed",
    )


def run_main_inprocess(case_id: str, argv: list[str]) -> dict:
    """Drive ontologylab.main.main() in-process, capturing a CLI transcript."""
    stdout_buf, stderr_buf = io.StringIO(), io.StringIO()
    exit_code: int | None = None
    exception: str | None = None
    try:
        with redirect_stdout(stdout_buf), redirect_stderr(stderr_buf):
            main(list(argv))
    except SystemExit as exc:
        exit_code = exc.code
    except BaseException as exc:  # noqa: BLE001 - red team wants loud failures
        exception = f"{type(exc).__name__}: {exc}"
    entry = {
        "case": case_id,
        "mode": "in-process",
        "argv": ["python", "-m", "ontologylab.main", *argv],
        "exit_code": exit_code,
        "exception": exception,
        "stdout": stdout_buf.getvalue(),
        "stderr": stderr_buf.getvalue(),
    }
    TRANSCRIPT.append(entry)
    return entry


def dead_proxy_env() -> dict[str, str]:
    """Environment that routes any accidental urllib fetch to a dead proxy."""
    env = dict(os.environ)
    env.update(
        {
            "http_proxy": "http://127.0.0.1:9",
            "https_proxy": "http://127.0.0.1:9",
            "HTTP_PROXY": "http://127.0.0.1:9",
            "HTTPS_PROXY": "http://127.0.0.1:9",
            "no_proxy": "",
            "NO_PROXY": "",
        }
    )
    return env


def run_main_subprocess(case_id: str, argv: list[str]) -> dict:
    """Run the real CLI as a subprocess with dead proxies (zero real network)."""
    cmd = [sys.executable, "-m", "ontologylab.main", *argv]
    proc = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=60,
        cwd=REPO_ROOT,
        env=dead_proxy_env(),
    )
    entry = {
        "case": case_id,
        "mode": "subprocess",
        "argv": cmd,
        "exit_code": proc.returncode,
        "exception": None,
        "stdout": proc.stdout,
        "stderr": proc.stderr,
    }
    TRANSCRIPT.append(entry)
    return entry


def list_documents(data_dir) -> list:
    store = KGStore.open(paths.kg_db_path(Path(data_dir)))
    try:
        return store.list_documents()
    finally:
        store.close()


def provenance_steps(data_dir) -> list[str]:
    """All provenance step names logged under data_dir's job dirs."""
    steps: list[str] = []
    for jsonl in sorted(Path(data_dir).glob("jobs/*/provenance.jsonl")):
        for line in jsonl.read_text(encoding="utf-8").splitlines():
            steps.append(json.loads(line)["step"])
    return steps


def dump_artifacts() -> None:
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    (ARTIFACT_DIR / "round2-cli-transcript.json").write_text(
        json.dumps(
            {"kind": "cli-live-transcript", "round": 2, "records": TRANSCRIPT},
            indent=2,
        ),
        encoding="utf-8",
    )
    report_path = ARTIFACT_DIR / "round2-qa-report.json"
    existing: dict = {}
    if report_path.exists():
        try:
            existing = json.loads(report_path.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            existing = {}
    report = {
        "kind": "cli-redteam-test-report",
        "round": 2,
        "cases": CASES,
        "pytest_runs": existing.get("pytest_runs", []),
    }
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
