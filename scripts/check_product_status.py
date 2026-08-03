#!/usr/bin/env python3
"""Validate the canonical product-status block and its local evidence paths."""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Final

START: Final = "<!-- product-status:v1:start -->"
END: Final = "<!-- product-status:v1:end -->"
REQUIRED_IDS: Final = ("AC-01", "AC-02", "AC-03", "CHUNK-SWEEP")
VALID_STATUSES: Final = frozenset({"COMPLETE", "INCOMPLETE"})
PATH_RE: Final = re.compile(r"`([^`]+)`")
DOCUMENT_START: Final = "<!-- product-evidence:v1:start -->"
DOCUMENT_END: Final = "<!-- product-evidence:v1:end -->"
EVIDENCE_CONTRACT: Final = {
    "AC-01": frozenset(
        {
            "tests/test_staleness.py::test_manifest_carries_basis_and_the_default_policy",
            "tests/test_staleness.py::test_count_cancellation_still_reports_semantic_staleness",
            "tests/test_staleness.py::test_same_stable_id_material_change_is_replacement",
            "tests/test_staleness.py::test_pending_count_is_computed_live_against_the_store",
        }
    ),
    "AC-02": frozenset(
        {
            "tests/test_registry.py::test_absent_cache_is_off_not_an_error_and_warns_once",
            "tests/test_registry.py::test_csv_import_resolves_scientific_synonym_and_common_case_insensitively",
            "tests/test_agrochem_schema.py::test_organisms_and_actives_carry_their_registry_identifier",
            "tests/test_normalization.py::test_unresolved_organism_is_kept_flagged_and_model_code_is_dropped",
            "tests/test_normalization.py::test_extraction_normalizes_before_storage_and_review_exposes_properties",
            "tests/test_cas_normalization.py::test_alias_resolution_cache_authority_and_moa_follow_canonical_cas",
            "tests/test_cas_normalization.py::test_unknown_active_is_flagged_without_moa_and_model_cas_is_dropped",
        }
    ),
    "AC-03": frozenset(
        {
            "docs/FIRST-PACK-EVIDENCE.md",
            "tests/test_mcp_two_tier.py::test_get_entity_full_record",
            "tests/test_mcp_two_tier.py::test_fastmcp_exposes_two_tier_surface",
        }
    ),
    "CHUNK-SWEEP": frozenset(
        {"docs/CHUNK-SWEEP-2026-08.md", "scripts/sweep_chunk_size.py"}
    ),
}
TEST_EVIDENCE_DIGESTS: Final = {
    "tests/test_staleness.py::test_manifest_carries_basis_and_the_default_policy": "187ae53741bb61b723e528c0fed5974c67934271bbf23d17d54c09d2e2cbd2fd",
    "tests/test_staleness.py::test_count_cancellation_still_reports_semantic_staleness": "490117e7b1ed4ab83eb3e7b9fea014e292dd30a51a51c2efbbee77d41507949d",
    "tests/test_staleness.py::test_same_stable_id_material_change_is_replacement": "d39412c6b53cea442505fcc85e1953b313dd4a564f23cf9a5cf4b94cf03c60c3",
    "tests/test_staleness.py::test_pending_count_is_computed_live_against_the_store": "c879c14e71112fdc9eaa365aa134215fc3d7ede2aff53063d14f5c37ac9669ea",
    "tests/test_registry.py::test_absent_cache_is_off_not_an_error_and_warns_once": "c326eec4b610145db80a3d1b72becd69b32e1c772110be4f36ecff68ec515103",
    "tests/test_registry.py::test_csv_import_resolves_scientific_synonym_and_common_case_insensitively": "0ce6de484d535417956cb912e9c02e7f92678e6d0d4f4fdd9376369c62fa538f",
    "tests/test_agrochem_schema.py::test_organisms_and_actives_carry_their_registry_identifier": "5cb9fcfa261837e8668a0c8de2af08609fb3a7bc0c5a98aeb8bf9a484526988f",
    "tests/test_normalization.py::test_unresolved_organism_is_kept_flagged_and_model_code_is_dropped": "e796e76ec19ced125b07c9376ab1aab12785ea95cd40c30dee032a99d45ee40e",
    "tests/test_normalization.py::test_extraction_normalizes_before_storage_and_review_exposes_properties": "2b0c63e02f2ec11aeb4b4af4ae6a08b70aaba4ea67f8b75e05afb9ed933ca2dd",
    "tests/test_cas_normalization.py::test_alias_resolution_cache_authority_and_moa_follow_canonical_cas": "5426ba3764035bda5cc22050c74b7353eff60ac47a08fb42bef8288a826afb9d",
    "tests/test_cas_normalization.py::test_unknown_active_is_flagged_without_moa_and_model_cas_is_dropped": "5f4919c76a1300590de379f4e46f0fa34624a25ba0d5abbdb23de1f4748a8547",
    "tests/test_mcp_two_tier.py::test_get_entity_full_record": "d88dc1a163345101f58ab9615f923c69e5998b8a899dbaf041bccb327774b7a6",
    "tests/test_mcp_two_tier.py::test_fastmcp_exposes_two_tier_surface": "81899c9a0856c1515df3ef2fd90e16bc61a87c246c6ae069096152e823c94d75",
}
SWEEP_DIGEST: Final = "66eacf5b9d57b4687d7f0b378871ea6885ad79fd68b4e9718e3dc8b06df7045f"
# The child never calls the object bound at the canonical test name. It selects the
# definition whose AST digest equals the audited digest, compiles that definition, calls
# the function that compiling produced, and records the digest it just executed. A name
# rebound to anything else is therefore not consulted, and the parent's receipt count is
# read back out of that record rather than out of this module's dict literal.
EVIDENCE_EXECUTOR_PROGRAM: Final = """
import ast
import hashlib
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(sys.argv[1]).resolve()
PLAN = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))
LEDGER_FILE = Path(sys.argv[3])
LEDGER = {}

# The audited definitions are compiled here rather than by pytest's assertion
# rewriter, so plain `assert` enforcement is what carries the evidence.
if sys.flags.optimize:
    raise SystemExit("canonical evidence cannot run with assertions optimized out")


def audited_definition(node_id):
    # Return the definition whose AST digest is the audited one, or fail loudly.
    entry = PLAN[node_id]
    source = (ROOT / entry["path"]).read_text(encoding="utf-8")
    tree = ast.parse(source, filename=entry["path"])
    matches = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if node.name != entry["name"]:
            continue
        dumped = ast.dump(node, annotate_fields=True, include_attributes=False)
        if hashlib.sha256(dumped.encode("utf-8")).hexdigest() == entry["digest"]:
            matches.append(node)
    if len(matches) != 1:
        raise AssertionError(
            f"{node_id}: {len(matches)} definitions carry the audited digest"
        )
    definition = matches[0]
    if definition.decorator_list:
        raise AssertionError(f"{node_id}: audited definition is decorated")
    if isinstance(definition, ast.AsyncFunctionDef):
        raise AssertionError(f"{node_id}: audited definition is async")
    signature = definition.args
    if (
        signature.posonlyargs
        or signature.kwonlyargs
        or signature.vararg
        or signature.kwarg
        or signature.defaults
    ):
        raise AssertionError(f"{node_id}: audited signature is not plain fixtures")
    return definition, entry


class EvidenceExecutor:
    # Execute the audited source itself, never the object bound at its name.

    @pytest.hookimpl(tryfirst=True)
    def pytest_runtest_call(self, item):
        node_id = f"{item.path.resolve().relative_to(ROOT).as_posix()}::{item.originalname}"
        definition, entry = audited_definition(node_id)
        namespace = dict(item.module.__dict__)
        module = ast.Module(body=[definition], type_ignores=[])
        exec(compile(module, str(ROOT / entry["path"]), "exec"), namespace)
        audited = namespace[entry["name"]]
        arguments = {
            argument.arg: item._request.getfixturevalue(argument.arg)
            for argument in definition.args.args
        }
        result = audited(**arguments)
        if result is not None:
            raise AssertionError("canonical test returned a value")
        LEDGER[node_id] = entry["digest"]
        item.runtest = lambda: None


sys.path.insert(0, str(ROOT))
try:
    code = pytest.main(sys.argv[4:], plugins=[EvidenceExecutor()])
finally:
    LEDGER_FILE.write_text(json.dumps(LEDGER, sort_keys=True), encoding="utf-8")
raise SystemExit(code)
"""
DOCUMENT_CONTRACTS: Final = {
    "docs/FIRST-PACK-EVIDENCE.md": {
        "claims": [
            "sourced_entity_lookup",
            "sourced_relation_traversal",
            "full_entity_provenance",
            "live_staleness",
        ],
        "command": ".venv/bin/python -m ontologylab.mcp_server --packs-dir <throwaway>/packs --live-store <throwaway>/data/kg.sqlite",
        "evidence_id": "AC-03-FIRST-PACK",
        "kind": "recorded-execution",
        "result": {
            "content_hash": "sha256:eb233081b580a9100f08a17a4709223a9c05649607ad2848f4b6686f1e430449",
            "edges_verified": 28,
            "nodes_verified": 29,
            "pack_id": "agrochem-first-20260802-223925",
            "pending_verified_count": 1,
        },
    },
    "docs/CHUNK-SWEEP-2026-08.md": {
        "command": ".venv/bin/python scripts/sweep_chunk_size.py --engine claude --output-dir /tmp/ontologylab-chunk-sweep-2026-08",
        "decision": 3000,
        "evidence_id": "CHUNK-SWEEP-2026-08",
        "fixture": "tests/gold/agrochem-mini/docs.json",
        "kind": "recorded-measurement",
        "results": {
            "1500": {"calls": 10, "triple_f1": 0.9643},
            "3000": {"calls": 5, "triple_f1": 0.9818},
        },
        "sizes": [1500, 3000],
    },
}


