from __future__ import annotations

import ast
import io
import json
import os
import re
import shlex
import subprocess
import sys
import tarfile
from pathlib import Path

import pytest

from scripts.check_product_status import Issue, _validate_pytest_receipt, check_status


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
    repository = Path(__file__).resolve().parents[1]
    paths = (
        *TEST_FUNCTIONS,
        "docs/FIRST-PACK-EVIDENCE.md",
        "docs/CHUNK-SWEEP-2026-08.md",
        "scripts/sweep_chunk_size.py",
    )
    for relative in paths:
        destination = root / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes((repository / relative).read_bytes())
    document = root / "docs/PRODUCT_SPEC.md"
    document.write_text(
        "# Product\n\n<!-- product-status:v1:start -->\n"
        + rows
        + "<!-- product-status:v1:end -->\n",
        encoding="utf-8",
    )
    return document


def _executable_fixture(root: Path) -> Path:
    repository = Path(__file__).resolve().parents[1]
    archive = subprocess.run(
        ["git", "archive", "--format=tar", "0baab72"],
        cwd=repository,
        check=True,
        capture_output=True,
    ).stdout
    with tarfile.open(fileobj=io.BytesIO(archive), mode="r:") as tar:
        tar.extractall(root, filter="data")
    for relative in (*TEST_FUNCTIONS, "tests/factories.py"):
        destination = root / relative
        destination.write_bytes((repository / relative).read_bytes())
    return root / "docs/PRODUCT_SPEC.md"


def _replace_test_body(path: Path, function_name: str, body: str) -> None:
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    function = next(
        node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name == function_name
    )
    lines = source.splitlines(keepends=True)
    replacement = "".join(f"    {line}\n" for line in body.splitlines())
    lines[function.body[0].lineno - 1 : function.end_lineno] = [replacement]
    path.write_text("".join(lines), encoding="utf-8")


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


@pytest.mark.parametrize(
    "body",
    (
        "assert 1",
        "assert object() is not None",
        "# assertion intentionally removed\n    pass",
    ),
)
def test_tautological_or_comment_only_test_evidence_fails(
    tmp_path: Path, body: str
) -> None:
    document = _fixture(tmp_path)
    path = tmp_path / "tests/test_staleness.py"
    _replace_test_body(
        path,
        "test_manifest_carries_basis_and_the_default_policy",
        body,
    )

    report = check_status(document, tmp_path)

    assert any(issue.code == "evidence_integrity" for issue in report.issues)


def test_empty_documentary_evidence_fails(tmp_path: Path) -> None:
    document = _fixture(tmp_path)
    (tmp_path / "docs/FIRST-PACK-EVIDENCE.md").write_text("", encoding="utf-8")

    report = check_status(document, tmp_path)

    assert any(issue.code == "documentary_evidence" for issue in report.issues)


@pytest.mark.parametrize(
    "marker",
    (
        "",
        "<!-- product-evidence:v1:start -->\nnot-json\n<!-- product-evidence:v1:end -->\n",
        '<!-- product-evidence:v1:start -->\n{"evidence_id":"wrong"}\n<!-- product-evidence:v1:end -->\n',
    ),
)
def test_missing_malformed_or_wrong_documentary_marker_fails(
    tmp_path: Path, marker: str
) -> None:
    document = _fixture(tmp_path)
    (tmp_path / "docs/CHUNK-SWEEP-2026-08.md").write_text(marker, encoding="utf-8")

    report = check_status(document, tmp_path)

    assert any(issue.code == "documentary_evidence" for issue in report.issues)


def test_noop_sweep_implementation_fails(tmp_path: Path) -> None:
    document = _fixture(tmp_path)
    (tmp_path / "scripts/sweep_chunk_size.py").write_text(
        "CHUNK_SIZES = (1500, 3000)\n"
        "async def sweep_size():\n    pass\n"
        "async def run():\n    pass\n",
        encoding="utf-8",
    )

    report = check_status(document, tmp_path)

    assert any(issue.code == "evidence_integrity" for issue in report.issues)


