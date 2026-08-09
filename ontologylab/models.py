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
    qualifiers: dict[str, Any] = field(default_factory=dict)
    confidence: float | None = None
    source_span: SourceSpan | None = None


@dataclass(frozen=True, slots=True)
class OntologyXrefCandidate:
    """One unverified external mapping carried by an extraction candidate."""

    authority: str
    external_id: str
    mapping_predicate: str
    source_uri: str
    source_version: str | None
    valid_from: float | None
    valid_to: float | None
    retrieved_at: float
    confidence: float
    license_gate: str
    lifecycle: str
    replacement_xref_id: str | None
    change_reason: str | None


@dataclass(frozen=True, slots=True)
class OntologyCandidate:
    """Typed evidence offered to the ontology proposal workflow.

    Source review and ontology review are deliberately separate.  A verified
    graph row records who accepted the extracted fact; it still becomes an
    ontology term only after the proposal carries its own human verification.
    """

    id: str
    source_kind: str
    source_id: str
    source_status: str
    source_verified_by: str | None
    source_verified_at: float | None
    schema_version_id: int
    type_name: str
    preferred_label: str
    language: str
    definition: str
    aliases: tuple[str, ...]
    qualifiers: dict[str, Any]
    lifecycle: str
    replacement_term_id: str | None
    change_reason: str | None
    xrefs: tuple[OntologyXrefCandidate, ...]
    source_doc_id: str | None
    source_span: SourceSpan | None


@dataclass(frozen=True, slots=True)
class OntologySourceVerification:
    """Review state of one extraction artifact contributing to a proposal."""

    candidate_id: str
    status: str
    verified_by: str | None
    verified_at: float | None


@dataclass(frozen=True, slots=True)
class HumanVerification:
    """The explicit human decision that turns a proposal into a term change."""

    decision: str
    reviewer: str
    provenance: str
    verified_at: float
    note: str | None = None


@dataclass(frozen=True, slots=True)
class OntologyProposal:
    """Deterministic proposal artifact; never verified when first produced."""

    id: str
    action: str
    target_term_id: str | None
    schema_version_id: int
    source_kind: str
    type_name: str
    preferred_label: str
    language: str
    definition: str
    aliases: tuple[str, ...]
    qualifiers: dict[str, Any]
    lifecycle: str
    replacement_term_id: str | None
    change_reason: str | None
    xrefs: tuple[OntologyXrefCandidate, ...]
    source_candidate_ids: tuple[str, ...]
    source_verifications: tuple[OntologySourceVerification, ...]
    requires_human_verification: bool
    verification: HumanVerification | None


@dataclass(frozen=True, slots=True)
class OntologyTerm:
    """Exact immutable row shape published from ``ontology_term``."""

    id: str
    iri: str
    preferred_label: str
    language: str
    definition: str
    lifecycle: str
    replacement_term_id: str | None
    change_reason: str | None
    schema_version_id: int
    reviewer: str
    provenance: str
    created_ts: float
    updated_ts: float
    legacy_kind: str | None
    legacy_id: int | None


@dataclass(frozen=True, slots=True)
class TermAlias:
    """Exact immutable row shape published from ``term_alias``."""

    id: str
    term_id: str
    label: str
    language: str
    alias_kind: str
    reviewer: str
    provenance: str
    created_ts: float


@dataclass(frozen=True, slots=True)
class TermXref:
    """Exact immutable row shape published from ``term_xref``."""

    id: str
    term_id: str
    authority: str
    external_id: str
    mapping_predicate: str
    source_uri: str
    source_version: str | None
    valid_from: float | None
    valid_to: float | None
    retrieved_at: float
    confidence: float
    reviewer: str
    lifecycle: str
    replacement_xref_id: str | None
    change_reason: str | None
    license_gate: str
    created_ts: float
    updated_ts: float


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
    # Version/algorithm capability marker for semantic comparison. Actual
    # packed facts remain solely in the content-hashed immutable pack.sqlite.
    semantic_fact_baseline: dict[str, Any] | None = None
    # Sorted schema_version ids whose verified facts the pack ships. Packs
    # preserve facts judged under every historical ontology version, so a
    # consumer resolves each fact's schema_version_id against this list and
    # the version-keyed "schemas" collection in schema.json. Absent (None)
    # only on manifests written before the multi-schema contract.
    included_schema_version_ids: list[int] | None = None
    # Machine-readable publication boundary for first-class ontology rows.
    # None only on packs written before ontology term publication shipped.
    ontology_publication: dict[str, Any] | None = None


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
    "OntologyXrefCandidate",
    "OntologyCandidate",
    "OntologySourceVerification",
    "HumanVerification",
    "OntologyProposal",
    "OntologyTerm",
    "TermAlias",
    "TermXref",
    "PackManifest",
    "Engine",
]
