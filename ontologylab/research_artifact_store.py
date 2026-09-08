from __future__ import annotations

import os
import re
import secrets
from pathlib import Path

from ontologylab import research_artifact_codec as codec
from ontologylab import research_plan, research_spec
from ontologylab.provenance import Provenance
from ontologylab.research_artifact_types import (
    ArtifactPointer,
    ResearchArtifactError,
    ResearchReplay,
)
from ontologylab.research_plan import PlanSnapshot
from ontologylab.research_spec import JsonObject, ResearchSpec

SPEC_NAME, POST_NAME = "research-spec.json", "post-extraction-assessment.json"
_PLAN_RE = re.compile(r"research-plan-([0-9]{4})[.]json")
_ACQ_RE = re.compile(r"research-acquisition-([0-9]{4})[.]json")


def _record(
    provenance: Provenance | None,
    kind: str,
    pointer: ArtifactPointer,
    plan: PlanSnapshot | None = None,
) -> None:
    if provenance is None:
        return
    payload: JsonObject = {
        "artifact_kind": kind,
        "artifact_id": pointer.artifact_id,
        "content_hash": pointer.content_hash,
        "filename": pointer.path.name,
    }
    if plan is not None:
        payload.update(
            spec_id=plan.spec_id, plan_id=plan.plan_id, plan_version=plan.plan_version
        )
    provenance.log("research.artifact", payload)


def _validate_lineage(lineage: tuple[PlanSnapshot, ...], path: Path) -> None:
    try:
        research_plan.validate_lineage(lineage)
    except research_plan.PlanTransitionError as error:
        code = (
            "duplicate_execution"
            if "novel" in error.reason
            else "invalid_lineage"
        )
        raise ResearchArtifactError(code, path) from error


def _assessment(
    path: Path, kind: str, raw: bytes, plan: PlanSnapshot | None,
    spec_id: str, version: int,
) -> ArtifactPointer:
    pointer, bound_spec, spec_hash, plan_id, bound_version = codec.parse_bound_artifact(
        path, kind, raw
    )
    binding = None if plan is None else (spec_id, plan.spec_hash, plan.plan_id, version)
    codec.require(
        (bound_spec, spec_hash, plan_id, bound_version) == binding,
        "stale_assessment", path,
    )
    return pointer


