"""Authoritative organism normalization for extraction proposals."""

from __future__ import annotations

from ontologylab.models import ProposedEntity
from ontologylab.registry import RegistryCache

ORGANISM_ENTITY_TYPES = frozenset({"Crop", "Pathogen", "Pest", "Weed"})
_MISSING = object()


def normalize_proposal(
    proposal: ProposedEntity, cache: RegistryCache
) -> ProposedEntity:
    """Resolve one organism proposal against EPPO, mutating it in place.

    Name is tried before aliases and the first resolved surface wins. Other
    entity types are returned without touching any field.
    """
    if proposal.entity_type not in ORGANISM_ENTITY_TYPES:
        return proposal

    properties = proposal.properties
    model_code = properties.pop("eppo_code", _MISSING)

    for surface in (proposal.name, *proposal.aliases):
        code, status = cache.resolve_with_status(surface)
        if status == "cache_absent":
            # An absent optional cache switches the feature off. Per-entity
            # flags would turn one run configuration issue into noisy review.
            properties.pop("normalization", None)
            properties.pop("eppo_matched_surface", None)
            properties.pop("eppo_code_dropped", None)
            return proposal
        if status != "resolved":
            continue

        # The registry outranks model output: generated identifiers are not
        # evidence, even when they happen to look like valid EPPO codes.
        properties["eppo_code"] = code
        properties["eppo_matched_surface"] = surface
        properties.pop("normalization", None)
        if model_code is not _MISSING and model_code != code:
            properties["eppo_code_dropped"] = model_code
        else:
            properties.pop("eppo_code_dropped", None)
        return proposal

    if model_code is not _MISSING:
        properties["eppo_code_dropped"] = model_code
    else:
        properties.pop("eppo_code_dropped", None)
    properties.pop("eppo_matched_surface", None)
    properties["normalization"] = "no_eppo_match"
    return proposal


__all__ = ["ORGANISM_ENTITY_TYPES", "normalize_proposal"]
