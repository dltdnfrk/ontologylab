"""Read-only trial accounting; no provider calls or store writes."""
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import sys
from typing import Any

from ontologylab.claims import find_contradictions
from ontologylab.method_store import prepare_method_connection
from ontologylab.extractor import PROMPT_VERSION
from ontologylab.polarity_eval import _rate, score_polarity, validate_gold
from ontologylab.schemas import preset

gold_path = Path(sys.argv[1])
qualified = gold_path.name in (
    "gold-aligned-qualified.json", "gold-qualified-normalized.json",
    "gold-adjudicated-qualified.json",
)
claim_types = {
    relation["name"] for relation in preset("agrochem-v2")["relation_types"]
    if "polarity" in relation["qualifiers"]
}
reports = []
metric_names = (
    "polarity_accuracy", "recall_no_effect", "recall_refutes",
    "recall_no_effect_refutes", "supports_when_gold_no_effect_flip_rate",
)
for directory in map(Path, sys.argv[2:]):
    wal = directory / "kg.sqlite-wal"
    assert not wal.exists() or wal.stat().st_size == 0
    http = json.loads((directory / "http-receipt.json").read_text())
    conn = sqlite3.connect(f"file:{directory}/kg.sqlite?mode=ro&immutable=1", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA query_only=ON")
        prepare_method_connection(conn)
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert not conn.execute("PRAGMA foreign_key_check").fetchall()
        jobs = [dict(r) for r in conn.execute("SELECT * FROM runs")]
        extraction_jobs = [job for job in jobs if job["kind"] == "extract"]
        assert len(extraction_jobs) == 1
        job = extraction_jobs[0]
        assert job["status"] != "running"
        runs = [dict(r) for r in conn.execute("SELECT * FROM extraction_runs")]
        chunks = [dict(r) for r in conn.execute("SELECT * FROM extraction_chunks")]
        stats = [json.loads(c["stats_json"]) for c in chunks if c["stats_json"]]
        edges = [dict(r) for r in conn.execute(
            "SELECT * FROM edges WHERE status IN ('proposed','verified') "
            "AND invalidated_ts IS NULL"
        )]
        claims = [e for e in edges if e["relation_type"] in claim_types]
        labels = Counter(json.loads(e["qualifiers_json"]).get("polarity", "")
                         for e in claims)
        job_dir = directory / "jobs" / job["id"]
        status = json.loads((job_dir / "status.json").read_text())
        events = [json.loads(line) for line in
                  (job_dir / "provenance.jsonl").read_text().splitlines()]
        calls = [e for e in events if e["payload"].get("engine_call")]
        assert len(calls) == status["engine_calls"] <= 60
        assert all(json.loads(r["decode_params"]) == {"temperature": 0.0} for r in runs)
        assert all(r["prompt_version"] == PROMPT_VERSION for r in runs)
        contradictions = find_contradictions(conn, include_proposed=True, limit=10000)
        pairs = [
            {"subject": group["subject"], "relation": group["relation"],
             "object": group["object"], "supporting_id": support["edge_id"],
             "no_effect_id": opposing["edge_id"]}
            for group in contradictions["contradictions"]
            for support in group["supporting"] if support["polarity"] == "supports"
            for opposing in group["opposing"] if opposing["polarity"] == "no_effect"
        ]
        assert all(pair["supporting_id"] != pair["no_effect_id"] for pair in pairs)
        rejected = [e for e in events if e["step"] == "extract.proposal_rejected"]
        rejections = {key: sum(e["payload"]["kind"] == kind for e in rejected)
                      for key, kind in (("entities_rejected", "entity"), ("relations_rejected", "relation"))}
        assert all(http["terminal"]["totals"][k] == v for k, v in rejections.items())
        report = {
            "integrity": "ok", "foreign_key_errors": [],
            "status_engine_calls": status["engine_calls"],
            "status_counter_agrees": len(calls) == status["engine_calls"],
            "rejected_proposals": rejections, "rejection_events": rejected,
            "budget": [e["payload"] for e in events if e["step"] == "extract.budget"],
            "http_receipt": http,
            "attempted_chunks": sum(c["attempts"] > 0 for c in chunks),
            "expected_chunks": 21,
            "coverage": _rate([c["status"] == "succeeded" for c in chunks] + [False] * (21 - len(chunks))),
            "nodes": [dict(r) for r in conn.execute("SELECT * FROM nodes")],
            "aliases": [dict(r) for r in conn.execute("SELECT * FROM node_aliases")],
            "edges": edges,
            "data_dir": str(directory), "job": job,
            "documents": [dict(r) for r in conn.execute(
                "SELECT id,title,source_kind,content_hash FROM documents ORDER BY title")],
            "observations": [dict(r) for r in conn.execute(
                "SELECT representation_id,content_kind,source FROM document_observations")],
            "extraction_runs": runs, "chunks": chunks,
            "chunk_status_counts": dict(Counter(c["status"] for c in chunks)),
            "engine_calls": len(calls),
            "engine_request_decode_params": [
                e["payload"]["usage_meta"].get("decode_params") for e in calls],
            "parse_rejections": sum(e["step"] == "extract.parse_rejected" for e in events),
            "engine_errors": sum(e["step"] == "extract.engine_error" for e in events),
            "warning_count": sum(e["step"] == "extract.warning" for e in events),
            "stage_rows": [dict(r) for r in conn.execute(
                "SELECT relation_type, COALESCE(json_extract(qualifiers_json,'$.polarity'),'') "
                "AS polarity, COUNT(*) AS n FROM edges WHERE status IN ('proposed','verified') "
                "AND invalidated_ts IS NULL GROUP BY 1,2")],
            "g1": _rate([c["status"] == "succeeded" for c in chunks]),
            "g2": {**_rate([json.loads(e["qualifiers_json"]).get("polarity", "") in ("supports", "no_effect", "refutes") for e in claims]), "labels": dict(labels)},
            "g3": score_polarity(conn, gold_path, qualified=qualified),
            "g4": {"all_edge_merges": sum(s["edges_merged"] for s in stats),
                   "supports_no_effect_pairs": pairs,
                   "observed_collapses": sum(p["supporting_id"] == p["no_effect_id"] for p in pairs),
                   "contradictions_total": contradictions["total"]},
            "verified_edges": conn.execute(
                "SELECT COUNT(*) FROM edges WHERE status='verified'").fetchone()[0],
            "provenance_sha256": hashlib.sha256(
                (job_dir / "provenance.jsonl").read_bytes()).hexdigest(),
            "status_sha256": hashlib.sha256((job_dir / "status.json").read_bytes()).hexdigest(),
        }
        reports.append(report)
    finally:
        conn.close()

pooled: dict[str, Any] = {
    gate: {field: sum(r[gate][field] for r in reports)
           for field in ("numerator","denominator")}
    for gate in ("g1","g2")
}
for gate in ("g1", "g2"):
    pooled[gate] = _rate([value for report in reports for value in ([True] * report[gate]["numerator"] + [False] * (report[gate]["denominator"] - report[gate]["numerator"]))])
pooled["g3"] = {
    metric: _rate([
        outcome
        for report in reports
        for outcome in (
            [True] * report["g3"][metric]["numerator"]
            + [False] * (report["g3"][metric]["denominator"]
                         - report["g3"][metric]["numerator"])
        )
    ])
    for metric in metric_names
}
pooled["g4"] = {
    "observed_collapses": sum(r["g4"]["observed_collapses"] for r in reports),
    "all_edge_merges": sum(r["g4"]["all_edge_merges"] for r in reports),
    "coexisting_supports_no_effect_pairs": sum(
        len(r["g4"]["supports_no_effect_pairs"]) for r in reports),
}
payload = {"gold_validation": validate_gold(gold_path, qualified=qualified), "reports": reports,
           "pooled": pooled}
text = json.dumps(payload, sort_keys=True)
key = os.environ.get("GOOGLE_API_KEY", "")
print(text.replace(key, "[REDACTED]") if key else text)
