"""Wave 2.1 Step 1 Goal G002 — direct-service ingestion identity
characterization tests.

Scope: `KGStore.insert_document` / `normalize_doi`, called directly (no CLI,
HTTP, worker, or MCP surface — those belong to G003). Every assertion below
reads machine-consumed state back out of sqlite or the filesystem: row
counts, `doi`/`content_hash` columns, ids, and bytes on disk. None of it
asserts prose.

Four scenarios, each traced to the audit report
(`docs/OMO-INGESTION-WAVE-2.1-MASS-ULW-INTEGRATED-ANALYSIS-2026-08-20.md`
and `.omo/mass-ulw/20260820-ingestion-integration/{02-current-code,
03-audit-evidence,07-synthesis-blueprint}.md`):

1. Same DOI / new bytes — a currently GREEN, deliberately-pinned invariant:
   DOI identity wins over representation bytes, so the second write is a
   dedupe hit and the richer text is discarded. This is a Step-1
   characterization of that existing contract, not a defect: Step 2
   (Work/Representation) is the step permitted to change it.

2. Different DOI / same bytes — a currently RED gap (C-029/C-031 family):
   two distinct, real, registered DOIs whose bodies happen to be
   byte-identical collide on the store's `UNIQUE(content_hash)` fallback,
   which the direct-service path exposes as a hard `IntegrityError` on the
   caller rather than two independently-identified documents.

3. Populated legacy resolver DOI — a currently RED gap: `_migrate` adds the
   nullable `doi` column to a pre-existing store without backfilling it from
   already-stored resolver-shaped `source_uri` values, so a row written
   before migration keeps `doi IS NULL` after migration and a same-DOI
   reinsert is not recognized as the same paper.

4. Registered terminal-parenthesis DOI — a currently RED gap (C-029):
   `normalize_doi`'s citation-punctuation `rstrip(".,;)")` also strips the
   trailing `)` off registered identifiers that legitimately end in one
   (e.g. `10.1002/0471221929.ch26(vii)`), silently mutating the DOI that
   gets persisted.

Each RED case is asserted as a named defect receipt (`xfail(strict=True)`,
reason references the audit-report code), never presented as GREEN, per the
G002 evidence contract: a test that passes by reproducing a defect is
characterization metadata, not release evidence.
"""

from __future__ import annotations

import pytest

from ontologylab.kgstore import KGStore
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
        "Target invariant for Step 2 (04-domain-architecture.md 'Different "
        "DOI, same bytes'), not current product behavior: two distinct, "
        "real DOIs must be two distinct documents even when their bodies "
        "are byte-identical, but the content_hash fallback in "
        "insert_document currently merges them (C-029/C-031). This asserts "
        "the target so a Step-2 fix flips it to GREEN, not a defect "
        "reproduction."
    ),
)
def test_different_doi_same_bytes_should_yield_two_documents(tmp_path) -> None:
    """Target invariant for Step 2: two distinct, real DOIs are two distinct
    documents even when their bodies are byte-identical — content hash must
    never merge Work identity (`04-domain-architecture.md` "Different DOI,
    same bytes").
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


def test_different_doi_same_bytes_currently_collapses_to_one_document(
    tmp_path,
) -> None:
    """Characterization of CURRENT behavior (C-029/C-031), not release
    evidence: insert_document's DOI lookup misses (different DOI), then its
    content_hash fallback SELECT matches the first row and returns it as a
    dedupe hit instead of inserting a second document
    (kgstore.py:2009-2014,2062-2069).
    """
    store = KGStore.open(tmp_path / "kg.sqlite")
    try:
        first, second = insert_different_doi_same_bytes(
            store,
            first_doi="10.1000/wave21.collide.a",
            second_doi="10.1000/wave21.collide.b",
            shared_text="Identical body shared by two distinct registered works.",
        )
    finally:
        store.close()

    # This is the CURRENT (defective) outcome: the content-hash fallback
    # treats the second, differently-DOI'd paper as the same document.
    assert second.created is False
    assert second.doc_id == first.doc_id
    assert second.document_count == 1
    # The strongest possible statement of the defect: the row that comes
    # back under the second DOI does not even carry that DOI.
    assert second.doi_column == first.doi_column == "10.1000/wave21.collide.a"


# ---------------------------------------------------------------------------
# 3. Populated legacy resolver DOI — RED characterization
# ---------------------------------------------------------------------------


@pytest.mark.xfail(
    strict=True,
    reason=(
        "Target invariant for Step 2, not current product behavior: "
        "migrating a populated legacy store must backfill doi from the "
        "resolver-shaped source_uri already on disk, so a same-paper "
        "reinsert by DOI dedupes against the pre-existing row. _migrate "
        "currently only adds the nullable column (03-audit-evidence.md). "
        "This asserts the target so a Step-2 backfill fix flips it to "
        "GREEN, not a defect reproduction."
    ),
)
def test_populated_legacy_row_should_be_recognized_after_migration(
    tmp_path,
) -> None:
    """Target invariant for Step 2: migrating a populated legacy store must
    backfill `doi` from the resolver-shaped `source_uri` already on disk, so
    a same-paper reinsert by DOI dedupes against the pre-existing row.
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
@pytest.mark.xfail(
    strict=True,
    reason=(
        "Target invariant for Step 2 (07-synthesis-blueprint.md 'C-029 DOI "
        "syntax'), not current product behavior: identifier-field "
        "normalization must not apply citation-prose punctuation stripping "
        "to a registered DOI, so these three real, registered identifiers "
        "must persist byte-for-byte. normalize_doi's rstrip('.,;)') "
        "currently strips the trailing ')' unconditionally (C-029). This "
        "asserts the target so a Step-2 identifier-field fix flips it to "
        "GREEN, not a defect reproduction."
    ),
)
def test_registered_terminal_paren_doi_should_round_trip_exactly(
    tmp_path, doi
) -> None:
    """Target invariant for Step 2: identifier-field normalization must not
    apply citation-prose punctuation stripping to a registered DOI, so these
    three real, registered identifiers persist byte-for-byte
    (`07-synthesis-blueprint.md` "C-029 DOI syntax").
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


@pytest.mark.parametrize("doi", REGISTERED_TERMINAL_PAREN_DOIS)
def test_registered_terminal_paren_doi_currently_loses_the_paren(
    tmp_path, doi
) -> None:
    """Characterization of CURRENT behavior (C-029/O-171), not release
    evidence: normalize_doi's citation-prose rstrip('.,;)') strips the
    trailing ')' off registered identifiers that legitimately end in one
    (connectors/base.py normalize_doi), so the stored doi column silently
    loses a character of the registered identity.
    """
    store = KGStore.open(tmp_path / "kg.sqlite")
    try:
        receipt = terminal_paren_round_trip(
            store, doi=doi, raw_text=f"Chapter body for {doi}."
        )
    finally:
        store.close()

    # This is the CURRENT (defective) outcome: the registered ')' is gone.
    assert receipt.round_trips is False
    assert receipt.stored_doi == doi[:-1]
    assert receipt.normalized_doi == doi[:-1]


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
