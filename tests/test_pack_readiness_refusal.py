"""F11 generation-readiness and C-036 publication-authorization refusals."""
# noqa: SIZE_OK — single SUT refusal/authorization matrix; Task 11 owns only this test file

from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Final

import pytest

from ontologylab.file_lifecycle import content_hash_for
from ontologylab.migration import (
    MIGRATION_PHASES,
    begin_phase,
    complete_phase,
    compute_source_fingerprint,
)
from ontologylab.pack_readiness import (
    PackPublication,
    PackReadinessCode,
    PackReadinessRefused,
    PublicationScope,
    REVIEWED_CAPABILITIES,
    UNREVIEWED_CAPABILITIES,
    authorize_publication,
    receipt_inventory,
)
from ontologylab.review_decision_schema import ensure_review_decision_schema
from tests.test_pack_v2_closure import (
    _GENERATION,
    _V2Fixture,
    _build_v2,
    _plant_v2,
    _staging_residue,
    _visible_pack_names,
)

_C036_TABLE: Final = "c036_capability_receipts"
_C036_SCOPE: Final = "sourced"
_C036_DECISION: Final = "authorize"


def _seal_ready(conn: sqlite3.Connection, *, generation: int = _GENERATION) -> str:
    conn.execute("DELETE FROM v2_migration_ledger")
    fingerprint = compute_source_fingerprint(conn)
    for phase in MIGRATION_PHASES:
        begin_phase(
            conn, phase=phase, generation=generation, source_fingerprint=fingerprint,
        )
        complete_phase(
            conn, phase=phase, generation=generation, source_fingerprint=fingerprint,
        )
    return fingerprint


def _ready_fixture(tmp_path: Path) -> _V2Fixture:
    fixture = _plant_v2(tmp_path)
    _seal_ready(fixture.store.conn, generation=fixture.generation)
    fixture.store.conn.commit()
    return fixture


def _assert_invisible(packs: Path, root: Path) -> None:
    assert _visible_pack_names(packs) == []
    assert _staging_residue(root) == []


def _request_sourced(conn: sqlite3.Connection) -> str:
    fact_id = str(conn.execute("SELECT id FROM nodes LIMIT 1").fetchone()[0])
    ensure_review_decision_schema(conn)
    conn.execute(
        "INSERT INTO review_decisions ("
        "decision_id, decision_kind, fact_kind, fact_id, fact_revision, "
        "citation_set_hash, grounding_class, actor, reason, batch_id, "
        "member_ids_json, created_ts) VALUES ("
        "'dec-c036', 'approve', 'node', ?, 'rev-c036', 'cite-c036', "
        "'grounded', 'tester', 'c036', 'batch-c036', '[]', 1.0)",
        (fact_id,),
    )
    conn.execute(
        "INSERT INTO review_publication ("
        "fact_kind, fact_id, publication_class, decision_id, updated_ts) "
        "VALUES ('node', ?, 'sourced', 'dec-c036', 1.0)",
        (fact_id,),
    )
    return fact_id


def _plant_c036(
    conn: sqlite3.Connection,
    *,
    generation: int,
    fingerprint: str,
    root: str,
    scope: str = _C036_SCOPE,
    decision: str = _C036_DECISION,
    receipt_id: str = "c036-valid",
) -> None:
    conn.execute(
        f"CREATE TABLE IF NOT EXISTS {_C036_TABLE} ("
        "receipt_id TEXT PRIMARY KEY, generation INTEGER NOT NULL, "
        "source_fingerprint TEXT NOT NULL, receipt_inventory_root TEXT NOT NULL, "
        "scope TEXT NOT NULL, decision TEXT NOT NULL)"
    )
    conn.execute(
        f"INSERT INTO {_C036_TABLE} ("
        "receipt_id, generation, source_fingerprint, receipt_inventory_root, "
        "scope, decision) VALUES (?, ?, ?, ?, ?, ?)",
        (receipt_id, generation, fingerprint, root, scope, decision),
    )


