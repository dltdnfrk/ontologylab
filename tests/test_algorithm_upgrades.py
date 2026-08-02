"""The five algorithm upgrades, each held in place by the failure it fixes.

P0 evaluation — extraction quality becomes a number (triple P/R/F1).
P1 Leiden — replaces label propagation, which this file shows collapsing
   two bridged cliques into one community on a ten-node graph.
P2 reranking — a second stage that actually reads the query against each
   candidate; RRF alone only merges ranks.
P3 blocking — the merge scan stops being O(n²) without losing the pairs
   the four signals exist to find.
P4 conformal triage — the review queue's own approve/reject history buys a
   finite-sample guarantee. Ordering only; approving stays human.
"""

from __future__ import annotations

import json
import random

import pytest

from ontologylab.communities import detect_communities
from ontologylab.conformal import (
    ConformalError,
    conformal_threshold,
    minimum_rejected,
    triage,
)
from ontologylab.embeddings import pack_vector
from ontologylab.evaluation import GoldError, evaluate_store, load_gold
from ontologylab.kgstore import KGStore
from ontologylab.merge import scan_merge_candidates
from ontologylab.rerankers import get_reranker, sigmoid
from tests.conftest import insert, make_entity, make_relation

# --------------------------------------------------------------------------
# P0 — the measurement
# --------------------------------------------------------------------------


def _gold(tmp_path, entities=(), triples=()):
    path = tmp_path / "gold.json"
    path.write_text(
        json.dumps(
            {
                "entities": [{"name": name} for name in entities],
                "triples": [
                    {"src": s, "relation": r, "dst": d} for s, r, d in triples
                ],
            }
        ),
        encoding="utf-8",
    )
    return load_gold(path)


def test_eval_scores_are_the_hand_computed_ones(tmp_path, store, doc) -> None:
    """3 gold entities, store has 2 of them + 1 spurious → P=R=2/3."""
    a, b, extra = make_entity("ApiGateway"), make_entity("RateLimiter"), make_entity("Rogue")
    insert(store, doc, [a, b, extra], [make_relation(a, b, "uses")])
    gold = _gold(
        tmp_path,
        entities=["ApiGateway", "RateLimiter", "OrderService"],
        triples=[("ApiGateway", "uses", "RateLimiter"),
                 ("RateLimiter", "uses", "OrderService")],
    )

    report = evaluate_store(store, gold)

    assert report.entity["precision"] == pytest.approx(2 / 3)
    assert report.entity["recall"] == pytest.approx(2 / 3)
    assert report.triple["precision"] == pytest.approx(1.0)
    assert report.triple["recall"] == pytest.approx(0.5)
    assert report.triple["f1"] == pytest.approx(2 / 3)
    assert report.missing_triples == [("ratelimiter", "uses", "orderservice")]


def test_eval_matches_on_the_pipeline_s_own_normalization(
    tmp_path, store, doc
) -> None:
    """Gold written as prose ("Rate Limiter") must match the stored node."""
    insert(store, doc, [make_entity("RateLimiter")])
    gold = _gold(tmp_path, entities=["Rate Limiter"])

    assert evaluate_store(store, gold).entity["recall"] == 1.0


def test_eval_zero_conventions_are_the_documented_ones(tmp_path, store) -> None:
    gold = _gold(tmp_path, entities=["Ghost"])
    report = evaluate_store(store, gold)  # empty store
    assert report.entity == {"precision": 0.0, "recall": 0.0, "f1": 0.0}
    # triples: both sides empty → perfect by convention
    assert report.triple == {"precision": 1.0, "recall": 1.0, "f1": 1.0}


def test_eval_verified_only_measures_the_reviewer(tmp_path, store, doc) -> None:
    entity = make_entity("ApiGateway")
    insert(store, doc, [entity])
    gold = _gold(tmp_path, entities=["ApiGateway"])

    assert evaluate_store(store, gold).entity["recall"] == 1.0
    assert (
        evaluate_store(store, gold, include_proposed=False).entity["recall"] == 0.0
    ), "a proposal is not yet reviewed knowledge"


def test_a_malformed_gold_file_is_a_typed_error(tmp_path) -> None:
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    with pytest.raises(GoldError):
        load_gold(bad)
    with pytest.raises(GoldError):
        load_gold(tmp_path / "absent.json")


