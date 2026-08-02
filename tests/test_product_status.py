from __future__ import annotations

import json
import re
import shlex
import subprocess
import sys
from pathlib import Path

from scripts.check_product_status import check_status


ROWS = """\
| ID | Status | Evidence | Follow-up |
|---|---|---|---|
| AC-01 | COMPLETE | `tests/test_staleness.py::test_manifest_carries_basis_and_the_default_policy`, `tests/test_staleness.py::test_count_cancellation_still_reports_semantic_staleness`, `tests/test_staleness.py::test_same_stable_id_material_change_is_replacement`, `tests/test_staleness.py::test_pending_count_is_computed_live_against_the_store` | NONE |
| AC-02 | COMPLETE | `tests/test_registry.py::test_absent_cache_is_off_not_an_error_and_warns_once`, `tests/test_registry.py::test_csv_import_resolves_scientific_synonym_and_common_case_insensitively`, `tests/test_agrochem_schema.py::test_organisms_and_actives_carry_their_registry_identifier`, `tests/test_normalization.py::test_unresolved_organism_is_kept_flagged_and_model_code_is_dropped`, `tests/test_normalization.py::test_extraction_normalizes_before_storage_and_review_exposes_properties`, `tests/test_cas_normalization.py::test_alias_resolution_cache_authority_and_moa_follow_canonical_cas`, `tests/test_cas_normalization.py::test_unknown_active_is_flagged_without_moa_and_model_cas_is_dropped` | NONE |
| AC-03 | COMPLETE | `docs/FIRST-PACK-EVIDENCE.md`, `tests/test_mcp_two_tier.py::test_get_entity_full_record`, `tests/test_mcp_two_tier.py::test_fastmcp_exposes_two_tier_surface` | NONE |
| CHUNK-SWEEP | COMPLETE | `docs/CHUNK-SWEEP-2026-08.md`, `scripts/sweep_chunk_size.py` | NON-BLOCKING: representative real-corpus rerun |
"""

TEST_FUNCTIONS = {
    "tests/test_staleness.py": (
        "test_manifest_carries_basis_and_the_default_policy",
        "test_count_cancellation_still_reports_semantic_staleness",
        "test_same_stable_id_material_change_is_replacement",
        "test_pending_count_is_computed_live_against_the_store",
    ),
    "tests/test_registry.py": (
        "test_absent_cache_is_off_not_an_error_and_warns_once",
        "test_csv_import_resolves_scientific_synonym_and_common_case_insensitively",
    ),
    "tests/test_agrochem_schema.py": (
        "test_organisms_and_actives_carry_their_registry_identifier",
    ),
    "tests/test_normalization.py": (
        "test_unresolved_organism_is_kept_flagged_and_model_code_is_dropped",
        "test_extraction_normalizes_before_storage_and_review_exposes_properties",
    ),
    "tests/test_cas_normalization.py": (
        "test_alias_resolution_cache_authority_and_moa_follow_canonical_cas",
        "test_unknown_active_is_flagged_without_moa_and_model_cas_is_dropped",
    ),
    "tests/test_mcp_two_tier.py": (
        "test_get_entity_full_record",
        "test_fastmcp_exposes_two_tier_surface",
    ),
}


def _fixture(root: Path, rows: str = ROWS) -> Path:
    (root / "docs").mkdir(exist_ok=True)
    (root / "tests").mkdir(exist_ok=True)
    (root / "scripts").mkdir(exist_ok=True)
    for relative, names in TEST_FUNCTIONS.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            "\n".join(f"def {name}():\n    assert object() is not None\n" for name in names),
            encoding="utf-8",
        )
    (root / "docs/FIRST-PACK-EVIDENCE.md").write_text("# First pack evidence\n", encoding="utf-8")
    (root / "docs/CHUNK-SWEEP-2026-08.md").write_text("# Chunk sweep\n", encoding="utf-8")
    (root / "scripts/sweep_chunk_size.py").write_text(
        "CHUNK_SIZES = (1500, 3000)\n"
        "async def sweep_size():\n    return CHUNK_SIZES\n"
        "async def run():\n    return await sweep_size()\n",
        encoding="utf-8",
    )
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
    assert chunk.evidence == (
        "docs/CHUNK-SWEEP-2026-08.md",
        "scripts/sweep_chunk_size.py",
    )
    assert "docs/FIRST-PACK-EVIDENCE.md" in report.resolved_paths
    assert "tests/test_staleness.py" in report.resolved_paths