def _cli(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "ontologylab.pack_readiness", *args],
        check=False,
        capture_output=True,
        text=True,
    )


def test_migrating_ledger_refuses_before_visible_pack(tmp_path: Path) -> None:
    fixture = _plant_v2(tmp_path)
    packs = tmp_path / "packs"
    fixture.store.conn.execute("DELETE FROM v2_migration_ledger")
    fingerprint = compute_source_fingerprint(fixture.store.conn)
    begin_phase(
        fixture.store.conn,
        phase="expand",
        generation=fixture.generation,
        source_fingerprint=fingerprint,
    )
    fixture.store.conn.commit()
    try:
        with pytest.raises(PackReadinessRefused) as raised:
            authorize_publication(fixture.store.conn)
        assert raised.value.code is PackReadinessCode.MIGRATING
        with pytest.raises(PackReadinessRefused):
            _build_v2(fixture, packs, evidence_mode="full")
        _assert_invisible(packs, tmp_path)
    finally:
        fixture.store.close()


def test_incomplete_ledger_refuses_when_required_phases_absent(
    tmp_path: Path,
) -> None:
    fixture = _plant_v2(tmp_path)
    packs = tmp_path / "packs"
    fixture.store.conn.execute("DELETE FROM v2_migration_ledger")
    fingerprint = compute_source_fingerprint(fixture.store.conn)
    begin_phase(
        fixture.store.conn,
        phase="expand",
        generation=fixture.generation,
        source_fingerprint=fingerprint,
    )
    complete_phase(
        fixture.store.conn,
        phase="expand",
        generation=fixture.generation,
        source_fingerprint=fingerprint,
    )
    fixture.store.conn.commit()
    try:
        with pytest.raises(PackReadinessRefused) as raised:
            authorize_publication(fixture.store.conn)
        assert raised.value.code is PackReadinessCode.INCOMPLETE_LEDGER
        with pytest.raises(PackReadinessRefused):
            _build_v2(fixture, packs, evidence_mode="full")
        _assert_invisible(packs, tmp_path)
    finally:
        fixture.store.close()


def test_ambiguous_ledger_refuses_when_generations_conflict(
    tmp_path: Path,
) -> None:
    fixture = _ready_fixture(tmp_path)
    packs = tmp_path / "packs"
    fingerprint = compute_source_fingerprint(fixture.store.conn)
    begin_phase(
        fixture.store.conn,
        phase="expand",
        generation=fixture.generation + 1,
        source_fingerprint=fingerprint,
    )
    fixture.store.conn.commit()
    try:
        with pytest.raises(PackReadinessRefused) as raised:
            authorize_publication(fixture.store.conn)
        assert raised.value.code is PackReadinessCode.AMBIGUOUS_LEDGER
        with pytest.raises(PackReadinessRefused):
            _build_v2(fixture, packs, evidence_mode="full")
        _assert_invisible(packs, tmp_path)
    finally:
        fixture.store.close()


def test_generation_drift_refuses_when_check_disagrees_with_snapshot(
    tmp_path: Path,
) -> None:
    fixture = _ready_fixture(tmp_path)
    try:
        with pytest.raises(PackReadinessRefused) as raised:
            authorize_publication(
                fixture.store.conn, check_generation=fixture.generation + 1,
            )
        assert raised.value.code is PackReadinessCode.GENERATION_DRIFT
    finally:
        fixture.store.close()


def test_fingerprint_mismatch_refuses_before_visible_pack(tmp_path: Path) -> None:
    fixture = _ready_fixture(tmp_path)
    packs = tmp_path / "packs"
    fixture.store.conn.execute(
        "UPDATE v2_migration_ledger SET source_fingerprint = 'sha256:not-live'"
    )
    fixture.store.conn.commit()
    try:
        with pytest.raises(PackReadinessRefused) as raised:
            authorize_publication(fixture.store.conn)
        assert raised.value.code is PackReadinessCode.FINGERPRINT_MISMATCH
        with pytest.raises(PackReadinessRefused):
            _build_v2(fixture, packs, evidence_mode="full")
        _assert_invisible(packs, tmp_path)
    finally:
        fixture.store.close()