def test_the_eval_cli_gates_on_triple_f1(tmp_path) -> None:
    """Exit 3 (below gate) must be distinct from exit 2 (broken harness)."""
    from tests.test_topic_recording import _cli

    data_dir = tmp_path / "data"
    store = KGStore.open(data_dir / "kg.sqlite")
    store.close()
    gold_path = tmp_path / "gold.json"
    gold_path.write_text(
        json.dumps({"entities": [{"name": "Ghost"}]}), encoding="utf-8"
    )

    assert _cli(["eval", "--data-dir", str(data_dir), "--gold", str(gold_path)]) == 0
    assert _cli(
        ["eval", "--data-dir", str(data_dir), "--gold", str(gold_path),
         "--min-triple-f1", "0.5"]
    ) == 0, "empty-vs-empty triples are perfect by convention"
    gold_path.write_text(
        json.dumps({"triples": [{"src": "A", "relation": "uses", "dst": "B"}]}),
        encoding="utf-8",
    )
    assert _cli(
        ["eval", "--data-dir", str(data_dir), "--gold", str(gold_path),
         "--min-triple-f1", "0.5"]
    ) == 3
    bad = tmp_path / "bad.json"
    bad.write_text("nope", encoding="utf-8")
    assert _cli(["eval", "--data-dir", str(data_dir), "--gold", str(bad)]) == 2


# --------------------------------------------------------------------------
# P1 — Leiden
# --------------------------------------------------------------------------


def _bridged_cliques():
    from itertools import combinations

    a = [f"a{i}" for i in range(5)]
    b = [f"b{i}" for i in range(5)]
    edges = list(combinations(a, 2)) + list(combinations(b, 2)) + [("a0", "b0")]
    return a, b, edges


def test_leiden_splits_what_label_propagation_collapses() -> None:
    """The quality gap, on ten nodes.

    Two 5-cliques joined by one bridge are two communities by any modularity
    reading. Label propagation returns ONE community of ten — this is not a
    contrived pathology, it is the fallback's everyday behaviour — and it is
    why Leiden is the default whenever it is importable.
    """
    a, b, edges = _bridged_cliques()

    leiden = detect_communities(a + b, edges, algorithm="leiden")
    fallback = detect_communities(a + b, edges, algorithm="label_propagation")

    assert leiden == [sorted(a), sorted(b)]
    assert fallback == [sorted(a + b)], "if this fails, retire the fallback note"


def test_auto_prefers_leiden_when_installed() -> None:
    a, b, edges = _bridged_cliques()
    assert detect_communities(a + b, edges) == detect_communities(
        a + b, edges, algorithm="leiden"
    )


def test_leiden_is_deterministic_across_edge_order() -> None:
    a, b, edges = _bridged_cliques()
    assert detect_communities(a + b, edges, algorithm="leiden") == (
        detect_communities(a + b, list(reversed(edges)), algorithm="leiden")
    )


def test_isolated_nodes_are_singletons_and_empty_graphs_are_empty() -> None:
    assert detect_communities(["x", "y"], [], algorithm="leiden") == [["x"], ["y"]]
    assert detect_communities([], [], algorithm="leiden") == []


def test_asking_for_leiden_by_name_raises_when_unavailable(monkeypatch) -> None:
    """A caller who asks by name wants the guarantee, not the label."""
    import ontologylab.communities as communities

    monkeypatch.setattr(communities, "_leiden_available", lambda: False)
    with pytest.raises(RuntimeError):
        detect_communities(["x"], [], algorithm="leiden")
    # auto degrades silently to the fallback
    assert detect_communities(["x"], []) == [["x"]]
    assert communities.community_algorithm() == "label_propagation"


def test_unknown_algorithm_is_refused() -> None:
    with pytest.raises(ValueError):
        detect_communities(["x"], [], algorithm="louvain")


# --------------------------------------------------------------------------
# P3 — blocking
# --------------------------------------------------------------------------