def test_wrong_existing_evidence_fails_the_canonical_contract(tmp_path: Path) -> None:
    rows = ROWS.replace(
        "`tests/test_staleness.py::test_manifest_carries_basis_and_the_default_policy`",
        "`tests/test_registry.py::test_absent_cache_is_off_not_an_error_and_warns_once`",
        1,
    )

    report = check_status(_fixture(tmp_path, rows), tmp_path)

    assert any(issue.code == "evidence_contract" for issue in report.issues)


@pytest.mark.parametrize(
    ("xml", "detail"),
    (
        (
            '<testsuites><testsuite tests="0" failures="0" errors="0" skipped="0"/></testsuites>',
            "pytest executed 0 of 13 canonical nodes",
        ),
        (
            '<testsuites><testsuite tests="13" failures="0" errors="0" skipped="13"/></testsuites>',
            "pytest skipped 13 canonical nodes",
        ),
        (
            '<testsuites><testsuite tests="12" failures="0" errors="0" skipped="0"/></testsuites>',
            "pytest executed 12 of 13 canonical nodes",
        ),
        (
            '<testsuites><testsuite tests="13" failures="1" errors="0" skipped="0"/></testsuites>',
            "pytest failed 1 canonical nodes",
        ),
    ),
)
def test_execution_receipt_rejects_zero_skipped_deselected_and_failed_evidence(
    tmp_path: Path, xml: str, detail: str
) -> None:
    receipt = tmp_path / "pytest.xml"
    receipt.write_text(xml, encoding="utf-8")

    issue = _validate_pytest_receipt(receipt, expected_count=13)

    assert issue == Issue("evidence_execution", "DOCUMENT", detail)


