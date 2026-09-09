"""Issue the release eligibility receipt from freshly measured evidence.

Until now the only thing that could produce an
``ontologylab.release.eligibility.v2`` receipt was a one-off driver script
under ``.omo/evidence/``. That left the gate in a bad position: whenever the
source snapshot changed, the honest way to re-issue the receipt was to go
archaeology in an evidence directory, and the dishonest way -- hand-editing
the recorded hashes -- produced a receipt asserting ``production_authorized``
over performance numbers nobody re-measured.

This module is the supported path. Every number in the receipt is either
measured here or read from the policy and the benchmark protocol; nothing is
carried over from a previous receipt. When a gate fails the receipt is not
written at all, because a receipt that exists is a claim that it passed.
"""

from __future__ import annotations

import json
import platform
import shutil
from pathlib import Path
from typing import Any

from ontologylab.release_mutation_evidence import (
    MutationEvidenceRequest,
    _outputs_payload,
    generate_mutation_receipt,
)
from ontologylab.release_performance_types import OutputCount, OutputSummary
from ontologylab.release_policy import load_policy, read_version
from ontologylab.release_snapshot import _sha256_file, write_snapshot

_ELIGIBILITY_SCHEMA = "ontologylab.release.eligibility.v2"
_EVIDENCE_SCHEMA = "ontologylab.ingestion-performance-evidence.v1"
_EXPECTED_FINALIZATIONS = 38


class EligibilityIssueRefused(Exception):
    """A gate failed, so no receipt was written."""

    def __init__(self, gate: str, detail: object) -> None:
        super().__init__(f"{gate}: {detail}")
        self.gate = gate
        self.detail = detail


def _summarize(outputs) -> OutputSummary:
    create, duplicate = outputs
    return OutputSummary(
        create=OutputCount(
            entries=create.entries,
            created=create.created,
            conflicts=create.conflicts,
            failures=create.failures,
        ),
        duplicate=OutputCount(
            entries=duplicate.entries,
            created=duplicate.created,
            conflicts=duplicate.conflicts,
            failures=duplicate.failures,
        ),
    )


def _toolchain() -> dict[str, str]:
    return {
        "implementation": platform.python_implementation(),
        "python": platform.python_version(),
        "machine": platform.machine(),
        "platform": platform.platform(),
    }


def _write_json(path: Path, payload: dict[str, Any]) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return _sha256_file(path)


