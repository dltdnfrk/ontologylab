"""P2-A: Frozen competency release gates.

Three competency questions (Q1/Q2/Q3) with frozen gold fixtures that pin
exact answers — not structural counts. The evaluator runs the current
pipeline (extraction → review → pack → query) against each fixture and
reports a per-question pass/fail receipt.

Q1 (provenance): every verified fact must trace to its exact source
document, extraction stream, and approval record.

Q2 (extraction): the mock extractor must produce the exact expected
entities and relations from a known document. Parser F1 is reported
separately as an informational metric, not a gate.

Q3 (pack-query): a built pack must return exact answers to user queries.

The evaluator is deterministic — no LLM judgment is used to score answers.
The MockEngine (CamelCase extraction) makes the pipeline offline and
reproducible, so the same fixture + same code always produces the same
receipt.
"""

from __future__ import annotations

import asyncio
import json
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ontologylab.extractor import (
    build_extraction_prompt,
    chunk_document,
    parse_and_validate_extraction,
)
from ontologylab.kgstore import KGStore, normalize_name
from ontologylab.models import Engine
from ontologylab.packbuilder import build_pack


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class QuestionResult:
    """One competency question's outcome."""

    question_id: str
    question: str
    passed: bool
    expected_count: int = 0
    actual_count: int = 0
    missing: list[Any] = field(default_factory=list)
    spurious: list[Any] = field(default_factory=list)
    detail: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "question_id": self.question_id,
            "question": self.question,
            "passed": self.passed,
            "expected_count": self.expected_count,
            "actual_count": self.actual_count,
            "missing": self.missing,
            "spurious": self.spurious,
            "detail": self.detail,
        }


@dataclass
class Receipt:
    """Full competency suite receipt."""

    questions: list[QuestionResult] = field(default_factory=list)
    all_passed: bool = False
    passed_count: int = 0
    total_count: int = 0
    evaluated_at: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "questions": [q.to_dict() for q in self.questions],
            "all_passed": self.all_passed,
            "passed_count": self.passed_count,
            "total_count": self.total_count,
            "evaluated_at": self.evaluated_at,
        }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _default_schema() -> dict[str, Any]:
    """Build the default schema dict for the mock extractor prompt."""
    from ontologylab.ontology_schema import (
        DEFAULT_ENTITY_TYPES,
        DEFAULT_RELATION_TYPES,
    )

    return {
        "entity_types": [
            {"name": name, "description": desc, "attributes": attrs}
            for name, (desc, attrs) in DEFAULT_ENTITY_TYPES.items()
        ],
        "relation_types": [
            {
                "name": name,
                "description": desc,
                "domain_type": domain,
                "range_type": range_,
                "directed": directed,
            }
            for name, (desc, domain, range_, directed) in (
                DEFAULT_RELATION_TYPES.items()
            )
        ],
    }


def _load_fixture(gold_dir: Path, name: str) -> dict[str, Any]:
    path = gold_dir / "cq" / f"{name}.json"
    return json.loads(path.read_text(encoding="utf-8"))


def _extract_for_competency(
    text: str, engine: Engine, *, prompt_version: str = "cq-v1"
) -> tuple[list[dict], list[dict]]:
    """Run engine extraction and return parsed entities/relations.

    Returns dicts with normalized names and relation triples — the
    deterministic output the fixtures pin against.
    """
    schema = _default_schema()
    chunks = chunk_document(text)

    all_entities: list[dict] = []
    all_relations: list[dict] = []
    seen_entities: set[tuple[str, str]] = set()
    seen_relations: set[tuple[str, str, str]] = set()

    for chunk in chunks:
        prompt = build_extraction_prompt(schema, chunk.text)
        raw, _usage = asyncio.run(engine.generate(prompt, model=None))
        result = parse_and_validate_extraction(
            raw, schema, chunk
        )
        for ent in result.entities:
            key = (normalize_name(ent.name), ent.entity_type)
            if key not in seen_entities:
                seen_entities.add(key)
                all_entities.append(
                    {
                        "normalized_name": normalize_name(ent.name),
                        "entity_type": ent.entity_type,
                        "name": ent.name,
                    }
                )
        for rel in result.relations:
            src_name = next(
                (
                    e.name
                    for e in result.entities
                    if e.id == rel.src_entity_id
                ),
                "",
            )
            dst_name = next(
                (
                    e.name
                    for e in result.entities
                    if e.id == rel.dst_entity_id
                ),
                "",
            )
            key = (
                normalize_name(src_name),
                rel.relation_type,
                normalize_name(dst_name),
            )
            if key not in seen_relations:
                seen_relations.add(key)
                all_relations.append(
                    {
                        "src_norm": normalize_name(src_name),
                        "relation_type": rel.relation_type,
                        "dst_norm": normalize_name(dst_name),
                    }
                )

    return all_entities, all_relations


