"""Descriptive miss accounting on the durable export; never changes scoring."""
from collections import Counter
import json
from pathlib import Path
import sqlite3
import sys

from ontologylab.polarity_eval import _node_match_keys, load_polarity_gold, score_polarity
from ontologylab.qualified_polarity_eval import qualifiers_cover
from ontologylab.statement_qualifiers import normalize_qualifier_value

exported = json.loads(Path(sys.argv[1]).read_text())
qualified_path = Path(sys.argv[2])
legacy_path = Path(sys.argv[3])
raw = json.loads(qualified_path.read_text())
qualified_gold = load_polarity_gold(qualified_path, qualified=True)
reports = []
for run in exported["runs"]:
    conn = sqlite3.connect(":memory:")
    try:
        for table in ("nodes", "node_aliases", "edges"):
            conn.execute(run["schemas"][table])
            rows = run["tables"][table]
            if rows:
                columns = list(rows[0])
                conn.executemany(
                    f'INSERT INTO "{table}" ({",".join(columns)}) '
                    f'VALUES ({",".join("?" for _ in columns)})',
                    [[row[column] for column in columns] for row in rows],
                )
        keys = _node_match_keys(conn)
        nodes = {row["id"]: row for row in run["tables"]["nodes"]}
        documents = {row["id"]: row for row in run["tables"]["documents"]}
        edges = [
            row for row in run["tables"]["edges"]
            if row["status"] in ("proposed", "verified") and row["invalidated_ts"] is None
        ]
        modes = {}
        for mode, path, qualified in (
            ("primary", qualified_path, True), ("legacy", legacy_path, False),
        ):
            gold = load_polarity_gold(path, qualified=qualified)
            missed = []
            wrong = []
            for index, ((src, relation, dst), actual) in enumerate(gold.relations):
                core = [
                    edge for edge in edges
                    if src in keys.get(edge["src_node_id"], set())
                    and dst in keys.get(edge["dst_node_id"], set())
                    and edge["relation_type"] == relation
                ]
                matched = [
                    edge for edge in core
                    if not qualified or qualifiers_cover(
                        json.loads(edge["qualifiers_json"]), gold.qualifiers[index]
                    )
                ]
                labels = sorted({
                    json.loads(edge["qualifiers_json"]).get("polarity") or "omitted"
                    for edge in matched
                })
                if labels:
                    wrong.extend(
                        {"gold_index": index + 1, "gold_polarity": actual,
                         "predicted_polarity": label,
                         "edge_ids": [
                             edge["id"] for edge in matched
                             if (json.loads(edge["qualifiers_json"]).get("polarity") or "omitted") == label
                         ]}
                        for label in labels if label != actual
                    )
                    continue
                category = "scope" if core else ""
                candidates = core
                if not candidates and not qualified:
                    qsrc, qrel, qdst = qualified_gold.relations[index][0]
                    candidates = [
                        edge for edge in edges
                        if qsrc in keys.get(edge["src_node_id"], set())
                        and qdst in keys.get(edge["dst_node_id"], set())
                        and edge["relation_type"] == qrel
                    ]
                    if candidates:
                        category = "scope"
                if not candidates:
                    candidates = [
                        edge for edge in edges
                        if ((src in keys.get(edge["src_node_id"], set())
                             and dst in keys.get(edge["dst_node_id"], set()))
                            or (dst in keys.get(edge["src_node_id"], set())
                                and src in keys.get(edge["dst_node_id"], set())))
                    ]
                    if candidates:
                        category = "relation"
                if not candidates:
                    candidates = [
                        edge for edge in edges
                        if edge["relation_type"] == relation
                        and raw["relations"][index]["pmcid"] in documents[edge["source_doc_id"]]["source_uri"]
                        and (src in keys.get(edge["src_node_id"], set())
                             or dst in keys.get(edge["dst_node_id"], set()))
                    ]
                    category = "surface" if candidates else "absent"
                descriptions = []
                for edge in candidates:
                    qualifiers = json.loads(edge["qualifiers_json"])
                    descriptions.append({
                        "edge_id": edge["id"], "source_doc_id": edge["source_doc_id"],
                        "src": nodes[edge["src_node_id"]]["name"],
                        "relation": edge["relation_type"],
                        "dst": nodes[edge["dst_node_id"]]["name"],
                        "qualifiers": qualifiers, "source_span": edge["source_span"],
                        "qualifier_mismatches": {
                            key: {"expected": value, "predicted": qualifiers.get(key)}
                            for key, value in gold.qualifiers[index].items()
                            if key not in qualifiers
                            or normalize_qualifier_value(qualifiers[key]) != normalize_qualifier_value(value)
                        } if qualified else {},
                    })
                missed.append({
                    "gold_index": index + 1, "triple": [src, relation, dst],
                    "polarity": actual, "qualifiers": gold.qualifiers[index],
                    "category": category, "candidates": descriptions,
                })
            score = score_polarity(conn, path, qualified=qualified)
            assert len(missed) == score["counts"]["missing_relations"]
            assert [item["triple"] for item in missed] == score["missing_triples"]
            assert len(wrong) == (
                score["polarity_accuracy"]["denominator"] - score["polarity_accuracy"]["numerator"]
            )
            modes[mode] = {
                "counts": dict(Counter(item["category"] for item in missed)),
                "missing": missed, "wrong_polarity": wrong,
            }
        reports.append({"run": run["run"], **modes})
    finally:
        conn.close()
print(json.dumps({
    "runs": reports,
    "method": (
        "Exclusive diagnostic order: exact core with unmet qualifiers = scope; "
        "legacy miss with mapped qualified core = scope; exact endpoints with "
        "different relation/direction = relation; same-paper same-relation "
        "one-endpoint candidates = surface; otherwise absent comparable candidate. "
        "All candidates retained; these are descriptive, not equivalence rules. "
        "Absent means absent under this candidate rule, not proven semantic absence."
    ),
}, sort_keys=True))