def test_deliberately_stale_status_fails_semantically(tmp_path: Path) -> None:
    stale = ROWS.replace("| AC-01 | COMPLETE |", "| AC-01 | INCOMPLETE |").replace(
        "| NONE |", "| BLOCKING: implement staleness |", 1
    )
    document = _fixture(tmp_path, stale)

    report = check_status(document, tmp_path)

    assert not report.ok
    assert [(issue.code, issue.item_id) for issue in report.issues] == [
        ("stale_status", "AC-01")
    ]


def test_duplicate_and_missing_ids_fail(tmp_path: Path) -> None:
    ac01 = next(line for line in ROWS.splitlines() if line.startswith("| AC-01 |"))
    ac02 = next(line for line in ROWS.splitlines() if line.startswith("| AC-02 |"))
    rows = ROWS.replace(ac02, ac01)

    report = check_status(_fixture(tmp_path, rows), tmp_path)

    assert {issue.code for issue in report.issues} == {"duplicate_id", "missing_id"}


def test_completion_cannot_have_blocking_followup(tmp_path: Path) -> None:
    rows = ROWS.replace(
        "| AC-03 | COMPLETE | `docs/FIRST-PACK-EVIDENCE.md`, `tests/test_mcp_two_tier.py::test_get_entity_full_record`, `tests/test_mcp_two_tier.py::test_fastmcp_exposes_two_tier_surface` | NONE |",
        "| AC-03 | COMPLETE | `docs/FIRST-PACK-EVIDENCE.md`, `tests/test_mcp_two_tier.py::test_get_entity_full_record`, `tests/test_mcp_two_tier.py::test_fastmcp_exposes_two_tier_surface` | BLOCKING: unanswered work |",
    )

    report = check_status(_fixture(tmp_path, rows), tmp_path)

    assert any(issue.code == "followup_contradiction" for issue in report.issues)


def test_broken_or_empty_evidence_fails(tmp_path: Path) -> None:
    rows = ROWS.replace(
        "`tests/test_staleness.py::test_manifest_carries_basis_and_the_default_policy`",
        "`tests/missing.py::test_missing`",
        1,
    ).replace(
        "| AC-02 | COMPLETE | `tests/test_registry.py::test_absent_cache_is_off_not_an_error_and_warns_once`, `tests/test_registry.py::test_csv_import_resolves_scientific_synonym_and_common_case_insensitively`, `tests/test_agrochem_schema.py::test_organisms_and_actives_carry_their_registry_identifier`, `tests/test_normalization.py::test_unresolved_organism_is_kept_flagged_and_model_code_is_dropped`, `tests/test_normalization.py::test_extraction_normalizes_before_storage_and_review_exposes_properties`, `tests/test_cas_normalization.py::test_alias_resolution_cache_authority_and_moa_follow_canonical_cas`, `tests/test_cas_normalization.py::test_unknown_active_is_flagged_without_moa_and_model_cas_is_dropped` |",
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


def test_semantically_hollow_or_comment_only_test_evidence_fails(tmp_path: Path) -> None:
    document = _fixture(tmp_path)
    (tmp_path / "tests/test_staleness.py").write_text(
        "# def test_manifest_carries_basis_and_the_default_policy(): assert contract\n",
        encoding="utf-8",
    )

    report = check_status(document, tmp_path)

    assert any(issue.code == "non_executable_evidence" for issue in report.issues)


def test_wrong_existing_evidence_fails_the_canonical_contract(tmp_path: Path) -> None:
    rows = ROWS.replace(
        "`tests/test_staleness.py::test_manifest_carries_basis_and_the_default_policy`",
        "`tests/test_registry.py::test_absent_cache_is_off_not_an_error_and_warns_once`",
        1,
    )

    report = check_status(_fixture(tmp_path, rows), tmp_path)

    assert any(issue.code == "evidence_contract" for issue in report.issues)


def test_ci_runs_canonical_checker_against_repository_document() -> None:
    workflow = (Path(__file__).resolve().parents[1] / ".github/workflows/ci.yml").read_text(
        encoding="utf-8"
    )

    run_commands = re.findall(r"^\s*run:\s*(.+)$", workflow, flags=re.MULTILINE)
    assert [
        "python",
        "scripts/check_product_status.py",
        "--root",
        ".",
        "--document",
        "docs/PRODUCT_SPEC.md",
    ] in [shlex.split(command) for command in run_commands]


def test_cli_stale_fixture_exits_nonzero_with_json_reason(tmp_path: Path) -> None:
    stale = ROWS.replace("| AC-01 | COMPLETE |", "| AC-01 | INCOMPLETE |").replace(
        "| NONE |", "| BLOCKING: old claim |", 1
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
