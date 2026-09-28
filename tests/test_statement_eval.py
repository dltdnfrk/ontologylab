"""Independent, hand-counted oracles for the offline receipt scorer."""

from __future__ import annotations

from dataclasses import replace
from hashlib import sha256

import pytest

from ontologylab.statement_eval import (
    AdjudicatedGold, HarnessRun, Paper, Span, SplitLock, SplitManifest, SplitViolation,
    Statement, freeze_split, score_statements, wilson_slice,
)

TEXT = "µ A reduced X; B did not reduce X. A reduced X again."
DOI = "10.5555/new-paper"
HASHES = tuple(
    (name, sha256(name.encode("ascii")).hexdigest())
    for name in (
        "gold", "source-selection", "rules", "prompt", "schema",
        "cue", "qualifier", "completion", "normalization", "scorer",
    )
)


def paper(doi: str = DOI, pmcid: str = "PMC90000000") -> Paper:
    return Paper(doi, pmcid, TEXT, sha256(TEXT.encode("utf-8")).hexdigest())


def span(quote: str, *, occurrence: int = 0) -> Span:
    start = -1
    for _ in range(occurrence + 1):
        start = TEXT.index(quote, start + 1)
    return Span(start, start + len(quote), quote)


def statement(
    row_id: str, *, arm: Span | None = None, result: Span | None = None,
    polarity: str = "supports", qualifier: tuple[tuple[str, str], ...] = (),
    scope: tuple[tuple[str, str], ...] = (), predicate: str = "reduces",
) -> Statement:
    return Statement(
        row_id, DOI, row_id, "A", predicate, "X", polarity,
        qualifier, scope, arm or span("A"), result or span("reduced X"),
    )


def inventory(
    predictions: tuple[Statement, ...], expected: tuple[Statement, ...],
    *, store_edges: tuple[Statement, ...] = (),
) -> tuple[HarnessRun, AdjudicatedGold, SplitLock]:
    source = paper()
    lock = freeze_split(
        SplitManifest(((source, "test"),), HASHES, first_test_open="2026-09-28T00:00:00Z"),
        current_gold_ids=set(),
    )
    return (
        HarnessRun(predictions, (source,), HASHES, store_edges=store_edges),
        AdjudicatedGold(expected, (source,), HASHES[0][1]),
        lock,
    )


def test_exact_qualifiers_do_not_accept_extra_scope() -> None:
    # Given: same triple, polarity and anchors, but an extra prediction atom.
    expected = statement("gold", qualifier=(("dose", "0.1 mg"),))
    predicted = statement(
        "receipt", qualifier=(("dose", "0.1 mg"), ("aspect", "growth")),
    )
    run, gold, lock = inventory((predicted,), (expected,))

    # When: a fully qualified score uses only the receipt.
    score = score_statements(run, gold, lock)

    # Then: one FP and FN, though the shared dose atom is conditionally correct.
    assert (score.statements.tp, score.statements.fp, score.statements.fn) == (0, 1, 1)
    assert (score.qualifiers.tp, score.qualifiers.fp, score.qualifiers.fn) == (1, 1, 0)
    assert (score.units.tp, score.units.fp, score.units.fn) == (1, 0, 0)


def test_two_doses_and_wrong_polarity_count_separately() -> None:
    # Given: first dose matches, second has an opposite polarity.
    dose_1 = (("dose", "0.1 mg"),)
    dose_2 = (("dose", "0.2 mg"),)
    first = statement("g1", qualifier=dose_1, scope=dose_1)
    second = statement("g2", qualifier=dose_2, scope=dose_2)
    predicted = (
        replace(first, row_id="p1"),
        replace(second, row_id="p2", polarity="no_effect"),
    )
    run, gold, lock = inventory(predicted, (first, second))

    # When: exact scope and polarity are scored.
    score = score_statements(run, gold, lock)

    # Then: a wrong polarity is precisely one false positive and one miss.
    assert (score.statements.tp, score.statements.fp, score.statements.fn) == (1, 1, 1)
    assert score.statements.f1 == 0.5
    assert score.per_predicate["reduces"].f1 == 0.5
    assert score.per_paper[DOI].recall == 0.5
    assert score.per_paper_units[DOI].tp == 2
    assert score.per_predicate_units["reduces"].tp == 2
    assert score.ci == "CI = not estimable with 2 independent papers"


