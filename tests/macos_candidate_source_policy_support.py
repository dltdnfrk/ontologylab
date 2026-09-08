"""Authoritative source discovery for macOS candidate and Task12 policy tests."""

from __future__ import annotations

import ast
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Final

ROOT = Path(__file__).resolve().parents[1]
_SKIP_PARTS: Final = frozenset({"__pycache__", ".DS_Store"})
_DEPENDENCY_TEST_PATTERNS: Final = (
    "test_macos_candidate*.py",
    "test_release_policy.py",
    "test_release_policy_cli.py",
    "test_release_task10_authority.py",
    "test_retained_evidence*.py",
    "test_sqlite_vec_license_override.py",
    "test_macos_supervisor.py",
    "test_macos_runtime_package.py",
)
_PERFORMANCE_AUTHORITY: Final = frozenset(
    {
        "tests/test_ingestion_performance.py",
        "tests/wave21/ingest_perf.py",
        "tests/wave21/perf_fixture.py",
    }
)
_PRODUCT_CONTRACT_TEST_PATTERNS: Final = (
    "test_p[0-9]_ui_ux_contract.py",
    "test_*_api_auth.py",
    "test_release_*_binding.py",
    "test_release_*_evidence.py",
)


@dataclass(frozen=True, slots=True)
class PolicyCoverage:
    """Complete Task 10-12 authoritative-file coverage audit."""

    declared: frozenset[str]
    authoritative: frozenset[str]
    task10_authoritative: frozenset[str]
    missing: frozenset[str]
    generated_violations: frozenset[str]


def covered(rel: str, declarations: frozenset[str] | set[str]) -> bool:
    return any(rel == item or rel.startswith(f"{item}/") for item in declarations)


def _build_paths(root: Path) -> tuple[str, ...]:
    tree = ast.parse((root / "release" / "candidate_stage.py").read_text())
    for node in tree.body:
        if (
            isinstance(node, ast.AnnAssign)
            and isinstance(node.target, ast.Name)
            and node.target.id == "BUILD_PATHS"
            and node.value is not None
        ):
            value = ast.literal_eval(node.value)
            assert isinstance(value, tuple) and all(
                isinstance(item, str) for item in value
            )
            return value
    raise AssertionError("BUILD_PATHS literal is unavailable")


def _source_files(root: Path, rel: str) -> set[str]:
    path = root / rel
    if path.is_file():
        return {rel}
    return {
        item.relative_to(root).as_posix()
        for item in path.rglob("*")
        if item.is_file()
        and not any(part in _SKIP_PARTS for part in item.parts)
        and item.suffix not in {".pyc", ".pyo"}
    }


def _local_imports(root: Path, rel: str) -> set[str]:
    tree = ast.parse((root / rel).read_text(encoding="utf-8"))
    found: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.ImportFrom) or node.module is None:
            continue
        module = node.module
        if node.level and rel.startswith("release/"):
            module = f"release.{module}"
        if module.startswith(("release.", "scripts.", "tests.")):
            candidate = f"{module.replace('.', '/')}.py"
            if (root / candidate).is_file():
                found.add(candidate)
    return found


def matching_candidate_modules(root: Path) -> set[str]:
    """Discover every Task 11 release module by authoritative naming class."""
    return {
        path.relative_to(root).as_posix()
        for path in (root / "release").glob("candidate_*.py")
    }


def _matching_tests(root: Path, patterns: tuple[str, ...]) -> set[str]:
    return {
        path.relative_to(root).as_posix()
        for pattern in patterns
        for path in (root / "tests").glob(pattern)
    }


def matching_authoritative_tests(root: Path) -> set[str]:
    """Discover release, platform, UI, API-auth, and causal release tests."""
    return _matching_tests(
        root, _DEPENDENCY_TEST_PATTERNS + _PRODUCT_CONTRACT_TEST_PATTERNS
    )


