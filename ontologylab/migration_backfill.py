"""DOI backfill and collision executor on backup-API copies (Wave 2.1 5B).

Consumes the Step 2 read-only planner (``plan_doi_backfill``) and Step 4
``record_collision``. Runs only on a caller-owned 5A snapshot copy:
backfillable rows gain ``documents.doi``; ``collision_owner`` and
``collision_ambiguous`` groups become deterministic pending records with
zero accepted owner; equivalent explicit-DOI groups converge under one
accepted assertion with every Representation id preserved. Writes are
SAVEPOINT-scoped inside the caller-owned transaction; this module never
issues COMMIT.

Gap vs 5A: ``snapshot_db`` copies the SQLite file only. Representation
sidecar files live next to the store at ``documents/{id}/raw.txt``, so
``prepare_backup_copy`` wraps the snapshot and copies that tree.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from pathlib import Path

from ontologylab.authority_repo import attach_identifier, create_work
from ontologylab.connectors.base import normalize_doi
from ontologylab.doi_backfill import plan_doi_backfill
from ontologylab.identity_decisions import CollisionReceipt, record_collision
from ontologylab.migration import (
    begin_phase,
    complete_phase,
    compute_source_fingerprint,
    phase_is_complete,
    snapshot_db,
)

_BACKFILL_PHASE = "backfill"
_SP_EXECUTE = "migration_backfill"
_ACTOR = "migration-backfill"
_REASON = "wave-2.1-step-5-doi-backfill"
_COLLISION_CLASSES = frozenset({"collision_owner", "collision_ambiguous"})


@dataclass(frozen=True, slots=True)
class IntegrityClassification:
    raw_text_identical: bool
    citation_spans_identical: bool


@dataclass(frozen=True, slots=True)
class EquivalentGroup:
    doi: str
    accepted_count: int
    representation_ids: tuple[str, ...]
    work_id: str


@dataclass(frozen=True, slots=True)
class AmbiguousGroup:
    doi: str
    accepted_count: int
    pending_identifier_ids: tuple[str, ...]
    representation_ids: tuple[str, ...]
    redirect_count: int


@dataclass(frozen=True, slots=True)
class BackfillReceipt:
    equivalent: tuple[EquivalentGroup, ...]
    ambiguous: tuple[AmbiguousGroup, ...]
    integrity: IntegrityClassification
    receipt_sha256: str


def prepare_backup_copy(source_path: str | Path, target_dir: str | Path) -> Path:
    """5A backup-API snapshot plus representation sidecar copy."""
    dest = snapshot_db(source_path, target_dir)
    src_docs = Path(source_path).parent / "documents"
    dst_docs = Path(target_dir) / "documents"
    if src_docs.is_dir():
        if dst_docs.exists():
            shutil.rmtree(dst_docs)
        shutil.copytree(src_docs, dst_docs)
    return dest


def inspect_f1(
    conn: sqlite3.Connection,
) -> tuple[tuple[EquivalentGroup, ...], tuple[AmbiguousGroup, ...]]:
    """F1 groups from DB state: accepted DOI groups vs pending collisions."""
    reps_by_work: dict[str, list[str]] = defaultdict(list)
    for doc_id, work_id in conn.execute(
        "SELECT id, work_id FROM documents WHERE work_id IS NOT NULL ORDER BY id"
    ):
        reps_by_work[str(work_id)].append(str(doc_id))

    accepted_rows = conn.execute(
        "SELECT normalized_value, work_id FROM work_identifiers "
        "WHERE scheme = 'doi' AND status = 'accepted' "
        "ORDER BY normalized_value, work_id"
    ).fetchall()
    equivalent = tuple(
        EquivalentGroup(
            doi=str(doi),
            accepted_count=1,
            representation_ids=tuple(reps_by_work.get(str(work_id), ())),
            work_id=str(work_id),
        )
        for doi, work_id in accepted_rows
    )

    pending_by_doi: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for ident_id, work_id, doi in conn.execute(
        "SELECT id, work_id, normalized_value FROM work_identifiers "
        "WHERE scheme = 'doi' AND status = 'pending' "
        "ORDER BY normalized_value, id"
    ):
        pending_by_doi[str(doi)].append((str(ident_id), str(work_id)))

    accepted_dois = {group.doi for group in equivalent}
    redirect_count = int(
        conn.execute("SELECT COUNT(*) FROM work_redirect_decisions").fetchone()[0]
    )
    ambiguous: list[AmbiguousGroup] = []
    for doi, rows in pending_by_doi.items():
        work_ids = {work_id for _ident, work_id in rows}
        reps = tuple(
            doc_id
            for work_id in sorted(work_ids)
            for doc_id in reps_by_work.get(work_id, ())
        )
        ambiguous.append(
            AmbiguousGroup(
                doi=doi,
                accepted_count=1 if doi in accepted_dois else 0,
                pending_identifier_ids=tuple(ident for ident, _work in rows),
                representation_ids=reps,
                redirect_count=redirect_count,
            )
        )
    return equivalent, tuple(ambiguous)


def execute_doi_backfill(
    conn: sqlite3.Connection,
    *,
    generation: int = 0,
) -> BackfillReceipt:
    """Apply the planner's plan. Caller owns the transaction; no COMMIT."""
    raw_before = _raw_inventory(conn)
    cites_before = _citation_spans(conn)
    plan = plan_doi_backfill(conn)
    fingerprint = compute_source_fingerprint(conn)
    already_complete = phase_is_complete(conn, _BACKFILL_PHASE)

    def _write() -> None:
        if not already_complete:
            begin_phase(
                conn,
                phase=_BACKFILL_PHASE,
                generation=generation,
                source_fingerprint=fingerprint,
            )
        _apply_plan(conn, plan.entries)
        if not already_complete:
            complete_phase(
                conn,
                phase=_BACKFILL_PHASE,
                generation=generation,
                source_fingerprint=fingerprint,
            )

    _in_savepoint(conn, _SP_EXECUTE, _write)

    integrity = IntegrityClassification(
        raw_text_identical=_raw_inventory(conn) == raw_before,
        citation_spans_identical=_citation_spans(conn) == cites_before,
    )
    equivalent, ambiguous = inspect_f1(conn)
    return BackfillReceipt(
        equivalent=equivalent,
        ambiguous=ambiguous,
        integrity=integrity,
        receipt_sha256=_receipt_hash(equivalent, ambiguous, integrity),
    )


