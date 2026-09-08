"""Deterministic validator for research contract characterization fixtures."""

from __future__ import annotations

import hashlib
import json
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Final, TypeAlias

JsonValue: TypeAlias = (
    str | int | float | bool | None | list["JsonValue"] | dict[str, "JsonValue"]
)
JsonObject: TypeAlias = dict[str, JsonValue]

_EXPECTED_COUNTS: Final = {
    "controlled-omission.jsonl": 24,
    "chat-direct-parity.jsonl": 40,
    "interaction-policy.jsonl": 60,
    "crash-replay.jsonl": 12,
    "source-eligibility.jsonl": 18,
}
_REQUIRED_FIELDS: Final[Mapping[str, frozenset[str]]] = {
    "controlled-omission.jsonl": frozenset(
        {
            "id",
            "mandatory_need_kind",
            "corpus_state",
            "remaining_axis",
            "broaden_available",
            "expected_recommendation",
            "expected_stop_reason",
        }
    ),
    "chat-direct-parity.jsonl": frozenset(
        {
            "id",
            "direct_topic",
            "chat_topic",
            "direct_controls",
            "expected_normalized_goal",
        }
    ),
    "interaction-policy.jsonl": frozenset(
        {
            "id",
            "origin",
            "ambiguity_kind",
            "expected_decision",
            "expected_job_started",
        }
    ),
    "crash-replay.jsonl": frozenset(
        {"id", "scenario", "expected_result", "expected_error_code"}
    ),
    "source-eligibility.jsonl": frozenset(
        {"id", "need_kind", "content_kind", "retracted", "expected_eligible"}
    ),
}
_ENUM_FIELDS: Final[Mapping[str, frozenset[str | None]]] = {
    "mandatory_need_kind": frozenset(
        {
            "general",
            "bibliographic_existence",
            "context",
            "mechanism",
            "method",
            "result",
            "safety",
            "trial",
        }
    ),
    "need_kind": frozenset(
        {
            "general",
            "bibliographic_existence",
            "context",
            "mechanism",
            "method",
            "result",
            "safety",
            "trial",
        }
    ),
    "content_kind": frozenset({"unknown", "metadata_only", "abstract", "fulltext"}),
    "corpus_state": frozenset({"empty", "metadata_only", "abstract_only", "partial_fulltext", "covered_fulltext"}),
    "expected_recommendation": frozenset({"extract", "broaden", "stop"}),
    "expected_stop_reason": frozenset({None, "budget_exhausted", "no_usable_source"}),
    "origin": frozenset({"chat", "direct_api"}),
    "ambiguity_kind": frozenset({"none", "multi_goal", "missing_topic", "unsafe_request", "unsupported_scope"}),
    "expected_decision": frozenset({"execute", "decompose", "clarify", "abstain"}),
    "expected_result": frozenset({"canonical_reload", "refused", "interrupted"}),
    "expected_error_code": frozenset(
        {
            None,
            "conflicting_bytes",
            "duplicate_execution",
            "missing_parent",
            "orphan_successor",
            "stale_assessment",
            "stale_spec_hash",
            "version_gap",
        }
    ),
}


@dataclass(frozen=True, slots=True)
class FixtureIssue:
    path: Path
    row: int
    field: str
    code: str

    def __str__(self) -> str:
        return f"{self.path}:{self.row}:{self.field}: {self.code}"


@dataclass(frozen=True, slots=True)
class FixtureValidationError(Exception):
    issues: tuple[FixtureIssue, ...]

    def __str__(self) -> str:
        return "\n".join(str(issue) for issue in self.issues)


@dataclass(frozen=True, slots=True)
class FixtureFileInventory:
    name: str
    count: int
    sha256: str


@dataclass(frozen=True, slots=True)
class FixtureInventory:
    files: tuple[FixtureFileInventory, ...]

    @property
    def counts(self) -> dict[str, int]:
        return {item.name: item.count for item in self.files}

    def as_json(self) -> str:
        payload = {
            "files": {
                item.name: {"count": item.count, "sha256": item.sha256}
                for item in self.files
            }
        }
        return json.dumps(
            payload,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )


