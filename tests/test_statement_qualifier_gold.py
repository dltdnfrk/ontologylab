"""Exact reversible derivation from the frozen full-text corpus."""

import copy
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
    assert script["render"](CORPUS) == (CORPUS / "gold-qualified.json").read_text()
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
