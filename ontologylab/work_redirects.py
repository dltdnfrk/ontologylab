"""Work redirect decisions and the current/as-of canonical projection
(Wave 2.1 Steps 3-4, D09).

Append-only merge/compensate decisions; a source Work holds at most one
active merge; cycles are refused over the active projection; and
``canonical_work`` computes the current or as-of owner as a pure read -
history is never rewritten.
"""

from __future__ import annotations

import sqlite3
import uuid
from dataclasses import dataclass

from ontologylab.authority_repo import AuthorityError


def _new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


@dataclass(frozen=True, slots=True)
class RedirectAlreadyActive(AuthorityError):
    """The source Work already has an active merge; compensate it first."""

    source_work_id: str
    active_target_work_id: str

    def __str__(self) -> str:
        return (
            f"work {self.source_work_id} already redirects to "
            f"{self.active_target_work_id}; compensate that decision before "
            f"recording a new merge"
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
class RedirectResult:
    """Outcome of one redirect decision."""

    decision_id: str


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
    decided_ts: float | None = None,
) -> RedirectResult:
    """Append one redirect/compensation decision; cycles are refused.

    Compensation supersedes a prior merge without rewriting any FK (D09):
    the active projection simply stops following superseded merges, so the
    cycle check runs over that projection. A source with an active merge
    refuses a second one typed (compensate first). ``decided_ts`` lets
    callers/tests supply the decision time deterministically; None stamps
    now.
    """
    if action == "merge":
        active = conn.execute(
            "SELECT d.target_work_id FROM work_redirect_decisions d "
            "WHERE d.source_work_id = ? AND d.action = 'merge' "
            "AND NOT EXISTS (SELECT 1 FROM work_redirect_decisions c "
            "  WHERE c.action = 'compensate' AND c.supersedes_id = d.id)",
            (source_work_id,),
        ).fetchone()
        if active is not None:
            raise RedirectAlreadyActive(
                source_work_id=source_work_id,
                active_target_work_id=active[0],
            )
        chain = _active_redirect_chain(conn, target_work_id)
        if source_work_id in chain:
            raise RedirectCycleError(
                source_work_id=source_work_id, target_work_id=target_work_id,
            )
    decision_id = _new_id("wrd")
    conn.execute(
        "INSERT INTO work_redirect_decisions (id, source_work_id, "
        "target_work_id, action, supersedes_id, actor, reason, created_ts) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, COALESCE(?, julianday('now')))",
        (decision_id, source_work_id, target_work_id, action,
         supersedes_id, actor, reason, decided_ts),
    )
    return RedirectResult(decision_id=decision_id)


def canonical_work(
    conn: sqlite3.Connection,
    work_id: str,
    *,
    as_of: float | None = None,
) -> str:
    """The canonical Work id under the redirect projection active at as_of.

    A merge counts when it was recorded at or before ``as_of`` and its
    superseding compensation is NOT yet recorded at that ``as_of``;
    ``as_of=None`` means now. Pure read - history is never rewritten, so an
    earlier as_of always returns the historical owner (D09).
    """
    current = work_id
    seen = {work_id}
    while True:
        row = conn.execute(
            "SELECT d.target_work_id FROM work_redirect_decisions d "
            "WHERE d.source_work_id = ? AND d.action = 'merge' "
            "AND (? IS NULL OR d.created_ts <= ?) "
            "AND NOT EXISTS (SELECT 1 FROM work_redirect_decisions c "
            "  WHERE c.action = 'compensate' AND c.supersedes_id = d.id "
            "  AND (? IS NULL OR c.created_ts <= ?)) "
            "ORDER BY d.created_ts DESC LIMIT 1",
            (current, as_of, as_of, as_of, as_of),
        ).fetchone()
        if row is None:
            return current
        if row[0] in seen:
            raise RedirectCycleError(
                source_work_id=current, target_work_id=row[0],
            )
        seen.add(row[0])
        current = row[0]
