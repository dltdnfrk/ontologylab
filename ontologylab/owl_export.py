"""Export a schema version as OWL 2 / RDFS Turtle.

The store's schema model is a typed property graph, not a description
logic — this export is the bridge to tools that need one (Protégé, a
DL reasoner, an ontology catalog). The mapping is deliberately the
RDFS/OWL-lite fragment the model actually carries:

    entity_type            → owl:Class
    parent_name            → rdfs:subClassOf
    relation_type          → owl:ObjectProperty (+ owl:SymmetricProperty
                             when undirected)
    domain_type/range_type → rdfs:domain / rdfs:range ('*' omits the
                             constraint — an unconstrained side is not
                             owl:Thing, it is simply unstated)
    entity attributes      → owl:DatatypeProperty, rdfs:domain the class,
                             rdfs:range the XSD type the attribute
                             declares (unknown types fall back to
                             rdfs:Literal)

Local IRIs under LOCAL_TERM_IRI_BASE for classes and a sibling base for
properties — the same identity discipline as the SKOS export.
"""

from __future__ import annotations

from typing import Any

from ontologylab.ontology_schema import LOCAL_TERM_IRI_BASE

_PROPERTY_IRI_BASE = f"{LOCAL_TERM_IRI_BASE}/property"

_XSD = {
    "string": "xsd:string",
    "text": "xsd:string",
    "number": "xsd:double",
    "float": "xsd:double",
    "integer": "xsd:integer",
    "int": "xsd:integer",
    "boolean": "xsd:boolean",
    "bool": "xsd:boolean",
}


def _esc(text: str) -> str:
    return (
        text.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\n", "\\n")
        .replace("\r", "\\r")
    )


def _local_name(name: str) -> str:
    # IRIs cannot carry spaces or most punctuation; the term id is the
    # stable identity, so the readable name is only a label.
    return "".join(c if c.isalnum() or c in "_-" else "_" for c in name)


def export_owl(store, schema_version_id: int | None = None) -> str:
    """Render one schema version (default: active) as OWL 2 Turtle."""
    schema = store.get_schema(schema_version_id)
    entity_names = {e["name"] for e in schema["entity_types"]}

    lines = [
        "@prefix owl: <http://www.w3.org/2002/07/owl#> .",
        "@prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .",
        "@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .",
        "@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .",
        f"@prefix ol: <{LOCAL_TERM_IRI_BASE}/> .",
        f"@prefix olp: <{_PROPERTY_IRI_BASE}/> .",
        "",
        f"<{LOCAL_TERM_IRI_BASE}/schema/{schema['schema_version_id']}>",
        "    a owl:Ontology ;",
        f'    rdfs:label "{_esc(schema["schema_label"])}" .',
        "",
    ]

    for e in schema["entity_types"]:
        lines.append(f"ol:{_local_name(e['name'])} a owl:Class ;")
        lines.append(f'    rdfs:label "{_esc(e["name"])}" ;')
        if (e.get("description") or "").strip():
            lines.append(f'    rdfs:comment "{_esc(e["description"])}" ;')
        if e.get("parent") and e["parent"] in entity_names:
            lines.append(
                f"    rdfs:subClassOf ol:{_local_name(e['parent'])} ;"
            )
        lines[-1] = lines[-1].rstrip(" ;") + " ."
        lines.append("")

        for attr_name, spec in (e.get("attributes") or {}).items():
            xsd = _XSD.get(
                str((spec or {}).get("type", "")).lower(), "rdfs:Literal"
            )
            prop = f"olp:{_local_name(e['name'])}__{_local_name(attr_name)}"
            lines.append(f"{prop} a owl:DatatypeProperty ;")
            lines.append(f'    rdfs:label "{_esc(attr_name)}" ;')
            lines.append(f"    rdfs:domain ol:{_local_name(e['name'])} ;")
            lines.append(f"    rdfs:range {xsd} .")
            lines.append("")

    for r in schema["relation_types"]:
        types = ["owl:ObjectProperty"]
        if not r.get("directed", True):
            types.append("owl:SymmetricProperty")
        lines.append(f"olp:{_local_name(r['name'])} a {' , '.join(types)} ;")
        lines.append(f'    rdfs:label "{_esc(r["name"])}" ;')
        if (r.get("description") or "").strip():
            lines.append(f'    rdfs:comment "{_esc(r["description"])}" ;')
        domain = r.get("domain_type", "*")
        range_ = r.get("range_type", "*")
        if domain in entity_names:
            lines.append(f"    rdfs:domain ol:{_local_name(domain)} ;")
        if range_ in entity_names:
            lines.append(f"    rdfs:range ol:{_local_name(range_)} ;")
        lines[-1] = lines[-1].rstrip(" ;") + " ."
        lines.append("")

    return "\n".join(lines)
