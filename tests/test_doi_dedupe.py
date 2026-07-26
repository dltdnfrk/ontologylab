"""Cross-source identity: one paper from five sources must stay one document.

Fanning out over the paper APIs returns the same work several times. The five
parsers do not agree on the shape of a DOI, and they do not agree on the text
of an abstract, so neither the raw identifier nor `content_hash` can be the
identity. `normalize_doi` supplies the identity and `collapse_duplicates`
picks the winner by a stated rule.

The rule has to be stated rather than incidental: `content_hash` follows
whichever abstract won, so a re-run that picked differently inserts the same
paper a second time and `UNIQUE(content_hash)` cannot see it.
"""

from __future__ import annotations

import json

from ontologylab.connectors.base import (
    RawDocument,
    collapse_duplicates,
    normalize_doi,
)
from ontologylab.connectors.paper_api import (
    SOURCE_ORDER,
    parse_atom,
    parse_crossref,
    parse_europepmc,
    parse_openalex,
    parse_semanticscholar,
)

DOI = "10.1234/nipo.demo.2026"


# --------------------------------------------------------------------------
# normalize_doi
# --------------------------------------------------------------------------


def test_a_bare_doi_survives_unchanged() -> None:
    assert normalize_doi(DOI) == DOI


def test_every_resolver_prefix_is_stripped() -> None:
    for prefix in (
        "https://doi.org/",
        "http://doi.org/",
        "https://dx.doi.org/",
        "http://dx.doi.org/",
        "doi:",
    ):
        assert normalize_doi(prefix + DOI) == DOI, prefix


def test_case_is_folded_because_dois_are_case_insensitive() -> None:
    assert normalize_doi("10.1234/NIPO.Demo.2026") == DOI


def test_trailing_citation_punctuation_is_dropped() -> None:
    for suffix in (".", ",", ";", ")"):
        assert normalize_doi(DOI + suffix) == DOI, suffix


def test_a_value_that_is_not_a_doi_is_refused() -> None:
    # A non-DOI must not become a de-duplication key: two unrelated papers
    # would then collide under it.
    for junk in ("", "   ", "not-a-doi", "https://arxiv.org/abs/2401.00001", None, 42):
        assert normalize_doi(junk) is None, junk


# --------------------------------------------------------------------------
# The five parsers, each with the shape its API actually returns
# --------------------------------------------------------------------------


def test_crossref_returns_a_bare_doi() -> None:
    payload = {
        "message": {
            "items": [
                {
                    "DOI": DOI,
                    "URL": f"https://doi.org/{DOI}",
                    "title": ["A paper"],
                    "abstract": "<jats:p>Body</jats:p>",
                }
            ]
        }
    }
    (doc,) = parse_crossref(json.dumps(payload))
    assert doc.doi == DOI


def test_openalex_returns_a_doi_url_and_is_still_normalized() -> None:
    """OpenAlex is the one source whose DOI does not arrive bare."""
    payload = {
        "results": [
            {
                "doi": f"https://doi.org/{DOI}",
                "id": "https://openalex.org/W123",
                "display_name": "A paper",
                "abstract_inverted_index": {"Body": [0]},
            }
        ]
    }
    (doc,) = parse_openalex(json.dumps(payload))
    assert doc.doi == DOI
    assert doc.source_uri.startswith("https://doi.org/")


def test_semantic_scholar_reads_the_doi_out_of_external_ids() -> None:
    payload = {
        "data": [
            {
                "title": "A paper",
                "abstract": "Body",
                "url": "https://www.semanticscholar.org/paper/abc",
                "externalIds": {"DOI": DOI},
            }
        ]
    }
    (doc,) = parse_semanticscholar(json.dumps(payload))
    assert doc.doi == DOI


def test_europepmc_returns_a_bare_doi() -> None:
    payload = {
        "resultList": {
            "result": [
                {
                    "title": "A paper",
                    "abstractText": "Body",
                    "doi": DOI,
                    "source": "MED",
                    "id": "1",
                }
            ]
        }
    }
    (doc,) = parse_europepmc(json.dumps(payload))
    assert doc.doi == DOI


def test_arxiv_has_no_doi_and_falls_back_to_its_entry_url() -> None:
    xml = """<?xml version="1.0"?>
    <feed xmlns="http://www.w3.org/2005/Atom">
      <entry>
        <title>A paper</title>
        <summary>Body</summary>
        <id>https://arxiv.org/abs/2401.00001v1</id>
      </entry>
    </feed>"""
    (doc,) = parse_atom(xml)
    assert doc.doi is None
    assert doc.dedupe_key == "uri:https://arxiv.org/abs/2401.00001v1"