def _should_infer_arbitrary_uris() -> bool:
    """Arbitrary URI-to-DOI inference is forbidden (D10)."""
    return False


def _record_planned_collision(
    conn: sqlite3.Connection,
    *,
    scheme: str,
    normalized_value: str,
    work_ids: tuple[str, ...],
    actor: str,
    reason: str,
) -> CollisionReceipt:
    return record_collision(
        conn,
        scheme=scheme,
        normalized_value=normalized_value,
        work_ids=work_ids,
        actor=actor,
        reason=reason,
    )


def _apply_plan(conn: sqlite3.Connection, entries: Iterable) -> None:
    collision_dois: set[str] = set()
    collisions: dict[str, list] = defaultdict(list)
    for entry in entries:
        if entry.classification == "backfillable" and entry.candidate_doi:
            _set_doi(conn, entry.doc_id, entry.candidate_doi)
        elif (
            _should_infer_arbitrary_uris()
            and entry.classification == "non_derivable"
        ):
            inferred = normalize_doi(entry.source_uri) or entry.source_uri
            if inferred:
                _set_doi(conn, entry.doc_id, inferred)
        elif (
            entry.classification in _COLLISION_CLASSES
            and entry.candidate_doi is not None
        ):
            collision_dois.add(entry.candidate_doi)
            collisions[entry.candidate_doi].append(entry)

    _converge_equivalent(conn, skip_dois=collision_dois)
    _quarantine_collisions(conn, collisions)


def _converge_equivalent(
    conn: sqlite3.Connection,
    *,
    skip_dois: set[str],
) -> None:
    groups: dict[str, list[str]] = defaultdict(list)
    for doc_id, raw_doi in conn.execute(
        "SELECT id, doi FROM documents WHERE doi IS NOT NULL ORDER BY id"
    ):
        key = normalize_doi(raw_doi)
        if key is None or key in skip_dois:
            continue
        groups[key].append(str(doc_id))
    for doi, doc_ids in groups.items():
        work_id = _work_id_for_doi(doi)
        _ensure_work(conn, work_id)
        for doc_id in doc_ids:
            conn.execute(
                "UPDATE documents SET work_id = ? WHERE id = ?",
                (work_id, doc_id),
            )
        attach_identifier(
            conn,
            work_id=work_id,
            scheme="doi",
            normalized_value=doi,
            idempotency_key=f"mig-backfill:{doi}",
            representation_id=doc_ids[0],
            source="migration-backfill",
        )


