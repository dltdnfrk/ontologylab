"""Shared helpers/state for the G001 QA red-team suite (throwaway QA code)."""

from __future__ import annotations

import io
import json
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from ontologylab import paths
from ontologylab.kgstore import KGStore
from ontologylab.main import main

ARTIFACT_DIR = Path("~/Documents/MUNI/artifacts/ultragoal-g001").expanduser()

TRANSCRIPT: list[dict] = []
CASES: list[dict] = []


def record_case(**case) -> None:
    CASES.append(case)


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


def record_subprocess(case_id: str, argv: list[str], proc) -> dict:
    entry = {
        "case": case_id,
        "mode": "subprocess",
        "argv": list(argv),
        "exit_code": proc.returncode,
        "exception": None,
        "stdout": proc.stdout,
        "stderr": proc.stderr,
    }
    TRANSCRIPT.append(entry)
    return entry


def list_documents(data_dir) -> list:
    """Open the KG store under data_dir and return document rows."""
    store = KGStore.open(paths.kg_db_path(Path(data_dir)))
    try:
        return store.list_documents()
    finally:
        store.close()


def read_raw_text(data_dir, doc) -> str:
    db_path = paths.kg_db_path(Path(data_dir))
    return (db_path.parent / doc.raw_text_path).read_text(encoding="utf-8")


def dump_artifacts() -> None:
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    (ARTIFACT_DIR / "cli-live-transcript.json").write_text(
        json.dumps(TRANSCRIPT, indent=2), encoding="utf-8"
    )
    (ARTIFACT_DIR / "qa-cases.json").write_text(
        json.dumps(CASES, indent=2), encoding="utf-8"
    )
