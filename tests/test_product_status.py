from __future__ import annotations

import ast
import hashlib
import hmac
import io
import json
import os
import py_compile
import re
import shlex
import site
import struct
import subprocess
import sys
import tarfile
import types
from pathlib import Path
from types import CodeType

import pytest

from scripts import check_product_status
from scripts.check_product_status import (
    EVIDENCE_MODULE_DIGESTS,
    TEST_EVIDENCE_DIGESTS,
    Issue,
    _product_digests,
    _read_execution_ledger,
    _test_digest,
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
        *EVIDENCE_MODULE_DIGESTS,
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
    for relative in (*TEST_FUNCTIONS, *EVIDENCE_MODULE_DIGESTS):
        destination = root / relative
        destination.write_bytes((repository / relative).read_bytes())
    return root / "docs/PRODUCT_SPEC.md"


def _checker_with_refreshed_digests(root: Path, destination: Path | None = None) -> Path:
    """A checker whose declared digests are regenerated from `root` as it stands.

    This is the maintainer who refreshes the constants after an edit — the one path by
    which a tampered evidence file can get past the static content gate. Tests use it
    to reach the in-run guards that sit behind that gate.
    """
    if destination is None or root in destination.parents or root == destination.parent:
        # Beside the audited tree, not inside it, and under a directory pytest reaps.
        # `tempfile.mkdtemp` here leaked one directory per test that reached the in-run
        # guards -- 1265 of them were found in TMPDIR across earlier lanes.
        beside = root.parent / (root.name + "-checker")
        beside.mkdir(exist_ok=True)
        destination = beside / "check_product_status.py"
    source = (
        Path(__file__).resolve().parents[1] / "scripts/check_product_status.py"
    ).read_text(encoding="utf-8")
    modules = {
        relative: hashlib.sha256((root / relative).read_bytes()).hexdigest()
        for relative in EVIDENCE_MODULE_DIGESTS
    }
    nodes = {
        node_id: _test_digest(root / node_id.split("::")[0], node_id.split("::")[1])
        for node_id in TEST_EVIDENCE_DIGESTS
    }
    destination.write_text(
        source.replace(
            "EVIDENCE_MODULE_DIGESTS: Final = {",
            f"EVIDENCE_MODULE_DIGESTS: Final = {modules!r}\n_SUPERSEDED = {{",
            1,
        ).replace(
            "TEST_EVIDENCE_DIGESTS: Final = {",
            f"TEST_EVIDENCE_DIGESTS: Final = {nodes!r}\n_SUPERSEDED_NODES = {{",
            1,
        ),
        encoding="utf-8",
    )
    return destination


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


# The corruption anchors above all live in `ontologylab/**`. These live on the other
# surface — the evidence modules' own namespace and one fixture body — because that is
# where the v3 gate was hollow: a module-level shadow of a product import, or a stubbed
# helper, left every audited body byte-identical and every AST digest matching while the
# bodies measured a stand-in instead of the product.
EVIDENCE_SURFACE_CORRUPTIONS: tuple[tuple[str, str, str], ...] = (
    (
        "tests/test_cas_normalization.py",
        "def test_alias_resolution_cache_authority_and_moa_follow_canonical_cas",
        "def normalize_proposal(proposal, cache, moa_cache=None):\n"
        "    return proposal\n\n\n"
        "def test_alias_resolution_cache_authority_and_moa_follow_canonical_cas",
    ),
    (
        "tests/test_normalization.py",
        "def test_unresolved_organism_is_kept_flagged_and_model_code_is_dropped",
        "normalize_proposal = lambda proposal, *rest, **kw: proposal\n\n\n"
        "def test_unresolved_organism_is_kept_flagged_and_model_code_is_dropped",
    ),
    (
        "tests/test_mcp_two_tier.py",
        '    """A pack with alias/property-rich nodes, loaded into a session."""',
        '    """A pack with alias/property-rich nodes, loaded into a session."""\n'
        "    import types\n"
        "    return types.SimpleNamespace(), 'forged-pack'",
    ),
    (
        "tests/factories.py",
        "def make_entity(",
        "def _superseded_make_entity(",
    ),
)


def _corrupt_evidence_surface(root: Path, index: int) -> str:
    """Apply one evidence-namespace corruption and return the file it touched."""
    relative, old, new = EVIDENCE_SURFACE_CORRUPTIONS[index]
    path = root / relative
    source = path.read_text(encoding="utf-8")
    assert old in source, f"corruption anchor vanished from {relative}"
    path.write_text(source.replace(old, new, 1), encoding="utf-8")
    return relative


def _run_checker(
    root: Path,
    document: Path,
    *,
    environment: dict[str, str] | None = None,
    checker: str = "scripts/check_product_status.py",
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            checker,
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


def test_evidence_digest_ignores_version_specific_empty_ast_fields(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Legacy ``ast.dump`` formatting cannot change source identity."""
    original_dump = ast.dump

    def legacy_dump(node, annotate_fields=True, include_attributes=False):
        try:
            return original_dump(
                node,
                annotate_fields=annotate_fields,
                include_attributes=include_attributes,
                show_empty=True,
            )
        except TypeError:  # Python 3.11/3.12 always include empty fields
            return original_dump(
                node,
                annotate_fields=annotate_fields,
                include_attributes=include_attributes,
            )

    monkeypatch.setattr(check_product_status.ast, "dump", legacy_dump)
    node_id = next(iter(TEST_EVIDENCE_DIGESTS))
    path, function_name = node_id.split("::", 1)

    assert _test_digest(Path(path), function_name) == TEST_EVIDENCE_DIGESTS[node_id]


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


LEDGER_SECRET = b"k" * 64
REPOSITORY = Path(__file__).resolve().parents[1]


class _StopBeforeExec(Exception):
    """Raised by the fakes below so the observed call never actually happens."""


class _Flags:
    """Just enough of `sys.flags` for the re-exec guard to read."""

    def __init__(self, *, isolated: bool, no_site: bool, safe_path: bool) -> None:
        self.isolated = isolated
        self.no_site = no_site
        self.safe_path = safe_path
        self.optimize = 0
_SITE_DIRS = [
    entry for entry in site.getsitepackages() if Path(entry).is_dir()
]


def _ledger(*, signature: str | None = None, **overrides: object) -> str:
    """A report envelope signed the way the child signs it."""
    body: dict[str, object] = {
        "executed": dict(TEST_EVIDENCE_DIGESTS),
        "modules": dict(EVIDENCE_MODULE_DIGESTS),
        "unaudited": [],
        "returncode": 0,
        "product": _product_digests(Path(__file__).resolve().parents[1]),
        "substituted": [],
    }
    body.update(overrides)
    payload = json.dumps(body, sort_keys=True)
    if signature is None:
        signature = hmac.new(
            LEDGER_SECRET, payload.encode("utf-8"), hashlib.sha256
        ).hexdigest()
    return json.dumps({"payload": payload, "signature": signature})


def test_execution_ledger_accepts_only_the_audited_digests(tmp_path: Path) -> None:
    ledger = tmp_path / "ledger.json"
    ledger.write_text(_ledger(), encoding="utf-8")

    executed, issue, returncode = _read_execution_ledger(ledger, LEDGER_SECRET, REPOSITORY)

    assert issue is None
    assert len(executed) == 13
    assert returncode == 0


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
            "execution report is not signed by this run",
            id="wrong-shape",
        ),
        pytest.param(
            json.dumps({"executed": dict(TEST_EVIDENCE_DIGESTS)}),
            "execution report is not signed by this run",
            id="missing-envelope",
        ),
        pytest.param(
            _ledger(signature="0" * 64),
            "execution report is not signed by this run",
            id="wrong-signature",
        ),
        pytest.param(
            json.dumps(
                {
                    "payload": json.dumps({"executed": {}}),
                    "signature": hmac.new(
                        LEDGER_SECRET,
                        json.dumps({"executed": {}}).encode("utf-8"),
                        hashlib.sha256,
                    ).hexdigest(),
                }
            ),
            "execution ledger is missing or malformed",
            id="signed-but-missing-sections",
        ),
        pytest.param(
            _ledger(executed={}),
            "executed source mismatch: missing="
            f"{sorted(TEST_EVIDENCE_DIGESTS)}; unexpected=[]; divergent=[]",
            id="nothing-executed",
        ),
        pytest.param(
            _ledger(modules={}),
            "evidence module digests were not all verified in-run: "
            f"{sorted(EVIDENCE_MODULE_DIGESTS)}",
            id="no-module-verified",
        ),
        pytest.param(
            _ledger(unaudited=["tests/helpers.py"]),
            "unaudited repository modules on the evidence path: ['tests/helpers.py']",
            id="unaudited-module-loaded",
        ),
    ),
)
def test_execution_ledger_rejects_anything_else(
    tmp_path: Path, payload: str, detail: str
) -> None:
    ledger = tmp_path / "ledger.json"
    ledger.write_text(payload, encoding="utf-8")

    _executed, issue, _returncode = _read_execution_ledger(ledger, LEDGER_SECRET, REPOSITORY)

    assert issue == Issue("evidence_execution", "DOCUMENT", detail)


def test_every_ledger_rejection_returns_the_full_result(tmp_path: Path) -> None:
    """No rejection path returns the wrong number of values.

    One branch returned a 2-tuple from a 3-tuple function, so a signed report with a
    mistyped section raised `ValueError` inside the checker instead of being reported. It
    failed loud rather than open, but it was uncovered; every malformed shape now goes
    through the same three-value contract.
    """
    ledger = tmp_path / "ledger.json"
    shapes = (
        "{ not json",
        json.dumps({"payload": 1, "signature": "x"}),
        _ledger(executed="not-a-mapping"),
        _ledger(modules="not-a-mapping"),
        _ledger(unaudited="not-a-list"),
        _ledger(returncode="not-an-int"),
        _ledger(product="not-a-mapping"),
        _ledger(substituted="not-a-list"),
    )
    for payload in shapes:
        ledger.write_text(payload, encoding="utf-8")

        executed, issue, returncode = _read_execution_ledger(
            ledger, LEDGER_SECRET, REPOSITORY
        )

        assert executed == {}, payload[:40]
        assert issue is not None, payload[:40]
        assert isinstance(returncode, int), payload[:40]


def test_execution_ledger_rejects_a_product_that_changed_under_the_run(
    tmp_path: Path,
) -> None:
    """The product the bodies loaded must still be the product on disk.

    Defence in depth, disclosed as such: a product that rewrites itself mid-run is caught
    first by the read-only tree check, so this comparison is redundant end to end. It is
    kept because it is the half that states the property positively -- the signed payload
    says which product ran -- and it is owned here rather than left untested.
    """
    ledger = tmp_path / "ledger.json"
    drifted = dict(_product_digests(REPOSITORY))
    assert drifted, "the product tree should not be empty"
    first = sorted(drifted)[0]
    drifted[first] = "0" * 64
    ledger.write_text(_ledger(product=drifted), encoding="utf-8")

    _executed, issue, _returncode = _read_execution_ledger(
        ledger, LEDGER_SECRET, REPOSITORY
    )

    assert issue is not None
    assert issue.detail == (
        f"product changed between the audited run and this check: ['{first}']"
    )


def test_execution_ledger_carries_the_childs_own_exit_code(tmp_path: Path) -> None:
    """The exit status the parent believes is the one inside the signed payload.

    `os._exit(0)` can hand the parent a zero the child never chose, so the child states its
    pytest exit code inside the signed report and the parent reads it from there.
    """
    ledger = tmp_path / "ledger.json"
    ledger.write_text(_ledger(returncode=4), encoding="utf-8")

    _executed, issue, returncode = _read_execution_ledger(ledger, LEDGER_SECRET, REPOSITORY)

    assert issue is None
    assert returncode == 4


def test_execution_ledger_names_a_node_that_ran_other_source(tmp_path: Path) -> None:
    node_id = "tests/test_registry.py::test_absent_cache_is_off_not_an_error_and_warns_once"
    divergent = dict(TEST_EVIDENCE_DIGESTS)
    divergent[node_id] = "0" * 64
    ledger = tmp_path / "ledger.json"
    ledger.write_text(_ledger(executed=divergent), encoding="utf-8")

    _executed, issue, _returncode = _read_execution_ledger(ledger, LEDGER_SECRET, REPOSITORY)

    assert issue == Issue(
        "evidence_execution",
        "DOCUMENT",
        f"executed source mismatch: missing=[]; unexpected=[]; divergent=['{node_id}']",
    )


def test_missing_ledger_is_not_a_silent_pass(tmp_path: Path) -> None:
    _executed, issue, _returncode = _read_execution_ledger(
        tmp_path / "absent.json", LEDGER_SECRET, REPOSITORY
    )

    assert issue == Issue(
        "evidence_execution", "DOCUMENT", "execution ledger is missing or malformed"
    )


def test_cli_reports_the_canonical_receipt_for_the_pristine_repository(
    tmp_path: Path,
) -> None:
    """The gate still passes honestly, and the count comes from what ran.

    Audited through an isolated copy of the working tree rather than the checkout itself.
    Pointing `--root` at the live repository made this race with the surrounding pytest
    session, which writes `.pytest_cache` into that same directory while the checker is
    snapshotting it -- the read-only guarantee then correctly reported a write and this test
    failed only in full-suite order. The audit is read-only; the harness around it was not.
    """
    document = _executable_fixture(tmp_path)

    result = _run_checker(tmp_path, document)

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
    """Hostile collection hooks are neutralized *and* the bodies still run.

    Against a pristine product every one of these hooks yields a green receipt whether or
    not a single assertion executed, so the corruption is what makes the assertion mean
    something: each hook tries to suppress, deselect, skip or fake the run, and the gate
    has to come back with all thirteen nodes genuinely red.
    """
    document = _executable_fixture(tmp_path)
    _corrupt_every_canonical_node(tmp_path)
    (tmp_path / "conftest.py").write_text(hook, encoding="utf-8")

    result = _run_checker(tmp_path, document)

    payload = json.loads(result.stdout)
    assert result.returncode == 1
    assert payload["ok"] is False
    assert payload["issues"] == [EVERY_NODE_FAILED]


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
    """The hostile conftest is never imported, and the bodies still ran.

    The marker file proves isolation; on its own it says nothing about execution, because a
    pristine product returns a green receipt either way. The corruption supplies the other
    half: thirteen nodes must come back red, which no un-run body can produce.
    """
    document = _executable_fixture(tmp_path)
    _corrupt_every_canonical_node(tmp_path)
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

    result = _run_checker(tmp_path, document, environment=environment)

    payload = json.loads(result.stdout)
    assert result.returncode == 1
    assert payload["ok"] is False
    assert payload["issues"] == [EVERY_NODE_FAILED]
    assert not marker.exists()


def test_cli_neutralizes_pythonpath_pytest_module_injection(tmp_path: Path) -> None:
    """The forged receipt never loads, and the real run reports the real damage.

    The injected `pytest.py` writes a flawless thirteen-node receipt. Against a pristine
    product that forgery is indistinguishable from the truth, so the corruption is what
    separates them: the genuine run must come back with thirteen failures.
    """
    document = _executable_fixture(tmp_path)
    _corrupt_every_canonical_node(tmp_path)
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

    result = _run_checker(tmp_path, document, environment=environment)

    payload = json.loads(result.stdout)
    assert result.returncode == 1
    assert payload["ok"] is False
    assert payload["issues"] == [EVERY_NODE_FAILED]
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

    The AST digest gate hashes the first top-level definition with the canonical name,
    so any later binding of that same name leaves it intact while pytest would collect
    and call the replacement. Each shape here keeps the audited definition untouched,
    rebinds the name to a passing stand-in, and breaks the product behind every canonical
    node: the checker must still fail all thirteen. The last shape declares no fixtures at
    all, so pytest's setup phase resolves none of the ones the audited bodies need; they
    are requested on demand instead.

    The declared digests are refreshed against the tampered tree first. The whole-file
    gate would otherwise reject these shapes before anything ran, which would prove file
    hashing rather than execution — and execution is the guarantee under test here.
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
    checker = _checker_with_refreshed_digests(tmp_path, tmp_path / "refreshed_checker.py")

    result = _run_checker(tmp_path, document, checker=str(checker))

    payload = json.loads(result.stdout)
    assert result.returncode == 1
    assert payload["ok"] is False
    assert payload["issues"] == [EVERY_NODE_FAILED]


def test_cli_requires_exactly_one_definition_to_carry_the_audited_digest(
    tmp_path: Path,
) -> None:
    """Ambiguity is not resolved in the product's favour; it is refused.

    A byte-identical duplicate of an audited body is what a bad merge produces, and it is
    the shape that shipped in c05f57b: the name resolves to the second copy while the
    content control looks at the first. Neither copy is admissible, because nothing says
    which one the spec meant.

    Reached with refreshed declarations, since the whole-file gate rejects the duplicate
    first; the point here is the in-run rule standing behind it. The mirror case — a
    declared digest matching nothing — is unreachable this way and is covered statically by
    `test_in_place_body_replacement_fails_the_digest`.
    """
    document = _executable_fixture(tmp_path)
    name = "test_absent_cache_is_off_not_an_error_and_warns_once"
    path = tmp_path / "tests/test_registry.py"
    source = path.read_text(encoding="utf-8")
    lines = source.splitlines(keepends=True)
    definition = next(
        node
        for node in ast.parse(source).body
        if isinstance(node, ast.FunctionDef) and node.name == name
    )
    body = "".join(lines[definition.lineno - 1 : definition.end_lineno])
    path.write_text(source + "\n\n" + body, encoding="utf-8")
    checker = _checker_with_refreshed_digests(tmp_path, tmp_path / "refreshed_checker.py")

    result = _run_checker(tmp_path, document, checker=str(checker))

    payload = json.loads(result.stdout)
    assert result.returncode == 1
    assert payload["ok"] is False
    (issue,) = payload["issues"]
    assert issue["code"] == "evidence_execution"
    # A red verdict is not enough: the reason has to reach the operator, so the refusal is
    # reported as a refusal rather than folded into a failed-node count.
    assert "2 definitions carry the audited digest" in issue["detail"]


def _run_imported_runtest_attack(
    tmp_path: Path,
    product_attack: str,
    *,
    transitive_attack: str | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run the CLI with an attack planted in product code that the evidence imports.

    The attack used to live in `tests/factories.py`. That file is now content-pinned, so
    an edit there is caught statically and would no longer exercise the execution path at
    all. `ontologylab/models.py` is imported by `tests/factories.py`, runs in the same
    in-process position at collection time, and is deliberately *not* pinned — it is the
    product under test — so the attack now comes from the one surface that stays
    unverified by design. That is a strictly harder starting position for the checker.
    """
    document = _executable_fixture(tmp_path)
    models = tmp_path / "ontologylab/models.py"
    models.write_text(
        models.read_text(encoding="utf-8") + "\n" + product_attack,
        encoding="utf-8",
    )
    if transitive_attack is not None:
        (tmp_path / "ontologylab/hostile_transitive.py").write_text(
            transitive_attack,
            encoding="utf-8",
        )
    _corrupt_every_canonical_node(tmp_path)
    return _run_checker(tmp_path, document)


NORMALIZATION_MUTANT = (
    "ontologylab/normalization.py",
    "    if proposal.entity_type in ORGANISM_ENTITY_TYPES and isinstance(",
    "    return proposal\n"
    "    if proposal.entity_type in ORGANISM_ENTITY_TYPES and isinstance(",
)
NORMALIZATION_MUTANT_NODES = 4


def _mutate_normalization(root: Path) -> None:
    """Delete normalization: `normalize_proposal` returns its input untouched.

    Narrow on purpose. Four canonical nodes reach this symbol, so it is the corruption a
    namespace shadow of that single name would have to rescue to matter.
    """
    relative, old, new = NORMALIZATION_MUTANT
    path = root / relative
    source = path.read_text(encoding="utf-8")
    assert old in source, f"corruption anchor vanished from {relative}"
    path.write_text(source.replace(old, new, 1), encoding="utf-8")


@pytest.mark.parametrize(
    ("index", "expected"),
    (
        pytest.param(
            0,
            "evidence_module_integrity",
            id="shadowing-def-in-an-evidence-module",
        ),
        pytest.param(
            1,
            "evidence_module_integrity",
            id="shadowing-assignment-in-an-evidence-module",
        ),
        pytest.param(2, "evidence_module_integrity", id="stubbed-fixture-body"),
        pytest.param(3, "evidence_module_integrity", id="renamed-imported-helper"),
    ),
)
def test_cli_rejects_a_shadow_of_the_symbol_under_test(
    tmp_path: Path, index: int, expected: str
) -> None:
    """A stand-in supplied by the evidence module's own namespace is not evidence.

    Each shape leaves all thirteen audited bodies byte-identical — every AST digest still
    matches — and re-supplies, from the evidence module itself, the product symbol the
    mutant deleted or the fixture that builds the inputs. The mutant alone reddens four
    nodes; the point of the shadow is to take that back. It cannot, because the file it
    has to be written into is content-pinned.
    """
    document = _executable_fixture(tmp_path)
    _mutate_normalization(tmp_path)
    relative = _corrupt_evidence_surface(tmp_path, index)

    result = _run_checker(tmp_path, document)

    payload = json.loads(result.stdout)
    assert result.returncode == 1
    assert payload["ok"] is False
    assert {issue["code"] for issue in payload["issues"]} == {expected}
    assert relative in {issue["detail"] for issue in payload["issues"]}


def test_cli_rejects_a_shadow_even_without_the_static_content_gate(
    tmp_path: Path,
) -> None:
    """The in-run half stands on its own.

    The static gate and the in-run closure audit are independent barriers against the same
    thing. This runs a checker whose declared digests were refreshed against the tampered
    tree — the maintainer who blesses a bad merge — so the static gate passes and only the
    in-run half is left. The audited bodies then execute against verified source, so the
    shadow is not on the path and the deleted product behaviour still shows up.

    Note on what this does and does not prove: with the digests refreshed, the verified
    source and the collected module agree, so this stays green if the executor is reverted to
    reading `item.module.__dict__`. Sourcing globals from verified source is defence in
    depth here, not the barrier under test — the barrier is the content pin. A pre-call
    shadow that reaches the collected module without appearing in any pinned file was
    attempted and is not constructible from product code, because the product module is
    imported before the evidence module binds the name it would have to overwrite.
    """
    document = _executable_fixture(tmp_path)
    _mutate_normalization(tmp_path)
    _corrupt_evidence_surface(tmp_path, 0)
    checker = _checker_with_refreshed_digests(tmp_path, tmp_path / "refreshed_checker.py")

    result = _run_checker(tmp_path, document, checker=str(checker))

    payload = json.loads(result.stdout)
    assert result.returncode == 1
    assert payload["ok"] is False
    assert payload["issues"] == [
        {
            "code": "evidence_execution",
            "id": "DOCUMENT",
            "detail": f"pytest failed {NORMALIZATION_MUTANT_NODES} canonical nodes",
        }
    ]


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
            "from ontologylab import hostile_transitive\n",
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


# A forge planted in product code, which is unpinned by design, so it reaches the trusted
# child without touching a content-verified file. It rewrites both artefacts the child
# writes -- the ledger at argv[3] and the JUnit receipt at --junitxml -- and then calls
# `os._exit(0)` so the parent also sees a zero exit. Receipt-only forging is caught by the
# ledger, ledger-only by the receipt, and `os._exit` alone by the receipt; only all three
# together defeated all three gates, which is why the report is signed rather than merely
# well-formed.
_THREE_WAY_FORGE = """
import atexit as _atexit, hashlib as _hl, hmac as _hmac, json as _json, os as _os, sys as _sys
from pathlib import Path as _Path


def _forge():
    try:
        plan = _json.loads(_Path(_sys.argv[2]).read_text())
        nodes, modules = plan["nodes"], plan["modules"]
        payload = _json.dumps({{
            "executed": {{node: entry["digest"] for node, entry in nodes.items()}},
            "modules": dict(modules),
            "unaudited": [],
            "returncode": 0,
        }}, sort_keys=True)
        _Path(_sys.argv[3]).write_text(_json.dumps({{
            "payload": payload,
            "signature": _hmac.new({key!r}, payload.encode(), _hl.sha256).hexdigest(),
        }}))
        receipt = _Path(_sys.argv[_sys.argv.index("--junitxml") + 1])
        cases = "".join(
            '<testcase file="%s" name="%s"/>' % tuple(node.split("::", 1)) for node in nodes
        )
        receipt.write_text(
            '<testsuites><testsuite tests="13" failures="0" errors="0" skipped="0">'
            + cases + "</testsuite></testsuites>"
        )
    finally:
        _sys.stdout.flush()
        _sys.stderr.flush()
        _os._exit(0)


_atexit.register(_forge)
"""


@pytest.mark.parametrize(
    "key",
    (
        pytest.param(b"", id="unsigned-envelope"),
        pytest.param(b"0" * 64, id="wrongly-signed-envelope"),
    ),
)
def test_cli_rejects_a_signed_looking_report_the_child_did_not_sign(
    tmp_path: Path, key: bytes
) -> None:
    """The receipt is bound to a secret the forging code cannot reach.

    The parent hands the child a per-run secret over a pipe; the executor drains it and
    closes the descriptor at import time, before any repository code runs. An `atexit` hook
    therefore fires with a closed descriptor and no key: it can rewrite both files and
    force the exit code, and still cannot produce the HMAC the parent requires. The exit
    code itself travels inside the signed payload, so `os._exit(0)` is not believed either.
    """
    result = _run_imported_runtest_attack(
        tmp_path, _THREE_WAY_FORGE.format(key=key)
    )

    payload = json.loads(result.stdout)
    assert result.returncode == 1
    assert payload["ok"] is False
    assert payload["issues"] == [
        {
            "code": "evidence_execution",
            "id": "DOCUMENT",
            "detail": "execution report is not signed by this run",
        }
    ]


@pytest.mark.parametrize(
    "forge",
    (
        pytest.param(
            "        receipt = _Path(_sys.argv[_sys.argv.index('--junitxml') + 1])\n"
            "        cases = ''.join(\n"
            "            '<testcase file=\"%s\" name=\"%s\"/>' % tuple(node.split('::', 1))\n"
            "            for node in _json.loads(_Path(_sys.argv[2]).read_text())['nodes']\n"
            "        )\n"
            "        receipt.write_text(\n"
            "            '<testsuites><testsuite tests=\"13\" failures=\"0\" errors=\"0\" "
            "skipped=\"0\">' + cases + '</testsuite></testsuites>'\n"
            "        )\n",
            id="receipt-forged-and-zero-exit-forced",
        ),
        pytest.param("        pass\n", id="zero-exit-forced-alone"),
    ),
)
def test_cli_does_not_believe_a_forced_zero_exit(tmp_path: Path, forge: str) -> None:
    """`os._exit(0)` is not a passing run.

    Product code forces a zero exit from an `atexit` hook, skipping `SystemExit(code)`. The
    parent's verdict does not rest on the process's exit status: the child's pytest exit
    code travels inside the signed payload, and the signed ledger records which audited
    bodies actually returned. Forging the JUnit receipt alongside it does not help, because
    the ledger is the thing that says what ran and it cannot be signed by the forge.
    """
    result = _run_imported_runtest_attack(
        tmp_path,
        "import atexit as _atexit, json as _json, os as _os, sys as _sys\n"
        "from pathlib import Path as _Path\n"
        "def _bail():\n"
        "    try:\n"
        + forge
        + "    finally:\n"
        "        _sys.stdout.flush()\n"
        "        _sys.stderr.flush()\n"
        "        _os._exit(0)\n"
        "_atexit.register(_bail)\n",
    )

    payload = json.loads(result.stdout)
    assert result.returncode == 1
    assert payload["ok"] is False
    (issue,) = payload["issues"]
    assert issue["code"] == "evidence_execution"
    assert issue["detail"].startswith(
        ("pytest failed 13", "executed source mismatch: missing=[")
    )


def test_cli_refuses_an_undeclared_module_on_the_evidence_path(tmp_path: Path) -> None:
    """New non-product code on the evidence path has to be declared before it counts.

    The static gate can only check files it knows about, so it cannot notice a *new* helper
    module. The child therefore audits what actually loaded: any repository-local module
    that is not the product under test and not covered by a declared digest is named and the
    run is refused, rather than silently trusted.
    """
    document = _executable_fixture(tmp_path)
    (tmp_path / "undeclared_helper.py").write_text("VALUE = 1\n", encoding="utf-8")
    evidence = tmp_path / "tests/test_registry.py"
    source = evidence.read_text(encoding="utf-8")
    marker = "from __future__ import annotations\n"
    evidence.write_text(
        source.replace(marker, marker + "\nimport undeclared_helper as _undeclared\n", 1),
        encoding="utf-8",
    )
    checker = _checker_with_refreshed_digests(tmp_path, tmp_path / "refreshed_checker.py")

    result = _run_checker(tmp_path, document, checker=str(checker))

    payload = json.loads(result.stdout)
    assert result.returncode == 1
    assert payload["ok"] is False
    (issue,) = payload["issues"]
    assert issue["code"] == "evidence_execution"
    assert issue["detail"] == (
        "unaudited repository modules on the evidence path: "
        "['undeclared_helper.py']"
    )


# A product module that behaves one way on disk and another way while being audited. The
# mutation is the suite's own NORMALIZATION_MUTANT; the second half detects the evidence
# child and puts the pre-mutation implementation back in front of the audited bodies. Only
# one tracked file is touched, no environment is controlled, and no digest is refreshed.
_DEFEAT_BY_REEXEC_BODY = """

import sys as _sys

if "--junitxml" in _sys.argv:
    _ns = dict(globals())
    exec(compile({pristine!r}, __file__, "exec"), _ns)
    normalize_proposal = _ns["normalize_proposal"]
"""
_DEFEAT_BY_METAPATH_BODY = """

import sys as _sys

if "--junitxml" in _sys.argv:
    import importlib.abc as _abc
    import importlib.machinery as _mach

    class _Loader(_abc.Loader):
        def create_module(self, spec):
            return None

        def exec_module(self, module):
            exec(compile({pristine!r}, {origin!r}, "exec"), module.__dict__)

    class _Finder:
        def find_spec(self, name, path=None, target=None):
            if name == "ontologylab.normalization":
                return _mach.ModuleSpec(name, _Loader(), origin={origin!r})
            return None

    _sys.meta_path.insert(0, _Finder())
"""


@pytest.mark.parametrize(
    ("carrier", "template"),
    (
        pytest.param(
            "ontologylab/normalization.py", _DEFEAT_BY_REEXEC_BODY, id="reexec-own-source"
        ),
        pytest.param(
            "ontologylab/models.py", _DEFEAT_BY_METAPATH_BODY, id="meta-path-substitution"
        ),
    ),
)
def test_cli_rejects_product_that_behaves_differently_while_audited(
    tmp_path: Path, carrier: str, template: str
) -> None:
    """The product may be broken; it may not be two different things at once.

    `ontologylab/**` is exempt from content pinning because pinning the thing under test
    would make the gate assert its own input. That exemption used to hand the product the
    power to decide what the audited bodies actually called: the evidence module's
    `from ontologylab.x import y` reads a live attribute, so a module that noticed the audit
    could serve its pre-mutation self. The child now reports, inside the signed payload,
    that every function a product module exposes as its own has a code object that
    compiling that module's current source can produce. That is identity, not correctness.
    """
    document = _executable_fixture(tmp_path)
    normalization = tmp_path / "ontologylab/normalization.py"
    pristine = normalization.read_text(encoding="utf-8")
    _mutate_normalization(tmp_path)
    addition = template.format(pristine=pristine, origin=str(normalization))
    hook = tmp_path / carrier
    hook.write_text(hook.read_text(encoding="utf-8") + addition, encoding="utf-8")

    result = _run_checker(tmp_path, document)

    payload = json.loads(result.stdout)
    assert result.returncode == 1
    assert payload["ok"] is False
    (issue,) = payload["issues"]
    assert issue["code"] == "evidence_execution"
    assert issue["detail"] == (
        "product code the bodies called is not what its own source compiles to: "
        "['ontologylab/normalization.py::normalize_proposal is not compiled from this "
        "file under that name']"
    )


CLASS_MUTANT = (
    "ontologylab/registry.py",
    '    def resolve_with_status(self, name: str) -> tuple[str | None, str]:\n'
    '        """Distinguish a lookup miss from the optional cache being switched off."""\n',
    "        return None, 'unresolved'\n",
)
CLASS_MUTANT_NODES = 2


def _mutate_registry_method(root: Path) -> str:
    """Gut a method on a class the canonical nodes exercise, returning the pristine source."""
    relative, anchor, insertion = CLASS_MUTANT
    path = root / relative
    pristine = path.read_text(encoding="utf-8")
    assert anchor in pristine, f"corruption anchor vanished from {relative}"
    path.write_text(pristine.replace(anchor, anchor + insertion, 1), encoding="utf-8")
    return pristine


def test_cli_rejects_a_timestamp_valid_stale_pyc(tmp_path: Path) -> None:
    """A cached `.pyc` that still looks fresh but executes older constants is caught.

    Bytecode alone is not meaning. Replacing a string constant with another of the same
    length leaves `co_code` byte-identical, so a stale `.pyc` whose source mtime was restored
    -- an ordinary rebase or checkout artefact -- ran the previous constant while the file on
    disk said something else, and the gate passed. The fingerprint now folds in constants and
    nested code objects, and leaves out line numbers and filenames so that relocating code is
    not mistaken for substituting it.
    """
    document = _executable_fixture(tmp_path)
    source = tmp_path / "ontologylab/normalization.py"
    original = source.stat()
    py_compile.compile(str(source), doraise=True)
    text = source.read_text(encoding="utf-8")
    assert '"no_eppo_match"' in text
    source.write_text(text.replace('"no_eppo_match"', '"xx_eppo_match"'), encoding="utf-8")
    os.utime(source, (original.st_atime, original.st_mtime))

    result = _run_checker(tmp_path, document)

    payload = json.loads(result.stdout)
    assert result.returncode == 1
    assert payload["ok"] is False
    (issue,) = payload["issues"]
    assert issue["detail"] == (
        "product code the bodies called is not what its own source compiles to: "
        "['ontologylab/normalization.py::_normalize_organism is not compiled from this "
        "file under that name']"
    )


def test_semantic_constant_encoding_is_typed_canonical_and_exact() -> None:
    """The fingerprint input is injective over the constant domain it accepts."""
    encode = _shipped_helpers("_frame", "_constant_bytes")["_constant_bytes"]
    # Constant-folding the expression ``inf - inf`` chooses a NaN sign that
    # differs between arm64 and x86_64. Build the two exact IEEE values this
    # encoding contract means to distinguish instead of testing the compiler.
    positive_nan = struct.unpack(">d", bytes.fromhex("7ff8000000000000"))[0]
    negative_nan = struct.unpack(">d", bytes.fromhex("fff8000000000000"))[0]
    scalars = (
        None,
        Ellipsis,
        False,
        True,
        0,
        1,
        -1,
        0.0,
        -0.0,
        positive_nan,
        negative_nan,
        0j,
        complex(-0.0, 0.0),
        "",
        b"",
    )

    encoded = [encode(value) for value in scalars]

    assert len(set(encoded)) == len(scalars)
    assert struct.pack(">d", positive_nan) == bytes.fromhex("7ff8000000000000")
    assert struct.pack(">d", negative_nan) == bytes.fromhex("fff8000000000000")
    assert encode({"second": 2, "first": 1}) == encode({"first": 1, "second": 2})
    assert encode(frozenset({"second", "first"})) == encode(
        frozenset({"first", "second"})
    )


def test_semantic_constant_encoding_rejects_unsupported_and_cyclic_values() -> None:
    """Values outside the deliberate domain fail instead of sharing a fallback encoding."""
    encode = _shipped_helpers("_frame", "_constant_bytes")["_constant_bytes"]
    cyclic: list[object] = []
    cyclic.append(cyclic)

    with pytest.raises(TypeError, match="unsupported code constant"):
        encode(object())
    with pytest.raises(ValueError, match="cyclic code constant"):
        encode(cyclic)


def test_semantic_fingerprint_includes_execution_metadata_but_not_locations() -> None:
    """All CPython 3.13 CodeType constructor fields are classified explicitly."""
    fingerprint = _shipped_helpers(
        "_frame", "_constant_bytes", "_code_bytes", "code_fingerprint"
    )["code_fingerprint"]
    code = compile(
        "def guarded(value):\n"
        "    try:\n        return 10 // value\n"
        "    except ZeroDivisionError:\n        return 99\n",
        "first.py",
        "exec",
    ).co_consts[0]
    without_handlers = code.replace(co_exceptiontable=b"")

    assert code.co_exceptiontable
    assert fingerprint(code) != fingerprint(without_handlers)
    assert types.FunctionType(code, {})(0) == 99
    with pytest.raises(ZeroDivisionError):
        types.FunctionType(without_handlers, {})(0)
    assert fingerprint(code) != fingerprint(
        code.replace(co_stacksize=code.co_stacksize + 1)
    )
    assert fingerprint(code) == fingerprint(
        code.replace(
            co_filename="relocated.py",
            co_firstlineno=code.co_firstlineno + 100,
            co_linetable=b"",
        )
    )


def test_semantic_fingerprint_preserves_nested_exception_tables() -> None:
    """Nested CodeType values recurse through the complete semantic inventory."""
    fingerprint = _shipped_helpers(
        "_frame", "_constant_bytes", "_code_bytes", "code_fingerprint"
    )["code_fingerprint"]
    outer = compile(
        "def outer():\n"
        "    def inner(value):\n"
        "        try:\n            return 10 // value\n"
        "        except ZeroDivisionError:\n            return 99\n"
        "    return inner\n",
        "probe.py",
        "exec",
    ).co_consts[0]
    inner_index = next(
        index for index, value in enumerate(outer.co_consts) if isinstance(value, CodeType)
    )
    inner = outer.co_consts[inner_index]
    constants = list(outer.co_consts)
    constants[inner_index] = inner.replace(co_exceptiontable=b"")
    changed = outer.replace(co_consts=tuple(constants))

    assert fingerprint(outer) != fingerprint(changed)


def test_cli_rejects_a_replaced_exception_table(tmp_path: Path) -> None:
    """Live exception dispatch must match what compiling the product source produces."""
    document = _executable_fixture(tmp_path)
    source = tmp_path / "ontologylab/registry.py"
    source.write_text(
        source.read_text(encoding="utf-8")
        + "\n\ndef a11_guarded(value):\n"
        "    try:\n"
        "        return 10 // value\n"
        "    except ZeroDivisionError:\n"
        "        return 99\n\n"
        "a11_guarded.__code__ = a11_guarded.__code__.replace(co_exceptiontable=b'')\n",
        encoding="utf-8",
    )

    result = _run_checker(tmp_path, document)

    payload = json.loads(result.stdout)
    assert result.returncode == 1
    assert payload["ok"] is False
    details = " ".join(issue["detail"] for issue in payload["issues"])
    assert (
        "ontologylab/registry.py::a11_guarded is not compiled from this file under that name"
        in details
    ), details


def test_semantic_fingerprint_preserves_nested_code_meaning() -> None:
    """A nested function's constants remain part of its enclosing code's identity."""
    fingerprint = _shipped_helpers(
        "_frame", "_constant_bytes", "_code_bytes", "code_fingerprint"
    )["code_fingerprint"]
    first = compile(
        "def outer():\n    def inner():\n        return 'first'\n    return inner\n",
        "probe.py",
        "exec",
    ).co_consts[0]
    second = compile(
        "def outer():\n    def inner():\n        return 'other'\n    return inner\n",
        "probe.py",
        "exec",
    ).co_consts[0]

    assert first.co_code == second.co_code
    assert fingerprint(first) != fingerprint(second)


def test_cli_rejects_opposite_sign_nan_in_a_timestamp_valid_stale_pyc(
    tmp_path: Path,
) -> None:
    """NaN sign bits are observable meaning even though both values repr as ``nan``."""
    document = _executable_fixture(tmp_path)
    source = tmp_path / "ontologylab/normalization.py"
    positive = "\n\ndef a10_nan_probe():\n    return 1e1000 - 1e1000   \n"
    negative = "\n\ndef a10_nan_probe():\n    return -(1e1000 - 1e1000)\n"
    assert len(positive.encode()) == len(negative.encode())
    source.write_text(source.read_text(encoding="utf-8") + positive, encoding="utf-8")
    compiled_stat = source.stat()
    py_compile.compile(str(source), doraise=True)
    source.write_text(
        source.read_text(encoding="utf-8").replace(positive, negative),
        encoding="utf-8",
    )
    os.utime(
        source,
        ns=(compiled_stat.st_atime_ns, compiled_stat.st_mtime_ns),
    )

    result = _run_checker(tmp_path, document)

    payload = json.loads(result.stdout)
    assert result.returncode == 1
    assert payload["ok"] is False
    details = " ".join(issue["detail"] for issue in payload["issues"])
    assert (
        "ontologylab/normalization.py::a10_nan_probe is not compiled from this file "
        "under that name"
    ) in details, details


def test_cli_validates_every_binding_path_of_an_aliased_class(tmp_path: Path) -> None:
    """`class A`, `class B`, then a leftover `B = A` -- both names are checked.

    Cycle prevention used one visited-object set for the whole module, so whichever name
    sorted first was validated and the other binding path was skipped entirely. That is the
    opposite of keying by where a thing is bound. The alias here carries the gutted method,
    and the canonical name is what the tests call.
    """
    document = _executable_fixture(tmp_path)
    registry = tmp_path / "ontologylab/registry.py"
    pristine = registry.read_text(encoding="utf-8")
    _mutate_registry_method(tmp_path)
    registry.write_text(
        registry.read_text(encoding="utf-8")
        + "\n\nimport sys as _sys\n\n"
        'if "--junitxml" in _sys.argv:\n'
        "    _ns = dict(globals())\n"
        "    exec(compile(%r, __file__, \"exec\"), _ns)\n"
        "    AAACache = _ns[\"RegistryCache\"]\n"
        "    RegistryCache = AAACache\n" % pristine,
        encoding="utf-8",
    )

    result = _run_checker(tmp_path, document)

    payload = json.loads(result.stdout)
    assert result.returncode == 1
    assert payload["ok"] is False
    (issue,) = payload["issues"]
    reported = issue["detail"]
    # Both binding paths of the aliased class are audited. The canonical name is the one the
    # canonical nodes call, so naming only the alias would report the wrong thing -- and a
    # visited-object set shared across the module skips whichever path sorts later.
    assert "RegistryCache.resolve_with_status" in reported, reported
    assert "AAACache.resolve_with_status" in reported, reported


def test_every_binding_path_is_walked_even_when_two_names_share_one_class() -> None:
    """Aliasing a class does not remove either name from the audit.

    Owned separately from the CLI test above because the traversal is the guarantee: with a
    module-wide visited set, `B = A` produced binding paths for `A` only. This measures the
    shipped walker directly, so it fails when cycle prevention is widened back to suppress a
    second top-level binding of the same object.
    """
    walker = _shipped_helpers(
        "_descriptor_members", "live_code_objects", "_code_objects_of"
    )["live_code_objects"]
    module = types.ModuleType("aliased_demo")
    exec(
        compile(
            "class A:\n    def go(self):\n        return 1\nB = A\n",
            "aliased_demo.py",
            "exec",
        ),
        module.__dict__,
    )
    for value in list(module.__dict__.values()):
        if isinstance(value, type):
            value.__module__ = "aliased_demo"

    paths = {path for path, _source_binding, _code, _function in walker(module)}

    assert paths == {"A.go", "B.go"}, sorted(paths)


@pytest.mark.parametrize(
    ("target", "dunder", "body"),
    (
        pytest.param(
            "ontologylab/registry.py",
            "__repr__",
            "def __repr__(self): return '<leftover>'",
            id="repr-on-a-plain-class",
        ),
        pytest.param(
            "ontologylab/registry.py",
            "__init__",
            "def __init__(self, data_dir): self.path = None",
            id="init-on-a-plain-class",
        ),
        pytest.param(
            "ontologylab/registry.py",
            "__eq__",
            "def __eq__(self, other): return True",
            id="eq-on-a-plain-class",
        ),
        pytest.param(
            "ontologylab/registry.py",
            "__hash__",
            "def __hash__(self): return 0",
            id="hash-on-a-plain-class",
        ),
        pytest.param(
            "ontologylab/registry.py",
            "__setattr__",
            "def __setattr__(self, name, value): object.__setattr__(self, name, value)",
            id="setattr-on-a-plain-class",
        ),
        pytest.param(
            "ontologylab/registry.py",
            "__delattr__",
            "def __delattr__(self, name): object.__delattr__(self, name)",
            id="delattr-on-a-plain-class",
        ),
    ),
)
def test_cli_rejects_a_dynamically_compiled_dunder_on_a_plain_class(
    tmp_path: Path, target: str, dunder: str, body: str
) -> None:
    """A whitelisted name is not provenance. Every whitelisted name is covered.

    The exemption used to be a name table: any `<string>` code object bound to one of six
    dunder names was skipped, which proved nothing about who generated it. `RegistryCache` is
    an ordinary class, so nothing about it is generated, and each of these is an unconditional
    dynamic-binding leftover of the kind a refactor leaves behind.
    """
    document = _executable_fixture(tmp_path)
    source = tmp_path / target
    source.write_text(
        source.read_text(encoding="utf-8")
        + "\n\n_leftover_ns = {\"__name__\": __name__}\n"
        f"exec(compile({body!r}, \"<string>\", \"exec\"), _leftover_ns)\n"
        f"RegistryCache.{dunder} = _leftover_ns[\"{dunder}\"]\n",
        encoding="utf-8",
    )

    result = _run_checker(tmp_path, document)

    payload = json.loads(result.stdout)
    assert result.returncode == 1
    assert payload["ok"] is False
    details = " ".join(issue["detail"] for issue in payload["issues"])
    assert f"RegistryCache.{dunder} was compiled from <string>" in details, details


@pytest.mark.parametrize(
    ("dunder", "body"),
    (
        pytest.param(
            "__repr__", "def __repr__(self): return '<leftover>'", id="repr-generated"
        ),
        pytest.param(
            "__init__",
            "def __init__(self, index, char_offset, text): self.index = index",
            id="init-generated",
        ),
    ),
)
def test_cli_rejects_a_leftover_on_a_genuine_dataclass(
    tmp_path: Path, dunder: str, body: str
) -> None:
    """Even on a real dataclass, on a name it really does generate, a leftover is caught.

    Declaring the class a dataclass is necessary but not sufficient: a leftover can target a
    genuine dataclass on a genuine generated name, and a declaration-only rule would exempt
    it. Provenance is therefore established by re-derivation -- the class statement alone is
    executed in a copy of the module namespace and the fingerprints compared -- so the
    trailing assignment in the same file cannot launder itself into the regenerated result.
    `__init__` is the dataclass-critical case; `__repr__` is the reported reproduction.
    """
    document = _executable_fixture(tmp_path)
    source = tmp_path / "ontologylab/extractor.py"
    source.write_text(
        source.read_text(encoding="utf-8")
        + "\n\n_leftover_ns = {\"__name__\": __name__}\n"
        f"exec(compile({body!r}, \"<string>\", \"exec\"), _leftover_ns)\n"
        f"Chunk.{dunder} = _leftover_ns[\"{dunder}\"]\n",
        encoding="utf-8",
    )

    result = _run_checker(tmp_path, document)

    payload = json.loads(result.stdout)
    assert result.returncode == 1
    assert payload["ok"] is False
    details = " ".join(issue["detail"] for issue in payload["issues"])
    assert f"Chunk.{dunder}" in details, details


def test_cli_accepts_genuinely_generated_dataclass_methods(tmp_path: Path) -> None:
    """The false-alarm control: real generated methods still pass, untouched.

    A legitimate frozen dataclass exercising `__init__`, `__repr__`, `__eq__`, `__hash__`,
    `__setattr__` and `__delattr__` -- every name on the old table -- alongside a property, a
    cached_property, a staticmethod and a classmethod, all added to product code the canonical
    nodes import. None of it may be reported.
    """
    document = _executable_fixture(tmp_path)
    source = tmp_path / "ontologylab/registry.py"
    source.write_text(
        source.read_text(encoding="utf-8")
        + "\n\nimport functools as _functools\n"
        "from dataclasses import dataclass as _dataclass\n\n\n"
        "@_dataclass(frozen=True)\n"
        "class LegitimateGenerated:\n"
        "    label: str\n"
        "    size: int = 3\n\n"
        "    @property\n"
        "    def doubled(self):\n"
        "        return self.size * 2\n\n"
        "    @_functools.cached_property\n"
        "    def tripled(self):\n"
        "        return self.size * 3\n\n"
        "    @staticmethod\n"
        "    def helper():\n"
        "        return 1\n\n"
        "    @classmethod\n"
        "    def build(cls):\n"
        "        return cls(label='x')\n",
        encoding="utf-8",
    )

    result = _run_checker(tmp_path, document)

    payload = json.loads(result.stdout)
    assert result.returncode == 0, payload["issues"]
    assert payload["ok"] is True
    assert payload["issues"] == []
    assert "EVIDENCE: 13 canonical pytest nodes passed" in result.stderr



def test_cli_rejects_moduleless_callbacks_in_all_owned_descriptor_containers(
    tmp_path: Path,
) -> None:
    """Descriptor ownership, not mutable ``__module__``, makes direct callbacks auditable."""
    document = _executable_fixture(tmp_path)
    source = tmp_path / "ontologylab/registry.py"
    source.write_text(
        source.read_text(encoding="utf-8")
        + """

class A12OwnedDescriptor:
    __slots__ = ("callback", "state", "members")
    def __init__(self, callback):
        self.callback = callback
        self.state = {"callbacks": [callback]}
        self.members = {callback}
    def __get__(self, instance, owner):
        return self.callback.__get__(instance, owner)

class A12DirectOwner:
    @A12OwnedDescriptor
    def marker(self): return "direct-source"
class A12SlotOwner:
    @A12OwnedDescriptor
    def marker(self): return "slot-source"
class A12NestedOwner:
    @A12OwnedDescriptor
    def marker(self): return "nested-source"
class A12SetOwner:
    @A12OwnedDescriptor
    def marker(self): return "set-source"
class A12FrozenOwner:
    @A12OwnedDescriptor
    def marker(self): return "frozen-source"

def _a12_callback():
    namespace = {}
    exec(compile("def marker(self, label='source'): return 'leftover'", "<string>", "exec"), namespace)
    callback = namespace["marker"]
    callback.__defaults__ = ("leftover-default",)
    assert callback.__module__ is None
    return callback

vars(A12DirectOwner)["marker"].callback = _a12_callback()
vars(A12SlotOwner)["marker"].callback = _a12_callback()
vars(A12NestedOwner)["marker"].state["callbacks"][0] = _a12_callback()
vars(A12SetOwner)["marker"].members = {_a12_callback()}
vars(A12FrozenOwner)["marker"].members = frozenset({_a12_callback()})
""",
        encoding="utf-8",
    )

    result = _run_checker(tmp_path, document)

    payload = json.loads(result.stdout)
    details = " ".join(issue["detail"] for issue in payload["issues"])
    owners = (
        "A12DirectOwner.marker.callback",
        "A12SlotOwner.marker.callback",
        "A12NestedOwner.marker.state[key:",
        "A12SetOwner.marker.members{member:",
        "A12FrozenOwner.marker.members{member:",
    )
    missing = [owner for owner in owners if owner not in details]
    assert missing == [], (missing, details)
    assert result.returncode == 1
    assert payload["ok"] is False


def test_cli_rejects_moduleless_owned_source_callback_default_drift(
    tmp_path: Path,
) -> None:
    """M1 ownership also subjects a source-origin callback's FunctionType state to I1."""
    document = _executable_fixture(tmp_path)
    source = tmp_path / "ontologylab/registry.py"
    source.write_text(
        source.read_text(encoding="utf-8")
        + """

class A12ModulelessDefaultDescriptor:
    def __init__(self, callback): self.callback = callback
    def __get__(self, instance, owner): return self.callback.__get__(instance, owner)
class A12ModulelessDefaultOwner:
    @A12ModulelessDefaultDescriptor
    def marker(self, label="source"): return label
vars(A12ModulelessDefaultOwner)["marker"].callback.__module__ = None
vars(A12ModulelessDefaultOwner)["marker"].callback.__defaults__ = ("leftover",)
""",
        encoding="utf-8",
    )

    result = _run_checker(tmp_path, document)

    payload = json.loads(result.stdout)
    details = " ".join(issue["detail"] for issue in payload["issues"])
    assert (
        "A12ModulelessDefaultOwner.marker.callback has positional default slot 0 "
        "that differs from its source declaration"
    ) in details
    assert result.returncode == 1


def test_cli_accepts_source_and_library_callbacks_in_descriptor_state(
    tmp_path: Path,
) -> None:
    """Owned source callbacks stay green and genuine stdlib origins retain their boundary."""
    document = _executable_fixture(tmp_path)
    source = tmp_path / "ontologylab/registry.py"
    source.write_text(
        source.read_text(encoding="utf-8")
        + """

import functools as _a12_functools
class A12CleanDescriptor:
    def __init__(self, callback): self.callback = callback
    def __get__(self, instance, owner): return self.callback.__get__(instance, owner)
class A12CleanOwner:
    @A12CleanDescriptor
    def marker(self, label="source", *, option={"nested": [1]}): return label
class A12LibraryOwner:
    marker = A12CleanDescriptor(_a12_functools.update_wrapper)
""",
        encoding="utf-8",
    )

    result = _run_checker(tmp_path, document)

    payload = json.loads(result.stdout)
    assert result.returncode == 0, payload["issues"]
    assert payload["ok"] is True


def test_descriptor_owned_synthetic_callback_cannot_hide_behind_module_metadata(
    tmp_path: Path,
) -> None:
    """Changing only a callback's claimed module cannot suppress origin validation."""
    document = _executable_fixture(tmp_path)
    source = tmp_path / "ontologylab/registry.py"
    source.write_text(
        source.read_text(encoding="utf-8")
        + """

class A12MetadataDescriptor:
    def __init__(self, callback): self.callback = callback
    def __get__(self, instance, owner): return self.callback.__get__(instance, owner)
class A12MetadataOwner:
    @A12MetadataDescriptor
    def marker(self): return "source"
_a12_ns = {"__name__": __name__}
exec(compile("def marker(self): return 'leftover'", "<string>", "exec"), _a12_ns)
_a12_ns["marker"].__module__ = "unrelated.claim"
vars(A12MetadataOwner)["marker"].callback = _a12_ns["marker"]
""",
        encoding="utf-8",
    )

    result = _run_checker(tmp_path, document)

    payload = json.loads(result.stdout)
    assert result.returncode == 1
    details = " ".join(issue["detail"] for issue in payload["issues"])
    assert "A12MetadataOwner.marker.callback was compiled from <string>" in details


def test_cli_accepts_an_annotated_source_declared_descriptor_alias(
    tmp_path: Path,
) -> None:
    """A value-bearing annotated class alias has the same source meaning as Assign."""
    document = _executable_fixture(tmp_path)
    source = tmp_path / "ontologylab/registry.py"
    source.write_text(
        source.read_text(encoding="utf-8")
        + """

class A12AnnotatedDescriptor:
    def __init__(self, callback): self.callback = callback
    def __get__(self, instance, owner): return self.callback.__get__(instance, owner)
class A12AnnotatedOwner:
    @A12AnnotatedDescriptor
    def marker(self): return "source"
    alias: object = marker
""",
        encoding="utf-8",
    )

    result = _run_checker(tmp_path, document)

    payload = json.loads(result.stdout)
    assert result.returncode == 0, payload["issues"]
    assert payload["ok"] is True


def test_cli_rejects_a_rebound_annotated_descriptor_alias(tmp_path: Path) -> None:
    """Annotated alias resolution preserves the explicit rebound ownership path."""
    document = _executable_fixture(tmp_path)
    source = tmp_path / "ontologylab/registry.py"
    source.write_text(
        source.read_text(encoding="utf-8")
        + """

class A12BadAnnotatedDescriptor:
    def __init__(self, callback): self.callback = callback
    def __get__(self, instance, owner): return self.callback.__get__(instance, owner)
class A12BadAnnotatedOwner:
    @A12BadAnnotatedDescriptor
    def marker(self): return "source"
    alias: object = marker
_a12_ns = {"__name__": __name__}
exec(compile("def marker(self): return 'leftover'", "<string>", "exec"), _a12_ns)
vars(A12BadAnnotatedOwner)["alias"].callback = _a12_ns["marker"]
""",
        encoding="utf-8",
    )

    result = _run_checker(tmp_path, document)

    payload = json.loads(result.stdout)
    assert result.returncode == 1
    details = " ".join(issue["detail"] for issue in payload["issues"])
    assert "A12BadAnnotatedOwner.alias.callback was compiled from <string>" in details


@pytest.mark.parametrize(
    ("key_expression", "hash_seed"),
    (("('callback', 1)", "1"), ("('callback', 1)", "271"),
     ("frozenset({'callback', 1})", "1"), ("frozenset({'callback', 1})", "271")),
)
def test_cli_accepts_exact_container_keys_across_hash_seeds(
    tmp_path: Path, key_expression: str, hash_seed: str
) -> None:
    """Supported exact hashable container keys are canonical and clean."""
    document = _executable_fixture(tmp_path)
    source = tmp_path / "ontologylab/registry.py"
    source.write_text(
        source.read_text(encoding="utf-8")
        + f"""

class A12KeyDescriptor:
    def __init__(self, callback): self.state = {{{key_expression}: callback}}
    def __get__(self, instance, owner): return next(iter(self.state.values())).__get__(instance, owner)
class A12KeyOwner:
    @A12KeyDescriptor
    def marker(self): return "source"
""",
        encoding="utf-8",
    )

    result = _run_checker(
        tmp_path, document, environment={**os.environ, "PYTHONHASHSEED": hash_seed}
    )

    payload = json.loads(result.stdout)
    assert result.returncode == 0, payload["issues"]
    assert payload["ok"] is True


def test_cli_rejects_rebound_callbacks_under_exact_container_keys(
    tmp_path: Path,
) -> None:
    """Tuple and frozenset keys retain distinct deterministic callback owner paths."""
    document = _executable_fixture(tmp_path)
    source = tmp_path / "ontologylab/registry.py"
    source.write_text(
        source.read_text(encoding="utf-8")
        + """

class A12BadKeyDescriptor:
    def __init__(self, callback, key): self.state = {key: callback}
    def __get__(self, instance, owner): return next(iter(self.state.values())).__get__(instance, owner)
class A12TupleKeyOwner:
    marker = A12BadKeyDescriptor(lambda self: "source", ("callback", 1))
class A12FrozenKeyOwner:
    marker = A12BadKeyDescriptor(lambda self: "source", frozenset({"callback", 1}))
_a12_ns = {"__name__": __name__}
exec(compile("def marker(self): return 'leftover'", "<string>", "exec"), _a12_ns)
vars(A12TupleKeyOwner)["marker"].state[("callback", 1)] = _a12_ns["marker"]
vars(A12FrozenKeyOwner)["marker"].state[frozenset({"callback", 1})] = _a12_ns["marker"]
""",
        encoding="utf-8",
    )

    details_by_seed = []
    for hash_seed in ("1", "271"):
        result = _run_checker(
            tmp_path, document,
            environment={**os.environ, "PYTHONHASHSEED": hash_seed},
        )
        payload = json.loads(result.stdout)
        assert result.returncode == 1
        details = " ".join(issue["detail"] for issue in payload["issues"])
        for owner in (
            "A12TupleKeyOwner.marker.state[key:",
            "A12FrozenKeyOwner.marker.state[key:",
        ):
            assert owner in details, (owner, details)
        details_by_seed.append(details)
    assert details_by_seed[0] == details_by_seed[1]


def test_descriptor_dict_keys_fail_closed_without_opening_objects() -> None:
    """Unsupported hashable keys fail explicitly; their object graph is never traversed."""
    walker = _shipped_helpers(
        "_frame", "_constant_bytes", "_code_bytes", "_descriptor_value_bytes",
        "_descriptor_members", "live_code_objects", "_code_objects_of"
    )["live_code_objects"]
    module = types.ModuleType("unsupported_key_demo")
    exec(
        compile(
            "class Key:\n"
            "    def __hash__(self): return 1\n"
            "class Descriptor:\n"
            "    def __init__(self, callback): self.state = {Key(): callback}\n"
            "    def __get__(self, instance, owner): raise AssertionError\n"
            "class Owner:\n"
            "    @Descriptor\n"
            "    def marker(self): return 'source'\n",
            "unsupported_key_demo.py", "exec",
        ), module.__dict__,
    )

    with pytest.raises(TypeError, match="unsupported descriptor-state key"):
        list(walker(module))


def test_cli_accepts_a_composed_descriptor_without_transferring_ownership(
    tmp_path: Path,
) -> None:
    """An outer descriptor reference does not open an independently bound descriptor."""
    document = _executable_fixture(tmp_path)
    source = tmp_path / "ontologylab/registry.py"
    source.write_text(
        source.read_text(encoding="utf-8")
        + """

class A12ComposedDescriptor:
    def __init__(self, callback, inner=None): self.callback, self.inner = callback, inner
    def __get__(self, instance, owner): return self.callback.__get__(instance, owner)
class A12ComposedOwner:
    @A12ComposedDescriptor
    def inner(self): return "inner-source"
    @A12ComposedDescriptor
    def outer(self): return "outer-source"
    outer.inner = inner
""",
        encoding="utf-8",
    )

    result = _run_checker(tmp_path, document)

    payload = json.loads(result.stdout)
    assert result.returncode == 0, payload["issues"]
    assert payload["ok"] is True


def test_cli_audits_the_independent_root_of_a_composed_descriptor(
    tmp_path: Path,
) -> None:
    """Closing descendant objects does not hide the inner descriptor's class binding."""
    document = _executable_fixture(tmp_path)
    source = tmp_path / "ontologylab/registry.py"
    source.write_text(
        source.read_text(encoding="utf-8")
        + """

class A12BadComposedDescriptor:
    def __init__(self, callback, inner=None): self.callback, self.inner = callback, inner
    def __get__(self, instance, owner): return self.callback.__get__(instance, owner)
class A12BadComposedOwner:
    @A12BadComposedDescriptor
    def inner(self): return "inner-source"
    @A12BadComposedDescriptor
    def outer(self): return "outer-source"
    outer.inner = inner
_a12_ns = {"__name__": __name__}
exec(compile("def inner(self): return 'leftover'", "<string>", "exec"), _a12_ns)
vars(A12BadComposedOwner)["inner"].callback = _a12_ns["inner"]
""",
        encoding="utf-8",
    )

    result = _run_checker(tmp_path, document)

    payload = json.loads(result.stdout)
    assert result.returncode == 1
    details = " ".join(issue["detail"] for issue in payload["issues"])
    assert "A12BadComposedOwner.inner.callback was compiled from <string>" in details
    assert "A12BadComposedOwner.outer.inner.callback" not in details


def test_cli_rejects_mutated_positional_keyword_and_nested_defaults(
    tmp_path: Path,
) -> None:
    """Function invocation defaults are source-bound independently of CodeType."""
    document = _executable_fixture(tmp_path)
    source = tmp_path / "ontologylab/registry.py"
    source.write_text(
        source.read_text(encoding="utf-8")
        + """

def a12_positional(label="source"): return label
def a12_keyword(*, label="source"): return label
def a12_nested(config={"items": ["source"]}): return config

a12_positional.__defaults__ = ("leftover",)
a12_keyword.__kwdefaults__["label"] = "leftover"
a12_nested.__defaults__[0]["items"][0] = "leftover"
assert a12_positional() == "leftover"
assert a12_keyword() == "leftover"
assert a12_nested()["items"] == ["leftover"]
""",
        encoding="utf-8",
    )

    result = _run_checker(tmp_path, document)

    payload = json.loads(result.stdout)
    details = " ".join(issue["detail"] for issue in payload["issues"])
    expected = {
        "a12_positional": "positional default slot 0",
        "a12_keyword": "keyword-only default 'label'",
        "a12_nested": "positional default slot 0",
    }
    missing = [
        owner for owner, slot in expected.items()
        if f"{owner} has {slot} that differs from its source declaration" not in details
    ]
    assert missing == [], (missing, details)
    assert result.returncode == 1


def test_cli_rejects_literal_slots_inside_mixed_source_defaults(
    tmp_path: Path,
) -> None:
    """Nonliteral neighbors cannot erase positional or keyword-only literal slots."""
    document = _executable_fixture(tmp_path)
    source = tmp_path / "ontologylab/registry.py"
    source.write_text(
        source.read_text(encoding="utf-8")
        + """

_A13_OPAQUE = object()
def a13_literal_first(literal="source", opaque=_A13_OPAQUE): return literal

def a13_literal_last(opaque=_A13_OPAQUE, literal="source"): return literal

def a13_posonly(first="source", opaque=_A13_OPAQUE, /, regular={"items": ["source"]}, *, named="source", required):
    return first, opaque, regular, named, required

a13_literal_first.__defaults__ = ("leftover", _A13_OPAQUE)
a13_literal_last.__defaults__ = (_A13_OPAQUE, "leftover")
a13_posonly.__defaults__ = ("leftover", _A13_OPAQUE, {"items": ["leftover"]})
a13_posonly.__kwdefaults__["named"] = "leftover"
assert a13_literal_first() == "leftover"
assert a13_literal_last() == "leftover"
assert a13_posonly(required=True)[0:4:2] == ("leftover", {"items": ["leftover"]})
""",
        encoding="utf-8",
    )

    result = _run_checker(tmp_path, document)

    payload = json.loads(result.stdout)
    details = " ".join(issue["detail"] for issue in payload["issues"])
    expected = (
        "a13_literal_first has positional default slot 0",
        "a13_literal_last has positional default slot 1",
        "a13_posonly has positional default slot 0",
        "a13_posonly has positional default slot 2",
        "a13_posonly has keyword-only default 'named'",
    )
    assert [owner for owner in expected if owner not in details] == []
    assert result.returncode == 1


def test_cli_accepts_clean_mixed_defaults(tmp_path: Path) -> None:
    document = _executable_fixture(tmp_path)
    source = tmp_path / "ontologylab/registry.py"
    source.write_text(
        source.read_text(encoding="utf-8")
        + """

_A13_CLEAN_OPAQUE = object()
def a13_clean_mixed(first="source", opaque=_A13_CLEAN_OPAQUE, /, last={"items": ["source"]}, *, named="source"):
    return first, opaque, last, named
""",
        encoding="utf-8",
    )

    result = _run_checker(tmp_path, document)

    payload = json.loads(result.stdout)
    assert result.returncode == 0, payload["issues"]
    assert payload["issues"] == []


def test_cli_binds_mixed_default_shape_even_when_values_are_nonliteral(
    tmp_path: Path,
) -> None:
    """None/tuple and keyword-key shape are source facts even for opaque slots."""
    document = _executable_fixture(tmp_path)
    source = tmp_path / "ontologylab/registry.py"
    source.write_text(
        source.read_text(encoding="utf-8")
        + """

_A13_SHAPE = object()
def a13_shape(value=_A13_SHAPE, *, named=_A13_SHAPE): return value, named
a13_shape.__defaults__ = None
a13_shape.__kwdefaults__ = {"other": _A13_SHAPE}
""",
        encoding="utf-8",
    )

    result = _run_checker(tmp_path, document)

    details = " ".join(issue["detail"] for issue in json.loads(result.stdout)["issues"])
    assert "a13_shape has positional defaults presence" in details
    assert "a13_shape has keyword-only default keys" in details
    assert result.returncode == 1


def test_shipped_mixed_default_inventory_binds_every_supported_slot() -> None:
    """Derive the inventory from shipped ASTs; no count is pinned across revisions."""
    helpers = _shipped_helpers(
        "_frame", "_constant_bytes", "_code_bytes", "_source_default",
        "source_function_defaults",
    )
    derive = helpers["source_function_defaults"]
    sentinel = helpers["source_function_defaults"].__globals__["UNBOUND_DEFAULT"]
    repository = Path(__file__).resolve().parents[1]
    expected_supported = observed_supported = mixed_functions = 0
    for path in sorted((repository / "ontologylab").rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for function in ast.walk(tree):
            if not isinstance(function, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            defaults = (
                *function.args.defaults,
                *(item for item in function.args.kw_defaults if item is not None),
            )
            for default in defaults:
                try:
                    ast.literal_eval(default)
                except (ValueError, TypeError, SyntaxError, MemoryError, RecursionError):
                    continue
                expected_supported += 1
        states = derive(tree)
        for positional, keyword in states.values():
            slots = [*(positional or ()), *(keyword or {}).values()]
            observed_supported += sum(value is not sentinel for value in slots)
            if any(value is sentinel for value in slots) and any(value is not sentinel for value in slots):
                mixed_functions += 1
    assert observed_supported == expected_supported
    assert mixed_functions > 0


def test_cli_fails_closed_on_unsupported_and_cyclic_live_defaults(
    tmp_path: Path,
) -> None:
    """A supported source declaration cannot drift into an unencodable live value."""
    document = _executable_fixture(tmp_path)
    source = tmp_path / "ontologylab/registry.py"
    source.write_text(
        source.read_text(encoding="utf-8")
        + """

def a12_unsupported_default(value="source"): return value
def a12_cyclic_default(value=[]): return value
_a12_cycle = a12_cyclic_default.__defaults__[0]
_a12_cycle.append(_a12_cycle)
a12_unsupported_default.__defaults__ = (object(),)
""",
        encoding="utf-8",
    )

    result = _run_checker(tmp_path, document)

    payload = json.loads(result.stdout)
    details = " ".join(issue["detail"] for issue in payload["issues"])
    assert "a12_unsupported_default has unsupported positional default slot 0" in details
    assert "a12_cyclic_default has unsupported positional default slot 0" in details
    assert result.returncode == 1


def test_cli_accepts_clean_supported_function_defaults(tmp_path: Path) -> None:
    """Clean positional, keyword-only, and mutable nested literals remain green."""
    document = _executable_fixture(tmp_path)
    source = tmp_path / "ontologylab/registry.py"
    source.write_text(
        source.read_text(encoding="utf-8")
        + """

def a12_clean_positional(label="source"): return label
def a12_clean_keyword(*, label="source"): return label
def a12_clean_nested(config={"items": ["source"]}): return config
""",
        encoding="utf-8",
    )

    result = _run_checker(tmp_path, document)

    payload = json.loads(result.stdout)
    assert result.returncode == 0, payload["issues"]
    assert payload["ok"] is True


def test_cli_rejects_function_to_methodtype_descriptor_rebinding(
    tmp_path: Path,
) -> None:
    """MethodType kind and __self__ are invocation state, not an alias for __func__."""
    document = _executable_fixture(tmp_path)
    source = tmp_path / "ontologylab/registry.py"
    source.write_text(
        source.read_text(encoding="utf-8")
        + """

import types as _a13_types
class A13MethodDescriptor:
    def __init__(self, callback): self.callback = callback
    def __get__(self, instance, owner): return self.callback.__get__(instance, owner)
class A13MethodOwner:
    label = "source"
    @A13MethodDescriptor
    def marker(self): return self.label
class A13MethodReceiver:
    label = "leftover"
vars(A13MethodOwner)["marker"].callback = _a13_types.MethodType(
    vars(A13MethodOwner)["marker"].callback, A13MethodReceiver()
)
assert vars(A13MethodOwner)["marker"].callback() == "leftover"
""",
        encoding="utf-8",
    )

    result = _run_checker(tmp_path, document)

    details = " ".join(issue["detail"] for issue in json.loads(result.stdout)["issues"])
    assert (
        "A13MethodOwner.marker.callback is a bound method where source declares an unbound function"
        in details
    )
    assert result.returncode == 1


def test_cli_accepts_clean_callable_wrappers_and_library_bound_callback(
    tmp_path: Path,
) -> None:
    """Clean functions, static/class methods, and external bound callbacks stay green."""
    document = _executable_fixture(tmp_path)
    source = tmp_path / "ontologylab/registry.py"
    source.write_text(
        source.read_text(encoding="utf-8")
        + """

import pathlib as _a13_pathlib
import types as _a13_clean_types
class A13WrapperDescriptor:
    def __init__(self, callback): self.callback = callback
    def __get__(self, instance, owner): return self.callback.__get__(instance, owner)
class A13CleanFunctionOwner:
    @A13WrapperDescriptor
    def marker(self): return "source"
class A13StaticClassOwner:
    @staticmethod
    def static(): return "source"
    @classmethod
    def build(cls): return cls()
class A13BoundLibraryOwner:
    marker = A13WrapperDescriptor(_a13_pathlib.Path(".").exists)
class A13StatelessReceiver: pass
def a13_clean_bound(self): return "source"
class A13CleanBoundOwner:
    marker = A13WrapperDescriptor(
        _a13_clean_types.MethodType(a13_clean_bound, A13StatelessReceiver())
    )
""",
        encoding="utf-8",
    )

    result = _run_checker(tmp_path, document)

    payload = json.loads(result.stdout)
    assert result.returncode == 0, payload["issues"]
    assert payload["issues"] == []


@pytest.mark.parametrize("mutation", ("receiver", "function"))
def test_cli_rejects_changed_source_declared_methodtype(
    tmp_path: Path, mutation: str
) -> None:
    """The narrow source MethodType domain binds wrapper kind and receiver identity."""
    document = _executable_fixture(tmp_path)
    source = tmp_path / "ontologylab/registry.py"
    source.write_text(
        source.read_text(encoding="utf-8")
        + """

import types as _a13_types2
class A13BoundDescriptor:
    def __init__(self, callback): self.callback = callback
    def __get__(self, instance, owner): return self.callback
class A13ExpectedReceiver: pass
class A13OtherReceiver: pass
def a13_bound_callback(self): return type(self).__name__
class A13BoundOwner:
    marker = A13BoundDescriptor(_a13_types2.MethodType(a13_bound_callback, A13ExpectedReceiver()))
if """
        + repr(mutation)
        + """ == "receiver":
    vars(A13BoundOwner)["marker"].callback = _a13_types2.MethodType(a13_bound_callback, A13OtherReceiver())
else:
    vars(A13BoundOwner)["marker"].callback = a13_bound_callback
""",
        encoding="utf-8",
    )

    result = _run_checker(tmp_path, document)

    details = " ".join(issue["detail"] for issue in json.loads(result.stdout)["issues"])
    expected = (
        "has a method receiver that differs"
        if mutation == "receiver"
        else "is an unbound function where source declares a bound method"
    )
    assert f"A13BoundOwner.marker.callback {expected}" in details
    assert result.returncode == 1


def test_methodtype_container_tokens_include_receiver_state() -> None:
    helpers = _shipped_helpers(
        "_frame", "_constant_bytes", "_code_bytes", "_descriptor_value_bytes"
    )
    encode = helpers["_descriptor_value_bytes"]
    namespace: dict[str, object] = {}
    exec("def callback(self): return self.label", namespace)
    callback = namespace["callback"]
    first = types.SimpleNamespace(label="first")
    second = types.SimpleNamespace(label="second")
    assert encode(types.MethodType(callback, first)) != encode(types.MethodType(callback, second))


def test_methodtype_set_paths_are_stable_across_hash_seeds(tmp_path: Path) -> None:
    document = _executable_fixture(tmp_path)
    source = tmp_path / "ontologylab/registry.py"
    source.write_text(
        source.read_text(encoding="utf-8")
        + """

import types as _a13_set_types
class A13MethodSetDescriptor:
    def __init__(self, callback): self.callbacks = {callback}
    def __get__(self, instance, owner): return next(iter(self.callbacks))
class A13MethodSetOwner:
    @A13MethodSetDescriptor
    def marker(self): return type(self).__name__
class A13SetFirst: pass
class A13SetSecond: pass
_a13_method = vars(A13MethodSetOwner)["marker"].callbacks.pop()
vars(A13MethodSetOwner)["marker"].callbacks = {
    _a13_set_types.MethodType(_a13_method, A13SetFirst()),
    _a13_set_types.MethodType(_a13_method, A13SetSecond()),
}
""",
        encoding="utf-8",
    )
    details = []
    for seed in ("1", "271"):
        result = _run_checker(
            tmp_path, document, environment={**os.environ, "PYTHONHASHSEED": seed}
        )
        assert result.returncode == 1
        detail = " ".join(issue["detail"] for issue in json.loads(result.stdout)["issues"])
        assert detail.count("A13MethodSetOwner.marker.callbacks{member:") == 2
        details.append(detail)
    assert details[0] == details[1]


@pytest.mark.parametrize("callback_form", ("module", "class"))
def test_cli_accepts_source_declared_descriptor_constructor_callbacks(
    tmp_path: Path, callback_form: str
) -> None:
    """Constructor assignment proves module/class callback provenance without live identity."""
    document = _executable_fixture(tmp_path)
    source = tmp_path / "ontologylab/registry.py"
    declaration = (
        "def a13_module_callback(self): return 'source'\n"
        "class A13ModuleCallbackOwner:\n"
        "    marker: object = A13ComposedDescriptor(callback=a13_module_callback)\n"
        "assert A13ModuleCallbackOwner().marker() == 'source'\n"
        if callback_form == "module"
        else "class A13ClassCallbackOwner:\n"
        "    def callback(self): return 'source'\n"
        "    marker = A13ComposedDescriptor(callback)\n"
        "assert A13ClassCallbackOwner().marker() == 'source'\n"
    )
    source.write_text(
        source.read_text(encoding="utf-8")
        + """

class A13ComposedDescriptor:
    def __init__(self, callback): self.callback: object = callback
    def __get__(self, instance, owner): return self.callback.__get__(instance, owner)
"""
        + declaration,
        encoding="utf-8",
    )

    result = _run_checker(tmp_path, document)

    payload = json.loads(result.stdout)
    assert result.returncode == 0, payload["issues"]
    assert payload["issues"] == []


@pytest.mark.parametrize("replacement", ("sibling", "moduleless", "synthetic"))
def test_cli_rejects_descriptor_constructor_callback_substitution(
    tmp_path: Path, replacement: str
) -> None:
    """Provenance remains the source argument, never the replacement's live qualname."""
    document = _executable_fixture(tmp_path)
    source = tmp_path / "ontologylab/registry.py"
    if replacement == "sibling":
        mutation = 'vars(A13NegativeOwner)["marker"].callback = a13_sibling\n'
    elif replacement == "moduleless":
        mutation = (
            "a13_sibling.__module__ = None\n"
            'vars(A13NegativeOwner)["marker"].callback = a13_sibling\n'
        )
    else:
        mutation = (
            '_a13_ns = {"__name__": __name__}\n'
            'exec(compile("def a13_original(self): return \'leftover\'", '
            '"<string>", "exec"), _a13_ns)\n'
            'vars(A13NegativeOwner)["marker"].callback = _a13_ns["a13_original"]\n'
        )
    source.write_text(
        source.read_text(encoding="utf-8")
        + """

class A13NegativeDescriptor:
    def __init__(self, callback): self.callback = callback
    def __get__(self, instance, owner): return self.callback.__get__(instance, owner)
def a13_original(self): return "source"
def a13_sibling(self): return "leftover"
class A13NegativeOwner:
    marker = A13NegativeDescriptor(a13_original)
"""
        + mutation,
        encoding="utf-8",
    )

    result = _run_checker(tmp_path, document)

    details = " ".join(issue["detail"] for issue in json.loads(result.stdout)["issues"])
    assert "A13NegativeOwner.marker.callback" in details
    if replacement in {"sibling", "moduleless"}:
        assert "not compiled from this file under that name" in details
    else:
        assert "was compiled from <string>" in details
    assert result.returncode == 1


def test_cli_rejects_changed_slotted_method_receiver_state(tmp_path: Path) -> None:
    """Concrete slots are invocation state even when the instance has no __dict__."""
    document = _executable_fixture(tmp_path)
    source = tmp_path / "ontologylab/registry.py"
    source.write_text(
        source.read_text(encoding="utf-8")
        + """

import types as _a14_slot_types
class A14SlotDescriptor:
    def __init__(self, callback): self.callback = callback
    def __get__(self, instance, owner): return self.callback
class A14SlotReceiver:
    __slots__ = ("label",)
    def __init__(self): self.label = "source"
def a14_slot_callback(self): return self.label
class A14SlotOwner:
    marker = A14SlotDescriptor(
        _a14_slot_types.MethodType(a14_slot_callback, A14SlotReceiver())
    )
_a14_slot_leftover = A14SlotReceiver()
_a14_slot_leftover.label = "leftover"
vars(A14SlotOwner)["marker"].callback = _a14_slot_types.MethodType(
    a14_slot_callback, _a14_slot_leftover
)
assert vars(A14SlotOwner)["marker"].callback() == "leftover"
""",
        encoding="utf-8",
    )

    result = _run_checker(tmp_path, document)

    details = " ".join(issue["detail"] for issue in json.loads(result.stdout)["issues"])
    assert "A14SlotOwner.marker.callback has a method receiver state that differs" in details
    assert result.returncode == 1


def test_cli_accepts_clean_inherited_and_unset_slotted_receivers(tmp_path: Path) -> None:
    """Inherited and unset concrete slots have deterministic source/live presence state."""
    document = _executable_fixture(tmp_path)
    source = tmp_path / "ontologylab/registry.py"
    source.write_text(
        source.read_text(encoding="utf-8")
        + """

import types as _a14_clean_slot_types
class A14CleanSlotDescriptor:
    def __init__(self, callback): self.callback = callback
    def __get__(self, instance, owner): return self.callback
class A14SlotBase:
    __slots__ = ("base", "unset")
    def __init__(self): self.base = {"label": "source"}
class A14SlotChild(A14SlotBase):
    __slots__ = ("child", "__weakref__")
    def __init__(self):
        super().__init__()
        self.child = ("source",)
def a14_clean_slot_callback(self): return self.base, self.child
class A14CleanSlotOwner:
    marker = A14CleanSlotDescriptor(
        _a14_clean_slot_types.MethodType(a14_clean_slot_callback, A14SlotChild())
    )
assert vars(A14CleanSlotOwner)["marker"].callback() == ({"label": "source"}, ("source",))
""",
        encoding="utf-8",
    )

    result = _run_checker(tmp_path, document)

    payload = json.loads(result.stdout)
    assert result.returncode == 0, payload["issues"]
    assert payload["issues"] == []


def test_slotted_method_receiver_tokens_bind_presence_values_and_cycles() -> None:
    helpers = _shipped_helpers(
        "_frame", "_constant_bytes", "_code_bytes", "_descriptor_value_bytes"
    )
    encode = helpers["_descriptor_value_bytes"]

    class Base:
        __slots__ = ("base", "unset")

    class Child(Base):
        __slots__ = ("child",)

    def callback(self):
        return None

    first = Child()
    first.base = "source"
    first.child = 1
    second = Child()
    second.base = "source"
    second.child = 2
    assert encode(types.MethodType(callback, first)) != encode(
        types.MethodType(callback, second)
    )
    del second.child
    assert encode(types.MethodType(callback, first)) != encode(
        types.MethodType(callback, second)
    )
    second.child = second
    with pytest.raises(TypeError):
        encode(types.MethodType(callback, second))


@pytest.mark.parametrize("source_kind", ("function", "method"))
def test_cli_rejects_source_local_callback_replaced_by_library_method(
    tmp_path: Path, source_kind: str
) -> None:
    """Source-local callable proof precedes the genuine-library exemption."""
    document = _executable_fixture(tmp_path)
    source = tmp_path / "ontologylab/registry.py"
    callback = (
        "a14_local_callback"
        if source_kind == "function"
        else "_a14_library_types.MethodType(a14_local_callback, A14LibraryReceiver())"
    )
    source.write_text(
        source.read_text(encoding="utf-8")
        + """

import pathlib as _a14_pathlib
import types as _a14_library_types
class A14LibraryDescriptor:
    def __init__(self, callback): self.callback = callback
    def __get__(self, instance, owner): return self.callback
class A14LibraryReceiver: pass
def a14_local_callback(self=None): return "source"
class A14LocalToLibraryOwner:
    marker = A14LibraryDescriptor("""
        + callback
        + """)
vars(A14LocalToLibraryOwner)["marker"].callback = _a14_pathlib.Path(".").exists
assert isinstance(vars(A14LocalToLibraryOwner)["marker"].callback(), bool)
""",
        encoding="utf-8",
    )

    result = _run_checker(tmp_path, document)

    details = " ".join(issue["detail"] for issue in json.loads(result.stdout)["issues"])
    assert "A14LocalToLibraryOwner.marker.callback" in details
    assert result.returncode == 1


def test_cli_accepts_source_declared_library_callbacks(tmp_path: Path) -> None:
    """Option A still exempts external callbacks when source declares the external value."""
    document = _executable_fixture(tmp_path)
    source = tmp_path / "ontologylab/registry.py"
    source.write_text(
        source.read_text(encoding="utf-8")
        + """

import pathlib as _a14_clean_pathlib
class A14ExternalDescriptor:
    def __init__(self, callback): self.callback = callback
    def __get__(self, instance, owner): return self.callback
class A14ExternalOwner:
    positional = A14ExternalDescriptor(_a14_clean_pathlib.Path(".").exists)
    keyword = A14ExternalDescriptor(callback=_a14_clean_pathlib.Path(".").is_dir)
assert isinstance(vars(A14ExternalOwner)["positional"].callback(), bool)
""",
        encoding="utf-8",
    )

    result = _run_checker(tmp_path, document)

    payload = json.loads(result.stdout)
    assert result.returncode == 0, payload["issues"]
    assert payload["issues"] == []


def test_cli_resolves_lexically_colliding_descriptor_constructors(tmp_path: Path) -> None:
    """Bare and qualified constructor calls retain their fully lexical declarations."""
    document = _executable_fixture(tmp_path)
    source = tmp_path / "ontologylab/registry.py"
    source.write_text(
        source.read_text(encoding="utf-8")
        + """

class A14CollisionDescriptor:
    def __init__(self, callback): self.callback = callback
    def __get__(self, instance, owner): return self.callback.__get__(instance, owner)
class A14CollisionContainer:
    class A14CollisionDescriptor:
        def __init__(self, handler): self.handler = handler
        def __get__(self, instance, owner): return self.handler.__get__(instance, owner)
    def nested_callback(self): return "nested"
    positional = A14CollisionDescriptor(nested_callback)
    keyword = A14CollisionDescriptor(handler=nested_callback)
def a14_collision_callback(self): return "module"
class A14CollisionOwner:
    positional = A14CollisionDescriptor(a14_collision_callback)
    keyword = A14CollisionDescriptor(callback=a14_collision_callback)
    annotated: object = A14CollisionDescriptor(a14_collision_callback)
    nested = A14CollisionContainer.A14CollisionDescriptor(a14_collision_callback)
assert A14CollisionOwner().positional() == "module"
assert A14CollisionContainer().positional() == "nested"
assert A14CollisionOwner().nested() == "module"
""",
        encoding="utf-8",
    )

    result = _run_checker(tmp_path, document)

    payload = json.loads(result.stdout)
    assert result.returncode == 0, payload["issues"]
    assert payload["issues"] == []


@pytest.mark.parametrize("scope", ("module", "nested"))
@pytest.mark.parametrize("replacement", ("sibling", "synthetic"))
def test_cli_rejects_colliding_constructor_callback_substitutions(
    tmp_path: Path, scope: str, replacement: str
) -> None:
    """Each lexical constructor scope keeps its own callback binding load-bearing."""
    document = _executable_fixture(tmp_path)
    source = tmp_path / "ontologylab/registry.py"
    owner = "A14LexicalOwner" if scope == "module" else "A14LexicalContainer"
    attribute = "callback" if scope == "module" else "handler"
    if replacement == "sibling":
        mutation = f'vars({owner})["marker"].{attribute} = a14_lexical_sibling\n'
    else:
        mutation = (
            '_a14_lexical_ns = {"__name__": __name__}\n'
            'exec(compile("def a14_lexical_original(self): return \'synthetic\'", '
            '"<string>", "exec"), _a14_lexical_ns)\n'
            f'vars({owner})["marker"].{attribute} = _a14_lexical_ns["a14_lexical_original"]\n'
        )
    source.write_text(
        source.read_text(encoding="utf-8")
        + """

def a14_lexical_original(self): return "source"
def a14_lexical_sibling(self): return "leftover"
class A14LexicalDescriptor:
    def __init__(self, callback): self.callback = callback
    def __get__(self, instance, owner): return self.callback.__get__(instance, owner)
class A14LexicalContainer:
    class A14LexicalDescriptor:
        def __init__(self, handler): self.handler = handler
        def __get__(self, instance, owner): return self.handler.__get__(instance, owner)
    marker = A14LexicalDescriptor(a14_lexical_original)
class A14LexicalOwner:
    marker = A14LexicalDescriptor(a14_lexical_original)
"""
        + mutation,
        encoding="utf-8",
    )

    result = _run_checker(tmp_path, document)

    details = " ".join(issue["detail"] for issue in json.loads(result.stdout)["issues"])
    assert f"{owner}.marker.{attribute}" in details
    assert result.returncode == 1


def test_cli_accepts_local_and_qualified_class_method_receivers(tmp_path: Path) -> None:
    """Name and qualified Attribute class objects are source-bound class receivers."""
    document = _executable_fixture(tmp_path)
    source = tmp_path / "ontologylab/registry.py"
    source.write_text(
        source.read_text(encoding="utf-8")
        + """

import types as _a14_class_types
class A14ClassReceiverDescriptor:
    def __init__(self, callback): self.callback = callback
    def __get__(self, instance, owner): return self.callback
class A14ClassReceiver: pass
class A14ClassReceiverContainer:
    class Receiver: pass
def a14_class_receiver_callback(cls): return cls.__name__
class A14ClassReceiverOwner:
    local = A14ClassReceiverDescriptor(
        _a14_class_types.MethodType(a14_class_receiver_callback, A14ClassReceiver)
    )
    qualified = A14ClassReceiverDescriptor(
        _a14_class_types.MethodType(
            a14_class_receiver_callback, A14ClassReceiverContainer.Receiver
        )
    )
assert vars(A14ClassReceiverOwner)["local"].callback() == "A14ClassReceiver"
assert vars(A14ClassReceiverOwner)["qualified"].callback() == "Receiver"
""",
        encoding="utf-8",
    )

    result = _run_checker(tmp_path, document)

    payload = json.loads(result.stdout)
    assert result.returncode == 0, payload["issues"]
    assert payload["issues"] == []


def test_class_method_receiver_tokens_are_canonical_in_frozensets() -> None:
    helpers = _shipped_helpers(
        "_frame", "_constant_bytes", "_code_bytes", "_descriptor_value_bytes"
    )
    encode = helpers["_descriptor_value_bytes"]

    class First: pass
    class Second: pass

    def callback(cls):
        return cls

    first = types.MethodType(callback, First)
    second = types.MethodType(callback, Second)
    assert encode(first) != encode(second)
    assert encode(frozenset((first, second))) == encode(frozenset((second, first)))


def test_cli_rejects_changed_class_method_receiver(tmp_path: Path) -> None:
    document = _executable_fixture(tmp_path)
    source = tmp_path / "ontologylab/registry.py"
    source.write_text(
        source.read_text(encoding="utf-8")
        + """

import types as _a14_changed_class_types
class A14ChangedClassDescriptor:
    def __init__(self, callback): self.callback = callback
    def __get__(self, instance, owner): return self.callback
class A14ExpectedClassReceiver: pass
class A14OtherClassReceiver: pass
def a14_changed_class_callback(cls): return cls.__name__
class A14ChangedClassOwner:
    marker = A14ChangedClassDescriptor(
        _a14_changed_class_types.MethodType(a14_changed_class_callback, A14ExpectedClassReceiver)
    )
vars(A14ChangedClassOwner)["marker"].callback = _a14_changed_class_types.MethodType(
    a14_changed_class_callback, A14OtherClassReceiver
)
assert vars(A14ChangedClassOwner)["marker"].callback() == "A14OtherClassReceiver"
""",
        encoding="utf-8",
    )

    result = _run_checker(tmp_path, document)

    details = " ".join(issue["detail"] for issue in json.loads(result.stdout)["issues"])
    assert "A14ChangedClassOwner.marker.callback has a method receiver that differs" in details
    assert result.returncode == 1


def test_same_class_empty_receiver_identity_is_a_declared_residual(tmp_path: Path) -> None:
    """The isolated checker knowingly cannot source-rederive instance object identity."""
    document = _executable_fixture(tmp_path)
    source = tmp_path / "ontologylab/registry.py"
    source.write_text(
        source.read_text(encoding="utf-8")
        + """

import types as _a14_identity_types
class A14IdentityDescriptor:
    def __init__(self, callback): self.callback = callback
    def __get__(self, instance, owner): return self.callback
class A14IdentityReceiver: pass
def a14_identity_callback(self): return self is _a14_expected_receiver
_a14_expected_receiver = A14IdentityReceiver()
class A14IdentityOwner:
    marker = A14IdentityDescriptor(
        _a14_identity_types.MethodType(a14_identity_callback, A14IdentityReceiver())
    )
_a14_expected_receiver = vars(A14IdentityOwner)["marker"].callback.__self__
assert vars(A14IdentityOwner)["marker"].callback() is True
vars(A14IdentityOwner)["marker"].callback = _a14_identity_types.MethodType(
    a14_identity_callback, A14IdentityReceiver()
)
assert vars(A14IdentityOwner)["marker"].callback() is False
""",
        encoding="utf-8",
    )

    result = _run_checker(tmp_path, document)

    payload = json.loads(result.stdout)
    assert result.returncode == 0, payload["issues"]
    assert payload["issues"] == []


def test_method_receiver_identity_residual_cannot_drift_into_hostile_boundaries() -> None:
    residual = _spec_section("#### 7.1.3", "## 8. 비목표")
    assert "`residual-5-receiver-identity`" in residual
    assert "same-class" in residual
    assert "object identity" in residual
    hostile = _spec_section("**막지 않는 것", "#### 7.1.1")
    assert "residual-5" not in hostile
    checker = (
        Path(__file__).resolve().parents[1] / "scripts/check_product_status.py"
    ).read_text(encoding="utf-8")
    assert "residual-5-receiver-identity" in checker


def test_cli_accepts_literal_parameter_and_combined_receiver_state(tmp_path: Path) -> None:
    """S1: direct dictionary values and constructor-bound values match live encoding."""
    document = _executable_fixture(tmp_path)
    source = tmp_path / "ontologylab/registry.py"
    source.write_text(
        source.read_text(encoding="utf-8")
        + r'''

import types as _a15_state_types
class A15StateDescriptor:
    def __init__(self, callback): self.callback = callback
    def __get__(self, instance, owner): return self.callback
class A15LiteralReceiver:
    def __init__(self):
        self.label = "source"
        self.payload = {"items": [1, True, None], "tags": {"b", "a"}}
class A15ParameterReceiver:
    def __init__(self, label="default", *, payload=(1, "x")):
        self.label = label
        self.payload = payload
class A15CombinedBase:
    __slots__ = {"base": "documented base", "unset": "left unset", "__dict__": "state"}
    def __init__(self, base): self.base = base
class A15CombinedReceiver(A15CombinedBase):
    __slots__ = ("child",)
    def __init__(self, label, child="slot"):
        super().__init__("base")
        self.label = label
        self.child = child
def a15_state_callback(self): return getattr(self, "label", None)
class A15StateOwner:
    literal = A15StateDescriptor(_a15_state_types.MethodType(a15_state_callback, A15LiteralReceiver()))
    positional = A15StateDescriptor(_a15_state_types.MethodType(a15_state_callback, A15ParameterReceiver("source")))
    keyword = A15StateDescriptor(_a15_state_types.MethodType(a15_state_callback, A15ParameterReceiver(label="source", payload={"k": 2})))
    defaults = A15StateDescriptor(_a15_state_types.MethodType(a15_state_callback, A15ParameterReceiver()))
    combined = A15StateDescriptor(_a15_state_types.MethodType(a15_state_callback, A15CombinedReceiver("source")))
assert vars(A15StateOwner)["literal"].callback() == "source"
assert vars(A15StateOwner)["combined"].callback() == "source"
''',
        encoding="utf-8",
    )

    result = _run_checker(tmp_path, document)

    payload = json.loads(result.stdout)
    assert result.returncode == 0, payload["issues"]
    assert payload["issues"] == []


def test_cli_rejects_changed_ordinary_receiver_dictionary(tmp_path: Path) -> None:
    """S1 inverse: expected state comes from source, never from the live receiver."""
    document = _executable_fixture(tmp_path)
    source = tmp_path / "ontologylab/registry.py"
    source.write_text(
        source.read_text(encoding="utf-8")
        + '''

import types as _a15_dict_types
class A15DictDescriptor:
    def __init__(self, callback): self.callback = callback
    def __get__(self, instance, owner): return self.callback
class A15DictReceiver:
    def __init__(self, label): self.label = label
def a15_dict_callback(self): return self.label
class A15DictOwner:
    marker = A15DictDescriptor(_a15_dict_types.MethodType(a15_dict_callback, A15DictReceiver("source")))
_a15_changed_dict = A15DictReceiver("leftover")
vars(A15DictOwner)["marker"].callback = _a15_dict_types.MethodType(a15_dict_callback, _a15_changed_dict)
assert vars(A15DictOwner)["marker"].callback() == "leftover"
''',
        encoding="utf-8",
    )

    result = _run_checker(tmp_path, document)

    details = " ".join(issue["detail"] for issue in json.loads(result.stdout)["issues"])
    assert "A15DictOwner.marker.callback has a method receiver state that differs" in details
    assert result.returncode == 1


def test_cli_handles_diamond_mro_slots_and_rejects_changed_state(tmp_path: Path) -> None:
    """S2: a shared base is legal and concrete slots follow reverse C3 MRO once."""
    document = _executable_fixture(tmp_path)
    source = tmp_path / "ontologylab/registry.py"
    source.write_text(
        source.read_text(encoding="utf-8")
        + '''

import types as _a15_diamond_types
class A15DiamondDescriptor:
    def __init__(self, callback): self.callback = callback
    def __get__(self, instance, owner): return self.callback
class A15DiamondBase:
    __slots__ = ("label",)
    def __init__(self, label="source"): self.label = label
class A15DiamondLeft(A15DiamondBase): __slots__ = ()
class A15DiamondRight(A15DiamondBase): __slots__ = ()
class A15Diamond(A15DiamondLeft, A15DiamondRight): __slots__ = ()
def a15_diamond_callback(self): return self.label
class A15DiamondOwner:
    clean = A15DiamondDescriptor(_a15_diamond_types.MethodType(a15_diamond_callback, A15Diamond()))
    changed = A15DiamondDescriptor(_a15_diamond_types.MethodType(a15_diamond_callback, A15Diamond()))
_a15_changed_diamond = A15Diamond("leftover")
vars(A15DiamondOwner)["changed"].callback = _a15_diamond_types.MethodType(a15_diamond_callback, _a15_changed_diamond)
assert vars(A15DiamondOwner)["clean"].callback() == "source"
''',
        encoding="utf-8",
    )

    result = _run_checker(tmp_path, document)

    details = " ".join(issue["detail"] for issue in json.loads(result.stdout)["issues"])
    assert "A15DiamondOwner.clean" not in details
    assert "A15DiamondOwner.changed.callback has a method receiver state that differs" in details
    assert result.returncode == 1


def test_source_receiver_lineage_fails_closed_on_a_real_cycle() -> None:
    """S2 inverse: active-stack cycle detection permits diamonds, not real cycles."""
    helpers = _shipped_helpers(
        "_frame", "_constant_bytes", "_source_default", "_assigned_pairs",
        "source_descriptor_callables",
    )
    tree = ast.parse('''
class Descriptor:
    def __init__(self, callback): self.callback = callback
class A(B): pass
class B(A): pass
def callback(self): return None
class Owner:
    marker = Descriptor(MethodType(callback, A()))
''')
    assert helpers["source_descriptor_callables"](tree, {}, "probe") == {}


def test_cli_handles_mapping_form_slots_and_rejects_mutation(tmp_path: Path) -> None:
    """S3: mapping keys are slot names; documentation values are not state."""
    document = _executable_fixture(tmp_path)
    source = tmp_path / "ontologylab/registry.py"
    source.write_text(
        source.read_text(encoding="utf-8")
        + '''

import types as _a15_mapping_types
class A15MappingDescriptor:
    def __init__(self, callback): self.callback = callback
    def __get__(self, instance, owner): return self.callback
class A15MappingReceiver:
    __slots__ = {"label": "documentation only"}
    def __init__(self, label="source"): self.label = label
def a15_mapping_callback(self): return self.label
class A15MappingOwner:
    clean = A15MappingDescriptor(_a15_mapping_types.MethodType(a15_mapping_callback, A15MappingReceiver()))
    changed = A15MappingDescriptor(_a15_mapping_types.MethodType(a15_mapping_callback, A15MappingReceiver()))
_a15_mapping_changed = A15MappingReceiver("leftover")
vars(A15MappingOwner)["changed"].callback = _a15_mapping_types.MethodType(a15_mapping_callback, _a15_mapping_changed)
''',
        encoding="utf-8",
    )

    result = _run_checker(tmp_path, document)

    details = " ".join(issue["detail"] for issue in json.loads(result.stdout)["issues"])
    assert "A15MappingOwner.clean" not in details
    assert "A15MappingOwner.changed.callback has a method receiver state that differs" in details
    assert result.returncode == 1


@pytest.mark.parametrize("changed", (False, True))
def test_cli_resolves_imported_library_class_receivers(
    tmp_path: Path, changed: bool
) -> None:
    """S4: imported qualified class receiver identity is source-derived and binding."""
    document = _executable_fixture(tmp_path)
    source = tmp_path / "ontologylab/registry.py"
    mutation = "" if not changed else '''
vars(A15LibraryClassOwner)["marker"].callback = _a15_lib_types.MethodType(
    a15_library_class_callback, _a15_pathlib.PurePath
)
'''
    source.write_text(
        source.read_text(encoding="utf-8")
        + '''

import pathlib as _a15_pathlib
import types as _a15_lib_types
class A15LibraryClassDescriptor:
    def __init__(self, callback): self.callback = callback
    def __get__(self, instance, owner): return self.callback
def a15_library_class_callback(cls): return cls.__name__
class A15LibraryClassOwner:
    marker = A15LibraryClassDescriptor(
        _a15_lib_types.MethodType(a15_library_class_callback, _a15_pathlib.Path)
    )
'''
        + mutation,
        encoding="utf-8",
    )

    result = _run_checker(tmp_path, document)
    payload = json.loads(result.stdout)
    if changed:
        assert result.returncode == 1
        assert "A15LibraryClassOwner.marker.callback has a method receiver that differs" in " ".join(
            issue["detail"] for issue in payload["issues"]
        )
    else:
        assert result.returncode == 0, payload["issues"]


@pytest.mark.parametrize("changed", (False, True))
def test_cli_resolves_constructor_before_later_nested_shadow(
    tmp_path: Path, changed: bool
) -> None:
    """S5: class body names see only prior local bindings, then module globals."""
    document = _executable_fixture(tmp_path)
    source = tmp_path / "ontologylab/registry.py"
    mutation = "" if not changed else '''
vars(A15TemporalOwner)["before"].callback = _a15_temporal_path.Path(".").exists
'''
    source.write_text(
        source.read_text(encoding="utf-8")
        + '''

import pathlib as _a15_temporal_path
class Descriptor:
    def __init__(self, callback): self.callback = callback
    def __get__(self, instance, owner): return self.callback
def a15_temporal_callback(self=None): return "source"
class A15TemporalOwner:
    before = Descriptor(a15_temporal_callback)
    class Descriptor:
        def __init__(self, handler): self.handler = handler
        def __get__(self, instance, owner): return self.handler
    after = Descriptor(a15_temporal_callback)
assert vars(A15TemporalOwner)["after"].handler() == "source"
'''
        + mutation,
        encoding="utf-8",
    )

    result = _run_checker(tmp_path, document)
    payload = json.loads(result.stdout)
    if changed:
        assert result.returncode == 1
        assert "A15TemporalOwner.before.callback" in " ".join(
            issue["detail"] for issue in payload["issues"]
        )
    else:
        assert result.returncode == 0, payload["issues"]


@pytest.mark.parametrize("changed", (False, True))
def test_cli_tracks_constructor_alias_chains_through_later_deletion(
    tmp_path: Path, changed: bool
) -> None:
    """S6: assignment aliases retain qualified constructor provenance at call time."""
    document = _executable_fixture(tmp_path)
    source = tmp_path / "ontologylab/registry.py"
    mutation = "" if not changed else '''
vars(A15AliasOwner)["marker"].callback = _a15_alias_path.Path(".").exists
'''
    source.write_text(
        source.read_text(encoding="utf-8")
        + '''

import pathlib as _a15_alias_path
class A15AliasDescriptor:
    def __init__(self, callback): self.callback = callback
    def __get__(self, instance, owner): return self.callback
A15AliasOne = A15AliasDescriptor
A15AliasTwo: object = A15AliasOne
def a15_alias_callback(self=None): return "source"
class A15AliasOwner:
    marker = A15AliasTwo(a15_alias_callback)
del A15AliasTwo
del A15AliasOne
'''
        + mutation,
        encoding="utf-8",
    )

    result = _run_checker(tmp_path, document)
    payload = json.loads(result.stdout)
    if changed:
        assert result.returncode == 1
        assert "A15AliasOwner.marker.callback" in " ".join(
            issue["detail"] for issue in payload["issues"]
        )
    else:
        assert result.returncode == 0, payload["issues"]


@pytest.mark.parametrize(
    ("aliases", "deletion"),
    (
        ("A16ChainOne = A16ChainTwo = A16ChainDescriptor", "del A16ChainOne, A16ChainTwo"),
        ("A16ChainOne = A16ChainTwo = A16ChainDescriptor\nA16ChainThree = A16ChainTwo", "del A16ChainOne, A16ChainTwo, A16ChainThree"),
    ),
)
@pytest.mark.parametrize("replacement", ("", "library", "sibling", "synthetic"))
def test_cli_tracks_chained_constructor_alias_events(
    tmp_path: Path, aliases: str, deletion: str, replacement: str
) -> None:
    """A1: every Name in a chained assignment retains the one RHS event."""
    document = _executable_fixture(tmp_path)
    source = tmp_path / "ontologylab/registry.py"
    constructor = "A16ChainThree" if "Three" in aliases else "A16ChainTwo"
    mutation = {
        "": "",
        "library": 'vars(A16ChainOwner)["marker"].callback = _a16_chain_path.Path(".").exists',
        "sibling": 'vars(A16ChainOwner)["marker"].callback = a16_chain_sibling',
        "synthetic": 'vars(A16ChainOwner)["marker"].callback = eval(compile("lambda: True", "<string>", "eval"))',
    }[replacement]
    source.write_text(
        source.read_text(encoding="utf-8")
        + f'''\n\nimport pathlib as _a16_chain_path
class A16ChainDescriptor:
    def __init__(self, callback): self.callback = callback
    def __get__(self, instance, owner): return self.callback
{aliases}
def a16_chain_callback(self=None): return "source"
def a16_chain_sibling(self=None): return "sibling"
class A16ChainOwner:
    marker = {constructor}(a16_chain_callback)
{deletion}
{mutation}
''',
        encoding="utf-8",
    )

    result = _run_checker(tmp_path, document)
    details = " ".join(issue["detail"] for issue in json.loads(result.stdout)["issues"])
    if replacement:
        assert result.returncode == 1
        assert "A16ChainOwner.marker.callback" in details
    else:
        assert result.returncode == 0, details


@pytest.mark.parametrize("slot_form", ('("zeta", "alpha")', '["zeta", "alpha"]', '{"zeta": "z", "alpha": "a"}'))
@pytest.mark.parametrize("mutated", (False, True))
def test_cli_canonicalizes_multislot_receiver_state(
    tmp_path: Path, slot_form: str, mutated: bool
) -> None:
    """A2: source/live slot records have one qualified, order-independent order."""
    document = _executable_fixture(tmp_path)
    source = tmp_path / "ontologylab/registry.py"
    mutation = "" if not mutated else '''
_a16_slots_changed = A16SlotChild()
_a16_slots_changed.alpha = "changed"
vars(A16SlotOwner)["marker"].callback = _a16_slot_types.MethodType(a16_slot_callback, _a16_slots_changed)
'''
    source.write_text(
        source.read_text(encoding="utf-8")
        + f'''\n\nimport types as _a16_slot_types
class A16SlotDescriptor:
    def __init__(self, callback): self.callback = callback
    def __get__(self, instance, owner): return self.callback
class A16SlotBase:
    __slots__ = {slot_form}
    def __init__(self): self.zeta = "z"; self.alpha = "a"
class A16SlotLeft(A16SlotBase): __slots__ = ()
class A16SlotRight(A16SlotBase): __slots__ = ()
class A16SlotChild(A16SlotLeft, A16SlotRight):
    __slots__ = ("zeta", "unset")
    def __init__(self): super().__init__(); self.zeta = "child-z"
def a16_slot_callback(self): return self.alpha + self.zeta
class A16SlotOwner:
    marker = A16SlotDescriptor(_a16_slot_types.MethodType(a16_slot_callback, A16SlotChild()))
{mutation}
''',
        encoding="utf-8",
    )

    result = _run_checker(tmp_path, document)
    details = " ".join(issue["detail"] for issue in json.loads(result.stdout)["issues"])
    if mutated:
        assert result.returncode == 1
        assert "A16SlotOwner.marker.callback has a method receiver state that differs" in details
    else:
        assert result.returncode == 0, details


@pytest.mark.parametrize("scope", ("module", "class"))
@pytest.mark.parametrize("owner", ("first", "second"))
@pytest.mark.parametrize("replacement", ("", "other", "library"))
def test_cli_binds_callbacks_to_exact_duplicate_definition_events(
    tmp_path: Path, scope: str, owner: str, replacement: str
) -> None:
    """B1: retained callbacks bind to the exact visible module/class definition event."""
    document = _executable_fixture(tmp_path)
    source = tmp_path / "ontologylab/registry.py"
    if scope == "module":
        declarations = '''
def a16_duplicate_callback(): return "first"
class A16DuplicateFirstOwner:
    marker = A16DuplicateDescriptor(a16_duplicate_callback)
def a16_duplicate_callback(): return "second"
class A16DuplicateSecondOwner:
    marker = A16DuplicateDescriptor(a16_duplicate_callback)
'''
        owner_expr = f"A16Duplicate{owner.title()}Owner"
    else:
        declarations = '''
class A16CallbackScope:
    def callback(): return "first"
    first = A16DuplicateDescriptor(callback)
    def callback(): return "second"
    second = A16DuplicateDescriptor(callback)
'''
        owner_expr = "A16CallbackScope"
    other = "second" if owner == "first" else "first"
    other_expr = (
        f'vars(A16Duplicate{other.title()}Owner)["marker"].callback'
        if scope == "module"
        else f'vars(A16CallbackScope)["{other}"].callback'
    )
    mutation = {
        "": "",
        "other": f'vars({owner_expr})["{owner if scope == "class" else "marker"}"].callback = {other_expr}',
        "library": f'vars({owner_expr})["{owner if scope == "class" else "marker"}"].callback = _a16_duplicate_path.Path(".").exists',
    }[replacement]
    source.write_text(
        source.read_text(encoding="utf-8")
        + '''\n\nimport pathlib as _a16_duplicate_path
class A16DuplicateDescriptor:
    def __init__(self, callback): self.callback = callback
    def __get__(self, instance, owner): return self.callback
'''
        + declarations
        + mutation
        + "\n",
        encoding="utf-8",
    )

    result = _run_checker(tmp_path, document)
    details = " ".join(issue["detail"] for issue in json.loads(result.stdout)["issues"])
    expected = owner_expr + (f".{owner}.callback" if scope == "class" else ".marker.callback")
    if replacement:
        assert result.returncode == 1
        assert expected in details
    else:
        assert result.returncode == 0, details


def test_cli_allows_identical_duplicate_function_bodies(tmp_path: Path) -> None:
    """B1 control: swapping semantically identical compiled bodies is indistinguishable."""
    document = _executable_fixture(tmp_path)
    source = tmp_path / "ontologylab/registry.py"
    source.write_text(source.read_text(encoding="utf-8") + '''

class A16IdenticalDescriptor:
    def __init__(self, callback): self.callback = callback
def a16_identical_callback(): return "same"
class A16IdenticalOwner:
    marker = A16IdenticalDescriptor(a16_identical_callback)
def a16_identical_callback(): return "same"
vars(A16IdenticalOwner)["marker"].callback = a16_identical_callback
''', encoding="utf-8")
    result = _run_checker(tmp_path, document)
    assert result.returncode == 0, json.loads(result.stdout)["issues"]


@pytest.mark.parametrize(
    ("import_line", "receiver"),
    (
        ("import collections.abc", "collections.abc.Mapping"),
        ("import xml.etree.ElementTree", "xml.etree.ElementTree.Element"),
        ("import collections.abc as cabc", "cabc.Mapping"),
        ("from collections.abc import Mapping", "Mapping"),
    ),
)
@pytest.mark.parametrize("changed", (False, True))
def test_cli_resolves_canonical_dotted_import_class_identity(
    tmp_path: Path, import_line: str, receiver: str, changed: bool
) -> None:
    """B2: the longest statically imported module prefix is the external identity."""
    document = _executable_fixture(tmp_path)
    source = tmp_path / "ontologylab/registry.py"
    mutation = "" if not changed else 'vars(A16ImportOwner)["marker"].callback = _a16_import_types.MethodType(a16_import_callback, _a16_import_path.PurePath)'
    source.write_text(source.read_text(encoding="utf-8") + f'''

import pathlib as _a16_import_path
import types as _a16_import_types
{import_line}
class A16ImportDescriptor:
    def __init__(self, callback): self.callback = callback
    def __get__(self, instance, owner): return self.callback
def a16_import_callback(cls): return cls.__name__
class A16ImportOwner:
    marker = A16ImportDescriptor(_a16_import_types.MethodType(a16_import_callback, {receiver}))
{mutation}
''', encoding="utf-8")
    result = _run_checker(tmp_path, document)
    details = " ".join(issue["detail"] for issue in json.loads(result.stdout)["issues"])
    if changed:
        assert result.returncode == 1
        assert "A16ImportOwner.marker.callback has a method receiver that differs" in details
    else:
        assert result.returncode == 0, details


@pytest.mark.parametrize("placement", ("module", "nested"))
@pytest.mark.parametrize("replacement", ("", "first-library", "second-library", "first-sibling"))
def test_cli_tracks_repeated_constructor_definition_events(
    tmp_path: Path, placement: str, replacement: str
) -> None:
    """B3: each construction uses constructor metadata from its visible class event."""
    document = _executable_fixture(tmp_path)
    source = tmp_path / "ontologylab/registry.py"
    if placement == "nested":
        declarations = '''
class A16RepeatedOwner:
    class Descriptor:
        def __init__(self, callback): self.callback = callback
        def __get__(self, instance, owner): return self.callback
    first = Descriptor(a16_repeated_callback)
    class Descriptor:
        def __init__(self, handler): self.handler = handler
        def __get__(self, instance, owner): return self.handler
    second = Descriptor(a16_repeated_callback)
'''
    else:
        declarations = '''
class A16RepeatedDescriptor:
    def __init__(self, callback): self.callback = callback
    def __get__(self, instance, owner): return self.callback
class A16RepeatedOwner:
    first = A16RepeatedDescriptor(a16_repeated_callback)
class A16RepeatedDescriptor:
    def __init__(self, handler): self.handler = handler
    def __get__(self, instance, owner): return self.handler
class A16RepeatedSecondOwner:
    second = A16RepeatedDescriptor(a16_repeated_callback)
'''
    second_owner = "A16RepeatedOwner" if placement == "nested" else "A16RepeatedSecondOwner"
    mutation = {
        "": "",
        "first-library": 'vars(A16RepeatedOwner)["first"].callback = _a16_repeated_path.Path(".").exists',
        "second-library": f'vars({second_owner})["second"].handler = _a16_repeated_path.Path(".").exists',
        "first-sibling": 'vars(A16RepeatedOwner)["first"].callback = a16_repeated_sibling',
    }[replacement]
    source.write_text(source.read_text(encoding="utf-8") + '''

import pathlib as _a16_repeated_path
def a16_repeated_callback(self=None): return "source"
def a16_repeated_sibling(self=None): return "sibling"
''' + declarations + mutation + "\n", encoding="utf-8")
    result = _run_checker(tmp_path, document)
    details = " ".join(issue["detail"] for issue in json.loads(result.stdout)["issues"])
    if replacement:
        assert result.returncode == 1
        if replacement.startswith("first"):
            expected = "A16RepeatedOwner.first.callback"
        else:
            prefix = "A16RepeatedOwner" if placement == "nested" else "A16RepeatedSecondOwner"
            expected = f"{prefix}.second.handler"
        assert expected in details
    else:
        assert result.returncode == 0, details


@pytest.mark.parametrize("changed", (False, True))
def test_cli_resolves_qualified_class_relative_to_retained_outer_event(
    tmp_path: Path, changed: bool
) -> None:
    """Q1: a qualified lookup stays attached to its bound outer class event."""
    document = _executable_fixture(tmp_path)
    source = tmp_path / "ontologylab/registry.py"
    mutation = "" if not changed else '''
vars(A17RetainedOwner)["marker"].callback = _a17_retained_path.Path(".").exists
assert isinstance(vars(A17RetainedOwner)["marker"].callback(), bool)
'''
    source.write_text(source.read_text(encoding="utf-8") + '''

import pathlib as _a17_retained_path
def a17_retained_callback(self=None): return "source"
class A17Outer:
    class Descriptor:
        def __init__(self, callback): self.callback = callback
        def __get__(self, instance, owner): return self.callback
A17Retained = A17Outer
class A17RetainedOwner:
    marker = A17Retained.Descriptor(a17_retained_callback)
del A17Retained
class A17Outer:
    class Descriptor:
        def __init__(self, handler): self.handler = handler
        def __get__(self, instance, owner): return self.handler
class A17LaterOwner:
    marker = A17Outer.Descriptor(a17_retained_callback)
assert vars(A17RetainedOwner)["marker"].callback() == "source"
assert vars(A17LaterOwner)["marker"].handler() == "source"
''' + mutation, encoding="utf-8")

    result = _run_checker(tmp_path, document)
    details = " ".join(issue["detail"] for issue in json.loads(result.stdout)["issues"])
    if changed:
        assert result.returncode == 1
        assert "A17RetainedOwner.marker.callback" in details
    else:
        assert result.returncode == 0, details


@pytest.mark.parametrize("scope", ("module", "nested"))
@pytest.mark.parametrize("receiver_kind", ("class", "instance"))
@pytest.mark.parametrize("owner_event", ("earlier", "later"))
@pytest.mark.parametrize("changed", (False, True))
def test_cli_binds_method_receivers_to_duplicate_class_definition_events(
    tmp_path: Path, scope: str, receiver_kind: str, owner_event: str, changed: bool
) -> None:
    """Q2: class and instance receivers carry their semantic class event."""
    document = _executable_fixture(tmp_path)
    source = tmp_path / "ontologylab/registry.py"
    if scope == "module":
        declarations = '''
class A17Receiver:
    __slots__ = ("label",)
    token = "first"
    def __init__(self): self.label = "same"
    def event(self): return "first"
A17EarlierReceiver = A17Receiver
class A17Receiver:
    __slots__ = ("label",)
    token = "second"
    def __init__(self): self.label = "same"
    def event(self): return "second"
'''
        earlier = "A17EarlierReceiver"
        later = "A17Receiver"
    else:
        declarations = '''
class A17Scope:
    class Receiver:
        __slots__ = ("label",)
        token = "first"
        def __init__(self): self.label = "same"
        def event(self): return "first"
A17EarlierScope = A17Scope
class A17Scope:
    class Receiver:
        __slots__ = ("label",)
        token = "second"
        def __init__(self): self.label = "same"
        def event(self): return "second"
'''
        earlier = "A17EarlierScope.Receiver"
        later = "A17Scope.Receiver"
    source_class = earlier if owner_event == "earlier" else later
    replacement_class = later if owner_event == "earlier" else earlier
    receiver = source_class if receiver_kind == "class" else f"{source_class}()"
    replacement = replacement_class if receiver_kind == "class" else f"{replacement_class}()"
    source_result = "first" if owner_event == "earlier" else "second"
    changed_result = "second" if owner_event == "earlier" else "first"
    callback_body = "return self.token" if receiver_kind == "class" else "return self.event()"
    mutation = "" if not changed else f'''
vars(A17ReceiverOwner)["marker"].callback = _a17_receiver_types.MethodType(
    a17_receiver_callback, {replacement}
)
assert vars(A17ReceiverOwner)["marker"].callback() == "{changed_result}"
'''
    source.write_text(source.read_text(encoding="utf-8") + f'''

import types as _a17_receiver_types
class A17ReceiverDescriptor:
    def __init__(self, callback): self.callback = callback
    def __get__(self, instance, owner): return self.callback
{declarations}
def a17_receiver_callback(self): {callback_body}
class A17ReceiverOwner:
    marker = A17ReceiverDescriptor(
        _a17_receiver_types.MethodType(a17_receiver_callback, {receiver})
    )
assert vars(A17ReceiverOwner)["marker"].callback() == "{source_result}"
{mutation}
del {"A17EarlierReceiver" if scope == "module" else "A17EarlierScope"}
''', encoding="utf-8")

    result = _run_checker(tmp_path, document)
    details = " ".join(issue["detail"] for issue in json.loads(result.stdout)["issues"])
    if changed:
        assert result.returncode == 1
        assert "A17ReceiverOwner.marker.callback" in details
        assert "method receiver" in details
    else:
        assert result.returncode == 0, details


def test_cli_allows_semantically_identical_duplicate_class_events(tmp_path: Path) -> None:
    """Q2 equivalence: identical represented class bodies have one semantic token."""
    document = _executable_fixture(tmp_path)
    source = tmp_path / "ontologylab/registry.py"
    source.write_text(source.read_text(encoding="utf-8") + '''

import types as _a17_identical_types
class A17IdenticalDescriptor:
    def __init__(self, callback): self.callback = callback
class A17IdenticalReceiver:
    token = "same"
    def event(self): return "same"
A17IdenticalEarlier = A17IdenticalReceiver
class A17IdenticalReceiver:
    token = "same"
    def event(self): return "same"
def a17_identical_receiver_callback(cls): return cls.event(cls)
class A17IdenticalOwner:
    marker = A17IdenticalDescriptor(
        _a17_identical_types.MethodType(a17_identical_receiver_callback, A17IdenticalEarlier)
    )
vars(A17IdenticalOwner)["marker"].callback = _a17_identical_types.MethodType(
    a17_identical_receiver_callback, A17IdenticalReceiver
)
del A17IdenticalEarlier
assert vars(A17IdenticalOwner)["marker"].callback() == "same"
''', encoding="utf-8")

    result = _run_checker(tmp_path, document)
    assert result.returncode == 0, json.loads(result.stdout)["issues"]


@pytest.mark.parametrize(
    ("imports", "receiver"),
    (
        ("from collections import abc", "abc.Mapping"),
        ("from collections import abc as imported_abc", "imported_abc.Mapping"),
        ("from xml.etree import ElementTree", "ElementTree.Element"),
        ("from xml.etree import ElementTree as ET", "ET.Element"),
        ("import collections.abc\nimport collections", "collections.abc.Mapping"),
        ("from pathlib import Path", "Path"),
    ),
)
@pytest.mark.parametrize("changed", (False, True))
def test_cli_resolves_temporal_imported_submodule_prefixes(
    tmp_path: Path, imports: str, receiver: str, changed: bool
) -> None:
    """Q3: imported submodules and loaded dotted prefixes canonicalize temporally."""
    document = _executable_fixture(tmp_path)
    source = tmp_path / "ontologylab/registry.py"
    mutation = "" if not changed else '''
vars(A17ImportOwner)["marker"].callback = _a17_import_types.MethodType(
    a17_import_callback, _a17_import_path.PurePath
)
'''
    source.write_text(source.read_text(encoding="utf-8") + f'''

import pathlib as _a17_import_path
import types as _a17_import_types
{imports}
class A17ImportDescriptor:
    def __init__(self, callback): self.callback = callback
    def __get__(self, instance, owner): return self.callback
def a17_import_callback(cls): return cls.__name__
class A17ImportOwner:
    marker = A17ImportDescriptor(
        _a17_import_types.MethodType(a17_import_callback, {receiver})
    )
{mutation}
''', encoding="utf-8")

    result = _run_checker(tmp_path, document)
    details = " ".join(issue["detail"] for issue in json.loads(result.stdout)["issues"])
    if changed:
        assert result.returncode == 1
        assert "A17ImportOwner.marker.callback has a method receiver that differs" in details
    else:
        assert result.returncode == 0, details


@pytest.mark.parametrize(
    ("body", "expected"),
    (
        ("def event(self): return 'old'\n    def event(self): return 'current'", "current"),
        ("value = 'gone'\n    del value", "current"),
        ("def event(self): return 'current'\n    event_alias = event", "current"),
        ("def event(self): return 'gone'\n    del event", "current"),
        ("value = 'current'\n    value_alias = value", "current"),
        ("def event(self): return 'old'\n    alias = event\n    del alias\n    def event(self): return 'current'", "current"),
        ("value = 'old'\n    alias = value\n    alias = 'current'\n    del value", "current"),
        ("@staticmethod\n    def event(): return 'current'\n    event_alias = event", "current"),
        ("@classmethod\n    def event(cls): return 'current'\n    event_alias = event", "current"),
        ("@property\n    def event(self): return 'current'\n    event_alias = event", "current"),
        ("value = alias = 'current'", "current"),
        ("class Event:\n        token = 'old'\n    class Event:\n        token = 'current'", "current"),
    ),
)
@pytest.mark.parametrize("changed", (False, True))
def test_cli_models_final_static_class_namespace(
    tmp_path: Path, body: str, expected: str, changed: bool
) -> None:
    """C1: source and live class tokens serialize one final binding map."""
    document = _executable_fixture(tmp_path)
    source = tmp_path / "ontologylab/registry.py"
    mutation = "" if not changed else '''
vars(A18NamespaceOwner)["marker"].callback = _a18_namespace_types.MethodType(
    a18_namespace_callback, A18NamespaceChanged
)
assert vars(A18NamespaceOwner)["marker"].callback() == "changed"
'''
    source.write_text(source.read_text(encoding="utf-8") + f'''

import types as _a18_namespace_types
class A18NamespaceDescriptor:
    def __init__(self, callback): self.callback = callback
    def __get__(self, instance, owner): return self.callback
class A18NamespaceReceiver:
    {body}
class A18NamespaceChanged:
    def event(self): return "changed"
def a18_namespace_callback(self):
    event = vars(self).get("event")
    if isinstance(event, staticmethod): return event.__func__()
    if isinstance(event, classmethod): return event.__func__(self)
    if isinstance(event, property): return event.fget(self)
    if event is not None: return event(self)
    alias = vars(self).get("event_alias")
    if isinstance(alias, staticmethod): return alias.__func__()
    if isinstance(alias, classmethod): return alias.__func__(self)
    if isinstance(alias, property): return alias.fget(self)
    if alias is not None and callable(alias): return alias(self)
    nested = vars(self).get("Event")
    if nested is not None: return nested.token
    return vars(self).get("value_alias", vars(self).get("alias", vars(self).get("value", "current")))
class A18NamespaceOwner:
    marker = A18NamespaceDescriptor(
        _a18_namespace_types.MethodType(a18_namespace_callback, A18NamespaceReceiver)
    )
assert vars(A18NamespaceOwner)["marker"].callback() == "{expected}"
{mutation}
''', encoding="utf-8")

    result = _run_checker(tmp_path, document)
    details = " ".join(issue["detail"] for issue in json.loads(result.stdout)["issues"])
    if changed:
        assert result.returncode == 1
        assert "A18NamespaceOwner.marker.callback" in details
    else:
        assert result.returncode == 0, details


@pytest.mark.parametrize("receiver_kind", ("class", "instance"))
@pytest.mark.parametrize("owner_event", ("earlier", "later"))
@pytest.mark.parametrize("changed", (False, True))
def test_cli_binds_class_identity_to_temporal_base_lineage(
    tmp_path: Path, receiver_kind: str, owner_event: str, changed: bool
) -> None:
    """C2: equal child bodies retain the exact recursively represented base event."""
    document = _executable_fixture(tmp_path)
    source = tmp_path / "ontologylab/registry.py"
    earlier = "A18EarlierChild"
    later = "A18Child"
    selected = earlier if owner_event == "earlier" else later
    replacement = later if owner_event == "earlier" else earlier
    receiver = selected if receiver_kind == "class" else f"{selected}()"
    changed_receiver = replacement if receiver_kind == "class" else f"{replacement}()"
    first = "first" if owner_event == "earlier" else "second"
    second = "second" if owner_event == "earlier" else "first"
    callback = "return self.event(self)" if receiver_kind == "class" else "return self.event()"
    mutation = "" if not changed else f'''
vars(A18BaseOwner)["marker"].callback = _a18_base_types.MethodType(
    a18_base_callback, {changed_receiver}
)
assert vars(A18BaseOwner)["marker"].callback() == "{second}"
'''
    source.write_text(source.read_text(encoding="utf-8") + f'''

import types as _a18_base_types
class A18BaseDescriptor:
    def __init__(self, callback): self.callback = callback
    def __get__(self, instance, owner): return self.callback
class A18Base:
    def event(self): return "first"
A18EarlierBase = A18Base
class A18Child(A18EarlierBase):
    pass
A18EarlierChild = A18Child
del A18EarlierBase
class A18Base:
    def event(self): return "second"
A18BaseAlias = A18Base
class A18Child(A18BaseAlias):
    pass
del A18BaseAlias
def a18_base_callback(self): {callback}
class A18BaseOwner:
    marker = A18BaseDescriptor(
        _a18_base_types.MethodType(a18_base_callback, {receiver})
    )
assert vars(A18BaseOwner)["marker"].callback() == "{first}"
{mutation}
del A18EarlierChild
''', encoding="utf-8")

    result = _run_checker(tmp_path, document)
    details = " ".join(issue["detail"] for issue in json.loads(result.stdout)["issues"])
    if changed:
        assert result.returncode == 1
        assert "A18BaseOwner.marker.callback" in details
    else:
        assert result.returncode == 0, details


@pytest.mark.parametrize("changed", (False, True))
def test_cli_preserves_diamond_base_order_in_class_identity(
    tmp_path: Path, changed: bool
) -> None:
    """C2: declared C3 diamond order and aliases are deterministic and load-bearing."""
    document = _executable_fixture(tmp_path)
    source = tmp_path / "ontologylab/registry.py"
    mutation = "" if not changed else '''
vars(A18DiamondOwner)["marker"].callback = _a18_diamond_types.MethodType(
    a18_diamond_callback, A18DiamondChild
)
assert vars(A18DiamondOwner)["marker"].callback() == "right"
'''
    source.write_text(source.read_text(encoding="utf-8") + '''

import types as _a18_diamond_types
class A18DiamondDescriptor:
    def __init__(self, callback): self.callback = callback
    def __get__(self, instance, owner): return self.callback
class A18DiamondRoot: pass
class A18DiamondLeft(A18DiamondRoot):
    def event(self): return "left"
class A18DiamondRight(A18DiamondRoot):
    def event(self): return "right"
A18DiamondAlias = A18DiamondLeft
class A18DiamondChild(A18DiamondAlias, A18DiamondRight): pass
A18EarlierDiamondChild = A18DiamondChild
del A18DiamondAlias
class A18DiamondChild(A18DiamondRight, A18DiamondLeft): pass
def a18_diamond_callback(self): return self.event(self)
class A18DiamondOwner:
    marker = A18DiamondDescriptor(
        _a18_diamond_types.MethodType(a18_diamond_callback, A18EarlierDiamondChild)
    )
assert vars(A18DiamondOwner)["marker"].callback() == "left"
''' + mutation + '''
del A18EarlierDiamondChild
''', encoding="utf-8")
    result = _run_checker(tmp_path, document)
    details = " ".join(issue["detail"] for issue in json.loads(result.stdout)["issues"])
    if changed:
        assert result.returncode == 1
        assert "A18DiamondOwner.marker.callback" in details
    else:
        assert result.returncode == 0, details


@pytest.mark.parametrize("root_import", ("import collections", "import collections as collections"))
@pytest.mark.parametrize("changed", (False, True))
def test_cli_preserves_prefixes_for_redundant_root_import_alias(
    tmp_path: Path, root_import: str, changed: bool
) -> None:
    """I1: `import root as root` preserves known dotted prefixes like root import."""
    document = _executable_fixture(tmp_path)
    source = tmp_path / "ontologylab/registry.py"
    mutation = "" if not changed else '''
vars(A18RootOwner)["marker"].callback = _a18_root_types.MethodType(
    a18_root_callback, _a18_root_path.PurePath
)
'''
    source.write_text(source.read_text(encoding="utf-8") + f'''

import pathlib as _a18_root_path
import types as _a18_root_types
import collections.abc
{root_import}
class A18RootDescriptor:
    def __init__(self, callback): self.callback = callback
    def __get__(self, instance, owner): return self.callback
def a18_root_callback(cls): return cls.__name__
class A18RootOwner:
    marker = A18RootDescriptor(
        _a18_root_types.MethodType(a18_root_callback, collections.abc.Mapping)
    )
{mutation}
''', encoding="utf-8")
    result = _run_checker(tmp_path, document)
    details = " ".join(issue["detail"] for issue in json.loads(result.stdout)["issues"])
    if changed:
        assert result.returncode == 1
        assert "A18RootOwner.marker.callback" in details
    else:
        assert result.returncode == 0, details


@pytest.mark.parametrize("changed", (False, True))
def test_cli_ignores_decorator_generated_class_methods(
    tmp_path: Path, changed: bool
) -> None:
    """C1 boundary: generated methods stay outside direct source namespace semantics."""
    document = _executable_fixture(tmp_path)
    source = tmp_path / "ontologylab/registry.py"
    mutation = "" if not changed else '''
vars(A18GeneratedOwner)["marker"].callback = _a18_generated_types.MethodType(
    a18_generated_callback, A18GeneratedChanged
)
'''
    source.write_text(source.read_text(encoding="utf-8") + '''

import dataclasses as _a18_generated_dataclasses
import types as _a18_generated_types
class A18GeneratedDescriptor:
    def __init__(self, callback): self.callback = callback
    def __get__(self, instance, owner): return self.callback
@_a18_generated_dataclasses.dataclass
class A18GeneratedReceiver:
    value: str = "current"
class A18GeneratedChanged:
    value = "changed"
def a18_generated_callback(cls): return cls.value
class A18GeneratedOwner:
    marker = A18GeneratedDescriptor(
        _a18_generated_types.MethodType(a18_generated_callback, A18GeneratedReceiver)
    )
''' + mutation, encoding="utf-8")
    result = _run_checker(tmp_path, document)
    details = " ".join(issue["detail"] for issue in json.loads(result.stdout)["issues"])
    if changed:
        assert result.returncode == 1
        assert "A18GeneratedOwner.marker.callback" in details
    else:
        assert result.returncode == 0, details


@pytest.mark.parametrize("changed", (False, True))
def test_cli_canonicalizes_external_base_identity(
    tmp_path: Path, changed: bool
) -> None:
    """C2 boundary: external bases stop at canonical module/qualname identity."""
    document = _executable_fixture(tmp_path)
    source = tmp_path / "ontologylab/registry.py"
    mutation = "" if not changed else '''
vars(A18ExternalBaseOwner)["marker"].callback = _a18_external_types.MethodType(
    a18_external_callback, A18ExternalBaseChanged
)
'''
    source.write_text(source.read_text(encoding="utf-8") + '''

import collections.abc
import types as _a18_external_types
class A18ExternalBaseDescriptor:
    def __init__(self, callback): self.callback = callback
    def __get__(self, instance, owner): return self.callback
class A18ExternalBaseReceiver(collections.abc.Mapping): pass
class A18ExternalBaseChanged(collections.abc.Sequence): pass
def a18_external_callback(cls): return cls.__name__
class A18ExternalBaseOwner:
    marker = A18ExternalBaseDescriptor(
        _a18_external_types.MethodType(a18_external_callback, A18ExternalBaseReceiver)
    )
''' + mutation, encoding="utf-8")
    result = _run_checker(tmp_path, document)
    details = " ".join(issue["detail"] for issue in json.loads(result.stdout)["issues"])
    if changed:
        assert result.returncode == 1
        assert "A18ExternalBaseOwner.marker.callback" in details
    else:
        assert result.returncode == 0, details


def test_cli_allows_distinct_alias_after_dotted_root_import(tmp_path: Path) -> None:
    """I1 control: a distinct alias does not disturb the existing root binding."""
    document = _executable_fixture(tmp_path)
    source = tmp_path / "ontologylab/registry.py"
    source.write_text(source.read_text(encoding="utf-8") + '''

import types as _a18_distinct_types
import collections.abc
import collections as c
class A18DistinctDescriptor:
    def __init__(self, callback): self.callback = callback
def a18_distinct_callback(cls): return cls.__name__
class A18DistinctOwner:
    marker = A18DistinctDescriptor(
        _a18_distinct_types.MethodType(a18_distinct_callback, collections.abc.Mapping)
    )
assert c is collections
''', encoding="utf-8")
    result = _run_checker(tmp_path, document)
    assert result.returncode == 0, json.loads(result.stdout)["issues"]


@pytest.mark.parametrize("scope", ("module", "nested"))
@pytest.mark.parametrize("receiver_kind", ("class", "instance"))
@pytest.mark.parametrize("owner_event", ("earlier", "later"))
@pytest.mark.parametrize("changed", (False, True))
def test_cli_binds_class_identity_to_temporal_metaclass_lineage(
    tmp_path: Path,
    scope: str,
    receiver_kind: str,
    owner_event: str,
    changed: bool,
) -> None:
    """M1: equal class bodies retain the exact effective local metaclass event."""
    document = _executable_fixture(tmp_path)
    source = tmp_path / "ontologylab/registry.py"
    if scope == "module":
        declarations = '''
class A19Meta(type):
    def event(cls): return "first"
class A19Receiver(metaclass=A19Meta): pass
A19EarlierReceiver = A19Receiver
class A19Meta(type):
    def event(cls): return "second"
class A19Receiver(metaclass=A19Meta): pass
'''
        earlier = "A19EarlierReceiver"
        later = "A19Receiver"
    else:
        declarations = '''
class A19Scope:
    class Meta(type):
        def event(cls): return "first"
    class Receiver(metaclass=Meta): pass
A19EarlierScope = A19Scope
class A19Scope:
    class Meta(type):
        def event(cls): return "second"
    class Receiver(metaclass=Meta): pass
'''
        earlier = "A19EarlierScope.Receiver"
        later = "A19Scope.Receiver"
    selected = earlier if owner_event == "earlier" else later
    replacement = later if owner_event == "earlier" else earlier
    receiver = selected if receiver_kind == "class" else f"{selected}()"
    changed_receiver = replacement if receiver_kind == "class" else f"{replacement}()"
    first = "first" if owner_event == "earlier" else "second"
    second = "second" if owner_event == "earlier" else "first"
    callback = "return self.event()" if receiver_kind == "class" else "return type(self).event()"
    mutation = "" if not changed else f'''
vars(A19MetaOwner)["marker"].callback = _a19_meta_types.MethodType(
    a19_meta_callback, {changed_receiver}
)
assert vars(A19MetaOwner)["marker"].callback() == "{second}"
'''
    source.write_text(source.read_text(encoding="utf-8") + f'''

import types as _a19_meta_types
class A19MetaDescriptor:
    def __init__(self, callback): self.callback = callback
    def __get__(self, instance, owner): return self.callback
{declarations}
def a19_meta_callback(self): {callback}
class A19MetaOwner:
    marker = A19MetaDescriptor(
        _a19_meta_types.MethodType(a19_meta_callback, {receiver})
    )
assert vars(A19MetaOwner)["marker"].callback() == "{first}"
{mutation}
del {"A19EarlierReceiver" if scope == "module" else "A19EarlierScope"}
''', encoding="utf-8")

    result = _run_checker(tmp_path, document)
    details = " ".join(issue["detail"] for issue in json.loads(result.stdout)["issues"])
    if changed:
        assert result.returncode == 1
        assert "A19MetaOwner.marker.callback" in details
        assert "method receiver" in details
    else:
        assert result.returncode == 0, details


@pytest.mark.parametrize("declaration", ("explicit", "inherited"))
@pytest.mark.parametrize("changed", (False, True))
def test_cli_canonicalizes_external_effective_metaclasses(
    tmp_path: Path, declaration: str, changed: bool
) -> None:
    """M1 boundary: external ABCMeta and default type stop at canonical identity."""
    document = _executable_fixture(tmp_path)
    source = tmp_path / "ontologylab/registry.py"
    receiver = (
        "class A19ExternalMetaReceiver(metaclass=_a19_external_meta_abc.ABCMeta): pass"
        if declaration == "explicit"
        else "class A19ExternalMetaReceiver(_a19_external_meta_abc.ABC): pass"
    )
    mutation = "" if not changed else '''
vars(A19ExternalMetaOwner)["marker"].callback = _a19_external_meta_types.MethodType(
    a19_external_meta_callback, A19DefaultMetaReceiver
)
'''
    source.write_text(source.read_text(encoding="utf-8") + f'''

import abc as _a19_external_meta_abc
import types as _a19_external_meta_types
class A19ExternalMetaDescriptor:
    def __init__(self, callback): self.callback = callback
    def __get__(self, instance, owner): return self.callback
{receiver}
class A19DefaultMetaReceiver: pass
def a19_external_meta_callback(cls):
    return type(cls) is _a19_external_meta_abc.ABCMeta
class A19ExternalMetaOwner:
    marker = A19ExternalMetaDescriptor(
        _a19_external_meta_types.MethodType(
            a19_external_meta_callback, A19ExternalMetaReceiver
        )
    )
assert vars(A19ExternalMetaOwner)["marker"].callback() is True
{mutation}
''', encoding="utf-8")

    result = _run_checker(tmp_path, document)
    details = " ".join(issue["detail"] for issue in json.loads(result.stdout)["issues"])
    if changed:
        assert result.returncode == 1
        assert "A19ExternalMetaOwner.marker.callback" in details
    else:
        assert result.returncode == 0, details


def test_source_external_metaclass_compatibility_never_dispatches_subclasscheck(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """G010: concrete external ancestry, not subclass protocols, selects the metaclass."""
    module_name = "g010_hostile_compatible_meta"
    module = types.ModuleType(module_name)
    exec(
        '''
calls = []
class SentinelMeta(type):
    def __subclasscheck__(cls, candidate):
        calls.append((cls, candidate))
        raise RuntimeError("custom subclasscheck dispatched")
class BaseMeta(type, metaclass=SentinelMeta): pass
class DerivedMeta(BaseMeta): pass
class Base(metaclass=BaseMeta): pass
''',
        vars(module),
    )
    monkeypatch.setitem(sys.modules, module_name, module)
    exec(
        f"import {module_name} as ext\n"
        "class Receiver(ext.Base, metaclass=ext.DerivedMeta): pass\n",
        {},
    )
    semantics = _shipped_helpers(
        "_frame", "_constant_bytes", "_source_class_semantics"
    )["_source_class_semantics"]

    encoded = semantics(
        ast.parse(
            f"import {module_name} as ext\n"
            "class Receiver(ext.Base, metaclass=ext.DerivedMeta): pass\n"
        )
    )

    assert encoded[("Receiver", 2)].startswith(b"K")
    assert vars(module)["calls"] == []


def test_source_external_metaclass_conflict_fails_closed_without_subclasscheck(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """G010: unrelated hostile external metaclasses stay unsupported without dispatch."""
    module_name = "g010_hostile_conflicting_meta"
    module = types.ModuleType(module_name)
    exec(
        '''
calls = []
class SentinelMeta(type):
    def __subclasscheck__(cls, candidate):
        calls.append((cls, candidate))
        raise RuntimeError("custom subclasscheck dispatched")
class LeftMeta(type, metaclass=SentinelMeta): pass
class RightMeta(type, metaclass=SentinelMeta): pass
class LeftBase(metaclass=LeftMeta): pass
''',
        vars(module),
    )
    monkeypatch.setitem(sys.modules, module_name, module)
    semantics = _shipped_helpers(
        "_frame", "_constant_bytes", "_source_class_semantics"
    )["_source_class_semantics"]

    encoded = semantics(
        ast.parse(
            f"import {module_name} as ext\n"
            "class Receiver(ext.LeftBase, metaclass=ext.RightMeta): pass\n"
        )
    )

    assert encoded[("Receiver", 2)].endswith(b"unsupported-lineage")
    assert vars(module)["calls"] == []


def test_cli_accepts_compatible_hostile_external_metaclasses_without_subclasscheck(
    tmp_path: Path,
) -> None:
    """G010 real surface: valid product identity is receipted with an empty hook log."""
    document = _executable_fixture(tmp_path)
    hook_log = tmp_path / "subclasscheck.log"
    hook_log.write_text("", encoding="utf-8")
    (tmp_path / "ontologylab/g010_hostile_meta.py").write_text(
        '''
from pathlib import Path
HOOK_LOG = Path(__file__).resolve().parents[1] / "subclasscheck.log"
class SentinelMeta(type):
    def __subclasscheck__(cls, candidate):
        with HOOK_LOG.open("a", encoding="utf-8") as handle:
            handle.write("called\\n")
        raise RuntimeError("custom subclasscheck dispatched")
class BaseMeta(type, metaclass=SentinelMeta): pass
class DerivedMeta(BaseMeta): pass
class Base(metaclass=BaseMeta): pass
''',
        encoding="utf-8",
    )
    source = tmp_path / "ontologylab/registry.py"
    source.write_text(
        source.read_text(encoding="utf-8")
        + '''

import ontologylab.g010_hostile_meta as _g010_hostile_meta
class G010CompatibleReceiver(
    _g010_hostile_meta.Base, metaclass=_g010_hostile_meta.DerivedMeta
): pass
assert type(G010CompatibleReceiver) is _g010_hostile_meta.DerivedMeta
''',
        encoding="utf-8",
    )

    result = _run_checker(tmp_path, document)

    assert hook_log.read_text(encoding="utf-8") == ""
    assert result.returncode == 0, json.loads(result.stdout)["issues"]
    assert json.loads(result.stdout)["ok"] is True
    assert "EVIDENCE: 13 canonical pytest nodes passed" in result.stderr


def test_cli_applies_python_metaclass_compatibility_rule(tmp_path: Path) -> None:
    """M1: an explicit local metaclass may refine the exact base metaclass event."""
    document = _executable_fixture(tmp_path)
    source = tmp_path / "ontologylab/registry.py"
    source.write_text(source.read_text(encoding="utf-8") + '''

import types as _a19_compatible_meta_types
class A19CompatibleBaseMeta(type): pass
class A19CompatibleDerivedMeta(A19CompatibleBaseMeta):
    def event(cls): return "derived"
class A19CompatibleBase(metaclass=A19CompatibleBaseMeta): pass
class A19CompatibleReceiver(
    A19CompatibleBase, metaclass=A19CompatibleDerivedMeta
): pass
class A19CompatibleDescriptor:
    def __init__(self, callback): self.callback = callback
    def __get__(self, instance, owner): return self.callback
def a19_compatible_callback(cls): return cls.event()
class A19CompatibleOwner:
    marker = A19CompatibleDescriptor(
        _a19_compatible_meta_types.MethodType(
            a19_compatible_callback, A19CompatibleReceiver
        )
    )
assert vars(A19CompatibleOwner)["marker"].callback() == "derived"
''', encoding="utf-8")

    result = _run_checker(tmp_path, document)
    assert result.returncode == 0, json.loads(result.stdout)["issues"]


def test_source_metaclass_conflicts_fail_closed() -> None:
    """M1: incompatible static metaclass candidates never acquire a guessed token."""
    semantics = _shipped_helpers(
        "_frame", "_constant_bytes", "_source_class_semantics"
    )["_source_class_semantics"]
    tree = ast.parse('''
class Left(type): pass
class Right(type): pass
class Base(metaclass=Left): pass
class Receiver(Base, metaclass=Right): pass
''')
    assert semantics(tree)[("Receiver", 5)].endswith(b"unsupported-lineage")


def test_cli_fails_closed_for_dynamic_metaclass_expression(tmp_path: Path) -> None:
    """M1 boundary: an executable but unsupported metaclass expression is not guessed."""
    document = _executable_fixture(tmp_path)
    source = tmp_path / "ontologylab/registry.py"
    source.write_text(source.read_text(encoding="utf-8") + '''

import types as _a19_dynamic_meta_types
def a19_choose_meta(): return type
class A19DynamicMetaReceiver(metaclass=a19_choose_meta()): pass
class A19DynamicMetaDescriptor:
    def __init__(self, callback): self.callback = callback
    def __get__(self, instance, owner): return self.callback
def a19_dynamic_meta_callback(cls): return cls.__name__
class A19DynamicMetaOwner:
    marker = A19DynamicMetaDescriptor(
        _a19_dynamic_meta_types.MethodType(
            a19_dynamic_meta_callback, A19DynamicMetaReceiver
        )
    )
''', encoding="utf-8")

    result = _run_checker(tmp_path, document)
    details = " ".join(issue["detail"] for issue in json.loads(result.stdout)["issues"])
    assert result.returncode == 1
    assert "A19DynamicMetaOwner.marker.callback" in details
    assert "method receiver" in details


@pytest.mark.parametrize("changed", (False, True))
def test_cli_class_encoding_never_dispatches_metaclass_descriptors(
    tmp_path: Path, changed: bool
) -> None:
    """M2: nested classes, bases, identity, and lineage use concrete type descriptors."""
    document = _executable_fixture(tmp_path)
    source = tmp_path / "ontologylab/registry.py"
    mutation = "" if not changed else '''
vars(A19SafeOwner)["marker"].callback = _a19_safe_types.MethodType(
    a19_safe_callback, A19SafeChanged
)
'''
    source.write_text(source.read_text(encoding="utf-8") + '''

import types as _a19_safe_types
class A19SafeMeta(type):
    calls = []
    @property
    def __module__(cls):
        type.__getattribute__(A19SafeMeta, "calls").append("property:__module__")
        raise RuntimeError("__module__")
    @property
    def __bases__(cls):
        type.__getattribute__(A19SafeMeta, "calls").append("property:__bases__")
        raise RuntimeError("__bases__")
    def __getattribute__(cls, name):
        if name in {"__module__", "__qualname__", "__bases__", "__dict__"}:
            type.__getattribute__(A19SafeMeta, "calls").append("getattribute:" + name)
            raise RuntimeError(name)
        return type.__getattribute__(cls, name)
class A19SafeBase(metaclass=A19SafeMeta):
    token = "base"
class A19SafeReceiver(A19SafeBase, metaclass=A19SafeMeta):
    class Nested:
        token = "nested"
    token = "source"
class A19SafeChanged:
    token = "changed"
class A19SafeDescriptor:
    def __init__(self, callback): self.callback = callback
    def __get__(self, instance, owner): return self.callback
def a19_safe_callback(cls): return vars(cls).get("token")
class A19SafeOwner:
    marker = A19SafeDescriptor(
        _a19_safe_types.MethodType(a19_safe_callback, A19SafeReceiver)
    )
type.__getattribute__(A19SafeMeta, "calls").clear()
''' + mutation, encoding="utf-8")

    result = _run_checker(tmp_path, document)
    details = " ".join(issue["detail"] for issue in json.loads(result.stdout)["issues"])
    if changed:
        assert result.returncode == 1
        assert "A19SafeOwner.marker.callback" in details
    else:
        assert result.returncode == 0, details


def test_class_lineage_never_invokes_custom_metaclass_getters() -> None:
    """C2 safety: static namespace and base traversal bypass metaclass lookup."""
    encode = _shipped_helpers("_frame", "_constant_bytes", "_class_definition_bytes")[
        "_class_definition_bytes"
    ]

    class Meta(type):
        calls = []

        @property
        def __module__(self):
            type.__getattribute__(Meta, "calls").append("property:__module__")
            raise RuntimeError("__module__")

        @property
        def __bases__(self):
            type.__getattribute__(Meta, "calls").append("property:__bases__")
            raise RuntimeError("__bases__")

        def __getattribute__(self, name):
            type.__getattribute__(Meta, "calls").append("getattribute:" + name)
            raise RuntimeError(name)

    class Base(metaclass=Meta):
        token = "base"

    class Receiver(Base, metaclass=Meta):
        token = "receiver"

    type.__getattribute__(Meta, "calls").clear()
    assert encode(Receiver).startswith(b"K")
    assert type.__getattribute__(Meta, "calls") == []


def test_receiver_bytes_never_invokes_custom_getattribute() -> None:
    """S7 direct owner: concrete descriptors are opened without receiver lookup."""
    encode = _shipped_helpers("_frame", "_constant_bytes", "_receiver_bytes")[
        "_receiver_bytes"
    ]

    class Receiver:
        __slots__ = ("label",)
        calls = 0

        def __init__(self):
            object.__setattr__(self, "label", "source")

        def __getattribute__(self, name):
            Receiver.calls += 1
            raise RuntimeError(name)

    token = encode(Receiver())
    assert token.startswith(b"I")
    assert Receiver.calls == 0


@pytest.mark.parametrize("changed", (False, True))
def test_cli_receiver_state_never_invokes_custom_getattribute(
    tmp_path: Path, changed: bool
) -> None:
    """S7 real surface: clean and changed state use only concrete CPython descriptors."""
    document = _executable_fixture(tmp_path)
    source = tmp_path / "ontologylab/registry.py"
    mutation = "" if not changed else '''
_a15_getattr_changed = A15GetattrReceiver("leftover")
vars(A15GetattrOwner)["marker"].callback = _a15_getattr_types.MethodType(
    a15_getattr_callback, _a15_getattr_changed
)
'''
    source.write_text(
        source.read_text(encoding="utf-8")
        + '''

import types as _a15_getattr_types
class A15GetattrDescriptor:
    def __init__(self, callback): self.callback = callback
    def __get__(self, instance, owner): return self.callback
class A15GetattrReceiver:
    __slots__ = ("label",)
    calls = 0
    def __init__(self, label="source"): object.__setattr__(self, "label", label)
    def __getattribute__(self, name):
        type(self).calls += 1
        raise RuntimeError(name)
def a15_getattr_callback(self): return object.__getattribute__(self, "label")
class A15GetattrOwner:
    marker = A15GetattrDescriptor(
        _a15_getattr_types.MethodType(a15_getattr_callback, A15GetattrReceiver())
    )
'''
        + mutation,
        encoding="utf-8",
    )

    result = _run_checker(tmp_path, document)
    payload = json.loads(result.stdout) if result.stdout else {"issues": []}
    if changed:
        assert result.returncode == 1
        assert "A15GetattrOwner.marker.callback has a method receiver state that differs" in " ".join(
            issue["detail"] for issue in payload["issues"]
        ), result.stderr
    else:
        assert result.returncode == 0, result.stderr or payload["issues"]


def test_cli_fails_closed_for_unsupported_and_cyclic_receiver_state(tmp_path: Path) -> None:
    """S1/S7 boundary: dynamic source init and cyclic live state never become expected."""
    document = _executable_fixture(tmp_path)
    source = tmp_path / "ontologylab/registry.py"
    source.write_text(
        source.read_text(encoding="utf-8")
        + '''

import types as _a15_unsupported_types
def a15_dynamic_value(): return "source"
class A15UnsupportedDescriptor:
    def __init__(self, callback): self.callback = callback
    def __get__(self, instance, owner): return self.callback
class A15UnsupportedReceiver:
    def __init__(self): self.label = a15_dynamic_value()
class A15CyclicReceiver:
    def __init__(self): self.label = "source"
def a15_unsupported_callback(self): return self.label
class A15UnsupportedOwner:
    dynamic = A15UnsupportedDescriptor(_a15_unsupported_types.MethodType(a15_unsupported_callback, A15UnsupportedReceiver()))
    cyclic = A15UnsupportedDescriptor(_a15_unsupported_types.MethodType(a15_unsupported_callback, A15CyclicReceiver()))
_a15_cycle = A15CyclicReceiver()
_a15_cycle.label = _a15_cycle.__dict__
vars(A15UnsupportedOwner)["cyclic"].callback = _a15_unsupported_types.MethodType(a15_unsupported_callback, _a15_cycle)
''',
        encoding="utf-8",
    )

    result = _run_checker(tmp_path, document)

    details = " ".join(issue["detail"] for issue in json.loads(result.stdout)["issues"])
    assert "A15UnsupportedOwner.dynamic.callback" in details
    assert "A15UnsupportedOwner.cyclic.callback has unsupported method receiver state" in details
    assert result.returncode == 1


def test_cli_rejects_a_callable_rebound_inside_a_custom_descriptor(
    tmp_path: Path,
) -> None:
    """A descriptor's ordinary instance state is part of its product binding."""
    document = _executable_fixture(tmp_path)
    source = tmp_path / "ontologylab/registry.py"
    source.write_text(
        source.read_text(encoding="utf-8")
        + "\n\nclass A10Descriptor:\n"
        "    def __init__(self, callback):\n"
        "        self.callback = callback\n\n"
        "    def __get__(self, instance, owner):\n"
        "        return self.callback.__get__(instance, owner)\n\n\n"
        "class A10DescriptorOwner:\n"
        "    @A10Descriptor\n"
        "    def marker(self):\n"
        "        return 'source'\n\n\n"
        "_a10_descriptor_ns = {'__name__': __name__}\n"
        "exec(compile(\"def marker(self): return 'leftover'\", \"<string>\", \"exec\"), "
        "_a10_descriptor_ns)\n"
        "vars(A10DescriptorOwner)['marker'].callback = _a10_descriptor_ns['marker']\n",
        encoding="utf-8",
    )

    result = _run_checker(tmp_path, document)

    payload = json.loads(result.stdout)
    assert result.returncode == 1
    assert payload["ok"] is False
    details = " ".join(issue["detail"] for issue in payload["issues"])
    assert (
        "A10DescriptorOwner.marker.callback was compiled from <string>" in details
    ), details


def test_cli_accepts_a_clean_custom_descriptor(tmp_path: Path) -> None:
    """Static descriptor-state traversal does not reject source-declared callbacks."""
    document = _executable_fixture(tmp_path)
    source = tmp_path / "ontologylab/registry.py"
    source.write_text(
        source.read_text(encoding="utf-8")
        + "\n\nclass A10CleanDescriptor:\n"
        "    def __init__(self, callback):\n"
        "        self.callback = callback\n\n"
        "    def __get__(self, instance, owner):\n"
        "        return self.callback.__get__(instance, owner)\n\n\n"
        "class A10CleanDescriptorOwner:\n"
        "    @A10CleanDescriptor\n"
        "    def marker(self):\n"
        "        return 'source'\n",
        encoding="utf-8",
    )

    result = _run_checker(tmp_path, document)

    payload = json.loads(result.stdout)
    assert result.returncode == 0, payload["issues"]
    assert payload["ok"] is True
    assert payload["issues"] == []
    assert "EVIDENCE: 13 canonical pytest nodes passed" in result.stderr


@pytest.mark.parametrize("container", ("set", "frozenset"))
def test_cli_rejects_a_callable_rebound_inside_descriptor_set_state(
    tmp_path: Path, container: str
) -> None:
    """Exact set and frozenset are part of statically owned descriptor state."""
    document = _executable_fixture(tmp_path)
    source = tmp_path / "ontologylab/registry.py"
    source.write_text(
        source.read_text(encoding="utf-8")
        + "\n\nclass A11SetDescriptor:\n"
        "    def __init__(self, callback):\n"
        f"        self.callbacks = {container}({{callback}})\n\n"
        "    def __get__(self, instance, owner):\n"
        "        return next(iter(self.callbacks)).__get__(instance, owner)\n\n\n"
        "class A11SetOwner:\n"
        "    @A11SetDescriptor\n"
        "    def marker(self):\n"
        "        return 'source'\n\n\n"
        "_a11_set_ns = {'__name__': __name__}\n"
        "exec(compile(\"def marker(self): return 'leftover'\", \"<string>\", \"exec\"), "
        "_a11_set_ns)\n"
        f"vars(A11SetOwner)['marker'].callbacks = {container}({{_a11_set_ns['marker']}})\n",
        encoding="utf-8",
    )

    result = _run_checker(tmp_path, document)

    payload = json.loads(result.stdout)
    assert result.returncode == 1
    assert payload["ok"] is False
    details = " ".join(issue["detail"] for issue in payload["issues"])
    assert "A11SetOwner.marker.callbacks" in details, details
    assert "was compiled from <string>" in details, details


@pytest.mark.parametrize(
    ("container", "hash_seed"),
    (("set", "1"), ("set", "271"), ("frozenset", "1"), ("frozenset", "271")),
)
def test_cli_accepts_clean_descriptor_set_state_across_hash_seeds(
    tmp_path: Path, container: str, hash_seed: str
) -> None:
    """Canonical traversal is clean and independent of hash iteration order."""
    document = _executable_fixture(tmp_path)
    source = tmp_path / "ontologylab/registry.py"
    source.write_text(
        source.read_text(encoding="utf-8")
        + "\n\nclass A11CleanSetDescriptor:\n"
        "    def __init__(self, callback):\n"
        f"        self.callbacks = {container}({{callback}})\n\n"
        "    def __get__(self, instance, owner):\n"
        "        return next(iter(self.callbacks)).__get__(instance, owner)\n\n\n"
        "class A11CleanSetOwner:\n"
        "    @A11CleanSetDescriptor\n"
        "    def marker(self):\n"
        "        return 'source'\n",
        encoding="utf-8",
    )
    environment = {**os.environ, "PYTHONHASHSEED": hash_seed}

    result = _run_checker(tmp_path, document, environment=environment)

    payload = json.loads(result.stdout)
    assert result.returncode == 0, payload["issues"]
    assert payload["ok"] is True
    assert payload["issues"] == []


def test_descriptor_container_paths_are_canonical_and_unambiguous() -> None:
    """Same-repr keys and members receive stable, distinct non-repr path tokens."""
    walker = _shipped_helpers(
        "_frame",
        "_constant_bytes",
        "_code_bytes",
        "code_fingerprint",
        "_descriptor_value_bytes",
        "_descriptor_members",
        "live_code_objects",
        "_code_objects_of",
    )["live_code_objects"]
    module = types.ModuleType("descriptor_tokens")
    exec(
        compile(
            "import struct\n"
            "class Descriptor:\n"
            "    def __init__(self, first, second):\n"
            "        one = struct.unpack('>d', bytes.fromhex('7ff8000000000000'))[0]\n"
            "        two = struct.unpack('>d', bytes.fromhex('7ff8000000000000'))[0]\n"
            "        self.mapping = {one: first, two: second}\n"
            "        self.members = {first, second}\n"
            "    def __get__(self, instance, owner): raise AssertionError\n"
            "class Owner:\n"
            "    def first(self): return 1\n"
            "    def second(self): return 2\n"
            "    marker = Descriptor(first, second)\n",
            "descriptor_tokens.py",
            "exec",
        ),
        module.__dict__,
    )

    paths = [
        binding
        for binding, source_binding, _code, _function in walker(module)
        if source_binding == "Owner.marker"
    ]

    mapping_paths = [path for path in paths if ".mapping[" in path]
    member_paths = [path for path in paths if ".members{" in path]
    assert len(mapping_paths) == len(set(mapping_paths)) == 2
    assert len(member_paths) == len(set(member_paths)) == 2
    assert all("nan" not in path for path in mapping_paths)


def test_cli_accepts_a_source_declared_descriptor_alias(tmp_path: Path) -> None:
    """A class-body alias retains the callback declaration's original binding."""
    document = _executable_fixture(tmp_path)
    source = tmp_path / "ontologylab/registry.py"
    source.write_text(
        source.read_text(encoding="utf-8")
        + "\n\nclass A11AliasDescriptor:\n"
        "    def __init__(self, callback): self.callback = callback\n"
        "    def __get__(self, instance, owner):\n"
        "        return self.callback.__get__(instance, owner)\n\n"
        "class A11AliasOwner:\n"
        "    @A11AliasDescriptor\n"
        "    def marker(self): return 'source'\n"
        "    alias = marker\n",
        encoding="utf-8",
    )

    result = _run_checker(tmp_path, document)

    payload = json.loads(result.stdout)
    assert result.returncode == 0, payload["issues"]
    assert payload["ok"] is True
    assert payload["issues"] == []


def test_cli_rejects_a_rebound_source_declared_descriptor_alias(tmp_path: Path) -> None:
    """Source alias structure does not excuse a callback replaced after declaration."""
    document = _executable_fixture(tmp_path)
    source = tmp_path / "ontologylab/registry.py"
    source.write_text(
        source.read_text(encoding="utf-8")
        + "\n\nclass A11BadAliasDescriptor:\n"
        "    def __init__(self, callback): self.callback = callback\n"
        "    def __get__(self, instance, owner):\n"
        "        return self.callback.__get__(instance, owner)\n\n"
        "class A11BadAliasOwner:\n"
        "    @A11BadAliasDescriptor\n"
        "    def marker(self): return 'source'\n"
        "    alias = marker\n\n"
        "_a11_alias_ns = {'__name__': __name__}\n"
        "exec(compile(\"def marker(self): return 'leftover'\", '<string>', 'exec'), "
        "_a11_alias_ns)\n"
        "vars(A11BadAliasOwner)['alias'].callback = _a11_alias_ns['marker']\n",
        encoding="utf-8",
    )

    result = _run_checker(tmp_path, document)

    payload = json.loads(result.stdout)
    assert result.returncode == 1
    assert payload["ok"] is False
    details = " ".join(issue["detail"] for issue in payload["issues"])
    assert "A11BadAliasOwner.alias.callback was compiled from <string>" in details, details


def test_descriptor_state_traversal_is_static_nested_and_cycle_safe() -> None:
    """Owned dict/list state is followed without invoking descriptor behavior."""
    walker = _shipped_helpers(
        "_frame",
        "_constant_bytes",
        "_code_bytes",
        "_descriptor_value_bytes",
        "_descriptor_members",
        "live_code_objects",
        "_code_objects_of",
    )["live_code_objects"]
    module = types.ModuleType("descriptor_demo")
    exec(
        compile(
            "class Descriptor:\n"
            "    def __init__(self, callback):\n"
            "        state = {'callbacks': [callback]}\n"
            "        state['cycle'] = state\n"
            "        self.state = state\n"
            "    def __get__(self, instance, owner):\n"
            "        raise AssertionError('descriptor behavior was invoked')\n"
            "class Owner:\n"
            "    @Descriptor\n"
            "    def marker(self): return 'source'\n",
            "descriptor_demo.py",
            "exec",
        ),
        module.__dict__,
    )

    found = list(walker(module))

    assert any(
        binding.startswith("Owner.marker.state[key:")
        and binding.endswith("][0]")
        and source_binding == "Owner.marker"
        and code.co_qualname == "Owner.marker"
        for binding, source_binding, code, _function in found
    )


def test_cli_rejects_a_product_binding_compiled_from_synthetic_source(
    tmp_path: Path,
) -> None:
    """An ordinary leftover bound from `compile(..., "<string>", ...)` is not exempt.

    Every synthetic origin used to be skipped, which was far wider than the `@dataclass`
    dunders it was meant to cover: a product name rebound to `exec`/`eval`/`compile` output
    inherited the same pass. The exemption is now the specific generated dunders, and
    anything else claiming a synthetic origin is reported under its binding path.
    """
    document = _executable_fixture(tmp_path)
    normalization = tmp_path / "ontologylab/normalization.py"
    pristine = normalization.read_text(encoding="utf-8")
    _mutate_normalization(tmp_path)
    normalization.write_text(
        normalization.read_text(encoding="utf-8")
        + "\n\nimport sys as _sys\n\n"
        'if "--junitxml" in _sys.argv:\n'
        "    _g = dict(globals())\n"
        '    exec(compile(%r, "<string>", "exec"), _g)\n'
        "    normalize_proposal = _g[\"normalize_proposal\"]\n" % pristine,
        encoding="utf-8",
    )

    result = _run_checker(tmp_path, document)

    payload = json.loads(result.stdout)
    assert result.returncode == 1
    assert payload["ok"] is False
    details = " ".join(issue["detail"] for issue in payload["issues"])
    assert "normalize_proposal was compiled from <string>" in details, details



def test_cli_rejects_a_rebound_module_level_lookup_table(tmp_path: Path) -> None:
    """A swapped constant is the same accident as a swapped function.

    The code-object rule binds what runs; it says nothing about the data that code reads.
    227 module-level values in the loaded product modules were bound by neither rule. This
    rebinding is deliberately behaviour-neutral -- the extra member changes no outcome, so
    every canonical node still passes -- which means only the data rule can report it.
    Values assigned from a call or an attribute lookup remain unbound by construction and
    are declared in the spec rather than left to be discovered.
    """
    document = _executable_fixture(tmp_path)
    normalization = tmp_path / "ontologylab/normalization.py"
    normalization.write_text(
        normalization.read_text(encoding="utf-8")
        + "\n\nimport sys as _sys\n\n"
        'if "--junitxml" in _sys.argv:\n'
        '    ORGANISM_ENTITY_TYPES = frozenset({"Crop", "Pathogen", "Pest", "Weed", "Extra"})\n',
        encoding="utf-8",
    )

    result = _run_checker(tmp_path, document)

    payload = json.loads(result.stdout)
    assert result.returncode == 1
    assert payload["ok"] is False
    (issue,) = payload["issues"]
    assert issue["detail"] == (
        "product code the bodies called is not what its own source compiles to: "
        "['ontologylab/normalization.py::ORGANISM_ENTITY_TYPES does not hold the value "
        "this file assigns']"
    )



def test_cli_rejects_a_rebound_class_that_hides_a_gutted_method(tmp_path: Path) -> None:
    """A duplicated or rebound *class* is as visible as a rebound function.

    Identity used to be enumerated from module-level attributes carrying `__code__`, so every
    method of every class sat outside the audit -- 726 of them in this product, measured. A
    bad merge that leaves a second copy of a class, or a debugging leftover that rebinds one,
    is an ordinary accident, and it was sufficient: with `RegistryCache.resolve_with_status`
    gutted and the class rebound to a pre-mutation copy while audited, ground truth was six
    failing tests and the gate printed its receipt. Identity is now bound per qualified name
    over every code object a module exposes, methods included.
    """
    document = _executable_fixture(tmp_path)
    pristine = _mutate_registry_method(tmp_path)
    registry = tmp_path / "ontologylab/registry.py"
    registry.write_text(
        registry.read_text(encoding="utf-8")
        + "\n\nimport sys as _sys\n\n"
        'if "--junitxml" in _sys.argv:\n'
        "    _ns = dict(globals())\n"
        "    exec(compile(%r, __file__, \"exec\"), _ns)\n"
        '    RegistryCache = _ns["RegistryCache"]\n' % pristine,
        encoding="utf-8",
    )

    result = _run_checker(tmp_path, document)

    payload = json.loads(result.stdout)
    assert result.returncode == 1
    assert payload["ok"] is False
    (issue,) = payload["issues"]
    assert issue["code"] == "evidence_execution"
    assert issue["detail"] == (
        "product code the bodies called is not what its own source compiles to: "
        "['ontologylab/registry.py::RegistryCache.resolve_with_status is not compiled "
        "from this file under that name']"
    )


def test_cli_rejects_a_function_rebound_to_a_sibling_in_the_same_file(
    tmp_path: Path,
) -> None:
    """Identity is bound per name, not by "appears somewhere in the file".

    The check used to ask whether the executed bytecode was among the code objects the file
    could produce, anywhere. A function rebound to a *different* function defined in the same
    file therefore satisfied it. Nothing here is behaviourally broken on its own -- the decoy
    is a pass-through -- so the report has to come from the identity rule.
    """
    document = _executable_fixture(tmp_path)
    normalization = tmp_path / "ontologylab/normalization.py"
    normalization.write_text(
        normalization.read_text(encoding="utf-8")
        + "\n\ndef _decoy(proposal, cache, moa_cache=None):\n"
        "    return proposal\n\n\n"
        "import sys as _sys\n\n"
        'if "--junitxml" in _sys.argv:\n'
        "    normalize_proposal = _decoy\n",
        encoding="utf-8",
    )

    result = _run_checker(tmp_path, document)

    payload = json.loads(result.stdout)
    assert result.returncode == 1
    assert payload["ok"] is False
    details = {issue["detail"] for issue in payload["issues"]}
    assert any(
        "ontologylab/normalization.py::normalize_proposal is not compiled from this file "
        "under that name" in detail
        for detail in details
    ), details


def test_cli_rejects_code_executed_under_a_filename_that_does_not_exist(
    tmp_path: Path,
) -> None:
    """A `.pyc` with no adjacent source is undeclared code, and is named as such.

    Two inferences behind the reach audit did not hold. Loading a `.pyc` fires no `compile`
    event, and `module_from_spec` never registers in `sys.modules`, so neither the hook's
    compile record nor a module walk saw it. Executing it does fire `exec`, and the filename
    that code object claims does not exist on disk -- which is the reportable fact.
    """
    document = _executable_fixture(tmp_path)
    source = tmp_path / "orphan_helper.py"
    source.write_text("def stub():\n    return None\n", encoding="utf-8")
    py_compile.compile(
        str(source), cfile=str(tmp_path / "orphan_helper.pyc"), doraise=True
    )
    source.unlink()
    evidence = tmp_path / "tests/test_registry.py"
    marker = "from __future__ import annotations\n"
    evidence.write_text(
        evidence.read_text(encoding="utf-8").replace(
            marker,
            marker
            + "\nimport importlib.util as _u\nimport pathlib as _pl\n"
            "_spec = _u.spec_from_file_location(\n"
            "    'orphan_helper', str(_pl.Path(__file__).parents[1] / 'orphan_helper.pyc')\n"
            ")\n_mod = _u.module_from_spec(_spec)\n_spec.loader.exec_module(_mod)\n",
            1,
        ),
        encoding="utf-8",
    )
    checker = _checker_with_refreshed_digests(tmp_path)

    result = _run_checker(tmp_path, document, checker=str(checker))

    payload = json.loads(result.stdout)
    assert result.returncode == 1
    assert payload["ok"] is False
    (issue,) = payload["issues"]
    assert issue["detail"] == (
        "unaudited repository modules on the evidence path: "
        "['orphan_helper.py: claimed source is absent']"
    )



def test_cli_rejects_a_module_that_declines_to_say_where_it_came_from(
    tmp_path: Path,
) -> None:
    """A loader that supplies no origin is not thereby exempt.

    The identity check keys on a module's `__file__` or its spec origin. A substituting
    loader that sets neither would previously fall out of every audit silently, so an
    unlocatable product module is now reported rather than skipped.
    """
    document = _executable_fixture(tmp_path)
    models = tmp_path / "ontologylab/models.py"
    models.write_text(
        models.read_text(encoding="utf-8")
        + "\n\nimport sys as _sys\n\n"
        "if '--junitxml' in _sys.argv:\n"
        "    import types as _t\n"
        "    _ghost = _t.ModuleType('ontologylab.ghost_helper')\n"
        "    _ghost.__spec__ = None\n"
        "    def _stub():\n"
        "        return None\n"
        "    _stub.__module__ = 'ontologylab.ghost_helper'\n"
        "    _ghost.helper = _stub\n"
        "    _sys.modules['ontologylab.ghost_helper'] = _ghost\n",
        encoding="utf-8",
    )

    result = _run_checker(tmp_path, document)

    payload = json.loads(result.stdout)
    assert result.returncode == 1
    assert payload["ok"] is False
    (issue,) = payload["issues"]
    assert "no declared origin" in issue["detail"]



@pytest.mark.parametrize(
    "evasion",
    (
        pytest.param(
            "import sys as _s\nimport sneaky_helper as _sh\ndel _s.modules['sneaky_helper']\n",
            id="deleted-from-sys-modules-after-import",
        ),
        pytest.param(
            "import pathlib as _p\n_ns = {}\n"
            "exec(compile(_p.Path('sneaky_helper.py').read_text(), 'sneaky_helper.py', 'exec'), _ns)\n",
            id="executed-without-ever-becoming-a-module",
        ),
    ),
)
def test_cli_sees_undeclared_code_that_never_stays_in_sys_modules(
    tmp_path: Path, evasion: str
) -> None:
    """Reach is measured at compile time, not by taking inventory of `sys.modules`.

    Both shapes run undeclared repository code and leave nothing behind for a
    `sys.modules` walk to find: one deletes its own entry after importing, the other never
    creates one. An audit hook installed before anything else records the compile itself,
    and audit hooks cannot be removed once installed, so the record is append-only.
    """
    document = _executable_fixture(tmp_path)
    (tmp_path / "sneaky_helper.py").write_text("def stub():\n    return None\n", encoding="utf-8")
    evidence = tmp_path / "tests/test_registry.py"
    marker = "from __future__ import annotations\n"
    source = evidence.read_text(encoding="utf-8")
    evidence.write_text(source.replace(marker, marker + "\n" + evasion, 1), encoding="utf-8")
    checker = _checker_with_refreshed_digests(tmp_path)

    result = _run_checker(tmp_path, document, checker=str(checker))

    payload = json.loads(result.stdout)
    assert result.returncode == 1
    assert payload["ok"] is False
    (issue,) = payload["issues"]
    assert issue["code"] == "evidence_execution"
    assert issue["detail"] == (
        "unaudited repository modules on the evidence path: ['sneaky_helper.py']"
    )


# `test_cli_does_not_run_startup_code_from_site_packages` used to live here. It planted a
# `.pth` in a directory it put on `PYTHONPATH` and asserted the corrupted-product verdict.
# Both halves were wrong: `site` scans only site directories for `.pth` files, never
# `PYTHONPATH` entries (measured: a non-hidden `.pth` on `PYTHONPATH` does not execute even
# with no interpreter flags), and the child pops `PYTHONPATH` anyway -- so the forge never
# constructed and the assertion was satisfied by the corruption alone. Deleting the whole
# `.pth` write left it passing. It was scenery.
#
# The guarantee it claimed is owned behaviourally by
# `test_the_child_is_launched_with_startup_code_disabled`, which observes the argv the
# checker really builds. Reaching the remaining vector -- a `.pth` in a genuine site
# directory -- would mean writing into the shared virtualenv from a test, which is not
# something this suite is allowed to do.


def test_the_library_exemption_never_covers_the_audited_tree(tmp_path: Path) -> None:
    """Undeclared repository code is still found when the library list names the root.

    The reach audit exempts library code, and that boundary used to be derived from
    `sys.prefix`, which silently exempted an in-tree virtualenv. Stating it explicitly
    introduced a sharper version of the same bug: `sys.path` carries `""`, meaning the
    working directory, so handing `sys.path` over wholesale would have exempted the whole
    repository. Only absolute, existing directories are passed now, and the audited root is
    dropped from the list however it is spelled.

    Honest scope: this passes with either guard removed, because the static content gate
    rejects the tampered evidence file first. It pins the end-to-end outcome, not those two
    lines; both are labelled redundant in the checker.
    """
    document = _executable_fixture(tmp_path)
    # Nested, because `library in path.parents` only ever hides files below the exempted
    # directory: a top-level file stays visible either way, and every evidence module is
    # nested, so this is the shape the exemption would really have covered.
    (tmp_path / "tests/sneaky_helper.py").write_text("VALUE = 1\n", encoding="utf-8")
    evidence = tmp_path / "tests/test_registry.py"
    marker = "from __future__ import annotations\n"
    evidence.write_text(
        evidence.read_text(encoding="utf-8").replace(
            marker, marker + "\nimport sys as _s\n_s.path.insert(0, str(__import__('pathlib').Path(__file__).parent))\nimport sneaky_helper as _sh\n", 1
        ),
        encoding="utf-8",
    )
    checker = _checker_with_refreshed_digests(tmp_path)
    environment = dict(os.environ)
    # The audited root spelled as an entry in its own right. `sys.path` carries "" and the
    # child runs with cwd == root, so passing `sys.path` through verbatim put exactly this
    # value on the library list and exempted the whole repository.
    environment["ONTOLOGYLAB_STATUS_SITEDIRS"] = os.pathsep.join(
        [str(tmp_path), *_SITE_DIRS]
    )

    result = _run_checker(
        tmp_path, document, environment=environment, checker=str(checker)
    )

    payload = json.loads(result.stdout)
    assert result.returncode == 1
    assert payload["ok"] is False
    (issue,) = payload["issues"]
    assert issue["detail"] == (
        "unaudited repository modules on the evidence path: ['tests/sneaky_helper.py']"
    )


def test_the_child_is_launched_with_startup_code_disabled(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The command the checker really builds for its child carries `-I -S`.

    Owned by observing the invocation, not by grepping the file that contains it: a check
    compared against a re-derivation of itself proves nothing. `subprocess.run` is replaced,
    `_execute_test_evidence` is called for real, and the argv it constructed is inspected.
    Deleting `-S` from the command line fails this; so does deleting `-I`.
    """
    captured: dict[str, object] = {}

    def fake_run(command, **kwargs):
        captured["command"] = list(command)
        captured["fds"] = kwargs.get("pass_fds")
        raise _StopBeforeExec

    monkeypatch.setattr(check_product_status.subprocess, "run", fake_run)
    with pytest.raises(_StopBeforeExec):
        check_product_status._execute_test_evidence(REPOSITORY)

    command = captured["command"]
    assert command[0] == sys.executable
    interpreter_flags = command[1 : command.index("-c")]
    assert "-I" in interpreter_flags, interpreter_flags
    assert "-S" in interpreter_flags, interpreter_flags
    # The run secret travels on an inherited descriptor, not on the command line.
    assert captured["fds"], "the child must inherit the secret pipe"


def test_the_parent_reexecs_itself_with_startup_code_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The re-exec the checker really performs carries `-I -S -P`.

    Same standard: `os.execv` is replaced and the argv is inspected. `-P` matters on its own
    -- without it `sys.path[0]` is `scripts/`, so a `scripts/pytest.py` would be imported in
    preference to the real package, before the secret is drained, out of a directory the
    audit never looks at.
    """
    captured: dict[str, object] = {}

    def fake_execve(executable, argv, environment):
        captured["executable"] = executable
        captured["argv"] = list(argv)
        captured["environment"] = dict(environment)
        raise _StopBeforeExec

    monkeypatch.setattr(check_product_status.os, "execve", fake_execve)
    monkeypatch.setattr(check_product_status.sys, "argv", ["check_product_status.py"])
    monkeypatch.delenv("ONTOLOGYLAB_STATUS_REEXEC", raising=False)
    monkeypatch.setattr(
        check_product_status.sys,
        "flags",
        _Flags(isolated=False, no_site=False, safe_path=False),
    )

    with pytest.raises(_StopBeforeExec):
        check_product_status._reexec_isolated()

    argv = captured["argv"]
    assert argv[0] == captured["executable"]
    flags = argv[1 : argv.index(str(REPOSITORY / "scripts/check_product_status.py"))]
    assert flags == ["-I", "-S", "-P"], flags
    # The sentinel travels in the replacement environment, not in this process: a re-exec
    # that does not happen must leave the caller's environment untouched.
    assert captured["environment"]["ONTOLOGYLAB_STATUS_REEXEC"] == "1"
    assert "ONTOLOGYLAB_STATUS_REEXEC" not in os.environ


def test_the_child_library_list_never_names_the_audited_tree(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The library allow-list the parent computes contains no path that means "here".

    `sys.path` carries "" -- the working directory, i.e. the audited root -- and handing it
    over verbatim exempted the entire repository from the reach audit for one iteration.
    This inspects the value actually placed in the environment for the child.
    """
    captured: dict[str, object] = {}

    def fake_execve(executable, argv, environment):
        captured["sitedirs"] = environment["ONTOLOGYLAB_STATUS_SITEDIRS"]
        captured["environment"] = dict(environment)
        raise _StopBeforeExec

    monkeypatch.setattr(check_product_status.os, "execve", fake_execve)
    monkeypatch.setattr(check_product_status.sys, "argv", ["check_product_status.py"])
    monkeypatch.delenv("ONTOLOGYLAB_STATUS_REEXEC", raising=False)
    monkeypatch.setattr(
        check_product_status.sys,
        "flags",
        _Flags(isolated=False, no_site=False, safe_path=False),
    )
    monkeypatch.chdir(REPOSITORY)

    with pytest.raises(_StopBeforeExec):
        check_product_status._reexec_isolated()

    entries = [
        entry for entry in str(captured["sitedirs"]).split(os.pathsep) if entry
    ]
    assert entries, "the child still needs its library directories"
    for entry in entries:
        assert Path(entry).is_absolute(), entry
        assert Path(entry).is_dir(), entry
        assert Path(entry).resolve() != REPOSITORY, entry



def test_the_run_secret_is_not_recoverable_after_the_executor_drains_it(
    tmp_path: Path,
) -> None:
    """Code that runs later cannot obtain the key the report is signed with.

    Disclosure rather than a claim of a barrier: `os.close` on the secret descriptor is
    hygiene. The property that actually holds is that the parent closed the write end and
    the executor consumed the whole secret before any repository code ran, so a later read
    yields nothing whether or not the descriptor was closed. This pins that, by having
    product code report what it can recover.
    """
    document = _executable_fixture(tmp_path)
    _corrupt_every_canonical_node(tmp_path)
    recovered = tmp_path.parent / (tmp_path.name + "-recovered.txt")
    models = tmp_path / "ontologylab/models.py"
    models.write_text(
        models.read_text(encoding="utf-8")
        + "\n\nimport os as _os, sys as _sys\n\n"
        "if '--junitxml' in _sys.argv:\n"
        "    try:\n"
        "        _got = _os.read(int(_sys.argv[4]), 64)\n"
        "    except OSError as _exc:\n"
        "        _got = b'closed:' + type(_exc).__name__.encode()\n"
        "    open(%r, 'wb').write(_got)\n" % str(recovered),
        encoding="utf-8",
    )

    result = _run_checker(tmp_path, document)

    assert result.returncode == 1
    assert json.loads(result.stdout)["issues"] == [EVERY_NODE_FAILED]
    assert recovered.read_bytes() in (b"", b"closed:OSError")


def test_cli_names_a_collection_error_as_one(tmp_path: Path) -> None:
    """An unimportable helper is reported as a collection error, not as failed assertions.

    Saying \"failed N canonical nodes\" for a broken import sends the reader looking for a
    product defect that is not there. The count and the kind are now separate.
    """
    document = _executable_fixture(tmp_path)
    models = tmp_path / "ontologylab/models.py"
    models.write_text(
        models.read_text(encoding="utf-8") + "\nimport ontologylab.definitely_absent\n",
        encoding="utf-8",
    )

    result = _run_checker(tmp_path, document)

    payload = json.loads(result.stdout)
    assert result.returncode == 1
    assert payload["ok"] is False
    (issue,) = payload["issues"]
    assert issue["code"] == "evidence_execution"
    assert "could not collect or set up" in issue["detail"]
    assert "failed" not in issue["detail"]


def test_cli_reports_a_write_into_the_audited_tree(tmp_path: Path) -> None:
    """A run that writes inside the tree it audits is reported as such.

    The sibling test above pins the *outcome* -- that nothing is written -- and passes as
    long as `-p no:cacheprovider` keeps pytest quiet, which means it survives deleting the
    reporting block entirely. This one forces a write from product code at import time, so
    the only thing that can turn the run red is the report itself.
    """
    document = _executable_fixture(tmp_path)
    models = tmp_path / "ontologylab/models.py"
    models.write_text(
        models.read_text(encoding="utf-8")
        + "\n\nimport pathlib as _pl\n\n"
        "_pl.Path(__file__).parent.parent.joinpath('audit-side-effect.txt').write_text('x')\n",
        encoding="utf-8",
    )

    result = _run_checker(tmp_path, document)

    payload = json.loads(result.stdout)
    assert result.returncode == 1
    assert payload["ok"] is False
    (issue,) = payload["issues"]
    assert issue["code"] == "evidence_execution"
    assert issue["detail"].startswith("the audited run wrote inside the audited tree: ")
    assert "audit-side-effect.txt" in issue["detail"]



def test_cli_leaves_the_audited_tree_untouched(tmp_path: Path) -> None:
    """The audit is read-only with respect to the tree it audits.

    pytest wrote `.pytest_cache/` into `--root`, which is the real checkout under the CI
    invocation. The cache plugin is off now, and the checker verifies the property rather
    than trusting the flag: it snapshots the tree and refuses a run that modified it. That
    matters more than the cache directory itself, because `--noconftest` also drops the
    suite's guard against a test writing the developer's own settings.
    """
    def snapshot() -> dict[str, int]:
        # `__pycache__` is the interpreter writing bytecode for imports, not the audit
        # writing data, and the checker's own snapshot excludes it for the same reason.
        return {
            str(path): path.stat().st_mtime_ns
            for path in tmp_path.rglob("*")
            if path.is_file() and "__pycache__" not in path.parts
        }

    document = _executable_fixture(tmp_path)
    before = snapshot()

    result = _run_checker(tmp_path, document)

    after = snapshot()
    assert result.returncode == 0
    assert json.loads(result.stdout)["ok"] is True
    assert sorted(set(after) - set(before)) == []
    assert [path for path, stamp in after.items() if before.get(path) != stamp] == []
    assert not (tmp_path / ".pytest_cache").exists()


def test_cli_isolates_its_own_process_from_pythonpath_injection(tmp_path: Path) -> None:
    """`sitecustomize.py` on `PYTHONPATH` does not reach the process that prints the receipt.

    `-I` hardened only the child, so `site` imported `sitecustomize` into the parent before
    `main()` ran — arbitrary code inside the very process that authors the claim, free to
    replace `subprocess.run` and hand every parent gate data it wrote itself. The checker now
    replaces its own process image with an isolated interpreter first, via `execv` rather
    than `subprocess`, because injected code already resident in the process can filter the
    latter and did.
    """
    document = _executable_fixture(tmp_path)
    _corrupt_every_canonical_node(tmp_path)
    injection = tmp_path / "parent-injection"
    injection.mkdir()
    (injection / "sitecustomize.py").write_text(
        "import json, subprocess\n"
        "from pathlib import Path\n"
        "class _Fake:\n"
        "    returncode = 0\n"
        "    stdout = ''\n"
        "    stderr = ''\n"
        "_real = subprocess.run\n"
        "def run(cmd, *a, **k):\n"
        "    if isinstance(cmd, list) and '-I' in cmd and len(cmd) > 6:\n"
        "        plan = json.loads(Path(cmd[5]).read_text())\n"
        "        nodes = plan['nodes']\n"
        "        Path(cmd[6]).write_text(json.dumps({\n"
        "            'executed': {n: e['digest'] for n, e in nodes.items()},\n"
        "            'modules': dict(plan['modules']),\n"
        "            'unaudited': [],\n"
        "        }, sort_keys=True))\n"
        "        receipt = Path(cmd[cmd.index('--junitxml') + 1])\n"
        "        cases = ''.join('<testcase file=\"%s\" name=\"%s\"/>' % tuple(n.split('::', 1)) for n in nodes)\n"
        "        receipt.write_text('<testsuites><testsuite tests=\"13\" failures=\"0\" "
        "errors=\"0\" skipped=\"0\">' + cases + '</testsuite></testsuites>')\n"
        "        return _Fake()\n"
        "    return _real(cmd, *a, **k)\n"
        "subprocess.run = run\n",
        encoding="utf-8",
    )
    environment = dict(os.environ)
    environment["PYTHONPATH"] = str(injection)

    result = _run_checker(tmp_path, document, environment=environment)

    payload = json.loads(result.stdout)
    assert result.returncode == 1
    assert payload["ok"] is False
    assert payload["issues"] == [EVERY_NODE_FAILED]


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


# One probe assignment per form, so the contract test measures the shipped function rather
# than trusting a comment about it. The literal forms must be bound; everything derived from
# an expression must not be, and whatever comes back unbound has to be declared in the spec.
_DATA_BINDING_PROBE = """
LITERAL_STR = "a"
LITERAL_INT = 1
LITERAL_TUPLE = (1, 2)
LITERAL_DICT = {"k": 1}
LITERAL_FROZENSET = frozenset({"x"})
LITERAL_SET = set(["y"])
ANNOTATED_LITERAL: int = 5
DERIVED_CALL = compute()
DERIVED_ATTRIBUTE = other.value
DERIVED_NAME = LITERAL_INT
DERIVED_BINOP = 2 * 1024 * 1024
DERIVED_COMPOUND = {"k": LITERAL_INT}
DERIVED_JOINEDSTR = f"{LITERAL_STR}-suffix"
"""


def _shipped_helpers(*names: str) -> dict[str, object]:
    """Lift named helpers out of the child program the checker actually ships."""
    source = (
        Path(__file__).resolve().parents[1] / "scripts/check_product_status.py"
    ).read_text(encoding="utf-8")
    child = source.split('EVIDENCE_EXECUTOR_PROGRAM: Final = """', 1)[1].split('"""', 1)[0]
    tree = ast.parse(child)
    namespace: dict[str, object] = {
        "ast": ast,
        "hashlib": hashlib,
        "struct": struct,
        "sys": sys,
        "types": types,
        "CodeType": CodeType,
        "UNBOUND_DEFAULT": object(),
        "_TYPE_NAMESPACE": type.__dict__["__dict__"],
        "_TYPE_BASES": type.__dict__["__bases__"],
        "_TYPE_MRO": type.__dict__["__mro__"],
        "_TYPE_MODULE": type.__dict__["__module__"],
        "_TYPE_QUALNAME": type.__dict__["__qualname__"],
        "_BUILTIN_TYPE_BINDING": ("external", "builtins", ("type",)),
    }
    requested = list(names)
    source_semantics_target = next(
        (
            name
            for name in ("source_descriptor_callables", "_source_class_semantics")
            if name in requested
        ),
        None,
    )
    if source_semantics_target is not None:
        insertion = requested.index(source_semantics_target)
        requested[insertion:insertion] = [
            "_code_bytes", "_is_class", "_class_namespace", "_class_bases",
            "_class_mro", "_class_identity", "_external_class",
            "_external_class_binding", "_class_semantic_bytes",
            "_method_semantic_bytes", "_literal_semantic_bytes",
            "_source_class_semantics"
        ]
    if "_class_definition_bytes" in requested:
        insertion = requested.index("_class_definition_bytes")
        requested[insertion:insertion] = [
            "_code_bytes", "_is_class", "_class_namespace", "_class_bases",
            "_class_mro", "_class_identity", "_class_semantic_bytes",
            "_method_semantic_bytes", "_literal_semantic_bytes"
        ]
    if "_receiver_bytes" in requested:
        insertion = requested.index("_receiver_bytes")
        requested[insertion:insertion] = [
            "_code_bytes", "_is_class", "_class_namespace", "_class_bases",
            "_class_mro", "_class_identity", "_class_semantic_bytes",
            "_method_semantic_bytes", "_literal_semantic_bytes",
            "_class_definition_bytes"
        ]
    class_walker_target = next(
        (
            name
            for name in ("live_code_objects", "_code_objects_of", "_descriptor_members")
            if name in requested
        ),
        None,
    )
    if class_walker_target is not None:
        insertion = requested.index(class_walker_target)
        requested[insertion:insertion] = [
            "_is_class", "_class_namespace", "_class_bases", "_class_mro",
            "_class_identity"
        ]
    if "_descriptor_value_bytes" in requested:
        insertion = requested.index("_descriptor_value_bytes")
        requested[insertion:insertion] = [
            "_code_bytes", "_is_class", "_class_namespace", "_class_bases",
            "_class_mro", "_class_identity", "_class_semantic_bytes",
            "_method_semantic_bytes", "_literal_semantic_bytes",
            "_class_definition_bytes", "_receiver_bytes", "_callable_bytes"
        ]
    for name in requested:
        definition = next(
            node
            for node in tree.body
            if isinstance(node, ast.FunctionDef) and node.name == name
        )
        exec(
            compile(ast.Module(body=[definition], type_ignores=[]), "<child>", "exec"),
            namespace,
        )
    return namespace


def _shipped_literal_assignments():
    """The `literal_assignments` the checker actually ships, lifted out of the child program."""
    source = (
        Path(__file__).resolve().parents[1] / "scripts/check_product_status.py"
    ).read_text(encoding="utf-8")
    child = source.split('EVIDENCE_EXECUTOR_PROGRAM: Final = """', 1)[1].split('"""', 1)[0]
    definition = next(
        node
        for node in ast.parse(child).body
        if isinstance(node, ast.FunctionDef) and node.name == "literal_assignments"
    )
    namespace: dict[str, object] = {"ast": ast}
    exec(
        compile(ast.Module(body=[definition], type_ignores=[]), "<child>", "exec"),
        namespace,
    )
    return namespace["literal_assignments"]


def _spec_section(heading: str, stop: str) -> str:
    spec = (
        Path(__file__).resolve().parents[1] / "docs/PRODUCT_SPEC.md"
    ).read_text(encoding="utf-8")
    assert heading in spec, f"docs/PRODUCT_SPEC.md no longer declares {heading!r}"
    return spec[spec.index(heading) : spec.index(stop)]


def test_the_declared_data_guarantee_matches_what_the_checker_binds() -> None:
    """The spec's data promise is exactly as wide as `literal_assignments()` actually is.

    The gate deliberately binds only literal assignments, which is a defensible limit. What
    is not defensible is promising more than that: §7.1 used to say unqualifiedly that a
    module-level constant holding a value other than the one its file declares is caught, and
    an ordinary cross-module refactor leftover (`r._MAX_INFO_BYTES = 2 * 1024 * 1024`, an
    arithmetic expression) passed the gate while that sentence stood.

    This measures the shipped function against one probe per assignment form and requires the
    spec to declare every form it leaves unbound. It fails if the residual declaration
    disappears, and equally if the function is widened without the spec following -- neither
    side can drift alone. It does not pin any sentence.
    """
    literal_assignments = _shipped_literal_assignments()
    bound = literal_assignments(_DATA_BINDING_PROBE, "<probe>")

    assigned = {
        node.targets[0].id if isinstance(node, ast.Assign) else node.target.id: node.value
        for node in ast.parse(_DATA_BINDING_PROBE).body
        if isinstance(node, (ast.Assign, ast.AnnAssign))
    }
    unbound = {name: value for name, value in assigned.items() if name not in bound}

    # The literal forms the spec claims are bound really are.
    assert set(bound) == {name for name in assigned if name.startswith("LITERAL_")} | {
        "ANNOTATED_LITERAL"
    }, sorted(bound)
    # And the derived ones really are not, so the residual is real rather than rhetorical.
    assert set(unbound) == {name for name in assigned if name.startswith("DERIVED_")}

    residual = _spec_section("#### 7.1.1", "## 8. 비목표")
    declared_kinds = set(re.findall(r"`([A-Z][A-Za-z]+)`", residual))
    observed_kinds = {type(value).__name__ for value in unbound.values()}
    assert observed_kinds <= declared_kinds, sorted(observed_kinds - declared_kinds)

    # The guarantee bullet must point at the qualification rather than stand unqualified.
    protected = _spec_section("**막는 것", "#### 7.1.1")
    data_bullet = next(
        line for line in protected.splitlines() if "모듈 수준 상수" in line
    )
    assert "리터럴" in data_bullet, data_bullet
    assert "§7.1.1" in protected

    # The residual is a fourth, non-hostile item, and must stay outside the hostile list.
    # Checked by label rather than by phrase: asserting that the words "hostile exclusion"
    # appear somewhere still passed when the residual was merged into that very list.
    assert "`residual-4-non-hostile`" in residual
    hostile = _spec_section("**막지 않는 것", "#### 7.1.1")
    hostile_labels = set(re.findall(r"`(hostile-\d)`", hostile))
    assert hostile_labels == {"hostile-1", "hostile-2", "hostile-3"}, sorted(hostile_labels)
    # The three hostile cases are declared where the code points at them, and the residual
    # is not one of them.
    assert "residual-4" not in hostile
    checker = (
        Path(__file__).resolve().parents[1] / "scripts/check_product_status.py"
    ).read_text(encoding="utf-8")
    assert checker.count("DECLARED BOUNDARY (docs/PRODUCT_SPEC.md \u00a77.1, case") == 3



def test_the_declared_boundaries_in_code_match_the_spec_section() -> None:
    """Every exemption in the checker points at the section that declares it.

    The reason cycle four's break walked through was that `ontologylab/**` was exempt
    silently. An undeclared boundary reads as a defect to the next reviewer and as coverage
    to the next maintainer. This keeps the two from drifting apart: each `DECLARED BOUNDARY`
    comment names the spec section, and the section names all three cases.
    """
    repository = Path(__file__).resolve().parents[1]
    checker = (repository / "scripts/check_product_status.py").read_text(encoding="utf-8")
    spec = (repository / "docs/PRODUCT_SPEC.md").read_text(encoding="utf-8")

    assert checker.count("DECLARED BOUNDARY (docs/PRODUCT_SPEC.md \u00a77.1") == 3
    for case in ("case 1", "case 2", "case 3"):
        assert f"\u00a77.1, {case})" in checker, case

    section = spec[spec.index("### 7.1"):spec.index("## 8.")]
    # The three cases the code defers to, and the reason the boundary sits there.
    assert "__main__" in section
    assert "scripts/subprocess.py" in section
    assert "LIBRARY_ROOTS" in section
    assert "-P" in section
    # The acceptance table is what the checker parses; the declaration must not disturb it.
    assert "<!-- product-status:v1:start -->" in spec
    assert spec.index("### 7.1") > spec.index("<!-- product-status:v1:end -->")



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
                "-P",
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
