"""Additive Method-schema migration and immutable-pack compatibility tests."""
from __future__ import annotations
import hashlib
import shutil
import sqlite3
from pathlib import Path
import pytest
from ontologylab.kgstore import KGStore
from ontologylab.packbuilder import build_pack
from tests.test_method_store import METHOD_TABLES, _graph_image, _seed


def _method_objects(conn: sqlite3.Connection) -> set[str]:
    return {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE "
        "name LIKE 'method_%' OR name IN ('source_policy', "
        "'document_policy_snapshot', 'statement_occurrence', 'bridge_proposal', "
        "'bridge_evidence')")}


def _drop_method_schema(path: Path) -> None:
    conn = sqlite3.connect(path)
    try:
        objects = list(conn.execute("SELECT type, name FROM sqlite_master WHERE "
            "name LIKE 'method_%' OR name IN ('source_policy', "
            "'document_policy_snapshot', 'statement_occurrence', 'bridge_proposal', "
            "'bridge_evidence') ORDER BY CASE type WHEN 'trigger' THEN 0 "
            "WHEN 'index' THEN 1 ELSE 2 END, name DESC"))
        for kind, name in objects:
            if kind in {"trigger", "index"}:
                conn.execute(f'DROP {kind.upper()} IF EXISTS "{name}"')
        for table in ("method_release", "method_compilation_gate",
                "method_compilation_attempt",
                "method_counter_evidence_search", "method_review_event",
                "bridge_evidence", "bridge_proposal", "method_gap", "method_link",
                "method_fragment_evidence", "method_fragment",
                "method_extraction_chunks", "method_extraction_runs",
                "statement_occurrence", "method_workspace",
                "document_policy_snapshot", "source_policy"):
            conn.execute(f'DROP TABLE IF EXISTS "{table}"')
        conn.commit()
    finally:
        conn.close()


