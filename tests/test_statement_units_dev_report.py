"""Binary oracle for the development statement-unit coverage script.

The fixture corpus is two invented documents: one uncued positive Results
sentence and one measured-null Discussion sentence. Counts below are
hand-written literals from that corpus, not re-derived from the script.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "statement_units_dev_report.py"
FIXTURE_GOLD_DIR = ROOT / "tests" / "fixtures" / "statement_units_dev_report"
BANNER = (
    "development-only, these papers were seen by earlier trials, "
    "not a precision or recall claim"
)

ELIGIBLE_SENTENCES = 2
UNITS = 2
EXPLICIT_UNITS = 2
UNRESOLVED_UNITS = 0
GOLD_SPANS = 2
GOLD_SPANS_IN_UNITS = 2
GOLD_SPANS_IN_ARM_SLOTS = 2
GOLD_NULL_ROWS = 1
GOLD_NULL_ROWS_WITH_CUES = 1
UNCUED_ELIGIBLE_SENTENCES = 1
NULL_ELIGIBLE_SENTENCES = 1
UNCUED_GOLD_NULL_ROWS = 0
NULL_GOLD_NULL_ROWS = 1


def _run(out_prefix: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--gold-dir",
            str(FIXTURE_GOLD_DIR),
            "--out-prefix",
            str(out_prefix),
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )


def _load_json(out_prefix: Path) -> dict[str, object]:
    payload = json.loads((Path(str(out_prefix) + ".json")).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise AssertionError("report json must be an object")
    return payload


def test_fixture_report_counts_match_hand_counted_literals(tmp_path: Path) -> None:
    out_prefix = tmp_path / "statement-units-dev"
    completed = _run(out_prefix)
    assert completed.returncode == 0, completed.stderr

    payload = _load_json(out_prefix)
    papers = payload["papers"]
    totals = payload["totals"]
    assert isinstance(papers, list) and len(papers) == 2
    assert isinstance(totals, dict)
    uncued, measured_null = papers
    assert isinstance(uncued, dict) and isinstance(measured_null, dict)

    assert payload["banner"] == BANNER
    assert payload["rules_version"] == "units-v1"
    assert payload["cue_version"] == "cues-v1"

    assert uncued["pmcid"] == "PMC90000001"
    assert uncued["eligible_sentences"] == UNCUED_ELIGIBLE_SENTENCES
    assert uncued["units"] == 1
    assert uncued["explicit_units"] == 1
    assert uncued["unresolved_units"] == 0
    assert uncued["gold_spans"] == 1
    assert uncued["gold_spans_in_units"] == 1
    assert uncued["gold_spans_in_arm_slots"] == 1
    assert uncued["gold_null_rows"] == UNCUED_GOLD_NULL_ROWS
    assert uncued["gold_null_rows_with_cues"] == 0

    assert measured_null["pmcid"] == "PMC90000002"
    assert measured_null["eligible_sentences"] == NULL_ELIGIBLE_SENTENCES
    assert measured_null["units"] == 1
    assert measured_null["explicit_units"] == 1
    assert measured_null["unresolved_units"] == 0
    assert measured_null["gold_spans"] == 1
    assert measured_null["gold_spans_in_units"] == 1
    assert measured_null["gold_spans_in_arm_slots"] == 1
    assert measured_null["gold_null_rows"] == NULL_GOLD_NULL_ROWS
    assert measured_null["gold_null_rows_with_cues"] == 1

    assert totals["papers"] == 2
    assert totals["eligible_sentences"] == ELIGIBLE_SENTENCES
    assert totals["units"] == UNITS
    assert totals["explicit_units"] == EXPLICIT_UNITS
    assert totals["unresolved_units"] == UNRESOLVED_UNITS
    assert totals["gold_spans"] == GOLD_SPANS
    assert totals["gold_spans_in_units"] == GOLD_SPANS_IN_UNITS
    assert totals["gold_spans_in_arm_slots"] == GOLD_SPANS_IN_ARM_SLOTS
    assert totals["gold_null_rows"] == GOLD_NULL_ROWS
    assert totals["gold_null_rows_with_cues"] == GOLD_NULL_ROWS_WITH_CUES

    markdown = (Path(str(out_prefix) + ".md")).read_text(encoding="utf-8")
    assert BANNER in markdown
    assert "not a precision or recall claim" in markdown


def test_uncued_positive_sentence_is_counted(tmp_path: Path) -> None:
    out_prefix = tmp_path / "statement-units-dev"
    completed = _run(out_prefix)
    assert completed.returncode == 0, completed.stderr
    payload = _load_json(out_prefix)
    papers = payload["papers"]
    totals = payload["totals"]
    assert isinstance(papers, list) and isinstance(totals, dict)
    uncued = papers[0]
    assert isinstance(uncued, dict)
    assert uncued["pmcid"] == "PMC90000001"
    assert uncued["eligible_sentences"] == UNCUED_ELIGIBLE_SENTENCES
    assert totals["eligible_sentences"] == ELIGIBLE_SENTENCES
