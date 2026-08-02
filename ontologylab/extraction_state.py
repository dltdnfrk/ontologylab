"""SQLite-backed extraction run and chunk lifecycle state."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import time
import uuid
from dataclasses import dataclass
from typing import Any, Iterable


_SCHEMA = """
CREATE TABLE IF NOT EXISTS extraction_runs (
    id                    TEXT PRIMARY KEY,
    document_id           TEXT NOT NULL REFERENCES documents(id),
    document_content_hash TEXT NOT NULL,
    schema_version_id     INTEGER NOT NULL REFERENCES schema_version(id),
    extractor_engine      TEXT NOT NULL,
    extractor_model       TEXT NOT NULL,
    prompt_version        TEXT NOT NULL,
    decode_params         TEXT NOT NULL,
    chunk_plan_hash       TEXT NOT NULL,
    status                TEXT NOT NULL CHECK (status IN
                          ('pending','running','complete','failed',
                           'interrupted','cancelled')),
    created_ts            REAL NOT NULL,
    updated_ts            REAL NOT NULL,
    finished_ts           REAL,
    UNIQUE (document_content_hash, schema_version_id, extractor_engine,
            extractor_model, prompt_version, decode_params, chunk_plan_hash)
);
CREATE INDEX IF NOT EXISTS idx_extraction_runs_document
    ON extraction_runs(document_id, status);

CREATE TABLE IF NOT EXISTS extraction_chunks (
    run_id          TEXT NOT NULL REFERENCES extraction_runs(id),
    chunk_index     INTEGER NOT NULL,
    char_offset     INTEGER NOT NULL,
    content_hash    TEXT NOT NULL,
    status          TEXT NOT NULL CHECK (status IN
                    ('pending','running','succeeded','failed',
                     'interrupted','cancelled')),
    attempts        INTEGER NOT NULL DEFAULT 0,
    stats_json      TEXT,
    error_kind      TEXT,
    started_ts      REAL,
    finished_ts     REAL,
    PRIMARY KEY (run_id, chunk_index)
);
CREATE INDEX IF NOT EXISTS idx_extraction_chunks_status
    ON extraction_chunks(run_id, status, chunk_index);