def issue_eligibility_receipt(root: Path, *, work_root: Path) -> dict[str, Any]:
    """Measure, gate, then write the receipt. Refuses instead of degrading."""
    policy = load_policy(root)
    protocol = json.loads(
        (root / policy.benchmark_protocol_path).read_text(encoding="utf-8")
    )
    manifest = write_snapshot(root, policy, read_version(root, policy))
    snapshot_path = root / policy.snapshot_manifest_path

    # Imported here, as release_mutation_evidence already does: the benchmark
    # recipe lives with the fixtures it replays, and importing it at module
    # scope would make the release tooling unimportable without the test tree.
    from tests.wave21.ingest_perf import measure_current_ingest

    measured = measure_current_ingest(
        work_root / "perf",
        document_count=protocol["documents"],
        n=protocol["samples"],
    )
    summary = _summarize(measured.outputs)
    outputs = _outputs_payload(summary)
    ceiling_ms = protocol["ceiling_ms"]

    if measured.p95_ms > ceiling_ms:
        raise EligibilityIssueRefused(
            "performance", {"p95_ms": measured.p95_ms, "ceiling_ms": ceiling_ms}
        )
    if outputs != protocol["outputs"]:
        raise EligibilityIssueRefused(
            "outputs", {"measured": outputs, "expected": protocol["outputs"]}
        )

    evidence = {
        "schema": _EVIDENCE_SCHEMA,
        "source_snapshot_sha256": manifest.snapshot_sha256,
        "fixture_manifest_sha256": _sha256_file(root / policy.fixture_manifest_path),
        "benchmark_protocol_sha256": _sha256_file(
            root / policy.benchmark_protocol_path
        ),
        "toolchain": _toolchain(),
        "samples_ms": list(measured.samples_ms),
        "statistic": protocol["statistic"],
        "p95_ms": measured.p95_ms,
        "ceiling_ms": ceiling_ms,
        "outputs": outputs,
        "status": "pass",
    }

    source_root = work_root / "source-tree"
    if not (source_root / "ontologylab").is_dir():
        shutil.copytree(root / "ontologylab", source_root / "ontologylab")
        shutil.copytree(root / "tests" / "wave21", source_root / "tests" / "wave21")
    mutation_tmp = work_root / "mutation-receipt.json"
    mutation = generate_mutation_receipt(
        MutationEvidenceRequest(
            source_root=source_root,
            work_root=work_root / "mutation",
            receipt_path=mutation_tmp,
            source_snapshot_sha256=manifest.snapshot_sha256,
            fixture_manifest_sha256=evidence["fixture_manifest_sha256"],
            benchmark_protocol_sha256=evidence["benchmark_protocol_sha256"],
            mutant_p95_ms=measured.p95_ms,
            ceiling_ms=ceiling_ms,
            benchmark_outputs=summary,
        )
    )
    causality = mutation.get("causality")
    if not isinstance(causality, dict):
        raise EligibilityIssueRefused("mutation-type", type(causality).__name__)
    if causality.get("normal_expected_finalizations") != _EXPECTED_FINALIZATIONS:
        raise EligibilityIssueRefused("mutation", causality)

    _write_json(root / policy.performance_evidence_path, evidence)
    canonical_mutation = root / policy.mutation_receipt_path
    canonical_mutation.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(mutation_tmp, canonical_mutation)

    receipt = {
        "schema": _ELIGIBILITY_SCHEMA,
        "version": manifest.version,
        "source_snapshot_sha256": manifest.snapshot_sha256,
        "source": {
            "snapshot_sha256": manifest.snapshot_sha256,
            "snapshot_manifest_sha256": _sha256_file(snapshot_path),
            "inventory_sha256": manifest.inventory_sha256,
            "git_status_sha256": manifest.git_status_sha256,
            "git_staged_diff_sha256": manifest.git_staged_diff_sha256,
            "git_unstaged_diff_sha256": manifest.git_unstaged_diff_sha256,
            "uv_lock_sha256": manifest.uv_lock.sha256,
            "policy_sha256": manifest.policy_sha256,
        },
        "task10_authority": {
            "plan": policy.task10_authority.plan,
            "report_path": policy.task10_authority.report_path,
            "report_sha256": policy.task10_authority.report_sha256,
            "task": policy.task10_authority.task,
            "task_id": policy.task10_authority.task_id,
            "verdict": policy.task10_authority.verdict,
        },
        "fixture": {
            "manifest_sha256": evidence["fixture_manifest_sha256"],
            "semantics_sha256": protocol["fixture_semantics_sha256"],
        },
        "benchmark": {"protocol_sha256": evidence["benchmark_protocol_sha256"]},
        "toolchain": evidence["toolchain"],
        "performance": {
            "evidence_sha256": _sha256_file(root / policy.performance_evidence_path),
            "mutation_receipt_sha256": _sha256_file(canonical_mutation),
            "samples_ms": evidence["samples_ms"],
            "statistic": evidence["statistic"],
            "p95_ms": measured.p95_ms,
            "ceiling_ms": ceiling_ms,
            "outputs": outputs,
        },
        "release": {"go": True, "production_authorized": True, "reasons": []},
    }
    _write_json(root / policy.eligibility_receipt_path, receipt)
    return receipt


def main(argv: list[str] | None = None) -> int:
    import argparse
    import sys
    import tempfile

    parser = argparse.ArgumentParser(
        prog="release.eligibility_issuer",
        description=(
            "Re-measure the ingestion benchmark and issue the release "
            "eligibility receipt. Refuses to write anything if a gate fails."
        ),
    )
    parser.add_argument("--root", default=".", help="Repository root.")
    parser.add_argument(
        "--work-root",
        default=None,
        help=(
            "Scratch directory for the benchmark. Must live under "
            "/private/tmp; a temporary directory is used when omitted."
        ),
    )
    args = parser.parse_args(argv)

    with tempfile.TemporaryDirectory(dir="/private/tmp") as tmp:
        work_root = Path(args.work_root) if args.work_root else Path(tmp)
        try:
            receipt = issue_eligibility_receipt(
                Path(args.root), work_root=work_root
            )
        except EligibilityIssueRefused as refusal:
            json.dump(
                {
                    "schema": "ontologylab.release.eligibility-refused.v1",
                    "status": "refused",
                    "gate": refusal.gate,
                    "detail": refusal.detail,
                },
                sys.stdout,
                indent=2,
                sort_keys=True,
            )
            sys.stdout.write("\n")
            return 1

    json.dump(
        {
            "schema": "ontologylab.release.eligibility-issued.v1",
            "status": "issued",
            "source_snapshot_sha256": receipt["source_snapshot_sha256"],
            "p95_ms": receipt["performance"]["p95_ms"],
            "ceiling_ms": receipt["performance"]["ceiling_ms"],
        },
        sys.stdout,
        indent=2,
        sort_keys=True,
    )
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
