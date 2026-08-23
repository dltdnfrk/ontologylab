"""Wave 2.1 Step 5 (5B): DOI backfill and collision executor on backup copies.

Runs the Step 2 planner over a 5A snapshot of a populated legacy store.
Tests assert machine-consumed documents/identifier/file/span state.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from ontologylab.kgstore import KGStore
from ontologylab.migration_backfill import (
    execute_doi_backfill,
    inspect_f1,
    prepare_backup_copy,
)
from tests.wave21.identity import seed_premigration_documents_row

OWNED_DOI = "10.1000/backfill.owned"
DUP_DOI = "10.1000/backfill.dup"
OK_DOI = "10.1000/backfill.ok"
EQUIV_DOI = "10.1000/equiv.work"
SPAN_JSON = json.dumps({"start": 0, "end": 11}, separators=(",", ":"))


def _seed_legacy_rows(db: Path) -> None:
    rows = (
        ("legacy-resolver", "https://doi.org/10.1000/backfill.ok", "sha256:bf-1"),
        ("legacy-arbitrary", "https://arxiv.org/abs/2401.00001", "sha256:bf-2"),
        ("legacy-bare", "10.9999/bare.doi", "sha256:bf-3"),
        ("legacy-owned", "https://doi.org/10.1000/backfill.owned", "sha256:bf-4"),
        ("legacy-dup-a", "https://doi.org/10.1000/backfill.dup", "sha256:bf-5"),
        ("legacy-dup-b", "https://dx.doi.org/10.1000/backfill.dup", "sha256:bf-6"),
    )
    for doc_id, source_uri, content_hash in rows:
        seed_premigration_documents_row(
            db,
            doc_id=doc_id,
            source_uri=source_uri,
            raw_text=f"legacy body for {doc_id}",
            content_hash=content_hash,
        )


def _insert_rep(
    conn: sqlite3.Connection,
    db_dir: Path,
    *,
    doc_id: str,
    source_uri: str,
    content_hash: str,
    raw_text: str,
    doi: str,
) -> None:
    rel = f"documents/{doc_id}/raw.txt"
    path = db_dir / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(raw_text, encoding="utf-8")
    conn.execute(
        "INSERT INTO documents "
        "(id, source_kind, source_uri, title, fetched_ts, content_hash, "
        "raw_text_path, source, evidence_grade, doi) "
        "VALUES (?, 'paper_api', ?, ?, 0, ?, ?, '', '', ?)",
        (doc_id, source_uri, f"Equiv {doc_id}", content_hash, rel, doi),
    )


def _populated_legacy_store(tmp_path: Path) -> Path:
    src = tmp_path / "src"
    src.mkdir()
    db = src / "kg.sqlite"
    _seed_legacy_rows(db)
    store = KGStore.open(db)
    store.insert_document(
        source_kind="paper_api",
        source_uri="https://doi.org/10.1000/backfill.owned",
        title="Modern owner",
        raw_text="the modern owner row",
        content_hash="sha256:bf-owner",
        doi=OWNED_DOI,
    )
    # Two explicit DOI strings that normalize to one value (case fold) with
    # different bytes: the F1 equivalent group. The v1 unique index is
    # case-sensitive, so both rows can coexist as documents.doi projections.
    _insert_rep(
        store.conn,
        db.parent,
        doc_id="equiv-a",
        source_uri="https://doi.org/10.1000/equiv.work",
        content_hash="sha256:eq-a",
        raw_text="abstract bytes for equivalent work",
        doi="10.1000/equiv.work",
    )
    _insert_rep(
        store.conn,
        db.parent,
        doc_id="equiv-b",
        source_uri="https://doi.org/10.1000/EQUIV.WORK",
        content_hash="sha256:eq-b",
        raw_text="fulltext bytes for equivalent work",
        doi="10.1000/EQUIV.WORK",
    )
    store.conn.execute(
        "INSERT INTO citations "
        "(kind, item_id, source_doc_id, source_span, created_ts) "
        "VALUES ('node', 'cite-legacy-resolver', 'legacy-resolver', ?, 0)",
        (SPAN_JSON,),
    )
    store.conn.commit()
    store.close()
    return db


def _backup_open(tmp_path: Path, source: Path) -> KGStore:
    target = tmp_path / "copy"
    target.mkdir()
    copied = prepare_backup_copy(source, target)
    return KGStore.open(copied)


def _doi_by_id(conn: sqlite3.Connection) -> dict[str, str | None]:
    return {
        row[0]: row[1]
        for row in conn.execute("SELECT id, doi FROM documents")
    }


def _accepted_count(conn: sqlite3.Connection, doi: str) -> int:
    return int(
        conn.execute(
            "SELECT COUNT(*) FROM work_identifiers "
            "WHERE scheme = 'doi' AND normalized_value = ? "
            "AND status = 'accepted'",
            (doi,),
        ).fetchone()[0]
    )


def _pending_ids(conn: sqlite3.Connection, doi: str) -> list[str]:
    return [
        row[0]
        for row in conn.execute(
            "SELECT id FROM work_identifiers "
            "WHERE scheme = 'doi' AND normalized_value = ? "
            "AND status = 'pending' ORDER BY id",
            (doi,),
        )
    ]


def _redirect_count(conn: sqlite3.Connection) -> int:
    return int(
        conn.execute("SELECT COUNT(*) FROM work_redirect_decisions").fetchone()[0]
    )


def _identity_dump(conn: sqlite3.Connection) -> list[tuple]:
    docs = conn.execute(
        "SELECT id, doi, work_id, content_hash, raw_text_path "
        "FROM documents ORDER BY id"
    ).fetchall()
    idents = conn.execute(
        "SELECT id, work_id, scheme, normalized_value, status "
        "FROM work_identifiers ORDER BY id"
    ).fetchall()
    decisions = conn.execute(
        "SELECT id, identifier_id, action, actor, reason "
        "FROM identifier_decisions ORDER BY id"
    ).fetchall()
    works = conn.execute("SELECT id, state FROM works ORDER BY id").fetchall()
    cites = conn.execute(
        "SELECT kind, item_id, source_doc_id, source_span "
        "FROM citations ORDER BY item_id"
    ).fetchall()
    return [tuple(row) for row in (*docs, *idents, *decisions, *works, *cites)]


def _raw_bytes(db_path: Path) -> dict[str, bytes]:
    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute("SELECT id, raw_text_path FROM documents").fetchall()
    finally:
        conn.close()
    out: dict[str, bytes] = {}
    for doc_id, rel in rows:
        path = db_path.parent / rel
        if path.is_file():
            out[doc_id] = path.read_bytes()
    return out


def test_backfillable_rows_gain_doi_on_backup_copy(tmp_path: Path) -> None:
    source = _populated_legacy_store(tmp_path)
    src_conn = sqlite3.connect(source)
    try:
        src_before = {
            row[0]: row[1]
            for row in src_conn.execute("SELECT id, doi FROM documents")
        }
    finally:
        src_conn.close()
    assert src_before["legacy-resolver"] is None

    store = _backup_open(tmp_path, source)
    try:
        execute_doi_backfill(store.conn)
        dois = _doi_by_id(store.conn)
        assert dois["legacy-resolver"] == OK_DOI
        assert dois["legacy-arbitrary"] is None
        assert dois["legacy-bare"] is None
        assert dois["legacy-owned"] is None
        assert dois["legacy-dup-a"] is None
        assert dois["legacy-dup-b"] is None
    finally:
        store.close()

    src_conn = sqlite3.connect(source)
    try:
        src_after = {
            row[0]: row[1]
            for row in src_conn.execute("SELECT id, doi FROM documents")
        }
    finally:
        src_conn.close()
    assert src_after == src_before


def test_f1_receipt_equivalent_converges_ambiguous_keeps_zero_owner(
    tmp_path: Path,
) -> None:
    source = _populated_legacy_store(tmp_path)
    store = _backup_open(tmp_path, source)
    try:
        original_ids = {
            row[0]
            for row in store.conn.execute("SELECT id FROM documents")
        }
        receipt = execute_doi_backfill(store.conn)
        equivalent, ambiguous = inspect_f1(store.conn)
        assert receipt.equivalent == equivalent
        assert receipt.ambiguous == ambiguous

        equiv = next(group for group in equivalent if group.doi == EQUIV_DOI)
        assert equiv.accepted_count == 1
        assert set(equiv.representation_ids) == {"equiv-a", "equiv-b"}
        assert _accepted_count(store.conn, EQUIV_DOI) == 1
        work_ids = {
            row[0]
            for row in store.conn.execute(
                "SELECT work_id FROM documents WHERE id IN ('equiv-a', 'equiv-b')"
            )
        }
        assert len(work_ids) == 1
        assert None not in work_ids

        ok = next(group for group in equivalent if group.doi == OK_DOI)
        assert ok.accepted_count == 1
        assert "legacy-resolver" in ok.representation_ids

        amb = next(group for group in ambiguous if group.doi == DUP_DOI)
        assert amb.accepted_count == 0
        assert amb.redirect_count == 0
        assert set(amb.representation_ids) == {"legacy-dup-a", "legacy-dup-b"}
        assert _accepted_count(store.conn, DUP_DOI) == 0
        assert _redirect_count(store.conn) == 0

        remaining = {
            row[0]
            for row in store.conn.execute("SELECT id FROM documents")
        }
        assert remaining == original_ids
    finally:
        store.close()


def test_collision_records_pending_pair_with_zero_owner(tmp_path: Path) -> None:
    source = _populated_legacy_store(tmp_path)
    store = _backup_open(tmp_path, source)
    try:
        execute_doi_backfill(store.conn)
        pending = _pending_ids(store.conn, DUP_DOI)
        assert len(pending) == 2
        assert _accepted_count(store.conn, DUP_DOI) == 0
        dois = _doi_by_id(store.conn)
        assert dois["legacy-dup-a"] is None
        assert dois["legacy-dup-b"] is None
        assert _redirect_count(store.conn) == 0
        audit = store.conn.execute(
            "SELECT COUNT(*) FROM identifier_decisions "
            "WHERE action = 'resolve_collision'"
        ).fetchone()[0]
        assert audit >= 2
    finally:
        store.close()


def test_owned_candidate_stays_untouched_and_files_collision(
    tmp_path: Path,
) -> None:
    source = _populated_legacy_store(tmp_path)
    store = _backup_open(tmp_path, source)
    try:
        before = store.conn.execute(
            "SELECT id, doi, content_hash, raw_text_path FROM documents "
            "WHERE id = 'legacy-owned'"
        ).fetchone()
        execute_doi_backfill(store.conn)
        after = store.conn.execute(
            "SELECT id, doi, content_hash, raw_text_path FROM documents "
            "WHERE id = 'legacy-owned'"
        ).fetchone()
        assert tuple(after) == tuple(before)
        assert after[1] is None
        assert _accepted_count(store.conn, OWNED_DOI) == 0
        assert _pending_ids(store.conn, OWNED_DOI)
        owner_doi = store.conn.execute(
            "SELECT doi FROM documents WHERE doi = ?", (OWNED_DOI,)
        ).fetchone()[0]
        assert owner_doi == OWNED_DOI
    finally:
        store.close()


def test_arbitrary_uri_never_derives_a_doi(tmp_path: Path) -> None:
    source = _populated_legacy_store(tmp_path)
    store = _backup_open(tmp_path, source)
    try:
        execute_doi_backfill(store.conn)
        dois = _doi_by_id(store.conn)
        assert dois["legacy-bare"] is None
        assert dois["legacy-arbitrary"] is None
        assert store.conn.execute(
            "SELECT COUNT(*) FROM work_identifiers "
            "WHERE normalized_value IN ('10.9999/bare.doi', "
            "'https://arxiv.org/abs/2401.00001')"
        ).fetchone()[0] == 0
    finally:
        store.close()


def test_raw_text_and_citation_spans_stay_byte_identical(tmp_path: Path) -> None:
    source = _populated_legacy_store(tmp_path)
    source_raw = _raw_bytes(source)
    source_span = sqlite3.connect(source).execute(
        "SELECT source_span FROM citations WHERE item_id = 'cite-legacy-resolver'"
    ).fetchone()[0]
    assert source_span == SPAN_JSON

    store = _backup_open(tmp_path, source)
    try:
        before_raw = _raw_bytes(store.db_path)
        before_span = store.conn.execute(
            "SELECT source_span FROM citations "
            "WHERE item_id = 'cite-legacy-resolver'"
        ).fetchone()[0]
        receipt = execute_doi_backfill(store.conn)
        after_raw = _raw_bytes(store.db_path)
        after_span = store.conn.execute(
            "SELECT source_span FROM citations "
            "WHERE item_id = 'cite-legacy-resolver'"
        ).fetchone()[0]
        assert after_raw == before_raw == source_raw
        assert after_span == before_span == SPAN_JSON
        assert receipt.integrity.raw_text_identical is True
        assert receipt.integrity.citation_spans_identical is True
    finally:
        store.close()


def test_backfill_rerun_is_idempotent(tmp_path: Path) -> None:
    source = _populated_legacy_store(tmp_path)
    store = _backup_open(tmp_path, source)
    try:
        first = execute_doi_backfill(store.conn)
        dump_first = _identity_dump(store.conn)
        second = execute_doi_backfill(store.conn)
        dump_second = _identity_dump(store.conn)
        assert first.receipt_sha256 == second.receipt_sha256
        assert dump_first == dump_second
    finally:
        store.close()
