"""Generate causal ingestion mutation receipts from instrumented source runs."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final

from ontologylab.release_performance_types import (
    OutputCount,
    OutputSummary,
    parse_outputs,
)
from ontologylab.release_policy_types import JsonValue

_MUTATION_SOURCE: Final = "created_ids = tuple(entry.document.id for entry in result.entries if entry.created)"
_MUTATION_REPLACEMENT: Final = (
    "created_ids = tuple(entry.document.id for entry in result.entries)"
)
_OBSERVATION_SCHEMA: Final = "ontologylab.ingestion-mutation-observation.v1"


@dataclass(frozen=True, slots=True)
class MutationEvidenceRequest:
    source_root: Path
    work_root: Path
    receipt_path: Path
    source_snapshot_sha256: str
    fixture_manifest_sha256: str
    benchmark_protocol_sha256: str
    mutant_p95_ms: float
    ceiling_ms: float
    benchmark_outputs: OutputSummary


@dataclass(frozen=True, slots=True)
class MutationObservation:
    exit_code: int
    finalizations: int
    p95_ms: float
    outputs: OutputSummary


@dataclass(slots=True)
class MutationGenerationError(Exception):
    member: str
    exit_code: int | None = None
    stderr: str = field(default="", repr=False)

    def __str__(self) -> str:
        suffix = "" if self.exit_code is None else f" (child exit {self.exit_code})"
        return f"mutation generation failed: {self.member}{suffix}"


def _outputs_payload(outputs: OutputSummary) -> dict[str, JsonValue]:
    create = outputs.create
    duplicate = outputs.duplicate
    return {
        "create": {
            "entries": create.entries,
            "created": create.created,
            "conflicts": create.conflicts,
            "failures": create.failures,
        },
        "duplicate": {
            "entries": duplicate.entries,
            "created": duplicate.created,
            "conflicts": duplicate.conflicts,
            "failures": duplicate.failures,
        },
    }


def _parse_observation(stdout: str, exit_code: int) -> MutationObservation:
    try:
        raw: JsonValue = json.loads(stdout)
    except json.JSONDecodeError as exc:
        raise MutationGenerationError("observation.json") from exc
    if not isinstance(raw, dict):
        raise MutationGenerationError("observation")
    obj = raw
    if set(obj) != {"schema", "finalizations", "p95_ms", "outputs"}:
        raise MutationGenerationError("observation.fields")
    finalizations = obj["finalizations"]
    p95_ms = obj["p95_ms"]
    if (
        obj["schema"] != _OBSERVATION_SCHEMA
        or type(finalizations) is not int
        or finalizations < 0
        or isinstance(p95_ms, bool)
        or not isinstance(p95_ms, (int, float))
        or p95_ms <= 0
    ):
        raise MutationGenerationError("observation.values")
    return MutationObservation(
        exit_code=exit_code,
        finalizations=finalizations,
        p95_ms=float(p95_ms),
        outputs=parse_outputs(obj["outputs"], "observation.outputs"),
    )


def _run_observation(source_root: Path, work_root: Path) -> MutationObservation:
    env = os.environ.copy()
    existing = env.get("PYTHONPATH")
    env["PYTHONPATH"] = (
        f"{source_root}{os.pathsep}{existing}" if existing else str(source_root)
    )
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "ontologylab.release_mutation_evidence",
            "observe",
            "--work-root",
            str(work_root),
        ],
        cwd=source_root,
        env=env,
        check=False,
        capture_output=True,
        text=True,
        timeout=300,
    )
    try:
        return _parse_observation(completed.stdout, completed.returncode)
    except MutationGenerationError as error:
        error.exit_code = completed.returncode
        error.stderr = (completed.stderr or "")[-4096:]
        raise


def generate_mutation_receipt(request: MutationEvidenceRequest) -> dict[str, JsonValue]:
    """Run the normal and named mutant sources and write one causal receipt."""
    source = request.source_root / "ontologylab" / "ingestion.py"
    original = source.read_text(encoding="utf-8")
    if original.count(_MUTATION_SOURCE) != 1:
        raise MutationGenerationError("mutation_source")
    normal = _run_observation(request.source_root, request.work_root / "normal")
    try:
        source.write_text(
            original.replace(_MUTATION_SOURCE, _MUTATION_REPLACEMENT),
            encoding="utf-8",
        )
        mutant = _run_observation(request.source_root, request.work_root / "mutant")
    finally:
        source.write_text(original, encoding="utf-8")
    restored = source.read_text(encoding="utf-8") == original
    if normal.exit_code != 0:
        raise MutationGenerationError("normal.exit_code")
    if mutant.exit_code == 0:
        raise MutationGenerationError("mutant.exit_code")
    if normal.outputs != mutant.outputs:
        raise MutationGenerationError("mutant.outputs")
    if mutant.finalizations <= normal.finalizations:
        raise MutationGenerationError("mutant.finalizations")
    if not restored:
        raise MutationGenerationError("restored")
    causality: dict[str, JsonValue] = {
        "metric": "finalize_representation_calls",
        "fixture_documents": 40,
        "normal_expected_finalizations": normal.finalizations,
        "mutant_observed_finalizations": mutant.finalizations,
        "delta": mutant.finalizations - normal.finalizations,
        "relation": "mutant_observed_gt_normal_expected",
        "test_failure": "finalization_count_mismatch",
        "normal_outputs": _outputs_payload(normal.outputs),
        "mutant_outputs": _outputs_payload(mutant.outputs),
    }
    receipt: dict[str, JsonValue] = {
        "schema": "ontologylab.ingestion-performance-mutation.v2",
        "source_snapshot_sha256": request.source_snapshot_sha256,
        "fixture_manifest_sha256": request.fixture_manifest_sha256,
        "benchmark_protocol_sha256": request.benchmark_protocol_sha256,
        "mutation_id": "restore-unbatched-duplicate-refinalization",
        "p95_ms": request.mutant_p95_ms,
        "ceiling_ms": request.ceiling_ms,
        "test_exit": mutant.exit_code,
        "outputs": _outputs_payload(request.benchmark_outputs),
        "restored": restored,
        "causality": causality,
    }
    request.receipt_path.parent.mkdir(parents=True, exist_ok=True)
    request.receipt_path.write_text(
        json.dumps(receipt, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return receipt


def _observe(work_root: Path) -> int:
    from ontologylab import ingestion as ingestion_module
    from ontologylab.kgstore import KGStore
    from tests.wave21.ingest_perf import measure_current_ingest

    real_finalize = ingestion_module.finalize_ingest_writes
    finalizations = 0

    def observe_finalize(
        store: KGStore,
        representation_ids: Sequence[str] = (),
        *,
        staging_operation_id: str | None = None,
    ) -> None:
        nonlocal finalizations
        finalizations += len(tuple(dict.fromkeys(representation_ids)))
        real_finalize(
            store,
            representation_ids,
            staging_operation_id=staging_operation_id,
        )

    ingestion_module.finalize_ingest_writes = observe_finalize
    measured = measure_current_ingest(work_root, document_count=40, n=1)
    create, duplicate = measured.outputs
    outputs = OutputSummary(
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
    print(
        json.dumps(
            {
                "schema": _OBSERVATION_SCHEMA,
                "finalizations": finalizations,
                "p95_ms": measured.p95_ms,
                "outputs": _outputs_payload(outputs),
            },
            sort_keys=True,
        )
    )
    return int(finalizations != outputs.create.created)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("observe",))
    parser.add_argument("--work-root", type=Path, required=True)
    args = parser.parse_args(argv)
    return _observe(args.work_root)


if __name__ == "__main__":
    sys.exit(main())
