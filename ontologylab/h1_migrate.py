"""H1 rehearsal loop. SAVEPOINT per anchor; caller owns COMMIT."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from typing import assert_never

from ontologylab.h1_finalize import commit_one, commit_run_unit
from ontologylab.h1_inventory import family_of, list_anchors
from ontologylab.h1_schema import ensure_h1_schema
from ontologylab.h1_store import classified_anchor_ids, checkpoint, phase_complete
from ontologylab.h1_types import (
    H1Anchor,
    H1ChunkAnchor,
    H1CitationAnchor,
    H1Classification,
    H1Failpoint,
    H1Family,
    H1FamilyCount,
    H1Inventory,
    H1Receipt,
    H1ReviewAnchor,
    H1RunAnchor,
)
from ontologylab.migration import compute_source_fingerprint
from ontologylab.migration_rehearsal import canonical_db_hash


_COMPLETE = "$complete"


def run_h1_migration(
    conn: sqlite3.Connection,
    *,
    failpoint: H1Failpoint | None = None,
) -> H1Receipt:
    """Classify every dest-only anchor. No hidden COMMIT/ROLLBACK."""
    ensure_h1_schema(conn)
    fingerprint = compute_source_fingerprint(conn)
    if phase_complete(conn):
        return build_receipt(conn)
    done = set(classified_anchor_ids(conn))
    anchors = list_anchors(conn)
    for anchor in anchors:
        if anchor.anchor_id in done:
            continue
        match anchor:
            case H1RunAnchor():
                chunks = tuple(
                    item
                    for item in anchors
                    if isinstance(item, H1ChunkAnchor)
                    and item.run_id == anchor.run_id
                    and item.anchor_id not in done
                )
                commit_run_unit(conn, anchor, chunks, fingerprint, failpoint)
                done.add(anchor.anchor_id)
                done.update(chunk.anchor_id for chunk in chunks)
            case H1ChunkAnchor() | H1CitationAnchor() | H1ReviewAnchor():
                commit_one(conn, anchor, fingerprint, failpoint)
                done.add(anchor.anchor_id)
            case unreachable:
                assert_never(unreachable)
    conn.execute("SAVEPOINT h1_anchor")
    try:
        checkpoint(conn, _COMPLETE, fingerprint)
        conn.execute("RELEASE SAVEPOINT h1_anchor")
    except Exception:
        conn.execute("ROLLBACK TO SAVEPOINT h1_anchor")
        conn.execute("RELEASE SAVEPOINT h1_anchor")
        raise
    return build_receipt(conn)


def h1_inventory(conn: sqlite3.Connection) -> H1Inventory:
    ensure_h1_schema(conn)
    anchors = list_anchors(conn)
    classified = {
        str(row[0]): str(row[1])
        for row in conn.execute(
            "SELECT anchor_id, classification FROM h1_anchor_receipts"
        )
    }
    families = tuple(
        _family_count(family, anchors, classified) for family in H1Family
    )
    verified = sum(item.verified for item in families)
    quarantined = sum(item.quarantined for item in families)
    pending = sum(item.pending for item in families)
    return H1Inventory(
        verified=verified,
        quarantined=quarantined,
        pending=pending,
        anchor_count=len(anchors),
        families=families,
    )


def build_receipt(conn: sqlite3.Connection) -> H1Receipt:
    inventory = h1_inventory(conn)
    dump = canonical_db_hash(conn)
    family_rows = [
        [str(row[0]), str(row[1]), "" if row[2] is None else str(row[2])]
        for row in conn.execute(
            "SELECT family, anchor_id, family_receipt_id "
            "FROM h1_anchor_receipts ORDER BY family, anchor_id"
        )
    ]
    payload = {
        "anchor_count": inventory.anchor_count,
        "complete": inventory.pending == 0,
        "dump_sha256": dump,
        "families": [
            {
                "anchor_count": item.anchor_count,
                "family": item.family.value,
                "pending": item.pending,
                "quarantined": item.quarantined,
                "verified": item.verified,
            }
            for item in inventory.families
        ],
        "family_receipts": family_rows,
        "pending": inventory.pending,
        "quarantined": inventory.quarantined,
        "verified": inventory.verified,
    }
    receipt = hashlib.sha256(
        json.dumps(
            payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
        ).encode("utf-8")
    ).hexdigest()
    return H1Receipt(
        inventory=inventory,
        dump_sha256=dump,
        receipt_sha256=receipt,
        complete=inventory.pending == 0,
    )


def _family_count(
    family: H1Family,
    anchors: tuple[H1Anchor, ...],
    classified: dict[str, str],
) -> H1FamilyCount:
    members = [item for item in anchors if family_of(item) is family]
    verified = 0
    quarantined = 0
    pending = 0
    for item in members:
        status = classified.get(item.anchor_id)
        if status == H1Classification.VERIFIED.value:
            verified += 1
        elif status == H1Classification.QUARANTINED.value:
            quarantined += 1
        else:
            pending += 1
    return H1FamilyCount(
        family=family,
        verified=verified,
        quarantined=quarantined,
        pending=pending,
        anchor_count=len(members),
    )