class ResearchArtifactStore:
    def __init__(self, job_dir: Path, provenance: Provenance | None = None) -> None:
        self.job_dir, self.provenance = Path(job_dir), provenance
        codec.require(self.job_dir.is_dir(), "missing_job_directory", self.job_dir)

    def _bytes(self, path: Path) -> bytes:
        try:
            mode = path.lstat()
        except FileNotFoundError as error:
            raise ResearchArtifactError("missing_artifact", path) from error
        owner_file = (
            path.is_file() and not path.is_symlink()
            and mode.st_mode & 0o777 == 0o600
        )
        codec.require(owner_file, "artifact_not_owner_only", path)
        return path.read_bytes()

    def _same(self, path: Path, raw: bytes) -> bool:
        if not path.exists() and not path.is_symlink():
            return False
        codec.require(self._bytes(path) == raw, "conflicting_bytes", path)
        return True

    def _write(
        self, path: Path, raw: bytes, artifact_id: str, kind: str,
        plan: PlanSnapshot | None = None,
    ) -> ArtifactPointer:
        if not self._same(path, raw):
            token = secrets.token_hex(8)
            temp = path.with_name(
                f".{path.name}.research-artifact-{token}.tmp"
            )
            descriptor = os.open(
                temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600
            )
            try:
                os.fchmod(descriptor, 0o600)
                with os.fdopen(descriptor, "wb") as handle:
                    handle.write(raw)
                    handle.flush()
                    os.fsync(handle.fileno())
                try:
                    os.link(temp, path)
                except FileExistsError:
                    self._same(path, raw)
                else:
                    temp.unlink()
                    directory = os.open(
                        self.job_dir,
                        os.O_RDONLY | getattr(os, "O_DIRECTORY", 0),
                    )
                    try:
                        os.fsync(directory)
                    finally:
                        os.close(directory)
            finally:
                temp.unlink(missing_ok=True)
        pointer = ArtifactPointer(artifact_id, codec.content_hash(raw), path)
        _record(self.provenance, kind, pointer, plan)
        return pointer

    def cleanup_owned_temps(self) -> int:
        paths = tuple(self.job_dir.glob(".*.research-artifact-*.tmp"))
        for path in paths:
            path.unlink(missing_ok=True)
        return len(paths)

    def _numbered(
        self, pattern: re.Pattern[str], prefix: str,
    ) -> tuple[tuple[int, Path], ...]:
        numbered: list[tuple[int, Path]] = []
        for path in self.job_dir.iterdir():
            match = pattern.fullmatch(path.name)
            if match is not None:
                numbered.append((int(match.group(1)), path))
            elif path.name.startswith(prefix) and path.name.endswith(".json"):
                raise ResearchArtifactError("invalid_artifact_filename", path)
        return tuple(sorted(numbered))

    def _spec(self) -> tuple[ResearchSpec, ArtifactPointer]:
        path, raw = self.job_dir / SPEC_NAME, self._bytes(self.job_dir / SPEC_NAME)
        try:
            spec = research_spec.parse_research_spec(raw)
        except research_spec.ResearchSpecParseError as error:
            raise ResearchArtifactError("invalid_spec", path) from error
        codec.require(raw == research_spec.canonical_research_spec(spec),
                 "conflicting_bytes", path)
        return spec, ArtifactPointer(spec.spec_id, codec.content_hash(raw), path)

    def _plans(self, spec: ResearchSpec) -> tuple[PlanSnapshot, ...]:
        numbered = self._numbered(_PLAN_RE, "research-plan-")
        codec.require(bool(numbered), "missing_plan", self.job_dir)
        versions = tuple(number for number, _path in numbered)
        codec.require(versions[0] == 1, "orphan_successor", numbered[0][1])
        expected_versions = tuple(range(1, len(versions) + 1))
        codec.require(versions == expected_versions, "version_gap", self.job_dir)
        spec_hash = research_spec.research_spec_hash(spec)
        plans: list[PlanSnapshot] = []
        for number, path in numbered:
            raw = self._bytes(path)
            try:
                plan = research_plan.parse_canonical_plan(raw)
            except research_plan.PlanTransitionError as error:
                try:
                    research_plan.parse_canonical_plan(raw.strip())
                except research_plan.PlanTransitionError:
                    raise ResearchArtifactError("invalid_plan", path) from error
                raise ResearchArtifactError("conflicting_bytes", path) from error
            codec.require(plan.plan_version == number, "version_gap", path)
            binding = plan.spec_id, plan.spec_hash
            codec.require(binding == (spec.spec_id, spec_hash), "stale_spec_hash", path)
            if plans:
                prior = plans[-1]
                parent_ids = {item.plan_id for item in plans}
                codec.require(plan.parent_plan_id in parent_ids, "missing_parent", path)
                codec.require(
                    plan.parent_plan_id == prior.plan_id,
                    "orphan_successor", path,
                )
            plans.append(plan)
        lineage = tuple(plans)
        _validate_lineage(lineage, self.job_dir)
        return lineage

    def _assessments(
        self, spec: ResearchSpec, plans: tuple[PlanSnapshot, ...],
    ) -> tuple[tuple[ArtifactPointer, ...], ArtifactPointer | None]:
        by_version = {plan.plan_version: plan for plan in plans}
        acquisitions = tuple(
            _assessment(
                path, "research_acquisition", self._bytes(path),
                by_version.get(number), spec.spec_id, number,
            )
            for number, path in self._numbered(_ACQ_RE, "research-acquisition-")
        )
        path = self.job_dir / POST_NAME
        if not path.exists() and not path.is_symlink():
            return acquisitions, None
        current = plans[-1]
        post = _assessment(
            path, "post_extraction_assessment", self._bytes(path),
            current, spec.spec_id, current.plan_version,
        )
        return acquisitions, post

    def write_spec(self, spec: ResearchSpec) -> ArtifactPointer:
        raw = research_spec.canonical_research_spec(spec)
        return self._write(
            self.job_dir / SPEC_NAME, raw, spec.spec_id, "research_spec"
        )

    def write_plan(self, plan: PlanSnapshot) -> ArtifactPointer:
        spec, _pointer = self._spec()
        numbered = self._numbered(_PLAN_RE, "research-plan-")
        existing = self._plans(spec) if numbered else ()
        path = self.job_dir / f"research-plan-{plan.plan_version:04d}.json"
        raw = research_plan.canonical_plan_json(plan).encode()
        if not path.exists():
            _validate_lineage((*existing, plan), path)
        return self._write(path, raw, plan.plan_id, "research_plan", plan)

    def _write_assessment(
        self, kind: str, plan: PlanSnapshot, payload: JsonObject,
    ) -> ArtifactPointer:
        replay = self.load()
        valid = plan in replay.plans and (
            kind != "post_extraction_assessment" or plan == replay.plans[-1]
        )
        codec.require(valid, "stale_assessment", self.job_dir)
        raw, artifact_id = codec.bound_artifact_bytes(kind, plan, payload)
        name = (
            f"research-acquisition-{plan.plan_version:04d}.json"
            if kind == "research_acquisition"
            else POST_NAME
        )
        return self._write(self.job_dir / name, raw, artifact_id, kind, plan)

    def write_acquisition(
        self, plan: PlanSnapshot, payload: JsonObject,
    ) -> ArtifactPointer:
        return self._write_assessment("research_acquisition", plan, payload)

    def write_post_extraction(
        self, plan: PlanSnapshot, payload: JsonObject,
    ) -> ArtifactPointer:
        return self._write_assessment("post_extraction_assessment", plan, payload)

    def load(self) -> ResearchReplay:
        self.cleanup_owned_temps()
        spec, spec_pointer = self._spec()
        plans = self._plans(spec)
        acquisitions, post = self._assessments(spec, plans)
        root: JsonObject = {
            "spec": spec_pointer.content_hash,
            "plans": [
                codec.content_hash(research_plan.canonical_plan_json(plan).encode())
                for plan in plans
            ],
            "acquisitions": [item.content_hash for item in acquisitions],
            "post_extraction": None if post is None else post.content_hash,
        }
        root_hash = codec.content_hash(codec.canonical_json(root))
        return ResearchReplay(spec, plans, acquisitions, post, root_hash)