def test_augmenting_path_recovers_two_units_greedy_misses() -> None:
    # Given: wide prediction can match either gold arm/result; narrow only g1.
    wide = statement("p1", arm=Span(2, 16, TEXT[2:16]),
                     result=Span(4, 35, TEXT[4:35]))
    narrow = statement("p2", arm=span("A"), result=span("reduced X"))
    g1 = statement("g1")
    g2 = statement("g2", arm=span("B"), result=span("reduce X", occurrence=0))
    run, gold, lock = inventory((wide, narrow), (g1, g2))

    # When: the paper's bipartite graph is matched.
    score = score_statements(run, gold, lock)

    # Then: p1->g2 and p2->g1 give two TPs, not the greedy one.
    assert (score.units.tp, score.units.fp, score.units.fn) == (2, 0, 0)


def test_unrelated_store_edge_never_enters_receipt_score() -> None:
    # Given: a curated/store edge is correct, but this run emitted no receipts.
    source_edge = statement("foreign-edge")
    run, gold, lock = inventory((), (statement("gold"),), store_edges=(source_edge,))

    # When: the run is scored.
    score = score_statements(run, gold, lock)

    # Then: store state cannot manufacture a run TP.
    assert (score.statements.tp, score.statements.fp, score.statements.fn) == (0, 0, 1)
    assert score.statements.precision == "NA"
    assert score.statements.recall == 0


@pytest.mark.parametrize("id_value", [
    "PMC12632097", "PMC12546283", "PMC12563837", "PMC12713700",
    "PMC11298438", "10.1186/s12866-025-04356-y",
    "10.1007/s10340-025-01925-y", "10.3390/genes16101169",
    "10.1002/ps.70214", "10.3389/fmicb.2024.1425392",
])
def test_development_papers_cannot_be_test(id_value: str) -> None:
    # Given: an exposed DOI or PMCID occupies the prospective test role.
    candidate = paper(doi=id_value) if id_value.startswith("10.") else paper(pmcid=id_value)

    # When/Then: freezing refuses it, regardless of the name's casing.
    with pytest.raises(SplitViolation, match="development paper"):
        freeze_split(SplitManifest(((candidate, "test"),), HASHES), current_gold_ids=set())


def test_test_doi_in_exemplar_refuses_split() -> None:
    # Given: a supposedly held-out DOI occurs in a few-shot exemplar.
    manifest = SplitManifest(
        ((paper(), "test"),), HASHES, ("Example sourced from 10.5555/new-paper",),
    )

    # When/Then: the first test look is embargoed.
    with pytest.raises(SplitViolation, match="exemplar"):
        freeze_split(manifest, current_gold_ids=set())


def test_changed_hash_after_first_test_look_invalidates_score() -> None:
    # Given: the frozen prompt differs from the recorded run.
    run, gold, lock = inventory((), ())
    changed = replace(run, hashes=tuple(
        (name, "0" * 64 if name == "prompt" else digest)
        for name, digest in HASHES
    ))

    # When/Then: there is no score.
    with pytest.raises(SplitViolation, match="artifact hash"):
        score_statements(changed, gold, lock)


def test_unicode_character_offsets_and_quote_integrity() -> None:
    # Given: a byte offset would point one character past the result.
    run, gold, lock = inventory(
        (statement("prediction"),), (statement("gold"),),
    )
    bad = replace(run.receipts[0], result=Span(5, 14, TEXT[4:13]))

    # When/Then: the claimed quote does not match source characters.
    with pytest.raises(SplitViolation, match="invalid source span"):
        score_statements(replace(run, receipts=(bad,)), gold, lock)


def test_empty_metrics_and_wilson_descriptive_slice() -> None:
    # Given: no claims in a complete, exhaustive one-paper fixture.
    run, gold, lock = inventory((), ())

    # When: score and descriptive binomial limits are calculated.
    score = score_statements(run, gold, lock)

    # Then: undefined denominators are NA, not perfect scores.
    assert (score.units.precision, score.statements.recall, score.statements.f1) == (
        "NA", "NA", "NA",
    )
    assert wilson_slice(0, 0) is None
    lo, hi = wilson_slice(12, 12) or (None, None)
    assert lo == pytest.approx(0.7575, abs=0.001)
    assert hi == pytest.approx(1)
