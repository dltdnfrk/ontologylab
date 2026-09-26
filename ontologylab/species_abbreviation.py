"""Resolve organism abbreviations using only the supplied document text."""

from __future__ import annotations

import re
from typing import Final

from ontologylab.models import ProposedEntity

_ORGANISM_TYPES: Final = frozenset(
    {"Crop", "Pathogen", "Pest", "Weed", "NonTargetOrganism"}
)
_ABBREVIATION: Final = re.compile(r"^([A-Z])\.\s?([a-z][a-z-]+)(?![\w-])")


def resolve_species_abbreviation(
    proposal: ProposedEntity, raw_text: str
) -> ProposedEntity:
    """Mutate a proposal only on a unique, exact document-local full binomial.

    Preserve everything after the epithet, including population qualifiers
    and punctuation. No registry, aliases, other documents, or model output
    supply the expansion; repeated mentions of one full form are not ambiguous.
    """
    if proposal.entity_type not in _ORGANISM_TYPES:
        return proposal
    abbreviated = _ABBREVIATION.match(proposal.name)
    if abbreviated is None:
        return proposal

    initial, epithet = abbreviated.groups()
    full_form = re.compile(
        rf"(?<![\w-])({initial}[a-z]+)\s+{re.escape(epithet)}(?![\w-])"
    )
    genera = {match.group(1) for match in full_form.finditer(raw_text)}
    if len(genera) != 1:
        proposal.properties["abbreviation_unresolved"] = (
            "absent" if not genera else "ambiguous"
        )
        return proposal

    surface = proposal.name
    proposal.name = f"{next(iter(genera))} {epithet}{surface[abbreviated.end():]}"
    if surface not in proposal.aliases:
        proposal.aliases.append(surface)
    proposal.properties.pop("abbreviation_unresolved", None)
    return proposal
