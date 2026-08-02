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

# Crop protection literature names four things at once and a paper usually
# spans several: what controls what, by which mechanism and how resistance
# breaks it, what residue and toxicity that leaves, and what a trial actually
# measured. Splitting those into four ontologies would force a document to be
# extracted four times, so they are one vocabulary here.
#
# Registry identifiers are attributes, not decoration. This domain has
# authoritative keys the software and biomedical domains lack — EPPO codes for
# organisms, CAS numbers for actives, FRAC/IRAC/HRAC group numbers for modes
# of action. Two mentions of "Boscalid" and "boscalid" resolve by name, but
# "Botrytis cinerea" and "grey mould" only resolve through the code, and
# string similarity will never learn that.
_AGROCHEM_ENTITIES: dict[str, tuple[str, dict]] = {
    # -- what is protected, what attacks it, what is applied ---------------
    "Crop": (
        "A cultivated plant or commodity (grapevine, tomato).",
        {
            "scientific_name": {"type": "string", "required": False},
            "eppo_code": {"type": "string", "required": False},
        },
    ),
    "Pathogen": (
        "A plant-pathogenic organism (Botrytis cinerea, Phytophthora "
        "infestans).",
        {
            "scientific_name": {"type": "string", "required": False},
            "eppo_code": {"type": "string", "required": False},
            "group": {"type": "string", "required": False},
        },
    ),
    "Pest": (
        "An animal pest: insect, mite, nematode (Tetranychus urticae).",
        {
            "scientific_name": {"type": "string", "required": False},
            "eppo_code": {"type": "string", "required": False},
        },
    ),
    "Weed": (
        "A weed species (Amaranthus palmeri).",
        {
            "scientific_name": {"type": "string", "required": False},
            "eppo_code": {"type": "string", "required": False},
        },
    ),
    "Disease": (
        "A named plant disease, distinct from the organism causing it "
        "(grey mould, late blight).",
        {},
    ),
    "ActiveIngredient": (
        "An agrochemical active substance (boscalid, azoxystrobin).",
        {
            "cas_number": {"type": "string", "required": False},
            "chemical_group": {"type": "string", "required": False},
        },
    ),
    "Product": (
        "A registered commercial product containing one or more actives.",
        {"registration_number": {"type": "string", "required": False}},
    ),
    "Region": (
        "A country or regulatory territory the claim applies to.",
        {"iso_code": {"type": "string", "required": False}},
    ),
    # -- how it works, and how that stops working --------------------------
    "MoAGroup": (
        "A mode-of-action classification group (FRAC 7, IRAC 4A, HRAC 2).",
        {
            "scheme": {"type": "string", "required": False},
            "code": {"type": "string", "required": False},
        },
    ),
    "TargetSite": (
        "The molecular site an active acts on (succinate dehydrogenase, "
        "acetolactate synthase).",
        {},
    ),
    "Protein": (
        "A protein or enzyme subunit (SdhB, CYP51).",
        {"uniprot_id": {"type": "string", "required": False}},
    ),
    "Gene": ("A gene or locus (sdhB, cyp51A).", {}),
    "ResistanceMutation": (
        "A specific substitution linked to resistance (SdhB H272R).",
        {},
    ),
    "ResistanceMechanism": (
        "A non-mutational resistance route: enhanced metabolism, efflux, "
        "reduced uptake.",
        {"mechanism_class": {"type": "string", "required": False}},
    ),
    "Pathway": (
        "A biochemical pathway or process (ergosterol biosynthesis).",
        {},
    ),
    # -- what it leaves behind ---------------------------------------------
    "ResidueLimit": (
        "A maximum residue level for one active on one crop in one "
        "territory.",
        {
            "value_mg_kg": {"type": "string", "required": False},
            "crop": {"type": "string", "required": False},
            "region": {"type": "string", "required": False},
        },
    ),
    "PreHarvestInterval": (
        "The required interval between last application and harvest.",
        {
            "days": {"type": "string", "required": False},
            "crop": {"type": "string", "required": False},
            "region": {"type": "string", "required": False},
        },
    ),
    "ToxicityEndpoint": (
        "A reported toxicological or ecotoxicological value (LD50, NOAEL, "
        "EC50).",
        {
            "endpoint": {"type": "string", "required": False},
            "species": {"type": "string", "required": False},
            "value": {"type": "string", "required": False},
            "unit": {"type": "string", "required": False},
        },
    ),
    "NonTargetOrganism": (
        "An organism the treatment is not aimed at (honeybee, earthworm, "
        "Daphnia).",
        {"group": {"type": "string", "required": False}},
    ),
    "RegulatoryAction": (
        "An approval, restriction or withdrawal by an authority.",
        {
            "action": {"type": "string", "required": False},
            "region": {"type": "string", "required": False},
            "date": {"type": "string", "required": False},
        },
    ),
    # -- how it was applied and what the trial measured --------------------
    "Formulation": (
        "A formulation type (WP, SC, EC, WG).",
        {"code": {"type": "string", "required": False}},
    ),
    "ApplicationMethod": (
        "How the treatment is delivered (foliar spray, seed treatment, "
        "soil drench).",
        {},
    ),
    "DoseRate": (
        "An application rate (250 g a.i./ha).",
        {
            "value": {"type": "string", "required": False},
            "unit": {"type": "string", "required": False},
        },
    ),
    "GrowthStage": (
        "A crop growth stage, BBCH where given (BBCH 65).",
        {"bbch_code": {"type": "string", "required": False}},
    ),
    "Trial": (
        "One experiment: field, greenhouse, or in vitro assay.",
        {
            "trial_type": {"type": "string", "required": False},
            "year": {"type": "string", "required": False},
            "location": {"type": "string", "required": False},
        },
    ),
    "EfficacyOutcome": (
        "A measured result (85% disease control, EC50 0.03 mg/L).",
        {
            "metric": {"type": "string", "required": False},
            "value": {"type": "string", "required": False},
            "unit": {"type": "string", "required": False},
        },
    ),
}

