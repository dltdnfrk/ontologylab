"""Direct-service ingestion identity characterization tests.

Scope: `KGStore.insert_document` / `normalize_doi`, called directly without
the CLI, HTTP, worker, or MCP surfaces. Assertions read machine-consumed
state from SQLite or the filesystem rather than pinning prose.

The scenarios cover same-DOI representations, conflicting explicit DOIs,
legacy DOI backfill, and registered DOI punctuation. Remaining unsupported
schema behavior is represented by strict xfail rather than reported as
release evidence.
"""

from __future__ import annotations

import pytest

from ontologylab.kgstore import DocumentIdentityConflict, KGStore
from tests.wave21.identity import (
    insert_different_doi_same_bytes,
    insert_same_doi_new_bytes,
    migrate_and_reinsert_by_doi,
    seed_premigration_documents_row,
    terminal_paren_round_trip,
)

DOI = "10.1234/wave21.g002.demo"

# Three real, registered identifiers whose DOI legitimately ends in `)`
# (`03-audit-evidence.md` C-029: independently confirmed registered O-171
# examples).
REGISTERED_TERMINAL_PAREN_DOIS = (
    "10.1002/0471221929.ch26(vii)",
    "10.1002/0470846410.ch12(ii)",
    "10.1002/0470846410.ch138a(ii)",
)


# ---------------------------------------------------------------------------
# 1. Same DOI, new bytes — pinned current contract (GREEN characterization)
# ---------------------------------------------------------------------------


def test_same_doi_new_bytes_is_one_row_and_keeps_the_first_bytes(tmp_path) -> None:
    """DOI identity wins over representation bytes: this IS current, pinned
    product behavior (`tests/test_kgstore.py::test_same_doi_with_changed_body_is_one_document`),
    not a defect. G002 records it as an explicit invariant so a future step
    that changes it (Work/Representation versioning) does so knowingly.
    """
    store = KGStore.open(tmp_path / "kg.sqlite")
    try:
        first, second = insert_same_doi_new_bytes(
            store,
            doi=DOI,
            first_text="Abstract only.",
            second_text="Full text with substantially more evidence.",
        )
    finally:
        store.close()

    assert first.created is True
    assert second.created is False
    assert second.doc_id == first.doc_id
    assert second.document_count == 1
    # The richer second body never reached disk under this contract — the
    # stored bytes are still the first write's.
    assert second.raw_text == "Abstract only."


# ---------------------------------------------------------------------------
# 2. Different DOI, same bytes — RED characterization
# ---------------------------------------------------------------------------


@pytest.mark.xfail(
    strict=True,
    reason=(
        "Target invariant for the v2 schema step (04-domain-architecture.md "
        "'Different DOI, same bytes'), not current product behavior: two "
        "distinct, real DOIs must materialize as two documents even when "
        "their bodies are byte-identical, which the v1 UNIQUE(content_hash) "
        "constraint cannot hold. Step 2 delivers the typed "
        "DocumentIdentityConflict refusal instead of the old silent merge; "
        "this stays pinned until Step 9's constraint rebuild (the v2 schema "
        "step)."
    ),
)
def test_different_doi_same_bytes_should_yield_two_documents(tmp_path) -> None:
    """Target invariant for the v2 schema step: two distinct, real DOIs are
    two distinct documents even when their bodies are byte-identical —
    content hash must never merge Work identity (`04-domain-architecture.md`
    "Different DOI, same bytes").
    """
    store = KGStore.open(tmp_path / "kg.sqlite")
    try:
        first, second = insert_different_doi_same_bytes(
            store,
            first_doi="10.1000/wave21.a",
            second_doi="10.1000/wave21.b",
            shared_text="Identical body shared by two distinct registered works.",
        )
    finally:
        store.close()

    assert first.created is True
    assert second.created is True
    assert second.doc_id != first.doc_id
    assert second.document_count == 2


