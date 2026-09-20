"""Export a schema version as SKOS Turtle — the symmetric counterpart of
skos_import.

The mapping mirrors the importer exactly, so a round trip preserves what
the model can express: entity_type → skos:Concept, parent_name →
skos:broader, term_alias → skos:altLabel/hiddenLabel, term_xref → a SKOS
mapping property when the external id is an IRI and skos:notation when it
is not. Relation types are not SKOS concepts; they belong to the OWL
export, not this one.

Identifiers are local IRIs under LOCAL_TERM_IRI_BASE — the same base the
term table's CHECK constraint enforces, so the export never invents an
identity the store would reject on re-import.
"""

from __future__ import annotations

from typing import Any

from ontologylab.ontology_schema import LOCAL_TERM_IRI_BASE

_XREF_TO_SKOS = {
    "exact": "skos:exactMatch",
    "close": "skos:closeMatch",
    "broader": "skos:broadMatch",
    "narrower": "skos:narrowMatch",
    "related": "skos:relatedMatch",
    # 'advisory' has no SKOS mapping property; it exports as notation.
}


def _esc(text: str) -> str:
    return (
        text.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\n", "\\n")
        .replace("\r", "\\r")
    )


def _lang_tag(language: str) -> str:
    return f"@{language}" if language else ""


def _is_iri(value: str) -> bool:
    return "://" in value or value.startswith("urn:")


def export_skos(store, schema_version_id: int | None = None) -> str:
    """Render one schema version (default: active) as SKOS Turtle."""
    schema = store.get_schema(schema_version_id)
    sv_id = schema["schema_version_id"]

    # entity_type → its ontology_term row (the identity the aliases and
    # xrefs hang off).
    term_rows = store.conn.execute(
        "SELECT t.id AS term_id, t.iri AS iri, t.language AS language, "
        "e.name AS name FROM ontology_term t "
        "JOIN entity_type e ON e.id = t.legacy_id "
        "WHERE t.legacy_kind = 'entity_type' AND t.schema_version_id = ?",
        (sv_id,),
    ).fetchall()
    term_by_name = {r["name"]: r for r in term_rows}

    lines = [
        "@prefix skos: <http://www.w3.org/2004/02/skos/core#> .",
        "@prefix dct: <http://purl.org/dc/terms/> .",
        f"@prefix ol: <{LOCAL_TERM_IRI_BASE}/> .",
        "",
    ]
    for e in schema["entity_types"]:
        term = term_by_name.get(e["name"])
        subject = f"ol:{term['term_id']}" if term else f"<#{e['name']}>"
        lines.append(f"{subject} a skos:Concept ;")
        lang = _lang_tag(term["language"] if term else "")
        lines.append(f'    skos:prefLabel "{_esc(e["name"])}"{lang} ;')
        if (e.get("description") or "").strip():
            lines.append(f'    skos:definition "{_esc(e["description"])}"{lang} ;')
        if e.get("parent"):
            parent_term = term_by_name.get(e["parent"])
            parent_ref = (
                f"ol:{parent_term['term_id']}"
                if parent_term
                else f"<#{e['parent']}>"
            )
            lines.append(f"    skos:broader {parent_ref} ;")
        if term:
            for a in store.list_term_aliases(term["term_id"]):
                pred = (
                    "skos:hiddenLabel"
                    if a["alias_kind"] == "hidden"
                    else "skos:altLabel"
                )
                lines.append(
                    f'    {pred} "{_esc(a["label"])}"'
                    f'{_lang_tag(a["language"])} ;'
                )
            for x in store.list_term_xrefs(term["term_id"]):
                if x["lifecycle"] != "active":
                    continue
                pred = _XREF_TO_SKOS.get(x["mapping_predicate"])
                if pred and _is_iri(x["external_id"]):
                    lines.append(f"    {pred} <{x['external_id']}> ;")
                else:
                    lines.append(
                        f'    skos:notation "{_esc(x["external_id"])}" ;'
                    )
        lines[-1] = lines[-1].rstrip(" ;") + " ."
        lines.append("")
    return "\n".join(lines)
