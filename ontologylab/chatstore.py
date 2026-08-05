"""The conversation, kept — because a sentence is now part of the record.

Chat became the primary surface, and that quietly moved something into a
place with no memory. A research run has provenance: which query was
formulated, which sources answered, which document produced which
proposal. But the run started from a sentence somebody typed, and that
sentence lived in a DOM node until the tab was refreshed. "Why is this
document in my graph" could be answered down to the character offset and
not up to the question that caused it.

So turns are stored, and a turn that started a run carries its `job_id`.
That closes the chain in the direction people actually ask about it.

**Not in `kg.sqlite`.** A pack is built by copying named tables out of the
knowledge graph and is meant to be handed to someone else; conversation is
workspace state. Physical separation is what makes "a pack cannot contain
your chat history" a property of the layout rather than a promise about
remembering not to write one more copy line.

Nothing here is knowledge. Reading this file back does not restore any
graph state — it restores what a person saw, so they can pick up where
they left off.
"""

from __future__ import annotations

import json
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Any, Optional

# How many turns a conversation keeps. Old turns are dropped rather than
# retained forever: this is a transcript for picking up where you left off,
# not an archive, and an unbounded local file that nobody ever looks at is
# a liability rather than a feature.
MAX_TURNS = 200

_SCHEMA = """
CREATE TABLE IF NOT EXISTS turns (
    id           TEXT PRIMARY KEY,
    created_ts   REAL NOT NULL,
    -- What the person typed, verbatim. Never a model rewrite of it: the
    -- point of showing it back is that they can see what was actually sent.
    message      TEXT NOT NULL,
    -- A browser session boundary. Starting a new conversation changes this
    -- value; it never deletes the turns from older conversations.
    session_id   TEXT NOT NULL DEFAULT 'legacy',
    -- How it was read. `action` is a name from `intent.ACTIONS`; `reading`
    -- is the model's one-line restatement, shown back so a misread is
    -- visible.
    action       TEXT NOT NULL DEFAULT 'unknown',
    reading      TEXT NOT NULL DEFAULT '',
    -- The rendered answer and the trace, as the browser received them.
    -- Stored as sent rather than re-derived on read: re-running the action
    -- would produce today's answer under yesterday's question.
    result_json  TEXT NOT NULL DEFAULT '{}',
    steps_json   TEXT NOT NULL DEFAULT '[]',
    -- Set when this turn started a run. The link that closes the chain
    -- from a document back to the question that asked for it.
    job_id       TEXT
);
CREATE INDEX IF NOT EXISTS idx_turns_created ON turns (created_ts);
CREATE INDEX IF NOT EXISTS idx_turns_job ON turns (job_id);
"""

_SESSION_INDEX = """
CREATE INDEX IF NOT EXISTS idx_turns_session_created
ON turns (session_id, created_ts);
"""


