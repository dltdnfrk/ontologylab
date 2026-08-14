"""Strict bounded declarative Method replay and denominator receipts."""

from __future__ import annotations

from dataclasses import dataclass
import unicodedata
from typing import Any, Iterable, Mapping, cast

from ontologylab.method_compiler_contract import (
    COMPILER_REPLAY_KINDS,
    CompilationGateResult,
    CompilerReplayKindCount,
    CompilerReplayResult,
    GateId,
    replay_receipt_hash,
)
from ontologylab.method_compiler_gates import canonical_hash, gate_result
from ontologylab.method_ir import canonical_json_bytes


REPLAY_KINDS = COMPILER_REPLAY_KINDS
MAX_REPLAY_BYTES = 65_536
MAX_REPLAY_FIXTURES = 256
MAX_REPLAY_ID_BYTES = 128
MAX_REPLAY_POINTER_TOKENS = 64
MAX_REPLAY_ROWS = 1_000
MAX_REPLAY_VALUE_DEPTH = 64


@dataclass(frozen=True, slots=True)
class ReplayReceipt:
    fixture_set_hash: str
    fixture_count: int
    result_count: int
    kind_counts: tuple[CompilerReplayKindCount, ...]
    results: tuple[CompilerReplayResult, ...]
    receipt_hash: str


def _exact_json_equal(left: object, right: object) -> bool:
    if type(left) is not type(right):
        return False
    if isinstance(left, dict):
        return (
            left.keys() == cast(dict[object, object], right).keys()
            and all(
                _exact_json_equal(
                    item,
                    cast(dict[object, object], right)[key],
                )
                for key, item in left.items()
            )
        )
    if isinstance(left, list):
        other = cast(list[object], right)
        return len(left) == len(other) and all(
            _exact_json_equal(item, other[index])
            for index, item in enumerate(left)
        )
    return left == right


def _pointer(value: object, path: str) -> tuple[bool, object]:
    current = value
    for token in path.split("/")[1:]:
        token = token.replace("~1", "/").replace("~0", "~")
        if isinstance(current, dict) and token in current:
            current = current[token]
        else:
            return False, None
    return True, current


def _query(
    method: Mapping[str, Any],
    request: Mapping[str, Any],
) -> tuple[bool, object]:
    exists, value = _pointer(method, cast(str, request["path"]))
    if not exists:
        return False, None
    if request["op"] == "get":
        return True, value
    if not isinstance(value, list):
        return False, None
    where = cast(Mapping[str, Any], request["where"])
    rows = [
        row
        for row in value
        if isinstance(row, dict)
        and all(
            key in row
            and _exact_json_equal(row[key], item)
            for key, item in where.items()
        )
    ]
    if not rows:
        return True, None
    return _pointer(rows[0], cast(str, request["field"]))


def _fixture_result(
    method: Mapping[str, Any],
    fixture: Mapping[str, Any],
) -> CompilerReplayResult:
    fixture_id = cast(str, fixture["id"])
    kind = cast(str, fixture["kind"])
    found, actual = _query(
        method,
        cast(Mapping[str, Any], fixture["query"]),
    )
    if kind == "expected_output":
        passed = found and _exact_json_equal(
            actual,
            fixture.get("expected"),
        )
    elif kind == "expected_error":
        passed = not found
    elif kind == "expected_no_output":
        passed = found and actual is None
    else:
        passed = not found or (
            isinstance(actual, dict)
            and actual.get("state") == "unknown"
        )
    return CompilerReplayResult(fixture_id, kind, passed)


def _depth_and_rows(value: object) -> tuple[int, int]:
    maximum = 0
    row_count = 0
    stack: list[tuple[object, int]] = [(value, 0)]
    while stack:
        current, depth = stack.pop()
        maximum = max(maximum, depth)
        if isinstance(current, (list, tuple)):
            if isinstance(current, list):
                row_count = max(row_count, len(current))
            stack.extend((item, depth + 1) for item in current)
        elif isinstance(current, dict):
            stack.extend((item, depth + 1) for item in current.values())
    return maximum, row_count


def _valid_pointer(value: object) -> bool:
    if not isinstance(value, str) or not value.startswith("/"):
        return False
    tokens = value[1:].split("/")
    if len(tokens) > MAX_REPLAY_POINTER_TOKENS:
        return False
    return all(
        all(
            token[index] != "~"
            or (
                index + 1 < len(token)
                and token[index + 1] in {"0", "1"}
            )
            for index in range(len(token))
        )
        for token in tokens
    )