# ---------------------------------------------------------------------------
# Q1: Provenance
# ---------------------------------------------------------------------------


def evaluate_q1(
    store: KGStore, fixture: dict[str, Any], *, engine: Engine
) -> QuestionResult:
    """Verify every verified fact traces to its exact source and approval."""
    cfg = fixture["configuration"]
    doc_cfg = cfg["document"]
    ext_cfg = cfg["extraction"]
    appr_cfg = cfg["approval"]
    expected = fixture["expected"]

    # Insert document
    document, created = store.insert_document(
        source_kind="upload",
        source_uri=doc_cfg.get("source_uri", "gold://cq/q1"),
        title=doc_cfg["title"],
        raw_text=doc_cfg["text"],
        content_hash="sha256:cq1",
    )

    # Extract with mock engine
    entities, relations = _extract_for_competency(
        doc_cfg["text"], engine, prompt_version=ext_cfg.get("prompt_version", "cq-v1")
    )

    # Insert proposals
    from ontologylab.models import ProposedEntity, ProposedRelation

    proposed_entities = [
        ProposedEntity(
            id=f"e{i}",
            name=e["name"],
            entity_type=e["entity_type"],
            properties={},
        )
        for i, e in enumerate(entities)
    ]
    # Build name->id map for relations (keyed by normalized name)
    name_to_id = {normalize_name(e.name): e.id for e in proposed_entities}
    proposed_relations = [
        ProposedRelation(
            id=f"r{i}",
            src_entity_id=name_to_id[r["src_norm"]],
            dst_entity_id=name_to_id[r["dst_norm"]],
            relation_type=r["relation_type"],
            properties={},
            qualifiers={},
        )
        for i, r in enumerate(relations)
        if r["src_norm"] in name_to_id and r["dst_norm"] in name_to_id
    ]

    result = store.insert_proposed(
        proposed_entities,
        proposed_relations,
        source_doc_id=document.id,
        extractor_engine=ext_cfg["engine"],
        extractor_model=None,
        prompt_version=ext_cfg.get("prompt_version"),
    )

    # Approve all nodes first, then edges (cascade=True for edges)
    node_ids = [
        row["id"]
        for row in store.conn.execute(
            "SELECT id FROM nodes WHERE status = 'proposed' ORDER BY normalized_name"
        )
    ]
    for nid in node_ids:
        store.approve(nid, by=appr_cfg["verified_by"])

    edge_ids = [
        row["id"]
        for row in store.conn.execute(
            "SELECT id FROM edges WHERE status = 'proposed' ORDER BY created_ts"
        )
    ]
    for eid in edge_ids:
        store.approve(eid, by=appr_cfg["verified_by"])

    # Now check provenance
    missing: list[Any] = []
    spurious: list[Any] = []

    # Check entities
    exp_entities = {(e["normalized_name"], e["entity_type"]): e for e in expected["entities"]}
    actual_entities = {}
    for row in store.conn.execute(
        """
        SELECT n.normalized_name, n.entity_type, n.status, n.verified_by,
               n.extractor_engine, d.title AS source_doc_title
        FROM nodes n
        JOIN documents d ON d.id = n.source_doc_id
        WHERE n.status = 'verified'
        """
    ):
        key = (row["normalized_name"], row["entity_type"])
        actual_entities[key] = dict(row)

    for key, exp in exp_entities.items():
        if key not in actual_entities:
            missing.append({"kind": "entity", "key": list(key)})
        else:
            actual = actual_entities[key]
            for field_name in ("source_doc_title", "extractor_engine", "status", "verified_by"):
                if actual.get(field_name) != exp.get(field_name):
                    missing.append(
                        {
                            "kind": "entity",
                            "key": list(key),
                            "field": field_name,
                            "expected": exp.get(field_name),
                            "actual": actual.get(field_name),
                        }
                    )

    for key, actual in actual_entities.items():
        if key not in exp_entities:
            spurious.append({"kind": "entity", "key": list(key)})

    # Check relations
    exp_rels = {
        (r["src_norm"], r["relation_type"], r["dst_norm"]): r
        for r in expected["relations"]
    }
    actual_rels = {}
    for row in store.conn.execute(
        """
        SELECT s.normalized_name AS src_norm, e.relation_type,
               d.normalized_name AS dst_norm, e.status, e.verified_by,
               e.extractor_engine, doc.title AS source_doc_title
        FROM edges e
        JOIN nodes s ON s.id = e.src_node_id
        JOIN nodes d ON d.id = e.dst_node_id
        JOIN documents doc ON doc.id = e.source_doc_id
        WHERE e.status = 'verified'
        """
    ):
        key = (row["src_norm"], row["relation_type"], row["dst_norm"])
        actual_rels[key] = dict(row)

    for key, exp in exp_rels.items():
        if key not in actual_rels:
            missing.append({"kind": "relation", "key": list(key)})
        else:
            actual = actual_rels[key]
            for field_name in ("source_doc_title", "extractor_engine", "status", "verified_by"):
                if actual.get(field_name) != exp.get(field_name):
                    missing.append(
                        {
                            "kind": "relation",
                            "key": list(key),
                            "field": field_name,
                            "expected": exp.get(field_name),
                            "actual": actual.get(field_name),
                        }
                    )

    for key, actual in actual_rels.items():
        if key not in exp_rels:
            spurious.append({"kind": "relation", "key": list(key)})

    passed = len(missing) == 0 and len(spurious) == 0
    return QuestionResult(
        question_id=fixture["question_id"],
        question=fixture["question"],
        passed=passed,
        expected_count=len(exp_entities) + len(exp_rels),
        actual_count=len(actual_entities) + len(actual_rels),
        missing=missing[:20],
        spurious=spurious[:20],
        detail={},
    )


