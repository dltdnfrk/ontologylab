"""Advisory registry lookups for review-queue entities (science-skills slice 2).

The LLM is never the authority for an external identifier, and neither is
this module: it looks the proposed entity's name up in public registries
(UniProt for genes/proteins, PubChem for drugs, ClinVar for variants) and
records what the registry says, so the human reviewing the proposal can
confirm the entity is real before approving. Nothing here writes status —
the review queue and its human-only approval stay untouched.

Lookups are keyless and best-effort: a transport failure becomes a row
with an error text (the reviewer must see that the check *could not run*,
not silently nothing), and a name the registry does not know becomes no
row at all — absence means "not found", which is itself information.
"""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any

# Which entity kinds get looked up in which registry. Kinds without a
# registry (Disease, Pathway, CellLine, Assay) are deliberately skipped —
# inventing a lookup for them would manufacture false confidence.
REGISTRY_FOR_TYPE: dict[str, str] = {
    "Gene": "uniprot",
    "Protein": "uniprot",
    "Drug": "pubchem",
    "Variant": "clinvar",
}

_UNIPROT_SEARCH = "https://rest.uniprot.org/uniprotkb/search"
_PUBCHEM_PROPERTY = "https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/name"
_EUTILS = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"

_TIMEOUT_S = 10
_MAX_BYTES = 2 * 1024 * 1024


@dataclass
class Enrichment:
    """One registry answer (or one failed attempt)."""

    registry: str
    identifier: str
    label: str
    description: str = ""
    error: str = ""


def _get(url: str) -> bytes:
    """One bounded GET; raises ValueError with a Korean-free failure key.

    Failure keys are stable ('timeout', 'refused', 'http_429', 'offline',
    'shape') so the caller can store a short reason instead of an error
    body that might carry anything.
    """
    request = urllib.request.Request(
        url, headers={"User-Agent": "ontologylab/1.0 (+https://github.com/dltdnfrk/ontologylab)"}
    )
    try:
        with urllib.request.urlopen(request, timeout=_TIMEOUT_S) as response:
            return response.read(_MAX_BYTES + 1)
    except urllib.error.HTTPError as exc:
        raise ValueError(f"http_{exc.code}") from exc
    except urllib.error.URLError:
        raise ValueError("offline") from None
    except TimeoutError:
        raise ValueError("timeout") from None


def _get_json(url: str) -> dict[str, Any]:
    try:
        body = _get(url)
    except ValueError as exc:
        raise ValueError(str(exc)) from exc
    try:
        return json.loads(body)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ValueError("shape") from exc


def lookup_uniprot(name: str) -> Enrichment:
    """Gene/protein name -> top UniProtKB hit (accession, name, function)."""
    url = (
        f"{_UNIPROT_SEARCH}?query={urllib.parse.quote_plus(name)}"
        "&format=json&size=1"
    )
    data = _get_json(url)
    results = data.get("results") or []
    if not results:
        return Enrichment("uniprot", "", name, error="not_found")
    hit = results[0]
    label = (
        (hit.get("proteinDescription") or {}).get("recommendedName") or {}
    ).get("fullName") or name
    gene = (hit.get("genes") or [{}])[0].get("geneName", {}).get("value", "")
    organism = ((hit.get("organism") or {}).get("scientificName")) or ""
    return Enrichment(
        "uniprot",
        hit.get("primaryAccession") or "",
        label,
        f"{gene} · {organism}".strip(" ·"),
    )


def lookup_pubchem(name: str) -> Enrichment:
    """Drug/compound name -> PubChem CID, title, formula."""
    url = (
        f"{_PUBCHEM_PROPERTY}/{urllib.parse.quote_plus(name)}"
        "/property/Title,MolecularFormula/JSON"
    )
    try:
        data = _get_json(url)
    except ValueError as exc:
        if str(exc) == "http_404":
            return Enrichment("pubchem", "", name, error="not_found")
        raise
    props = ((data.get("PropertyTable") or {}).get("Properties")) or []
    if not props:
        return Enrichment("pubchem", "", name, error="not_found")
    prop = props[0]
    formula = prop.get("MolecularFormula") or ""
    return Enrichment(
        "pubchem",
        str(prop.get("CID") or ""),
        prop.get("Title") or name,
        f"분자식 {formula}" if formula else "",
    )


def lookup_clinvar(name: str) -> Enrichment:
    """Variant name -> ClinVar record via E-utilities (esearch + esummary)."""
    esearch = (
        f"{_EUTILS}/esearch.fcgi?db=clinvar&retmode=json&retmax=1"
        f"&term={urllib.parse.quote_plus(name)}"
    )
    data = _get_json(esearch)
    ids = ((data.get("esearchresult") or {}).get("idlist")) or []
    if not ids:
        return Enrichment("clinvar", "", name, error="not_found")
    summary = _get_json(
        f"{_EUTILS}/esummary.fcgi?db=clinvar&retmode=json&id={ids[0]}"
    )
    record = ((summary.get("result") or {}).get(ids[0])) or {}
    genes = " ".join((record.get("gene_name") or [])[:2])
    return Enrichment(
        "clinvar",
        ids[0],
        record.get("title") or name,
        genes,
    )


_LOOKUPS = {
    "uniprot": lookup_uniprot,
    "pubchem": lookup_pubchem,
    "clinvar": lookup_clinvar,
}


def lookup_entity(name: str, type_name: str) -> list[Enrichment]:
    """The registries that apply to this entity kind, in a stable order.

    One registry per kind; the mapping is fixed so a name is never
    bounced between registries hoping one sticks. A failed network call
    still yields an Enrichment row carrying the failure key.
    """
    registry = REGISTRY_FOR_TYPE.get(type_name)
    if registry is None:
        return []
    try:
        return [_LOOKUPS[registry](name)]
    except ValueError as exc:
        return [Enrichment(registry, "", name, error=str(exc))]
