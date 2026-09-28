"""Scripted offline assertions through the real SQLite proposal boundary."""

from __future__ import annotations

import json
import re
from hashlib import sha256

import pytest

from ontologylab.engines import EngineError
from ontologylab.extractor import Chunk, parse_and_validate_extraction
from ontologylab.schemas import preset
from ontologylab.statement_harness import (
    HarnessBudget, PROMPT_VERSION, run_statement_harness,
)


@pytest.fixture
def qualified_store(store):
    schema = preset("agrochem-v2")
    store.install_schema(
        label=schema["label"], description=schema["description"],
        entity_types=schema["entity_types"], relation_types=schema["relation_types"],
    )
    return store


def document(store, text):
    doc, created = store.insert_document(
        source_kind="upload", source_uri="file:///harness.txt",
        title="harness", raw_text=text,
        content_hash=sha256(text.encode("utf-8")).hexdigest(),
        doi="10.5555/statement-harness",
    )
    assert created
    return doc.id


def mention(window, quote, occurrence=0, *, entity_type=None):
    at = -1
    for _ in range(occurrence + 1):
        at = window.index(quote, at + 1)
    item = {"quote": quote, "start": at, "end": at + len(quote)}
    if entity_type:
        item["entity_type"] = entity_type
    return item


def proposal(unit, treatment, result, *, subject=None, comparator=None, time=None,
             endpoint="cover", result_occurrence=0):
    window = unit["window"]
    subject = subject or treatment
    arm = next(slot for slot in unit["slots"] if slot["role"] == "arm")
    result_slot = next(slot for slot in unit["slots"] if slot["role"] == "result")
    qualifiers = {}
    cited = {}
    for key, value in (
        ("comparison_context_qualifier", comparator),
        ("observation_time_qualifier", time),
    ):
        if value is not None:
            qualifiers[key] = value
            cited[key] = mention(window, value)
    return {
        "unit_id": unit["unit_id"],
        "subject": mention(window, subject, entity_type="ActiveIngredient"),
        "object": mention(window, endpoint, entity_type="Pest"),
        "treatment": mention(window, treatment),
        "endpoint": mention(window, endpoint),
        "result": {
            "quote": result_slot["quote"], "start": result_slot["start"],
            "end": result_slot["end"],
        },
        "arm": {"quote": arm["quote"], "start": arm["start"], "end": arm["end"]},
        "source": {"quote": window, "start": 0, "end": len(window)},
        "relation_type": "controls",
        "polarity": "no_effect" if "did not" in result else "supports",
        "qualifiers": qualifiers, "qualifier_mentions": cited,
    }


class ScriptedEngine:
    def __init__(self, script):
        self.script = script
        self.calls = 0

    def name(self):
        return "scripted"

    async def generate(self, prompt, *, model=None):
        match = re.search(r"<statement-unit>\n(.+)\n</statement-unit>", prompt)
        assert match is not None
        unit = json.loads(match[1])
        self.calls += 1
        return json.dumps({"statements": self.script(unit)}), {"calls": 1}


def test_unicode_quote_rebases_and_only_proposes(qualified_store):
    text = "µ heading\nMethods\nDose was prepared.\nResults\nAgentA reduced cover."
    doc_id = document(qualified_store, text)
    engine = ScriptedEngine(lambda u: [proposal(u, "AgentA", "reduced cover")])

    run = run_statement_harness(qualified_store, [doc_id], engine, budget=2)

    assert run.status == "complete" and run.calls == 1
    assert len(run.receipts) == 1
    receipt = run.receipts[0]
    assert text[receipt.arm.start:receipt.arm.end] == "AgentA"
    assert text[receipt.result.start:receipt.result.end] == receipt.result.quote
    assert qualified_store.conn.execute(
        "SELECT COUNT(*) FROM edges WHERE status='verified'"
    ).fetchone()[0] == 0
    edge = qualified_store.conn.execute(
        "SELECT status, origin, prompt_version FROM edges"
    ).fetchone()
    assert tuple(edge) == ("proposed", "extracted", PROMPT_VERSION)


def test_two_arms_keep_comparator_and_time_identities(qualified_store):
    text = (
        "Results\nAgentA did not reduce cover whereas AgentB reduced cover "
        "relative to untreated on day 7."
    )
    doc_id = document(qualified_store, text)

    def script(unit):
        arm = next(slot["quote"] for slot in unit["slots"] if slot["role"] == "arm")
        return [proposal(
            unit, arm, "did not reduce" if arm == "AgentA" else "reduced",
            comparator="untreated", time="day 7",
        )]

    run = run_statement_harness(qualified_store, [doc_id], ScriptedEngine(script), budget=2)

    assert len(run.receipts) == 2
    assert {row.arm.quote for row in run.receipts} == {"AgentA", "AgentB"}
    assert {row.polarity for row in run.receipts} == {"supports", "no_effect"}
    assert qualified_store.conn.execute("SELECT COUNT(*) FROM edges").fetchone()[0] == 2
    assert all(
        {"comparison_context_qualifier", "observation_time_qualifier"} <=
        dict(row.qualifiers).keys() for row in run.receipts
    )


def test_explicit_adjacent_antecedent_is_recorded(qualified_store):
    text = "Results\nAgentA was sprayed. It reduced cover."
    doc_id = document(qualified_store, text)

    def script(unit):
        if "reduced" not in unit["window"]:
            return []
        return [proposal(unit, "AgentA", "reduced cover", subject="AgentA")]

    run = run_statement_harness(qualified_store, [doc_id], ScriptedEngine(script), budget=2)

    assert len(run.receipts) == 1
    assert run.receipts[0].subject == "AgentA"
    assert run.receipts[0].arm.quote == "It"