# ---------------------------------------------------------------------------
# Q2: Extraction
# ---------------------------------------------------------------------------


def evaluate_q2(fixture: dict[str, Any], *, engine: Engine) -> QuestionResult:
    """Verify the extractor produces the exact expected entities and relations."""
    cfg = fixture["configuration"]
    doc_cfg = cfg["document"]
    expected = fixture["expected"]

    entities, relations = _extract_for_competency(doc_cfg["text"], engine)

    exp_entities = {
        (e["normalized_name"], e["entity_type"]) for e in expected["entities"]
    }
    act_entities = {(e["normalized_name"], e["entity_type"]) for e in entities}
    exp_relations = {
        (r["src_norm"], r["relation_type"], r["dst_norm"])
        for r in expected["relations"]
    }
    act_relations = {
        (r["src_norm"], r["relation_type"], r["dst_norm"]) for r in relations
    }

    missing_entities = sorted(exp_entities - act_entities)
    spurious_entities = sorted(act_entities - exp_entities)
    missing_relations = sorted(exp_relations - act_relations)
    spurious_relations = sorted(act_relations - exp_relations)

    # Parser F1 (informational, not a gate)
    tp = len(exp_entities & act_entities) + len(exp_relations & act_relations)
    fp = len(act_entities - exp_entities) + len(act_relations - exp_relations)
    fn = len(exp_entities - act_entities) + len(exp_relations - act_relations)
    precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    f1 = (
        2 * precision * recall / (precision + recall)
        if (precision + recall) > 0
        else 0.0
    )

    missing = (
        [{"kind": "entity", "key": list(k)} for k in missing_entities]
        + [{"kind": "relation", "key": list(k)} for k in missing_relations]
    )
    spurious = (
        [{"kind": "entity", "key": list(k)} for k in spurious_entities]
        + [{"kind": "relation", "key": list(k)} for k in spurious_relations]
    )

    passed = len(missing) == 0 and len(spurious) == 0
    return QuestionResult(
        question_id=fixture["question_id"],
        question=fixture["question"],
        passed=passed,
        expected_count=len(exp_entities) + len(exp_relations),
        actual_count=len(act_entities) + len(act_relations),
        missing=missing[:20],
        spurious=spurious[:20],
        detail={"parser_f1": round(f1, 4)},
    )


