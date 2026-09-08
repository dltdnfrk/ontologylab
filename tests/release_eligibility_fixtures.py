"""Disposable exact-dirty release eligibility fixtures."""

from __future__ import annotations

import hashlib
import json
import os
import platform
import subprocess
from collections.abc import Callable
from dataclasses import asdict
from pathlib import Path
from typing import Any

from ontologylab.release_policy import load_policy, read_version
from ontologylab.release_policy_types import JsonValue
from ontologylab.release_snapshot import write_snapshot
from release.candidate_source_closure import copy_policy_inputs
from tests.test_release_policy import POLICY_REL, REPO, _policy_payload, _write_json
from tests.wave21.perf import MANIFEST_PATH

PROTOCOL_REL = "release/ingestion-performance-protocol.json"
EVIDENCE_REL = "evidence/task13-performance.json"
MUTATION_REL = "evidence/task13-mutation.json"
RECEIPT_REL = "tests/fixtures/wave21/step10-release-receipt-v1.json"
CEILING_MS = 10195.704249618575
OUTPUTS: dict[str, JsonValue] = {
    "create": {"entries": 9500, "created": 9500, "conflicts": 500, "failures": 0},
    "duplicate": {"entries": 9500, "created": 0, "conflicts": 500, "failures": 0},
}
CAUSAL_OUTPUTS: dict[str, JsonValue] = {
    "create": {"entries": 38, "created": 38, "conflicts": 2, "failures": 0},
    "duplicate": {"entries": 38, "created": 0, "conflicts": 2, "failures": 0},
}


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def fixture_semantics_sha(path: Path) -> str:
    payload = json.loads(path.read_text(encoding="utf-8"))
    dataset = payload["dataset"]
    operations = {
        item["id"]: (item["kind"], item["n"]) for item in payload["operations"]
    }
    semantics = {
        "recipe_id": payload["recipe_id"],
        "seed": payload["seed"],
        "dataset": {
            "documents": dataset["documents"],
            "legacy_doi_resolver_rows": dataset["legacy_doi_resolver_rows"],
            "doi_collision_ratio": dataset["doi_collision_ratio"],
            "same_bytes_different_doi_ratio": dataset["same_bytes_different_doi_ratio"],
        },
        "operations": {key: operations[key] for key in sorted(operations)},
        "forbidden": sorted(payload["forbidden"]),
    }
    encoded = json.dumps(semantics, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _git(root: Path, *args: str) -> bytes:
    env = {
        "PATH": os.environ["PATH"],
        "HOME": str(root),
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_CONFIG_SYSTEM": os.devnull,
    }
    return subprocess.run(
        ["git", "-C", str(root), *args],
        check=True,
        capture_output=True,
        env=env,
    ).stdout


def _git_hash(root: Path, *args: str) -> str:
    return hashlib.sha256(_git(root, *args)).hexdigest()


def _write_fixture_source(root: Path) -> Path:
    copy_policy_inputs(REPO, root)
    for rel, body in {
        "ontologylab/__init__.py": "__version__ = 'fixture'\n",
        "web/index.html": "<html>fixture</html>\n",
        "launcher/README.md": "fixture launcher\n",
        "release/licenses/NOTICE.txt": "fixture license notice\n",
    }.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8")
    fixture = root / MANIFEST_PATH.relative_to(REPO)
    fixture.parent.mkdir(parents=True, exist_ok=True)
    fixture.write_bytes(MANIFEST_PATH.read_bytes())
    authority = _policy_payload()["task10_authority"]
    assert isinstance(authority, dict)
    report_rel = authority["report_path"]
    assert isinstance(report_rel, str)
    report = root / report_rel
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_bytes((REPO / report_rel).read_bytes())
    return fixture


def _write_policy_and_protocol(root: Path, fixture: Path) -> None:
    protocol_payload: dict[str, JsonValue] = {
        "schema": "ontologylab.ingestion-performance-protocol.v1",
        "operation": "current_ingest_create_and_duplicate",
        "fixture_path": fixture.relative_to(root).as_posix(),
        "recipe_id": "wave21-perf-v1",
        "seed": 20260820,
        "documents": 10000,
        "samples": 3,
        "scratch": {
            "cloud_sync": False,
            "filesystem": "apfs",
            "path_prefix": "/private/tmp",
        },
        "statistic": "nearest-rank-p95",
        "ceiling_ms": CEILING_MS,
        "outputs": OUTPUTS,
        "fixture_semantics_sha256": fixture_semantics_sha(fixture),
    }
    _write_json(root, PROTOCOL_REL, protocol_payload)
    policy = _policy_payload()
    policy["source_inputs"].extend([fixture.relative_to(root).as_posix(), PROTOCOL_REL])
    policy["performance_contract"] = {
        "fixture_manifest_path": fixture.relative_to(root).as_posix(),
        "benchmark_protocol_path": PROTOCOL_REL,
        "performance_evidence_path": EVIDENCE_REL,
        "mutation_receipt_path": MUTATION_REL,
    }
    _write_json(root, POLICY_REL, policy)


def _git_source_identity(root: Path, source_inputs: tuple[str, ...]) -> dict[str, str]:
    suffix = ("--", *source_inputs)
    return {
        "git_status_sha256": _git_hash(
            root, "status", "--porcelain=v1", "-z", "--untracked-files=all", *suffix
        ),
        "git_staged_diff_sha256": _git_hash(
            root, "diff", "--cached", "--binary", "--no-ext-diff", *suffix
        ),
        "git_unstaged_diff_sha256": _git_hash(
            root, "diff", "--binary", "--no-ext-diff", *suffix
        ),
    }


def bound_go_root(tmp_path: Path) -> Path:
    """Build one valid GO whose tracked and untracked dirty bytes are exact."""
    root = tmp_path / "fixture"
    root.mkdir(parents=True)
    fixture = _write_fixture_source(root)
    _write_policy_and_protocol(root, fixture)
    _git(root, "init", "-q")
    _git(root, "add", "-A")
    _git(
        root,
        "-c",
        "user.email=qa@example.invalid",
        "-c",
        "user.name=qa",
        "commit",
        "-qm",
        "base",
    )
    (root / "ontologylab" / "__init__.py").write_text(
        "__version__ = 'fixture-dirty'\n", encoding="utf-8"
    )
    (root / "ontologylab" / "local_plugin.py").write_text(
        "VALUE = 'untracked-source-input'\n", encoding="utf-8"
    )
    policy = load_policy(root)
    manifest = write_snapshot(root, policy, read_version(root, policy))
    manifest_path = root / policy.snapshot_manifest_path
    samples = [5000.0, 5100.0, 5200.0]
    toolchain = {
        "implementation": platform.python_implementation(),
        "python": platform.python_version(),
        "machine": platform.machine(),
        "platform": platform.platform(),
    }
    evidence = {
        "schema": "ontologylab.ingestion-performance-evidence.v1",
        "source_snapshot_sha256": manifest.snapshot_sha256,
        "fixture_manifest_sha256": _sha(fixture),
        "benchmark_protocol_sha256": _sha(root / PROTOCOL_REL),
        "toolchain": toolchain,
        "samples_ms": samples,
        "statistic": "nearest-rank-p95",
        "p95_ms": max(samples),
        "ceiling_ms": CEILING_MS,
        "outputs": OUTPUTS,
        "status": "pass",
    }
    mutation = {
        "schema": "ontologylab.ingestion-performance-mutation.v2",
        "source_snapshot_sha256": manifest.snapshot_sha256,
        "fixture_manifest_sha256": _sha(fixture),
        "benchmark_protocol_sha256": _sha(root / PROTOCOL_REL),
        "mutation_id": "restore-unbatched-duplicate-refinalization",
        "p95_ms": 18000.0,
        "ceiling_ms": CEILING_MS,
        "test_exit": 1,
        "outputs": OUTPUTS,
        "restored": True,
        "causality": {
            "metric": "finalize_representation_calls",
            "fixture_documents": 40,
            "normal_expected_finalizations": 38,
            "mutant_observed_finalizations": 76,
            "delta": 38,
            "relation": "mutant_observed_gt_normal_expected",
            "test_failure": "finalization_count_mismatch",
            "normal_outputs": CAUSAL_OUTPUTS,
            "mutant_outputs": CAUSAL_OUTPUTS,
        },
    }
    _write_json(root, EVIDENCE_REL, evidence)
    _write_json(root, MUTATION_REL, mutation)
    source = {
        "snapshot_sha256": manifest.snapshot_sha256,
        "snapshot_manifest_sha256": _sha(manifest_path),
        "inventory_sha256": manifest.inventory_sha256,
        **_git_source_identity(root, policy.source_inputs),
        "uv_lock_sha256": manifest.uv_lock.sha256,
        "policy_sha256": manifest.policy_sha256,
    }
    receipt = {
        "schema": "ontologylab.release.eligibility.v2",
        "version": read_version(root, policy),
        "source_snapshot_sha256": manifest.snapshot_sha256,
        "source": source,
        "task10_authority": asdict(policy.task10_authority),
        "fixture": {
            "manifest_sha256": _sha(fixture),
            "semantics_sha256": fixture_semantics_sha(fixture),
        },
        "benchmark": {"protocol_sha256": _sha(root / PROTOCOL_REL)},
        "toolchain": toolchain,
        "performance": {
            "evidence_sha256": _sha(root / EVIDENCE_REL),
            "mutation_receipt_sha256": _sha(root / MUTATION_REL),
            "samples_ms": samples,
            "statistic": "nearest-rank-p95",
            "p95_ms": max(samples),
            "ceiling_ms": CEILING_MS,
            "outputs": OUTPUTS,
        },
        "release": {"go": True, "production_authorized": True, "reasons": []},
    }
    _write_json(root, RECEIPT_REL, receipt)
    return root


def mutate_receipt(root: Path, mutate: Callable[[dict[str, Any]], None]) -> None:
    path = root / RECEIPT_REL
    payload = json.loads(path.read_text(encoding="utf-8"))
    mutate(payload)
    _write_json(root, RECEIPT_REL, payload)
