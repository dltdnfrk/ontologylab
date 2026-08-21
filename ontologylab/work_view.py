"""On-read Work serializer (Wave 2.1 Step 3, 3C).

Pure projection: the preferred Representation is COMPUTED per call from the
fixed preferred-representation-v1 policy and never stored. Identifiers and
Observations stay on their original Work forever (D09 forbids FK rewrites);
current/as-of canonicalization over redirect decisions is the separate
``canonical_work`` projection in ``ontologylab.work_redirects``, not this
serializer.
"""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path

from ontologylab.preferred import preferred_representation


class WorkNotFound(Exception):
    def __init__(self, work_id: str) -> None:
        self.work_id = work_id
        super().__init__(f"work {work_id!r} not found")


def work_snapshot(conn: sqlite3.Connection, work_id: str) -> dict:
    """One Work's identifiers, observations, representations, and the
    computed preferred Representation id (or None)."""
    work = conn.execute(
        "SELECT id, state, created_ts FROM works WHERE id = ?",
        (work_id,),
    ).fetchone()
    if work is None:
        raise WorkNotFound(work_id)

    identifiers = [
        {
            "id": row[0],
            "work_id": row[1],
            "scheme": row[2],
            "normalized_value": row[3],
            "status": row[4],
        }
        for row in conn.execute(
            "SELECT id, work_id, scheme, normalized_value, status "
            "FROM work_identifiers WHERE work_id = ? ORDER BY created_ts",
            (work_id,),
        )
    ]
    observations = [
        {
            "id": row[0],
            "representation_id": row[1],
            "idempotency_key": row[2],
            "source": row[3],
            "evidence_grade": row[4],
            "stage": row[5],
            "content_kind": row[6],
        }
        for row in conn.execute(
            "SELECT o.id, o.representation_id, o.idempotency_key, o.source, "
            "o.evidence_grade, o.stage, o.content_kind "
            "FROM document_observations o "
            "JOIN identifier_assertions ia ON ia.observation_id = o.id "
            "JOIN work_identifiers wi ON wi.id = ia.identifier_id "
            "WHERE wi.work_id = ? ORDER BY o.created_ts",
            (work_id,),
        )
    ]
    observations_by_rep = {
        row[0]: row for row in conn.execute(
            "SELECT o.representation_id, o.stage, o.content_kind, o.source, "
            "o.evidence_grade "
            "FROM document_observations o "
            "JOIN identifier_assertions ia ON ia.observation_id = o.id "
            "JOIN work_identifiers wi ON wi.id = ia.identifier_id "
            "WHERE wi.work_id = ?",
            (work_id,),
        )
    }

    representations: list[dict] = []
    db_root = Path(
        conn.execute("PRAGMA database_list").fetchone()[2]
    ).parent
    for row in conn.execute(
        "SELECT id, content_hash, raw_text_path FROM documents "
        "WHERE work_id = ? ORDER BY id",
        (work_id,),
    ):
        doc_id, content_hash, raw_text_path = row[0], row[1], row[2]
        raw_path = db_root / raw_text_path
        byte_length = os.path.getsize(raw_path) if raw_path.is_file() else 0
        meta = observations_by_rep.get(doc_id)
        representations.append(
            {
                "doc_id": doc_id,
                "content_hash": content_hash,
                "byte_length": byte_length,
                "stage": meta[1] if meta else "unknown",
                "kind": meta[2] if meta else "metadata_only",
                "source": meta[3] if meta else "",
                "evidence_grade": meta[4] if meta else "",
            }
        )

    preferred_id = None
    if representations:
        preferred = preferred_representation(
            [
                {
                    "doc_id": rep["doc_id"],
                    "stage": rep["stage"],
                    "kind": rep["kind"],
                    "evidence_grade": rep["evidence_grade"],
                    "source": rep["source"],
                    "byte_length": rep["byte_length"],
                    "content_hash": rep["content_hash"],
                }
                for rep in representations
            ]
        )
        preferred_id = preferred["doc_id"]

    return {
        "work": {
            "id": work[0],
            "state": work[1],
            "created_ts": work[2],
        },
        "identifiers": identifiers,
        "observations": observations,
        "representations": representations,
        "preferred_representation_id": preferred_id,
    }