def matching_internal_deployment_sources(root: Path) -> set[str]:
    """Discover Task 10 modules and invoked operator entrypoints."""
    modules = {
        path.relative_to(root).as_posix()
        for path in (root / "scripts").glob("internal_deployment*.py")
    }
    entrypoints = {
        f"scripts/{name}"
        for name in (
            "ontologylab-internal-install",
            "ontologylab-internal-support",
            "ontologylab-internal-uninstall",
        )
        if (root / "scripts" / name).is_file()
    }
    return modules | entrypoints


def matching_internal_deployment_tests(root: Path) -> set[str]:
    """Discover every Task 10 test and controller-side support module."""
    tests = {
        path.relative_to(root).as_posix()
        for path in (root / "tests").glob("test_internal_deployment*.py")
    }
    support = root / "tests/internal_deployment_anchor_support.py"
    if support.is_file():
        tests.add(support.relative_to(root).as_posix())
    return tests


def _task10_master_files(root: Path) -> set[str]:
    master = json.loads(
        (
            root
            / ".omo/evidence/mac-desktop-deployment-roadmap/task-10"
            / "task-10-mac-desktop-deployment-roadmap.json"
        ).read_text(encoding="utf-8")
    )
    return {
        rel
        for rel in master.get("files", {})
        if isinstance(rel, str) and (root / rel).is_file()
    }


def _task12_sources(root: Path) -> set[str]:
    return {
        path.relative_to(root).as_posix()
        for pattern in ("release/task12_*.py", "scripts/retained_evidence*.py")
        for path in root.glob(pattern)
    }


def task11_policy_coverage(root: Path = ROOT) -> PolicyCoverage:
    """Enumerate every Task 10-12 source, workflow, test, and fixture file."""
    policy = json.loads(
        (root / "release" / "release-policy.json").read_text(encoding="utf-8")
    )
    declared = frozenset(policy["source_inputs"])
    candidate_modules = matching_candidate_modules(root)
    dependency_tests = _matching_tests(root, _DEPENDENCY_TEST_PATTERNS)
    product_contract_tests = _matching_tests(root, _PRODUCT_CONTRACT_TEST_PATTERNS)
    master = json.loads(
        (
            root
            / ".omo/evidence/mac-desktop-deployment-roadmap/task-11"
            / "task-11-mac-desktop-deployment-roadmap.json"
        ).read_text(encoding="utf-8")
    )
    master_files = {
        rel
        for rel in master.get("changed_files", {})
        if isinstance(rel, str)
        and rel.startswith((".github/", "release/", "scripts/", "tests/"))
        and (root / rel).is_file()
    }
    task10_files = (
        matching_internal_deployment_sources(root)
        | matching_internal_deployment_tests(root)
        | _task10_master_files(root)
    )
    roots = (
        candidate_modules
        | dependency_tests
        | master_files
        | task10_files
        | _task12_sources(root)
        | _PERFORMANCE_AUTHORITY
        | {
            ".github/workflows/macos-candidate.yml",
            "tests/macos_candidate_source_policy_support.py",
            "tests/macos_candidate_test_support.py",
        }
    )
    build_files: set[str] = set()
    for rel in _build_paths(root):
        build_files.update(_source_files(root, rel))
    shell_files = {
        path.relative_to(root).as_posix()
        for path in (root / "scripts").glob("build-macos-*.sh")
    }
    fixture_files = _source_files(root, "tests/fixtures/macos_supervisor")
    closure = (
        set(roots) | build_files | shell_files | fixture_files | product_contract_tests
    )
    pending = list(roots)
    while pending:
        rel = pending.pop()
        if not rel.endswith(".py"):
            continue
        for dependency in _local_imports(root, rel):
            if dependency not in closure:
                closure.add(dependency)
                pending.append(dependency)
    unsafe = frozenset(
        item
        for item in declared
        if item.startswith(("build", ".omo", "evidence", "artifacts", ".venv"))
        or "__pycache__" in item
        or item == "release/source-snapshot.json"
    )
    authoritative = frozenset(closure)
    missing = frozenset(rel for rel in authoritative if not covered(rel, declared))
    return PolicyCoverage(
        declared, authoritative, frozenset(task10_files), missing, unsafe
    )
