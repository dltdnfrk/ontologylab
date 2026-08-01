"""Conformal triage tests (2026-08-01 audit: this module had none).

The finite-sample guarantee holds only if every calibration score comes
from ONE critic distribution — exchangeability is the method's premise,
so mixing engines/prompt versions in the calibration set breaks it.
"""

from __future__ import annotations

import pytest

from ontologylab.conformal import (
    calibration_scores,
    conformal_threshold,
    minimum_rejected,
    triage,
)
from ontologylab.kgstore import KGStore
from ontologylab.models import ProposedEntity


def _seed_store(tmp_path, *, rejected: int, verified: int, proposed: int = 0):
    store = KGStore.open(tmp_path / "kg.sqlite")
    doc, _ = store.insert_document(
        source_kind="t", source_uri="t://1", title="t",
        raw_text="x", content_hash="h",
    )
    ids = {"rejected": [], "verified": [], "proposed": []}
    for status, count in (("rejected", rejected), ("verified", verified), ("proposed", proposed)):
        for i in range(count):
            item_id = f"{status[0]}{i:031x}"[-32:].rjust(32, "0")
            store.insert_proposed(
                [ProposedEntity(id=item_id, entity_type="Concept", name=f"{status}-{i}")],
                [], source_doc_id=doc.id, extractor_engine="t",
            )
            if status == "verified":
                store.approve(item_id, by="me")
            elif status == "rejected":
                store.reject(item_id, by="me")
            ids[status].append(item_id)
    return store, ids


def _review(store, item_id, *, engine="critic", model=None, version="v1",
            score=0.5, ts=1000.0):
    store.conn.execute(
        "INSERT INTO critic_reviews (kind, item_id, engine, model, "
        "prompt_version, score, rationale, created_ts) "
        "VALUES ('node', ?, ?, ?, ?, ?, 'r', ?)",
        (item_id, engine, model, version, score, ts),
    )
    store.conn.commit()


def test_threshold_is_the_kth_smallest_rejected_score() -> None:
    scores = [0.9, 0.1, 0.5, 0.3, 0.7] * 4
    alpha = 0.2
    n = len(scores)
    k = -(-(n + 1) * (1 - alpha) // 1)
    expected = sorted(scores)[int(k) - 1]
    assert conformal_threshold(scores, alpha) == expected


def test_threshold_is_honestly_absent_when_rejections_are_scarce() -> None:
    alpha = 0.05
    assert conformal_threshold([0.9] * (minimum_rejected(alpha) - 1), alpha) is None
    assert conformal_threshold([], alpha) is None


def test_alpha_out_of_range_raises() -> None:
    with pytest.raises(Exception):
        conformal_threshold([0.5] * 30, 1.5)


def test_calibration_excludes_proposed_items(tmp_path) -> None:
    store, ids = _seed_store(tmp_path, rejected=1, verified=1, proposed=2)
    try:
        for status in ids:
            for item_id in ids[status]:
                _review(store, item_id, score=0.5)
        rejected, verified = calibration_scores(store)
        assert len(rejected) == 1 and len(verified) == 1
    finally:
        store.close()


def test_calibration_uses_only_the_current_critic_stream(tmp_path) -> None:
    store, ids = _seed_store(tmp_path, rejected=2, verified=2)
    try:
        _review(store, ids["rejected"][0], engine="cheap", score=0.10, ts=1000.0)
        _review(store, ids["rejected"][1], engine="cheap", score=0.20, ts=1001.0)
        _review(store, ids["verified"][0], engine="cheap", score=0.80, ts=1002.0)
        _review(store, ids["verified"][1], engine="cheap", score=0.85, ts=1003.0)
        _review(store, ids["rejected"][0], engine="frontier", score=0.95, ts=2000.0)
        rejected, verified = calibration_scores(store)
        assert rejected == [0.95]
        assert verified == []
    finally:
        store.close()


def test_triage_reports_unavailable_when_stream_history_is_thin(tmp_path) -> None:
    store, ids = _seed_store(tmp_path, rejected=minimum_rejected(0.05), verified=0)
    try:
        for i, item_id in enumerate(ids["rejected"]):
            _review(store, item_id, engine="old", score=0.1 + i * 0.01, ts=1000.0 + i)
        _review(store, ids["rejected"][0], engine="new", score=0.99, ts=9999.0)
        result = triage(store, alpha=0.05)
        assert result.available is False
        assert result.n_rejected == 1
    finally:
        store.close()


def test_triage_computes_a_line_from_one_stream(tmp_path) -> None:
    alpha = 0.05
    store, ids = _seed_store(tmp_path, rejected=minimum_rejected(alpha), verified=3)
    try:
        for i, item_id in enumerate(ids["rejected"]):
            _review(store, item_id, score=0.05 + i * 0.01, ts=1000.0 + i)
        for item_id in ids["verified"]:
            _review(store, item_id, score=0.9, ts=1000.0)
        result = triage(store, alpha=alpha)
        assert result.available is True
        assert result.threshold == pytest.approx(
            conformal_threshold([0.05 + i * 0.01 for i in range(len(ids["rejected"]))], alpha)
        )
    finally:
        store.close()
