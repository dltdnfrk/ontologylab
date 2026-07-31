"""Bundled ontologies, and the reason there is more than one.

`ontology_schema.py` holds the default — a neutral vocabulary for software
documentation (`Concept`, `Component`, `Technique` / `related_to`,
`part_of`, `uses`). It is a reasonable thing to start from and a poor thing
to stay on, because the ontology is what the extractor is told to find.
Ask for `Concept` and `related_to` on a p53 abstract and that is what comes
back: measured on one, five relations, every one of them `related_to`, plus
24 proposals the schema had no shape to hold and which were rejected.

The store was built for this — `nodes`, `edges` and both type tables carry
`schema_version_id` — but nothing could install one, so every corpus ran on
the software vocabulary. These are the presets that make the intended path
usable without hand-writing JSON.

A preset is a starting point, not a standard. The honest expectation is
that anyone working a real corpus edits one: an ontology that fits a
literature is a research artifact, and this file cannot know what someone
is studying.
"""

from __future__ import annotations

from typing import Any

from ontologylab import ontology_schema as _default


def _schema(
    label: str,
    description: str,
    entities: dict[str, tuple[str, dict]],
    relations: dict[str, tuple[str, str, str, bool]],
) -> dict[str, Any]:
    return {
        "label": label,
        "description": description,
        "entity_types": [
            {"name": name, "description": desc, "attributes": attrs}
            for name, (desc, attrs) in entities.items()
        ],
        "relation_types": [
            {
                "name": name,
                "description": desc,
                "domain_type": domain,
                "range_type": range_,
                "directed": directed,
            }
            for name, (desc, domain, range_, directed) in relations.items()
        ],
    }


# The relation types carry most of the weight. `related_to` is what a model
# reaches for when nothing more specific is offered, and a graph of
# "X is related to Y" answers no question anyone had. Each of these names a
# direction and a claim that can be checked against the sentence it came
# from — which is the whole point of the review queue.
_BIOMEDICAL_ENTITIES: dict[str, tuple[str, dict]] = {
    "Gene": ("A gene or its locus (TP53, BRCA1).", {}),
    "Protein": ("A protein, isoform or complex (p53, PARP1).", {}),
    "Variant": ("A specific mutation, allele or isoform (R248W).", {}),
    "Disease": ("A disease or clinical condition (breast cancer).", {}),
    "Drug": ("A drug, inhibitor or therapeutic compound (olaparib).", {}),
    "Pathway": (
        "A biological pathway or process (apoptosis, homologous "
        "recombination).",
        {},
    ),
    "CellLine": ("A cell line, tissue or model system (MCF-7).", {}),
    "Assay": (
        "An experimental method or measurement (ChIP-seq, steered molecular "
        "dynamics).",
        {},
    ),
}

_BIOMEDICAL_RELATIONS: dict[str, tuple[str, str, str, bool]] = {
    "encodes": ("Gene encodes the protein.", "Gene", "Protein", True),
    "has_variant": (
        "Gene or protein carries this variant.", "*", "Variant", True,
    ),
    "causes": ("Source causes or drives the condition.", "*", "Disease", True),
    "inhibits": ("Source inhibits, suppresses or impairs target.", "*", "*", True),
    "activates": ("Source activates or upregulates target.", "*", "*", True),
    "binds": ("Physical binding interaction.", "*", "*", False),
    "participates_in": (
        "Entity takes part in the pathway.", "*", "Pathway", True,
    ),
    "treats": ("Drug treats the disease.", "Drug", "Disease", True),
    "measured_by": ("Entity is measured by the assay.", "*", "Assay", True),
    "expressed_in": (
        "Gene or protein is expressed in the model.", "*", "CellLine", True,
    ),
    # Kept deliberately, and last. Real papers report associations that are
    # not causal — removing the honest word for that would push the model
    # into claiming `causes`, which is worse than a vague relation: it is a
    # confident wrong one.
    "associated_with": (
        "Statistically or clinically associated, without a claimed "
        "mechanism.",
        "*", "*", False,
    ),
}

PRESETS: dict[str, dict[str, Any]] = {
    "software-docs": _schema(
        _default.DEFAULT_SCHEMA_LABEL,
        _default.DEFAULT_SCHEMA_DESCRIPTION,
        _default.DEFAULT_ENTITY_TYPES,
        _default.DEFAULT_RELATION_TYPES,
    ),
    "biomedical": _schema(
        "biomed-v1",
        "Genes, proteins, variants, diseases and the claims papers make "
        "about them.",
        _BIOMEDICAL_ENTITIES,
        _BIOMEDICAL_RELATIONS,
    ),
}


def preset(name: str) -> dict[str, Any]:
    """One bundled ontology, ready for `KGStore.install_schema`."""
    try:
        return PRESETS[name]
    except KeyError:
        raise KeyError(
            f"unknown preset {name!r}; available: {', '.join(sorted(PRESETS))}"
        ) from None