# --------------------------------------------------------------------------
# Identity
# --------------------------------------------------------------------------


def _doc(text: str, doi: str | None = DOI, uri: str = "https://example/x"):
    return RawDocument(
        source_kind="paper_api",
        source_uri=uri,
        title="A paper",
        raw_text=text,
        doi=doi,
    )


def test_the_same_doi_written_four_ways_is_one_identity() -> None:
    """The four shapes the real sources actually return.

    Calling `normalize_doi` here first made all four inputs the identical
    string before `dedupe_key` ever saw them, so removing normalization from
    the identity path was invisible to this test. The parsers normalize; this
    asserts that they have to.
    """
    forms = (DOI, f"https://doi.org/{DOI}", DOI.upper(), f"doi:{DOI}.")
    assert len({_doc("x", normalize_doi(form)).dedupe_key for form in forms}) == 1
    # And the raw shapes must NOT already agree — otherwise the line above
    # would hold with normalization deleted.
    assert len({_doc("x", form).dedupe_key for form in forms}) > 1


def test_documents_without_a_doi_stay_distinct_from_each_other() -> None:
    a = _doc("x", None, "https://arxiv.org/abs/1")
    b = _doc("x", None, "https://arxiv.org/abs/2")
    assert a.dedupe_key != b.dedupe_key


# --------------------------------------------------------------------------
# The winner rule
# --------------------------------------------------------------------------


def test_the_fullest_abstract_wins() -> None:
    kept = collapse_duplicates(
        [
            ("crossref", [_doc("short")]),
            ("openalex", [_doc("a much longer abstract body")]),
        ],
        SOURCE_ORDER,
    )
    assert len(kept) == 1
    assert kept[0].raw_text == "a much longer abstract body"


def _tagged(source: str):
    """Two candidates of identical length, distinguishable by title.

    Equal length is the point — it forces the tie-break to decide — and the
    title is what makes the decision observable. Comparing the texts instead
    would pass whichever way the tie fell.
    """
    return RawDocument(
        source_kind="paper_api",
        source_uri="https://example/x",
        title=source,
        raw_text="identical length body",
        doi=DOI,
    )


def test_a_tie_is_broken_by_declared_source_order_not_arrival() -> None:
    earlier, later = SOURCE_ORDER[0], SOURCE_ORDER[1]

    forward = collapse_duplicates(
        [(earlier, [_tagged(earlier)]), (later, [_tagged(later)])], SOURCE_ORDER
    )
    reverse = collapse_duplicates(
        [(later, [_tagged(later)]), (earlier, [_tagged(earlier)])], SOURCE_ORDER
    )

    assert len(forward) == len(reverse) == 1
    # The earlier-declared source wins from either arrival order.
    assert forward[0].title == earlier
    assert reverse[0].title == earlier


def test_an_unranked_source_loses_a_tie_to_a_declared_one() -> None:
    declared = SOURCE_ORDER[-1]
    kept = collapse_duplicates(
        [("some-future-source", [_tagged("future")]), (declared, [_tagged(declared)])],
        SOURCE_ORDER,
    )
    assert len(kept) == 1
    assert kept[0].title == declared


def test_five_sources_returning_one_paper_yield_one_document() -> None:
    batches = [(name, [_doc("body " * (i + 1))]) for i, name in enumerate(SOURCE_ORDER)]
    kept = collapse_duplicates(batches, SOURCE_ORDER)
    assert len(kept) == 1


def test_distinct_papers_are_all_kept() -> None:
    batches = [
        ("crossref", [_doc("a", "10.1/a"), _doc("b", "10.1/b")]),
        ("openalex", [_doc("c", "10.1/c")]),
    ]
    assert len(collapse_duplicates(batches, SOURCE_ORDER)) == 3


def test_the_result_is_stable_across_repeated_runs() -> None:
    """The whole point: a second run must not insert the paper again."""
    batches = [
        ("openalex", [_doc("medium length")]),
        ("crossref", [_doc("short")]),
        ("europepmc", [_doc("the longest abstract of the three")]),
    ]
    first = collapse_duplicates(batches, SOURCE_ORDER)
    # Reversed, because passing the same order twice let "first arrival wins"
    # — the precise instability the rule exists to prevent — pass this test.
    again = collapse_duplicates(list(reversed(batches)), SOURCE_ORDER)
    assert [d.content_hash for d in first] == [d.content_hash for d in again]