def test_missing_ledger_refuses_and_is_not_treated_ready(tmp_path: Path) -> None:
    fixture = _plant_v2(tmp_path)
    packs = tmp_path / "packs"
    fixture.store.conn.execute("DELETE FROM v2_migration_ledger")
    fixture.store.conn.commit()
    try:
        with pytest.raises(PackReadinessRefused) as raised:
            authorize_publication(fixture.store.conn)
        assert raised.value.code is PackReadinessCode.INCOMPLETE_LEDGER
        with pytest.raises(PackReadinessRefused):
            _build_v2(fixture, packs, evidence_mode="full")
        _assert_invisible(packs, tmp_path)
    finally:
        fixture.store.close()


def test_phase_named_ready_is_not_sufficient(tmp_path: Path) -> None:
    fixture = _plant_v2(tmp_path)
    packs = tmp_path / "packs"
    fingerprint = compute_source_fingerprint(fixture.store.conn)
    fixture.store.conn.execute("DELETE FROM v2_migration_ledger")
    fixture.store.conn.execute(
        "INSERT INTO v2_migration_ledger "
        "(phase, cursor, generation, source_fingerprint, created_ts) "
        "VALUES ('ready', '$complete', ?, ?, 1.0)",
        (fixture.generation, fingerprint),
    )
    fixture.store.conn.commit()
    try:
        with pytest.raises(PackReadinessRefused) as raised:
            authorize_publication(fixture.store.conn)
        assert raised.value.code is PackReadinessCode.INCOMPLETE_LEDGER
        with pytest.raises(PackReadinessRefused):
            _build_v2(fixture, packs, evidence_mode="full")
        _assert_invisible(packs, tmp_path)
    finally:
        fixture.store.close()


def test_missing_receipt_inventory_refuses(tmp_path: Path) -> None:
    fixture = _ready_fixture(tmp_path)
    packs = tmp_path / "packs"
    fixture.store.conn.execute(
        "DROP TRIGGER IF EXISTS trg_preferred_selection_receipts_no_delete"
    )
    fixture.store.conn.execute("DELETE FROM preferred_selection_receipts")
    fixture.store.conn.commit()
    try:
        with pytest.raises(PackReadinessRefused) as raised:
            authorize_publication(fixture.store.conn)
        assert raised.value.code is PackReadinessCode.MISSING_RECEIPT
        assert raised.value.member == "policy"
        with pytest.raises(PackReadinessRefused):
            _build_v2(fixture, packs, evidence_mode="full")
        _assert_invisible(packs, tmp_path)
    finally:
        fixture.store.close()


def test_stale_receipt_refuses_when_representation_hash_drifts(
    tmp_path: Path,
) -> None:
    fixture = _ready_fixture(tmp_path)
    packs = tmp_path / "packs"
    fixture.store.conn.execute("DROP TRIGGER IF EXISTS trg_citation_receipts_no_update")
    fixture.store.conn.execute(
        "UPDATE citation_receipts SET representation_content_hash = 'sha256:stale' "
        "WHERE receipt_id = ?",
        (fixture.citation_ids[0],),
    )
    fixture.store.conn.commit()
    try:
        with pytest.raises(PackReadinessRefused) as raised:
            authorize_publication(fixture.store.conn)
        assert raised.value.code is PackReadinessCode.STALE_RECEIPT
        with pytest.raises(PackReadinessRefused):
            _build_v2(fixture, packs, evidence_mode="full")
        _assert_invisible(packs, tmp_path)
    finally:
        fixture.store.close()


