"""Pydantic request/response models for the ontologylab local web layer."""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field

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


class ExtractRequest(BaseModel):
    """Start a background extraction job (Extraction Jobs screen)."""

    engine: str = "mock"
    model: Optional[str] = None
    doc_ids: list[str] = Field(default_factory=list)
    max_engine_calls: int = Field(DEFAULT_MAX_ENGINE_CALLS, ge=1)
    time_budget: float = Field(DEFAULT_TIME_BUDGET_S, gt=0)
    seed: int = DEFAULT_SEED


class PackBuildRequest(BaseModel):
    """Build a verified-only knowledge pack (Packs screen)."""

    name: str = Field(min_length=1, max_length=64)


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
    kind: str = "extract"
    status: str  # "running" | "complete" | "failed"
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
