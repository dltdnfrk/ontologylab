"""Pydantic request/response models for the ontologylab local web layer."""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field, field_validator

from ontologylab.connectors.paper_api import (
    DEFAULT_LIMIT as PAPER_DEFAULT_LIMIT,
    DEFAULT_PAPER_SOURCE,
    MAX_LIMIT as PAPER_MAX_LIMIT,
)
from ontologylab.paths import (
    DEFAULT_ACTOR,
    DEFAULT_ENGINE,
    DEFAULT_MAX_ENGINE_CALLS,
    DEFAULT_MODEL,
    DEFAULT_SEED,
    DEFAULT_TIME_BUDGET_S,
)


class CollectRequest(BaseModel):
    """Trigger a collect run against allowlisted sources (Sources screen)."""

    urls: list[str] = Field(default_factory=list)
    files: list[str] = Field(default_factory=list)
    paper_queries: list[str] = Field(default_factory=list)
    paper_source: str = DEFAULT_PAPER_SOURCE
    limit: int = Field(PAPER_DEFAULT_LIMIT, ge=1, le=PAPER_MAX_LIMIT)


class ResearchRequest(BaseModel):
    """Collect a topic across paper sources, then extract what arrived.

    An empty `sources` means every implemented source. `topic` is validated
    by `check_paper_query` in the route before a job exists, so a bad topic
    comes back as a typed `rejected` response rather than as a job that
    fails a moment later — the classification has nowhere to live on `Job`.
    """

    topic: str
    sources: list[str] = Field(default_factory=list)
    limit: int = Field(PAPER_DEFAULT_LIMIT, ge=1, le=PAPER_MAX_LIMIT)
    # Fetch open-access full text where it exists, instead of stopping at
    # the abstract. Default on: the body is where methods and measurements
    # live, and an abstract states conclusions without the evidence for
    # them. It costs one extra request per open-access hit and a much
    # larger extraction budget, so it remains switchable.
    fulltext: bool = True
    engine: str = "mock"
    model: Optional[str] = None
    max_engine_calls: int = Field(DEFAULT_MAX_ENGINE_CALLS, ge=1)
    time_budget: float = Field(DEFAULT_TIME_BUDGET_S, gt=0)
    seed: int = DEFAULT_SEED


class ExtractRequest(BaseModel):
    """Start a background extraction job (Extraction Jobs screen)."""

    engine: str = "mock"
    model: Optional[str] = None
    doc_ids: list[str] = Field(default_factory=list)
    max_engine_calls: int = Field(DEFAULT_MAX_ENGINE_CALLS, ge=1)
    time_budget: float = Field(DEFAULT_TIME_BUDGET_S, gt=0)
    seed: int = DEFAULT_SEED


class SourceCreate(BaseModel):
    """Connect a publisher API (Sources screen).

    ``key`` is write-only: it goes straight into the Keychain and is never
    stored in the registry, returned, or logged. It deliberately carries **no
    Field constraints** — a failed constraint produces a 422 whose `input`
    holds the offending value, and the value here is an API key. Its shape is
    checked inside the route, where the message is written by hand.
    (`app.create_app` also strips `input` from every validation error, so
    this is belt and braces on the one endpoint that receives a secret.)
    """

    id: str
    role: str = "literature"
    label: str = ""
    key: Optional[str] = None
    keychain_account: str = ""
    api_key_env: str = ""


class SourceModel(BaseModel):
    """Public view of one connected source — presence only, never a key."""

    id: str
    role: str
    keychain_account: str = ""
    api_key_env: str = ""
    label: str = ""
    key_present: bool = False


class PackBuildRequest(BaseModel):
    """Build a verified-only knowledge pack (Packs screen)."""

    name: str = Field(min_length=1, max_length=64)

    @field_validator("name")
    @classmethod
    def _safe_name(cls, value: str) -> str:
        # The name becomes a directory segment under packs_dir; reject path
        # separators / traversal up front (build_pack revalidates in depth).
        from ontologylab.packbuilder import PackBuildError, safe_pack_component

        try:
            return safe_pack_component(value, kind="pack name")
        except PackBuildError as exc:
            raise ValueError(str(exc)) from exc


