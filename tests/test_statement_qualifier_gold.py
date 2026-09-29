"""Exact reversible derivation from the frozen full-text corpus."""

import copy
import hashlib
import json
from pathlib import Path
import runpy

import pytest

from ontologylab.polarity_eval import validate_gold

CORPUS = Path(__file__).parent / "gold" / "agrochem-polarity"


def test_every_qualified_row_maps_back_to_unchanged_source():
    source = json.loads((CORPUS / "gold-fulltext.json").read_text())
    qualified = json.loads((CORPUS / "gold-qualified.json").read_text())
    assert len(qualified["relations"]) == len(source["relations"]) == 34
    assert qualified["papers"] == source["papers"]
    for index, row in enumerate(qualified["relations"]):
        recovered = dict(row)
        assert recovered.pop("source_row") == index
        recovered["src"] = recovered.pop("original_src")
        recovered["dst"] = recovered.pop("original_dst")
        recovered.pop("qualifiers")
        assert recovered == source["relations"][index]
    assert validate_gold(CORPUS / "gold-qualified.json", qualified=True)["spans_verified"] == 34


def test_generator_reproduces_committed_bytes_and_rejects_incomplete_mapping():
    script = runpy.run_path(str(CORPUS / "qualify_gold.py"))
    assert script["render"](CORPUS) == (CORPUS / "gold-qualified-normalized.json").read_text()
    source = json.loads((CORPUS / "gold-fulltext.json").read_text())
    mapping = json.loads((CORPUS / "qualified-mapping.json").read_text())
    broken = copy.deepcopy(mapping)
    broken["rows"] = broken["rows"][:-1]
    with pytest.raises(ValueError, match="every source row"):
        script["derive"](source, broken)
    broken = copy.deepcopy(mapping)
    broken["rows"][0]["source"]["dst"] = "Different source finding"
    with pytest.raises(ValueError, match="changed since mapping"):
        script["derive"](source, broken)


def test_alignment_changes_only_reviewed_labels_and_preserves_field_bytes():
    # Given: independent adjudication coordinates and immutable source rows.
    source = json.loads((CORPUS / "gold-fulltext.json").read_text())
    table = json.loads((CORPUS / "alignment.json").read_text())
    script = runpy.run_path(str(CORPUS / "qualify_gold.py"))
    # When: exercise the actual derivation, so dropping alignment cannot pass.
    generated = script["render"](CORPUS, "aligned")
    aligned = json.loads(generated)
    # Then: exact reviewed decisions, every rationale, and no collateral edits.
    assert generated.encode() == (CORPUS / "gold-aligned.json").read_bytes()
    assert len(table["rows"]) == len(aligned["relations"]) == 34
    assert [r["row"] for r in table["rows"]] == list(range(1, 35))
    assert [r["row"] for r in table["rows"] if r["status"] == "ambiguous"] == []
    changes = []
    for index, (old, new, review) in enumerate(zip(
        source["relations"], aligned["relations"], table["rows"], strict=True,
    )):
        assert review["source_row"] == index
        assert review["rationale"].strip()
        assert (review["quote"], review["old"], review["new"]) == (
            old["span"]["quote"], old["polarity"], new["polarity"],
        )
        expected = copy.deepcopy(old)
        if index in (10, 22, 28, 29, 30):
            expected["polarity"] = "no_effect"
            changes.append((index + 1, old["polarity"], new["polarity"]))
            assert review["status"] == "changed"
        else:
            assert review["status"] in ("unchanged", "ambiguous")
        assert json.dumps(new, ensure_ascii=False).encode() == json.dumps(
            expected, ensure_ascii=False,
        ).encode()
        context = review["context_evidence"]
        body = (CORPUS / context["source"]).read_bytes()
        assert body[old["span"]["start"]:old["span"]["end"]] == review["quote"].encode()
        assert review["quote"].encode() in body[context["start"]:context["end"]]
    assert changes == [
        (11, "refutes", "no_effect"), (23, "refutes", "no_effect"),
        (29, "refutes", "no_effect"), (30, "refutes", "no_effect"),
        (31, "refutes", "no_effect"),
    ]
    assert aligned["papers"] == source["papers"]
    assert validate_gold(CORPUS / "gold-aligned.json")["spans_verified"] == 34


@pytest.mark.parametrize("damage", ["missing_row", "missing_rationale", "changed_quote", "ambiguous_change"])
def test_alignment_rejects_unreviewed_changes(damage):
    # Given: a malformed copy of the review table.
    source = json.loads((CORPUS / "gold-fulltext.json").read_text())
    table = json.loads((CORPUS / "alignment.json").read_text())
    if damage == "missing_row":
        table["rows"].pop()
    elif damage == "missing_rationale":
        table["rows"][10]["rationale"] = ""
    elif damage == "changed_quote":
        table["rows"][10]["quote"] = "Different evidence"
    else:
        table["rows"][28]["status"] = "ambiguous"
    # When / Then: no artifact can be produced from unreviewed edits.
    script = runpy.run_path(str(CORPUS / "qualify_gold.py"))
    with pytest.raises(ValueError):
        script["align"](source, table)


@pytest.mark.parametrize("kind,filename", [
    ("qualified", "gold-qualified-normalized.json"),
    ("aligned-qualified", "gold-aligned-qualified.json"),
])
def test_qualified_derivations_preserve_all_non_dose_scope(kind, filename):
    # Given: the historical qualified artifact, not a freshly derived oracle.
    old = json.loads((CORPUS / "gold-qualified.json").read_text())
    script = runpy.run_path(str(CORPUS / "qualify_gold.py"))
    # When
    rendered = script["render"](CORPUS, kind)
    new = json.loads(rendered)
    # Then: only the reviewed labels and three reference-rate surfaces change.
    assert rendered.encode() == (CORPUS / filename).read_bytes()
    for index, (before, after) in enumerate(zip(old["relations"], new["relations"], strict=True)):
        expected = copy.deepcopy(before)
        if index in (13, 14, 15):
            expected["qualifiers"]["dose"] = "1x_label_rate"
        if kind == "aligned-qualified" and index in (10, 22, 28, 29, 30):
            expected["polarity"] = "no_effect"
        assert json.dumps(after, ensure_ascii=False).encode() == json.dumps(
            expected, ensure_ascii=False,
        ).encode()
    assert validate_gold(CORPUS / filename, qualified=True)["spans_verified"] == 34


@pytest.mark.parametrize("filename,digest", [
    ("gold.json", "c899bc553773f2ee4986d0d808165c7791ad7e5cd9c8ba8ff7a9187458a55203"),
    ("gold-fulltext.json", "cf7ea33f227540f201f2142eb7fa640bf08a1edf3cb039528c3b4828796f4f23"),
    ("gold-qualified.json", "04601aa947fc465013eb77f2d4b10dde277c32990151ca267f8e572956836295"),
    ("qualified-mapping.json", "0cc618356dd343ac56ef6a86c8f76a812bd38b832a15ce8082f9e94650d80b08"),
])
def test_historical_gold_and_mapping_remain_byte_identical(filename, digest):
    # Given / When / Then: bind the pre-alignment archival bytes.
    assert hashlib.sha256((CORPUS / filename).read_bytes()).hexdigest() == digest
