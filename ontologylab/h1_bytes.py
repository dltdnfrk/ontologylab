"""Ready Representation bytes for H1 classification."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from ontologylab.file_lifecycle import (
    FileIntegrityError,
    FileNotReady,
    PathEscapeError,
    content_hash_for,
    read_ready_text,
    store_root_from_conn,
)
from ontologylab.h1_types import H1QuarantineReason


@dataclass(frozen=True, slots=True)
class H1DocumentBytes:
    representation_id: str
    text: str
    content_hash: str


def run_for_representation(
    conn: sqlite3.Connection, representation_id: str,
) -> sqlite3.Row | None:
    """I7: run identity is Representation id, never content-hash lookup."""
    return conn.execute(
        "SELECT * FROM extraction_runs WHERE document_id = ? ORDER BY id",
        (representation_id,),
    ).fetchone()


def load_document(
    conn: sqlite3.Connection, representation_id: str,
) -> H1DocumentBytes | H1QuarantineReason:
    row = conn.execute(
        "SELECT content_hash FROM documents WHERE id = ?",
        (representation_id,),
    ).fetchone()
    if row is None:
        return H1QuarantineReason.UNREADABLE_SOURCE
    try:
        text = read_ready_text(
            conn, store_root_from_conn(conn), representation_id,
        )
    except FileNotReady:
        return H1QuarantineReason.UNREADABLE_SOURCE
    except PathEscapeError:
        return H1QuarantineReason.UNREADABLE_SOURCE
    except FileIntegrityError:
        return H1QuarantineReason.HASH_MISMATCH
    digest = content_hash_for(text.encode("utf-8"))
    stored = str(row["content_hash"])
    if digest != stored:
        return H1QuarantineReason.HASH_MISMATCH
    return H1DocumentBytes(representation_id, text, stored)
