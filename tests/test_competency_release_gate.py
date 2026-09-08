"""P2-A: Frozen competency release gates.

Tests that the competency evaluator runs against the current pipeline and
all three questions (Q1 provenance, Q2 extraction, Q3 pack-query) pass with
exact answers matching the frozen gold fixtures.

RED first: these tests fail until competency.py and the fixtures exist.
GREEN: the evaluator passes all three questions against the current
deterministic mock-extraction pipeline.
"""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = str(Path(__file__).resolve().parent.parent)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import pytest  # noqa: E402

from ontologylab.competency import (  # noqa: E402
    QuestionResult,
    Receipt,
    evaluate_q1,
    evaluate_q2,
    evaluate_q3,
    run_competency_suite,
)
from ontologylab.engines import MockEngine
from ontologylab.kgstore import KGStore  # noqa: E402

GOLD_DIR = Path(__file__).resolve().parent / "gold"


def test_q2_requires_explicit_engine() -> None:
    import json

    fixture = json.loads((GOLD_DIR / "cq" / "q2-extraction.json").read_text())
    with pytest.raises(TypeError, match="engine"):
        evaluate_q2(fixture)


# ---------------------------------------------------------------------------
# Suite-level gate: all three questions must pass
# ---------------------------------------------------------------------------


class TestCompetencyReleaseGate:
    """The release gate: all three questions must pass."""

    def test_suite_all_pass(self, tmp_path):
        """run_competency_suite returns all_passed=True for the current pipeline."""
        receipt = run_competency_suite(GOLD_DIR, engine=MockEngine())
        assert receipt.total_count == 3
        for q in receipt.questions:
            assert q.passed, (
                f"{q.question_id} FAILED: missing={q.missing} spurious={q.spurious}"
            )
        assert receipt.all_passed

    def test_suite_receipt_structure(self, tmp_path):
        """The receipt has the required structure for the Packs screen."""
        receipt = run_competency_suite(GOLD_DIR, engine=MockEngine())
        d = receipt.to_dict()
        assert "questions" in d
        assert "all_passed" in d
        assert "passed_count" in d
        assert "total_count" in d
        assert "evaluated_at" in d
        for q in d["questions"]:
            assert "question_id" in q
            assert "question" in q
            assert "passed" in q
            assert "expected_count" in q
            assert "actual_count" in q
            assert "missing" in q
            assert "spurious" in q

    def test_q1_provenance_exact(self, tmp_path):
        """Q1: every verified fact traces to its exact source and approval."""
        store = KGStore.open(tmp_path / "kg.sqlite")
        try:
            import json
            fixture = json.loads(
                (GOLD_DIR / "cq" / "q1-provenance.json").read_text()
            )
            result = evaluate_q1(store, fixture, engine=MockEngine())
            assert result.passed, (
                f"missing={result.missing} spurious={result.spurious}"
            )
            assert result.question_id == "Q1"
        finally:
            store.close()

    def test_q2_extraction_exact(self, tmp_path):
        """Q2: the extractor produces the exact expected entities and relations."""
        import json
        fixture = json.loads(
            (GOLD_DIR / "cq" / "q2-extraction.json").read_text()
        )
        result = evaluate_q2(fixture, engine=MockEngine())
        assert result.passed, (
            f"missing={result.missing} spurious={result.spurious}"
        )
        assert result.question_id == "Q2"
        # Parser F1 is reported (informational)
        assert "parser_f1" in result.detail

    def test_q3_pack_query_exact(self, tmp_path):
        """Q3: a built pack returns exact answers to user queries."""
        store = KGStore.open(tmp_path / "kg.sqlite")
        packs_dir = tmp_path / "packs"
        packs_dir.mkdir()
        try:
            import json
            fixture = json.loads(
                (GOLD_DIR / "cq" / "q3-pack-query.json").read_text()
            )
            result = evaluate_q3(store, packs_dir, fixture, engine=MockEngine())
            assert result.passed, (
                f"missing={result.missing} spurious={result.spurious}"
            )
            assert result.question_id == "Q3"
            assert "pack_id" in result.detail
        finally:
            store.close()

    def test_failure_detection(self, tmp_path):
        """Corrupting an expected answer makes the gate fail."""
        import json
        fixture = json.loads(
            (GOLD_DIR / "cq" / "q2-extraction.json").read_text()
        )
        # Corrupt: add a spurious expected entity
        fixture["expected"]["entities"].append(
            {"normalized_name": "nonexistent", "entity_type": "Component"}
        )
        result = evaluate_q2(fixture, engine=MockEngine())
        assert not result.passed
        assert len(result.missing) > 0


# ---------------------------------------------------------------------------
# API surface: receipt endpoint visible on Packs screen
# ---------------------------------------------------------------------------


class TestCompetencyReceiptAPI:
    """The release receipt is reachable via the web API (Packs screen)."""

    def test_receipt_endpoint(self, tmp_path):
        """GET /api/packs/competency returns a structured receipt."""
        from fastapi.testclient import TestClient
        from ontologylab.server.app import create_app

        data_dir = tmp_path / "data"
        data_dir.mkdir(parents=True, exist_ok=True)
        app = create_app(data_dir=data_dir, packs_dir=tmp_path / "packs")
        client = TestClient(app)

        resp = client.get("/api/packs/competency")
        assert resp.status_code == 200
        body = resp.json()
        assert "all_passed" in body
        assert "passed_count" in body
        assert "total_count" in body
        assert "questions" in body
        assert body["total_count"] == 3
        for q in body["questions"]:
            assert "question_id" in q
            assert "passed" in q

    def test_receipt_in_packs_screen(self, tmp_path):
        """GET /api/packs includes the competency receipt for the Packs screen."""
        from fastapi.testclient import TestClient
        from ontologylab.server.app import create_app

        data_dir = tmp_path / "data"
        data_dir.mkdir(parents=True, exist_ok=True)
        app = create_app(data_dir=data_dir, packs_dir=tmp_path / "packs")
        client = TestClient(app)

        resp = client.get("/api/packs")
        assert resp.status_code == 200
        body = resp.json()
        # The competency receipt is embedded in the packs response
        assert "competency" in body
        comp = body["competency"]
        assert "all_passed" in comp
        assert "total_count" in comp