def test_cli_ignores_collection_only_environment_and_executes_assertions() -> None:
    root = Path(__file__).resolve().parents[1]
    environment = dict(os.environ)
    environment["PYTEST_ADDOPTS"] = "--collect-only"

    result = subprocess.run(
        [
            sys.executable,
            "scripts/check_product_status.py",
            "--root",
            ".",
            "--document",
            "docs/PRODUCT_SPEC.md",
            "--json",
        ],
        cwd=root,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert json.loads(result.stdout)["ok"] is True
    assert "EVIDENCE: 13 canonical pytest nodes passed" in result.stderr


def test_cli_overrides_tracked_collection_only_addopts(tmp_path: Path) -> None:
    document = _executable_fixture(tmp_path)
    (tmp_path / "pyproject.toml").write_text(
        '[tool.pytest.ini_options]\naddopts = "--collect-only"\n',
        encoding="utf-8",
    )

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

    assert result.returncode == 0
    assert json.loads(result.stdout)["ok"] is True


@pytest.mark.parametrize(
    "hook",
    (
        "def pytest_configure(config): config.option.collectonly = True\n",
        "def pytest_collection_modifyitems(config, items):\n"
        "    config.hook.pytest_deselected(items=items)\n"
        "    items[:] = []\n",
        "def pytest_collection_modifyitems(config, items):\n"
        "    removed = items.pop()\n"
        "    config.hook.pytest_deselected(items=[removed])\n",
        "import pytest\n"
        "def pytest_collection_modifyitems(items):\n"
        "    for item in items:\n"
        "        item.add_marker(pytest.mark.skip(reason='hostile skip'))\n",
        "def pytest_runtest_call(item):\n"
        "    raise AssertionError('hostile assertion')\n",
    ),
)
def test_cli_neutralizes_repository_collection_and_runtest_hooks(
    tmp_path: Path, hook: str
) -> None:
    document = _executable_fixture(tmp_path)
    (tmp_path / "conftest.py").write_text(hook, encoding="utf-8")

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
    assert result.returncode == 0
    assert payload["ok"] is True
    assert payload["issues"] == []
    assert "EVIDENCE: 13 canonical pytest nodes passed" in result.stderr


@pytest.mark.parametrize(
    ("conftest_path", "hook"),
    (
        (
            "conftest.py",
            "def pytest_collection_modifyitems(items):\n"
            "    for item in items:\n"
            "        item.runtest = lambda: None\n",
        ),
        (
            "tests/conftest.py",
            "import pytest\n"
            "@pytest.hookimpl(tryfirst=True)\n"
            "def pytest_runtest_call(item):\n"
            "    item.runtest = lambda: None\n",
        ),
    ),
)
def test_cli_neutralizes_repository_conftest_execution_replacement(
    tmp_path: Path, conftest_path: str, hook: str
) -> None:
    document = _executable_fixture(tmp_path)
    marker = tmp_path / "hostile-conftest-loaded"
    conftest = tmp_path / conftest_path
    original = conftest.read_text(encoding="utf-8") if conftest.exists() else ""
    conftest.write_text(
        original
        + "\nimport os\n"
        "from pathlib import Path\n"
        "Path(os.environ['G009_HOOK_MARKER']).write_text('loaded')\n"
        + hook,
        encoding="utf-8",
    )
    environment = dict(os.environ)
    environment["G009_HOOK_MARKER"] = str(marker)

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
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert json.loads(result.stdout)["ok"] is True
    assert "EVIDENCE: 13 canonical pytest nodes passed" in result.stderr
    assert not marker.exists()


def test_cli_neutralizes_pythonpath_pytest_module_injection(tmp_path: Path) -> None:
    document = _executable_fixture(tmp_path)
    injection = tmp_path / "injection"
    injection.mkdir()
    marker = tmp_path / "hostile-pytest-loaded"
    (injection / "pytest.py").write_text(
        "import os, sys\n"
        "from pathlib import Path\n"
        "Path(os.environ['G009_HOOK_MARKER']).write_text('loaded')\n"
        "args = sys.argv[1:]\n"
        "receipt = Path(args[args.index('--junitxml') + 1])\n"
        "nodes = [arg for arg in args if '::' in arg]\n"
        "cases = ''.join(f'<testcase file=\\\"{node.split(\"::\", 1)[0]}\\\" name=\\\"{node.split(\"::\", 1)[1]}\\\"/>' for node in nodes)\n"
        "receipt.write_text(f'<testsuites><testsuite tests=\\\"{len(nodes)}\\\" failures=\\\"0\\\" errors=\\\"0\\\" skipped=\\\"0\\\">{cases}</testsuite></testsuites>')\n",
        encoding="utf-8",
    )
    environment = dict(os.environ)
    environment["PYTHONPATH"] = str(injection)
    environment["G009_HOOK_MARKER"] = str(marker)

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
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert json.loads(result.stdout)["ok"] is True
    assert "EVIDENCE: 13 canonical pytest nodes passed" in result.stderr
    assert not marker.exists()


@pytest.mark.parametrize(
    ("conftest_path", "hook"),
    (
        (
            "conftest.py",
            "def pytest_collection_modifyitems(items):\n"
            "    for item in items:\n"
            "        item.runtest = lambda: None\n",
        ),
        (
            "tests/conftest.py",
            "def pytest_collection_modifyitems(items):\n"
            "    for item in items:\n"
            "        item.runtest = lambda: None\n",
        ),
        (
            "tests/conftest.py",
            "from _pytest.python import Function\n"
            "Function.runtest = lambda self: None\n",
        ),
    ),
)
def test_cli_runs_genuine_assertions_despite_noop_conftest(
    tmp_path: Path, conftest_path: str, hook: str
) -> None:
    document = _executable_fixture(tmp_path)
    schemas = tmp_path / "ontologylab/schemas.py"
    schemas.write_text(
        schemas.read_text(encoding="utf-8").replace('"eppo_code"', '"forged_code"'),
        encoding="utf-8",
    )
    conftest = tmp_path / conftest_path
    original = conftest.read_text(encoding="utf-8") if conftest.exists() else ""
    conftest.write_text(original + "\n" + hook, encoding="utf-8")

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
        {
            "code": "evidence_execution",
            "id": "DOCUMENT",
            "detail": "pytest failed 2 canonical nodes",
        }
    ]


