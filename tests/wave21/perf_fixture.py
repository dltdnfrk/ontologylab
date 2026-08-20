"""Deterministic 10,000-row Wave 2.1 performance fixture construction."""

from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path

from ontologylab.connectors.base import RawDocument
from ontologylab.kgstore import KGStore


def deterministic_documents(
    count: int,
    *,
    duplicate_every: int = 20,
) -> list[RawDocument]:
    """Generate exact DOI-collision and same-byte ratios deterministically."""
    docs: list[RawDocument] = []
    for index in range(count):
        doi_index = (
            1 if index == 0 else index - 1
            if index % duplicate_every == 0
            else index
        )
        text_index = (
            index - 1
            if index > 0 and index % duplicate_every == duplicate_every // 2
            else index
        )
        docs.append(
            RawDocument(
                source_kind="synthetic",
                source_uri=f"https://doi.org/10.5555/perf.{doi_index:05d}",
                title=f"Wave 2.1 deterministic paper {index:05d}",
                raw_text=(
                    "PaymentGateway validates through FraudDetector. "
                    + " ".join(
                        f"token{text_index:05d}-{part}" for part in range(40)
                    )
                ),
                doi=f"10.5555/perf.{doi_index:05d}",
                source="synthetic",
                evidence_grade="preprint",
            )
        )
    return docs


def create_populated_legacy_fixture(
    db_path: Path,
    docs: list[RawDocument],
) -> None:
    """Create a pre-DOI store with one physical row per recipe document."""
    store = KGStore.open(db_path)
    store.close()
    with sqlite3.connect(db_path) as conn:
        conn.execute("PRAGMA foreign_keys = OFF")
        conn.execute(
            """
            CREATE TABLE documents_legacy (
                id TEXT PRIMARY KEY,
                source_kind TEXT NOT NULL,
                source_uri TEXT NOT NULL,
                title TEXT,
                fetched_ts REAL NOT NULL,
                content_hash TEXT NOT NULL,
                raw_text_path TEXT NOT NULL,
                source TEXT NOT NULL DEFAULT '',
                evidence_grade TEXT NOT NULL DEFAULT ''
            )
            """
        )
        conn.execute("DROP TABLE documents")
        conn.execute("ALTER TABLE documents_legacy RENAME TO documents")
        rows: list[
            tuple[str, str, str, str | None, float, str, str, str, str]
        ] = []
        for index, doc in enumerate(docs):
            doc_id = f"perf-doc-{index:05d}"
            rel_path = f"documents/{doc_id}/raw.txt"
            raw_path = db_path.parent / rel_path
            raw_path.parent.mkdir(parents=True, exist_ok=True)
            raw_path.write_text(doc.raw_text, encoding="utf-8")
            rows.append(
                (
                    doc_id,
                    doc.source_kind,
                    doc.source_uri,
                    doc.title,
                    0.0,
                    hashlib.sha256(doc.raw_text.encode("utf-8")).hexdigest(),
                    rel_path,
                    doc.source,
                    doc.evidence_grade,
                )
            )
        conn.executemany(
            """
            INSERT INTO documents
            (id, source_kind, source_uri, title, fetched_ts, content_hash,
             raw_text_path, source, evidence_grade)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            rows,
        )
