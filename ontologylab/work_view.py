"""On-read Work serializer (Wave 2.1 Step 3, 3C).

Pure projection: the preferred Representation is COMPUTED per call from the
fixed preferred-representation-v1 policy and never stored. Identifiers and
Observations stay on their original Work forever (D09 forbids FK rewrites);
current/as-of canonicalization over redirect decisions is the separate
``canonical_work`` projection in ``ontologylab.work_redirects``, not this
serializer.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from ontologylab.file_lifecycle import ready_byte_length
from ontologylab.preferred import preferred_representation
from ontologylab.selection_types import RepresentationCandidate


class WorkNotFound(Exception):
    def __init__(self, work_id: str) -> None:
        self.work_id = work_id
        super().__init__(f"work {work_id!r} not found")


def work_candidates(
    conn: sqlite3.Connection, work_id: str,
) -> tuple[RepresentationCandidate, ...]:
    """Every Representation on a Work, including staged state."""
    work = conn.execute(
        "SELECT id FROM works WHERE id = ?", (work_id,),
    ).fetchone()
    if work is None:
        raise WorkNotFound(work_id)
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
    document_columns = {
        row[1] for row in conn.execute("PRAGMA table_info(documents)")
    }
    select = ["id", "content_hash", "raw_text_path"]
    has_state = "representation_state" in document_columns
    if has_state:
        select.append("representation_state")
    db_root = Path(
        conn.execute("PRAGMA database_list").fetchone()[2]
    ).parent
    candidates: list[RepresentationCandidate] = []
    for row in conn.execute(
        f"SELECT {', '.join(select)} FROM documents "
        "WHERE work_id = ? ORDER BY id",
        (work_id,),
    ):
        mapped = dict(zip(select, row))
        doc_id = str(mapped["id"])
        state = str(mapped["representation_state"]) if has_state else "ready"
        byte_length = ready_byte_length(
            db_root, str(mapped["raw_text_path"]), state
        )
        meta = observations_by_rep.get(doc_id)
        candidates.append(
            RepresentationCandidate(
                representation_id=doc_id,
                content_hash=str(mapped["content_hash"]),
                byte_length=byte_length,
                stage=str(meta[1]) if meta else "unknown",
                kind=str(meta[2]) if meta else "metadata_only",
                source=str(meta[3]) if meta else "",
                evidence_grade=str(meta[4]) if meta else "",
                state=state,
            )
        )
    return tuple(candidates)


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
    candidates = work_candidates(conn, work_id)
    representations = [
        {
            "doc_id": candidate.representation_id,
            "content_hash": candidate.content_hash,
            "byte_length": candidate.byte_length,
            "stage": candidate.stage,
            "kind": candidate.kind,
            "source": candidate.source,
            "evidence_grade": candidate.evidence_grade,
        }
        for candidate in candidates
    ]
    preferred_id = None
    ready = [
        rep
        for rep, candidate in zip(representations, candidates)
        if candidate.state == "ready"
    ]
    if ready:
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
                for rep in ready
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
