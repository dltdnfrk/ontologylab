"""Replay fixture statements through extraction, review HTTP, and scoring offline."""

from __future__ import annotations

import json
import re
from dataclasses import replace
from hashlib import sha256
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from ontologylab.kgstore import KGStore
from ontologylab.schemas import preset
from ontologylab.server.app import create_app
from ontologylab.statement_eval import (
    AdjudicatedGold, Paper, Span, SplitManifest, SplitViolation, Statement,
    freeze_split, score_statements,
)
from ontologylab.statement_harness import run_statement_harness


FIXTURES = Path(__file__).parent / "fixtures" / "statement_harness"
PREFIX = "Results\n"


def _fixture(name: str) -> dict:
    return json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))


def _mention(window: str, quote: str, *, entity_type: str | None = None) -> dict:
    start = window.index(quote)
    value = {"quote": quote, "start": start, "end": start + len(quote)}
    if entity_type is not None:
        value["entity_type"] = entity_type
    return value


class ScriptedEngine:
    def __init__(self, *, extra: bool = False) -> None:
        self.extra = extra

    def name(self) -> str:
        return "fixture-script"

    async def generate(self, prompt: str, *, model: str | None = None) -> tuple[str, dict]:
        match = re.search(r"<statement-unit>\n(.+)\n</statement-unit>", prompt)
        assert match is not None
        unit = json.loads(match[1])
        window = unit["window"]
        if "relative to untreated plots" in window and not self.extra:
            return json.dumps({"statements": []}), {"calls": 1}
        arm = next(slot for slot in unit["slots"] if slot["role"] == "arm")
        result = next(slot for slot in unit["slots"] if slot["role"] == "result")
        endpoint = "density" if "relative to untreated plots" in window else (
            "P. annua" if "P. annua" in window else
            "density" if "density" in result["quote"] else "biomass"
        )
        polarity = "no_effect" if (
            "did not" in result["quote"] or "unchanged" in result["quote"]
        ) else "supports"
        statement = {
            "unit_id": unit["unit_id"],
            "subject": _mention(window, arm["quote"], entity_type="ActiveIngredient"),
            "object": _mention(window, endpoint, entity_type="Pest"),
            "treatment": _mention(window, arm["quote"]),
            "endpoint": _mention(window, endpoint),
            "arm": {key: arm[key] for key in ("quote", "start", "end")},
            "result": {key: result[key] for key in ("quote", "start", "end")},
            "source": {"quote": window, "start": 0, "end": len(window)},
            "relation_type": "controls",
            "polarity": polarity,
            "qualifiers": {},
            "qualifier_mentions": {},
        }
        return json.dumps({"statements": [statement]}), {"calls": 1}


def _gold(paper: Paper, fixture: dict, arm: str, result: str, polarity: str,
          endpoint: str) -> Statement:
    slots = fixture["expected_slots"]
    arm_slot = next(s for s in slots if s["role"] == "arm" and s["quote"] == arm)
    result_slot = next(
        s for s in slots if s["role"] == "result" and s["arm"] == arm
    )
    assert result_slot["quote"] == result
    base = len(PREFIX)
    return Statement(
        f"gold-{paper.doi}-{arm}", paper.doi, f"gold-{arm}",
        arm, "controls", endpoint, polarity, (), (),
        Span(base + arm_slot["start"], base + arm_slot["end"], arm),
        Span(base + result_slot["start"], base + result_slot["end"], result),
    )


def _manifest(papers: tuple[Paper, ...], hashes: tuple[tuple[str, str], ...],
              gold_hash: str) -> SplitManifest:
    return SplitManifest(
        tuple((paper, "test") for paper in papers),
        hashes + (
            ("gold", gold_hash),
            ("source-selection", sha256(b"fixture-selection").hexdigest()),
            ("scorer", sha256(b"fixture-scorer").hexdigest()),
        ),
    )


