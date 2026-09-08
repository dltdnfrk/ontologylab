"""Strict fixture inventory for the research evaluation matrix."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Literal, TypeAlias, assert_never

from ontologylab.research_spec import JsonObject, JsonValue

FieldKind: TypeAlias = Literal[
    "string", "nullable_string", "boolean", "object"
]

FILES = {
    "controlled_omission": ("controlled-omission.jsonl", 24),
    "paired_parity": ("chat-direct-parity.jsonl", 40),
    "interaction": ("interaction-policy.jsonl", 60),
    "crash_replay": ("crash-replay.jsonl", 12),
    "source_eligibility": ("source-eligibility.jsonl", 18),
}
REPLAY_OUTCOMES = {
    "valid_root_reload": ("canonical_reload", None),
    "valid_broaden_reload": ("canonical_reload", None),
    "interrupted_running_job": ("interrupted", None),
    "partial_temp_file": ("canonical_reload", None),
    "missing_parent": ("refused", "missing_parent"),
    "version_gap": ("refused", "version_gap"),
    "stale_spec_hash": ("refused", "stale_spec_hash"),
    "same_id_different_bytes": ("refused", "conflicting_bytes"),
    "duplicate_semantic_execution": ("refused", "duplicate_execution"),
    "orphan_successor": ("refused", "orphan_successor"),
    "stale_assessment": ("refused", "stale_assessment"),
    "valid_retry_reload": ("canonical_reload", None),
}
_SCHEMAS: dict[str, dict[str, FieldKind]] = {
    "controlled_omission": {
        "id": "string",
        "mandatory_need_kind": "string",
        "corpus_state": "string",
        "remaining_axis": "boolean",
        "broaden_available": "boolean",
        "expected_recommendation": "string",
        "expected_stop_reason": "nullable_string",
    },
    "paired_parity": {
        "id": "string",
        "direct_topic": "string",
        "chat_topic": "string",
        "expected_normalized_goal": "string",
        "direct_controls": "object",
    },
    "interaction": {
        "id": "string",
        "origin": "string",
        "ambiguity_kind": "string",
        "expected_decision": "string",
        "expected_job_started": "boolean",
    },
    "crash_replay": {
        "id": "string",
        "scenario": "string",
        "expected_result": "string",
        "expected_error_code": "nullable_string",
    },
    "source_eligibility": {
        "id": "string",
        "need_kind": "string",
        "content_kind": "string",
        "retracted": "boolean",
        "expected_eligible": "boolean",
    },
}


class EvaluationError(ValueError):
    pass


def _matches(value: JsonValue, kind: FieldKind) -> bool:
    match kind:
        case "string":
            return isinstance(value, str) and bool(value)
        case "nullable_string":
            return value is None or isinstance(value, str)
        case "boolean":
            return isinstance(value, bool)
        case "object":
            return isinstance(value, dict)
        case _ as unreachable:
            assert_never(unreachable)


def load_research_fixtures(fixture_dir: Path) -> dict[str, list[JsonObject]]:
    fixture_dir = Path(fixture_dir)
    expected_names = {item[0] for item in FILES.values()}
    try:
        actual_names = {
            path.name for path in fixture_dir.iterdir() if path.is_file()
        }
    except OSError as error:
        raise EvaluationError("fixture_directory_unreadable") from error
    if actual_names != expected_names:
        raise EvaluationError("fixture_inventory_mismatch")
    result: dict[str, list[JsonObject]] = {}
    ids: set[str] = set()
    for key, (name, count) in FILES.items():
        try:
            rows = [
                json.loads(line)
                for line in (fixture_dir / name).read_text(
                    encoding="utf-8"
                ).splitlines()
            ]
        except (OSError, UnicodeError, json.JSONDecodeError) as error:
            raise EvaluationError(f"fixture_parse_error:{name}") from error
        schema = _SCHEMAS[key]
        if len(rows) != count:
            raise EvaluationError(f"fixture_count_mismatch:{name}")
        validated: list[JsonObject] = []
        for index, row in enumerate(rows, start=1):
            if not isinstance(row, dict) or set(row) != set(schema):
                raise EvaluationError(f"fixture_schema_mismatch:{name}:{index}")
            if any(not _matches(row[field], kind) for field, kind in schema.items()):
                raise EvaluationError(f"fixture_type_mismatch:{name}:{index}")
            case_id = str(row["id"])
            if case_id in ids:
                raise EvaluationError(f"fixture_duplicate_id:{case_id}")
            ids.add(case_id)
            validated.append(row)
        result[key] = validated
    return result
