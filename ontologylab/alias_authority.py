"""Registry alias authority classes (Wave 2.1 Step 4, 4C / D11).

The proposal name is span-grounded (``source_attested``); parser-minted
aliases are ``model_unattested``; registry caches and curators supply
``registry_supplied`` / ``human_asserted`` surfaces. Only authorized
surfaces may establish EPPO/CAS identity - a model_unattested alias alone
can never mint registry identity, because generated identifiers are not
evidence even when they happen to match.

Compatibility rule: proposals without an ``alias_authority`` classification
map at all keep the pre-4C behavior (every surface authorized), so the
SHA-pinned legacy evidence tests stay green; the extraction boundary stamps
classification, so enforcement is live on the real pipeline.
"""

from __future__ import annotations

from dataclasses import dataclass

AUTHORIZED = frozenset({"registry_supplied", "human_asserted"})


@dataclass(frozen=True, slots=True)
class SurfacePlan:
    """Which surfaces may be offered to the registry for resolution."""

    authorized: tuple[str, ...]
    unattested: tuple[str, ...]


def surface_plan(
    *,
    name: str,
    aliases: list[str],
    alias_authority: dict[str, str] | None,
) -> SurfacePlan:
    if alias_authority is None:
        return SurfacePlan(authorized=tuple([name, *aliases]), unattested=())
    authorized: list[str] = [name]
    unattested: list[str] = []
    for alias in aliases:
        if alias_authority.get(alias, "model_unattested") in AUTHORIZED:
            authorized.append(alias)
        else:
            unattested.append(alias)
    return SurfacePlan(authorized=tuple(authorized), unattested=tuple(unattested))


def authorized_surfaces(proposal) -> SurfacePlan:
    """The plan for one extraction proposal, from its properties map."""
    return surface_plan(
        name=proposal.name,
        aliases=list(proposal.aliases),
        alias_authority=proposal.properties.get("alias_authority"),
    )
