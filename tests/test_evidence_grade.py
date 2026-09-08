"""A reviewer judging a claim needs to know who checked the paper first.

Approving a proposal means deciding whether the source supports it, and
that decision changes depending on whether anyone reviewed the source. The
store could not tell: thirteen of the first twenty-three documents recorded
`doi.org` as their host, which names neither the source that found them nor
whether it was peer reviewed.

The design that suggests itself — map source to grade — was measured
against the live APIs and is wrong for most documents. Crossref, asked for
four BRCA1/PARP works, returned two `report`, one `book-chapter` and one
`posted-content`; no journal article at all. Europe PMC returns `MED` and
`PPR` rows in the same result list. So the grade is read off the record,
and the source is only a fallback for the servers that hold exactly one
kind of thing.
"""

from __future__ import annotations

import pytest

from ontologylab import evidence


# --------------------------------------------------------------------------
# What a source guarantees, and what it does not
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "source, grade",
    [
        ("arxiv", evidence.PREPRINT),
        ("biorxiv", evidence.PREPRINT),
        ("medrxiv", evidence.PREPRINT),
        ("clinicaltrials", evidence.REGISTRATION),
        ("elsevier", evidence.PEER_REVIEWED),
        ("springer", evidence.PEER_REVIEWED),
    ],
)
def test_a_single_purpose_source_settles_the_grade(source, grade) -> None:
    """These servers hold one kind of record by construction."""
    assert evidence.grade_from_source(source) == grade


@pytest.mark.parametrize(
    "source", ["crossref", "openalex", "semanticscholar", "europepmc",
               "core", "searxng"],
)
def test_an_aggregator_alone_settles_nothing(source) -> None:
    """The load-bearing one.

    Every aggregator returns a mixture, so a source-to-grade map would
    label the majority of documents wrong — and confidently. `unknown` is
    the honest value until the record itself says otherwise.
    """
    assert evidence.grade_from_source(source) == evidence.UNKNOWN


# --------------------------------------------------------------------------
# What the record says
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "record_type, grade",
    [
        ("journal-article", evidence.PEER_REVIEWED),
        # What Crossref calls a preprint. bioRxiv and medRxiv both register
        # their DOIs this way, so this is how a preprint arrives without
        # ever naming a preprint server.
        ("posted-content", evidence.PREPRINT),
        ("book-chapter", evidence.OTHER),
        ("report", evidence.OTHER),
    ],
)
def test_crossref_type_decides(record_type, grade) -> None:
    assert evidence.grade_from_record(
        "crossref", {"type": record_type}
    ) == grade


@pytest.mark.parametrize(
    "record, grade",
    [
        ({"source": "MED"}, evidence.PEER_REVIEWED),
        ({"source": "PPR"}, evidence.PREPRINT),
        ({"source": "NBK"}, evidence.OTHER),
        # `source` is a controlled code and `pubType` is free text, so the
        # code wins; the text is only consulted when the code is unknown.
        ({"source": "ZZZ", "pubType": "preprint"}, evidence.PREPRINT),
        ({"source": "MED", "pubType": "preprint"}, evidence.PEER_REVIEWED),
    ],
)
def test_europepmc_states_it_in_the_record(record, grade) -> None:
    assert evidence.grade_from_record("europepmc", record) == grade


def test_openalex_type_decides() -> None:
    assert evidence.grade_from_record(
        "openalex", {"type": "preprint"}
    ) == evidence.PREPRINT
    assert evidence.grade_from_record(
        "openalex", {"type": "article"}
    ) == evidence.PEER_REVIEWED


def test_a_record_with_no_type_falls_back_to_the_source() -> None:
    """A field the API did not return must not become a wrong claim."""
    assert evidence.grade_from_record("crossref", {}) == evidence.UNKNOWN
    assert evidence.grade_from_record("arxiv", {}) == evidence.PREPRINT
    assert evidence.grade_from_record("crossref", None) == evidence.UNKNOWN


def test_an_unrecognised_type_is_unknown_not_a_guess() -> None:
    assert evidence.grade_from_record(
        "crossref", {"type": "something-new"}
    ) == evidence.UNKNOWN


def test_a_stored_value_this_build_does_not_know_is_normalized() -> None:
    """Documents predate the column and read back empty; a stray value
    would otherwise reach the browser and render as a raw string next to
    real grades."""
    assert evidence.normalize("") == evidence.UNKNOWN
    assert evidence.normalize(None) == evidence.UNKNOWN
    assert evidence.normalize("nonsense") == evidence.UNKNOWN
    assert evidence.normalize(evidence.PREPRINT) == evidence.PREPRINT


# --------------------------------------------------------------------------
# Through the store, to the reviewer
# --------------------------------------------------------------------------


