"""URL construction for date, identifier, trial, and local searches."""

from __future__ import annotations

import datetime
import os
from ontologylab.connectors.allowlist import NotAllowlisted, check_searxng_base_url
from urllib.parse import parse_qsl, quote_plus, urlencode, urlsplit, urlunsplit

BIORXIV_API_URL = "https://api.biorxiv.org/details/biorxiv"


BIORXIV_WINDOW_DAYS = 28


PUBMED_EUTILS_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"


CLINICALTRIALS_API_URL = "https://clinicaltrials.gov/api/v2/studies"


SEARXNG_URL_ENV = "ONTOLOGYLAB_SEARXNG_URL"


SEARXNG_ENGINES = "arxiv,google scholar,pubmed,semantic scholar,crossref,openalex"


def _build_clinicaltrials_url(query: str, limit: int) -> str:
    # `fields` keeps the payload to what the parser reads. Without it a
    # study record is tens of kilobytes of arms, eligibility and locations,
    # and a five-source fan-out multiplies that.
    fields = ",".join(
        (
            "NCTId",
            "BriefTitle",
            "OfficialTitle",
            "BriefSummary",
            "DetailedDescription",
            "OverallStatus",
            "Condition",
        )
    )
    return (
        f"{CLINICALTRIALS_API_URL}"
        f"?query.term={quote_plus(query)}"
        f"&pageSize={limit}"
        f"&fields={fields}"
        "&format=json"
    )


def _build_biorxiv_url(query: str, limit: int) -> str:
    """A recent-window browse URL; the query filters locally in the parser.

    The bioRxiv API has no keyword endpoint, so the query cannot be encoded
    here. The science-skills guidance is to browse a narrow window (1-4
    weeks) and filter locally — a wider range means downloading every
    preprint in it. `limit` does not reach the API either (the endpoint has
    no result count); the fetch path caps the parsed page with it.
    """
    end = datetime.date.today()
    start = end - datetime.timedelta(days=BIORXIV_WINDOW_DAYS)
    return f"{BIORXIV_API_URL}/{start.isoformat()}/{end.isoformat()}/0"


def _build_pubmed_url(query: str, limit: int) -> str:
    """The esearch step: keyword -> PMIDs. efetch follows in _fetch_pubmed."""
    return (
        f"{PUBMED_EUTILS_URL}/esearch.fcgi"
        f"?db=pubmed&term={quote_plus(query)}"
        f"&retmode=json&retmax={limit}"
    )


def _searxng_base_url() -> str:
    """The user's own SearXNG, validated, or "" when not configured.

    Settings first, environment second. The setting is what the app can
    show and edit; the variable is the escape hatch for a headless run,
    which is the same order `resolve_source_key` uses for publisher keys.

    Unset is not an error: an unconfigured source drops out of the fan-out
    the same way an unkeyed publisher does. A *misconfigured* one does
    raise — a typo that silently disabled the source would be worse than a
    refusal, because the run would still look complete.
    """
    # This reads the environment and nothing else, deliberately.
    #
    # The obvious alternative — read `server.settings` here — was written
    # first and reverted. It inverts the layering (`server` depends on
    # `connectors`, not the reverse) and it makes every source lookup
    # depend on a file under `paths.ROOT` that every process on the machine
    # shares: saving the setting once in the browser made unrelated tests
    # fail, because "is SearXNG configured?" started meaning "does this
    # developer happen to run one?".
    #
    # The setting still works. `server.settings.apply_to_environment` is
    # the one explicit bridge, called where the app starts and where the
    # value is saved.
    raw = os.environ.get(SEARXNG_URL_ENV, "").strip()
    if not raw:
        return ""
    return check_searxng_base_url(raw)


def _build_searxng_url(query: str, limit: int) -> str:
    # `limit` is deliberately unused: SearXNG answers a page at a time and
    # takes no result count. One page of six engines measured at 55 results
    # for an ordinary query, so the cap is applied in `parse_searxng`
    # instead — dropping it entirely would let one source outweigh the
    # other six combined in the fan-out.
    del limit
    base = _searxng_base_url()
    if not base:
        # Reached only if the source was requested explicitly; the default
        # fan-out filters it out first.
        raise NotAllowlisted(
            f"SearXNG is not configured; set {SEARXNG_URL_ENV} to the "
            f"address of an instance you run (e.g. http://localhost:8080)"
        )
    # Engines are named rather than taking the whole `science` category.
    # Measured against a live instance, `categories=science` also returns
    # `pdbe` (protein structure records) and `openairedatasets` — entries
    # with a title and no abstract, which would enter a corpus whose whole
    # claim is that a proposal traces back to something a paper says.
    #
    # google scholar is the reason this source exists: it has no API, so it
    # is unreachable any other way.
    return (
        f"{base}/search"
        f"?q={quote_plus(query)}"
        f"&engines={quote_plus(SEARXNG_ENGINES)}"
        "&format=json"
        "&pageno=1"
    )


def _biorxiv_cursor_url(base_url: str, cursor: int) -> str:
    """Replace the cursor path component without changing the browse window."""
    split = urlsplit(base_url)
    parts = split.path.rstrip("/").split("/")
    parts[-1] = str(cursor)
    return urlunsplit(
        (
            split.scheme,
            split.netloc,
            "/".join(parts),
            split.query,
            split.fragment,
        )
    )


def _clinicaltrials_page_url(base_url: str, token: str) -> str:
    """Add the next-page token without changing the query or page size."""
    if not token:
        return base_url
    split = urlsplit(base_url)
    params = dict(parse_qsl(split.query, keep_blank_values=True))
    params["pageToken"] = token
    return urlunsplit(
        (
            split.scheme,
            split.netloc,
            split.path,
            urlencode(params),
            split.fragment,
        )
    )


def _build_pubmed_efetch_url(ids: list[str]) -> str:
    """Build the existing efetch URL after esearch supplies its identifiers."""
    return (
        f"{PUBMED_EUTILS_URL}/efetch.fcgi?db=pubmed&retmode=xml"
        f"&id={','.join(ids)}"
    )