def _quarantine_collisions(
    conn: sqlite3.Connection,
    collisions: dict[str, list],
) -> None:
    owners_by_doi = _owner_docs_by_doi(conn)
    for doi, entries in collisions.items():
        work_ids: list[str] = []
        seen: set[str] = set()
        for entry in entries:
            wid = _ensure_rep_work(conn, entry.doc_id)
            if wid not in seen:
                work_ids.append(wid)
                seen.add(wid)
        for owner_doc in owners_by_doi.get(doi, ()):
            wid = _ensure_rep_work(conn, owner_doc)
            if wid not in seen:
                work_ids.append(wid)
                seen.add(wid)
        _record_planned_collision(
            conn,
            scheme="doi",
            normalized_value=doi,
            work_ids=tuple(sorted(work_ids)),
            actor=_ACTOR,
            reason=_REASON,
        )


def _owner_docs_by_doi(conn: sqlite3.Connection) -> dict[str, tuple[str, ...]]:
    grouped: dict[str, list[str]] = defaultdict(list)
    for doc_id, raw_doi in conn.execute(
        "SELECT id, doi FROM documents WHERE doi IS NOT NULL ORDER BY id"
    ):
        key = normalize_doi(raw_doi)
        if key is not None:
            grouped[key].append(str(doc_id))
    return {doi: tuple(doc_ids) for doi, doc_ids in grouped.items()}


def _set_doi(conn: sqlite3.Connection, doc_id: str, doi: str) -> None:
    conn.execute("UPDATE documents SET doi = ? WHERE id = ?", (doi, doc_id))


def _ensure_work(conn: sqlite3.Connection, work_id: str) -> str:
    exists = conn.execute(
        "SELECT 1 FROM works WHERE id = ?", (work_id,)
    ).fetchone()
    if exists is None:
        create_work(conn, work_id)
    return work_id


def _ensure_rep_work(conn: sqlite3.Connection, doc_id: str) -> str:
    existing = conn.execute(
        "SELECT work_id FROM documents WHERE id = ?", (doc_id,)
    ).fetchone()
    if existing is not None and existing[0]:
        return str(existing[0])
    work_id = _work_id_for_rep(doc_id)
    _ensure_work(conn, work_id)
    conn.execute(
        "UPDATE documents SET work_id = ? WHERE id = ?",
        (work_id, doc_id),
    )
    return work_id


def _work_id_for_doi(doi: str) -> str:
    digest = hashlib.sha256(doi.encode("utf-8")).hexdigest()[:16]
    return f"w-doi-{digest}"


def _work_id_for_rep(doc_id: str) -> str:
    digest = hashlib.sha256(doc_id.encode("utf-8")).hexdigest()[:16]
    return f"w-rep-{digest}"


def _connection_db_path(conn: sqlite3.Connection) -> Path | None:
    for row in conn.execute("PRAGMA database_list"):
        if row[1] == "main" and row[2]:
            return Path(row[2])
    return None


def _raw_inventory(conn: sqlite3.Connection) -> tuple[tuple[str, str], ...]:
    db_path = _connection_db_path(conn)
    rows: list[tuple[str, str]] = []
    for doc_id, rel in conn.execute(
        "SELECT id, raw_text_path FROM documents ORDER BY id"
    ):
        digest = ""
        if db_path is not None and rel:
            path = db_path.parent / rel
            if path.is_file():
                digest = hashlib.sha256(path.read_bytes()).hexdigest()
        rows.append((str(doc_id), digest))
    return tuple(rows)


def _citation_spans(conn: sqlite3.Connection) -> tuple[tuple[str, ...], ...]:
    return tuple(
        (str(row[0]), str(row[1]), str(row[2]), row[3] if row[3] is not None else "")
        for row in conn.execute(
            "SELECT kind, item_id, source_doc_id, source_span "
            "FROM citations ORDER BY kind, item_id, source_doc_id, source_span"
        )
    )


def _receipt_hash(
    equivalent: tuple[EquivalentGroup, ...],
    ambiguous: tuple[AmbiguousGroup, ...],
    integrity: IntegrityClassification,
) -> str:
    payload = {
        "equivalent": [asdict(group) for group in equivalent],
        "ambiguous": [asdict(group) for group in ambiguous],
        "integrity": asdict(integrity),
    }
    blob = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


def _in_savepoint(
    conn: sqlite3.Connection,
    name: str,
    body,
) -> None:
    conn.execute(f"SAVEPOINT {name}")
    try:
        body()
        conn.execute(f"RELEASE SAVEPOINT {name}")
    except Exception:
        conn.execute(f"ROLLBACK TO SAVEPOINT {name}")
        conn.execute(f"RELEASE SAVEPOINT {name}")
        raise
