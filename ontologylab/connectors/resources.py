"""Curated data resources, looked up by exact name — never searched.

The paper connectors fetch documents; these fetch *records*. The difference
decides everything about how they are allowed to behave here.

A paper is prose, so a proposal drawn from it cites a span a person can
read and judge. A UniProt entry is a curated fact table: nothing in it is
hallucinated, and re-reading it tells a reviewer nothing they could
disagree with. The risk moves. It is no longer "did the model invent this
claim" but **"is this the right record"** — and that risk is severe,
because a wrong record is a page of true statements attached to the wrong
thing.

That is not hypothetical. The first probe written against UniProt asked it
for `BRCA1` and got back, as its top hit:

    Q6UWZ7 — BRCA1-A complex subunit Abraxas 1   (gene: ABRAXAS1)

A different protein, confidently ranked first, because its *name contains*
the query. Attaching that record's function text to a node called BRCA1
would have produced an annotation that is entirely true and entirely
wrong.

So there is no free-text search in this module. Every lookup is
field-qualified and exact:

    gene_exact:BRCA1 AND organism_id:9606 AND reviewed:true   ->  P38398

and a name that matches nothing returns nothing rather than the closest
thing. Deny-by-default, the same posture as the URL allowlist: the cost of
a miss is an annotation that does not appear, and the cost of a false hit
is a lie the reviewer has no way to catch.

An exact match is still only a *candidate*. Gene symbols collide across
organisms and are reused as protein-complex names, which is why the
organism filter is part of the query and why every match still goes to a
human before it becomes knowledge.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import quote_plus, urlparse
from urllib.error import HTTPError

from ontologylab.connectors.paper_api import _http_get_text

# One fixed endpoint per resource, exactly as the paper connectors do, so the
# host allowlist stays derivable rather than hand-maintained.
UNIPROT_API_URL = "https://rest.uniprot.org/uniprotkb/search"
MYGENE_API_URL = "https://mygene.info/v3/query"
ENSEMBL_API_URL = "https://rest.ensembl.org/lookup/symbol"
CHEMBL_API_URL = "https://www.ebi.ac.uk/chembl/api/data/molecule.json"

UNIPROT_RESOURCE = "uniprot"
MYGENE_RESOURCE = "mygene"
ENSEMBL_RESOURCE = "ensembl"
CHEMBL_RESOURCE = "chembl"

# The organism every gene lookup is narrowed to. Each resource spells it
# differently, so all three spellings live here together — an earlier
# version had `HUMAN_TAXON` used by UniProt while MyGene said `human` and
# Ensembl said `homo_sapiens` inline. Changing the constant then moved one
# resource and left the other two, which is worse than not being
# configurable at all: UniProt would answer about mouse Trp53 while MyGene
# and Ensembl answered about human TP53, and all three would be attached to
# the same node as agreeing evidence.
#
# Narrowing is what makes "exact" mean something: a bare gene symbol is
# ambiguous across organisms, and `TP53` has a distinct record in mouse,
# zebrafish and human.
ORGANISM = {
    "taxon_id": "9606",
    "mygene_species": "human",
    "ensembl_species": "homo_sapiens",
    "label": "Homo sapiens",
}

# Back-compat alias for the one spelling that was already exported.
HUMAN_TAXON = ORGANISM["taxon_id"]

RESOURCE_HOSTS: frozenset[str] = frozenset(
    (urlparse(url).hostname or "").lower()
    for url in (UNIPROT_API_URL, MYGENE_API_URL, ENSEMBL_API_URL, CHEMBL_API_URL)
)

# Enough to be useful, small enough that a reviewer reads all of it. A long
# annotation is one nobody checks, which defeats the review it must pass.
MAX_FACT_CHARS = 600


class ResourceError(Exception):
    """A resource did not answer, or answered unusably."""


@dataclass(frozen=True)
class ResourceMatch:
    """One record a resource offers for one entity name.

    ``matched_name`` is what the resource calls it, kept separate from the
    name we asked about so the reviewer compares the two rather than taking
    our word that they correspond.
    """

    resource: str
    external_id: str
    record_url: str
    matched_name: str
    facts: dict[str, Any] = field(default_factory=dict)

    def as_row(self) -> dict[str, Any]:
        return {
            "resource": self.resource,
            "external_id": self.external_id,
            "record_url": self.record_url,
            "matched_name": self.matched_name,
            "facts_json": json.dumps(self.facts, ensure_ascii=False),
        }


def _clip(text: Any) -> str:
    text = " ".join(str(text or "").split())
    return text[:MAX_FACT_CHARS]


def _looks_like_symbol(name: str) -> bool:
    """Whether ``name`` could be a gene/protein symbol at all.

    Both resources take any string, so without this an entity called
    "the patient cohort" is dutifully looked up, misses, and costs a
    request per node per resource. Symbols are short and have no spaces.
    """
    name = name.strip()
    return bool(name) and " " not in name and 2 <= len(name) <= 20


# ---------------------------------------------------------------------------
# UniProt
# ---------------------------------------------------------------------------

_UNIPROT_FIELDS = (
    "accession",
    "protein_name",
    "gene_names",
    "organism_name",
    "cc_function",
)


def build_uniprot_url(symbol: str) -> str:
    # `gene_exact` rather than a bare term: the bare form is what returned
    # ABRAXAS1 for BRCA1. `reviewed:true` keeps it to Swiss-Prot, whose
    # entries are manually curated and one-per-gene — the unreviewed
    # TrEMBL set adds isoform fragments that share the symbol.
    query = (
        f"gene_exact:{symbol} AND organism_id:{ORGANISM['taxon_id']} "
        "AND reviewed:true"
    )
    return (
        f"{UNIPROT_API_URL}?query={quote_plus(query)}"
        f"&size=1&fields={','.join(_UNIPROT_FIELDS)}"
    )


def parse_uniprot(json_text: str, symbol: str) -> ResourceMatch | None:
    try:
        payload = json.loads(json_text)
    except json.JSONDecodeError as exc:
        raise ResourceError(f"uniprot returned unparseable JSON: {exc}") from exc
    results = payload.get("results") or []
    if not results:
        return None
    item = results[0]
    accession = _clip(item.get("primaryAccession"))
    if not accession:
        return None

    genes = [
        g.get("geneName", {}).get("value", "")
        for g in (item.get("genes") or [])
        if isinstance(g, dict)
    ]
    # The exactness the query asked for, confirmed against what came back.
    # A resource that ignores a field qualifier would otherwise hand us a
    # near-match wearing an exact match's clothes.
    if not any(g.strip().upper() == symbol.strip().upper() for g in genes):
        return None

    description = item.get("proteinDescription") or {}
    recommended = description.get("recommendedName") or {}
    protein_name = _clip((recommended.get("fullName") or {}).get("value"))

    function = ""
    for comment in item.get("comments") or []:
        if comment.get("commentType") == "FUNCTION":
            texts = comment.get("texts") or []
            if texts:
                function = _clip(texts[0].get("value"))
            break

    return ResourceMatch(
        resource=UNIPROT_RESOURCE,
        external_id=accession,
        record_url=f"https://www.uniprot.org/uniprotkb/{accession}",
        matched_name=protein_name or accession,
        facts={
            "protein_name": protein_name,
            "gene_names": [g for g in genes if g],
            "organism": _clip((item.get("organism") or {}).get("scientificName")),
            "function": function,
        },
    )


# ---------------------------------------------------------------------------
# MyGene.info
# ---------------------------------------------------------------------------

_MYGENE_FIELDS = ("symbol", "name", "summary", "entrezgene", "taxid")


def build_mygene_url(symbol: str) -> str:
    # `symbol:` is the exact-field form; the bare query is a fuzzy search
    # across names and aliases and ranks by popularity.
    return (
        f"{MYGENE_API_URL}?q={quote_plus(f'symbol:{symbol}')}"
        f"&species={ORGANISM['mygene_species']}&size=1"
        f"&fields={','.join(_MYGENE_FIELDS)}"
    )


def parse_mygene(json_text: str, symbol: str) -> ResourceMatch | None:
    try:
        payload = json.loads(json_text)
    except json.JSONDecodeError as exc:
        raise ResourceError(f"mygene returned unparseable JSON: {exc}") from exc
    hits = payload.get("hits") or []
    if not hits:
        return None
    hit = hits[0]
    returned = _clip(hit.get("symbol"))
    if returned.upper() != symbol.strip().upper():
        return None
    entrez = _clip(hit.get("entrezgene"))
    if not entrez:
        return None
    return ResourceMatch(
        resource=MYGENE_RESOURCE,
        external_id=entrez,
        record_url=f"https://www.ncbi.nlm.nih.gov/gene/{entrez}",
        matched_name=_clip(hit.get("name")) or returned,
        facts={
            "symbol": returned,
            "gene_name": _clip(hit.get("name")),
            "summary": _clip(hit.get("summary")),
            "entrez_id": entrez,
        },
    )


# ---------------------------------------------------------------------------
# Ensembl
# ---------------------------------------------------------------------------


def build_ensembl_url(symbol: str) -> str:
    # A path lookup, not a search: Ensembl resolves the symbol itself and
    # 404s when it does not know it. There is no ranked list to mis-read.
    return (
        f"{ENSEMBL_API_URL}/{ORGANISM['ensembl_species']}/{quote_plus(symbol)}"
        "?content-type=application/json&expand=0"
    )


def parse_ensembl(json_text: str, symbol: str) -> ResourceMatch | None:
    try:
        item = json.loads(json_text)
    except json.JSONDecodeError as exc:
        raise ResourceError(f"ensembl returned unparseable JSON: {exc}") from exc
    if not isinstance(item, dict):
        return None
    gene_id = _clip(item.get("id"))
    if not gene_id:
        return None
    display = _clip(item.get("display_name"))
    # Ensembl resolves aliases, so the symbol it answers with can differ from
    # the one asked about. That is a redirect, not a match — the node is
    # named what it is named, and silently binding it to a different symbol
    # is the same class of error as the ABRAXAS1 hit.
    if display and display.upper() != symbol.strip().upper():
        return None
    return ResourceMatch(
        resource=ENSEMBL_RESOURCE,
        external_id=gene_id,
        record_url=f"https://www.ensembl.org/Homo_sapiens/Gene/Summary?g={gene_id}",
        matched_name=display or gene_id,
        facts={
            "ensembl_id": gene_id,
            "biotype": _clip(item.get("biotype")),
            "chromosome": _clip(item.get("seq_region_name")),
            "description": _clip(item.get("description")),
        },
    )


# ---------------------------------------------------------------------------
# ChEMBL
# ---------------------------------------------------------------------------


def build_chembl_url(name: str) -> str:
    # `__iexact` is ChEMBL's exact (case-insensitive) filter. The plain
    # `pref_name=` and the search endpoint both rank by similarity, which is
    # the behaviour this module exists to avoid.
    return f"{CHEMBL_API_URL}?pref_name__iexact={quote_plus(name)}&limit=1"


def parse_chembl(json_text: str, name: str) -> ResourceMatch | None:
    try:
        payload = json.loads(json_text)
    except json.JSONDecodeError as exc:
        raise ResourceError(f"chembl returned unparseable JSON: {exc}") from exc
    molecules = payload.get("molecules") or []
    if not molecules:
        return None
    item = molecules[0]
    chembl_id = _clip(item.get("molecule_chembl_id"))
    pref = _clip(item.get("pref_name"))
    if not chembl_id or pref.upper() != name.strip().upper():
        return None
    props = item.get("molecule_properties") or {}
    return ResourceMatch(
        resource=CHEMBL_RESOURCE,
        external_id=chembl_id,
        record_url=f"https://www.ebi.ac.uk/chembl/compound_report_card/{chembl_id}/",
        matched_name=pref,
        facts={
            "chembl_id": chembl_id,
            "molecule_type": _clip(item.get("molecule_type")),
            # 4 means an approved drug. Worth carrying: it is the one field
            # here that changes how much weight a claim deserves.
            "max_phase": _clip(item.get("max_phase")),
            "formula": _clip(props.get("full_molformula")),
        },
    )


_RESOURCE_DISPATCH: dict[str, tuple[Any, Any]] = {
    UNIPROT_RESOURCE: (build_uniprot_url, parse_uniprot),
    MYGENE_RESOURCE: (build_mygene_url, parse_mygene),
    ENSEMBL_RESOURCE: (build_ensembl_url, parse_ensembl),
    CHEMBL_RESOURCE: (build_chembl_url, parse_chembl),
}

RESOURCE_ORDER: tuple[str, ...] = tuple(_RESOURCE_DISPATCH)

RESOURCE_LABELS: dict[str, str] = {
    UNIPROT_RESOURCE: "UniProt (Swiss-Prot)",
    MYGENE_RESOURCE: "NCBI Gene (via MyGene.info)",
    ENSEMBL_RESOURCE: "Ensembl",
    CHEMBL_RESOURCE: "ChEMBL",
}


def lookup(resource: str, name: str) -> ResourceMatch | None:
    """Look one entity name up in one resource. None when it does not match.

    Returning None for "no exact match" is the whole contract: there is no
    second-best answer here, because a second-best record is a set of true
    facts about something else.
    """
    if resource not in _RESOURCE_DISPATCH:
        raise ResourceError(f"unknown resource {resource!r}")
    if not _looks_like_symbol(name):
        return None
    build, parse = _RESOURCE_DISPATCH[resource]
    try:
        body = _http_get_text(build(name.strip()))
    except HTTPError as exc:
        # A path-lookup resource says "I do not know this name" with 404
        # (Ensembl) or 400 (a malformed symbol it will not even consider).
        # Those are misses, not outages: reporting them as failures would
        # fill the operator's error list with every non-gene in the graph
        # and bury the one resource that is actually down.
        if exc.code in (400, 404):
            return None
        raise
    return parse(body, name.strip())