@dataclass(frozen=True, slots=True)
class StatusEntry:
    item_id: str
    status: str
    evidence: tuple[str, ...]
    follow_up: str
    follow_up_detail: str


@dataclass(frozen=True, slots=True)
class Issue:
    code: str
    item_id: str
    detail: str


@dataclass(frozen=True, slots=True)
class StatusReport:
    ok: bool
    entries: tuple[StatusEntry, ...]
    resolved_paths: tuple[str, ...]
    issues: tuple[Issue, ...]

    def payload(self) -> dict[str, object]:
        return {
            "ok": self.ok,
            "entries": [asdict(entry) for entry in self.entries],
            "resolved_paths": list(self.resolved_paths),
            "issues": [
                {"code": issue.code, "id": issue.item_id, "detail": issue.detail}
                for issue in self.issues
            ],
        }


def _table_rows(text: str) -> tuple[list[dict[str, str]], list[Issue]]:
    if text.count(START) != 1 or text.count(END) != 1:
        return [], [Issue("missing_delimiters", "DOCUMENT", "expected one v1 status block")]
    block = text.split(START, 1)[1].split(END, 1)[0]
    lines = [line.strip() for line in block.splitlines() if line.strip().startswith("|")]
    if len(lines) < 3:
        return [], [Issue("invalid_table", "DOCUMENT", "status block has no data rows")]
    headers = [cell.strip() for cell in lines[0].strip("|").split("|")]
    expected = ["ID", "Status", "Evidence", "Follow-up"]
    if headers != expected:
        return [], [
            Issue("invalid_table", "DOCUMENT", f"expected columns {', '.join(expected)}")
        ]
    rows: list[dict[str, str]] = []
    issues: list[Issue] = []
    for line_number, line in enumerate(lines[2:], start=3):
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        if len(cells) != len(headers):
            issues.append(
                Issue("invalid_table", f"ROW-{line_number}", "row width differs from header")
            )
            continue
        rows.append(dict(zip(headers, cells, strict=True)))
    return rows, issues