"""

RETRYABLE_CHUNK_STATUSES = ("pending", "failed", "interrupted")


def ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(_SCHEMA)


def canonical_decode_params(params: dict[str, Any] | None) -> str:
    return json.dumps(params, sort_keys=True, separators=(",", ":"))


def interrupt_running(conn: sqlite3.Connection) -> int:
    """Turn state left by a dead app into explicit, resumable state."""
    ensure_schema(conn)
    now = time.time()
    with conn:
        chunks = conn.execute(
            "UPDATE extraction_chunks SET status = 'interrupted', "
            "finished_ts = ? WHERE status = 'running'", (now,),
        ).rowcount
        conn.execute(
            "UPDATE extraction_runs SET status = 'interrupted', updated_ts = ? "
            "WHERE status = 'running'", (now,),
        )
    return chunks


def _plan_hash(chunks: Iterable[Any]) -> str:
    digest = hashlib.sha256()
    for chunk in chunks:
        digest.update(str(chunk.index).encode("ascii"))
        digest.update(b":")
        digest.update(str(chunk.char_offset).encode("ascii"))
        digest.update(b":")
        digest.update(hashlib.sha256(chunk.text.encode("utf-8")).digest())
    return "sha256:" + digest.hexdigest()


@dataclass(frozen=True)
class RunPlan:
    run_id: str
    status: str
    retryable: frozenset[int]


class ExtractionState:
    """Lifecycle operations sharing the KG connection and transaction."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn
        ensure_schema(conn)

    def plan(
        self,
        document_id: str,
        chunks: list[Any],
        *,
        schema_version_id: int,
        engine: str,
        model: str | None,
        prompt_version: str,
        decode_params: dict[str, Any] | None,
    ) -> RunPlan:
        document = self.conn.execute(
            "SELECT content_hash FROM documents WHERE id = ?", (document_id,),
        ).fetchone()
        if document is None:
            raise ValueError(f"unknown document {document_id!r}")
        identity = (
            document["content_hash"], schema_version_id, engine, model or "",
            prompt_version, canonical_decode_params(decode_params),
            _plan_hash(chunks),
        )
        row = self.conn.execute(
            "SELECT id, status FROM extraction_runs WHERE "
            "document_content_hash = ? AND schema_version_id = ? AND "
            "extractor_engine = ? AND extractor_model = ? AND "
            "prompt_version = ? AND decode_params = ? AND chunk_plan_hash = ?",
            identity,
        ).fetchone()
        now = time.time()
        if row is None:
            run_id = uuid.uuid4().hex
            with self.conn:
                self.conn.execute(
                    "INSERT INTO extraction_runs (id, document_id, "
                    "document_content_hash, schema_version_id, extractor_engine, "
                    "extractor_model, prompt_version, decode_params, "
                    "chunk_plan_hash, status, created_ts, updated_ts) "
                    "VALUES (?,?,?,?,?,?,?,?,?,'pending',?,?)",
                    (run_id, document_id, *identity, now, now),
                )
                self.conn.executemany(
                    "INSERT INTO extraction_chunks (run_id, chunk_index, "
                    "char_offset, content_hash, status) VALUES (?,?,?,?,'pending')",
                    [
                        (run_id, chunk.index, chunk.char_offset,
                         "sha256:" + hashlib.sha256(
                             chunk.text.encode("utf-8")
                         ).hexdigest())
                        for chunk in chunks
                    ],
                )
            status = "pending"
        else:
            run_id, status = row["id"], row["status"]

        if status in {"pending", "failed", "interrupted"}:
            with self.conn:
                self.conn.execute(
                    "UPDATE extraction_runs SET status = 'running', "
                    "updated_ts = ?, finished_ts = NULL WHERE id = ?",
                    (now, run_id),
                )
            status = "running"
        retryable = frozenset(
            row["chunk_index"] for row in self.conn.execute(
                "SELECT chunk_index FROM extraction_chunks WHERE run_id = ? "
                "AND status IN ('pending','failed','interrupted')",
                (run_id,),
            )
        )
        return RunPlan(run_id, status, retryable)

    def claim(self, run_id: str, chunk_index: int) -> bool:
        now = time.time()
        with self.conn:
            changed = self.conn.execute(
                "UPDATE extraction_chunks SET status = 'running', "
                "attempts = attempts + 1, started_ts = ?, finished_ts = NULL, "
                "error_kind = NULL WHERE run_id = ? AND chunk_index = ? "
                "AND status IN ('pending','failed','interrupted')",
                (now, run_id, chunk_index),
            ).rowcount
        return changed == 1

    def failed(self, run_id: str, chunk_index: int, error_kind: str) -> None:
        self.conn.rollback()
        now = time.time()
        with self.conn:
            self.conn.execute(
                "UPDATE extraction_chunks SET status = 'failed', error_kind = ?, "
                "finished_ts = ? WHERE run_id = ? AND chunk_index = ?",
                (error_kind, now, run_id, chunk_index),
            )
            self.conn.execute(
                "UPDATE extraction_runs SET status = 'failed', updated_ts = ?, "
                "finished_ts = ? WHERE id = ?", (now, now, run_id),
            )

    def succeeded(
        self, run_id: str, chunk_index: int, stats: dict[str, Any]
    ) -> None:
        # Commits proposal rows and their success marker atomically.
        self.conn.execute(
            "UPDATE extraction_chunks SET status = 'succeeded', stats_json = ?, "
            "finished_ts = ? WHERE run_id = ? AND chunk_index = ?",
            (json.dumps(stats, sort_keys=True), time.time(), run_id, chunk_index),
        )
        self.conn.commit()

    def finish(self, run_id: str, *, cancelled: bool = False) -> str:
        now = time.time()
        with self.conn:
            if cancelled:
                self.conn.execute(
                    "UPDATE extraction_chunks SET status = 'cancelled', "
                    "finished_ts = ? WHERE run_id = ? AND status != 'succeeded'",
                    (now, run_id),
                )
                status = "cancelled"
            else:
                counts = {
                    row["status"]: row["n"] for row in self.conn.execute(
                        "SELECT status, COUNT(*) AS n FROM extraction_chunks "
                        "WHERE run_id = ? GROUP BY status", (run_id,),
                    )
                }
                if counts.get("failed"):
                    status = "failed"
                elif any(counts.get(key) for key in ("pending", "running", "interrupted")):
                    self.conn.execute(
                        "UPDATE extraction_chunks SET status = 'interrupted', "
                        "finished_ts = ? WHERE run_id = ? AND status = 'running'",
                        (now, run_id),
                    )
                    status = "interrupted"
                else:
                    status = "complete"
            self.conn.execute(
                "UPDATE extraction_runs SET status = ?, updated_ts = ?, "
                "finished_ts = ? WHERE id = ?", (status, now, now, run_id),
            )
        return status