def _read_rows(path: Path) -> tuple[tuple[JsonObject, ...], tuple[FixtureIssue, ...]]:
    rows: list[JsonObject] = []
    issues: list[FixtureIssue] = []
    for row_number, raw_line in enumerate(
        path.read_text(encoding="utf-8").splitlines(),
        start=1,
    ):
        try:
            value: JsonValue = json.loads(raw_line)
        except json.JSONDecodeError:
            issues.append(FixtureIssue(path, row_number, "$", "invalid_json"))
            continue
        if not isinstance(value, dict):
            issues.append(FixtureIssue(path, row_number, "$", "expected_object"))
            continue
        rows.append(value)
    return tuple(rows), tuple(issues)


def _validate_rows(
    path: Path,
    rows: tuple[JsonObject, ...],
    seen_ids: set[str] | None = None,
) -> tuple[FixtureIssue, ...]:
    issues: list[FixtureIssue] = []
    known_ids = set() if seen_ids is None else seen_ids
    required = _REQUIRED_FIELDS[path.name]
    for row_number, row in enumerate(rows, start=1):
        for field in sorted(required - row.keys()):
            issues.append(FixtureIssue(path, row_number, field, "missing_field"))
        fixture_id = row.get("id")
        if not isinstance(fixture_id, str) or not fixture_id:
            issues.append(FixtureIssue(path, row_number, "id", "invalid_id"))
        elif fixture_id in known_ids:
            issues.append(FixtureIssue(path, row_number, "id", "duplicate_id"))
        else:
            known_ids.add(fixture_id)
        for field, allowed in _ENUM_FIELDS.items():
            if field in row and row[field] not in allowed:
                issues.append(FixtureIssue(path, row_number, field, "invalid_enum"))
        for field in ("broaden_available", "remaining_axis", "expected_job_started", "retracted", "expected_eligible"):
            if field in row and not isinstance(row[field], bool):
                issues.append(FixtureIssue(path, row_number, field, "expected_boolean"))
    return tuple(issues)


def load_fixture(path: Path) -> tuple[JsonObject, ...]:
    """Parse and validate one approved fixture file."""
    rows, parse_issues = _read_rows(path)
    issues = (*parse_issues, *_validate_rows(path, rows))
    expected_count = _EXPECTED_COUNTS[path.name]
    if len(rows) != expected_count:
        issues = (*issues, FixtureIssue(path, 0, "$", "invalid_count"))
    if issues:
        raise FixtureValidationError(issues)
    return rows


def build_inventory(fixture_dir: Path) -> FixtureInventory:
    """Parse all approved fixtures and return a byte-derived inventory."""
    issues: list[FixtureIssue] = []
    files: list[FixtureFileInventory] = []
    seen_ids: set[str] = set()
    if not fixture_dir.is_dir():
        raise FixtureValidationError(
            (FixtureIssue(fixture_dir, 0, "$", "missing_directory"),)
        )
    approved_names = _EXPECTED_COUNTS.keys()
    for entry in sorted(fixture_dir.iterdir(), key=lambda path: path.name):
        if entry.name not in approved_names:
            code = "unexpected_directory" if entry.is_dir() else "unexpected_file"
            issues.append(FixtureIssue(entry, 0, "$", code))
    for name, expected_count in sorted(_EXPECTED_COUNTS.items()):
        path = fixture_dir / name
        if not path.is_file():
            issues.append(FixtureIssue(path, 0, "$", "missing_file"))
            continue
        rows, parse_issues = _read_rows(path)
        issues.extend(parse_issues)
        issues.extend(_validate_rows(path, rows, seen_ids))
        if len(rows) != expected_count:
            issues.append(FixtureIssue(path, 0, "$", "invalid_count"))
        files.append(
            FixtureFileInventory(
                name=name,
                count=len(rows),
                sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
            )
        )
    if issues:
        raise FixtureValidationError(tuple(issues))
    return FixtureInventory(tuple(files))


def main(argv: list[str] | None = None) -> int:
    arguments = sys.argv[1:] if argv is None else argv
    if len(arguments) != 1:
        sys.stderr.write("fixture-dir:0:$: expected_one_directory\n")
        return 2
    try:
        inventory = build_inventory(Path(arguments[0]))
    except FixtureValidationError as error:
        sys.stderr.write(f"{error}\n")
        return 2
    sys.stdout.write(f"{inventory.as_json()}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
