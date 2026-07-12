"""Connector Protocol + the raw-document record connectors return.

Modeled after (not copied from) drylab's clean domain Protocol style. A
connector fetches raw documents for a source spec; persistence into the
``documents`` table is the caller's job (main.collect), so connectors stay
side-effect-free apart from network I/O.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable


@dataclass
class RawDocument:
    """One fetched document, pre-persistence."""

    source_kind: str  # "paper_api" | "web_crawl" | "upload"
    source_uri: str
    title: str | None
    raw_text: str

    @property
    def content_hash(self) -> str:
        return "sha256:" + hashlib.sha256(self.raw_text.encode("utf-8")).hexdigest()


@runtime_checkable
class Connector(Protocol):
    """A document-ingest backend. Must enforce the allowlist BEFORE any I/O."""

    def name(self) -> str:
        ...

    async def fetch(self, source_spec: dict[str, Any]) -> list[RawDocument]:
        ...