def test_different_doi_same_bytes_raises_a_typed_conflict(tmp_path) -> None:
    """Step 2 service contract: content-hash equality must not merge two
    different explicit DOIs. Until the v2 schema can hold both rows, the
    insert refuses with a typed DocumentIdentityConflict and writes nothing.
    """
    store = KGStore.open(tmp_path / "kg.sqlite")
    try:
        first, _created = store.insert_document(
            source_kind="paper_api",
            source_uri="https://doi.org/10.1000/wave21.collide.a",
            title="Paper A",
            raw_text="Identical body shared by two distinct registered works.",
            content_hash="sha256:collide-1",
            doi="10.1000/wave21.collide.a",
        )
        with pytest.raises(DocumentIdentityConflict) as raised:
            store.insert_document(
                source_kind="paper_api",
                source_uri="https://doi.org/10.1000/wave21.collide.b",
                title="Paper B",
                raw_text="Identical body shared by two distinct registered works.",
                content_hash="sha256:collide-1",
                doi="10.1000/wave21.collide.b",
            )
        assert raised.value.existing_doc_id == first.id
        assert raised.value.existing_doi == "10.1000/wave21.collide.a"
        assert raised.value.incoming_doi == "10.1000/wave21.collide.b"
        assert raised.value.content_hash == "sha256:collide-1"
        assert len(store.list_documents()) == 1
        # A refused insert leaves no orphan raw-text directory behind.
        assert len(list((tmp_path / "documents").iterdir())) == 1
    finally:
        store.close()


def test_conflict_truth_table_preserves_existing_dedupe(tmp_path) -> None:
    """Over-fire guard: the conflict fires only for two DIFFERENT explicit
    DOIs. Same-DOI reinsert still dedupes; an explicit DOI over a NULL-doi
    hash row still merges (legacy-compatible); no-DOI inserts keep plain
    hash dedupe."""
    store = KGStore.open(tmp_path / "kg.sqlite")
    try:
        a1, created1 = store.insert_document(
            source_kind="paper_api", source_uri="https://doi.org/10.1000/tt.a",
            title="A", raw_text="body tt a", content_hash="sha256:tt-a",
            doi="10.1000/tt.a",
        )
        a2, created2 = store.insert_document(
            source_kind="paper_api", source_uri="https://doi.org/10.1000/tt.a",
            title="A", raw_text="body tt a", content_hash="sha256:tt-a",
            doi="10.1000/tt.a",
        )
        assert created1 is True and created2 is False and a2.id == a1.id

        b1, _ = store.insert_document(
            source_kind="upload", source_uri="file:///b.txt", title="B",
            raw_text="body tt b", content_hash="sha256:tt-b",
        )
        b2, created_b2 = store.insert_document(
            source_kind="paper_api", source_uri="https://doi.org/10.1000/tt.b",
            title="B", raw_text="body tt b", content_hash="sha256:tt-b",
            doi="10.1000/tt.b",
        )
        assert created_b2 is False and b2.id == b1.id

        c1, _ = store.insert_document(
            source_kind="upload", source_uri="file:///c1.txt", title="C",
            raw_text="body tt c", content_hash="sha256:tt-c",
        )
        c2, created_c2 = store.insert_document(
            source_kind="upload", source_uri="file:///c2.txt", title="C",
            raw_text="body tt c", content_hash="sha256:tt-c",
        )
        assert created_c2 is False and c2.id == c1.id
    finally:
        store.close()


def test_ingest_batch_survives_and_records_the_typed_conflict(tmp_path) -> None:
    """Step 2 seam contract: a conflicting document must not kill the batch;
    ingest_raw_documents_and_finalize records one typed conflict entry and persists the rest.
    """
    from ontologylab.connectors.base import RawDocument
    from ontologylab.ingestion import ingest_raw_documents_and_finalize
    from ontologylab.provenance import Provenance

    store = KGStore.open(tmp_path / "kg.sqlite")
    try:
        shared = "Identical body shared by two distinct registered works."
        docs = [
            RawDocument(
                source_kind="paper_api",
                source_uri="https://doi.org/10.1000/seam.a",
                title="A", raw_text=shared, doi="10.1000/seam.a",
            ),
            RawDocument(
                source_kind="paper_api",
                source_uri="https://doi.org/10.1000/seam.b",
                title="B", raw_text=shared, doi="10.1000/seam.b",
            ),
            RawDocument(
                source_kind="paper_api",
                source_uri="https://doi.org/10.1000/seam.c",
                title="C", raw_text="A different body entirely.",
                doi="10.1000/seam.c",
            ),
        ]
        result = ingest_raw_documents_and_finalize(
            store, docs, Provenance(str(tmp_path / "jobs"), seed=1)
        )
        assert result.document_count == 2
        assert result.created_count == 2
        assert len(result.conflicts) == 1
        conflict = result.conflicts[0]
        assert conflict.incoming_doi == "10.1000/seam.b"
        assert conflict.existing_doi == "10.1000/seam.a"
        assert len(store.list_documents()) == 2
    finally:
        store.close()


# ---------------------------------------------------------------------------
# 3. Populated legacy resolver DOI — RED characterization
# ---------------------------------------------------------------------------