def _follow_up(cell: str) -> tuple[str, str] | None:
    if cell == "NONE":
        return "NONE", ""
    for kind in ("BLOCKING", "NON-BLOCKING"):
        prefix = f"{kind}:"
        if cell.startswith(prefix) and cell[len(prefix) :].strip():
            return kind, cell[len(prefix) :].strip()
    return None


def _inside_root(root: Path, reference: str) -> Path | None:
    candidate = (root / reference).resolve()
    if candidate == root or root in candidate.parents:
        return candidate
    return None


def _test_digest(path: Path, function_name: str) -> str | None:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except (OSError, SyntaxError, UnicodeError):
        return None
    function = next(
        (
            node
            for node in tree.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == function_name
        ),
        None,
    )
    if function is None:
        return None
    normalized = ast.dump(function, annotate_fields=True, include_attributes=False)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _documentary_evidence(path: Path, reference: str) -> bool:
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return False
    if text.count(DOCUMENT_START) != 1 or text.count(DOCUMENT_END) != 1:
        return False
    payload_text = text.split(DOCUMENT_START, 1)[1].split(DOCUMENT_END, 1)[0].strip()
    try:
        payload = json.loads(payload_text)
    except json.JSONDecodeError:
        return False
    return payload == DOCUMENT_CONTRACTS[reference]


