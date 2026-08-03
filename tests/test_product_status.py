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

from scripts import check_product_status
from scripts.check_product_status import (
    TEST_EVIDENCE_DIGESTS,
    Issue,
    _read_execution_ledger,
    _validate_pytest_receipt,
    check_status,
)


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


# One deliberate product defect per canonical node, measured so that the union
# fails all thirteen. A test that asserts "13 failed" therefore notices any single
# node that was skipped, deselected, or answered by something other than its own
# audited body — the narrower `eppo_code` corruption used before sensitized only
# two nodes, leaving eleven free to be faked without changing the verdict.
CANONICAL_CORRUPTIONS: tuple[tuple[str, str, str], ...] = (
    (
        "ontologylab/schemas.py",
        '"eppo_code": {"type": "string", "required": False}',
        '"forged_code": {"type": "string", "required": False}',
    ),
    (
        "ontologylab/registry.py",
        'return " ".join(unicodedata.normalize("NFKC", value).casefold().split())',
        'return " ".join(unicodedata.normalize("NFKC", value).split())',
    ),
    (
        "ontologylab/registry.py",
        "        if self.path.is_file() or self._absence_reported:\n"
        "            return None\n"
        "        self._absence_reported = True\n"
        '        return "EPPO cache absent"',
        "        if self.path.is_file():\n"
        "            return None\n"
        '        return "EPPO cache absent"',
    ),
    (
        "ontologylab/normalization.py",
        "    if model_code is not _MISSING:\n"
        '        properties["eppo_code_dropped"] = model_code',
        "    if False:\n" '        properties["eppo_code_dropped"] = model_code',
    ),
    (
        "ontologylab/normalization.py",
        '    properties.pop("moa_scheme", None)\n'
        '    properties.pop("moa_code", None)',
        '    properties.pop("moa_scheme", None)\n'
        '    properties.pop("moa_code", None)\n'
        "    return proposal",
    ),
    (
        "ontologylab/packbuilder.py",
        '    "pending_verified_count_threshold": 0,',
        '    "pending_verified_count_threshold": 7,',
    ),
    (
        "ontologylab/semantic_staleness.py",
        "            details[kind] = [\n"
        '                {"id": item_id, "label": source[item_id]["label"]}\n'
        "                for item_id in sorted(ids)\n"
        "            ]",
        "            details[kind] = []",
    ),
    (
        "ontologylab/mcp_server.py",
        "                pending_verified_count=max(0, store_count - pack_count),",
        "                pending_verified_count=0,",
    ),
    (
        "ontologylab/mcp_server.py",
        '    entity["edges"] = edges\n    return entity',
        '    entity["edges"] = edges\n'
        '    entity.pop("properties", None)\n'
        "    return entity",
    ),
    (
        "ontologylab/mcp_server.py",
        "    @mcp.tool()\n    def get_communities(",
        "    def get_communities(",
    ),
)
EVERY_NODE_FAILED = {
    "code": "evidence_execution",
    "id": "DOCUMENT",
    "detail": "pytest failed 13 canonical nodes",
}


def _corrupt_every_canonical_node(root: Path) -> None:
    """Break the product behind every canonical node, so skipping one shows up."""
    for relative, old, new in CANONICAL_CORRUPTIONS:
        path = root / relative
        source = path.read_text(encoding="utf-8")
        assert old in source, f"corruption anchor vanished from {relative}"
        path.write_text(source.replace(old, new), encoding="utf-8")


