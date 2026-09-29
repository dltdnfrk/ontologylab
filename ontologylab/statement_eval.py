"""Offline statement scoring from one run's receipts, never from store edges.

``Paper`` contains a DOI, optional PMCID, unchanged Unicode source text, and
its UTF-8 SHA-256. ``Span`` uses zero-based half-open *character* offsets and
an exact quote. ``Statement`` has stable row and unit IDs, a paper DOI, a
normalized directed triple, polarity, normalized qualifier and explicit
scope key/value pairs, plus separate arm and result spans. An absent scope
axis is absent, not a wildcard. ``HarnessRun`` carries only validated,
persisted proposal/citation receipt statements, paper sources, frozen
pipeline hashes, and a completion flag. Optional ``store_edges`` are an
untrusted diagnostic snapshot and must never enter scoring. ``AdjudicatedGold``
carries exhaustive human statements and an independently hashed gold artifact. ``SplitManifest``
records prospective paper roles, pipeline/gold hashes, exemplar contents,
and an optional first-test-open timestamp; ``SplitLock`` freezes those facts.

The caller supplies independently adjudicated, exhaustive held-out gold.
Historical partial gold and model-silver annotations cannot establish a
precision denominator. CI is not estimable for fewer than 20 papers.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, replace
from hashlib import sha256
from math import sqrt
from typing import Final

from ontologylab.kgstore_base import normalize_name
from ontologylab.statement_qualifiers import normalize_statement_value

DEV_PAPERS: Final = frozenset({
    "PMC12632097", "PMC12546283", "PMC12563837", "PMC12713700",
    "PMC11298438", "10.1186/s12866-025-04356-y",
    "10.1007/s10340-025-01925-y", "10.3390/genes16101169",
    "10.1002/ps.70214", "10.3389/fmicb.2024.1425392",
})
CI_SMALL: Final = "CI = not estimable with 2 independent papers"
FROZEN_ARTIFACTS: Final = frozenset({
    "gold", "source-selection", "rules", "prompt", "schema",
    "cue", "qualifier", "completion", "normalization", "scorer",
})
RUN_ARTIFACTS: Final = frozenset({
    "rules", "cue", "prompt", "schema",
    "qualifier", "normalization", "completion",
})


class SplitViolation(ValueError):
    """A source, prompt, gold, or partition breached the frozen test lock."""


@dataclass(frozen=True, slots=True)
class Paper:
    doi: str
    pmcid: str
    text: str
    source_sha256: str


@dataclass(frozen=True, slots=True)
class Span:
    start: int
    end: int
    quote: str


@dataclass(frozen=True, slots=True)
class Statement:
    row_id: str
    paper_doi: str
    unit_id: str
    subject: str
    predicate: str
    object_name: str
    polarity: str
    qualifiers: tuple[tuple[str, str], ...]
    scope: tuple[tuple[str, str], ...]
    arm: Span
    result: Span


@dataclass(frozen=True, slots=True)
class SplitManifest:
    papers: tuple[tuple[Paper, str], ...]  # role: "development" or "test"
    hashes: tuple[tuple[str, str], ...]  # gold, selection, rules, prompt, etc.
    exemplars: tuple[str, ...] = ()
    first_test_open: str | None = None


@dataclass(frozen=True, slots=True)
class SplitLock:
    papers: tuple[tuple[Paper, str], ...]
    hashes: tuple[tuple[str, str], ...]
    first_test_open: str | None


@dataclass(frozen=True, slots=True)
class HarnessRun:
    receipts: tuple[Statement, ...]
    papers: tuple[Paper, ...]
    hashes: tuple[tuple[str, str], ...]
    complete: bool = True
    store_edges: tuple[Statement, ...] = ()


@dataclass(frozen=True, slots=True)
class AdjudicatedGold:
    statements: tuple[Statement, ...]
    papers: tuple[Paper, ...]
    gold_sha256: str
    exhaustive: bool = True


@dataclass(frozen=True, slots=True)
class Metrics:
    tp: int
    fp: int
    fn: int
    precision: float | str
    recall: float | str
    f1: float | str


@dataclass(frozen=True, slots=True)
class StatementScore:
    units: Metrics
    statements: Metrics
    qualifiers: Metrics  # conditional on paired core/scope/polarity
    per_paper: dict[str, Metrics]
    per_predicate: dict[str, Metrics]
    per_paper_units: dict[str, Metrics]
    per_predicate_units: dict[str, Metrics]
    ci: str


def _identity(paper: Paper) -> str:
    return paper.doi.strip().casefold()


def _check_paper(paper: Paper) -> None:
    if sha256(paper.text.encode("utf-8")).hexdigest() != paper.source_sha256:
        raise SplitViolation(f"source hash mismatch: {paper.doi}")


def freeze_split(
    manifest: SplitManifest, *, current_gold_ids: set[str],
) -> SplitLock:
    """Freeze prospective roles and all supplied artifact hashes before test look."""
    ids = [_identity(p) for p, _ in manifest.papers]
    if len(ids) != len(set(ids)) or not ids:
        raise SplitViolation("duplicate or empty paper selection")
    hashes = dict(manifest.hashes)
    if (len(hashes) != len(manifest.hashes)
            or not FROZEN_ARTIFACTS <= hashes.keys()
            or any(len(value) != 64 or any(char not in "0123456789abcdef" for char in value)
                   for value in hashes.values())):
        raise SplitViolation("missing or duplicate frozen artifact hashes")
    embargo = {key.casefold() for key in DEV_PAPERS | current_gold_ids}
    tests = [p for p, role in manifest.papers if role == "test"]
    if not tests or any(role not in {"test", "development"} for _, role in manifest.papers):
        raise SplitViolation("test papers and valid roles required")
    for paper, role in manifest.papers:
        _check_paper(paper)
        if role == "test" and ({_identity(paper), paper.pmcid.casefold()} & embargo):
            raise SplitViolation(f"development paper assigned to test: {paper.doi}")
    for paper in tests:
        if any(_identity(paper) in exemplar.casefold()
               or (paper.pmcid and paper.pmcid.casefold() in exemplar.casefold())
               for exemplar in manifest.exemplars):
            raise SplitViolation(f"test paper appears in exemplar: {paper.doi}")
    return SplitLock(manifest.papers, manifest.hashes, manifest.first_test_open)


def _span_ok(span: Span, text: str) -> bool:
    return (type(span.start) is int and type(span.end) is int
            and 0 <= span.start < span.end <= len(text)
            and bool(span.quote) and text[span.start:span.end] == span.quote)


def _pairs(rows: tuple[tuple[str, str], ...]) -> tuple[tuple[str, str], ...]:
    if len({key for key, _ in rows}) != len(rows):
        raise SplitViolation("duplicate qualifier or scope key")
    return tuple(sorted((key, normalize_statement_value(key, value)) for key, value in rows))


def _overlap(a: Span, b: Span) -> int:
    return max(0, min(a.end, b.end) - max(a.start, b.start))


def _core(a: Statement, b: Statement) -> bool:
    return (normalize_name(a.subject) == normalize_name(b.subject)
            and a.predicate == b.predicate
            and normalize_name(a.object_name) == normalize_name(b.object_name)
            and a.polarity == b.polarity
            and _pairs(a.scope) == _pairs(b.scope))


def _anchors(a: Statement, b: Statement) -> bool:
    return _overlap(a.arm, b.arm) > 0 and _overlap(a.result, b.result) > 0


def _matching(
    predictions: list[Statement], gold: list[Statement], *,
    mode: str,
) -> list[tuple[int, int]]:
    """Maximum cardinality, then maximum overlap, then stable ID order.

    Unit pairing tests arm/result only; statement pairing also requires exact
    core, polarity, scope, and qualifier atoms. Residual shortest augmenting
    paths maximize weight at each cardinality without a greedy first-fit.
    """
    n, m = len(predictions), len(gold)
    graph: list[list[list[int]]] = [[] for _ in range(n + m + 2)]
    source, sink = n + m, n + m + 1

    def edge(u: int, v: int, cost: int) -> None:
        graph[u].append([v, len(graph[v]), 1, cost])
        graph[v].append([u, len(graph[u]) - 1, 0, -cost])

    for i in range(n):
        edge(source, i, 0)
    for j in range(m):
        edge(n + j, sink, 0)
    for i, predicted in enumerate(predictions):
        for j, expected in enumerate(gold):
            if not _anchors(predicted, expected):
                continue
            if mode == "statement" and (
                not _core(predicted, expected)
                or _pairs(predicted.qualifiers) != _pairs(expected.qualifiers)
            ):
                continue
            overlap = _overlap(predicted.arm, expected.arm) + _overlap(
                predicted.result, expected.result,
            )
            edge(i, n + j, -(
                overlap * (n + 1) ** 2 * (m + 1) ** 2
                + (n - i) * (m + 1) + m - j
            ))
    size = len(graph)
    while True:
        distance: list[int | None] = [None] * size
        previous: list[tuple[int, int] | None] = [None] * size
        distance[source] = 0
        for _ in range(size - 1):
            changed = False
            for u in range(size):
                base = distance[u]
                if base is None:
                    continue
                for index, (v, _, capacity, cost) in enumerate(graph[u]):
                    candidate = base + cost
                    prior = distance[v]
                    if capacity and (prior is None or candidate < prior):
                        distance[v], previous[v] = candidate, (u, index)
                        changed = True
            if not changed:
                break
        if previous[sink] is None:
            break
        v = sink
        while v != source:
            step = previous[v]
            assert step is not None
            u, index = step
            forward = graph[u][index]
            forward[2] = 0
            graph[v][forward[1]][2] = 1
            v = u
    return [(i, arc[0] - n) for i in range(n)
            for arc in graph[i] if n <= arc[0] < n + m and arc[2] == 0]


def _metrics(tp: int, predicted: int, expected: int) -> Metrics:
    fp, fn = predicted - tp, expected - tp
    return Metrics(
        tp, fp, fn,
        tp / predicted if predicted else "NA",
        tp / expected if expected else "NA",
        2 * tp / (predicted + expected) if predicted + expected else "NA",
    )


def score_statements(
    run: HarnessRun, gold: AdjudicatedGold, lock: SplitLock,
) -> StatementScore:
    """Score complete run receipts against source-verified exhaustive test gold."""
    locked = {_identity(p): p for p, role in lock.papers if role == "test"}
    if not run.complete or not gold.exhaustive:
        raise SplitViolation("incomplete run or non-exhaustive human gold")
    frozen = dict(lock.hashes)
    recorded = dict(run.hashes)
    if (len(recorded) != len(run.hashes) or set(recorded) != RUN_ARTIFACTS
            or any(recorded[key] != frozen.get(key) for key in RUN_ARTIFACTS)
            or gold.gold_sha256 != frozen.get("gold")):
        raise SplitViolation("artifact hash changed after split freeze/test look")
    for papers in (run.papers, gold.papers):
        if {_identity(p) for p in papers} != set(locked):
            raise SplitViolation("test paper set changed")
        for paper in papers:
            _check_paper(paper)
            if paper != locked[_identity(paper)]:
                raise SplitViolation("source changed after split freeze/test look")
    for row in (*run.receipts, *gold.statements):
        paper = locked.get(row.paper_doi.casefold())
        if paper is None or not _span_ok(row.arm, paper.text) or not _span_ok(
            row.result, paper.text,
        ):
            raise SplitViolation(f"unknown paper or invalid source span: {row.row_id}")
        _pairs(row.scope)
        _pairs(row.qualifiers)
    if (len({r.row_id for r in run.receipts}) != len(run.receipts)
            or len({r.row_id for r in gold.statements}) != len(gold.statements)):
        raise SplitViolation("duplicate receipt or gold row ID")

    by_paper: dict[str, Metrics] = {}
    by_paper_units: dict[str, Metrics] = {}
    predicate_counts: dict[str, list[int]] = defaultdict(lambda: [0, 0, 0])
    predicate_units: dict[str, list[int]] = defaultdict(lambda: [0, 0, 0])
    totals = [0, 0, 0, 0, 0, 0]
    atom_counts = [0, 0, 0]
    for doi in sorted(locked):
        predicted = sorted(
            (r for r in run.receipts if r.paper_doi.casefold() == doi),
            key=lambda r: r.row_id,
        )
        expected = sorted(
            (r for r in gold.statements if r.paper_doi.casefold() == doi),
            key=lambda r: r.row_id,
        )
        unit_pairs = _matching(predicted, expected, mode="unit")
        statement_pairs = _matching(predicted, expected, mode="statement")
        by_paper[doi] = _metrics(len(statement_pairs), len(predicted), len(expected))
        by_paper_units[doi] = _metrics(len(unit_pairs), len(predicted), len(expected))
        for offset, matches in ((0, unit_pairs), (3, statement_pairs)):
            totals[offset] += len(matches)
            totals[offset + 1] += len(predicted)
            totals[offset + 2] += len(expected)
        for r in predicted:
            predicate_counts[r.predicate][1] += 1
            predicate_units[r.predicate][1] += 1
        for r in expected:
            predicate_counts[r.predicate][2] += 1
            predicate_units[r.predicate][2] += 1
        for i, j in statement_pairs:
            predicate_counts[expected[j].predicate][0] += 1
        for predicate in {r.predicate for r in (*predicted, *expected)}:
            predicate_units[predicate][0] += len(_matching(
                [r for r in predicted if r.predicate == predicate],
                [r for r in expected if r.predicate == predicate],
                mode="unit",
            ))
        # Conditional atoms pair by correct core and evidence, not qualifier.
        core_pairs = _matching_core(predicted, expected)
        for i, j in core_pairs:
            left, right = set(_pairs(predicted[i].qualifiers)), set(_pairs(expected[j].qualifiers))
            atom_counts[0] += len(left & right)
            atom_counts[1] += len(left)
            atom_counts[2] += len(right)
    return StatementScore(
        _metrics(*totals[:3]),
        _metrics(*totals[3:]),
        _metrics(*atom_counts),
        by_paper,
        {key: _metrics(*values) for key, values in sorted(predicate_counts.items())},
        by_paper_units,
        {key: _metrics(*values) for key, values in sorted(predicate_units.items())},
        CI_SMALL if len(locked) < 20 else "paper-cluster CI not calculated",
    )


def _matching_core(predicted: list[Statement], expected: list[Statement]) -> list[tuple[int, int]]:
    """Pair only correct cores for conditional qualifier measurement."""
    # Reuse the exact maximum-cardinality matcher by placing the core-aligned
    # rows in a separate graph with a sentinel shared qualifier set.
    pairs: list[tuple[int, int]] = []
    for predicate in sorted({r.predicate for r in (*predicted, *expected)}):
        left = [(i, r) for i, r in enumerate(predicted) if r.predicate == predicate]
        right = [(j, r) for j, r in enumerate(expected) if r.predicate == predicate]
        blank_left = [replace(r, qualifiers=()) for _, r in left]
        blank_right = [replace(r, qualifiers=()) for _, r in right]
        pairs.extend((left[i][0], right[j][0]) for i, j in _matching(
            blank_left, blank_right, mode="statement",
        ))
    return pairs


def wilson_slice(k: int, n: int) -> tuple[float, float] | None:
    """Descriptive 95% Wilson binomial interval, not a paper-cluster CI."""
    if not (0 <= k <= n):
        raise ValueError("expected 0 <= k <= n")
    if n == 0:
        return None
    z = 1.96
    p = k / n
    denominator = 1 + z * z / n
    center = (p + z * z / (2 * n)) / denominator
    spread = z * sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denominator
    return max(0.0, center - spread), min(1.0, center + spread)