def _sweep_digest(path: Path) -> str | None:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return None


def check_status(document: Path, root: Path) -> StatusReport:
    root = root.resolve()
    document = document if document.is_absolute() else root / document
    try:
        text = document.read_text(encoding="utf-8")
    except OSError as exc:
        issue = Issue("unreadable_document", "DOCUMENT", str(exc))
        return StatusReport(False, (), (), (issue,))

    rows, issues = _table_rows(text)
    if not rows and issues:
        return StatusReport(False, (), (), tuple(issues))
    entries: list[StatusEntry] = []
    resolved_paths: set[str] = set()
    counts = {item_id: 0 for item_id in REQUIRED_IDS}

    for row in rows:
        item_id = row["ID"]
        status = row["Status"]
        evidence = tuple(PATH_RE.findall(row["Evidence"]))
        parsed_follow_up = _follow_up(row["Follow-up"])

        if item_id not in counts:
            issues.append(Issue("unexpected_id", item_id, "ID is not in the canonical set"))
        else:
            counts[item_id] += 1
        if status not in VALID_STATUSES:
            issues.append(Issue("invalid_status", item_id, status))
        elif status != "COMPLETE":
            issues.append(
                Issue("stale_status", item_id, f"expected COMPLETE, got {status}")
            )
        if not evidence:
            issues.append(Issue("empty_evidence", item_id, "at least one path is required"))
        expected_evidence = EVIDENCE_CONTRACT.get(item_id)
        if expected_evidence is not None and set(evidence) != expected_evidence:
            missing = sorted(expected_evidence - set(evidence))
            unexpected = sorted(set(evidence) - expected_evidence)
            detail = f"missing={missing}; unexpected={unexpected}"
            issues.append(Issue("evidence_contract", item_id, detail))
        if parsed_follow_up is None:
            issues.append(
                Issue("invalid_followup", item_id, "use NONE, BLOCKING:, or NON-BLOCKING:")
            )
            follow_up, follow_up_detail = "INVALID", row["Follow-up"]
        else:
            follow_up, follow_up_detail = parsed_follow_up
        if status == "COMPLETE" and follow_up == "BLOCKING":
            issues.append(
                Issue(
                    "followup_contradiction",
                    item_id,
                    "COMPLETE cannot have a blocking follow-up",
                )
            )
        if status == "INCOMPLETE" and follow_up != "BLOCKING":
            issues.append(
                Issue(
                    "followup_contradiction",
                    item_id,
                    "INCOMPLETE requires a blocking follow-up",
                )
            )

        for reference in evidence:
            path_reference, separator, function_name = reference.partition("::")
            candidate = _inside_root(root, path_reference)
            if candidate is None or not candidate.is_file():
                issues.append(Issue("broken_path", item_id, path_reference))
                continue
            resolved_paths.add(path_reference)
            if separator:
                expected_digest = TEST_EVIDENCE_DIGESTS.get(reference)
                if expected_digest is None or _test_digest(candidate, function_name) != expected_digest:
                    issues.append(Issue("evidence_integrity", item_id, reference))
            elif reference in DOCUMENT_CONTRACTS and not _documentary_evidence(
                candidate, reference
            ):
                issues.append(Issue("documentary_evidence", item_id, reference))
            elif (
                reference == "scripts/sweep_chunk_size.py"
                and _sweep_digest(candidate) != SWEEP_DIGEST
            ):
                issues.append(Issue("evidence_integrity", item_id, reference))
        entries.append(StatusEntry(item_id, status, evidence, follow_up, follow_up_detail))

    for item_id, count in counts.items():
        if count == 0:
            issues.append(Issue("missing_id", item_id, "required row is absent"))
        elif count > 1:
            issues.append(Issue("duplicate_id", item_id, f"found {count} rows"))

    return StatusReport(
        not issues,
        tuple(entries),
        tuple(sorted(resolved_paths)),
        tuple(issues),
    )


