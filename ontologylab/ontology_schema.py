"""Default ontology definition for ontologylab.

Seeds the ``schema_version`` / ``entity_type`` / ``relation_type`` tables at
first run (types are data, not code — see ARCHITECTURE.md §5.1). The shipped
default is a small, neutral software-documentation ontology; users edit the
tables (or ship packs with their own exported schema) to change it.

``domain_type`` / ``range_type`` of "*" means "any entity type" — the
extraction validator only enforces endpoint types when a concrete type name
is declared.
"""

from __future__ import annotations

LOCAL_TERM_IRI_BASE = "https://ontologylab.local/term"
DEFAULT_TERM_LANGUAGE = "en"
BUNDLED_TERM_REVIEWER = "ontologylab-bundled-schema"
LEGACY_TERM_REVIEWER = "ontologylab-schema-migration"
LEGACY_TERM_PROVENANCE = "legacy-schema-backfill"

TERM_LIFECYCLES = ("active", "deprecated", "replaced")
TERM_ALIAS_KINDS = ("alternative", "hidden", "former-preferred")
XREF_MAPPING_PREDICATES = (
    "exact",
    "close",
    "broader",
    "narrower",
    "related",
    "advisory",
)
XREF_LICENSE_GATES = ("allow", "identifier-only", "deny-text")


def local_term_iri(term_id: str) -> str:
    """Derive the local IRI from the immutable UUID and nothing else."""
    return f"{LOCAL_TERM_IRI_BASE}/{term_id}"


DEFAULT_SCHEMA_LABEL = "software-docs-v1"
DEFAULT_SCHEMA_DESCRIPTION = (
    "Neutral default ontology for software / technical documentation."
)

# name -> (description, attributes_json-able dict)
DEFAULT_ENTITY_TYPES: dict[str, tuple[str, dict]] = {
    "Concept": (
        "An abstract idea, algorithm, pattern, or principle.",
        {},
    ),
    "Component": (
        "A concrete software artifact: module, service, library, tool, API.",
        {
            "language": {"type": "string", "required": False},
            "version": {"type": "string", "required": False},
        },
    ),
    "Technique": (
        "A method, procedure, or practice applied to build or operate systems.",
        {},
    ),
}

# name -> (description, domain_type, range_type, directed)
DEFAULT_RELATION_TYPES: dict[str, tuple[str, str, str, bool]] = {
    "uses": ("Source makes use of target.", "*", "*", True),
    "part_of": ("Source is a constituent of target.", "*", "*", True),
    "related_to": ("Source and target are associated.", "*", "*", False),
}

# Relation qualifiers are declared independently from entity properties. The
# default ontology permits none, but every relation still has an explicit
# qualifier contract so schema exports and prompts have one stable shape.
DEFAULT_RELATION_QUALIFIERS: dict[str, dict[str, dict]] = {
    name: {} for name in DEFAULT_RELATION_TYPES
}