def test_fresh_migration_is_exact_idempotent_and_not_in_graph_schema(
    tmp_path: Path,
) -> None:
    from ontologylab import kgstore as kgstore_module
    from ontologylab.method_store import ensure_method_schema
    path = tmp_path / "fresh.sqlite"
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    try:
        ensure_method_schema(conn)
        assert conn.in_transaction
        assert METHOD_TABLES == {row[0] for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        conn.commit()
        first = sorted(map(tuple, conn.execute(
            "SELECT type, name, sql FROM sqlite_master "
            "WHERE name NOT LIKE 'sqlite_%'")))
        ensure_method_schema(conn)
        conn.commit()
        second = sorted(map(tuple, conn.execute(
            "SELECT type, name, sql FROM sqlite_master "
            "WHERE name NOT LIKE 'sqlite_%'")))
        assert first == second
        assert "method_workspace" not in kgstore_module._SCHEMA
        assert "source_policy" not in kgstore_module._SCHEMA
    finally:
        conn.close()


@pytest.mark.parametrize("phase, denied", [
    (sqlite3.SQLITE_CREATE_TABLE, "method_gap"),
    (sqlite3.SQLITE_CREATE_TABLE, "method_compilation_gate"),
    (sqlite3.SQLITE_CREATE_INDEX, "idx_method_gap_workspace"),
    (sqlite3.SQLITE_CREATE_TRIGGER, "method_release_no_update"),
])
def test_ddl_failure_rolls_back_every_owned_object_twice(
    tmp_path: Path, phase: int, denied: str,
) -> None:
    from ontologylab.method_store import ensure_method_schema
    path = tmp_path / f"failure-{phase}.sqlite"
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    def authorizer(action, first, _second, _database, _trigger):
        return sqlite3.SQLITE_DENY if action == phase and first == denied else sqlite3.SQLITE_OK
    try:
        conn.set_authorizer(authorizer)
        for _ in range(2):
            with pytest.raises(sqlite3.DatabaseError):
                ensure_method_schema(conn)
            assert not conn.in_transaction
            assert _method_objects(conn) == set()
    finally:
        conn.set_authorizer(None)
        conn.close()


def test_caller_rollback_removes_successful_ddl(tmp_path: Path) -> None:
    from ontologylab.method_store import ensure_method_schema
    path = tmp_path / "rollback.sqlite"
    conn = sqlite3.connect(path)
    try:
        ensure_method_schema(conn)
        assert _method_objects(conn)
        conn.rollback()
        assert _method_objects(conn) == set()
        ensure_method_schema(conn)
        conn.commit()
        assert METHOD_TABLES <= _method_objects(conn)
    finally:
        conn.close()


def test_production_shaped_owned_copy_migrates_additively(tmp_path: Path) -> None:
    source, document, _, graph_before = _seed(tmp_path / "source")
    source_path = source.db_path
    source.conn.execute("INSERT INTO nodes (id, schema_version_id, entity_type, "
        "name, normalized_name, status, source_doc_id, extractor_engine, created_ts) "
        "VALUES ('legacy-node', 1, 'Component', 'Legacy', 'legacy', 'proposed', "
        "?, 'fixture', 1.0)", (document.id,))
    source.conn.commit()
    graph_before = _graph_image(source.conn)
    source.close()
    _drop_method_schema(source_path)
    copied = tmp_path / "copied-production.sqlite"
    shutil.copy2(source_path, copied)
    migrated = KGStore.open(copied)
    try:
        assert METHOD_TABLES <= {row[0] for row in migrated.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        assert _graph_image(migrated.conn) == graph_before
        assert sqlite3.connect(source_path).execute("SELECT COUNT(*) FROM nodes").fetchone()[0] == 1
    finally:
        migrated.close()


def test_task3_database_adds_receipt_columns_and_gate_table(
    tmp_path: Path,
) -> None:
    from ontologylab.method_store import MethodStore, MethodUnitOfWork
    from tests.test_method_store import _bootstrap, _bound_compiler_receipt

    store, document, _, _ = _seed(tmp_path / "task3")
    _bootstrap(store, document)
    path = store.db_path
    store.close()
    legacy = sqlite3.connect(path)
    try:
        legacy.execute("PRAGMA foreign_keys=OFF")
        for trigger in (
            "method_release_requires_passed_gates",
            "method_gate_no_update",
            "method_gate_no_delete",
            "method_attempt_requires_gates",
        ):
            legacy.execute(f'DROP TRIGGER IF EXISTS "{trigger}"')
        legacy.execute("DROP TABLE method_compilation_gate")
        legacy.execute("DROP INDEX idx_method_attempt_workspace")
        for trigger in (
            "method_release_attempt_binding",
            "method_attempt_no_update",
            "method_attempt_no_delete",
            "method_release_no_update",
            "method_release_no_delete",
        ):
            legacy.execute(f'DROP TRIGGER IF EXISTS "{trigger}"')
        legacy.commit()
    finally:
        legacy.close()

    migrated = KGStore.open(path)
    try:
        assert {
            row[1]
            for row in migrated.conn.execute(
                "PRAGMA table_info(method_compilation_attempt)"
            )
        } >= {"compiler_receipt_json", "compiler_receipt_hash"}
        assert migrated.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name='method_compilation_gate'"
        ).fetchone()[0] == "method_compilation_gate"
        receipt = _bound_compiler_receipt(
            migrated, MethodStore, MethodUnitOfWork,
            attempt_id="typed-attempt", release_id="typed-release",
        )
        with MethodUnitOfWork(migrated.conn) as uow:
            MethodStore(migrated.conn, uow).record_compilation_attempt(
                receipt
            )
        assert migrated.conn.execute(
            "SELECT COUNT(*) FROM method_compilation_gate "
            "WHERE attempt_id='typed-attempt'"
        ).fetchone()[0] == 9
    finally:
        migrated.close()


def test_pre_remediation_schema_gets_semantic_release_triggers(
    tmp_path: Path,
) -> None:
    from ontologylab.method_store import MethodStore, MethodUnitOfWork
    from tests.test_method_release import _insert_ordinary_rows
    from tests.test_method_store import _bootstrap, _bound_compiler_receipt

    store, document, _, _ = _seed(tmp_path / "legacy-contract")
    _bootstrap(store, document)
    path = store.db_path
    store.close()
    legacy = sqlite3.connect(path)
    try:
        legacy.execute("PRAGMA foreign_keys=OFF")
        for trigger in (
            "method_attempt_semantic_check",
            "method_gate_semantic_check",
            "method_release_semantic_check",
        ):
            legacy.execute(f'DROP TRIGGER IF EXISTS "{trigger}"')
        legacy.commit()
    finally:
        legacy.close()

    migrated = KGStore.open(path)
    try:
        receipt = _bound_compiler_receipt(
            migrated, MethodStore, MethodUnitOfWork
        )
        from tests.test_method_release import _ordinary_release_rows
        rows = _ordinary_release_rows(receipt)
        rows["release"][2] = "method-unrelated"
        with pytest.raises(sqlite3.IntegrityError):
            with MethodUnitOfWork(migrated.conn):
                _insert_ordinary_rows(migrated.conn, rows)
        assert migrated.conn.execute(
            "SELECT COUNT(*) FROM method_release"
        ).fetchone()[0] == 0
    finally:
        migrated.close()


def test_graph_only_pack_opens_read_only_without_migration(tmp_path: Path) -> None:
    store, document, _, _ = _seed(tmp_path / "source")
    store.conn.execute("INSERT INTO nodes (id, schema_version_id, entity_type, name, "
        "normalized_name, status, source_doc_id, extractor_engine, created_ts) "
        "VALUES ('pack-node', 1, 'Component', 'Pack', 'pack', 'verified', ?, "
        "'fixture', 1.0)", (document.id,))
    store.conn.commit()
    manifest = build_pack(store.db_path, tmp_path / "packs", name="historical",
        allow_incomplete_extraction=True,
        incomplete_extraction_intent="read-only migration fixture")
    store.close()
    pack = tmp_path / "packs" / manifest.pack_id / "pack.sqlite"
    before = hashlib.sha256(pack.read_bytes()).hexdigest()
    historical = KGStore.open(pack, read_only=True)
    try:
        assert historical.conn.execute("SELECT COUNT(*) FROM nodes").fetchone()[0] == 1
        assert historical.conn.execute(
            "SELECT canonical_json_valid('{}')"
        ).fetchone()[0] == 1
        assert not (METHOD_TABLES & {row[0] for row in historical.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")})
        with pytest.raises(sqlite3.OperationalError, match="readonly"):
            historical.conn.execute("CREATE TABLE forbidden(id INTEGER)")
    finally:
        historical.close()
    assert hashlib.sha256(pack.read_bytes()).hexdigest() == before


def test_release_review_search_append_only_and_gap_upsert_preserves_human_state(
    tmp_path: Path,
) -> None:
    from ontologylab.method_store import MethodStore, MethodUnitOfWork
    store, document, _, graph_before = _seed(tmp_path)
    from tests.test_method_store import _bootstrap, _bound_compiler_receipt
    payload = {
        "id": "method-1", "schema_version": "method-v1", "version": 1
    }
    try:
        _bootstrap(store, document)
        with MethodUnitOfWork(store.conn) as uow:
            method = MethodStore(store.conn, uow)
            method.upsert_gap("gap-1", workspace_id="workspace-1",
                gap_class="required_slot_missing", target_fragment_id=None,
                field_path=None, detector_id="detector", detector_version="1",
                input_snapshot_hash="sha256:" + "7" * 64, detail={"run": 1})
            method.decide("gap", "gap-1", "waived", reviewer="human",
                note="known bounded omission")
            method.upsert_gap("gap-1", workspace_id="workspace-1",
                gap_class="required_slot_missing", target_fragment_id=None,
                field_path=None, detector_id="detector", detector_version="2",
                input_snapshot_hash="sha256:" + "8" * 64, detail={"run": 2})
        receipt = _bound_compiler_receipt(
            store, MethodStore, MethodUnitOfWork
        )
        with MethodUnitOfWork(store.conn) as uow:
            method = MethodStore(store.conn, uow)
            method.record_compilation_attempt(receipt)
            method.insert_release(
                method_id="method-1",
                method_json=payload,
                source_index=(),
                compiler_receipt=receipt,
                review_receipt={"reviewer": "human-1"},
            )
        gap = store.conn.execute("SELECT status, detector_version, detail_json FROM "
            "method_gap WHERE id='gap-1'").fetchone()
        assert tuple(gap) == ("waived", "2", '{"run":2}')
        for table in ("method_review_event", "method_release"):
            with pytest.raises(sqlite3.IntegrityError, match="append-only"):
                store.conn.execute(f"UPDATE {table} SET created_ts=created_ts WHERE 1")
            store.conn.rollback()
            with pytest.raises(sqlite3.IntegrityError, match="append-only"):
                store.conn.execute(f"DELETE FROM {table} WHERE 1")
            store.conn.rollback()
        assert _graph_image(store.conn) == graph_before
    finally:
        store.close()


def test_real_open_rolls_back_graph_and_method_ddl_on_method_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import ontologylab.method_store as method_store

    path = tmp_path / "legacy.sqlite"
    KGStore.open(path).close()
    _drop_method_schema(path)
    conn = sqlite3.connect(path)
    try:
        conn.execute("PRAGMA journal_mode=DELETE")
        conn.execute("DROP TABLE ontologylab_storage_metadata")
        conn.commit()
        before = {
            (row[0], row[1], row[2])
            for row in conn.execute(
                "SELECT type, name, sql FROM sqlite_master "
                "WHERE name NOT LIKE 'sqlite_%'"
            )
        }
    finally:
        conn.close()

    ensure_schema = method_store.ensure_method_schema

    def fail_after_method_ddl(conn: sqlite3.Connection) -> None:
        ensure_schema(conn)
        raise sqlite3.DatabaseError("injected Method migration failure")

    monkeypatch.setattr(
        method_store, "ensure_method_schema", fail_after_method_ddl, raising=True
    )
    with pytest.raises(sqlite3.DatabaseError, match="injected Method"):
        KGStore.open(path)

    observer = sqlite3.connect(path)
    try:
        after = {
            (row[0], row[1], row[2])
            for row in observer.execute(
                "SELECT type, name, sql FROM sqlite_master "
                "WHERE name NOT LIKE 'sqlite_%'"
            )
        }
        assert after == before
        assert _method_objects(observer) == set()
    finally:
        observer.close()


def test_architecture_columns_and_state_vocabularies_are_exact(
    tmp_path: Path,
) -> None:
    store = KGStore.open(tmp_path / "schema.sqlite")
    try:
        workspace_columns = {
            row[1] for row in store.conn.execute("PRAGMA table_info(method_workspace)")
        }
        assert "method_schema_version" in workspace_columns
        sql = {
            row[0]: row[1]
            for row in store.conn.execute(
                "SELECT name, sql FROM sqlite_master WHERE type='table' "
                "AND name IN ('method_workspace','statement_occurrence',"
                "'method_fragment','bridge_evidence')"
            )
        }
        assert all(
            f"'{state}'" in sql["method_workspace"]
            for state in ("draft", "review_ready", "compiled", "superseded")
        )
        assert "'active'" not in sql["method_workspace"]
        assert "'closed'" not in sql["method_workspace"]
        assert "'stale'" in sql["statement_occurrence"]
        assert "'stale'" in sql["method_fragment"]
        assert all(
            f"'{role}'" in sql["bridge_evidence"]
            for role in ("supports", "counters", "bounds")
        )
        assert "'contradicts'" not in sql["bridge_evidence"]
        assert "'qualifies'" not in sql["bridge_evidence"]
        release_columns = {
            row[1] for row in store.conn.execute("PRAGMA table_info(method_release)")
        }
        assert release_columns >= {
            "input_snapshot_hash",
            "compiler_receipt_json",
            "compiler_receipt_hash",
        }
        assert [
            row[1]
            for row in store.conn.execute(
                "PRAGMA table_info(method_compilation_gate)"
            )
        ] == [
            "attempt_id",
            "workspace_id",
            "gate_id",
            "passed",
            "reasons_json",
            "compiler_receipt_hash",
            "compiler_receipt_json",
        ]
    finally:
        store.close()


def test_method_table_inventory_has_no_missing_or_extra_names(
    tmp_path: Path,
) -> None:
    expected = {
        "source_policy",
        "document_policy_snapshot",
        "method_workspace",
        "statement_occurrence",
        "method_extraction_runs",
        "method_extraction_chunks",
        "method_fragment",
        "method_fragment_evidence",
        "method_link",
        "method_gap",
        "bridge_proposal",
        "bridge_evidence",
        "method_review_event",
        "method_counter_evidence_search",
        "method_compilation_attempt",
        "method_compilation_gate",
        "method_release",
    }
    assert METHOD_TABLES == expected
    store = KGStore.open(tmp_path / "inventory.sqlite")
    try:
        actual = {
            row[0]
            for row in store.conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND "
                "(name LIKE 'method_%' OR name IN "
                "('source_policy','document_policy_snapshot',"
                "'statement_occurrence','bridge_proposal','bridge_evidence'))"
            )
        }
        assert {
            "count": len(actual),
            "missing": sorted(expected - actual),
            "extra": sorted(actual - expected),
        } == {"count": 17, "missing": [], "extra": []}
    finally:
        store.close()
