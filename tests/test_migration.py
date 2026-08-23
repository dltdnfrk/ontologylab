"""Wave 2.1 Step 5 (5A): resumable migration core on backup-API copies.

Snapshot, phase/cursor ledger, writer fence, post_cutover_write, and
below-cursor drift scan. Tests assert machine-consumed ledger/row state.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from ontologylab.authority_repo import create_work
from ontologylab.kgstore import KGStore
from ontologylab.migration import (
    PHASE_COMPLETE,
    SnapshotSourceMissing,
    SnapshotTargetMissing,
    WritesFenced,
    advance_cursor,
    begin_phase,
    complete_phase,
    compute_source_fingerprint,
    fence_writes,
    apply_v2_authority_mutation,
    phase_is_complete,
    plan_phases,
    read_ledger,
    scan_drift,
    snapshot_db,
)
from tests.wave21.harness import Failpoint, FailpointArmed


def _insert_doc(conn: sqlite3.Connection, doc_id: str) -> None:
    conn.execute(
        "INSERT INTO documents "
        "(id, source_kind, source_uri, title, fetched_ts, content_hash, "
        "raw_text_path) "
        "VALUES (?, 'upload', ?, ?, 0, ?, ?)",
        (
            doc_id,
            f"file:///{doc_id}.txt",
            doc_id,
            f"sha256:{doc_id}",
            f"documents/{doc_id}/raw.txt",
        ),
    )


@pytest.fixture()
def store(tmp_path: Path):
    s = KGStore.open(tmp_path / "kg.sqlite")
    yield s
    s.close()


def test_snapshot_db_copies_via_backup_api(tmp_path: Path) -> None:
    source = tmp_path / "src" / "kg.sqlite"
    source.parent.mkdir()
    store = KGStore.open(source)
    _insert_doc(store.conn, "doc-a")
    store.conn.commit()
    store.close()

    target = tmp_path / "copy"
    target.mkdir()
    copied = snapshot_db(source, target)
    assert copied == target / "kg.sqlite"
    assert copied.is_file()

    copy_conn = sqlite3.connect(copied)
    try:
        ids = [
            row[0]
            for row in copy_conn.execute("SELECT id FROM documents ORDER BY id")
        ]
    finally:
        copy_conn.close()
    assert ids == ["doc-a"]

    src_conn = sqlite3.connect(source)
    try:
        src_ids = [
            row[0]
            for row in src_conn.execute("SELECT id FROM documents ORDER BY id")
        ]
    finally:
        src_conn.close()
    assert src_ids == ["doc-a"]


def test_snapshot_db_missing_source_is_typed(tmp_path: Path) -> None:
    missing = tmp_path / "nope.sqlite"
    with pytest.raises(SnapshotSourceMissing) as raised:
        snapshot_db(missing, tmp_path)
    assert raised.value.source_path == str(missing)


def test_snapshot_db_missing_target_is_typed(tmp_path: Path) -> None:
    source = tmp_path / "kg.sqlite"
    KGStore.open(source).close()
    target = tmp_path / "missing-dir"
    with pytest.raises(SnapshotTargetMissing) as raised:
        snapshot_db(source, target)
    assert raised.value.target_dir == str(target)


def test_plan_phases_carries_source_fingerprint(store) -> None:
    _insert_doc(store.conn, "doc-a")
    plan = plan_phases(store.conn, generation=1)
    assert plan.generation == 1
    assert plan.phases == ("expand", "backfill", "validate", "enforce")
    assert plan.source_fingerprint == compute_source_fingerprint(store.conn)
    assert plan.source_fingerprint


def test_begin_phase_records_source_fingerprint(store) -> None:
    fingerprint = compute_source_fingerprint(store.conn)
    row = begin_phase(
        store.conn,
        phase="expand",
        generation=1,
        source_fingerprint=fingerprint,
    )
    assert row.source_fingerprint == fingerprint
    ledger = read_ledger(store.conn)
    assert len(ledger) == 1
    assert ledger[0].phase == "expand"
    assert ledger[0].generation == 1
    assert ledger[0].source_fingerprint == fingerprint
    assert ledger[0].cursor is None


def test_cursor_is_not_advanced_before_phase_row_commit(store) -> None:
    fingerprint = compute_source_fingerprint(store.conn)
    advance_cursor(
        store.conn,
        phase="backfill",
        cursor="doc-m",
        generation=1,
        source_fingerprint=fingerprint,
    )
    ledger = read_ledger(store.conn)
    assert len(ledger) == 2
    assert ledger[0].phase == "backfill"
    assert ledger[0].cursor is None
    assert ledger[0].generation == 1
    assert ledger[0].source_fingerprint == fingerprint
    assert ledger[1].phase == "backfill"
    assert ledger[1].cursor == "doc-m"
    assert ledger[1].generation == 1
    assert ledger[1].source_fingerprint == fingerprint
    assert ledger[0].seq < ledger[1].seq


def test_failpoint_between_phase_and_cursor_leaves_no_half_advanced_phase(
    tmp_path: Path,
) -> None:
    db = tmp_path / "kg.sqlite"
    store = KGStore.open(db)
    try:
        fingerprint = compute_source_fingerprint(store.conn)
        begin_phase(
            store.conn,
            phase="backfill",
            generation=1,
            source_fingerprint=fingerprint,
        )
        store.conn.commit()
        before = read_ledger(store.conn)
        failpoint = Failpoint()
        failpoint.arm("after_phase_row")
        with pytest.raises(FailpointArmed) as raised:
            advance_cursor(
                store.conn,
                phase="backfill",
                cursor="doc-m",
                generation=1,
                source_fingerprint=fingerprint,
                failpoint=failpoint.hit,
            )
        assert raised.value.name == "after_phase_row"
        after = read_ledger(store.conn)
        assert after == before
        assert all(row.cursor is None for row in after)
    finally:
        store.close()

    reopened = KGStore.open(db)
    try:
        ledger = read_ledger(reopened.conn)
        assert len(ledger) == 1
        assert ledger[0].phase == "backfill"
        assert ledger[0].cursor is None
        assert ledger[0].source_fingerprint
    finally:
        reopened.close()


def test_complete_phase_finalizes_ledger(store) -> None:
    fingerprint = compute_source_fingerprint(store.conn)
    begin_phase(
        store.conn,
        phase="validate",
        generation=1,
        source_fingerprint=fingerprint,
    )
    complete_phase(
        store.conn,
        phase="validate",
        generation=1,
        source_fingerprint=fingerprint,
    )
    assert phase_is_complete(store.conn, "validate")
    latest = read_ledger(store.conn)[-1]
    assert latest.phase == "validate"
    assert latest.cursor == PHASE_COMPLETE
    assert latest.source_fingerprint == fingerprint


def test_armed_fence_rejects_v2_authority_mutation(store) -> None:
    fingerprint = compute_source_fingerprint(store.conn)
    fence_writes(
        store.conn, generation=1, source_fingerprint=fingerprint,
    )
    with pytest.raises(WritesFenced) as raised:
        def _create(conn: sqlite3.Connection) -> None:
            create_work(conn, "w-fenced")

        apply_v2_authority_mutation(
            store.conn,
            _create,
            generation=1,
            source_fingerprint=fingerprint,
        )
    assert raised.value.generation == 1
    assert store.conn.execute("SELECT COUNT(*) FROM works").fetchone()[0] == 0
    assert all(
        row.phase != "post_cutover_write" for row in read_ledger(store.conn)
    )


def test_post_cutover_write_lands_with_first_v2_mutation(store) -> None:
    fingerprint = compute_source_fingerprint(store.conn)
    def _create(conn: sqlite3.Connection) -> None:
        create_work(conn, "w-cutover")

    apply_v2_authority_mutation(
        store.conn,
        _create,
        generation=1,
        source_fingerprint=fingerprint,
    )
    work_ids = [
        row[0] for row in store.conn.execute("SELECT id FROM works ORDER BY id")
    ]
    assert work_ids == ["w-cutover"]
    markers = [
        row for row in read_ledger(store.conn)
        if row.phase == "post_cutover_write"
    ]
    assert len(markers) == 1
    assert markers[0].generation == 1
    assert markers[0].source_fingerprint == fingerprint


def test_failpoint_between_v2_mutation_and_marker_rolls_both_back(store) -> None:
    fingerprint = compute_source_fingerprint(store.conn)
    failpoint = Failpoint()
    failpoint.arm("after_v2_mutation")
    with pytest.raises(FailpointArmed):
        def _create(conn: sqlite3.Connection) -> None:
            create_work(conn, "w-torn")

        apply_v2_authority_mutation(
            store.conn,
            _create,
            generation=1,
            source_fingerprint=fingerprint,
            failpoint=failpoint.hit,
        )
    assert store.conn.execute("SELECT COUNT(*) FROM works").fetchone()[0] == 0
    assert read_ledger(store.conn) == ()


def test_below_cursor_drift_scan_returns_post_snapshot_rows(
    tmp_path: Path,
) -> None:
    source = tmp_path / "src" / "kg.sqlite"
    source.parent.mkdir()
    store = KGStore.open(source)
    for doc_id in ("doc-a", "doc-m", "doc-z"):
        _insert_doc(store.conn, doc_id)
    store.conn.commit()
    store.close()

    target = tmp_path / "copy"
    target.mkdir()
    copied = snapshot_db(source, target)

    src = KGStore.open(source)
    copy = KGStore.open(copied)
    try:
        _insert_doc(src.conn, "doc-b")
        _insert_doc(src.conn, "doc-zz")
        src.conn.commit()
        below = scan_drift(src.conn, copy.conn, cursor="doc-m")
        assert "doc-b" in below
        assert "doc-a" not in below
        assert "doc-m" not in below
        full = scan_drift(src.conn, copy.conn)
        assert "doc-b" in full
        assert "doc-zz" in full
        assert "doc-a" not in full
    finally:
        src.close()
        copy.close()