def _validate_pytest_receipt(
    receipt: Path,
    *,
    expected_count: int,
    expected_nodes: frozenset[str] | None = None,
) -> Issue | None:
    try:
        root = ET.parse(receipt).getroot()
        suites = root.findall(".//testsuite")
        testcases = root.findall(".//testcase")
        tests = sum(int(suite.attrib.get("tests", "0")) for suite in suites)
        failures = sum(int(suite.attrib.get("failures", "0")) for suite in suites)
        errors = sum(int(suite.attrib.get("errors", "0")) for suite in suites)
        skipped = sum(int(suite.attrib.get("skipped", "0")) for suite in suites)
    except (ET.ParseError, OSError, ValueError):
        return Issue("evidence_execution", "DOCUMENT", "pytest receipt is missing or malformed")

    if failures or errors:
        return Issue(
            "evidence_execution",
            "DOCUMENT",
            f"pytest failed {failures + errors} canonical nodes",
        )
    if skipped:
        return Issue(
            "evidence_execution",
            "DOCUMENT",
            f"pytest skipped {skipped} canonical nodes",
        )
    if tests != expected_count:
        return Issue(
            "evidence_execution",
            "DOCUMENT",
            f"pytest executed {tests} of {expected_count} canonical nodes",
        )
    if expected_nodes is not None:
        executed_nodes = frozenset(
            f"{case.attrib['file']}::{case.attrib['name']}"
            for case in testcases
            if "file" in case.attrib and "name" in case.attrib
        )
        if executed_nodes != expected_nodes:
            missing = sorted(expected_nodes - executed_nodes)
            unexpected = sorted(executed_nodes - expected_nodes)
            return Issue(
                "evidence_execution",
                "DOCUMENT",
                f"pytest node mismatch: missing={missing}; unexpected={unexpected}",
            )
    return None