def test_blocking_keeps_every_signal_s_pairs(store, doc) -> None:
    """The recall contract: each of the four signals still finds its pair."""
    similar_a, similar_b = make_entity("RateLimiter"), make_entity("RateLimiters")
    contain_a, contain_b = make_entity("Gateway"), make_entity("PaymentGateway")
    alias_a = make_entity("Rate Limiting Service", aliases=["throttler"])
    alias_b = make_entity("RequestThrottler", aliases=["throttler"])
    vec_a, vec_b = make_entity("AlphaOne"), make_entity("ZetaNine")
    insert(store, doc, [similar_a, similar_b, contain_a, contain_b,
                        alias_a, alias_b, vec_a, vec_b])
    # An embedding-only duplicate: names share nothing, vectors are close.
    close = pack_vector([1.0, 0.0, 0.0])
    for name in ("AlphaOne", "ZetaNine"):
        store.conn.execute(
            "UPDATE nodes SET embedding = ?, embedding_model = 'm' "
            "WHERE name = ?",
            (close, name),
        )
    store.conn.commit()

    scan_merge_candidates(store)

    found = {
        frozenset((item["node_a"]["name"], item["node_b"]["name"]))
        for item in store.merge_candidates_pending()
    }
    assert frozenset(("RateLimiter", "RateLimiters")) in found
    assert frozenset(("Gateway", "PaymentGateway")) in found
    assert frozenset(("Rate Limiting Service", "RequestThrottler")) in found
    assert frozenset(("AlphaOne", "ZetaNine")) in found, (
        "the lexically-unrelated duplicate is exactly what vector "
        "neighbours exist to keep"
    )


def test_blocking_actually_blocks(store, doc) -> None:
    """200 unrelated names: the scan must not rebuild the cross product."""
    entities = [
        make_entity(f"{prefix}{index:03d}Q")
        for index, prefix in enumerate(
            ["Zx", "Qv", "Wm", "Rk", "Tp", "Yn", "Ub", "Ic", "Od", "Pe"] * 20
        )
    ]
    insert(store, doc, entities)

    stats = scan_merge_candidates(store)

    assert stats["pairs_possible"] == 200 * 199 // 2
    assert stats["pairs_checked"] < stats["pairs_possible"] * 0.25, (
        f"blocking checked {stats['pairs_checked']} of "
        f"{stats['pairs_possible']} pairs — that is not blocking"
    )


def test_rescan_is_idempotent_under_blocking(store, doc) -> None:
    insert(store, doc, [make_entity("RateLimiter"), make_entity("RateLimiters")])
    first = scan_merge_candidates(store)
    second = scan_merge_candidates(store)
    assert first["candidates_new"] == 1
    assert second["candidates_new"] == 0
    assert second["candidates_existing"] == 1


# --------------------------------------------------------------------------
# P2 — reranking
# --------------------------------------------------------------------------


class _FakeReranker:
    """Scores by a fixed table — order and determinism are what's under test."""

    def __init__(self, table):
        self._table = table
        self.calls = 0

    def name(self) -> str:
        return "fake"

    def score(self, query, texts):
        self.calls += 1
        return [self._table.get(text.split(" | ")[0], -5.0) for text in texts]


def _searchable_store(store, doc):
    entities = [make_entity(name) for name in
                ("TokenBucket", "TokenBucketX", "TokenService")]
    insert(store, doc, entities)
    for entity in entities:
        row = store.conn.execute(
            "SELECT id FROM nodes WHERE name = ?", (entity.name,)
        ).fetchone()
        store.approve(row["id"])
    from ontologylab.embeddings import HashingEmbedder

    store.embed_nodes(HashingEmbedder())
    return HashingEmbedder()


def test_a_reranker_reorders_the_fused_shortlist(store, doc) -> None:
    embedder = _searchable_store(store, doc)
    baseline = store.hybrid_search("token bucket", embedder, top_k=3)
    assert baseline, "the fixture must retrieve something"
    # Prefer the item RRF ranked last.
    last = baseline[-1]["name"]
    reranker = _FakeReranker({last: 9.0})

    reranked = store.hybrid_search(
        "token bucket", embedder, top_k=3, reranker=reranker
    )

    assert reranker.calls == 1
    assert reranked[0]["name"] == last, "the reranker's order must win"
    assert reranked[0]["match_score"] == pytest.approx(sigmoid(9.0), abs=1e-4)


def test_no_reranker_means_the_shipped_rrf_order(store, doc) -> None:
    embedder = _searchable_store(store, doc)
    assert store.hybrid_search("token bucket", embedder, top_k=3) == (
        store.hybrid_search("token bucket", embedder, top_k=3, reranker=None)
    )


