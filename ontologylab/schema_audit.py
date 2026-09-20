"""Static pitfall audit for a schema version — the OOPS!-style check the
pipeline never had.

OOPS! (OntOlogy Pitfall Scanner) catalogs the mistakes ontology authors
actually make: missing annotations, unconstrained relations, isolated
types. This module is the local, stdlib-only equivalent for the store's
schema model — no reasoner, no network, just the checks the data model
can support. Install-time validation already rejects unknown parents and
cycles; these are the defects that are legal but wrong.

Severity: ``warning`` is a defect worth fixing before the schema drives
extraction; ``info`` is a smell that may be deliberate (a fresh schema
has no instances yet).
"""

from __future__ import annotations

from typing import Any

from ontologylab.kgstore_base import normalize_name


def audit_schema(store, schema_version_id: int | None = None) -> dict[str, Any]:
    """Audit one schema version (default: active) for static pitfalls."""
    schema = store.get_schema(schema_version_id)
    sv_id = schema["schema_version_id"]
    findings: list[dict[str, Any]] = []

    def add(pitfall: str, severity: str, subject: str, detail: str) -> None:
        findings.append(
            {
                "pitfall": pitfall,
                "severity": severity,
                "subject": subject,
                "detail": detail,
            }
        )

    entity_types = schema["entity_types"]
    relation_types = schema["relation_types"]
    entity_names = {e["name"] for e in entity_types}

    # Missing annotations — a type with no description gives the extractor
    # and the reviewer nothing to judge membership against.
    for e in entity_types:
        if not (e.get("description") or "").strip():
            add("missing-description", "warning", e["name"],
                "entity type has no description")
    for r in relation_types:
        if not (r.get("description") or "").strip():
            add("missing-description", "warning", r["name"],
                "relation type has no description")

    # Unconstrained relations — domain and range both '*' means the
    # extractor can attach it to anything, which is how 'related_to'
    # graphs happen.
    for r in relation_types:
        domain, range_ = r.get("domain_type", "*"), r.get("range_type", "*")
        if domain == "*" and range_ == "*":
            add("unconstrained-relation", "warning", r["name"],
                "relation has neither domain nor range constraint")
        elif domain == "*" or range_ == "*":
            side = "domain" if domain == "*" else "range"
            add("partially-unconstrained-relation", "info", r["name"],
                f"relation has no {side} constraint")

    # Orphan types — an entity type no relation can reach is a leaf the
    # graph can populate but never connect.
    connected = set()
    for r in relation_types:
        for side in ("domain_type", "range_type"):
            t = r.get(side, "*")
            if t in entity_names:
                connected.add(t)
    for e in entity_types:
        if e["name"] not in connected and not e.get("parent"):
            add("orphan-type", "info", e["name"],
                "entity type is unreachable by any relation and has no parent")

    # Normalized-name collisions — two types that normalize to the same
    # key resolve against each other in extraction output.
    seen: dict[str, str] = {}
    for e in entity_types:
        key = normalize_name(e["name"])
        if key in seen:
            add("name-collision", "warning", e["name"],
                f"normalizes to the same key as {seen[key]!r}")
        else:
            seen[key] = e["name"]

    # Usage — a type with no instances may be a fresh schema or dead
    # vocabulary; reported as info, never a warning.
    used_types = {
        r["entity_type"]
        for r in store.conn.execute(
            "SELECT DISTINCT entity_type FROM nodes WHERE schema_version_id = ?",
            (sv_id,),
        )
    }
    used_relations = {
        r["relation_type"]
        for r in store.conn.execute(
            "SELECT DISTINCT relation_type FROM edges WHERE schema_version_id = ?",
            (sv_id,),
        )
    }
    for e in entity_types:
        if e["name"] not in used_types:
            add("unused-type", "info", e["name"],
                "no nodes of this type under this schema version")
    for r in relation_types:
        if r["name"] not in used_relations:
            add("unused-relation", "info", r["name"],
                "no edges of this type under this schema version")

    # CQ coverage — a schema that cannot express its own questions.
    cq = store.check_schema_cqs(sv_id)
    for q in cq["questions"]:
        if not q["covered"]:
            if q["reason"] == "unscoped":
                add("unscoped-cq", "info", q["id"],
                    f"competency question names no terms: {q['question']!r}")
            else:
                add("uncovered-cq", "warning", q["id"],
                    f"competency question needs undeclared terms "
                    f"{q['missing']}: {q['question']!r}")

    return {
        "schema_version_id": sv_id,
        "schema_label": schema["schema_label"],
        "findings": findings,
        "warnings": sum(1 for f in findings if f["severity"] == "warning"),
        "info": sum(1 for f in findings if f["severity"] == "info"),
    }
