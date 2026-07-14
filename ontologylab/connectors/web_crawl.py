"""Single-URL / small-URL-list web connector (stdlib only).

Every URL's host is checked against ``allowlist.WEB_CRAWL_ALLOWED_HOSTS``
**before** any network I/O (deny-by-default). HTML is reduced to plain text
with a small ``html.parser`` extractor — quality is "good enough for
extraction", not layout-faithful.
"""

from __future__ import annotations

import re
from html.parser import HTMLParser
from typing import Any
from urllib.request import HTTPRedirectHandler, Request, build_opener

from ontologylab.connectors.allowlist import check_url
from ontologylab.connectors.base import (
    FETCH_TIMEOUT_S as _FETCH_TIMEOUT_S,
    USER_AGENT as _USER_AGENT,
    RawDocument,
)

_SKIPPED_ELEMENTS = {"script", "style", "noscript", "template", "svg", "head"}
_BLOCK_ELEMENTS = {
    "p", "div", "section", "article", "li", "ul", "ol", "table", "tr",
    "h1", "h2", "h3", "h4", "h5", "h6", "pre", "blockquote", "br",
}


class _TextExtractor(HTMLParser):
    """Collects visible text, block elements separated by newlines."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._chunks: list[str] = []
        self._skip_depth = 0
        self._title_parts: list[str] = []
        self._in_title = False

    def handle_starttag(self, tag: str, attrs: list) -> None:
        if tag in _SKIPPED_ELEMENTS:
            self._skip_depth += 1
        if tag == "title":
            self._in_title = True
        if tag in _BLOCK_ELEMENTS:
            self._chunks.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in _SKIPPED_ELEMENTS and self._skip_depth:
            self._skip_depth -= 1
        if tag == "title":
            self._in_title = False
        if tag in _BLOCK_ELEMENTS:
            self._chunks.append("\n")

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self._title_parts.append(data)
            return
        if self._skip_depth == 0 and data.strip():
            self._chunks.append(data)

    @property
    def title(self) -> str | None:
        title = "".join(self._title_parts).strip()
        return title or None

    @property
    def text(self) -> str:
        raw = "".join(self._chunks)
        raw = re.sub(r"[ \t]+", " ", raw)
        raw = re.sub(r"\n\s*\n+", "\n\n", raw)
        return raw.strip()


def html_to_text(html: str) -> tuple[str | None, str]:
    """Return (title, plain_text) for an HTML document."""
    extractor = _TextExtractor()
    extractor.feed(html)
    return extractor.title, extractor.text


class _AllowlistedRedirectHandler(HTTPRedirectHandler):
    """Re-validates every HTTP redirect target against the host allowlist.

    Without this, checking only the caller-supplied URL lets an allowlisted
    host 3xx-redirect the fetch to an arbitrary origin — network I/O would
    reach a host the deny-by-default allowlist never approved.
    """

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        check_url(newurl)  # raises NotAllowlisted on a non-allowlisted hop
        return super().redirect_request(req, fp, code, msg, headers, newurl)


_opener = build_opener(_AllowlistedRedirectHandler())


def _fetch_url(url: str) -> str:
    """Fetch one allowlist-checked URL; separated for test monkeypatching."""
    request = Request(url, headers={"User-Agent": _USER_AGENT})
    with _opener.open(request, timeout=_FETCH_TIMEOUT_S) as response:
        charset = response.headers.get_content_charset() or "utf-8"
        return response.read().decode(charset, errors="replace")


class WebCrawlConnector:
    """Fetches one or more explicit URLs (no link-following crawl)."""

    def name(self) -> str:
        return "web_crawl"

    async def fetch(self, source_spec: dict[str, Any]) -> list[RawDocument]:
        urls: list[str] = list(source_spec.get("urls") or [])
        if not urls:
            raise ValueError("web_crawl source_spec requires non-empty 'urls'")
        # Allowlist EVERY url before any network call, so a single bad url
        # rejects the whole request instead of partially fetching.
        for url in urls:
            check_url(url)
        documents: list[RawDocument] = []
        for url in urls:
            body = _fetch_url(url)
            if "<" in body and ">" in body:
                title, text = html_to_text(body)
            else:
                title, text = None, body
            if not text.strip():
                raise ValueError(f"no extractable text at {url}")
            documents.append(
                RawDocument(
                    source_kind="web_crawl",
                    source_uri=url,
                    title=title,
                    raw_text=text,
                )
            )
        return documents
