"""Emit qualified gold deterministically; never modify the source gold.

Run: uv run python tests/gold/agrochem-polarity/qualify_gold.py
Check committed bytes: append --check.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path


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
            qualifiers=entry["qualifiers"],
            source_row=entry["source_row"],
            original_src=original["src"], original_dst=original["dst"],
        )
    return result


def render(directory: Path) -> str:
    source_bytes = (directory / "gold-fulltext.json").read_bytes()
    mapping = json.loads((directory / "qualified-mapping.json").read_text())
    if hashlib.sha256(source_bytes).hexdigest() != mapping["source_sha256"]:
        raise ValueError("frozen source gold hash changed")
    return json.dumps(derive(json.loads(source_bytes), mapping), ensure_ascii=False, indent=2) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    directory = Path(__file__).resolve().parent
    generated = render(directory)
    if args.check:
        if (directory / "gold-qualified.json").read_text() != generated:
            raise ValueError("committed qualified gold differs from deterministic output")
        print("34 source rows mapped; 0 unmappable; committed bytes match")
    else:
        print(generated, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
