"""P0 — the measurement everything else depends on.

Extraction quality was unmeasured: the pipeline could be "improved" and
nobody could say whether precision or recall moved, or in which direction.
Every algorithm swap this repository plans (Leiden, reranking, ER blocking)
is only an improvement if a number moves, so the number comes first.

The unit of measurement is the **normalized triple**. Entities compare on
``normalize_name`` — the same normalization the store's own entity
resolution uses, so the harness cannot disagree with the pipeline about
what "the same name" means. Triples compare on
``(src_norm, relation_type, dst_norm)``; relation types are schema-
controlled strings and compare exactly.

A gold file is deliberately plain JSON a person can write by hand::

    {
      "entities": [{"name": "OrderApp"}, ...],
      "triples":  [{"src": "OrderApp", "relation": "part_of",
                    "dst": "KitchenDisplay"}, ...]
    }

Conventions when a denominator is zero: if both sides are empty the score
is 1.0 (nothing to find, nothing found — perfect); if exactly one side is
empty the score is 0.0. Stated here because silently choosing one is how
two evaluation scripts end up disagreeing about the same run.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ontologylab.kgstore import KGStore, normalize_name

# How many missing/spurious examples to carry in a report. The lists exist
# so a bad score is actionable ("which triples did it miss?"), not to dump
# the whole corpus into a terminal.
MAX_EXAMPLES = 20


class GoldError(Exception):
    """Raised when a gold file cannot be read or is malformed."""


@dataclass(frozen=True)
class Gold:
    """A hand-written reference: what extraction *should* have produced."""

    entities: frozenset[str]  # normalized names
    triples: frozenset[tuple[str, str, str]]  # (src_norm, relation, dst_norm)
    path: str = ""


def load_gold(path: str | Path) -> Gold:
    """Read and normalize a gold JSON file."""
    p = Path(path)
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise GoldError(f"gold file not found: {p}") from exc
    except json.JSONDecodeError as exc:
        raise GoldError(f"gold file is not valid JSON: {p}: {exc}") from exc
    if not isinstance(raw, dict):
        raise GoldError(f"gold file must be a JSON object: {p}")

    entities: set[str] = set()
    for item in raw.get("entities", []):
        name = item.get("name") if isinstance(item, dict) else None
        if not name or not isinstance(name, str):
            raise GoldError(f"gold entity needs a string 'name': {item!r}")
        entities.add(normalize_name(name))

    triples: set[tuple[str, str, str]] = set()
    for item in raw.get("triples", []):
        if not isinstance(item, dict):
            raise GoldError(f"gold triple must be an object: {item!r}")
        try:
            src, relation, dst = item["src"], item["relation"], item["dst"]
        except KeyError as exc:
            raise GoldError(f"gold triple needs src/relation/dst: {item!r}") from exc
        triples.add((normalize_name(src), str(relation), normalize_name(dst)))

    if not entities and not triples:
        raise GoldError(f"gold file has no entities and no triples: {p}")
    return Gold(entities=frozenset(entities), triples=frozenset(triples),
                path=str(p))


def store_view(
    store: KGStore, *, include_proposed: bool = True
) -> tuple[set[str], set[tuple[str, str, str]]]:
    """What the store currently holds, in the gold file's terms.

    ``include_proposed=True`` is the default because this harness measures
    the *extractor*: proposals are its raw output, and scoring only what a
    human already approved would measure the reviewer instead.
    """
    statuses = ("proposed", "verified") if include_proposed else ("verified",)
    marks = ",".join("?" for _ in statuses)

    entities = {
        row["normalized_name"]
        for row in store.conn.execute(
            f"SELECT normalized_name FROM nodes WHERE status IN ({marks})",
            statuses,
        )
    }
    triples = {
        (row["src_norm"], row["relation_type"], row["dst_norm"])
        for row in store.conn.execute(
            f"""
            SELECT s.normalized_name AS src_norm, e.relation_type,
                   d.normalized_name AS dst_norm
            FROM edges e
            JOIN nodes s ON s.id = e.src_node_id
            JOIN nodes d ON d.id = e.dst_node_id
            WHERE e.status IN ({marks})
            """,
            statuses,
        )
    }
    return entities, triples


def _prf(gold: frozenset, found: set) -> dict[str, float]:
    """Precision/recall/F1 with the zero conventions from the module doc."""
    if not gold and not found:
        return {"precision": 1.0, "recall": 1.0, "f1": 1.0}
    true_positives = len(gold & found)
    precision = true_positives / len(found) if found else 0.0
    recall = true_positives / len(gold) if gold else 0.0
    f1 = (
        2 * precision * recall / (precision + recall)
        if (precision + recall) > 0
        else 0.0
    )
    return {"precision": precision, "recall": recall, "f1": f1}


@dataclass
class Report:
    """One evaluation of one store against one gold file."""

    entity: dict[str, float]
    triple: dict[str, float]
    counts: dict[str, int]
    missing_triples: list[tuple[str, str, str]] = field(default_factory=list)
    spurious_triples: list[tuple[str, str, str]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "entity": {k: round(v, 4) for k, v in self.entity.items()},
            "triple": {k: round(v, 4) for k, v in self.triple.items()},
            "counts": dict(self.counts),
            "missing_triples": [list(t) for t in self.missing_triples],
            "spurious_triples": [list(t) for t in self.spurious_triples],
        }


def evaluate_store(
    store: KGStore, gold: Gold, *, include_proposed: bool = True
) -> Report:
    """Score the store's extractions against the gold reference."""
    found_entities, found_triples = store_view(
        store, include_proposed=include_proposed
    )
    return Report(
        entity=_prf(gold.entities, found_entities),
        triple=_prf(gold.triples, found_triples),
        counts={
            "gold_entities": len(gold.entities),
            "found_entities": len(found_entities),
            "gold_triples": len(gold.triples),
            "found_triples": len(found_triples),
        },
        missing_triples=sorted(gold.triples - found_triples)[:MAX_EXAMPLES],
        spurious_triples=sorted(found_triples - gold.triples)[:MAX_EXAMPLES],
    )


__all__ = [
    "Gold",
    "GoldError",
    "MAX_EXAMPLES",
    "Report",
    "evaluate_store",
    "load_gold",
    "store_view",
]