def test_rerank_ties_break_by_id_and_truncate_to_top_k(store, doc) -> None:
    embedder = _searchable_store(store, doc)
    reranker = _FakeReranker({})  # every score identical → pure tie

    results = store.hybrid_search(
        "token bucket", embedder, top_k=2, reranker=reranker
    )

    assert len(results) == 2
    assert results == sorted(results, key=lambda item: item["id"])


def test_get_reranker_none_and_failing_auto_degrade(monkeypatch) -> None:
    import ontologylab.rerankers as rerankers

    assert get_reranker(None) is None
    assert get_reranker("none") is None

    def _boom(*a, **k):
        raise RuntimeError("no model cached")

    monkeypatch.setattr(rerankers, "CrossEncoderReranker", _boom)
    assert rerankers.get_reranker("auto") is None, "auto must fail soft"
    with pytest.raises(RuntimeError):
        rerankers.get_reranker("some/explicit-model")


def test_sigmoid_is_a_correct_squash() -> None:
    assert sigmoid(0.0) == pytest.approx(0.5)
    assert sigmoid(9.0) > 0.99
    assert sigmoid(-9.0) < 0.01
    assert sigmoid(-1000.0) >= 0.0  # no overflow


# --------------------------------------------------------------------------
# P4 — conformal triage
# --------------------------------------------------------------------------


def test_the_threshold_is_the_split_conformal_quantile() -> None:
    """n=9 rejected, α=0.2 → k=⌈10·0.8⌉=8 → the 8th smallest score."""
    scores = [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9]
    assert conformal_threshold(scores, alpha=0.2) == pytest.approx(0.8)


def test_too_few_rejections_is_an_honest_absence() -> None:
    assert conformal_threshold([0.5] * 5, alpha=0.05) is None
    assert conformal_threshold([], alpha=0.5) is None
    assert minimum_rejected(0.05) == 19
    assert conformal_threshold([0.1] * 19, alpha=0.05) is not None


def test_alpha_outside_the_open_interval_is_refused() -> None:
    for alpha in (0.0, 1.0, -0.1, 2.0):
        with pytest.raises(ConformalError):
            conformal_threshold([0.5], alpha=alpha)


def test_the_guarantee_holds_in_simulation() -> None:
    """P(fresh rejected score > τ) ≤ α, checked empirically at fixed seed."""
    rng = random.Random(7)
    calibration = [rng.betavariate(2, 5) for _ in range(200)]
    tau = conformal_threshold(calibration, alpha=0.1)
    fresh = [rng.betavariate(2, 5) for _ in range(4000)]

    violation_rate = sum(1 for s in fresh if s > tau) / len(fresh)

    assert violation_rate <= 0.1 + 0.02, violation_rate


def test_triage_reads_real_review_history(store, doc) -> None:
    """Approve/reject + critic scores → a threshold; latest score wins."""
    entities = [make_entity(f"Item{i:02d}X") for i in range(24)]
    insert(store, doc, entities)
    for index, entity in enumerate(entities):
        row = store.conn.execute(
            "SELECT id FROM nodes WHERE name = ?", (entity.name,)
        ).fetchone()
        score = 0.02 + index * 0.04
        store.record_critic_review(
            "node", row["id"], engine="mock", model=None,
            prompt_version="critic-v1", score=score,
        )
        if index < 20:
            store.reject(row["id"])
        else:
            store.approve(row["id"])

    result = triage(store, alpha=0.1)

    assert result.available is True
    assert result.n_rejected == 20
    assert result.n_verified == 4
    # k = ceil(21*0.9) = 19 → 19th smallest of the 20 rejected scores
    rejected_scores = sorted(0.02 + i * 0.04 for i in range(20))
    assert result.threshold == pytest.approx(rejected_scores[18])


def test_triage_with_no_history_says_so(store) -> None:
    result = triage(store, alpha=0.05)
    assert result.available is False
    assert result.threshold is None
    assert result.needed_rejected == 19