def test_ready_unreviewed_publishes_without_c036(tmp_path: Path) -> None:
    fixture = _ready_fixture(tmp_path)
    packs = tmp_path / "packs"
    try:
        granted = authorize_publication(fixture.store.conn)
        assert isinstance(granted, PackPublication)
        assert granted.generation == fixture.generation
        assert granted.publication_scope is PublicationScope.UNREVIEWED
        assert granted.capabilities == UNREVIEWED_CAPABILITIES
        assert granted.c036_receipt_id is None
        manifest = _build_v2(fixture, packs, evidence_mode="full")
        payload = json.loads(
            (packs / manifest.pack_id / "manifest.json").read_text(encoding="utf-8"),
        )
        assert payload["capabilities"] == list(UNREVIEWED_CAPABILITIES)
        assert "reviewed" not in payload["capabilities"]
        assert "sourced-answer-v2" not in payload["capabilities"]
        assert _visible_pack_names(packs) == [manifest.pack_id]
    finally:
        fixture.store.close()


def test_reviewed_without_c036_refuses_before_visible_pack(tmp_path: Path) -> None:
    fixture = _ready_fixture(tmp_path)
    packs = tmp_path / "packs"
    _request_sourced(fixture.store.conn)
    fixture.store.conn.commit()
    try:
        with pytest.raises(PackReadinessRefused) as raised:
            authorize_publication(fixture.store.conn)
        assert raised.value.code is PackReadinessCode.C036_REQUIRED
        with pytest.raises(PackReadinessRefused):
            _build_v2(fixture, packs, evidence_mode="full")
        _assert_invisible(packs, tmp_path)
    finally:
        fixture.store.close()


def test_reviewed_with_valid_c036_publishes_sourced_capabilities(
    tmp_path: Path,
) -> None:
    fixture = _ready_fixture(tmp_path)
    packs = tmp_path / "packs"
    _request_sourced(fixture.store.conn)
    inventory = receipt_inventory(fixture.store.conn)
    fingerprint = compute_source_fingerprint(fixture.store.conn)
    _plant_c036(
        fixture.store.conn,
        generation=fixture.generation,
        fingerprint=fingerprint,
        root=inventory.root,
    )
    fixture.store.conn.commit()
    try:
        granted = authorize_publication(fixture.store.conn)
        assert granted.publication_scope is PublicationScope.SOURCED
        assert granted.capabilities == REVIEWED_CAPABILITIES
        assert granted.c036_receipt_id == "c036-valid"
        manifest = _build_v2(fixture, packs, evidence_mode="full")
        payload = json.loads(
            (packs / manifest.pack_id / "manifest.json").read_text(encoding="utf-8"),
        )
        assert payload["capabilities"] == list(REVIEWED_CAPABILITIES)
        assert "sourced-answer-v2" in payload["capabilities"]
        assert _visible_pack_names(packs) == [manifest.pack_id]
        assert _staging_residue(tmp_path) == []
    finally:
        fixture.store.close()


def test_stale_c036_refuses_when_bindings_drift(tmp_path: Path) -> None:
    fixture = _ready_fixture(tmp_path)
    packs = tmp_path / "packs"
    _request_sourced(fixture.store.conn)
    inventory = receipt_inventory(fixture.store.conn)
    _plant_c036(
        fixture.store.conn,
        generation=fixture.generation + 3,
        fingerprint="sha256:not-the-snapshot",
        root=inventory.root,
    )
    fixture.store.conn.commit()
    try:
        with pytest.raises(PackReadinessRefused) as raised:
            authorize_publication(fixture.store.conn)
        assert raised.value.code is PackReadinessCode.C036_STALE
        with pytest.raises(PackReadinessRefused):
            _build_v2(fixture, packs, evidence_mode="full")
        _assert_invisible(packs, tmp_path)
    finally:
        fixture.store.close()


def test_failed_attempt_preserves_existing_pack(tmp_path: Path) -> None:
    fixture = _ready_fixture(tmp_path)
    packs = tmp_path / "packs"
    try:
        first = _build_v2(fixture, packs, evidence_mode="full")
        published = packs / first.pack_id
        before = (published / "manifest.json").read_bytes()
        names = _visible_pack_names(packs)
        fixture.store.conn.execute("DELETE FROM v2_migration_ledger")
        fingerprint = compute_source_fingerprint(fixture.store.conn)
        begin_phase(
            fixture.store.conn,
            phase="backfill",
            generation=fixture.generation,
            source_fingerprint=fingerprint,
        )
        fixture.store.conn.commit()
        with pytest.raises(PackReadinessRefused):
            _build_v2(fixture, packs, evidence_mode="full")
        assert _visible_pack_names(packs) == names
        assert (published / "manifest.json").read_bytes() == before
        assert _staging_residue(tmp_path) == []
    finally:
        fixture.store.close()


