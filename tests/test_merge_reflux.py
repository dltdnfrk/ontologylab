"""Merge reflux: extraction auto-scans the duplicate queue on completion.

``run_extract_job`` is the shared CLI/worker completion point. Before this
wiring, ``scan_merge_candidates`` only ran on a manual ``merge-scan`` call,
so extraction could mint duplicates that sat unscanned until someone
remembered. The scan is fail-open and advisory: it proposes candidates,
never merges.
"""

from __future__ import annotations

import asyncio

from ontologylab.engines import MockEngine
from ontologylab.extractor import run_extract_job
from tests.conftest import insert
from tests.factories import make_entity


def _run_job(store, tmp_path, doc_ids):
    return asyncio.run(
        run_extract_job(
            store,
            engine=MockEngine(),
            engine_name="mock",
            model=None,
            job_dir=tmp_path / "job",
            seed=7,
            doc_ids=doc_ids,
            max_engine_calls=100,
            time_budget=60.0,
            decode_params=None,
            on_progress=lambda _m: None,
            on_stats=lambda _s: None,
            should_abort=None,
        )
    )


def test_extraction_auto_scans_merge_candidates(store, doc, tmp_path):
    # Two near-duplicate proposed nodes: containment makes them a candidate
    # pair the moment a scan runs.
    insert(store, doc,
           [make_entity("RateLimiter"), make_entity("RateLimiterService")])
    assert store.merge_candidates_pending() == []

    _run_job(store, tmp_path, [doc.id])

    pending = store.merge_candidates_pending()
    assert len(pending) == 1
    names = {pending[0]["node_a"]["name"], pending[0]["node_b"]["name"]}
    assert names == {"RateLimiter", "RateLimiterService"}


def test_merge_scan_failure_does_not_fail_extraction(
    store, doc, tmp_path, monkeypatch
):
    import ontologylab.merge as merge_mod

    def boom(_store):
        raise RuntimeError("scan exploded")

    monkeypatch.setattr(merge_mod, "scan_merge_candidates", boom)
    # Extraction still completes; the scan error is logged, not raised.
    outcome = _run_job(store, tmp_path, [doc.id])
    assert outcome is not None
