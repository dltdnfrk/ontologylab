"""Offline reviewable-coverage measurement over immutable trial stores.

Usage: python evidence/is1_review_score.py GOLD.json STORE_DIR [STORE_DIR ...]
The caller stages the gold JSON and all sources in a real scratch directory.
Output is JSON on stdout; neither the gold nor the stores are modified.
"""

from __future__ import annotations

from collections import Counter
import json
from pathlib import Path
import sys
from urllib.parse import urlsplit

from ontologylab.kgstore import KGStore
from ontologylab.missed_null import _CUES, _sentences, missed_null_candidates
from ontologylab.polarity_eval import _node_match_keys, load_polarity_gold
from ontologylab.qualified_polarity_eval import qualifiers_cover, score_qualified
from ontologylab.statement_qualifiers import normalize_statement_qualifiers


def measure(gold_path: Path, directories: list[Path]) -> dict:
    """Count each gold null row once per run, using the qualified matcher."""
    gold = load_polarity_gold(gold_path, qualified=True)
    source_rows = json.loads(gold_path.read_text(encoding="utf-8"))["relations"]
    null_rows = [
        (index, row) for index, row in enumerate(source_rows)
        if row["polarity"] in ("no_effect", "refutes")
    ]
    reports = []
    for directory in directories:
        with KGStore.open(directory / "kg.sqlite", read_only=True, immutable=True) as store:
            documents = store.list_documents()
            by_pmcid = {
                Path(urlsplit(document.source_uri).path).stem: document
                for document in documents
            }
            assert all(row["pmcid"] in by_pmcid for _, row in null_rows)
            candidates = missed_null_candidates(store, documents)
            node_keys = _node_match_keys(store.conn)
            predicted = [
                (row["relation_type"], row["src_node_id"], row["dst_node_id"],
                 json.loads(row["qualifiers_json"]))
                for row in store.conn.execute(
                    "SELECT relation_type,src_node_id,dst_node_id,qualifiers_json "
                    "FROM edges WHERE status IN ('proposed','verified') "
                    "AND invalidated_ts IS NULL"
                )
            ]
            cited = [
                (row["source_doc_id"], json.loads(row["source_span"]))
                for row in store.conn.execute(
                    "SELECT c.source_doc_id, c.source_span FROM citations c "
                    "JOIN edges e ON e.id=c.item_id WHERE c.kind='edge' "
                    "AND e.status IN ('proposed','verified') AND e.invalidated_ts IS NULL "
                    "AND json_extract(e.qualifiers_json,'$.polarity') IN ('no_effect','refutes') "
                    "AND c.source_span IS NOT NULL"
                )
            ]
            outcomes = []
            spans_by_document: dict[str, list[tuple[int, int]]] = {}
            for index, row in null_rows:
                doc = by_pmcid[row["pmcid"]]
                source = (gold_path.parent / "sources" / "full" /
                          f"{row['pmcid']}.txt").read_bytes()
                start = len(source[:row["span"]["start"]].decode("utf-8"))
                end = len(source[:row["span"]["end"]].decode("utf-8"))
                assert store.document_raw_text(doc.id)[start:end] == row["span"]["quote"]
                sentence = next(
                    (part for a, b, part in _sentences(store.document_raw_text(doc.id))
                     if a < end and start < b),
                    "",
                )
                sentence_bounds = next(
                    ((a, b) for a, b, _ in _sentences(store.document_raw_text(doc.id))
                     if a < end and start < b),
                    (start, end),
                )
                spans_by_document.setdefault(doc.id, []).append((start, end))
                triple, polarity = gold.relations[index]
                qualifiers = normalize_statement_qualifiers(gold.qualifiers[index])
                extracted = any(
                    relation == triple[1] and scope.get("polarity") == polarity
                    and triple[0] in node_keys.get(subject, set())
                    and triple[2] in node_keys.get(obj, set())
                    and qualifiers_cover(scope, qualifiers)
                    for relation, subject, obj, scope in predicted
                )
                flagged = any(
                    candidate.document_id == doc.id
                    and candidate.start < end and start < candidate.end
                    for candidate in candidates
                )
                outcomes.append({
                    "source_row": row["source_row"], "pmcid": row["pmcid"],
                    "document_id": doc.id, "extracted": extracted,
                    "flagged": flagged, "reviewable": extracted or flagged,
                    "candidate_statuses": sorted({
                        candidate.status for candidate in candidates
                        if candidate.document_id == doc.id
                        and candidate.start < end and start < candidate.end
                    }),
                    "cue_in_sentence": next(
                        (name for name, pattern in _CUES if pattern.search(sentence)), None
                    ),
                    "null_citation_overlaps_sentence": any(
                        cited_doc == doc.id and span["start"] < sentence_bounds[1]
                        and sentence_bounds[0] < span["end"]
                        for cited_doc, span in cited
                    ),
                })
            non_gold = sum(
                not any(start < c.end and c.start < end
                        for start, end in spans_by_document.get(c.document_id, ()))
                for c in candidates
            )
            qualified = score_qualified(store.conn, gold)
            assert qualified["recall_no_effect_refutes"]["numerator"] == sum(
                row["extracted"] for row in outcomes
            )
            reports.append({
                "store": str(directory),
                "gold_rows": len(outcomes),
                "extracted": sum(row["extracted"] for row in outcomes),
                "flagged": sum(row["flagged"] for row in outcomes),
                "reviewable": sum(row["reviewable"] for row in outcomes),
                "coverage": sum(row["reviewable"] for row in outcomes) / len(outcomes),
                "review_burden": len(candidates),
                "candidate_status_counts": dict(Counter(
                    candidate.status for candidate in candidates
                )),
                "flagged_sentences_not_in_gold": non_gold,
                "qualified_polarity_accuracy": qualified["polarity_accuracy"],
                "qualified_flip_rate": qualified["supports_when_gold_no_effect_flip_rate"],
                "rows": outcomes,
            })
    totals = Counter({
        key: sum(report[key] for report in reports)
        for key in ("gold_rows", "extracted", "flagged", "reviewable",
                    "review_burden", "flagged_sentences_not_in_gold")
    })
    return {
        "gold": str(gold_path), "runs": reports,
        "pooled": {**totals, "coverage": totals["reviewable"] / totals["gold_rows"],
                   "candidate_status_counts": dict(sum((
                       Counter(report["candidate_status_counts"]) for report in reports
                   ), Counter())),
                   "passed": totals["reviewable"] / totals["gold_rows"] >= 0.90},
    }


if __name__ == "__main__":
    print(json.dumps(measure(Path(sys.argv[1]), list(map(Path, sys.argv[2:]))),
                     indent=2, ensure_ascii=False))
