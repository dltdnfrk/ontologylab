"""Wave 2.1 Step 5 (5C): F6 interrupt/resume rehearsal over the 5A core.

Interrupted runs leave a consistent phase/cursor ledger; resume continues
from the cursor without repeating completed rows; two complete runs over
the same fixture produce byte-identical canonical dumps; below-cursor
catch-up drops nothing; a rerun after completion is a no-op.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from ontologylab.kgstore import KGStore
from ontologylab.migration import (
    PHASE_COMPLETE,
    phase_is_complete,
    read_ledger,
    snapshot_db,
)
from ontologylab.migration_rehearsal import (
    InterruptionInjected,
    canonical_db_dump,
    canonical_db_hash,
    current_cursor,
    effect_counts,
    run_rehearsal,
)


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


def _populated_source(tmp_path: Path) -> Path:
    source = tmp_path / "src" / "kg.sqlite"
    source.parent.mkdir()
    store = KGStore.open(source)
    for doc_id in ("doc-a", "doc-m", "doc-z"):
        _insert_doc(store.conn, doc_id)
    store.conn.commit()
    store.close()
    return source


def _snapshot_pair(
    tmp_path: Path, source: Path, name: str
) -> tuple[KGStore, KGStore, Path]:
    target = tmp_path / name
    target.mkdir()
    copied = snapshot_db(source, target)
    return KGStore.open(source), KGStore.open(copied), copied


def _interrupt_on(row_id: str, phase: str = "expand"):
    def _hook(seen: str) -> None:
        if seen == row_id:
            raise InterruptionInjected(row_id=seen, phase=phase)

    return _hook


def _expand_cursors(conn: sqlite3.Connection) -> list[str]:
    return [
        row.cursor
        for row in read_ledger(conn)
        if row.phase == "expand"
        and row.cursor is not None
        and row.cursor != PHASE_COMPLETE
    ]


def test_interrupt_resume_keeps_ledger_consistent_and_counts_effects_once(
    tmp_path: Path,
) -> None:
    source = _populated_source(tmp_path)
    src, copy, copied = _snapshot_pair(tmp_path, source, "copy")
    try:
        with pytest.raises(InterruptionInjected) as raised:
            run_rehearsal(src.conn, copy.conn, failpoint=_interrupt_on("doc-z"))
        assert raised.value.row_id == "doc-z"
        assert raised.value.phase == "expand"
        copy.conn.commit()
        assert current_cursor(copy.conn, "expand") == "doc-m"
        assert not phase_is_complete(copy.conn, "expand")
        ledger = read_ledger(copy.conn)
        expand = [row for row in ledger if row.phase == "expand"]
        assert expand[-1].cursor == "doc-m"
        assert all(row.source_fingerprint for row in expand)
        assert effect_counts(copy.conn) == (("doc-a", 1), ("doc-m", 1))
        assert _expand_cursors(copy.conn) == ["doc-a", "doc-m"]
    finally:
        src.close()
        copy.close()

    src = KGStore.open(source)
    copy = KGStore.open(copied)
    try:
        assert current_cursor(copy.conn, "expand") == "doc-m"
        receipt = run_rehearsal(src.conn, copy.conn)
        copy.conn.commit()
        assert receipt.complete is True
        assert receipt.cursor == PHASE_COMPLETE
        assert receipt.effect_counts == (("doc-a", 1), ("doc-m", 1), ("doc-z", 1))
        assert _expand_cursors(copy.conn) == ["doc-a", "doc-m", "doc-z"]
        assert phase_is_complete(copy.conn, "expand")
    finally:
        src.close()
        copy.close()


def test_two_complete_runs_produce_byte_identical_canonical_dumps(
    tmp_path: Path,
) -> None:
    source = _populated_source(tmp_path)
    src_a, copy_a, _ = _snapshot_pair(tmp_path, source, "copy-a")
    src_b, copy_b, _ = _snapshot_pair(tmp_path, source, "copy-b")
    try:
        receipt_a = run_rehearsal(src_a.conn, copy_a.conn)
        receipt_b = run_rehearsal(src_b.conn, copy_b.conn)
        copy_a.conn.commit()
        copy_b.conn.commit()
        dump_a = canonical_db_dump(copy_a.conn)
        dump_b = canonical_db_dump(copy_b.conn)
        assert dump_a == dump_b
        assert canonical_db_hash(copy_a.conn) == canonical_db_hash(copy_b.conn)
        assert receipt_a.dump_sha256 == receipt_b.dump_sha256
        assert receipt_a.receipt_sha256 == receipt_b.receipt_sha256
        assert receipt_a.dump_sha256 == canonical_db_hash(copy_a.conn)
    finally:
        src_a.close()
        copy_a.close()
        src_b.close()
        copy_b.close()


def test_below_cursor_catchup_picks_up_post_snapshot_rows(tmp_path: Path) -> None:
    source = _populated_source(tmp_path)
    src, copy, copied = _snapshot_pair(tmp_path, source, "copy")
    try:
        with pytest.raises(InterruptionInjected):
            run_rehearsal(src.conn, copy.conn, failpoint=_interrupt_on("doc-z"))
        copy.conn.commit()
        assert current_cursor(copy.conn, "expand") == "doc-m"
        _insert_doc(src.conn, "doc-b")
        src.conn.commit()
    finally:
        src.close()
        copy.close()

    src = KGStore.open(source)
    copy = KGStore.open(copied)
    try:
        receipt = run_rehearsal(src.conn, copy.conn)
        copy.conn.commit()
        ids = [
            row[0]
            for row in copy.conn.execute("SELECT id FROM documents ORDER BY id")
        ]
        assert "doc-b" in ids
        assert ids == ["doc-a", "doc-b", "doc-m", "doc-z"]
        assert receipt.effect_counts == (
            ("doc-a", 1),
            ("doc-b", 1),
            ("doc-m", 1),
            ("doc-z", 1),
        )
        assert phase_is_complete(copy.conn, "expand")
    finally:
        src.close()
        copy.close()


def test_resume_continues_from_cursor_without_repeating_completed_rows(
    tmp_path: Path,
) -> None:
    source = _populated_source(tmp_path)
    src, copy, copied = _snapshot_pair(tmp_path, source, "copy")
    try:
        with pytest.raises(InterruptionInjected):
            run_rehearsal(src.conn, copy.conn, failpoint=_interrupt_on("doc-z"))
        copy.conn.commit()
        assert current_cursor(copy.conn, "expand") == "doc-m"
        assert effect_counts(copy.conn) == (("doc-a", 1), ("doc-m", 1))
    finally:
        src.close()
        copy.close()

    src = KGStore.open(source)
    copy = KGStore.open(copied)
    try:
        receipt = run_rehearsal(src.conn, copy.conn)
        copy.conn.commit()
        assert receipt.effect_counts == (("doc-a", 1), ("doc-m", 1), ("doc-z", 1))
        assert all(count == 1 for _, count in receipt.effect_counts)
        assert _expand_cursors(copy.conn) == ["doc-a", "doc-m", "doc-z"]
    finally:
        src.close()
        copy.close()


def test_rerun_after_completion_is_noop_with_identical_receipt_hash(
    tmp_path: Path,
) -> None:
    source = _populated_source(tmp_path)
    src, copy, _ = _snapshot_pair(tmp_path, source, "copy")
    try:
        first = run_rehearsal(src.conn, copy.conn)
        copy.conn.commit()
        dump_before = canonical_db_dump(copy.conn)
        second = run_rehearsal(src.conn, copy.conn)
        copy.conn.commit()
        assert first.complete is True
        assert second.complete is True
        assert first.receipt_sha256 == second.receipt_sha256
        assert first.dump_sha256 == second.dump_sha256
        assert canonical_db_dump(copy.conn) == dump_before
        assert effect_counts(copy.conn) == (("doc-a", 1), ("doc-m", 1), ("doc-z", 1))
        assert _expand_cursors(copy.conn) == ["doc-a", "doc-m", "doc-z"]
    finally:
        src.close()
        copy.close()
