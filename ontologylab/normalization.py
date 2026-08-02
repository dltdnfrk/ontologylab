"""Authoritative registry normalization for extraction proposals."""

from __future__ import annotations

from ontologylab.models import ProposedEntity
from ontologylab.registry import CASRegistryCache, MoARegistryCache, RegistryCache

ORGANISM_ENTITY_TYPES = frozenset({"Crop", "Pathogen", "Pest", "Weed"})
ACTIVE_ENTITY_TYPE = "ActiveIngredient"
_MISSING = object()


def _normalize_organism(
    proposal: ProposedEntity, cache: RegistryCache
) -> ProposedEntity:
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


def _normalize_active(
    proposal: ProposedEntity,
    cache: CASRegistryCache,
    moa_cache: MoARegistryCache | None,
) -> ProposedEntity:
    properties = proposal.properties
    model_cas = properties.pop("cas_number", _MISSING)
    # MoA is derived from canonical CAS identity, never from generated fields.
    properties.pop("moa_scheme", None)
    properties.pop("moa_code", None)

    for surface in (proposal.name, *proposal.aliases):
        cas_number, status = cache.resolve_with_status(surface)
        if status == "cache_absent":
            properties.pop("normalization", None)
            properties.pop("cas_matched_surface", None)
            properties.pop("cas_number_dropped", None)
            return proposal
        if status != "resolved":
            continue

        properties["cas_number"] = cas_number
        properties["cas_matched_surface"] = surface
        properties.pop("normalization", None)
        if model_cas is not _MISSING and model_cas != cas_number:
            properties["cas_number_dropped"] = model_cas
        else:
            properties.pop("cas_number_dropped", None)
        if moa_cache is not None:
            moa = moa_cache.resolve(cas_number)
            if moa is not None:
                properties["moa_scheme"], properties["moa_code"] = moa
        return proposal

    if model_cas is not _MISSING:
        properties["cas_number_dropped"] = model_cas
    else:
        properties.pop("cas_number_dropped", None)
    properties.pop("cas_matched_surface", None)
    properties["normalization"] = "no_cas_match"
    return proposal


def normalize_proposal(
    proposal: ProposedEntity,
    cache: RegistryCache | CASRegistryCache,
    moa_cache: MoARegistryCache | None = None,
) -> ProposedEntity:
    """Resolve one supported proposal, mutating it in place.

    Name is tried before aliases and the first resolved surface wins. The
    cache type selects its domain, preserving the Wave 2 two-argument API;
    unrelated entity/cache combinations pass through untouched.
    """
    if proposal.entity_type in ORGANISM_ENTITY_TYPES and isinstance(
        cache, RegistryCache
    ):
        return _normalize_organism(proposal, cache)
    if proposal.entity_type == ACTIVE_ENTITY_TYPE and isinstance(
        cache, CASRegistryCache
    ):
        return _normalize_active(proposal, cache, moa_cache)
    return proposal


__all__ = [
    "ACTIVE_ENTITY_TYPE",
    "ORGANISM_ENTITY_TYPES",
    "normalize_proposal",
]