class EngineInfo(BaseModel):
    """Availability info for one engine adapter."""

    name: str
    available: bool
    default_model: Optional[str] = None


class Settings(BaseModel):
    """Persisted local defaults for extraction / review."""

    default_engine: str = DEFAULT_ENGINE
    default_model: Optional[str] = DEFAULT_MODEL
    data_dir: Optional[str] = None
    packs_dir: Optional[str] = None


class CostSummary(BaseModel):
    """Aggregated engine-call cost across extraction jobs."""

    total_engine_calls: int
    total_elapsed_s: float
    per_engine: dict = Field(default_factory=dict)


class ProviderModel(BaseModel):
    """Public view of one registered API provider (never carries a key).

    ``api_key_env`` is the NAME of an env var; ``key_present`` reports whether
    that var is currently set — the value itself is never serialized.
    """

    id: str
    kind: str
    base_url: str
    api_key_env: str
    models: list[str] = Field(default_factory=list)
    label: str = ""
    key_present: bool = False


class ProviderCreate(BaseModel):
    """Register (or upsert) an API provider from the dashboard/HTTP layer."""

    id: str
    kind: str
    base_url: str
    api_key_env: str
    models: list[str] = Field(default_factory=list)
    label: str = ""


class ProviderTestResult(BaseModel):
    """Outcome of a one-shot provider ping (never carries a key)."""

    ok: bool
    latency_ms: Optional[int] = None
    sample: Optional[str] = None
    error: Optional[str] = None


class ProposalAction(BaseModel):
    """Approve or reject a single proposed node/edge."""

    id: str
    by: str = DEFAULT_ACTOR
    note: Optional[str] = None
    cascade: bool = False


class CriticRunRequest(BaseModel):
    """Run the critic model over pending proposals (advisory scores only)."""

    engine: str = "mock"
    model: Optional[str] = None
    limit: int = Field(200, ge=1, le=1000)
    batch_size: int = Field(20, ge=1, le=100)


class MergeScanRequest(BaseModel):
    """Run the fuzzy duplicate scan (proposals only, never merges)."""

    min_similarity: float = Field(0.82, ge=0.5, le=1.0)


class MergeAction(BaseModel):
    """Human decision on one merge candidate (Merge screen).

    ``target_id``/``source_id`` are explicit — the UI never pre-selects a
    direction for the reviewer.
    """

    target_id: str
    source_id: str
    by: str = DEFAULT_ACTOR
    note: Optional[str] = None


class MergeDismiss(BaseModel):
    """Dismiss one merge candidate (never re-proposed)."""

    by: str = DEFAULT_ACTOR
    note: Optional[str] = None


class JobStatus(BaseModel):
    """Status snapshot of one background extraction job (Extraction Jobs screen)."""

    job_id: str
    kind: str = "extract"  # "extract" | "research"
    status: str  # "running" | "complete" | "failed" | "cancelled"
    # Which half of a research run is executing. Kept out of `status` so the
    # dashboard's running→terminal edge detection keeps working.
    phase: str = ""
    engine: str
    model: Optional[str] = None
    started_ts: float
    finished_ts: Optional[float] = None
    totals: dict[str, int] = Field(
        default_factory=lambda: {
            "nodes_new": 0,
            "nodes_merged": 0,
            "edges_new": 0,
            "edges_merged": 0,
        }
    )
    progress: list[str] = Field(default_factory=list)
    error: Optional[str] = None


class AnnotationDecision(BaseModel):
    """Accept or reject one resource record for one node.

    `accept` is required and has no default: this is the decision the whole
    annotations table exists to record, and a default would let a
    malformed request cast a vote.
    """

    accept: bool
    note: str | None = None
