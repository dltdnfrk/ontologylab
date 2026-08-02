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
import random
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


def canonical_decode_params(params: dict[str, Any] | None) -> str | None:
    """The stored form of a sampler setting: key-sorted, space-free JSON.

    Must stay byte-identical to what ``KGStore.insert_proposed`` writes, or
    a filter would never match the rows it names.
    """
    if params is None:
        return None
    return json.dumps(params, sort_keys=True, separators=(",", ":"))


def _stream_clause(
    alias: str,
    engine: str | None,
    model: str | None,
    prompt_version: str | None,
    decode_params: str | None = None,
) -> tuple[str, list[str]]:
    """SQL fragment + params restricting ``alias`` to one extractor stream.

    A None filter is absent, not a match against NULL: "no engine given"
    means "score every engine", which is what an unfiltered report has
    always meant.
    """
    clauses: list[str] = []
    params: list[str] = []
    for column, value in (
        ("extractor_engine", engine),
        ("extractor_model", model),
        ("prompt_version", prompt_version),
        ("decode_params", decode_params),
    ):
        if value is not None:
            clauses.append(f"AND {alias}.{column} = ?")
            params.append(value)
    return " ".join(clauses), params


def store_view(
    store: KGStore,
    *,
    include_proposed: bool = True,
    engine: str | None = None,
    model: str | None = None,
    prompt_version: str | None = None,
    decode_params: dict[str, Any] | None = None,
) -> tuple[set[str], set[tuple[str, str, str]]]:
    """What the store currently holds, in the gold file's terms.

    ``include_proposed=True`` is the default because this harness measures
    the *extractor*: proposals are its raw output, and scoring only what a
    human already approved would measure the reviewer instead.

    The stream filters exist because one store can hold several extractors'
    output. Scored together, one engine's hits mask another's misses and the
    number names neither of them — the same mixing that made the conformal
    calibration set meaningless. A triple is attributed by its *edge*'s
    stream, since that is the row the extractor actually proposed.
    """
    statuses = ("proposed", "verified") if include_proposed else ("verified",)
    marks = ",".join("?" for _ in statuses)
    decode_json = canonical_decode_params(decode_params)
    node_clause, node_params = _stream_clause(
        "n", engine, model, prompt_version, decode_json
    )
    edge_clause, edge_params = _stream_clause(
        "e", engine, model, prompt_version, decode_json
    )

    entities = {
        row["normalized_name"]
        for row in store.conn.execute(
            f"""
            SELECT n.normalized_name
            FROM nodes n
            WHERE n.status IN ({marks}) {node_clause}
            """,
            (*statuses, *node_params),
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
            WHERE e.status IN ({marks}) {edge_clause}
            """,
            (*statuses, *edge_params),
        )
    }
    return entities, triples


# Bootstrap parameters. 2000 resamples puts the Monte-Carlo error of a 95%
# percentile bound well under a point of F1; the seed makes every report of
# the same store+gold identical, which is what lets two runs be compared.
BOOTSTRAP_RESAMPLES = 2000
BOOTSTRAP_SEED = 7
CONFIDENCE_LEVEL = 0.95


def bootstrap_f1_interval(
    gold: frozenset,
    found: set,
    *,
    n_resamples: int = BOOTSTRAP_RESAMPLES,
    seed: int = BOOTSTRAP_SEED,
    confidence: float = CONFIDENCE_LEVEL,
) -> dict[str, float]:
    """Percentile-bootstrap interval for F1 over the evaluation units.

    A gold set a person can actually write has tens of triples, and at that
    size the difference between F1 0.72 and 0.75 is routinely noise. A point
    estimate cannot say so; an interval can — "improved" becomes a claim
    about non-overlapping intervals instead of a mood, which was the whole
    reason P0 exists.

    The resampling unit is the individual outcome (each true positive,
    false positive and false negative), drawn with replacement — the case
    bootstrap. It treats items as independent, which ignores that triples
    from one document rise and fall together; the interval is therefore, if
    anything, a little narrow. Stated here so nobody mistakes it for a
    document-level bootstrap.
    """
    true_positives = len(gold & found)
    false_positives = len(found - gold)
    false_negatives = len(gold - found)
    total = true_positives + false_positives + false_negatives
    if total == 0:
        # Nothing to find and nothing found: F1 is 1.0 by the module's
        # convention, with no sampling variability to speak of.
        return {"low": 1.0, "high": 1.0}

    outcomes = (
        ["tp"] * true_positives
        + ["fp"] * false_positives
        + ["fn"] * false_negatives
    )
    rng = random.Random(seed)
    f1_samples: list[float] = []
    for _ in range(n_resamples):
        tp = fp = fn = 0
        for _ in range(total):
            outcome = outcomes[rng.randrange(total)]
            if outcome == "tp":
                tp += 1
            elif outcome == "fp":
                fp += 1
            else:
                fn += 1
        precision = tp / (tp + fp) if tp + fp else 0.0
        recall = tp / (tp + fn) if tp + fn else 0.0
        f1_samples.append(
            2 * precision * recall / (precision + recall)
            if (precision + recall) > 0
            else 0.0
        )
    f1_samples.sort()
    tail = (1.0 - confidence) / 2.0
    low_index = int(tail * n_resamples)
    high_index = min(n_resamples - 1, int((1.0 - tail) * n_resamples) - 1)
    return {
        "low": round(f1_samples[low_index], 4),
        "high": round(f1_samples[high_index], 4),
    }


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
    entity_f1_ci: dict[str, float] = field(default_factory=dict)
    triple_f1_ci: dict[str, float] = field(default_factory=dict)
    missing_triples: list[tuple[str, str, str]] = field(default_factory=list)
    spurious_triples: list[tuple[str, str, str]] = field(default_factory=list)
    # Which extractor stream this score is about. All-None reads "every
    # stream in the store", so a mixed number can never be mistaken for one
    # extractor's measurement.
    stream: dict[str, Any] = field(
        default_factory=lambda: {
            "engine": None,
            "model": None,
            "prompt_version": None,
            "decode_params": None,
        }
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "entity": {k: round(v, 4) for k, v in self.entity.items()},
            "triple": {k: round(v, 4) for k, v in self.triple.items()},
            "entity_f1_ci": dict(self.entity_f1_ci),
            "triple_f1_ci": dict(self.triple_f1_ci),
            "counts": dict(self.counts),
            "missing_triples": [list(t) for t in self.missing_triples],
            "spurious_triples": [list(t) for t in self.spurious_triples],
            "stream": dict(self.stream),
        }


def evaluate_store(
    store: KGStore,
    gold: Gold,
    *,
    include_proposed: bool = True,
    engine: str | None = None,
    model: str | None = None,
    prompt_version: str | None = None,
    decode_params: dict[str, Any] | None = None,
) -> Report:
    """Score the store's extractions against the gold reference."""
    found_entities, found_triples = store_view(
        store,
        include_proposed=include_proposed,
        engine=engine,
        model=model,
        prompt_version=prompt_version,
        decode_params=decode_params,
    )
    return Report(
        stream={
            "engine": engine,
            "model": model,
            "prompt_version": prompt_version,
            "decode_params": decode_params,
        },
        entity=_prf(gold.entities, found_entities),
        triple=_prf(gold.triples, found_triples),
        entity_f1_ci=bootstrap_f1_interval(gold.entities, found_entities),
        triple_f1_ci=bootstrap_f1_interval(gold.triples, found_triples),
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
    "bootstrap_f1_interval",
    "MAX_EXAMPLES",
    "Report",
    "evaluate_store",
    "load_gold",
    "store_view",
]
