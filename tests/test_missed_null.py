"""Null-candidate review starts from exact document text and citation spans."""

from __future__ import annotations

from ontologylab.kgstore import KGStore
from ontologylab.missed_null import missed_null_candidates
from ontologylab.models import ProposedEntity, ProposedRelation, SourceSpan
from ontologylab.schemas import preset


def test_candidate_spans_preserve_unicode_and_show_cited_arms(tmp_path) -> None:
    # Given two source sentences with the same cue, and one cited null edge.
    text = "D. suzukii was ineffective in the field — 1 × 106.\nSpinosad did not reduce oviposition."
    with KGStore.open(tmp_path / "kg.sqlite") as store:
        store.install_schema(**preset("agrochem-v2"))
        doc, _ = store.insert_document(
            source_kind="upload", source_uri="file:///trial.txt", title="Trial",
            raw_text=text, content_hash="sha256:trial-null",
        )
        start = text.index("Spinosad")
        store.insert_proposed(
            [
                ProposedEntity(id="s", entity_type="ActiveIngredient", name="Spinosad"),
                ProposedEntity(id="t", entity_type="Pest", name="Drosophila suzukii"),
            ],
            [ProposedRelation(
                id="edge", relation_type="controls", src_entity_id="s", dst_entity_id="t",
                qualifiers={"polarity": "no_effect"},
                source_span=SourceSpan(start, len(text)),
            )],
            source_doc_id=doc.id, extractor_engine="mock",
        )
        # When the detector examines document-local citations.
        result = missed_null_candidates(store, [doc])

    # Then both sentences remain reviewable; the already cited arm is visible.
    assert [(c.start, c.end, c.text, c.cue, c.status) for c in result] == [
        (0, text.index("\n"), text[:text.index("\n")],
         "ineffective", "unextracted"),
        (text.index("Spinosad"), len(text), text[text.index("Spinosad"):],
         "did not reduce", "partially_extracted"),
    ]
    assert result[0].existing_statements == ()
    assert [(item.edge_id, item.subject, item.polarity)
            for item in result[1].existing_statements] == [
        ("edge", "Spinosad", "no_effect")
    ]


def test_citation_for_another_document_does_not_change_its_status(tmp_path) -> None:
    # Given the same measured-null sentence in two documents, cite only one.
    with KGStore.open(tmp_path / "kg.sqlite") as store:
        store.install_schema(**preset("agrochem-v2"))
        docs = [
            store.insert_document(
                source_kind="upload", source_uri=f"file:///{n}.txt", title=n,
                raw_text="No resistant isolate was observed.",
                content_hash=f"sha256:null-{n}",
            )[0]
            for n in ("first", "second")
        ]
        store.insert_proposed(
            [
                ProposedEntity(id="s", entity_type="ActiveIngredient", name="Agent"),
                ProposedEntity(id="t", entity_type="Pest", name="Isolate"),
            ],
            [ProposedRelation(
                id="r", relation_type="controls", src_entity_id="s", dst_entity_id="t",
                qualifiers={"polarity": "no_effect"}, source_span=SourceSpan(0, 34),
            )],
            source_doc_id=docs[0].id, extractor_engine="mock",
        )
        # When both documents are scanned.
        candidates = missed_null_candidates(store, docs)

    # Then both remain reviewable, but only the cited source shows the edge.
    assert [(c.document_id, c.cue, c.status) for c in candidates] == [
        (docs[0].id, "no resistant isolate", "partially_extracted"),
        (docs[1].id, "no resistant isolate", "unextracted"),
    ]
    assert candidates[0].existing_statements[0].edge_id == "r"
    assert candidates[1].existing_statements == ()


def test_zero_percent_in_a_published_style_outcome_is_reviewable(tmp_path) -> None:
    # Given a zero-control outcome with intervening dose percentages.
    text = (
        "The 1× and 2× treatments resulted in 0%, 4% control of the "
        "resistant population. P. annua had no significant reduction."
    )
    with KGStore.open(tmp_path / "kg.sqlite") as store:
        doc, _ = store.insert_document(
            source_kind="upload", source_uri="file:///result.txt", title="Result",
            raw_text=text, content_hash="sha256:zero-outcome",
        )
        # When source sentences are scanned without extracted null citations.
        rows = missed_null_candidates(store, [doc])

    # Then both exact source spans are presented; abbreviation punctuation
    # does not create a spurious "annua" sentence.
    assert [(row.text, row.cue, text[row.start:row.end]) for row in rows] == [
        (text[:text.index(". ") + 1], "zero measured percent",
         text[:text.index(". ") + 1]),
        (text[text.index(" P. annua") + 1:], "no significant",
         text[text.index(" P. annua") + 1:]),
    ]
