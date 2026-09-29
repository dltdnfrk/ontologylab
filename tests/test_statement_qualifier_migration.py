"""An old SQLite store gains qualified identity without changing old rows."""

import json
import sqlite3

from ontologylab.kgstore import KGStore
from tests.conftest import insert
from tests.factories import make_entity, make_relation
from tests.test_statement_qualifier_validation import qualified_store


def test_legacy_rows_and_ids_survive_additive_migration(qualified_store, doc):
    a, b = make_entity("Agent", "ActiveIngredient"), make_entity("Pest", "Pest")
    old = make_relation(a, b, "controls")
    scoped = make_relation(a, b, "controls", qualifiers={"study_context": " In Vitro "})
    insert(qualified_store, doc, [a, b], [old, scoped])
    path = qualified_store.db_path
    # Simulate the old schema on a disposable copy, preserving every row.
    copy = path.parent / "pre-qualified.sqlite"
    with sqlite3.connect(copy) as conn:
        qualified_store.conn.backup(conn)
        conn.execute("DROP INDEX idx_edges_dedup")
        conn.execute("ALTER TABLE edges DROP COLUMN qualifiers_key")
        # Old stores could not contain these two same-polarity rows; use a
        # different polarity on the second, as the old writer would.
        conn.execute("UPDATE edges SET qualifiers_json=? WHERE id=?",
                     (json.dumps({"polarity": "supports", "study_context": " In Vitro "}), scoped.id))
        conn.execute(
            "CREATE UNIQUE INDEX idx_edges_dedup ON edges "
            "(schema_version_id, relation_type, src_node_id, dst_node_id, "
            "COALESCE(json_extract(qualifiers_json, '$.polarity'), '')) "
            "WHERE status IN ('proposed','verified') AND invalidated_ts IS NULL"
        )
        columns = [r[1] for r in conn.execute("PRAGMA table_info(edges)")]
        before = conn.execute(f"SELECT {','.join(columns)} FROM edges ORDER BY id").fetchall()
    migrated = KGStore.open(copy)
    try:
        after = migrated.conn.execute(f"SELECT {','.join(columns)} FROM edges ORDER BY id").fetchall()
        assert [tuple(r) for r in after] == before
        repeat = make_relation(a, b, "controls")
        stats = insert(migrated, doc, [a, b], [repeat])
        assert stats["edges_merged"] == 1
        assert len(migrated.citations("edge", old.id)) == 2
        assert migrated.conn.execute(
            "SELECT qualifiers_key FROM edges WHERE id=?", (scoped.id,)
        ).fetchone()[0] == '{"study_context":"in vitro"}'
    finally:
        migrated.close()
