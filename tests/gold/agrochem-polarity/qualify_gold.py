"""Emit versioned gold deterministically; never modify historical gold.

Run: uv run python tests/gold/agrochem-polarity/qualify_gold.py
Use --kind aligned or --kind aligned-qualified for the polarity ruling.
The default qualified output is gold-qualified-normalized.json.
Check the selected committed bytes: append --check.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path

from ontologylab.statement_qualifiers import normalize_statement_qualifiers


def derive(source: dict, mapping: dict) -> dict:
    """Apply the reviewed row table and retain exact inverse coordinates."""
    entries = mapping["rows"]
    if [entry["source_row"] for entry in entries] != list(range(len(source["relations"]))):
        raise ValueError("mapping must cover every source row exactly once in order")
    result = copy.deepcopy(source)
    result["statement_model"] = "biolink-qualified-v1"
    result["description"] = "Qualified statements derived from frozen full-text gold; source findings unchanged."
    result["mapping_source"] = "qualified-mapping.json"
    for original, mapped, entry in zip(source["relations"], result["relations"], entries):
        if entry["source"] != {key: original[key] for key in ("src", "dst", "context")}:
            raise ValueError(f"source row {entry['source_row']} changed since mapping review")
        mapped.update(
            src=entry["core_src"], dst=entry["core_dst"],
            qualifiers=normalize_statement_qualifiers(entry["qualifiers"]),
            source_row=entry["source_row"],
            original_src=original["src"], original_dst=original["dst"],
        )
    return result


def align(source: dict, alignment: dict) -> dict:
    """Change only reviewed polarity labels; retain ambiguous rows verbatim."""
    entries = alignment["rows"]
    if [entry["source_row"] for entry in entries] != list(range(len(source["relations"]))):
        raise ValueError("alignment must cover every source row exactly once in order")
    result = copy.deepcopy(source)
    result["annotation_policy"] = alignment["rule"]
    result["alignment_version"] = alignment["version"]
    result["alignment_source"] = "alignment.json"
    for original, mapped, entry in zip(source["relations"], result["relations"], entries):
        if (entry["old"] != original["polarity"]
                or entry["quote"] != original["span"]["quote"]
                or entry["pmcid"] != original["pmcid"]
                or entry["row"] != entry["source_row"] + 1):
            raise ValueError("source row changed since alignment review")
        if not entry["rationale"].strip():
            raise ValueError("every alignment row needs a rationale")
        if entry["new"] not in ("supports", "refutes", "no_effect"):
            raise ValueError("invalid aligned polarity")
        if entry["status"] not in ("changed", "unchanged", "ambiguous"):
            raise ValueError("invalid alignment status")
        if (entry["old"] != entry["new"]) != (entry["status"] == "changed"):
            raise ValueError("only changed rows may change polarity")
        mapped["polarity"] = entry["new"]
    return result


OUTPUTS = {
    "qualified": "gold-qualified-normalized.json",
    "aligned": "gold-aligned.json",
    "aligned-qualified": "gold-aligned-qualified.json",
}


def render(directory: Path, kind: str = "qualified") -> str:
    source_bytes = (directory / "gold-fulltext.json").read_bytes()
    mapping = json.loads((directory / "qualified-mapping.json").read_text())
    if hashlib.sha256(source_bytes).hexdigest() != mapping["source_sha256"]:
        raise ValueError("frozen source gold hash changed")
    source = json.loads(source_bytes)
    if kind in ("aligned", "aligned-qualified"):
        alignment = json.loads((directory / "alignment.json").read_text())
        if hashlib.sha256(source_bytes).hexdigest() != alignment["source_sha256"]:
            raise ValueError("alignment source gold hash changed")
        source = align(source, alignment)
    if kind != "aligned":
        source = derive(source, mapping)
    return json.dumps(source, ensure_ascii=False, indent=2) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--kind", choices=OUTPUTS, default="qualified")
    args = parser.parse_args()
    directory = Path(__file__).resolve().parent
    generated = render(directory, args.kind)
    if args.check:
        if (directory / OUTPUTS[args.kind]).read_text() != generated:
            raise ValueError("committed gold differs from deterministic output")
        print(f"34 source rows; {OUTPUTS[args.kind]} committed bytes match")
    else:
        print(generated, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
