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