def test_the_endpoint_is_read_only(tmp_path) -> None:
    """The triage line orders a queue; it must never move a status."""
    from fastapi.testclient import TestClient

    from ontologylab.server import routes
    from ontologylab.server.app import create_app

    data_dir = tmp_path / "data"
    client = TestClient(create_app(data_dir=data_dir))

    body = client.get("/api/review/triage").json()

    assert body["available"] is False
    assert body["needed_rejected"] == 19
    assert client.get("/api/review/triage?alpha=2.0").status_code == 422
    store = KGStore.open(data_dir / "kg.sqlite")
    try:
        statuses = store.conn.execute(
            "SELECT COUNT(*) FROM nodes WHERE status != 'proposed'"
        ).fetchone()[0]
    finally:
        store.close()
    assert statuses == 0


# --------------------------------------------------------------------------
# Math upgrades round 2: bootstrap CI, calibration, CPM
# --------------------------------------------------------------------------


def test_bootstrap_interval_contains_the_point_estimate(tmp_path, store, doc) -> None:
    from ontologylab.evaluation import bootstrap_f1_interval

    a, b = make_entity("ApiGateway"), make_entity("RateLimiter")
    insert(store, doc, [a, b])
    gold = _gold(tmp_path, entities=["ApiGateway", "RateLimiter", "Ghost"])

    report = evaluate_store(store, gold)

    ci = report.entity_f1_ci
    assert ci["low"] <= report.entity["f1"] <= ci["high"]
    # Deterministic: the same store+gold yields the same interval.
    assert evaluate_store(store, gold).entity_f1_ci == ci
    # Degenerate perfection has no sampling variability on the upper end.
    assert bootstrap_f1_interval(frozenset(), set()) == {"low": 1.0, "high": 1.0}


def test_bootstrap_interval_narrows_with_more_data() -> None:
    """The whole point of an interval: n=10 must be wider than n=1000."""
    from ontologylab.evaluation import bootstrap_f1_interval

    small_gold = frozenset(f"g{i}" for i in range(10))
    small_found = set(list(small_gold)[:7]) | {"x1", "x2"}
    big_gold = frozenset(f"g{i}" for i in range(1000))
    big_found = set(list(big_gold)[:700]) | {f"x{i}" for i in range(200)}

    small = bootstrap_f1_interval(small_gold, small_found)
    big = bootstrap_f1_interval(big_gold, big_found)

    assert (small["high"] - small["low"]) > (big["high"] - big["low"]) * 2


def test_pava_pools_adjacent_violators_to_the_known_fit() -> None:
    """Hand-checkable case: labels 1,0 at ascending confidence pool to 0.5."""
    from ontologylab.calibration import fit_isotonic

    calibrator = fit_isotonic([(0.1, 1), (0.2, 0), (0.8, 1)])

    assert calibrator.values == (0.5, 1.0)
    assert calibrator.predict(0.15) == 0.5
    assert calibrator.predict(0.9) == 1.0
    assert calibrator.predict(0.0) == 0.5  # below the first block
    # Equal-mean neighbours pool into ONE block: the exposed curve is the
    # minimal step function, not one step per tie group.
    flat = fit_isotonic([(0.1, 0), (0.1, 1), (0.5, 0), (0.5, 1)])
    assert flat.values == (0.5,)


def test_pava_output_is_monotone_on_noisy_input() -> None:
    from ontologylab.calibration import fit_isotonic

    rng = random.Random(7)
    pairs = [
        (round(rng.random(), 3), 1 if rng.random() < 0.5 else 0)
        for _ in range(300)
    ]
    calibrator = fit_isotonic(pairs)

    values = list(calibrator.values)
    assert values == sorted(values)
    assert all(values[i] < values[i + 1] for i in range(len(values) - 1)), (
        "PAVA blocks must be strictly increasing — equal neighbours "
        "should have been pooled"
    )
    grid = [calibrator.predict(x / 100) for x in range(101)]
    assert grid == sorted(grid)


def test_ece_is_the_hand_computed_weighted_gap() -> None:
    """One bin claims 0.9 and delivers 0.5; the other is perfect."""
    from ontologylab.calibration import expected_calibration_error

    pairs = [(0.9, 1), (0.9, 0)] + [(0.1, 0)] * 2
    report = expected_calibration_error(pairs)

    # bin(0.9): |0.9 - 0.5| = 0.4, weight 1/2; bin(0.1): |0.1 - 0| = 0.1,
    # weight 1/2 → ECE = 0.25
    assert report["ece"] == pytest.approx(0.25)
    assert report["n"] == 4


