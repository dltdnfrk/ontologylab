"""Pydantic request/response models for the ontologylab local web layer."""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field


class CollectRequest(BaseModel):
    """Trigger a collect run against allowlisted sources (Sources screen)."""

    urls: list[str] = Field(default_factory=list)
    files: list[str] = Field(default_factory=list)
    paper_queries: list[str] = Field(default_factory=list)
    paper_source: str = "arxiv"
    limit: int = Field(5, ge=1, le=25)


class ExtractRequest(BaseModel):
    """Start a background extraction job (Extraction Jobs screen)."""

    engine: str = "mock"
    model: Optional[str] = None
    doc_ids: list[str] = Field(default_factory=list)
    max_engine_calls: int = Field(200, ge=1)
    time_budget: float = Field(1800.0, gt=0)
    seed: int = 7


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

    default_engine: str = "claude"
    default_model: Optional[str] = "claude-fable-5"
    data_dir: Optional[str] = None
    packs_dir: Optional[str] = None


class CostSummary(BaseModel):
    """Aggregated engine-call cost across extraction jobs."""

    total_engine_calls: int
    total_elapsed_s: float
    per_engine: dict = Field(default_factory=dict)


class ProposalAction(BaseModel):
    """Approve or reject a single proposed node/edge."""

    id: str
    by: str = "local-user"
    note: Optional[str] = None
    cascade: bool = False