def _fixture_valid(value: object) -> bool:
    if not isinstance(value, dict):
        return False
    if set(value) - {"id", "kind", "query", "expected"}:
        return False
    fixture_id = value.get("id")
    kind = value.get("kind")
    query = value.get("query")
    if (
        not isinstance(fixture_id, str)
        or not fixture_id
        or kind not in REPLAY_KINDS
        or not isinstance(query, dict)
        or set(query) - {"op", "path", "where", "field"}
    ):
        return False
    operation = query.get("op")
    if operation not in {"get", "select"} or not _valid_pointer(
        query.get("path")
    ):
        return False
    if operation == "get":
        return set(query) == {"op", "path"}
    return (
        set(query) == {"op", "path", "where", "field"}
        and isinstance(query.get("where"), dict)
        and isinstance(query.get("field"), str)
        and _valid_pointer(query["field"])
    )


def _validate(
    fixtures: Iterable[Mapping[str, Any]],
    method: Mapping[str, Any],
) -> tuple[tuple[Mapping[str, Any], ...], str | None]:
    try:
        rows = tuple(fixtures)
    except TypeError:
        return (), "invalid-replay-fixture"
    if len(rows) > MAX_REPLAY_FIXTURES:
        return (), "replay-limit-exceeded"
    if any(
        isinstance(row, dict)
        and isinstance(row.get("query"), dict)
        and any(
            isinstance(row["query"].get(field), str)
            and row["query"][field].startswith("/")
            and len(row["query"][field][1:].split("/"))
            > MAX_REPLAY_POINTER_TOKENS
            for field in ("path", "field")
        )
        for row in rows
    ):
        return (), "replay-limit-exceeded"
    depth, row_count = _depth_and_rows((rows, method))
    if depth > MAX_REPLAY_VALUE_DEPTH or row_count > MAX_REPLAY_ROWS:
        return (), "replay-limit-exceeded"
    try:
        if len(canonical_json_bytes(rows)) > MAX_REPLAY_BYTES:
            return (), "replay-limit-exceeded"
    except (RecursionError, TypeError, ValueError):
        return (), "replay-limit-exceeded"
    if any(
        isinstance(row, dict)
        and isinstance(row.get("id"), str)
        and len(row["id"].encode()) > MAX_REPLAY_ID_BYTES
        for row in rows
    ):
        return (), "replay-limit-exceeded"
    if any(not _fixture_valid(row) for row in rows):
        return (), "invalid-replay-fixture"
    identities = tuple(
        unicodedata.normalize("NFC", cast(str, row["id"]))
        for row in rows
    )
    if len(identities) != len(set(identities)):
        return (), "invalid-replay-fixture"
    return rows, None


def _receipt(
    ordered: tuple[Mapping[str, Any], ...],
    results: tuple[CompilerReplayResult, ...],
) -> ReplayReceipt:
    fixture_set_hash = canonical_hash(list(ordered))
    kind_counts = tuple(
        CompilerReplayKindCount(
            kind,
            sum(result.kind == kind for result in results),
            sum(
                result.kind == kind and result.passed
                for result in results
            ),
        )
        for kind in REPLAY_KINDS
    )
    receipt_hash = replay_receipt_hash(
        fixture_set_hash,
        len(ordered),
        len(results),
        kind_counts,
        results,
    )
    return ReplayReceipt(
        fixture_set_hash,
        len(ordered),
        len(results),
        kind_counts,
        results,
        receipt_hash,
    )


def evaluate_replay(
    method: Mapping[str, Any],
    fixtures: Iterable[Mapping[str, Any]],
) -> tuple[ReplayReceipt, CompilationGateResult]:
    validated, failure = _validate(fixtures, method)
    if failure is not None:
        return _receipt((), ()), gate_result(GateId.G7, (failure,))
    ordered = tuple(sorted(validated, key=lambda row: cast(str, row["id"])))
    results = tuple(_fixture_result(method, row) for row in ordered)
    kinds = {result.kind for result in results}
    reasons = [
        reason
        for kind, reason in (
            ("expected_error", "expected-error-omitted"),
            ("expected_no_output", "no-output-omitted"),
            ("unknown", "unknown-output-omitted"),
        )
        if kind not in kinds
    ]
    if any(not result.passed for result in results):
        reasons.append("fixture-failed")
    return _receipt(ordered, results), gate_result(GateId.G7, reasons)
