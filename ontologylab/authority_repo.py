"""Typed authority repository (Wave 2.1 Step 3, 3B).

All writes are SAVEPOINT-scoped inside the caller-owned transaction: this
module never issues COMMIT or ROLLBACK itself (invariant 11). The attach
contract is reserve-then-observe-then-assert atomically (invariant 3):
the work_identifiers row is reserved first, then the Observation (retries
idempotent on idempotency_key, D08) and its append-only
identifier_assertions link.
"""

from __future__ import annotations

import sqlite3
import uuid
from dataclasses import dataclass


class AuthorityError(Exception):
    """Base class for typed authority conflicts."""


@dataclass(frozen=True, slots=True)
class IdentifierOwnedConflict(AuthorityError):
    """The (scheme, normalized_value) pair already has an accepted owner."""

    scheme: str
    normalized_value: str
    existing_work_id: str | None

    def __str__(self) -> str:
        return (
            f"identifier {self.scheme}:{self.normalized_value} is already "
            f"owned by work {self.existing_work_id!r}"
        )


@dataclass(frozen=True, slots=True)
class SecondDoiAttachConflict(AuthorityError):
    """A Work already has an active accepted DOI; a second one is refused."""

    work_id: str
    existing_doi: str
    incoming_doi: str

    def __str__(self) -> str:
        return (
            f"work {self.work_id} already has accepted DOI "
            f"{self.existing_doi!r}; refusing second DOI {self.incoming_doi!r}"
        )


@dataclass(frozen=True, slots=True)
class RedirectCycleError(AuthorityError):
    """The redirect would create a cycle in the active projection."""

    source_work_id: str
    target_work_id: str

    def __str__(self) -> str:
        return (
            f"redirect {self.source_work_id} -> {self.target_work_id} "
            f"would create a cycle in the active redirect projection"
        )


@dataclass(frozen=True, slots=True)
class AttachResult:
    """Outcome of one attach: ids plus whether anything was newly written."""

    identifier_id: str
    observation_id: str
    created: bool


@dataclass(frozen=True, slots=True)
class RedirectResult:
    """Outcome of one redirect decision."""

    decision_id: str


_OWNER_INDEX = "idx_work_identifiers_accepted_owner"
_DOI_INDEX = "idx_work_identifiers_one_doi_per_work"


def map_identifier_integrity_error(
    conn: sqlite3.Connection,
    exc: sqlite3.IntegrityError,
    *,
    work_id: str,
    scheme: str,
    normalized_value: str,
) -> AuthorityError:
    """Translate a reservation IntegrityError into the typed conflict.

    SQLite reports partial-index violations by column, not index name, so
    the distinction is made by re-querying the authoritative state on the
    same connection: a different accepted owner of the (scheme, value)
    pair means an ownership conflict; an accepted DOI already on this Work
    with a different value means a second-DOI attach refusal.
    """
    owner = _accepted_owner(conn, scheme, normalized_value)
    if owner is not None and owner != work_id:
        return IdentifierOwnedConflict(
            scheme=scheme, normalized_value=normalized_value,
            existing_work_id=owner,
        )
    if scheme == "doi":
        row = conn.execute(
            "SELECT normalized_value FROM work_identifiers WHERE work_id = ? "
            "AND scheme = 'doi' AND status = 'accepted'",
            (work_id,),
        ).fetchone()
        if row is not None and row[0] != normalized_value:
            return SecondDoiAttachConflict(
                work_id=work_id, existing_doi=row[0],
                incoming_doi=normalized_value,
            )
    return AuthorityError(str(exc))


def _new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


def create_work(conn: sqlite3.Connection, work_id: str | None = None) -> str:
    wid = work_id or _new_id("work")
    conn.execute(
        "INSERT INTO works (id, state, created_ts) VALUES (?, 'active', "
        "julianday('now'))",
        (wid,),
    )
    return wid


def _accepted_owner(conn: sqlite3.Connection, scheme: str, value: str) -> str | None:
    row = conn.execute(
        "SELECT work_id FROM work_identifiers WHERE scheme = ? AND "
        "normalized_value = ? AND status = 'accepted'",
        (scheme, value),
    ).fetchone()
    return row[0] if row else None


