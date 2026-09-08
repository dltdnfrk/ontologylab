from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from pathlib import Path

from ontologylab.research_artifact_types import (
    ArtifactPointer,
    ResearchArtifactError,
    ResearchArtifactPointers,
)
from ontologylab.research_plan import PlanSnapshot
from ontologylab.research_spec import JsonObject, JsonValue

_ARTIFACT_SCHEMA = "research-artifact-v1"
_JOB_POINTER_SCHEMA = "research-job-pointers-v1"
_ID_RE = re.compile(r"sha256:[0-9a-f]{64}")
_POINTER_ERROR_PATH = Path("runs.ask_json")


def canonical_json(value: JsonObject) -> bytes:
    text = json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return unicodedata.normalize("NFC", text).encode()


def content_hash(raw: bytes) -> str:
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def require(condition: bool, code: str, path: Path) -> None:
    if not condition:
        raise ResearchArtifactError(code, path)


def _object(raw: str | bytes, path: Path) -> JsonObject:
    try:
        value: JsonValue = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ResearchArtifactError("invalid_json", path) from error
    if isinstance(value, dict):
        return value
    raise ResearchArtifactError("expected_object", path)


def _artifact_id(value: JsonValue, path: Path, code: str) -> str:
    if isinstance(value, str) and _ID_RE.fullmatch(value) is not None:
        return value
    raise ResearchArtifactError(code, path)


def bound_artifact_bytes(
    kind: str,
    plan: PlanSnapshot,
    payload: JsonObject,
) -> tuple[bytes, str]:
    value: JsonObject = {
        "schema_version": _ARTIFACT_SCHEMA,
        "artifact_kind": kind,
        "spec_id": plan.spec_id,
        "spec_hash": plan.spec_hash,
        "plan_id": plan.plan_id,
        "plan_version": plan.plan_version,
        "payload": payload,
    }
    artifact_id = content_hash(canonical_json(value))
    value["artifact_id"] = artifact_id
    return canonical_json(value), artifact_id


def parse_bound_artifact(
    path: Path,
    kind: str,
    raw: bytes,
) -> tuple[ArtifactPointer, str, str, str, int]:
    value = _object(raw, path)
    fields = {
        "schema_version",
        "artifact_kind",
        "artifact_id",
        "spec_id",
        "spec_hash",
        "plan_id",
        "plan_version",
        "payload",
    }
    require(
        value.keys() == fields
        and value["schema_version"] == _ARTIFACT_SCHEMA
        and value["artifact_kind"] == kind
        and isinstance(value["payload"], dict),
        "invalid_schema",
        path,
    )
    artifact_id = _artifact_id(value["artifact_id"], path, "invalid_hash")
    identity: JsonObject = {
        key: item for key, item in value.items() if key != "artifact_id"
    }
    require(
        artifact_id == content_hash(canonical_json(identity)),
        "invalid_hash",
        path,
    )
    require(raw == canonical_json(value), "conflicting_bytes", path)
    version = value["plan_version"]
    if isinstance(version, bool) or not isinstance(version, int) or version < 1:
        raise ResearchArtifactError("invalid_schema", path)
    return (
        ArtifactPointer(artifact_id, content_hash(raw), path),
        _artifact_id(value["spec_id"], path, "invalid_schema"),
        _artifact_id(value["spec_hash"], path, "invalid_schema"),
        _artifact_id(value["plan_id"], path, "invalid_schema"),
        version,
    )


def _pointer_id(value: JsonValue) -> str:
    return _artifact_id(value, _POINTER_ERROR_PATH, "invalid_job_pointers")


def _pointer_ids(value: JsonValue, *, required: bool) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise ResearchArtifactError("invalid_job_pointers", _POINTER_ERROR_PATH)
    result = tuple(_pointer_id(item) for item in value)
    if (required and not result) or len(set(result)) != len(result):
        raise ResearchArtifactError("invalid_job_pointers", _POINTER_ERROR_PATH)
    return result


def encode_job_pointer_snapshot(
    ask: str | None,
    pointers: ResearchArtifactPointers | None,
) -> str | None:
    if pointers is None:
        return ask
    body: JsonObject = {
        "root_hash": pointers.root_hash,
        "spec_id": pointers.spec_id,
        "plan_ids": list(pointers.plan_ids),
        "acquisition_ids": list(pointers.acquisition_ids),
        "post_extraction_id": pointers.post_extraction_id,
        "current_plan_id": pointers.current_plan_id,
        "current_plan_version": pointers.current_plan_version,
    }
    value: JsonObject = {
        "schema_version": _JOB_POINTER_SCHEMA,
        "ask": ask,
        "research_artifacts": body,
    }
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def decode_job_pointer_snapshot(
    raw: str | None,
) -> tuple[str | None, ResearchArtifactPointers | None]:
    if raw is None:
        return None, None
    try:
        value: JsonValue = json.loads(raw)
    except json.JSONDecodeError:
        return raw, None
    if (
        not isinstance(value, dict)
        or value.get("schema_version") != _JOB_POINTER_SCHEMA
    ):
        return raw, None
    body = value.get("research_artifacts")
    if (
        value.keys() != {"schema_version", "ask", "research_artifacts"}
        or not isinstance(body, dict)
    ):
        raise ResearchArtifactError("invalid_job_pointers", _POINTER_ERROR_PATH)
    fields = {
        "root_hash",
        "spec_id",
        "plan_ids",
        "acquisition_ids",
        "post_extraction_id",
        "current_plan_id",
        "current_plan_version",
    }
    if body.keys() != fields:
        raise ResearchArtifactError("invalid_job_pointers", _POINTER_ERROR_PATH)
    plans = _pointer_ids(body.get("plan_ids"), required=True)
    acquisitions = _pointer_ids(body.get("acquisition_ids"), required=False)
    post = body.get("post_extraction_id")
    if post is not None:
        post = _pointer_id(post)
    version = body.get("current_plan_version")
    if isinstance(version, bool) or not isinstance(version, int) or version < 1:
        raise ResearchArtifactError("invalid_job_pointers", _POINTER_ERROR_PATH)
    ask = value.get("ask")
    if ask is not None and not isinstance(ask, str):
        raise ResearchArtifactError("invalid_job_pointers", _POINTER_ERROR_PATH)
    pointers = ResearchArtifactPointers(
        _pointer_id(body.get("root_hash")),
        _pointer_id(body.get("spec_id")),
        plans,
        acquisitions,
        post,
        _pointer_id(body.get("current_plan_id")),
        version,
    )
    if plans[-1] != pointers.current_plan_id or len(plans) != version:
        raise ResearchArtifactError("invalid_job_pointers", _POINTER_ERROR_PATH)
    return ask, pointers