def test_perfectly_calibrated_confidences_score_near_zero_ece() -> None:
    from ontologylab.calibration import expected_calibration_error

    rng = random.Random(7)
    pairs = []
    for _ in range(4000):
        confidence = rng.random()
        pairs.append((confidence, 1 if rng.random() < confidence else 0))

    assert expected_calibration_error(pairs)["ece"] < 0.05


def test_calibration_report_declines_on_thin_data(store, doc) -> None:
    from ontologylab.calibration import calibration_report

    entity = make_entity("LonelyItem")
    insert(store, doc, [entity])
    row = store.conn.execute(
        "SELECT id FROM nodes WHERE name = 'LonelyItem'"
    ).fetchone()
    store.approve(row["id"])

    report = calibration_report(store)

    assert report["available"] is False
    assert report["curve"] is None
    assert report["n"] == 1


def test_calibration_reads_real_review_outcomes(store, doc) -> None:
    """Overconfident extractor: claims ~0.9, humans reject half."""
    from ontologylab.calibration import calibration_report

    entities = [
        make_entity(f"CalItem{i:02d}Q", confidence=0.9) for i in range(24)
    ]
    insert(store, doc, entities)
    for index, entity in enumerate(entities):
        row = store.conn.execute(
            "SELECT id FROM nodes WHERE name = ?", (entity.name,)
        ).fetchone()
        if index % 2 == 0:
            store.approve(row["id"])
        else:
            store.reject(row["id"])

    report = calibration_report(store)

    assert report["available"] is True
    assert report["n"] == 24
    assert report["raw"]["ece"] == pytest.approx(0.4), (
        "claimed 0.9, observed 0.5 — the gap is the point"
    )
    assert report["curve"]["values"][-1] == pytest.approx(0.5)


def test_the_calibration_endpoint_is_read_only(tmp_path) -> None:
    from fastapi.testclient import TestClient

    from ontologylab.server import routes
    from ontologylab.server.app import create_app

    data_dir = tmp_path / "data"
    client = TestClient(create_app(data_dir=data_dir))

    body = client.get("/api/review/calibration").json()

    assert body["available"] is False
    assert body["n"] == 0


def _ring_of_triangles(count: int):
    nodes, edges = [], []
    for k in range(count):
        a, b, c = f"t{k:02d}a", f"t{k:02d}b", f"t{k:02d}c"
        nodes += [a, b, c]
        edges += [(a, b), (b, c), (a, c)]
    for k in range(count):
        edges.append((f"t{k:02d}c", f"t{(k + 1) % count:02d}a"))
    return nodes, edges


def test_cpm_escapes_the_resolution_limit_modularity_hits() -> None:
    """Fortunato & Barthélemy (PNAS 2007), reproduced as a fixture.

    A ring of 20 triangles has L=80 edges; modularity cannot resolve
    communities with fewer than ~√(L/2)≈6.3 internal edges, and a triangle
    has 3 — so modularity-Leiden merges triangles (8 communities measured
    here), while CPM at γ=0.3 recovers all 20. This is the reason the CPM
    option exists; if modularity ever starts finding 20, this test will
    say the escape hatch is no longer needed.
    """
    nodes, edges = _ring_of_triangles(20)

    modularity = detect_communities(nodes, edges, algorithm="leiden")
    cpm = detect_communities(
        nodes, edges, algorithm="leiden-cpm", resolution=0.3
    )

    assert len(cpm) == 20
    assert all(len(community) == 3 for community in cpm)
    assert len(modularity) < 20, "the resolution limit itself"


def test_cpm_demands_an_explicit_resolution() -> None:
    """γ→0 degenerates to one giant community; a silent default would be a
    resolution limit with extra steps."""
    nodes, edges = _ring_of_triangles(3)

    with pytest.raises(ValueError):
        detect_communities(nodes, edges, algorithm="leiden-cpm")
    with pytest.raises(ValueError):
        detect_communities(nodes, edges, algorithm="leiden-cpm", resolution=0.0)


def test_cpm_is_deterministic_and_keeps_the_output_contract() -> None:
    nodes, edges = _ring_of_triangles(5)

    first = detect_communities(nodes, edges, algorithm="leiden-cpm", resolution=0.3)
    second = detect_communities(
        nodes, list(reversed(edges)), algorithm="leiden-cpm", resolution=0.3
    )

    assert first == second
    assert first == sorted(first, key=lambda m: (-len(m), m[0]))
