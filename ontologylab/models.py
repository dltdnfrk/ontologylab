"""Core data model for ontologylab: dataclasses and Protocols shared across modules.

Plain-data contracts for the pipeline (documents, proposed entities/relations,
pack manifests) and the structural Protocols (Engine, Connector) every other
module imports against. No logic beyond type declarations.

The ``Engine`` Protocol is carried over verbatim from drylab; ``Document`` /
``ProposedEntity`` / ``ProposedRelation`` / ``PackManifest`` replace the
optimization-loop dataclasses.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable


@dataclass
class Document:
    """One collected raw document (paper-API record, crawled page, or upload)."""

    id: str
    source_kind: str  # "paper_api" | "web_crawl" | "upload"
    source_uri: str
    title: str | None
    fetched_ts: float
    content_hash: str  # sha256 of raw text
    raw_text_path: str  # path under data/documents/<id>/
    # Which connector fetched this (`arxiv`, `europepmc`, …) and what kind
    # of record it is (`evidence.GRADES`). Both are shown at review time:
    # judging whether a paper supports a claim starts with knowing whether
    # anyone reviewed the paper.
    source: str = ""
    evidence_grade: str = ""


@dataclass
class SourceSpan:
    """Character range into a document's raw text backing one extracted fact."""

    start: int
    end: int

    def as_json(self) -> str:
        import json

        return json.dumps({"start": self.start, "end": self.end})


@dataclass
class ProposedEntity:
    """A schema-valid extracted entity, pre-resolution (id is chunk-minted)."""

    id: str  # uuid4 hex minted by the parser; may be collapsed by resolution
    entity_type: str
    name: str
    aliases: list[str] = field(default_factory=list)
    properties: dict[str, Any] = field(default_factory=dict)
    confidence: float | None = None
    source_span: SourceSpan | None = None  # document coordinates (rebased)
    synthesized: bool = False  # endpoint minted for a relation, not emitted


@dataclass
class ProposedRelation:
    """A schema-valid extracted relation with endpoints bound to minted entity ids."""

    id: str
    relation_type: str
    src_entity_id: str
    dst_entity_id: str
    properties: dict[str, Any] = field(default_factory=dict)
    confidence: float | None = None
    source_span: SourceSpan | None = None


@dataclass
class PackManifest:
    """Identity + integrity metadata for one immutable knowledge pack."""

    pack_id: str
    created_ts: float
    schema_version_id: int
    schema_label: str
    source_job_id: str | None
    counts: dict[str, int]
    search_tier: str  # "fts5" | "embeddings"
    embedding_model: str | None
    ontologylab_version: str
    content_hash: str
    # The commit the pack was built against, so a consumer can judge how
    # much has happened since. None when the build host is not a git repo —
    # never a fabricated value.
    basis_commit: str | None = None
    # The documented default staleness policy (threshold + prose). Advisory
    # and overridable; it exists so consumers do not each invent a policy.
    staleness_policy: dict[str, Any] | None = None
    # Durable extraction state for the exact source streams of shipped facts,
    # including any explicit operator override used to admit incompleteness.
    extraction_completeness: dict[str, Any] | None = None


@runtime_checkable
class Engine(Protocol):
    """A text-generation backend (offline mock or CLI-adapter based)."""

    def name(self) -> str:
        """Return the engine's short identifying name."""
        ...

    async def generate(
        self, prompt: str, *, model: str | None
    ) -> tuple[str, dict[str, Any]]:
        """Produce raw model text plus usage metadata for the given prompt.

        Returns (raw_text, usage_meta); usage_meta may include keys such as
        "calls" and "elapsed". Downstream parsing (fenced-block extraction,
        JSON validation) is the caller's responsibility.
        """
        ...


# NOTE: the Connector Protocol lives in connectors/base.py (returning typed
# RawDocument records) — the single source of truth for the ingest contract.

__all__ = [
    "Document",
    "SourceSpan",
    "ProposedEntity",
    "ProposedRelation",
    "PackManifest",
    "Engine",
]
