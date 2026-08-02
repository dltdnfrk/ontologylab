from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from scripts.check_product_status import check_status


ROWS = """\
| ID | Status | Evidence | Follow-up |
|---|---|---|---|
| AC-01 | COMPLETE | `tests/evidence.py` | NONE |
| AC-02 | COMPLETE | `tests/evidence.py` | NONE |
| AC-03 | COMPLETE | `tests/evidence.py` | NONE |
| CHUNK-SWEEP | COMPLETE | `docs/CHUNK-SWEEP-2026-08.md` | NON-BLOCKING: representative real-corpus rerun |
"""


def _fixture(root: Path, rows: str = ROWS) -> Path:
    (root / "docs").mkdir(exist_ok=True)
    (root / "tests").mkdir(exist_ok=True)
    (root / "tests/evidence.py").write_text("# evidence\n", encoding="utf-8")
    (root / "docs/CHUNK-SWEEP-2026-08.md").write_text("# sweep\n", encoding="utf-8")
    document = root / "docs/PRODUCT_SPEC.md"
    document.write_text(
        "# Product\n\n<!-- product-status:v1:start -->\n"
        + rows
        + "<!-- product-status:v1:end -->\n",
        encoding="utf-8",
    )
    return document


def test_parses_statuses_followups_and_resolved_paths(tmp_path: Path) -> None:
    document = _fixture(tmp_path)

    report = check_status(document, tmp_path)

    assert report.ok
    assert {entry.item_id: entry.status for entry in report.entries} == {
        "AC-01": "COMPLETE",
        "AC-02": "COMPLETE",
        "AC-03": "COMPLETE",
        "CHUNK-SWEEP": "COMPLETE",
    }
    chunk = next(entry for entry in report.entries if entry.item_id == "CHUNK-SWEEP")
    assert chunk.follow_up == "NON-BLOCKING"
    assert chunk.evidence == ("docs/CHUNK-SWEEP-2026-08.md",)
    assert report.resolved_paths == (
        "docs/CHUNK-SWEEP-2026-08.md",
        "tests/evidence.py",
    )


def test_deliberately_stale_status_fails_semantically(tmp_path: Path) -> None:
    stale = ROWS.replace("| AC-01 | COMPLETE |", "| AC-01 | INCOMPLETE |").replace(
        "| AC-01 | INCOMPLETE | `tests/evidence.py` | NONE |",
        "| AC-01 | INCOMPLETE | `tests/evidence.py` | BLOCKING: implement staleness |",
    )
    document = _fixture(tmp_path, stale)

    report = check_status(document, tmp_path)

    assert not report.ok
    assert [(issue.code, issue.item_id) for issue in report.issues] == [
        ("stale_status", "AC-01")
    ]


def test_duplicate_and_missing_ids_fail(tmp_path: Path) -> None:
    rows = ROWS.replace(
        "| AC-02 | COMPLETE | `tests/evidence.py` | NONE |",
        "| AC-01 | COMPLETE | `tests/evidence.py` | NONE |",
    )

    report = check_status(_fixture(tmp_path, rows), tmp_path)

    assert {issue.code for issue in report.issues} == {"duplicate_id", "missing_id"}


def test_completion_cannot_have_blocking_followup(tmp_path: Path) -> None:
    rows = ROWS.replace(
        "| AC-03 | COMPLETE | `tests/evidence.py` | NONE |",
        "| AC-03 | COMPLETE | `tests/evidence.py` | BLOCKING: unanswered work |",
    )

    report = check_status(_fixture(tmp_path, rows), tmp_path)

    assert any(issue.code == "followup_contradiction" for issue in report.issues)


def test_broken_or_empty_evidence_fails(tmp_path: Path) -> None:
    rows = ROWS.replace("`tests/evidence.py`", "`tests/missing.py`", 1).replace(
        "| AC-02 | COMPLETE | `tests/evidence.py` |",
        "| AC-02 | COMPLETE |  |",
    )

    report = check_status(_fixture(tmp_path, rows), tmp_path)

    assert {issue.code for issue in report.issues} >= {"broken_path", "empty_evidence"}


def test_missing_delimiters_and_invalid_status_fail(tmp_path: Path) -> None:
    document = _fixture(tmp_path)
    document.write_text(ROWS.replace("COMPLETE", "DONE", 1), encoding="utf-8")

    missing = check_status(document, tmp_path)

    assert [issue.code for issue in missing.issues] == ["missing_delimiters"]

    document = _fixture(tmp_path, ROWS.replace("COMPLETE", "DONE", 1))
    invalid = check_status(document, tmp_path)
    assert any(issue.code == "invalid_status" for issue in invalid.issues)


def test_cli_stale_fixture_exits_nonzero_with_json_reason(tmp_path: Path) -> None:
    stale = ROWS.replace("| AC-01 | COMPLETE |", "| AC-01 | INCOMPLETE |").replace(
        "| AC-01 | INCOMPLETE | `tests/evidence.py` | NONE |",
        "| AC-01 | INCOMPLETE | `tests/evidence.py` | BLOCKING: old claim |",
    )
    document = _fixture(tmp_path, stale)

    result = subprocess.run(
        [
            sys.executable,
            "scripts/check_product_status.py",
            "--root",
            str(tmp_path),
            "--document",
            str(document),
            "--json",
        ],
        cwd=Path(__file__).resolve().parents[1],
        check=False,
        capture_output=True,
        text=True,
    )

    payload = json.loads(result.stdout)
    assert result.returncode == 1
    assert payload["ok"] is False
    assert payload["issues"] == [
        {"code": "stale_status", "id": "AC-01", "detail": "expected COMPLETE, got INCOMPLETE"}
    ]
