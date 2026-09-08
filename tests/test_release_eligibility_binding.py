"""Task 13 exact-dirty eligibility authority regression probes."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from ontologylab.release_policy import check
from ontologylab.release_policy_types import ReleasePolicyRefused
from tests.release_eligibility_fixtures import (
    EVIDENCE_REL,
    MUTATION_REL,
    PROTOCOL_REL,
    bound_go_root,
    mutate_receipt,
)
from tests.wave21.perf import MANIFEST_PATH


@pytest.mark.parametrize(
    "mutate",
    [
        lambda p: p["source"].update({"snapshot_manifest_sha256": "0" * 64}),
        lambda p: p["source"].update({"inventory_sha256": "0" * 64}),
        lambda p: p["source"].update({"git_status_sha256": "0" * 64}),
        lambda p: p["source"].update({"git_staged_diff_sha256": "0" * 64}),
        lambda p: p["source"].update({"git_unstaged_diff_sha256": "0" * 64}),
        lambda p: p["source"].update({"uv_lock_sha256": "0" * 64}),
        lambda p: p["source"].update({"policy_sha256": "0" * 64}),
        lambda p: p["fixture"].update({"manifest_sha256": "0" * 64}),
        lambda p: p["fixture"].update({"semantics_sha256": "0" * 64}),
        lambda p: p["benchmark"].update({"protocol_sha256": "0" * 64}),
        lambda p: p["performance"].update({"ceiling_ms": 999999.0}),
        lambda p: p["performance"].update({"samples_ms": [1.0, 2.0, 3.0]}),
        lambda p: p["performance"].update({"p95_ms": 1.0}),
        lambda p: p["performance"].update({"statistic": "median"}),
        lambda p: p["performance"].update({"evidence_sha256": "0" * 64}),
        lambda p: p["performance"].update({"mutation_receipt_sha256": "0" * 64}),
        lambda p: p["performance"]["outputs"]["create"].update({"created": 0}),
    ],
)
def test_check_refuses_release_critical_receipt_drift(
    tmp_path: Path, mutate: Callable[[dict[str, Any]], None]
) -> None:
    root = bound_go_root(tmp_path)
    check(root)
    mutate_receipt(root, mutate)
    with pytest.raises(ReleasePolicyRefused) as raised:
        check(root)
    assert str(raised.value.code) == "eligibility_field_drift"


@pytest.mark.parametrize(
    "mutate",
    [
        lambda p: p["toolchain"].update({"python": "0.0.0"}),
        lambda p: p["toolchain"].update({"implementation": "OtherPython"}),
        lambda p: p["toolchain"].update({"machine": "other-machine"}),
        lambda p: p["toolchain"].update({"platform": "other-platform"}),
    ],
)
def test_check_refuses_toolchain_drift(
    tmp_path: Path, mutate: Callable[[dict[str, Any]], None]
) -> None:
    root = bound_go_root(tmp_path)
    mutate_receipt(root, mutate)
    with pytest.raises(ReleasePolicyRefused) as raised:
        check(root)
    assert str(raised.value.code) == "toolchain_identity_drift"


@pytest.mark.parametrize(
    "relative_path",
    [
        MANIFEST_PATH.relative_to(MANIFEST_PATH.parents[3]).as_posix(),
        PROTOCOL_REL,
        EVIDENCE_REL,
        MUTATION_REL,
    ],
)
def test_check_refuses_changed_bound_artifact(
    tmp_path: Path, relative_path: str
) -> None:
    root = bound_go_root(tmp_path)
    path = root / relative_path
    path.write_bytes(path.read_bytes() + b"\n")
    with pytest.raises(ReleasePolicyRefused):
        check(root)


def _mutate_bound_mutation(
    root: Path, mutate: Callable[[dict[str, Any]], None]
) -> None:
    path = root / MUTATION_REL
    payload = json.loads(path.read_text(encoding="utf-8"))
    mutate(payload)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    mutate_receipt(
        root,
        lambda receipt: receipt["performance"].update(
            {"mutation_receipt_sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
        ),
    )


@pytest.mark.parametrize(
    "mutate",
    [
        lambda payload: payload.pop("causality"),
        lambda payload: payload.update({"test_exit": 0}),
        lambda payload: payload["causality"].update(
            {"test_failure": "unrelated_nonzero_exit"}
        ),
        lambda payload: payload["causality"].update(
            {"mutant_observed_finalizations": 38, "delta": 0}
        ),
        lambda payload: payload["causality"].update(
            {"mutant_observed_finalizations": 37, "delta": 1}
        ),
        lambda payload: payload["causality"].update(
            {"relation": "normal_expected_gt_mutant_observed"}
        ),
        lambda payload: payload["causality"].update({"delta": 37}),
        lambda payload: payload.update({"restored": False}),
        lambda payload: payload["causality"]["mutant_outputs"]["duplicate"].update(
            {"failures": 1}
        ),
    ],
)
def test_check_refuses_noncausal_mutation_receipt(
    tmp_path: Path, mutate: Callable[[dict[str, Any]], None]
) -> None:
    # Given: an otherwise hash-bound release with one causal mutation defect.
    root = bound_go_root(tmp_path)
    _mutate_bound_mutation(root, mutate)

    # When/Then: the bound release authority refuses the mutation evidence.
    with pytest.raises(ReleasePolicyRefused):
        check(root)


def test_check_refuses_missing_and_extra_receipt_fields(tmp_path: Path) -> None:
    root = bound_go_root(tmp_path)
    mutate_receipt(root, lambda p: p.pop("toolchain"))
    with pytest.raises(ReleasePolicyRefused) as missing:
        check(root)
    assert str(missing.value.code) == "eligibility_receipt_malformed"

    root = bound_go_root(tmp_path / "extra")
    mutate_receipt(root, lambda p: p.update({"unbound": True}))
    with pytest.raises(ReleasePolicyRefused) as extra:
        check(root)
    assert str(extra.value.code) == "eligibility_receipt_malformed"


def test_exact_dirty_snapshot_refuses_tracked_and_untracked_later_drift(
    tmp_path: Path,
) -> None:
    tracked = bound_go_root(tmp_path / "tracked")
    check(tracked)
    path = tracked / "ontologylab" / "__init__.py"
    path.write_text(path.read_text(encoding="utf-8") + "# later drift\n")
    with pytest.raises(ReleasePolicyRefused):
        check(tracked)

    untracked = bound_go_root(tmp_path / "untracked")
    check(untracked)
    (untracked / "web" / "later.js").write_text("// later\n")
    with pytest.raises(ReleasePolicyRefused):
        check(untracked)
