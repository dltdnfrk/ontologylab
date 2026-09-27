"""Qualifier-subset scoring; legacy scoring remains a separate unchanged path."""

from __future__ import annotations

from collections import defaultdict
import json
import sqlite3
from typing import Any

from ontologylab.evaluation import (
    BOOTSTRAP_RESAMPLES, BOOTSTRAP_SEED, CONFIDENCE_LEVEL, GoldError,
    bootstrap_f1_interval,
)
from ontologylab.polarity_eval import LABELS, POLARITIES, PolarityGold, _node_match_keys, _rate, _require
from ontologylab.statement_qualifiers import (
    canonical_qualifiers, normalize_statement_qualifiers, normalize_statement_value,
)


def qualifiers_cover(predicted: dict[str, Any], expected: dict[str, str]) -> bool:
    """Only gold-specified slots constrain a match; extras do not block it."""
    return all(
        key in predicted and isinstance(predicted[key], str)
        and normalize_statement_value(key, predicted[key]) == normalize_statement_value(key, value)
        for key, value in expected.items()
    )


def score_qualified(conn: sqlite3.Connection, gold: PolarityGold) -> dict[str, Any]:
    """Score scoped statements with the legacy confusion/rate definitions.

    Matching is set-based: extra predicted scope is projected onto each covered
    gold scope. Repeated evidence does not multiply votes. Distinct polarities
    still all count, so a correct label never hides an opposing prediction.
    """
    node_keys = _node_match_keys(conn)
    gold_qualifiers = tuple(normalize_statement_qualifiers(q) for q in gold.qualifiers)
    scopes = [
        (*triple, canonical_qualifiers(qualifiers))
        for (triple, _), qualifiers in zip(gold.relations, gold_qualifiers)
    ]
    predictions: dict[tuple[str, ...], set[str]] = defaultdict(set)
    for src, relation, dst, raw, src_id, dst_id in conn.execute(
        """SELECT s.normalized_name, e.relation_type, d.normalized_name,
                  e.qualifiers_json, s.id, d.id
           FROM edges e JOIN nodes s ON s.id=e.src_node_id
           JOIN nodes d ON d.id=e.dst_node_id
           WHERE e.status IN ('proposed','verified') AND e.invalidated_ts IS NULL"""
    ):
        try:
            qualifiers = json.loads(raw)
            _require(isinstance(qualifiers, dict), "edge qualifiers must be an object")
            _require(all(isinstance(v, str) and bool(v.strip()) for v in qualifiers.values()),
                     "edge qualifier values must be nonempty strings")
            polarity = qualifiers.get("polarity", "")
            _require(isinstance(polarity, str) and polarity in (*POLARITIES, ""),
                     "invalid predicted polarity")
        except (ValueError, TypeError) as exc:
            raise GoldError(f"malformed edge qualifiers: {exc}") from exc
        candidates = [
            index for index, (triple, _) in enumerate(gold.relations)
            if triple[1] == relation
            and triple[0] in node_keys.get(src_id, set())
            and triple[2] in node_keys.get(dst_id, set())
        ]
        _require(len({gold.relations[i][0] for i in candidates}) <= 1,
                 "multiple gold triples resolve to the same extracted identity")
        matches = [scopes[i] for i in candidates if qualifiers_cover(qualifiers, gold.qualifiers[i])]
        if matches:
            for scope in matches:
                predictions[scope].add(polarity or "omitted")
        else:
            predictions[(src, relation, dst, canonical_qualifiers(
                normalize_statement_qualifiers(qualifiers)
            ))].add(
                polarity or "omitted"
            )
    matrix = {p: dict.fromkeys(LABELS, 0) for p in LABELS}
    recall: dict[str, list[bool]] = {p: [] for p in POLARITIES}
    accuracy: list[bool] = []
    flips: list[bool] = []
    missing = []
    matched = conflicts = 0
    for scope, (triple, actual), qualifiers in zip(scopes, gold.relations, gold_qualifiers):
        found = predictions.get(scope, set())
        recall[actual].append(actual in found)
        if not found:
            missing.append({"triple": list(triple), "polarity": actual, "qualifiers": qualifiers})
            continue
        matched += 1
        conflicts += len(found) > 1
        for predicted in sorted(found):
            matrix[actual][predicted] += 1
            accuracy.append(actual == predicted)
        if actual == "no_effect":
            flips.append("supports" in found)
    expected = frozenset((*scope, actual) for scope, (_, actual) in zip(scopes, gold.relations))
    observed = {(*scope, label) for scope, labels in predictions.items() for label in labels}
    return {
        "matching_mode": "qualified",
        "labels": list(LABELS),
        "confusion_matrix": matrix,
        "counts": {
            "gold_relations": len(expected), "matched_relations": matched,
            "missing_relations": len(missing), "matched_predictions": len(accuracy),
            "conflicting_matched_relations": conflicts,
            "found_four_tuples": len(observed),
            "spurious_four_tuples": len(observed - expected),
        },
        "recall_no_effect": _rate(recall["no_effect"]),
        "recall_refutes": _rate(recall["refutes"]),
        "recall_no_effect_refutes": _rate(recall["no_effect"] + recall["refutes"]),
        "supports_when_gold_no_effect_flip_rate": _rate(flips),
        "polarity_accuracy": _rate(accuracy),
        "four_tuple_f1": 2 * len(expected & observed) / (len(expected) + len(observed)),
        "four_tuple_f1_ci95": bootstrap_f1_interval(expected, observed),
        "missing_triples": [item["triple"] for item in missing],
        "missing_statements": missing,
        "bootstrap": {
            "resamples": BOOTSTRAP_RESAMPLES, "seed": BOOTSTRAP_SEED,
            "confidence": CONFIDENCE_LEVEL, "unit": "individual outcome",
            "limitation": "Within-paper dependence is not modeled.",
        },
        "scope": "All current proposed/verified edges; use one trial stream per store.",
    }