def _execute_test_evidence(root: Path) -> tuple[Issue | None, int]:
    node_ids = sorted(TEST_EVIDENCE_DIGESTS)
    environment = os.environ.copy()
    environment.pop("PYTHONPATH", None)
    environment.pop("PYTHONHOME", None)
    environment.pop("PYTEST_ADDOPTS", None)
    environment.pop("PYTEST_PLUGINS", None)
    environment["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
    with tempfile.TemporaryDirectory(prefix="ontologylab-evidence-") as temporary:
        temporary_path = Path(temporary)
        receipt = temporary_path / "pytest.xml"
        plan_file = temporary_path / "plan.json"
        ledger_file = temporary_path / "ledger.json"
        plan_file.write_text(
            json.dumps(
                {
                    node_id: {
                        "path": node_id.split("::", 1)[0],
                        "name": node_id.split("::", 1)[1],
                        "digest": digest,
                    }
                    for node_id, digest in TEST_EVIDENCE_DIGESTS.items()
                },
                sort_keys=True,
            ),
            encoding="utf-8",
        )
        controlled_config = temporary_path / "pytest.ini"
        controlled_config.write_text("[pytest]\naddopts =\n", encoding="utf-8")
        result = subprocess.run(
            [
                sys.executable,
                "-I",
                "-c",
                EVIDENCE_EXECUTOR_PROGRAM,
                str(root),
                str(plan_file),
                str(ledger_file),
                "-q",
                "-c",
                str(controlled_config),
                "--rootdir",
                str(root),
                "--noconftest",
                "-o",
                "addopts=",
                "-o",
                "junit_family=legacy",
                "--junitxml",
                str(receipt),
                *node_ids,
            ],
            cwd=root,
            env=environment,
            check=False,
            capture_output=True,
            text=True,
        )
        ledger, ledger_issue = _read_execution_ledger(ledger_file)
        receipt_issue = _validate_pytest_receipt(
            receipt,
            expected_count=len(node_ids),
            expected_nodes=frozenset(node_ids),
        )
    if receipt_issue is not None:
        return receipt_issue, len(ledger)
    if ledger_issue is not None:
        return ledger_issue, len(ledger)
    if result.returncode != 0:
        output = "\n".join(
            part.strip() for part in (result.stdout, result.stderr) if part.strip()
        )
        return (
            Issue(
                "evidence_execution",
                "DOCUMENT",
                f"pytest exit {result.returncode}: {output[-4000:]}",
            ),
            len(ledger),
        )
    return None, len(ledger)


def _read_execution_ledger(ledger_file: Path) -> tuple[dict[str, str], Issue | None]:
    """Read what the child actually compiled and ran, and hold it to the digests."""
    try:
        ledger = json.loads(ledger_file.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return {}, Issue(
            "evidence_execution",
            "DOCUMENT",
            "execution ledger is missing or malformed",
        )
    if not isinstance(ledger, dict) or not all(
        isinstance(key, str) and isinstance(value, str) for key, value in ledger.items()
    ):
        return {}, Issue(
            "evidence_execution",
            "DOCUMENT",
            "execution ledger is missing or malformed",
        )
    if ledger != dict(TEST_EVIDENCE_DIGESTS):
        missing = sorted(set(TEST_EVIDENCE_DIGESTS) - set(ledger))
        unexpected = sorted(set(ledger) - set(TEST_EVIDENCE_DIGESTS))
        divergent = sorted(
            node_id
            for node_id, digest in ledger.items()
            if TEST_EVIDENCE_DIGESTS.get(node_id) not in (None, digest)
        )
        return ledger, Issue(
            "evidence_execution",
            "DOCUMENT",
            "executed source mismatch: "
            f"missing={missing}; unexpected={unexpected}; divergent={divergent}",
        )
    return ledger, None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd(), help="repository root")
    parser.add_argument(
        "--document",
        type=Path,
        default=Path("docs/PRODUCT_SPEC.md"),
        help="status document, absolute or relative to --root",
    )
    parser.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    args = parser.parse_args(argv)

    report = check_status(args.document, args.root)
    executed = 0
    if report.ok:
        execution_issue, executed = _execute_test_evidence(args.root.resolve())
        if execution_issue is not None:
            report = StatusReport(
                False,
                report.entries,
                report.resolved_paths,
                report.issues + (execution_issue,),
            )
    if report.ok:
        print(
            f"EVIDENCE: {executed} canonical pytest nodes passed",
            file=sys.stderr,
        )
    if args.json:
        print(json.dumps(report.payload(), ensure_ascii=False, sort_keys=True))
    else:
        verdict = "PASS" if report.ok else "FAIL"
        print(f"{verdict}: {len(report.entries)} statuses, {len(report.resolved_paths)} paths")
        for issue in report.issues:
            print(f"{issue.code}: {issue.item_id}: {issue.detail}")
    return 0 if report.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
