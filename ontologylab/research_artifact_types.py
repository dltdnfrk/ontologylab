from __future__ import annotations

from pathlib import Path
from typing import NamedTuple

from ontologylab.research_plan import PlanSnapshot
from ontologylab.research_spec import ResearchSpec


class ResearchArtifactError(Exception):
    def __init__(self, code: str, path: Path) -> None:
        super().__init__(code)
        self.code, self.path = code, path

    def __str__(self) -> str:
        return f"{self.path}: {self.code}"


class ArtifactPointer(NamedTuple):
    artifact_id: str
    content_hash: str
    path: Path


class ResearchArtifactPointers(NamedTuple):
    root_hash: str
    spec_id: str
    plan_ids: tuple[str, ...]
    acquisition_ids: tuple[str, ...]
    post_extraction_id: str | None
    current_plan_id: str
    current_plan_version: int


class ResearchReplay(NamedTuple):
    spec: ResearchSpec
    plans: tuple[PlanSnapshot, ...]
    acquisitions: tuple[ArtifactPointer, ...]
    post_extraction: ArtifactPointer | None
    root_hash: str

    def pointers(self) -> ResearchArtifactPointers:
        current = self.plans[-1]
        post_id = (
            None
            if self.post_extraction is None
            else self.post_extraction.artifact_id
        )
        return ResearchArtifactPointers(
            self.root_hash,
            self.spec.spec_id,
            tuple(plan.plan_id for plan in self.plans),
            tuple(item.artifact_id for item in self.acquisitions),
            post_id,
            current.plan_id,
            current.plan_version,
        )