class ChatStore:
    """Append-only-ish log of chat turns, capped at `MAX_TURNS`."""

    def __init__(self, conn: sqlite3.Connection, db_path: Path) -> None:
        self.conn = conn
        self.db_path = db_path

    @classmethod
    def open(cls, file_path: str | Path) -> "ChatStore":
        db_path = Path(file_path)
        db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(db_path), timeout=30.0)
        for sidecar in (db_path, *db_path.parent.glob(db_path.name + "-*")):
            if sidecar.is_file():
                sidecar.chmod(0o600)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.executescript(_SCHEMA)
        columns = {
            row["name"]
            for row in conn.execute("PRAGMA table_info(turns)").fetchall()
        }
        if "session_id" not in columns:
            conn.execute(
                "ALTER TABLE turns ADD COLUMN session_id TEXT "
                "NOT NULL DEFAULT 'legacy'"
            )
        conn.executescript(_SESSION_INDEX)
        conn.commit()
        return cls(conn, db_path)

    def close(self) -> None:
        self.conn.close()

    def __enter__(self) -> "ChatStore":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # ------------------------------------------------------------------

    def record(
        self,
        *,
        message: str,
        action: str,
        reading: str,
        result: dict[str, Any],
        steps: list[dict[str, Any]],
        session_id: str = "legacy",
        job_id: Optional[str] = None,
        created_ts: Optional[float] = None,
    ) -> str:
        """Store one turn; return its id.

        Called after the action has run, so `result` and `steps` describe
        what actually happened rather than what was about to be attempted.
        A turn that failed is stored too — a conversation that silently
        drops its failures reads as though nothing was ever tried.
        """
        turn_id = uuid.uuid4().hex
        self.conn.execute(
            "INSERT INTO turns (id, created_ts, message, session_id, action, "
            "reading, result_json, steps_json, job_id) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                turn_id,
                float(created_ts if created_ts is not None else time.time()),
                message,
                session_id,
                action,
                reading,
                json.dumps(result, ensure_ascii=False),
                json.dumps(steps, ensure_ascii=False),
                job_id,
            ),
        )
        self._trim()
        self.conn.commit()
        return turn_id

    def _trim(self) -> None:
        """Drop the oldest turns past the cap.

        By `created_ts`, not by rowid: the visible order is what the cap
        should follow, so the turn that disappears is the one furthest up
        the scroll.
        """
        self.conn.execute(
            "DELETE FROM turns WHERE id IN ("
            "  SELECT id FROM turns ORDER BY created_ts DESC LIMIT -1 OFFSET ?"
            ")",
            (MAX_TURNS,),
        )

    def attach_job(self, turn_id: str, job_id: str) -> None:
        """Link a turn to the run it started."""
        self.conn.execute(
            "UPDATE turns SET job_id = ? WHERE id = ?", (job_id, turn_id)
        )
        self.conn.commit()

    def history(
        self, limit: int = MAX_TURNS, session_id: Optional[str] = None
    ) -> list[dict[str, Any]]:
        """Oldest first — the order a conversation is read in."""
        if session_id is None:
            rows = self.conn.execute(
                "SELECT * FROM turns ORDER BY created_ts DESC LIMIT ?", (limit,)
            ).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT * FROM turns WHERE session_id = ? "
                "ORDER BY created_ts DESC LIMIT ?",
                (session_id, limit),
            ).fetchall()
        return [self._row(row) for row in reversed(rows)]

    def turn_for_job(self, job_id: str) -> Optional[dict[str, Any]]:
        """Which question started this run. The provenance direction people
        actually ask in: they find a document, not a job id."""
        row = self.conn.execute(
            "SELECT * FROM turns WHERE job_id = ? ORDER BY created_ts DESC "
            "LIMIT 1",
            (job_id,),
        ).fetchone()
        return None if row is None else self._row(row)

    def clear(self) -> int:
        """Forget the conversation. Returns how many turns were dropped.

        Present because a local-first tool that keeps a transcript owes the
        person a way to end it, and because "delete the file" is not an
        answer anyone should have to be given.
        """
        count = self.conn.execute(
            "SELECT COUNT(*) AS n FROM turns"
        ).fetchone()["n"]
        self.conn.execute("DELETE FROM turns")
        self.conn.commit()
        return int(count)

    @staticmethod
    def _row(row: sqlite3.Row) -> dict[str, Any]:
        def _loads(raw: str, fallback: Any) -> Any:
            try:
                return json.loads(raw)
            except (ValueError, TypeError):
                # A row this file cannot parse is still a turn that
                # happened. Showing the message without its answer beats
                # dropping the conversation at the corrupted row.
                return fallback

        return {
            "id": row["id"],
            "created_ts": row["created_ts"],
            "message": row["message"],
            "session_id": row["session_id"],
            "action": row["action"],
            "reading": row["reading"],
            "result": _loads(row["result_json"], {}),
            "steps": _loads(row["steps_json"], []),
            "job_id": row["job_id"],
        }