def _run_checker(
    root: Path,
    document: Path,
    *,
    environment: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            "scripts/check_product_status.py",
            "--root",
            str(root),
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


def _canonical_parameters(source: str, function_name: str) -> tuple[str, ...]:
    """The fixture parameters of the first definition with that name."""
    tree = ast.parse(source)
    function = next(
        node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name == function_name
    )
    return tuple(argument.arg for argument in function.args.args)


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
def test_in_place_body_replacement_fails_the_digest(
    tmp_path: Path, body: str
) -> None:
    """Editing the audited definition in place breaks its digest.

    This is the whole of what the static digest promises: it identifies one
    definition's source. It says nothing about which callable the module's name is
    bound to at run time, which is why the execution guarantee is tested
    separately against real product corruption.
    """
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


def test_execution_ledger_accepts_only_the_audited_digests(tmp_path: Path) -> None:
    ledger = tmp_path / "ledger.json"
    ledger.write_text(json.dumps(dict(TEST_EVIDENCE_DIGESTS)), encoding="utf-8")

    executed, issue = _read_execution_ledger(ledger)

    assert issue is None
    assert len(executed) == 13


@pytest.mark.parametrize(
    ("payload", "detail"),
    (
        pytest.param(
            "{ not json",
            "execution ledger is missing or malformed",
            id="unparseable",
        ),
        pytest.param(
            '["tests/test_registry.py::test_absent_cache_is_off_not_an_error_and_warns_once"]',
            "execution ledger is missing or malformed",
            id="wrong-shape",
        ),
        pytest.param(
            "{}",
            "executed source mismatch: missing="
            f"{sorted(TEST_EVIDENCE_DIGESTS)}; unexpected=[]; divergent=[]",
            id="nothing-executed",
        ),
    ),
)
def test_execution_ledger_rejects_anything_else(
    tmp_path: Path, payload: str, detail: str
) -> None:
    ledger = tmp_path / "ledger.json"
    ledger.write_text(payload, encoding="utf-8")

    _executed, issue = _read_execution_ledger(ledger)

    assert issue == Issue("evidence_execution", "DOCUMENT", detail)


def test_execution_ledger_names_a_node_that_ran_other_source(tmp_path: Path) -> None:
    node_id = "tests/test_registry.py::test_absent_cache_is_off_not_an_error_and_warns_once"
    divergent = dict(TEST_EVIDENCE_DIGESTS)
    divergent[node_id] = "0" * 64
    ledger = tmp_path / "ledger.json"
    ledger.write_text(json.dumps(divergent), encoding="utf-8")

    _executed, issue = _read_execution_ledger(ledger)

    assert issue == Issue(
        "evidence_execution",
        "DOCUMENT",
        f"executed source mismatch: missing=[]; unexpected=[]; divergent=['{node_id}']",
    )


def test_missing_ledger_is_not_a_silent_pass(tmp_path: Path) -> None:
    _executed, issue = _read_execution_ledger(tmp_path / "absent.json")

    assert issue == Issue(
        "evidence_execution", "DOCUMENT", "execution ledger is missing or malformed"
    )


def test_cli_reports_the_canonical_receipt_for_the_pristine_repository() -> None:
    """The gate still passes honestly, and the count comes from what ran."""
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
        cwd=Path(__file__).resolve().parents[1],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert json.loads(result.stdout)["ok"] is True
    assert "EVIDENCE: 13 canonical pytest nodes passed" in result.stderr


def test_cli_detects_a_defect_behind_every_single_canonical_node(
    tmp_path: Path,
) -> None:
    """Each of the thirteen nodes carries its own signal.

    The union corruption breaks the product behind all thirteen, so the count in
    the diagnostic is thirteen only if all thirteen audited bodies really ran. A
    node that were skipped, deselected, or answered by a stand-in would lower it.
    """
    document = _executable_fixture(tmp_path)
    _corrupt_every_canonical_node(tmp_path)

    result = _run_checker(tmp_path, document)

    payload = json.loads(result.stdout)
    assert result.returncode == 1
    assert payload["issues"] == [EVERY_NODE_FAILED]


def test_cli_ignores_collection_only_environment_and_executes_assertions(
    tmp_path: Path,
) -> None:
    """`--collect-only` in the parent environment neither reaches nor excuses the child.

    A leaked `--collect-only` produces no call phases at all, which reads as
    "executed 0 of 13"; skipping execution reads as a pass. Only genuine
    execution of every audited body under the corruption reads as thirteen
    failures.
    """
    document = _executable_fixture(tmp_path)
    _corrupt_every_canonical_node(tmp_path)
    environment = dict(os.environ)
    environment["PYTEST_ADDOPTS"] = "--collect-only"

    result = _run_checker(tmp_path, document, environment=environment)

    payload = json.loads(result.stdout)
    assert result.returncode == 1
    assert payload["issues"] == [EVERY_NODE_FAILED]


def test_cli_overrides_tracked_collection_only_addopts(tmp_path: Path) -> None:
    """A tracked `addopts = --collect-only` is overridden, not merely tolerated."""
    document = _executable_fixture(tmp_path)
    _corrupt_every_canonical_node(tmp_path)
    (tmp_path / "pyproject.toml").write_text(
        '[tool.pytest.ini_options]\naddopts = "--collect-only"\n',
        encoding="utf-8",
    )

    result = _run_checker(tmp_path, document)

    payload = json.loads(result.stdout)
    assert result.returncode == 1
    assert payload["issues"] == [EVERY_NODE_FAILED]


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


def test_cli_runs_genuine_assertions_despite_noop_conftest(tmp_path: Path) -> None:
    """A repository conftest that neuters pytest dispatch changes no verdict.

    This used to carry three parameters (two `collection_modifyitems` hooks and a
    class-level `Function.runtest` assignment). `--noconftest` means none of them is
    ever imported, so the three were indistinguishable from each other; the
    surviving single case states the one property that is actually checked. The
    `Function.runtest` shapes still have real coverage below, where an *imported*
    helper — which `--noconftest` cannot stop — performs them.
    """
    document = _executable_fixture(tmp_path)
    _corrupt_every_canonical_node(tmp_path)
    (tmp_path / "conftest.py").write_text(
        "def pytest_collection_modifyitems(items):\n"
        "    for item in items:\n"
        "        item.runtest = lambda: None\n",
        encoding="utf-8",
    )

    result = _run_checker(tmp_path, document)

    payload = json.loads(result.stdout)
    assert result.returncode == 1
    assert payload["ok"] is False
    assert payload["issues"] == [EVERY_NODE_FAILED]


@pytest.mark.parametrize(
    "divergence",
    (
        pytest.param(
            "\n\ndef {name}({parameters}) -> None:\n    return None\n",
            id="trailing-duplicate-def",
        ),
        pytest.param(
            "\n\n{name} = lambda {parameters}: None\n",
            id="module-level-rebinding",
        ),
        pytest.param(
            "\n\ndef _stand_in({parameters}) -> None:\n    return None\n"
            "{name} = _stand_in\n",
            id="module-level-alias",
        ),
        pytest.param(
            "\n\n{name} = lambda **unused: None\n",
            id="module-level-rebinding-without-fixtures",
        ),
    ),
)
def test_cli_executes_the_audited_source_not_the_name_it_is_bound_to(
    tmp_path: Path, divergence: str
) -> None:
    """The audited definition runs even when the name resolves to something else.

    The digest gate hashes the first top-level definition with the canonical name,
    so any later binding of that same name leaves the digest intact while pytest
    would collect and call the replacement. Each shape here keeps the audited
    definition untouched, rebinds the name to a passing stand-in, and breaks the
    product behind every canonical node: the checker must still fail all thirteen.
    The last shape declares no fixtures at all, so pytest's setup phase resolves
    none of the ones the audited bodies need; they are requested on demand instead.
    """
    document = _executable_fixture(tmp_path)
    _corrupt_every_canonical_node(tmp_path)
    for relative, names in TEST_FUNCTIONS.items():
        path = tmp_path / relative
        source = path.read_text(encoding="utf-8")
        for name in names:
            parameters = ", ".join(_canonical_parameters(source, name))
            source += divergence.format(name=name, parameters=parameters)
        path.write_text(source, encoding="utf-8")

    result = _run_checker(tmp_path, document)

    payload = json.loads(result.stdout)
    assert result.returncode == 1
    assert payload["ok"] is False
    assert payload["issues"] == [EVERY_NODE_FAILED]


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
    _corrupt_every_canonical_node(tmp_path)
    return _run_checker(tmp_path, document)


def _assert_corrupted_product_fails(result: subprocess.CompletedProcess[str]) -> None:
    payload = json.loads(result.stdout)
    assert result.returncode == 1
    assert payload["ok"] is False
    assert payload["issues"] == [EVERY_NODE_FAILED]


@pytest.mark.parametrize(
    ("factory_attack", "transitive_attack"),
    (
        pytest.param(
            "from _pytest.python import Function\n"
            "Function.runtest = lambda self: None\n",
            None,
            id="runtest-reassignment",
        ),
        pytest.param(
            "from _pytest.python import Function\n"
            "Function.runtest.__code__ = (lambda self: None).__code__\n",
            None,
            id="runtest-code-mutation",
        ),
        pytest.param(
            "from tests import hostile_transitive\n",
            "from _pytest.python import Function\n"
            "Function.runtest.__code__ = (lambda self: None).__code__\n",
            id="transitive-runtest-code-mutation",
        ),
        pytest.param(
            "from _pytest.python import Function\n"
            "original_runtest = Function.runtest\n"
            "class MaskedRuntest:\n"
            "    def __get__(self, instance, owner):\n"
            "        if instance is None:\n"
            "            return original_runtest\n"
            "        return lambda: None\n"
            "Function.runtest = MaskedRuntest()\n",
            None,
            id="bound-runtest-masking",
        ),
        pytest.param(
            "import tests.test_registry as _module\n"
            "_module.test_absent_cache_is_off_not_an_error_and_warns_once = (\n"
            "    lambda tmp_path: None\n"
            ")\n",
            None,
            id="imported-helper-rebinds-canonical-name",
        ),
    ),
)
def test_cli_executes_assertions_despite_imported_helper_attacks(
    tmp_path: Path, factory_attack: str, transitive_attack: str | None
) -> None:
    """`--noconftest` cannot stop an imported helper; the audited source still runs.

    `tests/factories.py` is imported by canonical modules, so it executes inside the
    trusted child. Each shape attacks a different part of pytest's dispatch — the
    `runtest` attribute, its code object, a descriptor that masks it, and the module
    namespace that `item.obj` reads.
    """
    result = _run_imported_runtest_attack(
        tmp_path, factory_attack, transitive_attack=transitive_attack
    )

    _assert_corrupted_product_fails(result)


def test_cli_rejects_a_forged_receipt_written_by_an_imported_helper(
    tmp_path: Path,
) -> None:
    """A perfect receipt does not substitute for a record of what ran.

    An imported helper replaces pytest's JUnit writer with a forger that reports
    thirteen passes whatever happened, so every arithmetic gate on the receipt is
    satisfied. What it cannot forge is the checker's own record of the audited
    definitions it compiled and called, which is why the mismatch is named.
    """
    result = _run_imported_runtest_attack(
        tmp_path,
        "import atexit, sys\n"
        f"_NODES = {tuple(node.split('::') for node in sorted(TEST_EVIDENCE_DIGESTS))!r}\n"
        "def _forge():\n"
        "    receipt = sys.argv[sys.argv.index('--junitxml') + 1]\n"
        "    cases = ''.join(\n"
        '        f\'<testcase file="{node[0]}" name="{node[1]}"/>\'\n'
        "        for node in _NODES\n"
        "    )\n"
        "    with open(receipt, 'w', encoding='utf-8') as handle:\n"
        "        handle.write(\n"
        '            \'<testsuites><testsuite tests="13" failures="0" \'\n'
        '            \'errors="0" skipped="0">\' + cases + \'</testsuite></testsuites>\'\n'
        "        )\n"
        "atexit.register(_forge)\n",
    )

    payload = json.loads(result.stdout)
    assert result.returncode == 1
    assert payload["ok"] is False
    (issue,) = payload["issues"]
    assert issue["code"] == "evidence_execution"
    assert issue["detail"].startswith("executed source mismatch: missing=[")


def test_receipt_count_is_the_number_of_audited_bodies_that_ran(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The printed number is execution-derived, not the dict literal's length.

    Reporting `len(TEST_EVIDENCE_DIGESTS)` cannot disagree with the gate that uses
    the same length, so the sentence carried no information about what ran.
    """
    monkeypatch.setattr(
        check_product_status, "_execute_test_evidence", lambda root: (None, 7)
    )

    exit_code = check_product_status.main(
        ["--root", str(Path(__file__).resolve().parents[1])]
    )

    assert exit_code == 0
    assert "EVIDENCE: 7 canonical pytest nodes passed" in capsys.readouterr().err


def _workflow_steps(workflow: str) -> list[str]:
    """Split a workflow into its `- name:` step blocks, comments excluded."""
    steps: list[str] = []
    for line in workflow.splitlines():
        if line.strip().startswith("#"):
            continue
        if re.match(r"\s*- name:", line):
            steps.append(line)
        elif steps:
            steps[-1] += "\n" + line
    return steps


@pytest.mark.parametrize(
    ("command", "hardening"),
    (
        (
            ["python", "-m", "pytest", "-q", "-c", "/dev/null", "--rootdir", "."],
            ('PYTHONPATH: ""', 'PYTEST_ADDOPTS: ""', 'PYTEST_DISABLE_PLUGIN_AUTOLOAD: "1"'),
        ),
        (
            [
                "python",
                "scripts/check_product_status.py",
                "--root",
                ".",
                "--document",
                "docs/PRODUCT_SPEC.md",
            ],
            ('PYTHONPATH: ""', 'PYTEST_ADDOPTS: ""', 'PYTEST_DISABLE_PLUGIN_AUTOLOAD: "1"'),
        ),
    ),
)
def test_ci_hardens_the_step_that_runs_each_canonical_command(
    command: list[str], hardening: tuple[str, ...]
) -> None:
    """Each command's own step carries the hardening.

    Counting occurrences across the whole file could not tell which step had them,
    so the checker step was free to lose `PYTEST_ADDOPTS` while the assertion stayed
    green on the pytest step alone.
    """
    workflow = (
        Path(__file__).resolve().parents[1] / ".github/workflows/ci.yml"
    ).read_text(encoding="utf-8")

    owning_steps = [
        step
        for step in _workflow_steps(workflow)
        if any(
            shlex.split(run) == command
            for run in re.findall(r"^\s*run:\s*(.+)$", step, flags=re.MULTILINE)
        )
    ]

    assert len(owning_steps) == 1, shlex.join(command)
    for setting in hardening:
        assert setting in owning_steps[0], (shlex.join(command), setting)


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
