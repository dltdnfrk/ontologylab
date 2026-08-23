"""H1 historical receipt migration: baseline, then backup-copy rehearsal."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

import pytest

from ontologylab.authority_repo import create_work
from ontologylab.file_lifecycle import content_hash_for
from ontologylab.kgstore import KGStore
from ontologylab.migration import phase_is_complete, snapshot_db
from ontologylab.migration_backfill import execute_doi_backfill, prepare_backup_copy
from ontologylab.migration_rehearsal import (
    InterruptionInjected,
    current_cursor,
    run_rehearsal,
)
from ontologylab.models import SourceSpan
from tests.factories import make_entity, make_relation
from tests.wave21.identity import seed_premigration_documents_row


_TEXT = "The PaymentGateway uses the DatabaseService."
_HASH = content_hash_for(_TEXT.encode("utf-8"))
_GATEWAY = (4, 18)
_SERVICE = (28, 44)
_OK_DOI = "10.1000/backfill.ok"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _tree_hashes(root: Path) -> dict[str, str]:
    hashes: dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        if path.name.endswith("-wal") or path.name.endswith("-shm"):
            continue
        hashes[str(path.relative_to(root))] = _sha256(path)
    return hashes


def _insert_legacy_run(
    conn: sqlite3.Connection,
    *,
    run_id: str,
    document_id: str,
    content_hash: str,
    chunk_hash: str,
    offset: int = 0,
) -> None:
    decode = json.dumps({"legacy": run_id}, sort_keys=True, separators=(",", ":"))
    conn.execute(
        "INSERT INTO extraction_runs ("
        "id, document_id, document_content_hash, schema_version_id, "
        "extractor_engine, extractor_model, prompt_version, decode_params, "
        "chunk_plan_hash, status, created_ts, updated_ts) "
        "VALUES (?,?,?,?,?,?,?,?,?,'complete',0,0)",
        (
            run_id,
            document_id,
            content_hash,
            1,
            "mock",
            "",
            "extract-v1",
            decode,
            f"sha256:plan-{run_id}",
        ),
    )
    conn.execute(
        "INSERT INTO extraction_chunks ("
        "run_id, chunk_index, char_offset, content_hash, status) "
        "VALUES (?,?,?,?,'succeeded')",
        (run_id, 0, offset, chunk_hash),
    )


def _disposable_v2_layout(db: Path) -> KGStore:
    store = KGStore.open(db)
    conn = store.conn
    conn.execute("PRAGMA foreign_keys = OFF")
    conn.execute(
        """CREATE TABLE documents_v2 (
            id            TEXT PRIMARY KEY,
            source_kind   TEXT NOT NULL,
            source_uri    TEXT NOT NULL,
            title         TEXT,
            fetched_ts    REAL NOT NULL,
            content_hash  TEXT NOT NULL,
            raw_text_path TEXT NOT NULL,
            doi           TEXT,
            source        TEXT NOT NULL DEFAULT '',
            evidence_grade TEXT NOT NULL DEFAULT '',
            work_id       TEXT REFERENCES works(id),
            representation_state TEXT NOT NULL DEFAULT 'ready'
        )"""
    )
    conn.execute(
        "INSERT INTO documents_v2 SELECT id, source_kind, source_uri, title, "
        "fetched_ts, content_hash, raw_text_path, doi, source, "
        "evidence_grade, work_id, representation_state FROM documents"
    )
    conn.execute("DROP TABLE documents")
    conn.execute("ALTER TABLE documents_v2 RENAME TO documents")
    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_documents_representation "
        "ON documents (work_id, content_hash) WHERE work_id IS NOT NULL"
    )
    conn.execute("PRAGMA foreign_keys = ON")
    return store


def _insert_ready_representation(
    store: KGStore,
    *,
    representation_id: str,
    work_id: str,
) -> None:
    root = Path(store.db_path).parent / "documents" / representation_id
    root.mkdir(parents=True, exist_ok=True)
    (root / "raw.txt").write_text(_TEXT, encoding="utf-8")
    store.conn.execute(
        "INSERT INTO documents (id, source_kind, source_uri, title, "
        "fetched_ts, content_hash, raw_text_path, source, evidence_grade, "
        "work_id, representation_state) "
        "VALUES (?, 'paper_api', ?, 'paper', 0.0, ?, ?, '', '', ?, 'ready')",
        (
            representation_id,
            f"https://doi.org/10.5555/{representation_id}",
            _HASH,
            f"documents/{representation_id}/raw.txt",
            work_id,
        ),
    )


def _mark_reviewed(
    conn: sqlite3.Connection,
    *,
    kind: str,
    item_id: str,
    actor: str,
    reason: str,
) -> None:
    table = "nodes" if kind == "node" else "edges"
    conn.execute(
        f"UPDATE {table} SET status = 'verified', verified_by = ?, "
        "review_note = ?, verified_ts = 1 WHERE id = ?",
        (actor, reason, item_id),
    )


def _seed_facts(
    store: KGStore,
    doc_id: str,
    *,
    invalid_edge: bool = False,
    missing_span: bool = False,
) -> tuple[str, str, str]:
    gateway = make_entity(
        "PaymentGateway",
        source_span=SourceSpan(start=_GATEWAY[0], end=_GATEWAY[1]),
    )
    service = make_entity(
        "DatabaseService",
        source_span=SourceSpan(start=_SERVICE[0], end=_SERVICE[1]),
    )
    edge_span = (
        SourceSpan(start=0, end=999)
        if invalid_edge
        else SourceSpan(start=0, end=len(_TEXT))
    )
    relation = make_relation(gateway, service, source_span=edge_span)
    store.insert_proposed(
        [gateway, service],
        [relation],
        source_doc_id=doc_id,
        extractor_engine="mock",
        extractor_model=None,
        prompt_version="extract-v1",
        commit=False,
    )
    if missing_span:
        store.conn.execute(
            "INSERT INTO citations "
            "(kind, item_id, source_doc_id, source_span, created_ts) "
            "VALUES ('node', ?, ?, NULL, 0)",
            (gateway.id, doc_id),
        )
    _mark_reviewed(
        store.conn,
        kind="node",
        item_id=gateway.id,
        actor="historian",
        reason="legacy-node",
    )
    _mark_reviewed(
        store.conn,
        kind="node",
        item_id=service.id,
        actor="historian",
        reason="legacy-node",
    )
    _mark_reviewed(
        store.conn,
        kind="edge",
        item_id=relation.id,
        actor="historian",
        reason="legacy-edge",
    )
    return gateway.id, service.id, relation.id


def _single_rep_source(
    tmp_path: Path,
    *,
    invalid_edge: bool = False,
    missing_span: bool = False,
) -> tuple[Path, str, str, str]:
    src = tmp_path / "src"
    src.mkdir()
    db = src / "kg.sqlite"
    store = KGStore.open(db)
    document, _created = store.insert_document(
        source_kind="upload",
        source_uri="file:///h1-legacy.txt",
        title="legacy",
        raw_text=_TEXT,
        content_hash=_HASH,
    )
    _insert_legacy_run(
        store.conn,
        run_id="run-a",
        document_id=document.id,
        content_hash=_HASH,
        chunk_hash=_HASH,
    )
    gateway_id, service_id, edge_id = _seed_facts(
        store,
        document.id,
        invalid_edge=invalid_edge,
        missing_span=missing_span,
    )
    store.conn.commit()
    store.close()
    return db, gateway_id, service_id, edge_id


def _two_rep_source(tmp_path: Path) -> Path:
    src = tmp_path / "src-two"
    src.mkdir()
    store = _disposable_v2_layout(src / "kg.sqlite")
    create_work(store.conn, "work-a")
    create_work(store.conn, "work-b")
    _insert_ready_representation(
        store, representation_id="rep-a", work_id="work-a",
    )
    _insert_ready_representation(
        store, representation_id="rep-b", work_id="work-b",
    )
    _insert_legacy_run(
        store.conn,
        run_id="run-a",
        document_id="rep-a",
        content_hash=_HASH,
        chunk_hash=_HASH,
    )
    _insert_legacy_run(
        store.conn,
        run_id="run-b",
        document_id="rep-b",
        content_hash=_HASH,
        chunk_hash=_HASH,
    )
    _seed_facts(store, "rep-a")
    _seed_facts(store, "rep-b")
    store.conn.commit()
    store.close()
    return src / "kg.sqlite"


def _run_cli(*argv: str) -> tuple[int, str]:
    from io import StringIO
    from contextlib import redirect_stdout

    from ontologylab.main import main

    buf = StringIO()
    with redirect_stdout(buf), pytest.raises(SystemExit) as exited:
        main(list(argv))
    return int(exited.value.code or 0), buf.getvalue()


def test_baseline_backup_copy_preserves_source_bytes(tmp_path: Path) -> None:
    source = tmp_path / "src"
    source.mkdir()
    db = source / "kg.sqlite"
    seed_premigration_documents_row(
        db,
        doc_id="legacy-resolver",
        source_uri="https://doi.org/10.1000/backfill.ok",
        raw_text="legacy body for resolver",
        content_hash="sha256:bf-1",
    )
    before = _tree_hashes(source)
    target = tmp_path / "copy"
    target.mkdir()
    copied = prepare_backup_copy(db, target)
    assert copied.is_file()
    assert _tree_hashes(source) == before


def test_baseline_doi_backfill_still_sets_resolver_doi(tmp_path: Path) -> None:
    source = tmp_path / "src"
    source.mkdir()
    db = source / "kg.sqlite"
    seed_premigration_documents_row(
        db,
        doc_id="legacy-resolver",
        source_uri="https://doi.org/10.1000/backfill.ok",
        raw_text="legacy body for resolver",
        content_hash="sha256:bf-1",
    )
    target = tmp_path / "copy"
    target.mkdir()
    store = KGStore.open(prepare_backup_copy(db, target))
    try:
        execute_doi_backfill(store.conn)
        doi = store.conn.execute(
            "SELECT doi FROM documents WHERE id = 'legacy-resolver'"
        ).fetchone()[0]
        assert doi == _OK_DOI
    finally:
        store.close()


def test_baseline_rehearsal_interrupt_keeps_cursor(tmp_path: Path) -> None:
    source = tmp_path / "src" / "kg.sqlite"
    source.parent.mkdir()
    store = KGStore.open(source)
    for doc_id in ("doc-a", "doc-m", "doc-z"):
        store.conn.execute(
            "INSERT INTO documents "
            "(id, source_kind, source_uri, title, fetched_ts, content_hash, "
            "raw_text_path) VALUES (?, 'upload', ?, ?, 0, ?, ?)",
            (
                doc_id,
                f"file:///{doc_id}.txt",
                doc_id,
                f"sha256:{doc_id}",
                f"documents/{doc_id}/raw.txt",
            ),
        )
    store.conn.commit()
    store.close()
    target = tmp_path / "copy"
    target.mkdir()
    copied = snapshot_db(source, target)
    src = KGStore.open(source)
    copy = KGStore.open(copied)
    try:
        def _hook(row_id: str) -> None:
            if row_id == "doc-z":
                raise InterruptionInjected(row_id=row_id, phase="expand")

        with pytest.raises(InterruptionInjected):
            run_rehearsal(src.conn, copy.conn, failpoint=_hook)
        copy.conn.commit()
        assert current_cursor(copy.conn, "expand") == "doc-m"
        assert not phase_is_complete(copy.conn, "expand")
    finally:
        src.close()
        copy.close()


def test_h1_same_hash_two_reps_do_not_share_run_authority(tmp_path: Path) -> None:
    from ontologylab.h1 import run_h1_operator

    source = _two_rep_source(tmp_path)
    dest = tmp_path / "dest-two"
    dest.mkdir()
    receipt = run_h1_operator(source, dest)
    store = KGStore.open(dest / source.name)
    try:
        runs = store.conn.execute(
            "SELECT representation_id, receipt_id FROM extraction_run_receipts "
            "ORDER BY representation_id"
        ).fetchall()
        assert [row[0] for row in runs] == ["rep-a", "rep-b"]
        assert runs[0][1] != runs[1][1]
        cite_runs = {
            row[0]: row[1]
            for row in store.conn.execute(
                "SELECT representation_id, run_receipt_id FROM citation_receipts"
            )
        }
        assert cite_runs["rep-a"] == runs[0][1]
        assert cite_runs["rep-b"] == runs[1][1]
        assert receipt.inventory.pending == 0
    finally:
        store.close()


def test_h1_classifies_every_node_edge_citation_review_anchor(
    tmp_path: Path,
) -> None:
    from ontologylab.h1 import run_h1_operator
    from ontologylab.h1_types import H1Classification, H1QuarantineReason

    source, _gateway, _service, edge_id = _single_rep_source(
        tmp_path, invalid_edge=True,
    )
    dest = tmp_path / "dest-root"
    dest.mkdir()
    receipt = run_h1_operator(source, dest)
    families = {item.family.value: item for item in receipt.inventory.families}
    assert set(families) == {"run", "chunk", "citation", "review"}
    for item in families.values():
        assert item.pending == 0
        assert item.verified + item.quarantined > 0
    store = KGStore.open(dest / source.name)
    try:
        edge_cite = store.conn.execute(
            "SELECT classification, quarantine_reason FROM h1_anchor_receipts "
            "WHERE family = 'citation' AND legacy_pk LIKE ?",
            (f"%{edge_id}%",),
        ).fetchone()
        assert edge_cite[0] == H1Classification.QUARANTINED.value
        assert edge_cite[1] == H1QuarantineReason.OUT_OF_RANGE.value
        edge_review = store.conn.execute(
            "SELECT classification FROM h1_anchor_receipts "
            "WHERE family = 'review' AND legacy_pk = ?",
            (f"edge:{edge_id}",),
        ).fetchone()
        assert edge_review[0] == H1Classification.QUARANTINED.value
        assert receipt.inventory.pending == 0
    finally:
        store.close()


def test_h1_out_of_range_span_is_quarantined_not_repaired(tmp_path: Path) -> None:
    from ontologylab.h1 import run_h1_operator
    from ontologylab.h1_types import H1Classification, H1QuarantineReason

    source, _gateway, _service, edge_id = _single_rep_source(
        tmp_path, invalid_edge=True,
    )
    src_conn = sqlite3.connect(source)
    try:
        original = src_conn.execute(
            "SELECT source_span FROM citations WHERE item_id = ?",
            (edge_id,),
        ).fetchone()[0]
    finally:
        src_conn.close()
    dest = tmp_path / "dest-span"
    dest.mkdir()
    run_h1_operator(source, dest)
    store = KGStore.open(dest / source.name)
    try:
        after = store.conn.execute(
            "SELECT source_span FROM citations WHERE item_id = ?",
            (edge_id,),
        ).fetchone()[0]
        assert after == original
        assert json.loads(after)["end"] == 999
        row = store.conn.execute(
            "SELECT classification, quarantine_reason FROM h1_anchor_receipts "
            "WHERE family = 'citation' AND legacy_pk LIKE ?",
            (f"%{edge_id}%",),
        ).fetchone()
        assert row[0] == H1Classification.QUARANTINED.value
        assert row[1] == H1QuarantineReason.OUT_OF_RANGE.value
        verified_edge = store.conn.execute(
            "SELECT COUNT(*) FROM citation_receipts WHERE fact_id = ?",
            (edge_id,),
        ).fetchone()[0]
        assert verified_edge == 0
    finally:
        store.close()


def test_h1_rerun_is_idempotent_and_byte_identical(tmp_path: Path) -> None:
    from ontologylab.h1 import run_h1_operator
    from ontologylab.migration_rehearsal import canonical_db_hash

    source, _, _, _ = _single_rep_source(tmp_path)
    dest = tmp_path / "dest-idemp"
    dest.mkdir()
    first = run_h1_operator(source, dest)
    store = KGStore.open(dest / source.name)
    try:
        dump_first = canonical_db_hash(store.conn)
        count_first = store.conn.execute(
            "SELECT COUNT(*) FROM h1_anchor_receipts"
        ).fetchone()[0]
    finally:
        store.close()
    second = run_h1_operator(source, dest)
    store = KGStore.open(dest / source.name)
    try:
        dump_second = canonical_db_hash(store.conn)
        count_second = store.conn.execute(
            "SELECT COUNT(*) FROM h1_anchor_receipts"
        ).fetchone()[0]
    finally:
        store.close()
    assert first.receipt_sha256 == second.receipt_sha256
    assert first.dump_sha256 == second.dump_sha256 == dump_first == dump_second
    assert count_first == count_second
    assert first.inventory.pending == second.inventory.pending == 0


def test_h1_operator_does_not_mutate_source(tmp_path: Path) -> None:
    from ontologylab.h1 import run_h1_operator

    source, _, _, _ = _single_rep_source(tmp_path)
    before = _tree_hashes(source.parent)
    dest = tmp_path / "dest-src"
    dest.mkdir()
    run_h1_operator(source, dest)
    assert _tree_hashes(source.parent) == before


def test_h1_missing_span_is_quarantined_not_verified(tmp_path: Path) -> None:
    from ontologylab.h1 import run_h1_operator
    from ontologylab.h1_types import H1Classification, H1QuarantineReason

    source, gateway_id, _, _ = _single_rep_source(tmp_path, missing_span=True)
    dest = tmp_path / "dest-miss"
    dest.mkdir()
    receipt = run_h1_operator(source, dest)
    store = KGStore.open(dest / source.name)
    try:
        row = store.conn.execute(
            "SELECT classification, quarantine_reason FROM h1_anchor_receipts "
            "WHERE family = 'citation' AND legacy_pk LIKE ? "
            "AND quarantine_reason = ?",
            (f"%{gateway_id}%", H1QuarantineReason.MISSING_SPAN.value),
        ).fetchone()
        assert row is not None
        assert row[0] == H1Classification.QUARANTINED.value
        assert receipt.inventory.pending == 0
    finally:
        store.close()


def test_h1_pending_zero_includes_quarantine(tmp_path: Path) -> None:
    from ontologylab.h1 import run_h1_operator

    source, _, _, _ = _single_rep_source(tmp_path, invalid_edge=True)
    dest = tmp_path / "dest-pending"
    dest.mkdir()
    receipt = run_h1_operator(source, dest)
    assert receipt.inventory.pending == 0
    assert receipt.inventory.quarantined > 0
    assert (
        receipt.inventory.verified + receipt.inventory.quarantined
        == receipt.inventory.anchor_count
    )
    for item in receipt.inventory.families:
        assert item.pending == 0
        assert item.verified + item.quarantined == item.anchor_count


def test_h1_interrupt_resume_does_not_duplicate(tmp_path: Path) -> None:
    from ontologylab.h1 import prepare_h1_copy, run_h1_migration
    from ontologylab.h1_types import H1Interruption

    source, _, _, _ = _single_rep_source(tmp_path)
    dest_dir = tmp_path / "dest-resume"
    dest_dir.mkdir()
    copied = prepare_h1_copy(source, dest_dir)
    store = KGStore.open(copied)
    seen: list[str] = []
    try:
        def _failpoint(anchor_id: str) -> None:
            seen.append(anchor_id)
            if len(seen) == 2:
                raise H1Interruption(anchor_id=anchor_id)

        with pytest.raises(H1Interruption):
            run_h1_migration(store.conn, failpoint=_failpoint)
        store.conn.commit()
        first_count = store.conn.execute(
            "SELECT COUNT(*) FROM h1_anchor_receipts"
        ).fetchone()[0]
        assert first_count == 2
        cursor = store.conn.execute(
            "SELECT cursor FROM h1_migration_ledger ORDER BY seq DESC LIMIT 1"
        ).fetchone()[0]
        assert cursor == seen[1]
    finally:
        store.close()

    store = KGStore.open(copied)
    try:
        receipt = run_h1_migration(store.conn)
        store.conn.commit()
        assert receipt.inventory.pending == 0
        assert receipt.complete is True
        ids = [
            row[0]
            for row in store.conn.execute(
                "SELECT receipt_id FROM h1_anchor_receipts ORDER BY receipt_id"
            )
        ]
        assert len(ids) == len(set(ids))
        assert len(ids) == receipt.inventory.anchor_count
    finally:
        store.close()


def test_h1_verified_receipts_seal_raw_file_and_span_hashes(tmp_path: Path) -> None:
    from ontologylab.h1 import run_h1_operator

    source, gateway_id, _, _ = _single_rep_source(tmp_path)
    dest = tmp_path / "dest-seal"
    dest.mkdir()
    run_h1_operator(source, dest)
    store = KGStore.open(dest / source.name)
    try:
        row = store.conn.execute(
            "SELECT raw_byte_seal, file_hash, span_hash, classification "
            "FROM h1_anchor_receipts WHERE family = 'citation' "
            "AND legacy_pk LIKE ? AND classification = 'verified'",
            (f"%{gateway_id}%",),
        ).fetchone()
        assert row is not None
        assert row[0] == _HASH
        assert row[1] == _HASH
        selected = _TEXT[_GATEWAY[0]:_GATEWAY[1]]
        assert row[2] == content_hash_for(selected.encode("utf-8"))
        run_row = store.conn.execute(
            "SELECT raw_byte_seal, file_hash FROM h1_anchor_receipts "
            "WHERE family = 'run' AND classification = 'verified'"
        ).fetchone()
        assert run_row[0] == _HASH
        assert run_row[1] == _HASH
    finally:
        store.close()


def test_h1_receipt_families_include_run_chunk_citation_review(
    tmp_path: Path,
) -> None:
    from ontologylab.h1 import run_h1_operator

    source, _, _, _ = _single_rep_source(tmp_path)
    dest = tmp_path / "dest-fam"
    dest.mkdir()
    receipt = run_h1_operator(source, dest)
    families = {item.family.value for item in receipt.inventory.families}
    assert families == {"run", "chunk", "citation", "review"}
    store = KGStore.open(dest / source.name)
    try:
        for family in ("run", "chunk", "citation", "review"):
            count = store.conn.execute(
                "SELECT COUNT(*) FROM h1_anchor_receipts WHERE family = ?",
                (family,),
            ).fetchone()[0]
            assert count > 0
        assert store.conn.execute(
            "SELECT COUNT(*) FROM extraction_run_receipts"
        ).fetchone()[0] == 1
        assert store.conn.execute(
            "SELECT COUNT(*) FROM extraction_chunk_receipts"
        ).fetchone()[0] == 1
        assert store.conn.execute(
            "SELECT COUNT(*) FROM citation_receipts"
        ).fetchone()[0] >= 2
        assert store.conn.execute(
            "SELECT COUNT(*) FROM grounded_review_decisions"
        ).fetchone()[0] >= 2
    finally:
        store.close()


def test_h1_malformed_source_is_typed_refusal(tmp_path: Path) -> None:
    from ontologylab.h1 import run_h1_operator
    from ontologylab.h1_types import H1RefusalCode, H1SourceRefused

    bad = tmp_path / "not.sqlite"
    bad.write_text("this is not sqlite", encoding="utf-8")
    dest = tmp_path / "dest-bad"
    with pytest.raises(H1SourceRefused) as refused:
        run_h1_operator(bad, dest)
    assert refused.value.code is H1RefusalCode.NOT_SQLITE
    assert not dest.exists() or not any(dest.rglob("kg.sqlite"))
    assert not dest.exists() or not any(dest.rglob("h1_anchor_receipts"))


def test_cli_migrate_h1_writes_inventory(tmp_path: Path) -> None:
    source, _, _, _ = _single_rep_source(tmp_path)
    dest = tmp_path / "dest-cli"
    code, stdout = _run_cli(
        "migrate-h1",
        "--source",
        str(source),
        "--dest",
        str(dest),
    )
    assert code == 0
    payload = json.loads(stdout)
    assert payload["pending"] == 0
    assert payload["complete"] is True
    assert payload["verified"] > 0
    assert "dump_sha256" in payload
    assert "receipt_sha256" in payload
    assert set(payload["families"]) == {"run", "chunk", "citation", "review"}


def test_cli_malformed_source_refuses_without_dest(tmp_path: Path) -> None:
    bad = tmp_path / "nope.txt"
    bad.write_bytes(b"not-a-database")
    dest = tmp_path / "dest-cli-bad"
    code, stdout = _run_cli(
        "migrate-h1",
        "--source",
        str(bad),
        "--dest",
        str(dest),
    )
    assert code != 0
    payload = json.loads(stdout)
    assert payload["code"] == "not_sqlite"
    assert not dest.exists() or not any(dest.rglob("*.sqlite"))


def test_h1_source_dest_same_root_is_typed_refusal(tmp_path: Path) -> None:
    from ontologylab.h1 import run_h1_operator
    from ontologylab.h1_types import H1RefusalCode, H1SourceRefused

    source, _, _, _ = _single_rep_source(tmp_path)
    before = _tree_hashes(source.parent)
    with pytest.raises(H1SourceRefused) as refused:
        run_h1_operator(source, source.parent)
    assert refused.value.code is H1RefusalCode.SOURCE_OVERLAP
    assert _tree_hashes(source.parent) == before
    src = sqlite3.connect(source)
    try:
        present = src.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' "
            "AND name = 'h1_anchor_receipts'"
        ).fetchone()
        assert present is None
    finally:
        src.close()


def test_h1_dest_inside_source_tree_is_typed_refusal(tmp_path: Path) -> None:
    from ontologylab.h1 import run_h1_operator
    from ontologylab.h1_types import H1RefusalCode, H1SourceRefused

    source, _, _, _ = _single_rep_source(tmp_path)
    before = _tree_hashes(source.parent)
    inside = source.parent / "nested-dest"
    with pytest.raises(H1SourceRefused) as refused:
        run_h1_operator(source, inside)
    assert refused.value.code is H1RefusalCode.SOURCE_OVERLAP
    assert _tree_hashes(source.parent) == before
    assert not inside.exists()


def test_h1_verified_family_receipt_id_matches_task_tables(tmp_path: Path) -> None:
    from ontologylab.h1 import run_h1_operator

    source, _, _, _ = _single_rep_source(tmp_path)
    dest = tmp_path / "dest-family-id"
    dest.mkdir()
    first = run_h1_operator(source, dest)
    store = KGStore.open(dest / source.name)
    try:
        rows = store.conn.execute(
            "SELECT family, classification, family_receipt_id FROM "
            "h1_anchor_receipts ORDER BY family, family_receipt_id"
        ).fetchall()
        verified_ids: list[tuple[str, str]] = []
        for family, classification, family_id in rows:
            if classification == "quarantined":
                assert family_id is None
                continue
            assert classification == "verified"
            assert family_id is not None
            assert family_id != ""
            table = {
                "run": "extraction_run_receipts",
                "chunk": "extraction_chunk_receipts",
                "citation": "citation_receipts",
                "review": "grounded_review_decisions",
            }[str(family)]
            found = store.conn.execute(
                f"SELECT 1 FROM {table} WHERE receipt_id = ?",
                (family_id,),
            ).fetchone()
            assert found is not None
            verified_ids.append((str(family), str(family_id)))
        assert {family for family, _id in verified_ids} == {
            "run", "chunk", "citation", "review",
        }
    finally:
        store.close()
    second = run_h1_operator(source, dest)
    assert first.receipt_sha256 == second.receipt_sha256
    assert first.dump_sha256 == second.dump_sha256


def test_h1_verified_review_seals_match_citation_set_and_decision(
    tmp_path: Path,
) -> None:
    from ontologylab.h1 import run_h1_operator

    source, gateway_id, _, _ = _single_rep_source(tmp_path)
    dest = tmp_path / "dest-review-seals"
    dest.mkdir()
    run_h1_operator(source, dest)
    store = KGStore.open(dest / source.name)
    try:
        row = store.conn.execute(
            "SELECT family_receipt_id, raw_byte_seal, file_hash, span_hash "
            "FROM h1_anchor_receipts WHERE family = 'review' "
            "AND classification = 'verified' AND legacy_pk = ?",
            (f"node:{gateway_id}",),
        ).fetchone()
        assert row is not None
        family_id, raw_seal, file_hash, span_hash = row
        assert family_id
        assert raw_seal
        assert file_hash
        assert span_hash
        decision = store.conn.execute(
            "SELECT receipt_id, citation_set_digest FROM "
            "grounded_review_decisions WHERE fact_kind = 'node' "
            "AND fact_id = ?",
            (gateway_id,),
        ).fetchone()
        assert decision is not None
        assert family_id == decision[0]
        assert span_hash == decision[1]
        assert file_hash == _HASH
        assert raw_seal == _HASH
    finally:
        store.close()


def test_h1_missing_review_timestamp_is_quarantined(tmp_path: Path) -> None:
    from ontologylab.h1 import run_h1_operator
    from ontologylab.h1_types import H1Classification, H1QuarantineReason

    source, gateway_id, _, _ = _single_rep_source(tmp_path)
    src = sqlite3.connect(source)
    try:
        src.execute(
            "UPDATE nodes SET verified_ts = NULL WHERE id = ?",
            (gateway_id,),
        )
        src.commit()
    finally:
        src.close()
    dest = tmp_path / "dest-miss-ts"
    dest.mkdir()
    run_h1_operator(source, dest)
    store = KGStore.open(dest / source.name)
    try:
        row = store.conn.execute(
            "SELECT classification, quarantine_reason, family_receipt_id "
            "FROM h1_anchor_receipts WHERE family = 'review' "
            "AND legacy_pk = ?",
            (f"node:{gateway_id}",),
        ).fetchone()
        assert row is not None
        assert row[0] == H1Classification.QUARANTINED.value
        assert row[1] == H1QuarantineReason.MISSING_TIMESTAMP.value
        assert row[2] is None
        written = store.conn.execute(
            "SELECT COUNT(*) FROM grounded_review_decisions "
            "WHERE fact_kind = 'node' AND fact_id = ?",
            (gateway_id,),
        ).fetchone()[0]
        assert written == 0
    finally:
        store.close()


def test_cli_source_overlap_refuses_without_partial(tmp_path: Path) -> None:
    source, _, _, _ = _single_rep_source(tmp_path)
    before = _tree_hashes(source.parent)
    code, stdout = _run_cli(
        "migrate-h1",
        "--source",
        str(source),
        "--dest",
        str(source.parent),
    )
    assert code != 0
    payload = json.loads(stdout)
    assert payload["code"] == "source_overlap"
    assert _tree_hashes(source.parent) == before