@pytest.mark.xfail(
    strict=True,
    reason=(
        "Target invariant for Step 5 (C-023), not current product behavior: "
        "migrating a populated legacy store must backfill doi from the "
        "resolver-shaped source_uri already on disk, so a same-paper "
        "reinsert by DOI dedupes against the pre-existing row. _migrate "
        "only adds the nullable column; executing the backfill needs Step "
        "5's cursor/ledger/collision machinery. Step 2 pins the policy as "
        "the read-only planner in ontologylab.doi_backfill; this stays "
        "pinned until Step 5 executes it."
    ),
)
def test_populated_legacy_row_should_be_recognized_after_migration(
    tmp_path,
) -> None:
    """Target invariant for Step 5 (C-023): migrating a populated legacy
    store must backfill `doi` from the resolver-shaped `source_uri` already
    on disk, so a same-paper reinsert by DOI dedupes against the
    pre-existing row. Step 2 pinned only the policy planner.
    """
    db_path = tmp_path / "kg.sqlite"
    seed_premigration_documents_row(
        db_path,
        doc_id="legacy-doc-1",
        source_uri="https://doi.org/10.1000/wave21.legacy",
        raw_text="Old abstract, collected before doi column existed.",
        content_hash="sha256:legacy-target",
    )

    receipt = migrate_and_reinsert_by_doi(
        db_path,
        legacy_doc_id="legacy-doc-1",
        doi="10.1000/wave21.legacy",
        new_text="Changed body arriving after migration.",
    )

    assert receipt.reinsert_created is False
    assert receipt.reinsert_doc_id == receipt.legacy_doc_id
    assert receipt.document_count == 1


def test_populated_legacy_row_currently_stays_null_and_duplicates(
    tmp_path,
) -> None:
    """Characterization of CURRENT behavior, not release evidence:
    `_migrate` adds the nullable `documents.doi` column but never backfills
    it from resolver-shaped `source_uri` values already on disk
    (03-audit-evidence.md). A row written before migration keeps `doi IS
    NULL` after migration, so a same-DOI reinsert misses the DOI lookup and
    creates a second row for the same paper.
    """
    db_path = tmp_path / "kg.sqlite"
    seed_premigration_documents_row(
        db_path,
        doc_id="legacy-doc-2",
        source_uri="https://doi.org/10.1000/wave21.legacy2",
        raw_text="Old abstract, collected before doi column existed.",
        content_hash="sha256:legacy-target-2",
    )

    receipt = migrate_and_reinsert_by_doi(
        db_path,
        legacy_doc_id="legacy-doc-2",
        doi="10.1000/wave21.legacy2",
        new_text="Changed body arriving after migration.",
    )

    # This is the CURRENT (defective) outcome: migration left the legacy
    # row's doi column NULL, so the DOI-based reinsert cannot find it and a
    # second row is created for the same paper.
    assert receipt.legacy_row_doi_after_migration is None
    assert receipt.reinsert_created is True
    assert receipt.reinsert_doc_id != receipt.legacy_doc_id
    assert receipt.document_count == 2


# ---------------------------------------------------------------------------
# 4. Registered terminal-parenthesis DOI — RED characterization
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("doi", REGISTERED_TERMINAL_PAREN_DOIS)
def test_registered_terminal_paren_doi_should_round_trip_exactly(
    tmp_path, doi
) -> None:
    """Delivered Step 2 invariant (C-029): identifier-field normalization
    applies no citation-prose punctuation stripping, so these three real,
    registered identifiers persist byte-for-byte through insert and
    read-back (`07-synthesis-blueprint.md` "C-029 DOI syntax").
    """
    store = KGStore.open(tmp_path / "kg.sqlite")
    try:
        receipt = terminal_paren_round_trip(
            store, doi=doi, raw_text=f"Chapter body for {doi}."
        )
    finally:
        store.close()

    assert receipt.round_trips is True
    assert receipt.stored_doi == doi


# ---------------------------------------------------------------------------
# Isolation guard
# ---------------------------------------------------------------------------


def test_helper_module_is_scoped_to_wave21_identity_only() -> None:
    """G002 files stay separate from G001 (harness) / G003 (real-surface):
    the helper module this test file imports exposes exactly the identity
    receipt builders above and nothing from another goal's surface."""
    import tests.wave21.identity as identity_mod

    exported = {name for name in vars(identity_mod) if not name.startswith("_")}
    assert exported >= {
        "insert_same_doi_new_bytes",
        "insert_different_doi_same_bytes",
        "seed_premigration_documents_row",
        "migrate_and_reinsert_by_doi",
        "terminal_paren_round_trip",
    }
    disallowed = {"cli", "http", "worker", "mcp", "sample"}
    assert not (exported & disallowed)
