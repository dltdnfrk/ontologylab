"""Export complete persisted graph evidence, or rescore it without trial stores."""
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import sys

from ontologylab.polarity_eval import score_polarity

TABLES = (
    "nodes", "node_aliases", "edges", "citations", "citation_receipts",
    "documents", "document_observations", "schema_version", "entity_type",
    "relation_type", "extraction_runs", "extraction_chunks",
    "extraction_run_receipts", "extraction_chunk_receipts",
)

if sys.argv[1] == "export":
    runs = []
    for number, directory in enumerate(map(Path, sys.argv[2:]), 1):
        database = directory / "kg.sqlite"
        wal = directory / "kg.sqlite-wal"
        assert not wal.exists() or wal.stat().st_size == 0
        conn = sqlite3.connect(database.as_uri() + "?mode=ro&immutable=1", uri=True)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("PRAGMA query_only=ON")
            tables = {}
            schemas = {}
            for table in TABLES:
                schemas[table] = conn.execute(
                    "SELECT sql FROM sqlite_master WHERE name=?", (table,)
                ).fetchone()[0]
                tables[table] = [
                    dict(row) for row in conn.execute(f'SELECT * FROM "{table}" ORDER BY rowid')
                ]
            assert all(row["embedding"] is None for row in tables["nodes"])
            runs.append({
                "run": number, "data_dir": str(directory),
                "database_sha256": hashlib.sha256(database.read_bytes()).hexdigest(),
                "schemas": schemas, "tables": tables,
                "counts": {table: len(rows) for table, rows in tables.items()},
            })
        finally:
            conn.close()
    payload = {
        "format_version": 1, "trial": 4, "runs": runs,
        "scope": "All persisted rows, including rejected and invalidated rows.",
        "spans": "Original source_span fields plus complete citations and citation_receipts.",
        "polarities": "Original edges.qualifiers_json; no normalization or filtering.",
        "extraction_passes": (
            "citations.extraction_passes is a JSON set of known producing passes "
            "(first, completion); NULL or an absent column means unrecorded. "
            "Duplicate observations within a chunk share the retained citation; "
            "union citation sets by (kind, item_id) for statement attribution."
        ),
    }
elif sys.argv[1] == "rescore":
    exported = json.loads(Path(sys.argv[2]).read_text())
    results = []
    for run in exported["runs"]:
        conn = sqlite3.connect(":memory:")
        try:
            for table in ("nodes", "node_aliases", "edges"):
                conn.execute(run["schemas"][table])
                rows = run["tables"][table]
                if rows:
                    columns = list(rows[0])
                    conn.executemany(
                        f'INSERT INTO "{table}" ({",".join(columns)}) '
                        f'VALUES ({",".join("?" for _ in columns)})',
                        [[row[column] for column in columns] for row in rows],
                    )
            results.append({
                "run": run["run"],
                "primary": score_polarity(conn, sys.argv[3], qualified=True),
                "legacy": score_polarity(conn, sys.argv[4]),
            })
        finally:
            conn.close()
    payload = {"runs": results, "input": sys.argv[2], "temporary_stores_used": False}
else:
    raise SystemExit("Expected export ROOT... or rescore EXPORT QUALIFIED_GOLD LEGACY_GOLD")

text = json.dumps(payload, sort_keys=True)
key = os.environ.get("GOOGLE_API_KEY", "")
assert not key or key not in text, "Secret found; refusing to export"
print(text)