def attach_identifier(
    conn: sqlite3.Connection,
    *,
    work_id: str,
    scheme: str,
    normalized_value: str,
    idempotency_key: str,
    source: str = "",
    evidence_grade: str = "",
    representation_id: str | None = None,
    stage: str = "unknown",
    content_kind: str = "metadata_only",
    begin_before_check: bool = True,
) -> AttachResult:
    """Reserve an identifier, then record the Observation and assertion.

    Retries with the same idempotency_key reuse the existing Observation
    (D08). Conflicts are typed; the SAVEPOINT guarantees no partial rows.
    """
    conn.execute("SAVEPOINT attach_identifier")
    try:
        # Retried operations are idempotent FIRST (D08): if the Observation
        # already exists, return its linked identifier without any insert.
        existing_obs = conn.execute(
            "SELECT id FROM document_observations WHERE idempotency_key = ?",
            (idempotency_key,),
        ).fetchone()
        if existing_obs is not None:
            linked = conn.execute(
                "SELECT identifier_id FROM identifier_assertions "
                "WHERE observation_id = ?",
                (existing_obs[0],),
            ).fetchone()
            conn.execute("RELEASE SAVEPOINT attach_identifier")
            return AttachResult(
                identifier_id=linked[0] if linked else "",
                observation_id=existing_obs[0],
                created=False,
            )
        if begin_before_check:
            owner = _accepted_owner(conn, scheme, normalized_value)
            if owner is not None and owner != work_id:
                raise IdentifierOwnedConflict(
                    scheme=scheme, normalized_value=normalized_value,
                    existing_work_id=owner,
                )
        existing_doi_row = conn.execute(
            "SELECT normalized_value FROM work_identifiers WHERE work_id = ? "
            "AND scheme = 'doi' AND status = 'accepted'",
            (work_id,),
        ).fetchone()
        if scheme == "doi" and existing_doi_row is not None and (
            existing_doi_row[0] != normalized_value
        ):
            raise SecondDoiAttachConflict(
                work_id=work_id,
                existing_doi=existing_doi_row[0],
                incoming_doi=normalized_value,
            )

        # Same identifier on the same Work: reuse the row and add an
        # assertion (invariant 3); a new identifier row is only reserved
        # when this Work does not already own the (scheme, value) pair.
        existing_same = conn.execute(
            "SELECT id FROM work_identifiers WHERE work_id = ? AND scheme = ? "
            "AND normalized_value = ? AND status = 'accepted'",
            (work_id, scheme, normalized_value),
        ).fetchone()
        if existing_same is not None:
            identifier_id = existing_same[0]
        else:
            identifier_id = _new_id("wi")
            try:
                conn.execute(
                    "INSERT INTO work_identifiers (id, work_id, scheme, "
                    "normalized_value, status, created_ts) "
                    "VALUES (?, ?, ?, ?, 'accepted', julianday('now'))",
                    (identifier_id, work_id, scheme, normalized_value),
                )
            except sqlite3.IntegrityError as exc:
                raise map_identifier_integrity_error(
                    conn, exc, work_id=work_id, scheme=scheme,
                    normalized_value=normalized_value,
                ) from exc

        observation_id = _insert_observation(
            conn,
            idempotency_key=idempotency_key,
            source=source,
            evidence_grade=evidence_grade,
            representation_id=representation_id,
            stage=stage,
            content_kind=content_kind,
        )
        created = True
        conn.execute(
            "INSERT OR IGNORE INTO identifier_assertions "
            "(identifier_id, observation_id, created_ts) "
            "VALUES (?, ?, julianday('now'))",
            (identifier_id, observation_id),
        )
        conn.execute("RELEASE SAVEPOINT attach_identifier")
        return AttachResult(
            identifier_id=identifier_id,
            observation_id=observation_id,
            created=created,
        )
    except Exception:
        conn.execute("ROLLBACK TO SAVEPOINT attach_identifier")
        conn.execute("RELEASE SAVEPOINT attach_identifier")
        raise


def _insert_observation(
    conn: sqlite3.Connection,
    *,
    idempotency_key: str,
    source: str,
    evidence_grade: str,
    representation_id: str | None,
    stage: str,
    content_kind: str,
) -> str:
    observation_id = _new_id("obs")
    conn.execute(
        "INSERT INTO document_observations (id, representation_id, "
        "idempotency_key, source, evidence_grade, stage, content_kind, "
        "created_ts) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, julianday('now'))",
        (observation_id, representation_id, idempotency_key, source,
         evidence_grade, stage, content_kind),
    )
    return observation_id


def _active_redirect_chain(conn: sqlite3.Connection, start: str) -> set[str]:
    """Works reachable from start through non-superseded merge decisions."""
    superseded = {
        row[0]
        for row in conn.execute(
            "SELECT supersedes_id FROM work_redirect_decisions "
            "WHERE supersedes_id IS NOT NULL"
        )
    }
    reachable = {start}
    frontier = [start]
    while frontier:
        current = frontier.pop()
        for row in conn.execute(
            "SELECT id, target_work_id FROM work_redirect_decisions "
            "WHERE source_work_id = ? AND action = 'merge'",
            (current,),
        ):
            if row[0] in superseded:
                continue
            if row[1] not in reachable:
                reachable.add(row[1])
                frontier.append(row[1])
    return reachable


def record_redirect(
    conn: sqlite3.Connection,
    *,
    source_work_id: str,
    target_work_id: str,
    action: str,
    actor: str,
    reason: str,
    supersedes_id: str | None = None,
) -> RedirectResult:
    """Append one redirect/compensation decision; cycles are refused.

    Compensation supersedes a prior merge without rewriting any FK (D09):
    the active projection simply stops following superseded merges, so the
    cycle check runs over that projection.
    """
    if action == "merge":
        chain = _active_redirect_chain(conn, target_work_id)
        if source_work_id in chain:
            raise RedirectCycleError(
                source_work_id=source_work_id, target_work_id=target_work_id,
            )
    decision_id = _new_id("wrd")
    conn.execute(
        "INSERT INTO work_redirect_decisions (id, source_work_id, "
        "target_work_id, action, supersedes_id, actor, reason, created_ts) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, julianday('now'))",
        (decision_id, source_work_id, target_work_id, action,
         supersedes_id, actor, reason),
    )
    return RedirectResult(decision_id=decision_id)
