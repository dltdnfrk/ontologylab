"""Conservative recovery of explicitly spelled organism variants."""

from __future__ import annotations

import re

from ontologylab.models import ProposedEntity, ProposedRelation
from ontologylab.statement_qualifiers import normalize_statement_value

_VARIANT = re.compile(
    r"^((?:[A-Z][a-z]+|[A-Z]\.)\s+[a-z][a-z-]+)\s+"
    r"((?:isolate|strain)\s+[A-Za-z0-9][\w.-]*(?:\s+[0-9]+)?)$"
)
_ORGANISMS = frozenset({"Crop", "Pathogen", "Pest", "Weed", "NonTargetOrganism"})


def split_grounded_variants(
    entities: list[ProposedEntity], relations: list[ProposedRelation], text: str,
) -> None:
    """Split only an explicit isolate/strain suffix cited by every linked edge.

    No inference of species, population, stage, aspect, dose or study context.
    Conflicting model qualifiers leave the proposal intact for review. Qualified
    names are never recorded as aliases of bare species.
    """
    for entity in entities:
        if entity.entity_type not in _ORGANISMS:
            continue
        match = _VARIANT.fullmatch(entity.name)
        if match is None:
            continue
        core, variant = match.groups()
        links = [
            (relation, f"{side}_form_or_variant_qualifier")
            for relation in relations
            for side, endpoint in (("subject", relation.src_entity_id),
                                   ("object", relation.dst_entity_id))
            if endpoint == entity.id
        ]
        if not links:
            continue
        if any(
            relation.source_span is None
            or entity.name.casefold() not in text[
                relation.source_span.start:relation.source_span.end
            ].casefold()
            or (slot in relation.qualifiers and normalize_statement_value(
                slot, relation.qualifiers[slot]
            ) != normalize_statement_value(slot, variant))
            for relation, slot in links
        ):
            continue
        entity.name = core
        entity.aliases = [alias for alias in entity.aliases if not _VARIANT.fullmatch(alias)]
        for relation, slot in links:
            relation.qualifiers[slot] = variant
