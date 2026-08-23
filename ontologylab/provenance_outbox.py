"""Transactional provenance outbox and deterministic JSONL projector.

SQLite ``provenance_outbox`` is audit truth. JSONL is a rebuilt, event-id
deduplicated projection. Domain artifact/Observation rows and the outbox
event share the caller-owned SAVEPOINT. ``mirrored_ts`` is written only
after the durable mirror exists. This module never commits or rolls back.
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from ontologylab.file_lifecycle import store_root_from_conn


OBSERVATION_STEP = "observation.recorded"
PROVENANCE_JSONL_NAME = "provenance.jsonl"
Failpoint = Callable[[str], None]


class OutboxError(Exception):
    """Typed outbox or projector failure."""


class MalformedOutboxPayload(OutboxError):
    """Payload is not canonical JSON with an event_id; fail closed."""


@dataclass(frozen=True, slots=True)
class OutboxEvent:
    event_id: str
    step: str
    payload_json: str
    created_ts: float
    mirrored_ts: float | None
    seq: int | None = None

    @property
    def projected(self) -> bool:
        return self.mirrored_ts is not None


@dataclass(frozen=True, slots=True)
class ProjectResult:
    written: int
    marked: int
    path: Path


def canonical_json(value: object) -> str:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    )


def event_id_for(*, step: str, observation_id: str) -> str:
    digest = hashlib.sha256(
        canonical_json(
            {"observation_id": observation_id, "step": step}
        ).encode("utf-8")
    ).hexdigest()
    return f"sha256:{digest}"


def provenance_jsonl_path(store_root: Path) -> Path:
    return Path(store_root) / PROVENANCE_JSONL_NAME


def _ensure_caller_transaction(conn: sqlite3.Connection) -> None:
    if not conn.in_transaction:
        conn.execute("BEGIN IMMEDIATE")


def _row_to_event(row: sqlite3.Row) -> OutboxEvent:
    mirrored = row["mirrored_ts"]
    return OutboxEvent(
        event_id=str(row["event_id"]),
        step=str(row["step"]),
        payload_json=str(row["payload_json"]),
        created_ts=float(row["created_ts"]),
        mirrored_ts=None if mirrored is None else float(mirrored),
        seq=int(row["seq"]) if row["seq"] is not None else None,
    )


def load_outbox_events(conn: sqlite3.Connection) -> tuple[OutboxEvent, ...]:
    rows = conn.execute(
        "SELECT seq, event_id, step, payload_json, created_ts, mirrored_ts "
        "FROM provenance_outbox ORDER BY seq ASC, event_id ASC"
    ).fetchall()
    return tuple(_row_to_event(row) for row in rows)


def insert_observation_event(
    conn: sqlite3.Connection,
    *,
    observation_id: str,
    work_id: str | None,
    representation_id: str | None,
    identifier_id: str | None,
    idempotency_key: str,
    step: str = OBSERVATION_STEP,
) -> OutboxEvent:
    """Insert one deterministic Observation event. Idempotent on event_id."""
    _ensure_caller_transaction(conn)
    event_id = event_id_for(step=step, observation_id=observation_id)
    payload = canonical_json(
        {
            "event_id": event_id,
            "identifier_id": identifier_id,
            "idempotency_key": idempotency_key,
            "observation_id": observation_id,
            "representation_id": representation_id,
            "step": step,
            "work_id": work_id,
        }
    )
    conn.execute(
        "INSERT OR IGNORE INTO provenance_outbox "
        "(event_id, step, payload_json, created_ts, mirrored_ts) "
        "VALUES (?, ?, ?, ?, NULL)",
        (event_id, step, payload, time.time()),
    )
    row = conn.execute(
        "SELECT seq, event_id, step, payload_json, created_ts, mirrored_ts "
        "FROM provenance_outbox WHERE event_id = ?",
        (event_id,),
    ).fetchone()
    if row is None:
        raise OutboxError(f"failed to persist outbox event {event_id}")
    return _row_to_event(row)


def _parse_payload(event: OutboxEvent) -> dict[str, object]:
    try:
        payload = json.loads(event.payload_json)
    except json.JSONDecodeError as exc:
        raise MalformedOutboxPayload(
            f"malformed payload for {event.event_id}"
        ) from exc
    if not isinstance(payload, dict) or "event_id" not in payload:
        raise MalformedOutboxPayload(
            f"malformed payload for {event.event_id}"
        )
    return cast(dict[str, object], payload)


def _dedupe_by_event_id(
    events: tuple[OutboxEvent, ...],
) -> tuple[OutboxEvent, ...]:
    seen: set[str] = set()
    unique: list[OutboxEvent] = []
    for event in events:
        if event.event_id in seen:
            continue
        seen.add(event.event_id)
        unique.append(event)
    return tuple(unique)


def _fsync_path(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _atomic_rebuild_jsonl(path: Path, lines: tuple[str, ...]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    with tmp.open("w", encoding="utf-8") as handle:
        for line in lines:
            handle.write(line)
            handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp, path)
    _fsync_path(path.parent)


def _mark_projected(conn: sqlite3.Connection, event_ids: tuple[str, ...]) -> int:
    if not event_ids:
        return 0
    now = time.time()
    marked = 0
    for event_id in event_ids:
        cursor = conn.execute(
            "UPDATE provenance_outbox SET mirrored_ts = ? "
            "WHERE event_id = ? AND mirrored_ts IS NULL",
            (now, event_id),
        )
        marked += cursor.rowcount
    return marked


def project_outbox(
    conn: sqlite3.Connection,
    store_root: Path | None = None,
    *,
    failpoint: Failpoint | None = None,
) -> ProjectResult:
    """Rebuild canonical JSONL, then mark projected. Never commit."""
    _ensure_caller_transaction(conn)
    root = store_root if store_root is not None else store_root_from_conn(conn)
    path = provenance_jsonl_path(root)
    events = _dedupe_by_event_id(load_outbox_events(conn))
    if not events and not path.exists():
        return ProjectResult(written=0, marked=0, path=path)
    payloads = tuple(_parse_payload(event) for event in events)
    lines = tuple(canonical_json(payload) for payload in payloads)
    if failpoint is not None:
        failpoint("before_durable_mirror")
    _atomic_rebuild_jsonl(path, lines)
    if failpoint is not None:
        failpoint("after_durable_mirror")
    marked = _mark_projected(conn, tuple(event.event_id for event in events))
    return ProjectResult(written=len(lines), marked=marked, path=path)


__all__ = [
    "MalformedOutboxPayload",
    "OBSERVATION_STEP",
    "OutboxError",
    "OutboxEvent",
    "PROVENANCE_JSONL_NAME",
    "ProjectResult",
    "canonical_json",
    "event_id_for",
    "insert_observation_event",
    "load_outbox_events",
    "project_outbox",
    "provenance_jsonl_path",
]