def test_cli_evaluate_emits_typed_refusal_for_migrating(tmp_path: Path) -> None:
    fixture = _plant_v2(tmp_path)
    fixture.store.conn.execute("DELETE FROM v2_migration_ledger")
    fingerprint = compute_source_fingerprint(fixture.store.conn)
    begin_phase(
        fixture.store.conn,
        phase="validate",
        generation=fixture.generation,
        source_fingerprint=fingerprint,
    )
    fixture.store.conn.commit()
    fixture.store.close()
    result = _cli([str(fixture.kg)])
    assert result.returncode == 2
    payload = json.loads(result.stdout)
    assert payload["ok"] is False
    assert payload["code"] == PackReadinessCode.MIGRATING.value


def test_cli_publish_ready_unreviewed_writes_pack(tmp_path: Path) -> None:
    fixture = _ready_fixture(tmp_path)
    packs = tmp_path / "packs"
    fixture.store.close()
    result = _cli(
        [
            str(fixture.kg),
            "--publish",
            str(packs),
            "--name",
            "ready-unreviewed",
            "--evidence-mode",
            "full",
        ],
    )
    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert payload["publication_scope"] == PublicationScope.UNREVIEWED.value
    assert payload["capabilities"] == list(UNREVIEWED_CAPABILITIES)
    assert _visible_pack_names(packs)
    assert _staging_residue(tmp_path) == []


_UPDATE_TRIGGERS: Final = (
    "trg_citation_receipts_no_update",
    "trg_grounded_review_decisions_no_update",
    "trg_extraction_run_receipts_no_update",
    "trg_extraction_chunk_receipts_no_update",
    "trg_preferred_selection_receipts_no_update",
)


def _drop_update_guards(conn: sqlite3.Connection) -> None:
    for trigger in _UPDATE_TRIGGERS:
        conn.execute(f"DROP TRIGGER IF EXISTS {trigger}")


def _reviewed_authorized(tmp_path: Path) -> tuple[_V2Fixture, str]:
    fixture = _ready_fixture(tmp_path)
    _request_sourced(fixture.store.conn)
    inventory = receipt_inventory(fixture.store.conn)
    _plant_c036(
        fixture.store.conn,
        generation=fixture.generation,
        fingerprint=compute_source_fingerprint(fixture.store.conn),
        root=inventory.root,
    )
    fixture.store.conn.commit()
    return fixture, inventory.root


def _mutate_citation(fixture: _V2Fixture) -> None:
    text = "ATTACKER-SOURCED-TEXT"
    fixture.store.conn.execute(
        "UPDATE citation_receipts SET selected_text = ?, selected_text_hash = ? "
        "WHERE receipt_id = ?",
        (text, content_hash_for(text.encode("utf-8")), fixture.citation_ids[0]),
    )


def _mutate_review(fixture: _V2Fixture) -> None:
    fixture.store.conn.execute(
        "UPDATE grounded_review_decisions SET actor = 'attacker', reason = 'same-id-tamper' "
        "WHERE receipt_id = ?",
        (fixture.review_ids[0],),
    )


def _mutate_run_engine(fixture: _V2Fixture) -> None:
    fixture.store.conn.execute(
        "UPDATE extraction_run_receipts SET extractor_engine = 'attacker-engine' "
        "WHERE receipt_id = ?",
        (fixture.run_receipt_id,),
    )


def _mutate_run_config(fixture: _V2Fixture) -> None:
    fixture.store.conn.execute(
        "UPDATE extraction_run_receipts SET config_identity = 'attacker-config' "
        "WHERE receipt_id = ?",
        (fixture.run_receipt_id,),
    )


