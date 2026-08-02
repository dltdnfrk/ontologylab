"""SQLite-backed extraction run and chunk lifecycle state."""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import sqlite3
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, BinaryIO, Iterable


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
    owner_token           TEXT,
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
    owner_token     TEXT,
    PRIMARY KEY (run_id, chunk_index)
);
CREATE INDEX IF NOT EXISTS idx_extraction_chunks_status
    ON extraction_chunks(run_id, status, chunk_index);
"""

RETRYABLE_CHUNK_STATUSES = ("pending", "failed", "interrupted")


class _StoreOwnerLock:
    """Process-lifetime proof for the durable owner token in SQLite.

    The token remains queryable in the run/chunk rows. Its adjacent lock file
    binds that identity to an OS-managed exclusive lock, which is released by
    the kernel if the process exits. Merely opening the store in another
    process therefore cannot be mistaken for restart recovery.
    """

    def __init__(self, file: BinaryIO, path: Path) -> None:
        self._file = file
        self._path = path

    @classmethod
    def acquire(
        cls, conn: sqlite3.Connection, owner_token: str,
    ) -> _StoreOwnerLock | None:
        database = next(
            row["file"] for row in conn.execute("PRAGMA database_list")
            if row["name"] == "main"
        )
        if not database:
            return None
        database_path = Path(database).resolve()
        lock_dir = database_path.with_name(
            database_path.name + ".extraction-owners"
        )
        lock_dir.mkdir(parents=True, exist_ok=True)
        lock_name = hashlib.sha256(owner_token.encode("utf-8")).hexdigest()
        lock_path = lock_dir / f"{lock_name}.lock"
        file = lock_path.open("a+b")
        try:
            fcntl.flock(file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            file.close()
            return None
        file.seek(0)
        file.truncate()
        file.write(f"{os.getpid()} {owner_token}\n".encode("ascii"))
        file.flush()
        os.fsync(file.fileno())
        return cls(file, lock_path)

    def close(self) -> None:
        if self._file.closed:
            return
        fcntl.flock(self._file.fileno(), fcntl.LOCK_UN)
        self._file.close()
        try:
            self._path.unlink()
        except FileNotFoundError:
            pass
        try:
            self._path.parent.rmdir()
        except OSError:
            pass


def ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(_SCHEMA)
    # Existing working stores predate ownership. SQLite has no
    # ``ADD COLUMN IF NOT EXISTS``, so inspect before applying the additive,
    # backwards-compatible migration.
    migrations = (
        ("extraction_runs", "owner_token"),
        ("extraction_chunks", "owner_token"),
    )
    for table, column in migrations:
        columns = {
            row["name"] for row in conn.execute(f"PRAGMA table_info({table})")
        }
        if column not in columns:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} TEXT")
    conn.commit()


def canonical_decode_params(params: dict[str, Any] | None) -> str:
    return json.dumps(params, sort_keys=True, separators=(",", ":"))


def effective_extractor_model(engine: Any, requested: str | None) -> str | None:
    """Return the model the already-resolved engine will actually use."""
    return requested or getattr(engine, "_model", None)


def interrupt_running(conn: sqlite3.Connection) -> int:
    """Recover only running rows whose durable owner lock is unheld."""
    ensure_schema(conn)
    owner_tokens = [
        row["owner_token"] for row in conn.execute(
            "SELECT DISTINCT owner_token FROM extraction_runs "
            "WHERE status = 'running'"
        )
    ]
    recovered = 0
    for owner_token in owner_tokens:
        # NULL is legacy pre-ownership state and has no possible live owner.
        owner_lock = (
            _StoreOwnerLock.acquire(conn, owner_token)
            if owner_token is not None else None
        )
        if owner_token is not None and owner_lock is None:
            continue
        try:
            now = time.time()
            owner_predicate = (
                "owner_token IS NULL"
                if owner_token is None else "owner_token = ?"
            )
            owner_args = () if owner_token is None else (owner_token,)
            with conn:
                recovered += conn.execute(
                    "UPDATE extraction_chunks SET status = 'interrupted', "
                    "finished_ts = ?, owner_token = NULL WHERE status = 'running' "
                    f"AND {owner_predicate}",
                    (now, *owner_args),
                ).rowcount
                conn.execute(
                    "UPDATE extraction_runs SET status = 'interrupted', "
                    "updated_ts = ?, owner_token = NULL WHERE status = 'running' "
                    f"AND {owner_predicate}",
                    (now, *owner_args),
                )
        finally:
            if owner_lock is not None:
                owner_lock.close()
    return recovered


def recover_running_once(conn: sqlite3.Connection) -> int:
    """Recover claims iff the OS proves their process owner is gone.

    Recovery is safe to call at every CLI/app startup. Each live extraction
    holds the lock named by its durable token, so another process skips its
    rows. Process exit releases the lock in the kernel, allowing
    the next startup to convert abandoned running state to interrupted.
    """
    return interrupt_running(conn)


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
        self.owner_token = uuid.uuid4().hex
        self._owner_lock: _StoreOwnerLock | None = None
        ensure_schema(conn)
        self._owner_lock = _StoreOwnerLock.acquire(conn, self.owner_token)

    def close(self) -> None:
        if self._owner_lock is not None:
            self._owner_lock.close()
            self._owner_lock = None

    def __del__(self) -> None:
        self.close()

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

        owns_run = False
        if (
            self._owner_lock is not None
            and status in {"pending", "failed", "interrupted"}
        ):
            with self.conn:
                owns_run = self.conn.execute(
                    "UPDATE extraction_runs SET status = 'running', "
                    "updated_ts = ?, finished_ts = NULL, owner_token = ? "
                    "WHERE id = ? AND status IN ('pending','failed','interrupted')",
                    (now, self.owner_token, run_id),
                ).rowcount == 1
            status = "running"
        elif self._owner_lock is not None:
            owns_run = self.conn.execute(
                "SELECT owner_token = ? FROM extraction_runs WHERE id = ?",
                (self.owner_token, run_id),
            ).fetchone()[0] == 1
        retryable = frozenset(
            row["chunk_index"] for row in self.conn.execute(
                "SELECT chunk_index FROM extraction_chunks WHERE run_id = ? "
                "AND status IN ('pending','failed','interrupted')",
                (run_id,),
            )
        ) if owns_run else frozenset()
        return RunPlan(run_id, status, retryable)

    def claim(self, run_id: str, chunk_index: int) -> bool:
        if self._owner_lock is None:
            return False
        now = time.time()
        with self.conn:
            changed = self.conn.execute(
                "UPDATE extraction_chunks SET status = 'running', "
                "attempts = attempts + 1, started_ts = ?, finished_ts = NULL, "
                "error_kind = NULL, owner_token = ? WHERE run_id = ? "
                "AND chunk_index = ? AND status IN "
                "('pending','failed','interrupted') AND EXISTS (SELECT 1 FROM "
                "extraction_runs WHERE id = ? AND owner_token = ?)",
                (now, self.owner_token, run_id, chunk_index, run_id,
                 self.owner_token),
            ).rowcount
        return changed == 1

    def failed(self, run_id: str, chunk_index: int, error_kind: str) -> None:
        self.conn.rollback()
        now = time.time()
        with self.conn:
            changed = self.conn.execute(
                "UPDATE extraction_chunks SET status = 'failed', error_kind = ?, "
                "finished_ts = ?, owner_token = NULL WHERE run_id = ? AND "
                "chunk_index = ? AND status = 'running' AND owner_token = ?",
                (error_kind, now, run_id, chunk_index, self.owner_token),
            ).rowcount
            if changed:
                self.conn.execute(
                    "UPDATE extraction_runs SET status = 'failed', updated_ts = ?, "
                    "finished_ts = ? WHERE id = ? AND owner_token = ?",
                    (now, now, run_id, self.owner_token),
                )

    def succeeded(
        self, run_id: str, chunk_index: int, stats: dict[str, Any]
    ) -> None:
        # Commits proposal rows and their success marker atomically.
        changed = self.conn.execute(
            "UPDATE extraction_chunks SET status = 'succeeded', stats_json = ?, "
            "finished_ts = ?, owner_token = NULL WHERE run_id = ? AND "
            "chunk_index = ? AND status = 'running' AND owner_token = ?",
            (json.dumps(stats, sort_keys=True), time.time(), run_id, chunk_index,
             self.owner_token),
        ).rowcount
        if changed != 1:
            self.conn.rollback()
            raise RuntimeError("extraction chunk ownership was lost before success")
        self.conn.commit()

    def finish(self, run_id: str, *, cancelled: bool = False) -> str:
        now = time.time()
        with self.conn:
            current = self.conn.execute(
                "SELECT status, owner_token FROM extraction_runs WHERE id = ?",
                (run_id,),
            ).fetchone()
            if current is None:
                raise ValueError(f"unknown extraction run {run_id!r}")
            if current["owner_token"] != self.owner_token:
                return current["status"]
            if cancelled:
                self.conn.execute(
                    "UPDATE extraction_chunks SET status = 'cancelled', "
                    "finished_ts = ?, owner_token = NULL WHERE run_id = ? "
                    "AND status != 'succeeded'",
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
                        "finished_ts = ?, owner_token = NULL WHERE run_id = ? "
                        "AND status = 'running' AND owner_token = ?",
                        (now, run_id, self.owner_token),
                    )
                    status = "interrupted"
                else:
                    status = "complete"
            self.conn.execute(
                "UPDATE extraction_runs SET status = ?, updated_ts = ?, "
                "finished_ts = ?, owner_token = NULL WHERE id = ? "
                "AND owner_token = ?",
                (status, now, now, run_id, self.owner_token),
            )
        return status