def test_malformed_schema_and_missing_result_are_rejected(qualified_store):
    text = "Results\nAgentA reduced cover."
    doc_id = document(qualified_store, text)
    malformed = ScriptedEngine(lambda unit: [{"unit_id": unit["unit_id"], "extra": 1}])

    first = run_statement_harness(qualified_store, [doc_id], malformed, budget=1)

    assert first.receipts == ()
    assert first.rejections[0][1] == "malformed_schema"

    def without_result(unit):
        item = proposal(unit, "AgentA", "reduced cover")
        item["result"]["quote"] = ""
        return [item]

    second = run_statement_harness(
        qualified_store, [doc_id], ScriptedEngine(without_result), budget=1,
    )
    assert second.receipts == ()
    assert second.rejections[0][1] == "result_quote_mismatch"
    assert qualified_store.conn.execute("SELECT COUNT(*) FROM edges").fetchone()[0] == 0


def test_wrong_arm_span_is_not_relocated(qualified_store):
    text = "Results\nAgentA did not reduce cover whereas AgentB reduced cover."
    doc_id = document(qualified_store, text)

    def wrong_arm(unit):
        slots = [slot for slot in unit["slots"] if slot["role"] == "arm"]
        item = proposal(unit, slots[0]["quote"], "reduced cover")
        if slots[0]["quote"] == "AgentB":
            item["arm"] = mention(unit["window"], "AgentA")
            item["treatment"] = mention(unit["window"], "AgentA")
        return [item]

    run = run_statement_harness(
        qualified_store, [doc_id], ScriptedEngine(wrong_arm), budget=2,
    )

    assert len(run.receipts) == 1
    assert run.receipts[0].arm.quote == "AgentA"
    assert (run.rejections[0][1] == "wrong_arm_or_result")


@pytest.mark.parametrize("wrong_quote", ["xgentA", "AgentB"])
def test_in_window_quote_must_match_its_offsets(qualified_store, wrong_quote):
    text = "Results\nAgentA did not reduce cover whereas AgentB reduced cover."
    doc_id = document(qualified_store, text)

    def wrong_arm(unit):
        arm = next(slot for slot in unit["slots"] if slot["role"] == "arm")
        if arm["quote"] != "AgentA":
            return []
        item = proposal(unit, arm["quote"], "reduced cover")
        item["arm"] = {
            "quote": wrong_quote, "start": arm["start"], "end": arm["end"],
        }
        return [item]

    run = run_statement_harness(
        qualified_store, [doc_id], ScriptedEngine(wrong_arm), budget=2,
    )

    assert run.receipts == ()
    assert run.rejections[0][1] == "arm_quote_mismatch"
    assert qualified_store.conn.execute("SELECT COUNT(*) FROM edges").fetchone()[0] == 0


def test_budget_cap_lists_every_unprocessed_unit(qualified_store):
    text = "Results\nAgentA reduced cover. AgentB reduced cover. AgentC reduced cover."
    doc_id = document(qualified_store, text)

    run = run_statement_harness(
        qualified_store, [doc_id], ScriptedEngine(lambda unit: []),
        budget=HarnessBudget(max_calls=1),
    )

    assert run.status == "incomplete" and run.complete is False
    assert run.calls == 1
    assert len(run.unprocessed_units) == 2
    assert len(set(run.unprocessed_units)) == 2


def test_repeat_run_receipt_names_persisted_edge(qualified_store):
    text = "Results\nAgentA reduced cover."
    doc_id = document(qualified_store, text)
    engine = ScriptedEngine(lambda unit: [proposal(unit, "AgentA", "reduced cover")])

    first = run_statement_harness(qualified_store, [doc_id], engine, budget=1)
    second = run_statement_harness(qualified_store, [doc_id], engine, budget=1)

    assert first.receipts[0].row_id == second.receipts[0].row_id
    assert qualified_store.conn.execute("SELECT COUNT(*) FROM edges").fetchone()[0] == 1
    assert qualified_store.conn.execute(
        "SELECT COUNT(*) FROM citations WHERE kind='edge'"
    ).fetchone()[0] == 2


def test_live_interface_refuses_unconfigured_provider(qualified_store):
    doc_id = document(qualified_store, "Results\nAgentA reduced cover.")

    with pytest.raises(EngineError, match="not configured"):
        run_statement_harness(qualified_store, [doc_id], None, budget=1, live=True)


def test_strict_parser_never_moves_wrong_entity_span():
    schema = {
        "entity_types": [{"name": "Component", "description": "", "attributes": {}}],
        "relation_types": [],
    }
    raw = json.dumps({
        "entities": [{"name": "B", "entity_type": "Component",
                      "source_span": {"start": 0, "end": 1}}],
        "relations": [],
    })
    chunk = Chunk(0, 0, "A and B")

    strict = parse_and_validate_extraction(raw, schema, chunk, no_relocation=True)
    legacy = parse_and_validate_extraction(raw, schema, chunk)

    assert strict.entities == []
    assert strict.rejections[0]["reason"] == "ungrounded_source_span"
    assert legacy.entities[0].source_span is not None
    assert legacy.entities[0].source_span.start == 6
