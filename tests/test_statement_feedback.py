"""Review receipts remain transactional, append-only, and split-isolated."""

from __future__ import annotations

import ast
import sqlite3
from pathlib import Path

import pytest

from ontologylab.statement_feedback import (
    ReviewEvent,
    export_feedback,
    review_snapshot,
)
from tests.conftest import insert
from tests.factories import make_entity


def test_review_store_modules_have_no_direct_commit() -> None:
    root = Path(__file__).resolve().parents[1] / "ontologylab"
    for name in ("kgstore_review.py", "kgstore_documents.py", "kgstore_proposed.py"):
        tree = ast.parse((root / name).read_text(encoding="utf-8"))
        direct = [
            node.lineno for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "commit"
            and isinstance(node.func.value, ast.Attribute)
            and node.func.value.attr == "conn"
        ]
        assert not direct, f"{name}: direct commits at {direct}"


def test_failed_event_rolls_back_approval(store, doc, monkeypatch) -> None:
    # Given a proposed node and a failure at the event insert seam.
    item = make_entity("ReviewTarget")
    insert(store, doc, [item])
    # Force the legacy no-citation approval branch, which has its own commit.
    store.conn.execute(
        "DELETE FROM citations WHERE kind='node' AND item_id=?", (item.id,),
    )
    store.conn.commit()

    def fail_event(_event: ReviewEvent) -> str:
        raise sqlite3.OperationalError("forced event failure")

    monkeypatch.setattr(store, "record_review_event", fail_event)

    # When the approval and receipt share one transaction.
    with pytest.raises(sqlite3.OperationalError, match="forced event failure"):
        with store.atomic():
            before = review_snapshot(store.conn, (item.id,))
            store.approve(item.id, by="reviewer")
            store.record_review_event(ReviewEvent(
                action="approve", actor="reviewer", item_ids=(item.id,),
                before=before, after=review_snapshot(store.conn, (item.id,)),
                source_doc_ids=(doc.id,), source_hashes=("sha256:test",),
            ))

    # Then the proposal remains unapproved and no receipt survives.
    assert store.conn.execute(
        "SELECT status FROM nodes WHERE id = ?", (item.id,),
    ).fetchone()["status"] == "proposed"
    assert store.conn.execute(
        "SELECT count(*) FROM statement_review_events"
    ).fetchone()[0] == 0


def test_held_out_feedback_is_not_exported(store, doc) -> None:
    # Given one development receipt and one held-out receipt with the same source.
    with store.atomic():
        store.record_review_event(ReviewEvent(
            action="reject", actor="curator", item_ids=("dev",),
            before=({"id": "dev", "status": "proposed"},),
            after=({"id": "dev", "status": "rejected"},),
            source_doc_ids=(doc.id,), source_hashes=("sha256:test",),
            split_assignment="development",
        ))
        store.record_review_event(ReviewEvent(
            action="reject", actor="curator", item_ids=("test",),
            before=({"id": "test", "status": "proposed"},),
            after=({"id": "test", "status": "rejected"},),
            source_doc_ids=(doc.id,), source_hashes=("sha256:test",),
            split_assignment="held_out",
        ))

    # When the development-only export is read.
    exported = export_feedback(store.conn, development_ids={"sha256:test"})

    # Then even a supplied development hash cannot dequarantine held-out feedback.
    assert len(exported) == 1
    assert exported[0]["item_ids"] == ("dev",)
    assert exported[0]["before"] == ({"id": "dev", "status": "proposed"},)
    assert export_feedback(store.conn, development_ids=set()) == ()


def test_review_event_requires_transaction_and_cannot_be_changed(store, doc) -> None:
    event = ReviewEvent(
        action="reject", actor="reviewer", item_ids=("item",),
        before=(), after=(), source_doc_ids=(doc.id,),
        source_hashes=("sha256:test",),
    )
    with pytest.raises(AssertionError, match="store.atomic"):
        store.record_review_event(event)
    with store.atomic():
        event_id = store.record_review_event(event)
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        store.conn.execute(
            "UPDATE statement_review_events SET actor='other' WHERE id=?",
            (event_id,),
        )
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        store.conn.execute(
            "DELETE FROM statement_review_events WHERE id=?", (event_id,),
        )
