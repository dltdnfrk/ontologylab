"""Typed, app-scoped dependencies for the FastAPI route layer."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Annotated

from fastapi import Depends, Request

from ontologylab.server.jobs import JobRegistry


class ServerConfigurationError(RuntimeError):
    """The FastAPI app was created without valid route dependencies."""


@dataclass(frozen=True)
class AppDependencies:
    data_dir: Path
    packs_dir: Path
    jobs: JobRegistry


def get_app_dependencies(request: Request) -> AppDependencies:
    """Read and validate dependencies owned by the request's application."""
    state = request.app.state
    try:
        data_dir = state.data_dir
    except AttributeError as exc:
        raise ServerConfigurationError(
            "server configuration missing app.state.data_dir"
        ) from exc
    if not isinstance(data_dir, Path):
        raise ServerConfigurationError(
            "server configuration app.state.data_dir must be a Path"
        )

    try:
        packs_dir = state.packs_dir
    except AttributeError as exc:
        raise ServerConfigurationError(
            "server configuration missing app.state.packs_dir"
        ) from exc
    if not isinstance(packs_dir, Path):
        raise ServerConfigurationError(
            "server configuration app.state.packs_dir must be a Path"
        )

    try:
        jobs = state.jobs
    except AttributeError as exc:
        raise ServerConfigurationError(
            "server configuration missing app.state.jobs"
        ) from exc
    if not isinstance(jobs, JobRegistry):
        raise ServerConfigurationError(
            "server configuration app.state.jobs must be a JobRegistry"
        )
    if jobs.data_dir != data_dir:
        raise ServerConfigurationError(
            "server configuration app.state.jobs belongs to a different data_dir"
        )
    return AppDependencies(data_dir=data_dir, packs_dir=packs_dir, jobs=jobs)


AppDependency = Annotated[AppDependencies, Depends(get_app_dependencies)]
