"""Published annotation integrity and independent statistic boundary checks."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import re
import runpy
import xml.etree.ElementTree as ET

import pytest

from ontologylab.connectors.fulltext import jats_to_text
from ontologylab.polarity_eval import load_polarity_gold, validate_gold
from ontologylab.schemas import AGROCHEM_STATEMENT_QUALIFIERS, preset
from ontologylab.statement_qualifiers import normalize_statement_qualifiers

GOLD = Path(__file__).parent / "gold/agrochem-polarity"
SILVER = GOLD.with_name("agrochem-polarity-silver")
AUDIT = runpy.run_path(str(GOLD / "annotation_audit.py"))


def test_new_fixtures_bind_character_and_byte_spans_and_vocabularies():
    # Given: separately stored new fixtures and the production vocabulary.
    files = [SILVER / "gold-silver.json", SILVER / "gold-silver-qualified.json"]
    files.extend(GOLD.glob("gold-adjudicated*.json"))
    # When / Then: validate through the existing scorer as well as character slicing.
    for path in files:
        raw = json.loads(path.read_text())
        assert validate_gold(path, qualified=True)["spans_verified"] == len(raw["relations"])
        for row in raw["relations"]:
            text = (path.parent / next(
                p["source"] for p in raw["papers"] if p["pmcid"] == row["pmcid"]
            )).read_text()
            quote = row["span"]["quote"]
            assert text.encode()[row["span"]["start"]:row["span"]["end"]] == quote.encode()
            if "char_start" in row:
                assert text[row["char_start"]:row["char_end"]] == quote
            assert set(row.get("qualifiers", {})) <= set(AGROCHEM_STATEMENT_QUALIFIERS)
            assert row["polarity"] in {"supports", "no_effect", "refutes"}
            for key, value in row.get("qualifier_quotes", {}).items():
                assert value and value in quote
                assert normalize_statement_qualifiers({key: value}) == normalize_statement_qualifiers(
                    {key: row["qualifiers"][key]}
                )


def test_silver_is_separate_from_human_gold_and_both_load():
    # Given: distinct provenance and directories, not a score threshold change.
    human = load_polarity_gold(GOLD / "gold-aligned-qualified.json", qualified=True)
    raw = json.loads((SILVER / "gold-silver.json").read_text())
    # When
    silver = load_polarity_gold(SILVER / "gold-silver-qualified.json", qualified=True)
    # Then
    assert GOLD.resolve() != SILVER.resolve()
    assert raw["silver"] == "model-annotated, not human ground truth"
    assert human.papers == 5
    assert silver.papers >= 10
    assert not (GOLD / "gold-silver.json").exists()
    assert not (SILVER / "gold-aligned.json").exists()
    human_ids = {p["pmcid"] for p in json.loads((GOLD / "gold-aligned.json").read_text())["papers"]}
    assert human_ids.isdisjoint(p["pmcid"] for p in raw["papers"])


def test_qualified_sibling_only_normalizes_existing_values():
    # Given: the source-valued annotation and its canonical sibling.
    raw = json.loads((SILVER / "gold-silver.json").read_text())
    qualified = json.loads((SILVER / "gold-silver-qualified.json").read_text())
    # When / Then: canonicalization cannot invent or discard a statement.
    assert raw["papers"] == qualified["papers"]
    assert len(raw["relations"]) == len(qualified["relations"])
    for before, after in zip(raw["relations"], qualified["relations"], strict=True):
        expected = copy.deepcopy(before)
        expected["qualifiers"] = normalize_statement_qualifiers(before["qualifiers"])
        assert after == expected


def test_manifest_license_and_complete_body_are_reproducible():
    # Given: original JATS responses (one storage LF) and complete converted bodies.
    manifest = json.loads((SILVER / "sources/full/manifest.json").read_text())
    assert len(manifest["papers"]) >= 10
    for paper in manifest["papers"]:
        stored = (SILVER / "sources/full" / f"{paper['pmcid']}.xml").read_bytes()
        # When: independently recompute licenses, attribution and conversion.
        assert hashlib.sha256(stored).hexdigest() == paper["stored_jats_sha256"]
        assert hashlib.sha256(stored[:-1]).hexdigest() == paper["jats_sha256"]
        tree = ET.fromstring(stored)
        meta = tree.find("front/article-meta")
        assert meta is not None
        licenses = meta.findall(".//license")
        assert licenses
        license_xml = " ".join(ET.tostring(item, encoding="unicode") for item in licenses)
        assert ("creativecommons.org/licenses/by/4.0/" in license_xml
                or "Creative Commons Attribution 4.0 International" in license_xml)
        assert "by-nc" not in license_xml and "NonCommercial" not in license_xml
        assert paper["license"] == "CC-BY-4.0"
        authors = [
            " ".join("".join(n.itertext()) for n in author.findall("name/*"))
            for group in meta.findall("contrib-group")
            if group.get("content-type", "author") == "author"
            for author in group.findall("contrib")
            if author.get("contrib-type", "author") == "author"
        ]
        assert authors == paper["authors"] and authors
        body = tree.find("body")
        assert body is not None
        wrapper = ET.Element("article")
        wrapper.append(body)
        converted = (jats_to_text(ET.tostring(wrapper, encoding="unicode")) + "\n").encode()
        # Then: the stored source is the complete conversion, not a selected excerpt.
        assert (SILVER / paper["source"]).read_bytes() == converted
        assert hashlib.sha256(converted).hexdigest() == paper["source_sha256"]
        assert len(converted) == paper["source_bytes"]


def test_silver_assertions_are_outside_methods_sections():
    # Given: section boundaries supplied independently by the published JATS.
    raw = json.loads((SILVER / "gold-silver.json").read_text())
    eligible = {}
    for paper in raw["papers"]:
        tree = ET.parse(SILVER / "sources/full" / f"{paper['pmcid']}.xml")
        sections = []
        for section in tree.findall(".//body//sec"):
            title = section.find("title")
            heading = "".join(title.itertext()) if title is not None else ""
            if re.search(r"\b(results?|discussion|conclusions?)\b", heading, re.IGNORECASE):
                wrapper = ET.Element("article")
                body = ET.SubElement(wrapper, "body")
                body.append(section)
                sections.append(jats_to_text(ET.tostring(wrapper, encoding="unicode")))
        eligible[paper["pmcid"]] = sections
    # When / Then: no selected quote comes only from methods or preparation text.
    for row in raw["relations"]:
        assert any(row["span"]["quote"] in section for section in eligible[row["pmcid"]])


def _row(polarity: str = "supports", *, number: int = 0) -> dict:
    return {
        "pmcid": "PMC1", "src": f"product {number}", "src_type": "Product",
        "relation": "controls", "dst": "weed", "dst_type": "Weed",
        "polarity": polarity, "quote": "Product controls weed in greenhouse.",
        "qualifiers": {"study_context": "greenhouse"},
        "qualifier_quotes": {"study_context": "greenhouse"},
        "rationale": "Published outcome.",
    }


def test_kappa_matches_hand_calculated_margins_without_label_based_pairing():
    # Given: 3/4 agreement, expected chance 5/16, hence kappa 7/11.
    a = [_row(p, number=i) for i, p in enumerate(("supports", "supports", "no_effect", "refutes"))]
    b = [_row(p, number=i) for i, p in enumerate(("supports", "no_effect", "no_effect", "refutes"))]
    # When
    result = AUDIT["agreement"](a, b)
    # Then
    assert result["reciprocal_scope_pairs"] == 4
    assert result["observed_polarity_agreement"] == 0.75
    assert result["expected_polarity_agreement"] == 5 / 16
    assert result["kappa"] == pytest.approx(7 / 11)
    assert result["polarity_disagreements"] == 1
    assert AUDIT["agreement"]([], [])["kappa"] is None
    assert AUDIT["agreement"]([_row()], [_row()])["kappa"] is None


def test_subset_match_is_directional_and_does_not_reuse_a_pair():
    # Given: production permits extra predicted scope but not missing scope.
    broad = _row()
    narrow = copy.deepcopy(broad)
    narrow["qualifiers"]["dose"] = "1x"
    # When
    result = AUDIT["agreement"]([broad], [narrow])
    # Then
    assert result["b_matches_a"]["rate"] == 1
    assert result["a_matches_b"]["rate"] == 0
    assert result["reciprocal_scope_pairs"] == 0
    assert len(AUDIT["matched_pairs"]([broad, broad], [broad])) == 1
    narrow["pmcid"] = "PMC2"
    assert not AUDIT["covers"](broad, narrow, polarity=False)


def test_repeated_literal_evidence_uses_first_occurrence_without_extra_votes():
    # Given: the same published sentence repeated without changing its scope.
    row = _row()
    text = row["quote"] + "\n" + row["quote"]
    # When
    bound = AUDIT["bind_annotation"](row, text)
    # Then: the citation is explicit, not an extra annotation or ambiguous offset.
    assert bound["quote_occurrences"] == 2
    assert bound["char_start"] == bound["span"]["start"] == 0
    assert text[bound["char_start"]:bound["char_end"]] == row["quote"]
    result = AUDIT["agreement"]([row, copy.deepcopy(row)], [row])
    assert result["a_annotation_rows"] == 2
    assert result["a_statements"] == result["b_statements"] == 1
    assert result["reciprocal_statement_match_rate"] == 1


def test_source_binding_repairs_preserve_submitted_labels_and_exact_quotes():
    # Given: the preserved submission, including swapped paper IDs.
    submitted = json.loads((SILVER / "annotations/annotator-b-submitted.json").read_text())
    bound = json.loads((SILVER / "annotations/annotator-b.json").read_text())
    repairs = {item["index"]: item for item in bound["source_binding_corrections"]}
    # When / Then: only paper IDs change, each independently resolved by literal text.
    assert repairs
    for index, (old, new) in enumerate(zip(submitted["relations"], bound["relations"], strict=True)):
        expected = copy.deepcopy(old)
        if index in repairs:
            fix = repairs[index]
            assert old["pmcid"] == fix["submitted"]
            expected["pmcid"] = fix["bound"]
            assert old["quote"] not in (SILVER / "sources/full" / f"{old['pmcid']}.txt").read_text()
            assert old["quote"] in (SILVER / "sources/full" / f"{new['pmcid']}.txt").read_text()
        assert new == expected


@pytest.mark.parametrize("damage", ["quote", "key", "value", "polarity", "entity"])
def test_binding_rejects_deliberately_corrupted_annotation(damage: str):
    # Given: one valid literal sentence and one deliberate fault.
    row = _row()
    text = "Intro: α.\n" + row["quote"]
    expected = AUDIT["bind_annotation"](row, text)
    assert expected["span"]["start"] == len("Intro: α.\n".encode())
    assert expected["char_start"] == len("Intro: α.\n")
    if damage == "quote":
        row["quote"] = "Invented outcome."
    elif damage == "key":
        row["qualifiers"] = {"invented": "greenhouse"}
        row["qualifier_quotes"] = {"invented": "greenhouse"}
    elif damage == "value":
        row["qualifiers"]["study_context"] = "field_trial"
    elif damage == "polarity":
        row["polarity"] = "probably"
    else:
        row["dst_type"] = "InventedType"
    # When / Then: the same boundary that validates committed rows rejects the fault.
    with pytest.raises(AUDIT["InvalidAnnotation"]):
        AUDIT["bind_annotation"](row, text)


def test_pre_adjudication_receipts_recompute_and_old_gold_is_immutable():
    # Given / When: the checker recomputes metrics from the raw blind outputs.
    result = AUDIT["check"]()
    # Then: both provenance classes are exercised through the production loader.
    assert result["gold-silver-qualified.json"]["papers"] >= 10
    assert result["agrochem-polarity"]["agreement"]["a_statements"] > 0


def test_gold_changes_are_only_explicit_adjudicated_source_scope():
    # Given: immutable reference rows and separately versioned adjudication.
    changes = json.loads((GOLD / "gold-change-record.json").read_text())["changes"]
    decisions = {d["id"]: d for d in json.loads(
        (GOLD / "annotations/adjudication.json").read_text()
    )["decisions"]}
    allowed = {"polarity", "qualifiers", "qualifier_quotes", "char_start", "char_end",
               "annotation_decision"}
    # When / Then: every changed field is traceable; unreviewed rows stay verbatim.
    for before_file, after_file in (
        ("gold-aligned.json", "gold-adjudicated.json"),
        ("gold-aligned-qualified.json", "gold-adjudicated-qualified.json"),
    ):
        before = json.loads((GOLD / before_file).read_text())
        after = json.loads((GOLD / after_file).read_text())
        assert before["papers"] == after["papers"]
        by_row = {change["source_row"]: change for change in changes}
        assert len(by_row) == len(changes)
        for index, (old, new) in enumerate(zip(before["relations"], after["relations"], strict=True)):
            if index not in by_row:
                assert new == old
                continue
            change = by_row[index]
            assert change["rationale"] == decisions[change["decision"]]["rationale"]
            assert new["annotation_decision"] == change["decision"]
            assert {k: v for k, v in new.items() if k not in allowed} == {
                k: v for k, v in old.items() if k not in allowed
            }
            annotation = change["annotation"]["annotation"]
            assert new["polarity"] == annotation["polarity"]
            assert normalize_statement_qualifiers(new["qualifiers"]) == change["after"]["qualifiers"]
            assert new["span"]["quote"] == annotation["quote"]


def test_blind_vocabulary_is_exactly_the_existing_schema():
    # Given: the frozen vocabulary received by annotators.
    vocabulary = json.loads((GOLD / "annotation-vocabulary.json").read_text())
    # When / Then: machine-consumed values equal the product's existing vocabulary.
    schema = preset("agrochem-v2")
    assert set(vocabulary["qualifier_keys"]) == set(AGROCHEM_STATEMENT_QUALIFIERS)
    assert set(vocabulary["claim_relations"]) == {
        item["name"] for item in schema["relation_types"] if "polarity" in item["qualifiers"]
    }
    assert set(vocabulary["entity_types"]) == {
        item["name"] for item in schema["entity_types"] if item.get("extractable", True)
    }
