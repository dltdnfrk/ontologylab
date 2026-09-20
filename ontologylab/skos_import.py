"""SKOS (Turtle subset) import: external vocabularies become schemas.

The pipeline's schema layer was write-only — every ontology had to be
authored by hand or picked from the three bundled presets. Most real
vocabularies ship as SKOS, so this module parses a bounded Turtle subset
and maps it onto ``install_schema``:

- ``skos:Concept``            → entity_type (prefLabel → name)
- ``skos:broader``            → entity_type.parent (is-a)
- ``skos:definition``/``note``/``scopeNote`` → entity_type.description
- ``skos:altLabel``/``hiddenLabel`` → term_alias (alternative / hidden)
- ``skos:*Match``             → term_xref (identifier-only license gate)

The parser is deliberately a subset: @prefix/@base, ``a``, IRIs, prefixed
names, plain and lang-tagged literals, ``;``/``,``/``.`` separators, and
``#`` comments. Blank nodes, collections, and multi-line literals are out
of scope — a file that needs them fails loudly rather than half-parsing.

Standard library only.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from typing import Any

from ontologylab.kgstore import KGStore, KGStoreError

SKOS_NS = "http://www.w3.org/2004/02/skos/core#"
RDF_TYPE = "http://www.w3.org/1999/02/22-rdf-syntax-ns#type"

# SKOS mapping properties → our xref predicates (XREF_MAPPING_PREDICATES).
_MATCH_PREDICATES = {
    "exactMatch": "exact",
    "closeMatch": "close",
    "broadMatch": "broader",
    "narrowMatch": "narrower",
    "relatedMatch": "related",
}


class SkosParseError(KGStoreError):
    """A Turtle construct outside the supported subset."""


@dataclass
class _Concept:
    iri: str
    pref_label: str = ""
    language: str = "en"
    definition: str = ""
    broader: list[str] = field(default_factory=list)
    alt_labels: list[tuple[str, str]] = field(default_factory=list)
    hidden_labels: list[tuple[str, str]] = field(default_factory=list)
    matches: list[tuple[str, str]] = field(default_factory=list)
    declared_types: list[str] = field(default_factory=list)


_PREFIX_RE = re.compile(r"@prefix\s+(\w*):\s*<([^>]+)>\s*\.")
_BASE_RE = re.compile(r"@base\s+<([^>]+)>\s*\.")
_LITERAL_RE = re.compile(
    r'^"(?P<text>(?:[^"\\]|\\.)*)"(?:@(?P<lang>[a-zA-Z-]+)|\^\^(?P<dt>\S+))?$'
)


def _unescape(text: str) -> str:
    return (
        text.replace("\\\"", '"')
        .replace("\\n", "\n")
        .replace("\\t", "\t")
        .replace("\\\\", "\\")
    )


def _split_statements(body: str) -> list[str]:
    """Split on top-level '.' — a '.' inside <> or "" does not end a statement."""
    out: list[str] = []
    depth_angle = 0
    in_string = False
    escaped = False
    start = 0
    for i, ch in enumerate(body):
        if in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch == "<":
            depth_angle += 1
        elif ch == ">":
            depth_angle = max(0, depth_angle - 1)
        elif ch == "." and depth_angle == 0:
            stmt = body[start:i].strip()
            if stmt:
                out.append(stmt)
            start = i + 1
    tail = body[start:].strip()
    if tail:
        out.append(tail)
    return out


def _split_top(body: str, sep: str) -> list[str]:
    """Split on a separator that does not apply inside <> or ""."""
    out: list[str] = []
    depth_angle = 0
    in_string = False
    escaped = False
    start = 0
    for i, ch in enumerate(body):
        if in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch == "<":
            depth_angle += 1
        elif ch == ">":
            depth_angle = max(0, depth_angle - 1)
        elif ch == sep and depth_angle == 0:
            out.append(body[start:i])
            start = i + 1
    out.append(body[start:])
    return [p.strip() for p in out if p.strip()]


def _strip_comments(text: str) -> str:
    lines = []
    for line in text.splitlines():
        in_string = False
        in_angle = False
        escaped = False
        cut = len(line)
        for i, ch in enumerate(line):
            if in_string:
                if escaped:
                    escaped = False
                elif ch == "\\":
                    escaped = True
                elif ch == '"':
                    in_string = False
                continue
            if ch == '"' and not in_angle:
                in_string = True
            elif ch == "<":
                in_angle = True
            elif ch == ">":
                in_angle = False
            elif ch == "#" and not in_angle:
                cut = i
                break
        lines.append(line[:cut])
    return "\n".join(lines)


def parse_skos_turtle(text: str) -> dict[str, _Concept]:
    """Parse the supported Turtle subset into {subject-iri: _Concept}."""
    prefixes: dict[str, str] = {
        "skos": SKOS_NS,
        "rdf": "http://www.w3.org/1999/02/22-rdf-syntax-ns#",
    }
    base = ""
    body = _strip_comments(text)

    def consume_directives() -> None:
        nonlocal body, base
        while True:
            m = _PREFIX_RE.match(body.lstrip())
            if m:
                prefixes[m.group(1)] = m.group(2)
                body = body.lstrip()[m.end():]
                continue
            m = _BASE_RE.match(body.lstrip())
            if m:
                base = m.group(1)
                body = body.lstrip()[m.end():]
                continue
            break

    def expand(token: str) -> str:
        token = token.strip()
        if token.startswith("<") and token.endswith(">"):
            iri = token[1:-1]
            return base + iri if base and ":" not in iri else iri
        if ":" in token:
            prefix, local = token.split(":", 1)
            if prefix in prefixes:
                return prefixes[prefix] + local
            if re.match(r"^[a-zA-Z][\w+.-]*$", prefix):
                return token  # absolute IRI with scheme
        raise SkosParseError(f"cannot resolve term {token!r}")

    consume_directives()
    concepts: dict[str, _Concept] = {}
    for stmt in _split_statements(body):
        parts = _split_top(stmt, ";")
        if not parts:
            continue
        head = parts[0].split(None, 1)
        if len(head) != 2:
            raise SkosParseError(f"malformed statement {stmt[:80]!r}")
        subject = expand(head[0])
        pred_obj = head[1] + ("; " + "; ".join(parts[1:]) if len(parts) > 1 else "")
        concept = concepts.setdefault(subject, _Concept(iri=subject))
        for po in _split_top(pred_obj, ";"):
            po_parts = po.split(None, 1)
            if len(po_parts) != 2:
                raise SkosParseError(f"malformed predicate-object {po[:80]!r}")
            pred_token, obj_blob = po_parts
            pred = (
                RDF_TYPE if pred_token == "a" else expand(pred_token)
            )
            for obj in _split_top(obj_blob, ","):
                obj = obj.strip()
                lit = _LITERAL_RE.match(obj)
                if pred == RDF_TYPE:
                    concept.declared_types.append(expand(obj))
                    continue
                # A recognized SKOS property with a non-literal object (blank
                # node, bare IRI) is malformed input for this subset — fail
                # loudly rather than silently dropping the value.
                literal_preds = {
                    SKOS_NS + "prefLabel",
                    SKOS_NS + "altLabel",
                    SKOS_NS + "hiddenLabel",
                    SKOS_NS + "definition",
                    SKOS_NS + "scopeNote",
                    SKOS_NS + "note",
                }
                if pred in literal_preds and lit is None:
                    raise SkosParseError(
                        f"{pred.rsplit('#', 1)[-1]} on {subject} expects a "
                        f"literal, got {obj[:60]!r}"
                    )
                if pred == SKOS_NS + "prefLabel" and lit is not None:
                    concept.pref_label = _unescape(lit.group("text"))
                    concept.language = lit.group("lang") or "en"
                elif pred == SKOS_NS + "altLabel" and lit is not None:
                    concept.alt_labels.append(
                        (_unescape(lit.group("text")),
                         lit.group("lang") or "en")
                    )
                elif pred == SKOS_NS + "hiddenLabel" and lit is not None:
                    concept.hidden_labels.append(
                        (_unescape(lit.group("text")),
                         lit.group("lang") or "en")
                    )
                elif (
                    pred
                    in (
                        SKOS_NS + "definition",
                        SKOS_NS + "scopeNote",
                        SKOS_NS + "note",
                    )
                    and lit is not None
                ):
                    if not concept.definition:
                        concept.definition = _unescape(lit.group("text"))
                elif pred == SKOS_NS + "broader":
                    concept.broader.append(expand(obj))
                elif pred == SKOS_NS + "narrower":
                    continue  # inverse of broader; the child asserts its own
                else:
                    local = pred.rsplit("#", 1)[-1].rsplit("/", 1)[-1]
                    if local in _MATCH_PREDICATES:
                        concept.matches.append(
                            (_MATCH_PREDICATES[local], expand(obj))
                        )
                    # Unknown predicates are ignored, not fatal — a SKOS file
                    # carries far more than our schema can hold.
    # Only subjects typed skos:Concept — or untyped but carrying at least
    # one SKOS property — become entity types. A subject explicitly typed
    # as something else (ConceptScheme, Collection) is metadata about the
    # vocabulary, and an untyped subject with no SKOS properties is just a
    # resource the file mentions, not a concept in it.
    def _is_concept(c: _Concept) -> bool:
        if c.declared_types:
            return SKOS_NS + "Concept" in c.declared_types
        return bool(
            c.pref_label
            or c.definition
            or c.broader
            or c.alt_labels
            or c.hidden_labels
            or c.matches
        )

    return {iri: c for iri, c in concepts.items() if _is_concept(c)}


def _local_name(iri: str) -> str:
    tail = iri.rsplit("#", 1)[-1].rsplit("/", 1)[-1]
    return tail or iri


def skos_to_schema(
    concepts: dict[str, _Concept], *, label: str
) -> dict[str, Any]:
    """Map parsed concepts onto the install_schema document shape."""
    entity_types: list[dict[str, Any]] = []
    used_names: set[str] = set()
    name_of: dict[str, str] = {}
    for iri, c in concepts.items():
        name = c.pref_label or _local_name(iri)
        if name in used_names:
            name = f"{name} ({_local_name(iri)})"
        used_names.add(name)
        name_of[iri] = name
    for iri, c in concepts.items():
        parent = None
        for broader_iri in c.broader:
            if broader_iri in name_of:
                parent = name_of[broader_iri]
                break
        entity_types.append(
            {
                "name": name_of[iri],
                "description": c.definition,
                "attributes": {},
                **({"parent": parent} if parent else {}),
                "_iri": iri,
                "_language": c.language,
                "_alt_labels": c.alt_labels,
                "_hidden_labels": c.hidden_labels,
                "_matches": c.matches,
            }
        )
    return {
        "label": label,
        "description": f"Imported SKOS vocabulary ({len(entity_types)} concepts)",
        "entity_types": entity_types,
        "relation_types": [
            {
                "name": "related_to",
                "description": "Source and target are associated.",
                "domain_type": "*",
                "range_type": "*",
                "directed": False,
            }
        ],
    }


def import_skos(
    store: KGStore, text: str, *, label: str
) -> dict[str, Any]:
    """Parse SKOS Turtle and install it as the active schema_version.

    Returns {schema_version_id, concepts, aliases, xrefs, warnings}.
    Aliases and xrefs attach to the term rows install_schema creates —
    looked up by the legacy (kind, id) link rather than by label, so two
    concepts sharing a prefLabel still get the right rows.
    """
    concepts = parse_skos_turtle(text)
    if not concepts:
        raise KGStoreError("no skos:Concept subjects found in the input")
    doc = skos_to_schema(concepts, label=label)
    private = {
        e["name"]: e for e in doc["entity_types"]
    }
    public_entity_types = [
        {k: v for k, v in e.items() if not k.startswith("_")}
        for e in doc["entity_types"]
    ]
    sv_id = store.install_schema(
        label=doc["label"],
        description=doc["description"],
        entity_types=public_entity_types,
        relation_types=doc["relation_types"],
        term_provenance=f"skos-import:{label}",
    )
    # term rows: legacy_kind='entity_type', legacy_id = entity_type.id
    term_rows = store.conn.execute(
        "SELECT t.id AS term_id, e.name AS name FROM ontology_term t "
        "JOIN entity_type e ON e.id = t.legacy_id "
        "WHERE t.legacy_kind = 'entity_type' AND t.schema_version_id = ?",
        (sv_id,),
    ).fetchall()
    term_by_name = {r["name"]: r["term_id"] for r in term_rows}
    aliases = 0
    xrefs = 0
    warnings: list[str] = []
    for name, spec in private.items():
        term_id = term_by_name.get(name)
        if term_id is None:
            warnings.append(f"no term row for {name!r}; aliases/xrefs skipped")
            continue
        for label_text, lang in spec["_alt_labels"]:
            store.add_term_alias(
                term_id=term_id, label=label_text, language=lang,
                reviewer="skos-import", provenance=f"skos-import:{label}",
                alias_kind="alternative",
            )
            aliases += 1
        for label_text, lang in spec["_hidden_labels"]:
            store.add_term_alias(
                term_id=term_id, label=label_text, language=lang,
                reviewer="skos-import", provenance=f"skos-import:{label}",
                alias_kind="hidden",
            )
            aliases += 1
        for predicate, target_iri in spec["_matches"]:
            store.add_term_xref(
                term_id=term_id,
                authority=_local_name(target_iri).split(":")[0] or "skos",
                external_id=target_iri,
                mapping_predicate=predicate,
                source_uri=target_iri,
                source_version=label,
                retrieved_at=time.time(),
                confidence=1.0,
                reviewer="skos-import",
                license_gate="identifier-only",
            )
            xrefs += 1
    return {
        "schema_version_id": sv_id,
        "concepts": len(concepts),
        "aliases": aliases,
        "xrefs": xrefs,
        "warnings": warnings,
    }


__all__ = [
    "SkosParseError",
    "parse_skos_turtle",
    "skos_to_schema",
    "import_skos",
]
