"""Advisory registry lookups for review-queue entities.

The runtime path performs curated exact-name lookups through ``resources``
(UniProt for genes/proteins and ChEMBL for drugs) and records the answer as
review evidence. The LLM and this module are both advisory: nothing here
writes status, so the review queue and human-only approval stay untouched.

Lookups are keyless and best-effort. A transport failure or exact-match miss
becomes a row with a stable error key so the reviewer can distinguish an
offline check from ``not_found``. Legacy parser helpers remain for direct
callers but use the same guarded HTTP seam; ``lookup_entity`` never uses
their ranked free-text results.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
from dataclasses import dataclass
from typing import Any

from ontologylab.connectors.paper_api import ResponseTooLarge, _http_get_text
from ontologylab.connectors.resources import (
    CHEMBL_RESOURCE,
    UNIPROT_RESOURCE,
    ResourceError,
    ResourceMatch,
    lookup,
)
from ontologylab.paths import NetworkBlocked

# Which entity kinds get looked up in which registry. Kinds without a
# registry (Disease, Pathway, CellLine, Assay) are deliberately skipped —
# inventing a lookup for them would manufacture false confidence.
REGISTRY_FOR_TYPE: dict[str, str] = {
    "Gene": UNIPROT_RESOURCE,
    "Protein": UNIPROT_RESOURCE,
    "Drug": CHEMBL_RESOURCE,
}

_UNIPROT_SEARCH = "https://rest.uniprot.org/uniprotkb/search"
_PUBCHEM_PROPERTY = "https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/name"
_EUTILS = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"


class LegacyLookupError(Exception):
    """A compatibility lookup failed before producing a registry row."""


@dataclass(frozen=True, slots=True)
class Enrichment:
    """One registry answer (or one failed attempt)."""

    registry: str
    identifier: str
    label: str
    description: str = ""
    error: str = ""


def _get(url: str) -> bytes:
    """Compatibility seam for the legacy parsers, behind the shared GET.

    Failure keys are stable ('timeout', 'refused', 'http_429', 'offline',
    'shape') so the caller can store a short reason instead of an error
    body that might carry anything.
    """
    try:
        return _http_get_text(url).encode()
    except urllib.error.HTTPError as exc:
        raise LegacyLookupError(f"http_{exc.code}") from exc
    except urllib.error.URLError:
        raise LegacyLookupError("offline") from None
    except TimeoutError:
        raise LegacyLookupError("timeout") from None
    except NetworkBlocked:
        raise LegacyLookupError("offline") from None


def _get_json(url: str) -> dict[str, Any]:
    body = _get(url)
    try:
        return json.loads(body)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise LegacyLookupError("shape") from exc


def _text(value: Any) -> str:
    """One text field, unwrapped and coerced.

    UniProt wraps its i18n strings as ``{"value": ...}``; reading the
    wrapper as the label crashed the store write (a dict bound to a TEXT
    column). Unwrapping here, and coercing anything else to str, makes a
    shape drift degrade to a wrong label, never a 500.
    """
    if isinstance(value, dict):
        value = value.get("value", "")
    if value is None:
        return ""
    return str(value)


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
    full_name = ((hit.get("proteinDescription") or {}).get("recommendedName") or {}).get("fullName")
    label = _text(full_name) or name
    gene = _text(((hit.get("genes") or [{}])[0].get("geneName") or {}).get("value"))
    organism = _text((hit.get("organism") or {}).get("scientificName"))
    return Enrichment(
        "uniprot",
        _text(hit.get("primaryAccession")),
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
    except LegacyLookupError as exc:
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


def _from_match(match: ResourceMatch) -> Enrichment:
    return Enrichment(
        registry=match.resource,
        identifier=match.external_id,
        label=match.matched_name,
        description=json.dumps(
            match.facts, ensure_ascii=False, sort_keys=True,
        ),
    )


def lookup_entity(name: str, type_name: str) -> list[Enrichment]:
    """Look up one proposal through the curated exact-match resource seam.

    The old runtime path called the free-text helpers above, accepted the
    top-ranked hit, and opened URLs directly. Review enrichment now shares
    the field-qualified resource contract used by graph enrichment.
    """
    registry = REGISTRY_FOR_TYPE.get(type_name)
    if registry is None:
        return []
    try:
        match = lookup(registry, name)
    except urllib.error.HTTPError as exc:
        return [Enrichment(registry, "", name, error=f"http_{exc.code}")]
    except urllib.error.URLError:
        return [Enrichment(registry, "", name, error="offline")]
    except TimeoutError:
        return [Enrichment(registry, "", name, error="timeout")]
    except NetworkBlocked:
        return [Enrichment(registry, "", name, error="offline")]
    except (ResourceError, ResponseTooLarge, UnicodeError):
        return [Enrichment(registry, "", name, error="shape")]
    if match is None:
        return [Enrichment(registry, "", name, error="not_found")]
    return [_from_match(match)]
