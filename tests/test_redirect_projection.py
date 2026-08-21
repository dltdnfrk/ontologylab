"""Wave 2.1 Step 4 (4B): current/as-of canonical redirect projection.

canonical_work follows merge decisions active at the queried time: recorded
at or before as_of and not yet superseded by a compensation recorded at or
before as_of. Decision times are supplied explicitly (decided_ts) so every
assertion is deterministic - no timing luck.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from ontologylab.authority_repo import create_work
from ontologylab.work_redirects import (
    RedirectAlreadyActive,
    RedirectCycleError,
    canonical_work,
    record_redirect,
)
from ontologylab.kgstore import KGStore


@pytest.fixture()
def store(tmp_path: Path):
    s = KGStore.open(tmp_path / "kg.sqlite")
    for wid in ("w-a", "w-b", "w-c"):
        create_work(s.conn, wid)
    yield s
    s.close()


def test_canonical_current_follows_active_merges(store) -> None:
    record_redirect(
        store.conn, source_work_id="w-a", target_work_id="w-b",
        action="merge", actor="qa", reason="a into b", decided_ts=10.0,
    )
    record_redirect(
        store.conn, source_work_id="w-b", target_work_id="w-c",
        action="merge", actor="qa", reason="b into c", decided_ts=20.0,
    )
    assert canonical_work(store.conn, "w-a") == "w-c"
    assert canonical_work(store.conn, "w-b") == "w-c"
    assert canonical_work(store.conn, "w-c") == "w-c"


def test_as_of_preserves_the_historical_owner(store) -> None:
    first = record_redirect(
        store.conn, source_work_id="w-a", target_work_id="w-b",
        action="merge", actor="qa", reason="a into b", decided_ts=10.0,
    )
    record_redirect(
        store.conn, source_work_id="w-a", target_work_id="w-b",
        action="compensate", actor="qa", reason="undo the merge",
        supersedes_id=first.decision_id, decided_ts=20.0,
    )
    assert canonical_work(store.conn, "w-a", as_of=5.0) == "w-a"
    assert canonical_work(store.conn, "w-a", as_of=15.0) == "w-b"
    assert canonical_work(store.conn, "w-a", as_of=25.0) == "w-a"
    assert canonical_work(store.conn, "w-a") == "w-a"


def test_mid_chain_as_of_returns_the_intermediate_owner(store) -> None:
    record_redirect(
        store.conn, source_work_id="w-a", target_work_id="w-b",
        action="merge", actor="qa", reason="a into b", decided_ts=10.0,
    )
    record_redirect(
        store.conn, source_work_id="w-b", target_work_id="w-c",
        action="merge", actor="qa", reason="b into c", decided_ts=20.0,
    )
    assert canonical_work(store.conn, "w-a", as_of=15.0) == "w-b"
    assert canonical_work(store.conn, "w-a", as_of=25.0) == "w-c"
    assert canonical_work(store.conn, "w-a", as_of=1.0) == "w-a"


def test_second_active_merge_from_one_source_is_refused(store) -> None:
    first = record_redirect(
        store.conn, source_work_id="w-a", target_work_id="w-b",
        action="merge", actor="qa", reason="a into b", decided_ts=10.0,
    )
    with pytest.raises(RedirectAlreadyActive) as raised:
        record_redirect(
            store.conn, source_work_id="w-a", target_work_id="w-c",
            action="merge", actor="qa", reason="ambiguous second target",
            decided_ts=15.0,
        )
    assert raised.value.source_work_id == "w-a"
    assert raised.value.active_target_work_id == "w-b"
    record_redirect(
        store.conn, source_work_id="w-a", target_work_id="w-b",
        action="compensate", actor="qa", reason="undo before re-redirect",
        supersedes_id=first.decision_id, decided_ts=20.0,
    )
    reverse = record_redirect(
        store.conn, source_work_id="w-a", target_work_id="w-c",
        action="merge", actor="qa", reason="now unambiguous",
        decided_ts=30.0,
    )
    assert reverse.decision_id
    assert canonical_work(store.conn, "w-a") == "w-c"


def test_cycle_still_refused_over_the_active_projection(store) -> None:
    record_redirect(
        store.conn, source_work_id="w-a", target_work_id="w-b",
        action="merge", actor="qa", reason="a into b", decided_ts=10.0,
    )
    with pytest.raises(RedirectCycleError):
        record_redirect(
            store.conn, source_work_id="w-b", target_work_id="w-a",
            action="merge", actor="qa", reason="would cycle", decided_ts=15.0,
        )


def test_redirect_decision_rows_are_append_only(store) -> None:
    """Named coverage for the work_redirect_decisions triggers (Step 3
    WATCH note 2)."""
    receipt = record_redirect(
        store.conn, source_work_id="w-a", target_work_id="w-b",
        action="merge", actor="qa", reason="a into b", decided_ts=10.0,
    )
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        store.conn.execute(
            "UPDATE work_redirect_decisions SET target_work_id='w-c' "
            "WHERE id = ?",
            (receipt.decision_id,),
        )
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        store.conn.execute(
            "DELETE FROM work_redirect_decisions WHERE id = ?",
            (receipt.decision_id,),
        )
