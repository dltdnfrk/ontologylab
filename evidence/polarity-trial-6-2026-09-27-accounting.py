"""Offline request accounting and bounded pass attribution; no provider calls."""
from collections import Counter, defaultdict
from contextlib import closing
import json
from pathlib import Path
import sqlite3
import sys

from ontologylab.polarity_eval import _node_match_keys, load_polarity_gold
from ontologylab.qualified_polarity_eval import qualifiers_cover

exported = json.loads(Path(sys.argv[1]).read_text())
gold_paths = list(map(Path, sys.argv[2:]))
reports = []
for run in exported["runs"]:
    root = Path(run["data_dir"])
    http = json.loads((root / "http-receipt.json").read_text())
    job_dir = root / "jobs" / http["job_id"]
    events = [
        json.loads(line)
        for line in (job_dir / "provenance.jsonl").read_text().splitlines()
    ]
    status = json.loads((job_dir / "status.json").read_text())
    passes = [e["payload"] for e in events if e["step"] == "extract.pass"]
    calls = [e for e in events if e["payload"].get("engine_call")]
    assert [p["request_number"] for p in passes] == list(range(1, len(calls) + 1))
    assert len(passes) == len(calls) == status["engine_calls"] <= 60
    by_chunk = defaultdict(list)
    for entry in passes:
        by_chunk[(entry["doc_id"], entry["chunk"])].append(entry)
    rejections = [e["payload"] for e in events if e["step"] == "extract.proposal_rejected"]
    failed_completion = {
        (e["doc_id"], e["chunk"]) for e in rejections
        if e["kind"] == "response" and e["reason"] == "completion_failed"
    }
    stream_docs = {
        r["id"]: r["document_id"] for r in run["tables"]["extraction_runs"]
    }
    chunk_receipts = []
    for chunk in run["tables"]["extraction_chunks"]:
        key = (stream_docs[chunk["run_id"]], chunk["chunk_index"])
        counts = Counter(p["pass"] for p in by_chunk[key])
        stats = json.loads(chunk["stats_json"]) if chunk["stats_json"] else {}
        completion_usable = counts["completion"] == 1 and key not in failed_completion
        assert counts["completion"] <= 1
        chunk_receipts.append({
            "document_id": key[0], "chunk": key[1], "status": chunk["status"],
            "started_ts": chunk["started_ts"], "finished_ts": chunk["finished_ts"],
            "first_requests": counts["first"], "completion_requests": counts["completion"],
            "retry_requests": max(0, counts["first"] - 1),
            "completion_response_usable": completion_usable,
            "edges_new": stats.get("edges_new", 0),
            "edges_merged": stats.get("edges_merged", 0),
            "accepted_statements": stats.get("edges_new", 0) + stats.get("edges_merged", 0),
        })
    annotations = {}
    for edge in run["tables"]["edges"]:
        origins = [
            c for c in chunk_receipts
            if c["document_id"] == edge["source_doc_id"]
            and c["started_ts"] is not None and c["finished_ts"] is not None
            and c["started_ts"] <= edge["created_ts"] <= c["finished_ts"]
        ]
        assert len(origins) == 1, (run["run"], edge["id"], len(origins))
        chunk = origins[0]
        annotations[edge["id"]] = {
            "pass": None if chunk["completion_response_usable"] else "first",
            "possible_passes": ["first", "completion"] if chunk["completion_response_usable"] else ["first"],
            "document_id": chunk["document_id"], "chunk": chunk["chunk"],
            "basis": (
                "created_ts identifies the insertion chunk; successful proposal pass is not persisted"
                if chunk["completion_response_usable"] else
                "created_ts identifies a chunk with no usable completion response"
            ),
        }
    known_first = {edge_id for edge_id, note in annotations.items() if note["pass"] == "first"}
    total_edges = len(run["tables"]["edges"])
    assert sum(c["edges_new"] for c in chunk_receipts) == total_edges
    assert len(known_first) == sum(
        c["edges_new"] for c in chunk_receipts if not c["completion_response_usable"]
    )
    contributions = {}
    with closing(sqlite3.connect(":memory:")) as conn:
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
        edges = [
            e for e in run["tables"]["edges"]
            if e["status"] in ("proposed", "verified") and e["invalidated_ts"] is None
        ]
        for path in gold_paths:
            qualified = "qualified" in path.name
            gold = load_polarity_gold(path, qualified=qualified)
            matches = []
            for index, ((src, relation, dst), actual) in enumerate(gold.relations):
                matched = [
                    e for e in edges if e["relation_type"] == relation
                    and src in keys[e["src_node_id"]] and dst in keys[e["dst_node_id"]]
                    and (not qualified or qualifiers_cover(
                        json.loads(e["qualifiers_json"]), gold.qualifiers[index]
                    ))
                ]
                if not matched:
                    continue
                correct = [
                    e for e in matched
                    if json.loads(e["qualifiers_json"]).get("polarity") == actual
                ]
                first_match = any(e["id"] in known_first for e in matched)
                first_correct = any(e["id"] in known_first for e in correct)
                matches.append({
                    "gold_index": index + 1, "gold_polarity": actual,
                    "edge_ids": [e["id"] for e in matched],
                    "correct_edge_ids": [e["id"] for e in correct],
                    "known_first_match": first_match,
                    "known_first_correct": first_correct,
                    "completion_incremental_match_possible": not first_match,
                    "completion_incremental_correct_possible": bool(correct) and not first_correct,
                })
            contributions[path.name] = {
                "matched_gold": len(matches),
                "known_first_matches": sum(m["known_first_match"] for m in matches),
                "incremental_matches_bound": [0, sum(m["completion_incremental_match_possible"] for m in matches)],
                "incremental_correct_negative_bound": [0, sum(
                    m["completion_incremental_correct_possible"] and m["gold_polarity"] != "supports"
                    for m in matches
                )],
                "matches": matches,
            }
    first_attempts = sum(c["first_requests"] > 0 for c in chunk_receipts)
    retries = sum(c["retry_requests"] for c in chunk_receipts)
    completion_requests = sum(c["completion_requests"] for c in chunk_receipts)
    assert first_attempts + retries + completion_requests == len(calls)
    first_statements = sum(
        c["accepted_statements"] for c in chunk_receipts if not c["completion_response_usable"]
    )
    all_statements = sum(c["accepted_statements"] for c in chunk_receipts)
    reports.append({
        "run": run["run"], "requests": {
            "first": first_attempts, "first_including_retries": first_attempts + retries,
            "completion": completion_requests, "retries": retries, "total": len(calls),
            "status": status["engine_calls"], "provenance": len(calls),
            "http_terminal_engine_calls": http["terminal"].get("engine_calls"),
        },
        "request_passes": passes, "chunks": chunk_receipts,
        "completion_skipped": [e["payload"] for e in events if e["step"] == "extract.completion_skipped"],
        "transport_retries": [e["payload"] for e in events if e["step"] == "extract.transport_retry"],
        "parse_rejections": [e["payload"] for e in events if e["step"] == "extract.parse_rejected"],
        "engine_errors": [e["payload"] for e in events if e["step"] == "extract.engine_error"],
        "rejected_proposals": rejections,
        "completion_duplicates": [e["payload"] for e in events if e["step"] == "extract.completion_duplicate"],
        "statements": {
            "accepted_before_cross_chunk_merges": all_statements,
            "first_accepted_bound": [first_statements, all_statements],
            "completion_accepted_bound": [0, all_statements - first_statements],
            "persisted_edges": total_edges, "first_persisted_bound": [len(known_first), total_edges],
            "completion_persisted_bound": [0, total_edges - len(known_first)],
            "exact_first": None, "exact_completion": None,
        },
        "edge_pass_provenance": annotations, "completion_contribution": contributions,
    })
print(json.dumps({
    "runs": reports,
    "limitation": (
        "No raw responses or successful proposal-to-pass map are retained. Mixed-chunk "
        "edges cannot be assigned to a pass. Bounds use final node identities/aliases "
        "and identify direct persisted-edge contribution, not a first-only counterfactual "
        "or an effect of completion on later chunks. Unknown is not zero."
    ),
}, sort_keys=True))
