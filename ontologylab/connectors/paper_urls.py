"""Fixed paper endpoints and source-specific URL construction."""

from __future__ import annotations

import os
import re
from ontologylab.connectors.paper_common import (
    ARXIV_SOURCE,
    BIORXIV_SOURCE,
    CLINICALTRIALS_SOURCE,
    CORE_SOURCE,
    CROSSREF_SOURCE,
    ELSEVIER_SOURCE,
    EUROPEPMC_SOURCE,
    OPENALEX_SOURCE,
    PUBMED_SOURCE,
    SEMANTIC_SCHOLAR_SOURCE,
    SPRINGER_SOURCE,
)
from urllib.parse import parse_qsl, quote_plus, urlencode, urlsplit, urlunsplit

ARXIV_API_URL = "https://export.arxiv.org/api/query"


CROSSREF_API_URL = "https://api.crossref.org/works"


OPENALEX_API_URL = "https://api.openalex.org/works"


SEMANTIC_SCHOLAR_API_URL = (
    "https://api.semanticscholar.org/graph/v1/paper/search"
)


EUROPEPMC_API_URL = (
    "https://www.ebi.ac.uk/europepmc/webservices/rest/search"
)


EUROPEPMC_FULLTEXT_URL = (
    "https://www.ebi.ac.uk/europepmc/webservices/rest/{pmcid}/fullTextXML"
)


_PMCID_RE = re.compile(r"^PMC[0-9]{1,12}$")


def europepmc_fulltext_url(pmcid: str) -> str:
    """URL for one PMC article's full text, or "" when the id is not one.

    Refusing an unrecognised id here means a malformed or hostile `pmcid`
    can never become a path segment.
    """
    pmcid = (pmcid or "").strip()
    if not _PMCID_RE.match(pmcid):
        return ""
    return EUROPEPMC_FULLTEXT_URL.format(pmcid=pmcid)


ELSEVIER_API_URL = "https://api.elsevier.com/content/search/scopus"


SPRINGER_API_URL = "https://api.springernature.com/openaccess/json"


CORE_API_URL = "https://api.core.ac.uk/v3/search/works"


_ELSEVIER_FIELDS = (
    "dc:title",
    "dc:description",
    "dc:creator",
    "prism:doi",
    "prism:publicationName",
    "prism:coverDate",
    "prism:url",
    "citedby-count",
    "subtypeDescription",
)


_CROSSREF_SELECT_FIELDS = (
    "DOI",
    "URL",
    "title",
    "abstract",
    "type",
    "author",
    "published",
    "container-title",
    "is-referenced-by-count",
    "update-to",
)


def _build_query_url(query: str, limit: int) -> str:
    return (
        f"{ARXIV_API_URL}"
        f"?search_query=all:{quote_plus(query)}"
        f"&start=0&max_results={limit}"
    )


def _build_crossref_url(query: str, limit: int) -> str:
    # `select` keeps the payload to exactly the fields we ingest.
    return (
        f"{CROSSREF_API_URL}"
        f"?query={quote_plus(query)}"
        f"&rows={limit}"
        "&select=" + ",".join(_CROSSREF_SELECT_FIELDS)
    )


OPENALEX_MAILTO_ENV = "OPENALEX_MAILTO"


def _openalex_mailto() -> str:
    return os.environ.get(OPENALEX_MAILTO_ENV, "").strip()


def _build_openalex_url(query: str, limit: int) -> str:
    query_param = (
        f"filter={quote_plus(query)}"
        if query.startswith("title_and_abstract.search:")
        else f"search={quote_plus(query)}"
    )
    url = (
        f"{OPENALEX_API_URL}?{query_param}"
        f"&per-page={limit}"
        "&select=id,doi,display_name,abstract_inverted_index,type,"
        "publication_year,cited_by_count,authorships,primary_location"
    )
    mailto = _openalex_mailto()
    if mailto:
        url += f"&mailto={quote_plus(mailto)}"
    return url


def _build_semanticscholar_url(query: str, limit: int) -> str:
    return (
        f"{SEMANTIC_SCHOLAR_API_URL}"
        f"?query={quote_plus(query)}"
        f"&limit={limit}"
        "&fields=title,abstract,url,externalIds,publicationTypes,"
        "year,authors,venue,citationCount"
    )


def _build_europepmc_url(query: str, limit: int) -> str:
    return (
        f"{EUROPEPMC_API_URL}"
        f"?query={quote_plus(query)}"
        f"&pageSize={limit}"
        "&format=json&resultType=core"
    )


_PAGE_PARAMETER: dict[str, tuple[str, int]] = {
    ARXIV_SOURCE: ("start", 0),
    CROSSREF_SOURCE: ("offset", 0),
    OPENALEX_SOURCE: ("page", 1),
    SEMANTIC_SCHOLAR_SOURCE: ("offset", 0),
    EUROPEPMC_SOURCE: ("page", 1),
    PUBMED_SOURCE: ("retstart", 0),
    ELSEVIER_SOURCE: ("start", 0),
    SPRINGER_SOURCE: ("s", 1),
    CORE_SOURCE: ("offset", 0),
}


PAGINATED_SOURCES: frozenset[str] = frozenset(_PAGE_PARAMETER) | {
    BIORXIV_SOURCE,
    CLINICALTRIALS_SOURCE,
}


def _paginate_url(
    source: str,
    url: str,
    page: int,
    page_size: int,
) -> str:
    """Add one source's offset/page parameter without touching credentials."""
    if source not in PAGINATED_SOURCES or page <= 1:
        return url
    name, first = _PAGE_PARAMETER[source]
    value = (
        page
        if first == 1 and name == "page"
        else first + ((page - 1) * page_size)
    )
    split = urlsplit(url)
    params = dict(parse_qsl(split.query, keep_blank_values=True))
    params[name] = str(value)
    return urlunsplit(
        (split.scheme, split.netloc, split.path, urlencode(params), split.fragment)
    )


def _build_elsevier_url(query: str, limit: int) -> str:
    # `field` is required to get an abstract: the STANDARD view omits
    # `dc:description`, so without this the parser would return titles only.
    return (
        f"{ELSEVIER_API_URL}"
        f"?query={quote_plus(query)}"
        f"&count={limit}"
        "&field=" + ",".join(_ELSEVIER_FIELDS)
    )


def _build_springer_url(query: str, limit: int) -> str:
    return f"{SPRINGER_API_URL}?q={quote_plus(query)}&p={limit}"


def _build_core_url(query: str, limit: int) -> str:
    return f"{CORE_API_URL}?q={quote_plus(query)}&limit={limit}"