_AGROCHEM_RELATIONS: dict[str, tuple[str, str, str, bool]] = {
    # -- control -----------------------------------------------------------
    # Endpoints stay `*` on purpose: the source may be an active or a
    # product, the target a pathogen, pest or weed, and a schema cannot
    # express a union. Forcing one type would make the model guess whether a
    # nematode is a pest or a pathogen and reject it for guessing wrong.
    "controls": (
        "An active or product suppresses the target pathogen, pest or weed.",
        "*", "*", True,
    ),
    "infects": ("Pathogen infects the crop.", "Pathogen", "Crop", True),
    "damages": ("Pest or weed damages the crop.", "*", "Crop", True),
    "causes": ("Pathogen causes the named disease.", "Pathogen", "Disease", True),
    "contains": (
        "Product contains the active ingredient.", "Product", "ActiveIngredient",
        True,
    ),
    "registered_for": (
        "Product is registered or labelled for use on the crop.",
        "Product", "Crop", True,
    ),
    "occurs_in": ("Organism or claim is reported in the region.", "*", "Region", True),
    # -- mode of action and resistance -------------------------------------
    "has_mode_of_action": (
        "Active belongs to the mode-of-action group.",
        "ActiveIngredient", "MoAGroup", True,
    ),
    "targets": ("Active acts on the target site.", "*", "TargetSite", True),
    "encodes": ("Gene encodes the protein.", "Gene", "Protein", True),
    "has_variant": (
        "Gene or protein carries this resistance mutation.",
        "*", "ResistanceMutation", True,
    ),
    "confers_resistance_to": (
        "Mutation or mechanism confers resistance to the active or group.",
        "*", "*", True,
    ),
    # The field's central time-varying claim: an active that worked in 2015
    # can be reported failing in 2023. The claim is recorded, and `valid_from`
    # / `invalidated_ts` on the edge carry when it held — the assertion is
    # never silently overwritten by a newer paper.
    "resistant_to": (
        "A population of this pathogen or pest is reported resistant to the "
        "active or group.",
        "*", "*", True,
    ),
    "cross_resistant_with": (
        "Resistance to one group implies resistance to the other.",
        "MoAGroup", "MoAGroup", False,
    ),
    "inhibits": ("Source inhibits or suppresses the target.", "*", "*", True),
    "participates_in": ("Entity takes part in the pathway.", "*", "Pathway", True),
    # -- residue and safety -------------------------------------------------
    "has_residue_limit": (
        "Active or product has this residue limit.", "*", "ResidueLimit", True,
    ),
    "has_preharvest_interval": (
        "Product has this pre-harvest interval.", "*", "PreHarvestInterval", True,
    ),
    "has_toxicity": (
        "Active or product has this measured endpoint.", "*", "ToxicityEndpoint",
        True,
    ),
    "toxic_to": (
        "Active or product harms the non-target organism.",
        "*", "NonTargetOrganism", True,
    ),
    "regulated_by": (
        "Active or product is subject to this regulatory action.",
        "*", "RegulatoryAction", True,
    ),
    # -- formulation and trial ---------------------------------------------
    "formulated_as": (
        "Product is supplied in this formulation.", "Product", "Formulation", True,
    ),
    "applied_by": ("Treatment is delivered by this method.", "*", "ApplicationMethod", True),
    "applied_at_rate": ("Treatment is applied at this rate.", "*", "DoseRate", True),
    "applied_at_stage": ("Treatment is applied at this growth stage.", "*", "GrowthStage", True),
    "evaluated_in": ("Treatment or organism was evaluated in this trial.", "*", "Trial", True),
    "reports_efficacy": ("Trial reports this outcome.", "Trial", "EfficacyOutcome", True),
    "phytotoxic_to": ("Treatment injures the crop it was applied to.", "*", "Crop", True),
    "synergizes_with": (
        "Two treatments are reported to act more than additively.", "*", "*", False,
    ),
    # Last, and for the same reason biomed-v1 keeps it: papers report
    # associations without a mechanism, and denying the honest word for that
    # pushes the model into a confident wrong `causes`.
    "associated_with": (
        "Associated without a claimed mechanism.", "*", "*", False,
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
    "agrochem": _schema(
        "agrochem-v1",
        "Crop protection: what controls which pathogen, pest or weed, by "
        "which mode of action, how resistance breaks it, what residue and "
        "toxicity it leaves, and what a trial measured.",
        _AGROCHEM_ENTITIES,
        _AGROCHEM_RELATIONS,
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
