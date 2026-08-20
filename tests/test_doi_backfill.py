"""Wave 2.1 Step 2: dry-run DOI backfill policy (C-023 boundary).

Step 5 owns executing the backfill with cursor/ledger/collision machinery;
this module pins the POLICY as a pure read-only classifier per D10:
exact-resolver derivation only, collisions quarantined with zero accepted
owner, deterministic receipts, nothing written.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from ontologylab.doi_backfill import plan_doi_backfill
from ontologylab.kgstore import KGStore
from tests.wave21.identity import seed_premigration_documents_row


def _seeded_store(tmp_path: Path) -> Path:
    db = tmp_path / "kg.sqlite"
    rows = (
        ("legacy-resolver", "https://doi.org/10.1000/backfill.ok", "sha256:bf-1"),
        ("legacy-arbitrary", "https://arxiv.org/abs/2401.00001", "sha256:bf-2"),
        ("legacy-bare", "10.9999/bare.doi", "sha256:bf-3"),
        ("legacy-owned", "https://doi.org/10.1000/backfill.owned", "sha256:bf-4"),
        ("legacy-dup-a", "https://doi.org/10.1000/backfill.dup", "sha256:bf-5"),
        ("legacy-dup-b", "https://dx.doi.org/10.1000/backfill.dup", "sha256:bf-6"),
    )
    for doc_id, source_uri, content_hash in rows:
        seed_premigration_documents_row(
            db,
            doc_id=doc_id,
            source_uri=source_uri,
            raw_text=f"legacy body for {doc_id}",
            content_hash=content_hash,
        )
    store = KGStore.open(db)  # migration adds the nullable doi column only
    store.insert_document(
        source_kind="paper_api",
        source_uri="https://doi.org/10.1000/backfill.owned",
        title="Modern owner",
        raw_text="the modern owner row",
        content_hash="sha256:bf-owner",
        doi="10.1000/backfill.owned",
    )
    store.close()
    return db


def _plan(db: Path):
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        return plan_doi_backfill(conn)
    finally:
        conn.close()


def test_plan_classifies_per_exact_resolver_policy(tmp_path: Path) -> None:
    plan = _plan(_seeded_store(tmp_path))
    by_id = {entry.doc_id: entry for entry in plan.entries}

    assert by_id["legacy-resolver"].classification == "backfillable"
    assert by_id["legacy-resolver"].candidate_doi == "10.1000/backfill.ok"
    # Arbitrary URI-to-DOI inference is forbidden (D10): arxiv URLs and bare
    # DOI strings without a resolver prefix never derive a candidate.
    assert by_id["legacy-arbitrary"].classification == "non_derivable"
    assert by_id["legacy-arbitrary"].candidate_doi is None
    assert by_id["legacy-bare"].classification == "non_derivable"
    # A candidate already owned by another row is a collision, never a
    # backfill; two rows deriving the same candidate are ambiguous.
    assert by_id["legacy-owned"].classification == "collision_owner"
    assert by_id["legacy-dup-a"].classification == "collision_ambiguous"
    assert by_id["legacy-dup-b"].classification == "collision_ambiguous"
    assert plan.counts == {
        "backfillable": 1,
        "collision_owner": 1,
        "collision_ambiguous": 2,
        "non_derivable": 2,
    }


def test_plan_is_read_only_and_deterministic(tmp_path: Path) -> None:
    db = _seeded_store(tmp_path)
    first = _plan(db)
    second = _plan(db)
    assert first.plan_sha256 == second.plan_sha256
    assert len(first.plan_sha256) == 64

    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        rows = conn.execute(
            "SELECT id, doi FROM documents ORDER BY id"
        ).fetchall()
    finally:
        conn.close()
    legacy_dois = [doi for doc_id, doi in rows if doc_id.startswith("legacy-")]
    assert legacy_dois == [None] * 6
    owner_dois = [doi for doc_id, doi in rows if not doc_id.startswith("legacy-")]
    assert owner_dois == ["10.1000/backfill.owned"]