# ---------------------------------------------------------------------------
# Q3: Pack-query
# ---------------------------------------------------------------------------


def evaluate_q3(
    store: KGStore,
    packs_dir: str | Path,
    fixture: dict[str, Any],
    *,
    engine: Engine,
) -> QuestionResult:
    """Verify a built pack returns exact answers to user queries."""
    cfg = fixture["configuration"]
    doc_cfg = cfg["document"]
    ext_cfg = cfg["extraction"]
    appr_cfg = cfg["approval"]
    pack_name = cfg.get("pack_name", "cq-release-pack")
    expected = fixture["expected"]

    # If the store is empty, seed it (Q3 may reuse Q1's store or get its own)
    if store.conn.execute("SELECT COUNT(*) AS n FROM nodes").fetchone()["n"] == 0:
        document, _ = store.insert_document(
            source_kind="upload",
            source_uri=doc_cfg.get("source_uri", "gold://cq/q3"),
            title=doc_cfg["title"],
            raw_text=doc_cfg["text"],
            content_hash="sha256:cq3",
        )
        entities, relations = _extract_for_competency(
            doc_cfg["text"], engine, prompt_version=ext_cfg.get("prompt_version", "cq-v1")
        )
        from ontologylab.models import ProposedEntity, ProposedRelation

        proposed_entities = [
            ProposedEntity(
                id=f"e{i}", name=e["name"], entity_type=e["entity_type"],
                properties={},
            )
            for i, e in enumerate(entities)
        ]
        name_to_id = {normalize_name(e.name): e.id for e in proposed_entities}
        proposed_relations = [
            ProposedRelation(
                id=f"r{i}",
                src_entity_id=name_to_id.get(r["src_norm"], ""),
                dst_entity_id=name_to_id.get(r["dst_norm"], ""),
                relation_type=r["relation_type"],
                properties={}, qualifiers={},
            )
            for i, r in enumerate(relations)
            if r["src_norm"] in name_to_id and r["dst_norm"] in name_to_id
        ]
        store.insert_proposed(
            proposed_entities, proposed_relations,
            source_doc_id=document.id,
            extractor_engine=ext_cfg["engine"],
            prompt_version=ext_cfg.get("prompt_version"),
        )
        for row in store.conn.execute(
            "SELECT id FROM nodes WHERE status = 'proposed'"
        ):
            store.approve(row["id"], by=appr_cfg["verified_by"])
        for row in store.conn.execute(
            "SELECT id FROM edges WHERE status = 'proposed'"
        ):
            store.approve(row["id"], by=appr_cfg["verified_by"])

    # Build a pack
    kg_path = store.conn.execute("PRAGMA database_list").fetchone()["file"]
    manifest = build_pack(
        kg_path, packs_dir, pack_name,
        allow_incomplete_extraction=True,
        incomplete_extraction_intent="competency-release-gate: manually seeded verified data",
    )

    # Open the pack's KGStore and query
    pack_db = Path(packs_dir) / manifest.pack_id / "pack.sqlite"
    pack_store = KGStore.open(pack_db, read_only=True)

    try:
        # Query verified entities
        actual_entities = sorted(
            row["normalized_name"]
            for row in pack_store.conn.execute(
                "SELECT normalized_name FROM nodes WHERE status = 'verified' ORDER BY normalized_name"
            )
        )
        # Query verified relations
        actual_relations = []
        for row in pack_store.conn.execute(
            """
            SELECT s.normalized_name AS src_norm, e.relation_type,
                   d.normalized_name AS dst_norm
            FROM edges e
            JOIN nodes s ON s.id = e.src_node_id
            JOIN nodes d ON d.id = e.dst_node_id
            WHERE e.status = 'verified'
            ORDER BY s.normalized_name, e.relation_type, d.normalized_name
            """
        ):
            actual_relations.append(dict(row))

        # Graph query for 'uses' relations
        gq = pack_store.graph_query(relation_type="uses")
        gq_nodes = sorted(
            normalize_name(n["name"]) for n in gq.get("nodes", [])
        )
        gq_edges = []
        for e in gq.get("edges", []):
            gq_edges.append(
                {
                    "src_norm": e.get("src_name", e.get("src", "")),
                    "relation_type": e.get("relation_type", ""),
                    "dst_norm": e.get("dst_name", e.get("dst", "")),
                }
            )

        pack_store.close()
    except Exception:
        pack_store.close()
        raise

    # Check against expected
    missing: list[Any] = []
    spurious: list[Any] = []

    exp_entities = sorted(expected["verified_entities"])
    if actual_entities != exp_entities:
        missing.append(
            {
                "kind": "verified_entities",
                "expected": exp_entities,
                "actual": actual_entities,
            }
        )

    exp_relations = sorted(
        (r["src_norm"], r["relation_type"], r["dst_norm"])
        for r in expected["verified_relations"]
    )
    act_relations = sorted(
        (r["src_norm"], r["relation_type"], r["dst_norm"])
        for r in actual_relations
    )
    if exp_relations != act_relations:
        missing.append(
            {
                "kind": "verified_relations",
                "expected": [list(t) for t in exp_relations],
                "actual": [list(t) for t in act_relations],
            }
        )

    exp_gq = expected.get("graph_query_uses", {})
    if exp_gq:
        exp_gq_nodes = sorted(exp_gq.get("nodes", []))
        if gq_nodes != exp_gq_nodes:
            spurious.append(
                {
                    "kind": "graph_query_nodes",
                    "expected": exp_gq_nodes,
                    "actual": gq_nodes,
                }
            )

    passed = len(missing) == 0 and len(spurious) == 0
    return QuestionResult(
        question_id=fixture["question_id"],
        question=fixture["question"],
        passed=passed,
        expected_count=len(exp_entities) + len(exp_relations),
        actual_count=len(actual_entities) + len(actual_relations),
        missing=missing[:20],
        spurious=spurious[:20],
        detail={"pack_id": manifest.pack_id},
    )


