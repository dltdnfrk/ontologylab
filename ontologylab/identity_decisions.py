"""Audited identity decision operations (Wave 2.1 Step 4, 4A).

Every decision carries a non-empty actor and reason and lands one
append-only ``identifier_decisions`` row in the same caller-owned
transaction (SAVEPOINT-scoped, no internal commit). Retraction is a
write-once status transition that frees the accepted-owner slot; ambiguous
collisions become deterministic PENDING records with zero accepted owner
(D10) - rerunning the same resolution reproduces identical ids and no
duplicate audit rows. No operation here deletes anything.
"""

from __future__ import annotations

import hashlib
import sqlite3
import uuid
from dataclasses import dataclass

from ontologylab.authority_repo import (
    AttachResult,
    AuthorityError,
    attach_identifier,
)


@dataclass(frozen=True, slots=True)
class DecisionInputInvalid(AuthorityError):
    """A decision arrived without the required actor or reason."""

    field: str

    def __str__(self) -> str:
        return f"decision requires a non-empty {self.field}"


@dataclass(frozen=True, slots=True)
class UnknownIdentifier(AuthorityError):
    """The referenced work_identifiers row does not exist."""

    identifier_id: str

    def __str__(self) -> str:
        return f"identifier {self.identifier_id!r} not found"


@dataclass(frozen=True, slots=True)
class IdentifierAlreadyRetracted(AuthorityError):
    """Retraction is write-once; the identifier is already retracted."""

    identifier_id: str

    def __str__(self) -> str:
        return f"identifier {self.identifier_id!r} is already retracted"


@dataclass(frozen=True, slots=True)
class DecisionReceipt:
    decision_id: str
    action: str
    identifier_id: str


@dataclass(frozen=True, slots=True)
class CollisionReceipt:
    """Deterministic pending records for one ambiguous (scheme, value)."""

    pending_identifier_ids: tuple[str, ...]
    decision_ids: tuple[str, ...]


def _require_inputs(actor: str, reason: str) -> None:
    if not actor.strip():
        raise DecisionInputInvalid(field="actor")
    if not reason.strip():
        raise DecisionInputInvalid(field="reason")


def _audit(
    conn: sqlite3.Connection,
    *,
    identifier_id: str,
    action: str,
    actor: str,
    reason: str,
    decision_id: str | None = None,
) -> str:
    decision_id = decision_id or f"idd-{uuid.uuid4().hex[:12]}"
    conn.execute(
        "INSERT INTO identifier_decisions "
        "(id, identifier_id, action, actor, reason, created_ts) "
        "VALUES (?, ?, ?, ?, ?, julianday('now'))",
        (decision_id, identifier_id, action, actor, reason),
    )
    return decision_id


def attach_with_decision(
    conn: sqlite3.Connection,
    *,
    work_id: str,
    scheme: str,
    normalized_value: str,
    idempotency_key: str,
    actor: str,
    reason: str,
    **attach_kwargs,
) -> tuple[AttachResult, DecisionReceipt]:
    """Operator-surface attach: the Step 3 reservation plus the audit row."""
    _require_inputs(actor, reason)
    conn.execute("SAVEPOINT identity_decision")
    try:
        result = attach_identifier(
            conn, work_id=work_id, scheme=scheme,
            normalized_value=normalized_value,
            idempotency_key=idempotency_key, **attach_kwargs,
        )
        decision_id = _audit(
            conn, identifier_id=result.identifier_id, action="attach",
            actor=actor, reason=reason,
        )
        conn.execute("RELEASE SAVEPOINT identity_decision")
        return result, DecisionReceipt(
            decision_id=decision_id, action="attach",
            identifier_id=result.identifier_id,
        )
    except Exception:
        conn.execute("ROLLBACK TO SAVEPOINT identity_decision")
        conn.execute("RELEASE SAVEPOINT identity_decision")
        raise


def retract_identifier(
    conn: sqlite3.Connection,
    *,
    identifier_id: str,
    actor: str,
    reason: str,
) -> DecisionReceipt:
    """Write-once retraction: frees the accepted-owner slot, never deletes."""
    _require_inputs(actor, reason)
    conn.execute("SAVEPOINT identity_decision")
    try:
        row = conn.execute(
            "SELECT status FROM work_identifiers WHERE id = ?",
            (identifier_id,),
        ).fetchone()
        if row is None:
            raise UnknownIdentifier(identifier_id=identifier_id)
        if row[0] == "retracted":
            raise IdentifierAlreadyRetracted(identifier_id=identifier_id)
        conn.execute(
            "UPDATE work_identifiers SET status = 'retracted' WHERE id = ?",
            (identifier_id,),
        )
        decision_id = _audit(
            conn, identifier_id=identifier_id, action="retract",
            actor=actor, reason=reason,
        )
        conn.execute("RELEASE SAVEPOINT identity_decision")
        return DecisionReceipt(
            decision_id=decision_id, action="retract",
            identifier_id=identifier_id,
        )
    except Exception:
        conn.execute("ROLLBACK TO SAVEPOINT identity_decision")
        conn.execute("RELEASE SAVEPOINT identity_decision")
        raise


def record_collision(
    conn: sqlite3.Connection,
    *,
    scheme: str,
    normalized_value: str,
    work_ids: tuple[str, ...],
    actor: str,
    reason: str,
) -> CollisionReceipt:
    """Ambiguity yields deterministic pending records, zero accepted owner.

    Ids derive from (scheme, value, work); rerunning the same resolution is
    idempotent - identical ids, no duplicate rows, no duplicate audit.
    """
    _require_inputs(actor, reason)
    conn.execute("SAVEPOINT identity_decision")
    try:
        pending_ids: list[str] = []
        decision_ids: list[str] = []
        for work_id in work_ids:
            digest = hashlib.sha256(
                f"{scheme}:{normalized_value}:{work_id}".encode("utf-8")
            ).hexdigest()[:12]
            pending_id = f"pend-{digest}"
            inserted = conn.execute(
                "INSERT OR IGNORE INTO work_identifiers "
                "(id, work_id, scheme, normalized_value, status, created_ts) "
                "VALUES (?, ?, ?, ?, 'pending', julianday('now'))",
                (pending_id, work_id, scheme, normalized_value),
            ).rowcount
            if inserted:
                decision_ids.append(
                    _audit(
                        conn, identifier_id=pending_id,
                        action="resolve_collision", actor=actor,
                        reason=reason, decision_id=f"idd-{digest}",
                    )
                )
            pending_ids.append(pending_id)
        conn.execute("RELEASE SAVEPOINT identity_decision")
        return CollisionReceipt(
            pending_identifier_ids=tuple(pending_ids),
            decision_ids=tuple(decision_ids),
        )
    except Exception:
        conn.execute("ROLLBACK TO SAVEPOINT identity_decision")
        conn.execute("RELEASE SAVEPOINT identity_decision")
        raise
