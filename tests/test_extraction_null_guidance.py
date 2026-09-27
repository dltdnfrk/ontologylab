"""Offline prompt delivery and statement persistence, not model recall."""

from __future__ import annotations

import json
from pathlib import Path
import re

import pytest

from ontologylab import extractor
from ontologylab.schemas import preset
from tests.test_engine_json_retry import CountingEngine, drive
from tests.test_statement_qualifier_validation import qualified_store


@pytest.mark.parametrize("block_name", ["_MULTI_ARM_GUIDANCE", "_POLARITY_GUIDANCE"])
def test_prompt_ships_comparison_and_precedence_blocks(qualified_store, block_name):
    # Shipped-copy equality permits rewording; missing delivery must fail.
    block = getattr(extractor, block_name)
    assert block.strip()
    for schema in (preset("agrochem-v2"), qualified_store.get_schema()):
        prompt = extractor.build_extraction_prompt(schema, "No findings.")
        assert prompt.count(block) == 1


def test_prompt_delivers_nonempty_background_section(qualified_store):
    for schema in (preset("agrochem-v2"), qualified_store.get_schema()):
        prompt = extractor.build_extraction_prompt(schema, "No findings.")
        sections = re.findall(
            r"<background-separation>\n(.*?)</background-separation>",
            prompt, flags=re.DOTALL,
        )
        assert len(sections) == 1
        # Check the section contract and shipped copy, never editorial wording.
        assert sections[0].strip()
        assert sections[0] == extractor._BACKGROUND_GUIDANCE


def test_extraction_prompt_version():
    assert extractor.PROMPT_VERSION == "extract-v7"


def _persist_statements(store, tmp_path, sentences, qualifiers):
    text = " ".join(sentences)
    entities = [
        {"name": "Agent Cedar", "entity_type": "ActiveIngredient"},
        {"name": "Beetle delta", "entity_type": "Pest"},
    ]
    relations = [
        {
            "source": entities[0], "target": entities[1],
            "relation_type": "controls", "qualifiers": scope,
            "source_span": {
                "start": text.index(sentence),
                "end": text.index(sentence) + len(sentence),
            },
        }
        for sentence, scope in zip(sentences, qualifiers, strict=True)
    ]
    engine = CountingEngine([json.dumps({"entities": entities, "relations": relations})])

    outcome, _ = drive(store, tmp_path, engine, text=text)

    assert outcome == "" and not outcome.chunk_failed
    assert engine.calls == 1
    rows = store.conn.execute("SELECT * FROM edges").fetchall()
    assert len(rows) == len(sentences)
    assert len({row["id"] for row in rows}) == len(sentences)
    # Core endpoints are shared; only the statements differ.
    assert len({(row["src_node_id"], row["dst_node_id"]) for row in rows}) == 1
    assert {row["relation_type"] for row in rows} == {"controls"}
    assert {row["status"] for row in rows} == {"proposed"}
    assert {row["prompt_version"] for row in rows} == {"extract-v7"}
    assert {
        json.dumps(json.loads(row["qualifiers_json"]), sort_keys=True) for row in rows
    } == {json.dumps(scope, sort_keys=True) for scope in qualifiers}
    assert store.conn.execute("SELECT COUNT(*) FROM nodes").fetchone()[0] == 2
    for row in rows:
        scope = json.loads(row["qualifiers_json"])
        expected_sentence = sentences[qualifiers.index(scope)]
        citations = store.citations("edge", row["id"])
        assert len(citations) == 1
        span = citations[0]["source_span"]
        assert text[span["start"]:span["end"]] == expected_sentence


@pytest.mark.parametrize("slot, labels, sentences", [
    (
        "population_context_qualifier",
        ("susceptible population", "resistant population"),
        (
            "Agent Cedar controlled Beetle delta in the susceptible population.",
            "Agent Cedar was ineffective against Beetle delta in the resistant population.",
        ),
    ),
    (
        "object_form_or_variant_qualifier",
        ("larvae", "adults"),
        (
            "Agent Cedar controlled Beetle delta larvae.",
            "Agent Cedar was ineffective against Beetle delta adults.",
        ),
    ),
])
def test_scripted_comparison_persists_positive_and_null_arms(
    qualified_store, tmp_path, slot, labels, sentences,
):
    _persist_statements(qualified_store, tmp_path, sentences, [
        {"polarity": "supports", slot: labels[0]},
        {"polarity": "no_effect", slot: labels[1]},
    ])


def test_scripted_null_arms_do_not_merge_even_with_equal_polarity(
    qualified_store, tmp_path,
):
    _persist_statements(qualified_store, tmp_path, (
        "Agent Cedar was ineffective against Beetle delta in the northern population.",
        "Agent Cedar was ineffective against Beetle delta in the southern population.",
    ), [
        {"polarity": "no_effect", "population_context_qualifier": "northern population"},
        {"polarity": "no_effect", "population_context_qualifier": "southern population"},
    ])


@pytest.mark.parametrize("finding, polarity", [
    ("Agent Cedar was ineffective against Beetle delta in the orchard trial.", "no_effect"),
    ("Agent Cedar controlled Beetle delta in the orchard trial.", "supports"),
])
def test_scripted_background_is_distinct_from_the_finding(
    qualified_store, tmp_path, finding, polarity,
):
    # The supports/supports case proves context separation independently of polarity.
    _persist_statements(qualified_store, tmp_path, (
        "Background: Agent Cedar is described as controlling Beetle delta.",
        finding,
    ), [
        {"polarity": "supports", "study_context": "background"},
        {"polarity": polarity, "study_context": "orchard trial"},
    ])
    rows = qualified_store.conn.execute("SELECT qualifiers_json FROM edges").fetchall()
    assert {
        scope["study_context"]: scope["polarity"]
        for row in rows
        for scope in [json.loads(row["qualifiers_json"])]
    } == {"background": "supports", "orchard trial": polarity}


def _seven_word_sequences(text: str) -> set[tuple[str, ...]]:
    words = re.findall(r"\w+", text.casefold())
    return {tuple(words[index:index + 7]) for index in range(len(words) - 6)}


def test_few_shots_have_no_seven_word_overlap_with_frozen_gold():
    # Scan every committed corpus file, including full source bodies and labels.
    gold_root = Path(__file__).parent / "gold" / "agrochem-polarity"
    files = sorted(path for path in gold_root.rglob("*") if path.is_file())
    assert files
    examples = extractor._FEW_SHOT + "\n" + extractor._AGROCHEM_GUIDANCE
    example_sequences = _seven_word_sequences(examples)
    assert example_sequences
    for path in files:
        overlap = example_sequences & _seven_word_sequences(path.read_text(encoding="utf-8"))
        assert not overlap, (str(path.relative_to(gold_root)), sorted(overlap))


def test_overlap_guard_detects_a_seven_word_copy():
    # Constructed positive/negative controls keep the scanner from passing vacuously.
    source = "cedar elm birch ash maple oak willow"
    assert _seven_word_sequences(source) & _seven_word_sequences(source.upper() + ".")
    assert not _seven_word_sequences(source) & _seven_word_sequences(
        "cedar elm birch ash maple oak spruce"
    )