def test_fixture_replay_review_and_receipt_scoring(tmp_path: Path) -> None:
    fixtures = tuple(_fixture(name) for name in (
        "whereas-mixed", "respectively-three-arm", "uncued-positive",
    ))
    data_dir = tmp_path / "data"
    with KGStore.open(data_dir / "kg.sqlite") as store:
        store.install_schema(**preset("agrochem-v2"))
        ids = []
        for index, fixture in enumerate(fixtures):
            text = PREFIX + fixture["text"]
            doc, created = store.insert_document(
                source_kind="upload", source_uri=f"file:///fixture-{index}.txt",
                title=fixture["id"], raw_text=text,
                content_hash=sha256(text.encode("utf-8")).hexdigest(),
                doi=f"10.5555/offline-fixture-{index}",
            )
            assert created
            ids.append(doc.id)

        first = run_statement_harness(store, ids, ScriptedEngine(), budget=6)
        expected = (
            ("Glyphosate", "did not reduce P. annua biomass", "no_effect", "P. annua"),
            ("mesotrione", "reduced P. annua biomass", "supports", "P. annua"),
            ("Pinoxaden", "reduced density", "supports", "density"),
            ("pyroxsulam", "left density unchanged", "no_effect", "density"),
            ("mesotrione", "reduced biomass", "supports", "biomass"),
        )
        gold_rows = tuple(
            _gold(first.papers[0 if index < 2 else 1],
                  fixtures[0 if index < 2 else 1], *values)
            for index, values in enumerate(expected)
        )
        assert first.status == "complete" and first.rejections == ()
        assert len(first.receipts) == 5
        assert {
            (row.paper_doi, row.arm, row.result, row.subject, row.polarity)
            for row in first.receipts
        } == {
            (row.paper_doi, row.arm, row.result, row.subject, row.polarity)
            for row in gold_rows
        }
        assert len({row.row_id for row in first.receipts}) == 5
        assert store.conn.execute(
            "SELECT COUNT(*) FROM edges WHERE status='verified'"
        ).fetchone()[0] == 0
        assert store.conn.execute("SELECT COUNT(*) FROM edges").fetchone()[0] == 5
        citations = store.conn.execute(
            "SELECT e.id, e.status, e.origin, c.source_doc_id, c.source_span "
            "FROM edges e JOIN citations c ON c.item_id=e.id AND c.kind='edge'"
        ).fetchall()
        assert len(citations) == 5
        for citation in citations:
            fixture = fixtures[ids.index(citation["source_doc_id"])]
            assert (citation["status"], citation["origin"]) == (
                "proposed", "extracted",
            )
            assert json.loads(citation["source_span"]) == {
                "start": len(PREFIX),
                "end": len(PREFIX) + len(fixture["text"]),
            }

        second = run_statement_harness(store, ids, ScriptedEngine(), budget=6)
        assert second.receipts == first.receipts
        assert second.hashes == first.hashes
        assert store.conn.execute("SELECT COUNT(*) FROM edges").fetchone()[0] == 5

        later = run_statement_harness(
            store, [ids[2]], ScriptedEngine(extra=True), budget=1,
        )
        assert len(later.receipts) == 1
        approved = later.receipts[0]
        assert approved.row_id not in {row.row_id for row in first.receipts}

    with TestClient(create_app(data_dir=data_dir, packs_dir=tmp_path / "packs")) as client:
        response = client.post("/api/proposals/approve", json={
            "id": approved.row_id, "by": "fixture-reviewer", "cascade": True,
        })
        assert response.status_code == 200, response.text

    with KGStore.open(data_dir / "kg.sqlite", read_only=True, immutable=False) as store:
        edges = store.conn.execute("SELECT id, status FROM edges").fetchall()
        assert len(edges) == 6
        assert {row["id"] for row in edges if row["status"] == "verified"} == {
            approved.row_id
        }
        events = store.conn.execute(
            "SELECT action, actor, item_ids_json FROM statement_review_events"
        ).fetchall()
        assert len(events) == 1
        assert events[0]["action"] == "approve"
        assert events[0]["actor"] == "fixture-reviewer"
        affected = json.loads(events[0]["item_ids_json"])
        assert affected[0] == approved.row_id
        assert len(affected) == 3  # The cascade also approves its two endpoints.

    gold = AdjudicatedGold(
        gold_rows + (_gold(
            first.papers[2], fixtures[2], "Mesotrione",
            "reduced P. annua density", "supports", "density",
        ),),
        first.papers, sha256(b"independent-fixture-gold").hexdigest(),
    )
    lock = freeze_split(
        _manifest(first.papers, first.hashes, gold.gold_sha256),
        current_gold_ids=set(),
    )
    # A verified store edge is diagnostic, not a receipt from the scored run.
    score = score_statements(
        replace(first, store_edges=(approved,)), gold, lock,
    )
    assert (score.statements.tp, score.statements.fp, score.statements.fn) == (5, 0, 1)
    assert (score.units.tp, score.units.fp, score.units.fn) == (5, 0, 1)


def test_dev_paper_embargo_blocks_freeze_before_scoring() -> None:
    fixture = _fixture("whereas-mixed")
    text = PREFIX + fixture["text"]
    paper = Paper(
        "10.5555/new-test-paper", "PMC12632097", text,
        sha256(text.encode("utf-8")).hexdigest(),
    )
    hashes = tuple(
        (name, sha256(name.encode("utf-8")).hexdigest())
        for name in (
            "rules", "cue", "prompt", "schema", "qualifier",
            "normalization", "completion",
        )
    )
    with pytest.raises(SplitViolation, match="development paper assigned to test"):
        freeze_split(
            _manifest((paper,), hashes, sha256(b"embargo-gold").hexdigest()),
            current_gold_ids=set(),
        )
