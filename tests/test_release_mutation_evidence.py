"""Causal mutation receipt generation through real instrumented ingestion."""

from __future__ import annotations

import shutil
from pathlib import Path

from ontologylab.release_mutation_evidence import (
    MutationEvidenceRequest,
    generate_mutation_receipt,
)
from ontologylab.release_performance_types import OutputCount, OutputSummary

_REPO = Path(__file__).resolve().parents[1]
_BENCHMARK_OUTPUTS = OutputSummary(
    create=OutputCount(entries=9500, created=9500, conflicts=500, failures=0),
    duplicate=OutputCount(entries=9500, created=0, conflicts=500, failures=0),
)


def test_generator_emits_causal_counts_and_restores_disposable_source(
    tmp_path: Path,
) -> None:
    # Given: a disposable source tree containing the production path and fixture driver.
    source_root = tmp_path / "source"
    shutil.copytree(_REPO / "ontologylab", source_root / "ontologylab")
    shutil.copytree(_REPO / "tests" / "wave21", source_root / "tests" / "wave21")
    ingestion = source_root / "ontologylab" / "ingestion.py"
    original = ingestion.read_bytes()
    receipt_path = tmp_path / "mutation-receipt.json"

    # When: the named duplicate-refinalization mutant is run under instrumentation.
    receipt = generate_mutation_receipt(
        MutationEvidenceRequest(
            source_root=source_root,
            work_root=tmp_path / "runs",
            receipt_path=receipt_path,
            source_snapshot_sha256="1" * 64,
            fixture_manifest_sha256="2" * 64,
            benchmark_protocol_sha256="3" * 64,
            mutant_p95_ms=9000.0,
            ceiling_ms=10195.704249618575,
            benchmark_outputs=_BENCHMARK_OUTPUTS,
        )
    )

    # Then: machine fields prove 76 > 38 and the exact source bytes are restored.
    causality = receipt["causality"]
    assert isinstance(causality, dict)
    assert causality["normal_expected_finalizations"] == 38
    assert causality["mutant_observed_finalizations"] == 76
    assert causality["delta"] == 38
    assert causality["relation"] == "mutant_observed_gt_normal_expected"
    assert receipt["test_exit"] == 1
    assert receipt["restored"] is True
    assert receipt_path.is_file()
    assert ingestion.read_bytes() == original
