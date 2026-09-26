"""Full-text polarity gold validation and read-only extraction scoring.

Run ``python -m ontologylab.polarity_eval GOLD.json`` to validate a corpus.
``score_polarity(conn, gold_path)`` scores current proposed/verified edges,
as evaluation.store_view does. Use a separate store for each trial run:
this API deliberately does not infer an extractor stream from mixed data.

Rows of confusion_matrix are gold; columns are predictions. Only matched
triples enter it; an absent qualifier is "omitted", NOT "supports". Missing
triples are reported separately and count as misses in recall. Distinct
polarities on one triple each enter the matrix once: never pick whichever
label agrees with gold. Accuracy uses all those predictions; recall counts
each gold relation once. Flip rate uses matched gold no_effect relations.

Entity keys use normalize_name and recorded node_aliases, with the store's
canonical-name precedence and same-schema/type alias ambiguity rule. Alias
spellings do not create extra predictions. No unrecorded abbreviation or
semantic equivalence is inferred; relation type and direction stay exact.

Rate CIs are seeded case-bootstrap percentiles conditional on each metric's
denominator. Like evaluation.bootstrap_f1_interval, they assume independent
outcomes, not papers; correlated claims can make intervals too narrow.
Undefined rates/CIs are null, never perfect scores. Four-tuple F1 also uses
the existing bootstrap_f1_interval unchanged.
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date
import hashlib
import json
from pathlib import Path
import random
import re
import sqlite3
import sys
from typing import Any

from ontologylab.connectors.fulltext import MIN_FULLTEXT_CHARS
from ontologylab.evaluation import (
    BOOTSTRAP_RESAMPLES,
    BOOTSTRAP_SEED,
    CONFIDENCE_LEVEL,
    GoldError,
    bootstrap_f1_interval,
)
from ontologylab.kgstore import normalize_name
from ontologylab.schemas import POLARITY_QUALIFIER, preset

POLARITIES = tuple(POLARITY_QUALIFIER["enum"])
LABELS = (*POLARITIES, "omitted")
Triple = tuple[str, str, str]


@dataclass(frozen=True, slots=True)
class PolarityGold:
    """Validated, uniquely labeled normalized triples and corpus counts."""

    relations: tuple[tuple[Triple, str], ...]
    papers: int


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise GoldError(message)


def load_polarity_gold(path: str | Path) -> PolarityGold:
    """Validate schema vocabulary, source integrity and exact body spans.

    This is offline integrity validation, not semantic adjudication or an
    independent proof of the upstream JATS bytes. Their hashes and body
    offsets are recorded for reproducible retrieval. Source text is data:
    no instruction, URL or executable content in it is interpreted.
    """
    path = Path(path)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        _require(isinstance(raw, dict), "gold must be an object")
        _require(raw["schema"] == "agrochem-v2", "expected agrochem-v2")
        _require(type(raw["format_version"]) is int and raw["format_version"] in (1, 2),
                 "unsupported gold format")
        full_body = raw["format_version"] == 2
        _require(isinstance(raw["papers"], list) and bool(raw["papers"]),
                 "gold needs papers")
        _require(isinstance(raw["relations"], list) and bool(raw["relations"]),
                 "gold needs relations")
        sources: dict[str, tuple[bytes, list[tuple[int, int]]]] = {}
        for paper in raw["papers"]:
            pmcid = paper["pmcid"]
            _require(isinstance(pmcid, str) and bool(re.fullmatch(r"PMC[0-9]+", pmcid)),
                     "invalid pmcid")
            _require(pmcid not in sources, f"duplicate paper: {pmcid}")
            for key in ("doi", "title", "license", "license_url", "retrieved_at"):
                _require(isinstance(paper[key], str) and bool(paper[key].strip()),
                         f"{pmcid}: missing {key}")
            date.fromisoformat(paper["retrieved_at"])
            kind = "full_body" if full_body else "body_excerpt"
            source_dir = "sources/full" if full_body else "sources"
            _require(paper["content_kind"] == kind, f"{pmcid}: not body text")
            _require(paper["source"] == f"{source_dir}/{pmcid}.txt",
                     f"{pmcid}: unsafe source path")
            source = path.parent / paper["source"]
            _require(source.resolve().is_relative_to(path.parent.resolve()),
                     f"{pmcid}: source escapes gold directory")
            data = source.read_bytes()
            _require(len(data.decode("utf-8").strip()) >= MIN_FULLTEXT_CHARS,
                     f"{pmcid}: empty or too-short source")
            _require(len(data) == paper["source_bytes"], f"{pmcid}: source size mismatch")
            _require(hashlib.sha256(data).hexdigest() == paper["source_sha256"],
                     f"{pmcid}: source hash mismatch")
            for key in ("body_sha256", "jats_sha256"):
                _require(bool(re.fullmatch(r"[0-9a-f]{64}", paper[key])),
                         f"{pmcid}: invalid {key}")
            ranges: list[tuple[int, int]] = []
            cursor = 0
            previous_body_end = 0
            for segment in paper["segments"]:
                a, b = segment["stored_start"], segment["stored_end"]
                lo, hi = segment["body_start"], segment["body_end"]
                _require(all(type(v) is int for v in (a, b, lo, hi, paper["body_bytes"])),
                         f"{pmcid}: offsets must be integer bytes")
                _require(a == cursor and a < b <= len(data),
                         f"{pmcid}: invalid stored range")
                _require(previous_body_end <= lo < hi <= paper["body_bytes"]
                         and hi - lo == b - a, f"{pmcid}: invalid body range")
                _require(bool(segment["section"].strip())
                         and "abstract" not in segment["section"].casefold(),
                         f"{pmcid}: invalid body section")
                data[a:b].decode("utf-8")
                _require(hashlib.sha256(data[a:b]).hexdigest() == segment["sha256"],
                         f"{pmcid}: segment hash mismatch")
                ranges.append((a, b))
                previous_body_end = hi
                cursor = b + 2
                _require(data[b:b + 2] == b"\n\n" or data[b:] == b"\n",
                         f"{pmcid}: invalid segment separator")
            _require(bool(ranges) and ranges[-1][1] + 1 == len(data),
                     f"{pmcid}: incomplete source ranges")
            if full_body:
                _require(ranges == [(0, paper["body_bytes"])]
                         and paper["segments"][0]["body_start"] == 0
                         and paper["segments"][0]["body_end"] == paper["body_bytes"],
                         f"{pmcid}: incomplete full body")
                _require(hashlib.sha256(data[:-1]).hexdigest() == paper["body_sha256"],
                         f"{pmcid}: full body hash mismatch")
            sources[pmcid] = data, ranges

        claim_relations = {
            rt["name"] for rt in preset("agrochem-v2")["relation_types"]
            if "polarity" in rt["qualifiers"]
        }
        relations: list[tuple[Triple, str]] = []
        seen: set[Triple] = set()
        cited: set[str] = set()
        for item in raw["relations"]:
            _require(all(isinstance(item[k], str) and bool(item[k].strip())
                         for k in ("src", "relation", "dst", "polarity", "context")),
                     "relation fields must be nonempty strings")
            _require(item["relation"] in claim_relations, "not an agrochem-v2 claim relation")
            _require(item["polarity"] in POLARITIES, "invalid gold polarity")
            triple = normalize_name(item["src"]), item["relation"], normalize_name(item["dst"])
            _require(bool(triple[0]) and bool(triple[2]), "empty normalized name")
            _require(triple not in seen, "duplicate or conflicting gold triple")
            seen.add(triple)
            pmcid = item["pmcid"]
            _require(pmcid in sources, "relation cites unknown paper")
            data, ranges = sources[pmcid]
            span = item["span"]
            a, b, quote = span["start"], span["end"], span["quote"]
            _require(type(a) is int and type(b) is int and isinstance(quote, str)
                     and bool(quote.strip()), "invalid span shape")
            _require(any(lo <= a < b <= hi for lo, hi in ranges),
                     f"{pmcid}: span outside retained body segment")
            _require(data[a:b] == quote.encode("utf-8"),
                     f"{pmcid}: span quote does not match source")
            relations.append((triple, item["polarity"]))
            cited.add(pmcid)
        _require(cited == set(sources), "uncited source in corpus")
        return PolarityGold(tuple(relations), len(sources))
    except (OSError, UnicodeError, ValueError, KeyError, TypeError, AttributeError) as exc:
        raise GoldError(f"malformed polarity gold: {exc}") from exc


def validate_gold(path: str | Path) -> dict[str, Any]:
    """Return counts only after every source and span has passed validation."""
    gold = load_polarity_gold(path)
    counts = Counter(polarity for _, polarity in gold.relations)
    return {
        "papers": gold.papers,
        "relations": len(gold.relations),
        "relations_per_polarity": {p: counts[p] for p in POLARITIES},
        "spans_verified": len(gold.relations),
    }


def _rate(outcomes: list[bool]) -> dict[str, Any]:
    """One proportion and its deterministic 95% percentile case bootstrap."""
    n = len(outcomes)
    if not n:
        return {"value": None, "numerator": 0, "denominator": 0, "ci95": None}
    rng = random.Random(BOOTSTRAP_SEED)
    samples = sorted(
        sum(outcomes[rng.randrange(n)] for _ in range(n)) / n
        for _ in range(BOOTSTRAP_RESAMPLES)
    )
    tail = (1 - CONFIDENCE_LEVEL) / 2
    return {
        "value": sum(outcomes) / n,
        "numerator": sum(outcomes),
        "denominator": n,
        "ci95": {
            "low": round(samples[int(tail * BOOTSTRAP_RESAMPLES)], 4),
            "high": round(samples[min(BOOTSTRAP_RESAMPLES - 1,
                                     int((1 - tail) * BOOTSTRAP_RESAMPLES) - 1)], 4),
        },
    }


def _node_match_keys(store_conn: sqlite3.Connection) -> dict[str, set[str]]:
    """Read the exact keys accepted by _resolve_node, without merge-queue writes."""
    keys = {
        node_id: {name}
        for node_id, name in store_conn.execute(
            "SELECT id, normalized_name FROM nodes WHERE status IN ('proposed','verified')"
        )
    }
    for node_id, alias in store_conn.execute(
        """SELECT a.node_id, a.normalized_alias
           FROM node_aliases a JOIN nodes n ON n.id = a.node_id
           WHERE n.status IN ('proposed','verified')
             AND NOT EXISTS (
               SELECT 1 FROM nodes direct
               WHERE direct.schema_version_id = n.schema_version_id
                 AND direct.entity_type = n.entity_type
                 AND direct.status IN ('proposed','verified')
                 AND direct.normalized_name = a.normalized_alias)
             AND NOT EXISTS (
               SELECT 1 FROM node_aliases other JOIN nodes holder ON holder.id = other.node_id
               WHERE other.normalized_alias = a.normalized_alias
                 AND holder.id != n.id
                 AND holder.schema_version_id = n.schema_version_id
                 AND holder.entity_type = n.entity_type
                 AND holder.status IN ('proposed','verified'))"""
    ):
        keys[node_id].add(alias)
    return keys


def score_polarity(store_conn: sqlite3.Connection, gold_path: str | Path) -> dict[str, Any]:
    """Score a v2 trial store without writes or changes to connection state."""
    gold = load_polarity_gold(gold_path)
    node_keys = _node_match_keys(store_conn)
    predictions: dict[Triple, set[str]] = defaultdict(set)
    # Positional access supports both sqlite3.Row and a default connection.
    for src, relation, dst, qualifiers, src_id, dst_id in store_conn.execute(
        """SELECT s.normalized_name, e.relation_type, d.normalized_name,
                  e.qualifiers_json, s.id, d.id
           FROM edges e
           JOIN nodes s ON s.id = e.src_node_id
           JOIN nodes d ON d.id = e.dst_node_id
           WHERE e.status IN ('proposed', 'verified')
             AND e.invalidated_ts IS NULL"""
    ):
        try:
            parsed = json.loads(qualifiers)
            _require(isinstance(parsed, dict), "edge qualifiers must be an object")
            polarity = parsed.get("polarity", "")
            _require(isinstance(polarity, str)
                     and polarity in (*POLARITIES, ""), "invalid predicted polarity")
        except (TypeError, ValueError) as exc:
            raise GoldError(f"malformed edge qualifiers: {exc}") from exc
        matches = [
            triple for triple, _ in gold.relations
            if triple[1] == relation
            and triple[0] in node_keys.get(src_id, set())
            and triple[2] in node_keys.get(dst_id, set())
        ]
        _require(len(matches) <= 1,
                 "multiple gold triples resolve to the same extracted identity")
        # Re-key, rather than expand aliases into extra observed four-tuples.
        triple = matches[0] if matches else (src, relation, dst)
        predictions[triple].add(polarity or "omitted")
    matrix = {p: dict.fromkeys(LABELS, 0) for p in LABELS}
    recall: dict[str, list[bool]] = {p: [] for p in POLARITIES}
    accuracy: list[bool] = []
    flips: list[bool] = []
    missing: list[list[str]] = []
    matched = conflicts = 0
    for triple, actual in gold.relations:
        found = predictions.get(triple, set())
        recall[actual].append(actual in found)
        if not found:
            missing.append(list(triple))
            continue
        matched += 1
        conflicts += len(found) > 1
        for predicted in sorted(found):
            matrix[actual][predicted] += 1
            accuracy.append(actual == predicted)
        if actual == "no_effect":
            flips.append("supports" in found)
    expected = frozenset((*triple, p) for triple, p in gold.relations)
    observed = {(*triple, p) for triple, values in predictions.items() for p in values}
    tp = len(expected & observed)
    return {
        "labels": list(LABELS),
        "confusion_matrix": matrix,
        "counts": {
            "gold_relations": len(expected),
            "matched_relations": matched,
            "missing_relations": len(missing),
            "matched_predictions": len(accuracy),
            "conflicting_matched_relations": conflicts,
            "found_four_tuples": len(observed),
            "spurious_four_tuples": len(observed - expected),
        },
        "recall_no_effect": _rate(recall["no_effect"]),
        "recall_refutes": _rate(recall["refutes"]),
        "recall_no_effect_refutes": _rate(recall["no_effect"] + recall["refutes"]),
        "supports_when_gold_no_effect_flip_rate": _rate(flips),
        "polarity_accuracy": _rate(accuracy),
        "four_tuple_f1": 2 * tp / (len(expected) + len(observed)),
        "four_tuple_f1_ci95": bootstrap_f1_interval(expected, observed),
        "missing_triples": missing,
        "bootstrap": {
            "resamples": BOOTSTRAP_RESAMPLES, "seed": BOOTSTRAP_SEED,
            "confidence": CONFIDENCE_LEVEL, "unit": "individual outcome",
            "limitation": "Within-paper dependence is not modeled.",
        },
        "scope": "All current proposed/verified edges; use one trial stream per store.",
    }


def main(argv: list[str] | None = None) -> int:
    """Offline gold-validator CLI; errors never print a success count."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("gold", type=Path)
    args = parser.parse_args(argv)
    try:
        counts = validate_gold(args.gold)
    except GoldError as exc:
        print(f"polarity gold refused: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(counts, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