# ---------------------------------------------------------------------------
# Suite runner
# ---------------------------------------------------------------------------


def run_competency_suite(
    gold_dir: str | Path,
    *,
    engine: Engine,
    data_dir: str | Path | None = None,
    packs_dir: str | Path | None = None,
) -> Receipt:
    """Run all three competency questions and return a structured receipt.

    If data_dir/packs_dir are not given, temporary directories are created
    and cleaned up. When given, the caller owns cleanup.
    """
    gold_path = Path(gold_dir)
    cleanup: list[Path] = []

    if data_dir is None:
        data_dir = Path(tempfile.mkdtemp(prefix="cq-data-"))
        cleanup.append(Path(data_dir))
    if packs_dir is None:
        packs_dir = Path(tempfile.mkdtemp(prefix="cq-packs-"))
        cleanup.append(Path(packs_dir))

    data_path = Path(data_dir)
    packs_path = Path(packs_dir)
    packs_path.mkdir(parents=True, exist_ok=True)

    questions: list[QuestionResult] = []

    # Q1 + Q3 share one store (Q3 reuses Q1's approved data)
    store = KGStore.open(data_path / "kg.sqlite")
    try:
        q1_fixture = _load_fixture(gold_path, "q1-provenance")
        questions.append(evaluate_q1(store, q1_fixture, engine=engine))

        q2_fixture = _load_fixture(gold_path, "q2-extraction")
        questions.append(evaluate_q2(q2_fixture, engine=engine))

        q3_fixture = _load_fixture(gold_path, "q3-pack-query")
        questions.append(evaluate_q3(store, packs_path, q3_fixture, engine=engine))
    finally:
        store.close()

    # Clean up temp dirs
    import shutil
    for d in cleanup:
        shutil.rmtree(d, ignore_errors=True)

    passed_count = sum(1 for q in questions if q.passed)
    receipt = Receipt(
        questions=questions,
        all_passed=passed_count == len(questions),
        passed_count=passed_count,
        total_count=len(questions),
        evaluated_at=time.time(),
    )
    return receipt


def main() -> None:
    """CLI entry: run the competency suite and exit 0 if all pass."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Run frozen competency release gates"
    )
    parser.add_argument(
        "--gold",
        default=str(Path(__file__).resolve().parent.parent / "tests" / "gold"),
        help="Gold fixtures directory (default: tests/gold)",
    )
    args = parser.parse_args()

    from ontologylab.engines import resolve_engine

    receipt = run_competency_suite(args.gold, engine=resolve_engine("mock"))
    print(json.dumps(receipt.to_dict(), indent=2, ensure_ascii=False))
    sys.exit(0 if receipt.all_passed else 1)


if __name__ == "__main__":
    main()
