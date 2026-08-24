"""Wave 2.1 Step 10 deterministic roots and capability claims."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from ontologylab.pack_readiness import (
    PackReadinessCode,
    PackReadinessRefused,
    authorize_publication,
)
from ontologylab.pack_verifier import verify_pack
from ontologylab.packbuilder import build_pack
from tests.test_pack_readiness_refusal import _ready_fixture, _request_sourced
from tests.test_pack_v2_publication_surface import _reviewed_pack

_REVIEWED = "reviewed"
_SOURCED = "sourced-answer-v2"
_RELEASE_RECEIPT = (
    Path(__file__).parent
    / "fixtures"
    / "wave21"
    / "step10-release-receipt-v1.json"
)


def _release_payload_root(
    closure: dict[str, tuple[str, ...]],
    policy: dict[str, str],
) -> str:
    payload = {
        "closure": {
            key: sorted(closure[key])
            for key in sorted(closure)
        },
        "policy": {key: policy[key] for key in sorted(policy)},
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _manifest(pack_dir: Path) -> dict[str, object]:
    return json.loads((pack_dir / "manifest.json").read_text(encoding="utf-8"))


def _capabilities(pack_dir: Path) -> tuple[str, ...]:
    value = _manifest(pack_dir)["capabilities"]
    assert isinstance(value, list)
    assert all(isinstance(item, str) for item in value)
    return tuple(value)


def _closure(pack_dir: Path) -> dict[str, tuple[str, ...]]:
    value = _manifest(pack_dir)["closure"]
    assert isinstance(value, dict)
    closure: dict[str, tuple[str, ...]] = {}
    for key, items in value.items():
        assert isinstance(key, str)
        assert isinstance(items, list)
        assert all(isinstance(item, str) for item in items)
        closure[key] = tuple(items)
    return closure


def _verified_pack_root(pack_dir: Path) -> str:
    value = _manifest(pack_dir)["pack_content_hash"]
    assert isinstance(value, str)
    assert verify_pack(pack_dir).pack_content_hash == value
    return value


def test_release_payload_root_binds_representation_and_policy() -> None:
    closure = {
        "representation": ("representation-1",),
        "policy": ("sha256:" + "a" * 64,),
    }
    policy = {"evidence_mode": "full", "schema": "pack-v2"}
    root = _release_payload_root(closure, policy)

    assert _release_payload_root(dict(closure), dict(policy)) == root
    assert _release_payload_root(
        {**closure, "representation": ("representation-2",)},
        policy,
    ) != root
    assert _release_payload_root(
        closure,
        {**policy, "evidence_mode": "excerpt"},
    ) != root


def test_same_snapshot_and_policy_keep_release_payload_root(tmp_path: Path) -> None:
    fixture = _ready_fixture(tmp_path / "kg")
    packs = tmp_path / "packs"
    try:
        first = build_pack(fixture.kg, packs, name="same-a", evidence_mode="full")
        second = build_pack(fixture.kg, packs, name="same-b", evidence_mode="full")
    finally:
        fixture.store.close()

    first_dir = packs / first.pack_id
    second_dir = packs / second.pack_id
    first_closure = _closure(first_dir)
    second_closure = _closure(second_dir)
    policy = {"evidence_mode": "full", "schema": "pack-v2"}
    assert first_closure == second_closure
    assert _release_payload_root(first_closure, policy) == _release_payload_root(
        second_closure,
        policy,
    )
    _verified_pack_root(first_dir)
    _verified_pack_root(second_dir)


def test_changed_policy_produces_new_release_payload_root(tmp_path: Path) -> None:
    fixture = _ready_fixture(tmp_path / "kg")
    packs = tmp_path / "packs"
    try:
        full = build_pack(fixture.kg, packs, name="full", evidence_mode="full")
        excerpt = build_pack(
            fixture.kg,
            packs,
            name="excerpt",
            evidence_mode="excerpt",
        )
    finally:
        fixture.store.close()

    full_dir = packs / full.pack_id
    excerpt_dir = packs / excerpt.pack_id
    full_closure = _closure(full_dir)
    excerpt_closure = _closure(excerpt_dir)
    assert _release_payload_root(
        full_closure,
        {"evidence_mode": "full", "schema": "pack-v2"},
    ) != _release_payload_root(
        excerpt_closure,
        {"evidence_mode": "excerpt", "schema": "pack-v2"},
    )
    _verified_pack_root(full_dir)
    _verified_pack_root(excerpt_dir)


def test_release_capabilities_follow_verified_c036_closure(
    tmp_path: Path,
) -> None:
    unreviewed = _ready_fixture(tmp_path / "unreviewed")
    unreviewed_packs = tmp_path / "unreviewed-packs"
    try:
        unreviewed_manifest = build_pack(
            unreviewed.kg,
            unreviewed_packs,
            name="unreviewed",
            evidence_mode="full",
        )
    finally:
        unreviewed.store.close()
    unreviewed_caps = _capabilities(
        unreviewed_packs / unreviewed_manifest.pack_id
    )
    assert _REVIEWED not in unreviewed_caps
    assert _SOURCED not in unreviewed_caps

    reviewed_packs, reviewed_id = _reviewed_pack(tmp_path, name="reviewed")
    reviewed_caps = _capabilities(reviewed_packs / reviewed_id)
    assert _REVIEWED in reviewed_caps
    assert _SOURCED in reviewed_caps
    verify_pack(reviewed_packs / reviewed_id)

    missing = _ready_fixture(tmp_path / "missing-c036")
    try:
        _request_sourced(missing.store.conn)
        missing.store.conn.commit()
        with pytest.raises(PackReadinessRefused) as raised:
            authorize_publication(missing.store.conn)
        assert raised.value.code is PackReadinessCode.C036_REQUIRED
    finally:
        missing.store.close()


def test_release_receipt_enforces_thresholds_roots_and_claims() -> None:
    receipt = json.loads(_RELEASE_RECEIPT.read_text(encoding="utf-8"))
    assert receipt["schema"] == "ontologylab.wave21.step10-release-receipt.v1"
    assert (
        receipt["recipe_anchor"]["manifest_sha256"]
        == "019a986f878bcba5b2ba8c67a1451d8fc19af021988e28bdd9f7e2287f82f0b1"
    )

    performance = receipt["performance"]
    target = performance["target_v2_migration"]
    assert target["current_p95_ms"] <= (
        target["historical_p95_ms"]
        * (1 + performance["p95_regression_limit_percent"] / 100)
    )
    increase_percent = (
        target["current_disk_bytes"] / target["historical_disk_bytes"] - 1
    ) * 100
    assert increase_percent <= performance[
        "payload_increase_approval_threshold_percent"
    ]
    assert target["approval_required"] is False

    ingest = performance["current_ingest_create_and_duplicate"]
    assert ingest["sample_active_lower_bound_ms"] > ingest["ceiling_ms"]
    assert ingest["status"] == "refused"

    roots = receipt["determinism"]
    assert roots["same_snapshot_policy_root_a"] == roots[
        "same_snapshot_policy_root_b"
    ]
    assert roots["changed_policy_root"] != roots["same_snapshot_policy_root_a"]
    assert roots["changed_representation_root"] != roots[
        "same_snapshot_policy_root_a"
    ]

    capabilities = receipt["capabilities"]
    assert capabilities["unreviewed"] == [
        "knowledge-graph-v2",
        "evidence-self-contained-v2",
    ]
    assert capabilities["reviewed_c036"] == [
        "knowledge-graph-v2",
        "evidence-self-contained-v2",
        "reviewed",
        "sourced-answer-v2",
    ]
    assert capabilities["missing_c036"] == "refused"

    release = receipt["release"]
    assert release["go"] is False
    assert release["production_authorized"] is False
    assert release["stop_token"] == "STOP_BEFORE_STEP_9C"