def _seeded(tmp_path, *, source: str, grade: str):
    from ontologylab.kgstore import KGStore
    from ontologylab.models import ProposedEntity, SourceSpan

    store = KGStore.open(tmp_path / "kg.sqlite")
    doc, _ = store.insert_document(
        source_kind="paper_api", source_uri="https://doi.org/10.1/x",
        title="a paper", raw_text="TP53 is a tumor suppressor.",
        content_hash="h", source=source, evidence_grade=grade,
    )
    store.insert_proposed(
        [ProposedEntity(id="e1", entity_type="Concept", name="TP53",
                        confidence=0.9, source_span=SourceSpan(0, 4))],
        [], source_doc_id=doc.id, extractor_engine="mock",
        extractor_model=None, prompt_version="v1",
    )
    return store


def test_the_grade_survives_a_round_trip(tmp_path) -> None:
    store = _seeded(tmp_path, source="arxiv", grade=evidence.PREPRINT)

    doc = store.list_documents()[0]

    assert doc.source == "arxiv"
    assert doc.evidence_grade == evidence.PREPRINT
    store.close()


def test_the_review_queue_carries_it(tmp_path) -> None:
    """The whole point. A reviewer sees the excerpt; the grade has to be
    beside it, not one screen away."""
    store = _seeded(tmp_path, source="arxiv", grade=evidence.PREPRINT)

    row = store.pending_review(kind="node")[0]

    assert row["evidence_grade"] == evidence.PREPRINT
    assert row["doc_source"] == "arxiv"
    assert row["excerpt"], "the excerpt still arrives"
    store.close()


def test_a_document_collected_before_this_existed_reads_as_unknown(
    tmp_path,
) -> None:
    """Old rows have no source and no grade. `unknown` is the truthful
    answer for a document nobody recorded the origin of — inventing
    `peer_reviewed` would be worse than saying nothing."""
    store = _seeded(tmp_path, source="", grade="")

    row = store.pending_review(kind="node")[0]

    assert row["evidence_grade"] == evidence.UNKNOWN
    store.close()


def test_an_existing_store_gains_the_columns(tmp_path) -> None:
    """The migration runs on an already-created database.

    Every install has documents from before this change; failing to open
    them would be worse than not having the grade at all.
    """
    import sqlite3

    from ontologylab.kgstore import KGStore

    path = tmp_path / "kg.sqlite"
    store = KGStore.open(path)
    store.close()
    # Drop back to the pre-change shape.
    conn = sqlite3.connect(path)
    conn.execute("ALTER TABLE documents DROP COLUMN evidence_grade")
    conn.execute("ALTER TABLE documents DROP COLUMN source")
    conn.commit()
    conn.close()

    reopened = KGStore.open(path)
    columns = {
        r["name"] for r in reopened.conn.execute("PRAGMA table_info(documents)")
    }

    assert {"source", "evidence_grade"} <= columns
    reopened.close()


# --------------------------------------------------------------------------
# On screen
# --------------------------------------------------------------------------


def test_every_grade_has_words_the_reviewer_can_read() -> None:
    """A grade the browser has no phrase for renders as its raw slug."""
    from ontologylab import web_assets

    script = web_assets.read_asset_text("app.js")
    labels = script.split("var GRADE_KO = {", 1)[1].split("};", 1)[0]

    missing = [g for g in evidence.GRADES if f"{g}:" not in labels]
    assert not missing, f"no Korean for: {missing}"


def test_the_badge_is_drawn_beside_the_excerpt() -> None:
    """One screen away is not beside. The reviewer decides while looking at
    the sentence, so the grade has to be in that field of view."""
    from ontologylab import web_assets

    script = web_assets.read_asset_text("app.js")
    source_line = script.split("class='ev-source muted'", 1)[1][:200]

    assert "evidenceBadge(item)" in source_line


def test_shared_ingestion_preserves_identity_evidence_and_provenance(tmp_path) -> None:
    """The application seam proves behavior, not which helper callers name."""
    import json

    from ontologylab.connectors.base import RawDocument
    from ontologylab.ingestion import ingest_raw_documents_and_finalize
    from ontologylab.kgstore import KGStore
    from ontologylab.provenance import Provenance

    store = KGStore.open(tmp_path / "kg.sqlite")
    provenance = Provenance(str(tmp_path / "run"), seed=0)
    raw = RawDocument(
        source_kind="paper_api",
        source_uri="https://doi.org/10.1/shared",
        title="Shared seam",
        raw_text="Evidence text.",
        doi="10.1/shared",
        source="crossref",
        evidence_grade=evidence.PEER_REVIEWED,
    )

    result = ingest_raw_documents_and_finalize(store, [raw], provenance)

    [stored] = store.list_documents()
    events = [
        json.loads(line)
        for line in provenance.jsonl_path.read_text(encoding="utf-8").splitlines()
    ]
    assert result.created_count == 1
    assert stored.source == "crossref"
    assert stored.evidence_grade == evidence.PEER_REVIEWED
    assert stored.doi == "10.1/shared"
    assert [event["step"] for event in events] == ["collect.doc", "collect.end"]
    assert events[0]["payload"]["doc_id"] == stored.id
    store.close()
