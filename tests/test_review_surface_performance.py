"""Review-surface latency gate.

Every surface that shows a critic score restricts to the current
`(engine, model, prompt_version)` stream. That restriction is correct as a
bound parameter and correct as a correlated subquery — the two return the
same rows, so no behavioral test can tell them apart. Only cost does: the
subquery re-scans `critic_reviews` once per candidate row.

The queue is the read path a human blocks on, and it is the one that
degrades superlinearly with review history. This module pins the shape of
that cost, not the wall clock of any one machine: the ceiling sits two
orders of magnitude above the measured parameterized path, so it passes on
a loaded laptop and fails on a re-introduced per-row scan.
"""

from __future__ import annotations

import statistics
import time

from ontologylab.critic import CRITIC_PROMPT_VERSION
from tests.conftest import insert, make_entity

# Measured on this fixture: 1.9ms with the stream bound as a parameter,
# 426.6ms with the same restriction written as a correlated subquery. The
# ceiling sits between them with ~20x headroom over the parameterized path
# and ~10x margin under the rescan, so machine load cannot fake either verdict.
_REVIEW_READ_CEILING_MS = 40.0

# Enough candidates that a per-row rescan is quadratic in observable time,
# small enough that building the fixture stays under a second.
_PROPOSAL_COUNT = 600

# One live stream plus retired ones. A single stream cannot expose the bug:
# the restriction only costs anything when there is history to scan past.
_RETIRED_STREAMS = ("critic-v0", "critic-v1")


def _seed_review_history(store, doc) -> list[str]:
    entities = [make_entity(f"CandidateNode{i:04d}") for i in range(_PROPOSAL_COUNT)]
    insert(store, doc, entities)
    node_ids = [row["id"] for row in store.pending_review(limit=_PROPOSAL_COUNT)]
    assert len(node_ids) == _PROPOSAL_COUNT

    for prompt_version in (*_RETIRED_STREAMS, CRITIC_PROMPT_VERSION):
        for position, node_id in enumerate(node_ids):
            store.record_critic_review(
                "node",
                node_id,
                engine="mock",
                model=None,
                prompt_version=prompt_version,
                score=0.5,
                rationale=f"{prompt_version}:{position}",
            )
    return node_ids


def _p95_ms(samples: list[float]) -> float:
    return statistics.quantiles(samples, n=20)[-1] if len(samples) > 1 else samples[0]


def test_review_reads_stay_bounded_as_critic_history_accumulates(store, doc):
    # Given: 600 proposals carrying three generations of critic scores.
    node_ids = _seed_review_history(store, doc)

    # When: each surface that scopes to the current stream is read repeatedly.
    samples: dict[str, list[float]] = {"queue": [], "entity": [], "provenance": []}
    for _ in range(5):
        start = time.perf_counter()
        queue = store.pending_review(order="critic", limit=100)
        samples["queue"].append((time.perf_counter() - start) * 1000)

        start = time.perf_counter()
        context = store.entity_review_context(node_ids[0])
        samples["entity"].append((time.perf_counter() - start) * 1000)

        start = time.perf_counter()
        origin = store.provenance("node", node_ids[0])
        samples["provenance"].append((time.perf_counter() - start) * 1000)

    # Then: every surface stays bounded, and still answers from the live
    # stream only — a fast read of the wrong generation is not a pass.
    for surface, timings in samples.items():
        assert _p95_ms(timings) <= _REVIEW_READ_CEILING_MS, (
            f"{surface} p95 {_p95_ms(timings):.1f}ms exceeded "
            f"{_REVIEW_READ_CEILING_MS}ms over {len(timings)} samples"
        )

    assert len(queue) == 100
    assert all(row["critic_score"] == 0.5 for row in queue)
    assert context["entity"]["id"] == node_ids[0]
    assert origin["critic"]["rationale"].startswith(f"{CRITIC_PROMPT_VERSION}:")