def _mutate_chunk(fixture: _V2Fixture) -> None:
    fixture.store.conn.execute(
        "UPDATE extraction_chunk_receipts SET chunk_text_hash = 'sha256:chunk-tamper' "
        "WHERE receipt_id = ?",
        (fixture.chunk_receipt_id,),
    )


def _mutate_policy(fixture: _V2Fixture) -> None:
    fixture.store.conn.execute(
        "UPDATE preferred_selection_receipts SET "
        "selected_representation_id = 'attacker-rep', "
        "selected_content_hash = 'sha256:deadbeef' WHERE receipt_id = ?",
        (fixture.policy_receipt_id,),
    )


@pytest.mark.parametrize(
    ("family", "mutate"),
    (
        ("citation", _mutate_citation),
        ("review", _mutate_review),
        ("run", _mutate_run_engine),
        ("chunk", _mutate_chunk),
        ("policy", _mutate_policy),
    ),
    ids=("citation", "review", "run", "chunk", "policy"),
)
def test_same_id_body_mutation_refuses_reused_c036(
    tmp_path: Path, family: str, mutate: Callable[[_V2Fixture], None],
) -> None:
    fixture, prior_root = _reviewed_authorized(tmp_path)
    packs = tmp_path / "packs"
    _drop_update_guards(fixture.store.conn)
    mutate(fixture)
    fixture.store.conn.commit()
    try:
        with pytest.raises(PackReadinessRefused) as raised:
            authorize_publication(fixture.store.conn)
        assert raised.value.code in {
            PackReadinessCode.STALE_RECEIPT,
            PackReadinessCode.C036_STALE,
        }
        assert raised.value.member in {family, "c036", "citation", "run", "chunk", "policy", "review_decision"}
        with pytest.raises(PackReadinessRefused):
            _build_v2(fixture, packs, evidence_mode="full")
        _assert_invisible(packs, tmp_path)
        try:
            later = receipt_inventory(fixture.store.conn).root
        except PackReadinessRefused:
            later = prior_root
        if later == prior_root and raised.value.code is PackReadinessCode.C036_STALE:
            raise AssertionError("C-036 root stayed ID-only after body mutation")
    finally:
        fixture.store.close()


@pytest.mark.parametrize(
    "mutate",
    (
        _mutate_citation,
        _mutate_review,
        _mutate_run_config,
        _mutate_chunk,
        _mutate_policy,
    ),
    ids=("citation", "review", "run", "chunk", "policy"),
)
def test_new_c036_cannot_bless_invalid_receipt_id(
    tmp_path: Path, mutate: Callable[[_V2Fixture], None],
) -> None:
    fixture, _prior = _reviewed_authorized(tmp_path)
    packs = tmp_path / "packs"
    _drop_update_guards(fixture.store.conn)
    mutate(fixture)
    fixture.store.conn.execute(f"DELETE FROM {_C036_TABLE}")
    fixture.store.conn.commit()
    try:
        try:
            new_root = receipt_inventory(fixture.store.conn).root
        except PackReadinessRefused as refused:
            assert refused.code is PackReadinessCode.STALE_RECEIPT
            with pytest.raises(PackReadinessRefused):
                _build_v2(fixture, packs, evidence_mode="full")
            _assert_invisible(packs, tmp_path)
            return
        _plant_c036(
            fixture.store.conn,
            generation=fixture.generation,
            fingerprint=compute_source_fingerprint(fixture.store.conn),
            root=new_root,
            receipt_id="c036-after-tamper",
        )
        fixture.store.conn.commit()
        with pytest.raises(PackReadinessRefused) as raised:
            authorize_publication(fixture.store.conn)
        assert raised.value.code is PackReadinessCode.STALE_RECEIPT
        with pytest.raises(PackReadinessRefused):
            _build_v2(fixture, packs, evidence_mode="full")
        _assert_invisible(packs, tmp_path)
    finally:
        fixture.store.close()