def _run_imported_runtest_attack(
    tmp_path: Path,
    factory_attack: str,
    *,
    transitive_attack: str | None = None,
) -> subprocess.CompletedProcess[str]:
    document = _executable_fixture(tmp_path)
    factories = tmp_path / "tests/factories.py"
    factories.write_text(
        factories.read_text(encoding="utf-8") + "\n" + factory_attack,
        encoding="utf-8",
    )
    if transitive_attack is not None:
        (tmp_path / "tests/hostile_transitive.py").write_text(
            transitive_attack,
            encoding="utf-8",
        )
    schemas = tmp_path / "ontologylab/schemas.py"
    schemas.write_text(
        schemas.read_text(encoding="utf-8").replace('"eppo_code"', '"forged_code"'),
        encoding="utf-8",
    )
    return subprocess.run(
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


def _assert_corrupted_product_fails(result: subprocess.CompletedProcess[str]) -> None:
    payload = json.loads(result.stdout)
    assert result.returncode == 1
    assert payload["ok"] is False
    assert payload["issues"] == [
        {
            "code": "evidence_execution",
            "id": "DOCUMENT",
            "detail": "pytest failed 2 canonical nodes",
        }
    ]


def test_cli_rejects_imported_helper_replacing_pytest_runtest(tmp_path: Path) -> None:
    result = _run_imported_runtest_attack(
        tmp_path,
        "from _pytest.python import Function\n"
        "Function.runtest = lambda self: None\n",
    )

    _assert_corrupted_product_fails(result)


def test_cli_executes_assertions_after_imported_runtest_code_mutation(
    tmp_path: Path,
) -> None:
    result = _run_imported_runtest_attack(
        tmp_path,
        "from _pytest.python import Function\n"
        "Function.runtest.__code__ = (lambda self: None).__code__\n",
    )

    _assert_corrupted_product_fails(result)


def test_cli_executes_assertions_after_transitive_runtest_mutation(
    tmp_path: Path,
) -> None:
    result = _run_imported_runtest_attack(
        tmp_path,
        "from tests import hostile_transitive\n",
        transitive_attack=(
            "from _pytest.python import Function\n"
            "Function.runtest.__code__ = (lambda self: None).__code__\n"
        ),
    )

    _assert_corrupted_product_fails(result)


def test_cli_executes_assertions_after_bound_runtest_masking(tmp_path: Path) -> None:
    result = _run_imported_runtest_attack(
        tmp_path,
        "from _pytest.python import Function\n"
        "original_runtest = Function.runtest\n"
        "class MaskedRuntest:\n"
        "    def __get__(self, instance, owner):\n"
        "        if instance is None:\n"
        "            return original_runtest\n"
        "        return lambda: None\n"
        "Function.runtest = MaskedRuntest()\n",
    )

    _assert_corrupted_product_fails(result)


def test_ci_runs_canonical_checker_against_repository_document() -> None:
    workflow = (Path(__file__).resolve().parents[1] / ".github/workflows/ci.yml").read_text(
        encoding="utf-8"
    )

    run_commands = re.findall(r"^\s*run:\s*(.+)$", workflow, flags=re.MULTILINE)
    commands = [shlex.split(command) for command in run_commands]
    assert [
        "python",
        "-m",
        "pytest",
        "-q",
        "-c",
        "/dev/null",
        "--rootdir",
        ".",
    ] in commands
    assert re.search(r'PYTEST_ADDOPTS:\s*["\']{2}', workflow)
    assert workflow.count('PYTHONPATH: ""') == 2
    assert workflow.count('PYTEST_DISABLE_PLUGIN_AUTOLOAD: "1"') == 2
    assert [
        "python",
        "scripts/check_product_status.py",
        "--root",
        ".",
        "--document",
        "docs/PRODUCT_SPEC.md",
    ] in commands


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
