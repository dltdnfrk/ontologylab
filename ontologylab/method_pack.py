"""Validated, explicit Method release publication into a Knowledge Pack."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping, Protocol, Sequence

from ontologylab.method_pack_contract import (
    COMPILER_VERSION,
    PUBLICATION_SCHEMA_VERSION,
    SCHEMA_VERSION,
    MethodPackError,
    MethodPackSelection,
)
from ontologylab.method_pack_rows import (
    method_row,
    source_rows as release_source_rows,
)
from ontologylab.method_pack_sql import MethodPackSql as MethodPackSql
from ontologylab.method_pack_validation import (
    copied_row_hashes,
    validate_method_pack as validate_method_pack,
)
from ontologylab.method_release_validation import canonical_release_envelope
from ontologylab.method_snapshot import (
    canonical_compiler_receipt,
    compiler_receipt_from_json,
)
from ontologylab.method_validation import canonical_json
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class _Release:
    values: tuple[Any, ...]
    method: Mapping[str, Any]
    sources: tuple[Mapping[str, Any], ...]
    receipt_json: str


class MethodPackPersistence(Protocol):
    def release(self, release_id: str) -> Sequence[Any] | None:
        ...

    def gates(self, attempt_id: str) -> Sequence[Sequence[Any]]:
        ...

    def attempt(self, attempt_id: str) -> Sequence[Any] | None:
        ...

    def snapshot_hash(self, workspace_id: str) -> str:
        ...

    def source_snapshot_hash(self) -> str:
        ...

    def validate_source(
        self,
        workspace_id: str,
        source: Mapping[str, Any],
    ) -> tuple[str, str, str, str]: ...

    def validate_policy_snapshot(
        self,
        workspace_id: str,
        snapshot_id: str,
        policy_version: str,
    ) -> None: ...

    def accepted_object_hashes(
        self,
        workspace_id: str,
        object_id: str,
    ) -> tuple[str, str]: ...

    def create_tables(self) -> None:
        ...

    def insert_releases(self, rows: Sequence[Sequence[Any]]) -> None:
        ...

    def insert_sources(self, rows: Sequence[Sequence[Any]]) -> None:
        ...

    def insert_publication_receipt(
        self,
        receipt_json: str,
        receipt_hash: str,
    ) -> None: ...


def reject_duplicate_release_ids(release_ids: Sequence[str]) -> tuple[str, ...]:
    seen: set[str] = set()
    for release_id in release_ids:
        if release_id in seen:
            raise MethodPackError(
                f"duplicate method release id {release_id!r}"
            )
        seen.add(release_id)
    return tuple(sorted(release_ids))


def _hash(value: object) -> str:
    payload = canonical_json(value).encode("utf-8")
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _object(value: object, label: str) -> Mapping[str, Any]:
    if not isinstance(value, dict):
        raise MethodPackError(f"{label} must be a JSON object")
    return value


def _sources(value: str) -> tuple[Mapping[str, Any], ...]:
    try:
        parsed = json.loads(value)
    except (TypeError, json.JSONDecodeError) as exc:
        raise MethodPackError("source index is not canonical JSON") from exc
    if not isinstance(parsed, list):
        raise MethodPackError("source index must be a JSON array")
    rows = tuple(
        _object(row, "source index row")
        for row in parsed
    )
    if len({str(row.get("id")) for row in rows}) != len(rows):
        raise MethodPackError("duplicate source order in release")
    return rows


def _release(
    persistence: MethodPackPersistence,
    release_id: str,
) -> _Release:
    row = persistence.release(release_id)
    if row is None:
        raise MethodPackError(f"unknown Method release {release_id!r}")
    values = tuple(row)
    try:
        method = _object(json.loads(str(values[4])), "Method JSON")
        sources = _sources(str(values[5]))
        receipt = compiler_receipt_from_json(str(values[11]))
        if receipt is None:
            raise MethodPackError("compiler receipt is not canonical")
        envelope = canonical_release_envelope(method, sources, receipt)
        canonical = canonical_compiler_receipt(envelope.receipt)
    except MethodPackError:
        raise
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise MethodPackError(
            f"release {release_id!r} is not canonical"
        ) from exc
    if (
        values[0] != release_id
        or values[2] != method.get("id")
        or values[3] != envelope.receipt.release_version
        or values[3] != method.get("version")
        or values[4] != envelope.method_json
        or values[5] != envelope.source_index
        or values[6] != envelope.content_hash
        or values[7] != COMPILER_VERSION
        or values[7] != envelope.receipt.compiler_version
        or values[8] != envelope.receipt.input_snapshot_hash
        or values[9] != canonical.gate_summary_json
        or values[10] != canonical_json(json.loads(str(values[10])))
        or values[11] != canonical.json
        or values[12] != canonical.receipt_hash
        or values[13] != envelope.receipt.attempt_id
        or not envelope.receipt.passed
    ):
        raise MethodPackError(f"release {release_id!r} binding is invalid")
    if _hash(json.loads(str(values[10]))) != (
        envelope.receipt.reviewer_receipt_hash
    ):
        raise MethodPackError(
            f"release {release_id!r} reviewer receipt is stale"
        )
    gate_rows = tuple(
        (
            str(gate_id),
            int(passed),
            str(reasons),
            str(receipt_hash),
            str(receipt_json),
        )
        for gate_id, passed, reasons, receipt_hash, receipt_json
        in persistence.gates(str(values[13]))
    )
    expected = tuple(
        (
            gate.gate_id.value,
            int(gate.passed),
            canonical_json(gate.reasons),
            canonical.receipt_hash,
            canonical.json,
        )
        for gate in envelope.receipt.gates
    )
    if gate_rows != expected or len(gate_rows) != 9:
        raise MethodPackError(f"release {release_id!r} gate rows are invalid")
    attempt = persistence.attempt(str(values[13]))
    if attempt is None or tuple(attempt) != (
        1,
        values[0],
        values[1],
        values[7],
        values[8],
        values[9],
        values[11],
        values[12],
    ):
        raise MethodPackError(f"release {release_id!r} attempt is stale")
    source_bindings = tuple(
        persistence.validate_source(str(values[1]), source)
        for source in sources
    )
    accepted = {
        item.object_id: (item.row_hash, item.input_hash)
        for item in envelope.receipt.accepted_objects
    }
    for source, (_, _, row_hash, input_hash) in zip(
        sources,
        source_bindings,
        strict=True,
    ):
        if accepted.get(str(source["occurrence_id"])) != (
            row_hash,
            input_hash,
        ):
            raise MethodPackError(
                f"release {release_id!r} source receipt is stale"
            )
    for item in envelope.receipt.accepted_objects:
        if persistence.accepted_object_hashes(
            str(values[1]),
            item.object_id,
        ) != (item.row_hash, item.input_hash):
            raise MethodPackError(
                f"release {release_id!r} accepted object is stale"
            )
    for policy in envelope.receipt.policy_snapshots:
        persistence.validate_policy_snapshot(
            str(values[1]),
            policy.snapshot_id,
            policy.policy_version,
        )
    used_policies = {
        (snapshot_id, policy_version)
        for snapshot_id, policy_version, _, _ in source_bindings
    }
    receipt_policies = {
        (policy.snapshot_id, policy.policy_version)
        for policy in envelope.receipt.policy_snapshots
    }
    if not used_policies <= receipt_policies:
        raise MethodPackError(
            f"release {release_id!r} policy receipt is stale"
        )
    if persistence.snapshot_hash(str(values[1])) != values[8]:
        raise MethodPackError(
            f"release {release_id!r} source or policy snapshot is stale"
        )
    return _Release(values, method, sources, canonical.json)


def copy_method_releases(
    persistence: MethodPackPersistence,
    release_ids: Sequence[str],
) -> MethodPackSelection:
    ordered = reject_duplicate_release_ids(release_ids)
    if not ordered:
        return MethodPackSelection((), (), "", "", "", "", "", "")
    releases = tuple(_release(persistence, release_id) for release_id in ordered)
    method_ids = tuple(str(release.values[2]) for release in releases)
    if len(set(method_ids)) != len(method_ids):
        raise MethodPackError("selection contains multiple releases for one method")
    releases = tuple(sorted(
        releases,
        key=lambda release: (str(release.values[2]), str(release.values[0])),
    ))
    method_rows = tuple(
        method_row(release.values, release.method, release.receipt_json)
        for release in releases
    )
    source_rows = tuple(
        row
        for release in releases
        for row in release_source_rows(release.values, release.sources)
    )
    method_hash, source_hash = copied_row_hashes(method_rows, source_rows)
    selection_rows = [
        {
            "method_id": str(release.values[2]),
            "release_id": str(release.values[0]),
            "release_content_hash": str(release.values[6]),
        }
        for release in releases
    ]
    compiler_snapshot_hashes = {str(release.values[8]) for release in releases}
    if len(compiler_snapshot_hashes) != 1:
        raise MethodPackError("selection spans multiple compiler snapshots")
    source_snapshot_hash = persistence.source_snapshot_hash()
    publication = {
        "schema_version": PUBLICATION_SCHEMA_VERSION,
        "method_schema_version": SCHEMA_VERSION,
        "compiler_version": COMPILER_VERSION,
        "source_snapshot_hash": source_snapshot_hash,
        "selection": selection_rows,
        "compiled_method_hash": method_hash,
        "compiled_method_source_hash": source_hash,
    }
    publication_json = canonical_json(publication)
    publication_hash = _hash(publication)
    persistence.create_tables()
    persistence.insert_releases(method_rows)
    persistence.insert_sources(source_rows)
    persistence.insert_publication_receipt(
        publication_json,
        publication_hash,
    )
    return MethodPackSelection(
        tuple(row["release_id"] for row in selection_rows),
        tuple(row["release_content_hash"] for row in selection_rows),
        _hash([json.loads(str(row[4])) for row in method_rows]),
        _hash([json.loads(str(row[5])) for row in method_rows]),
        _hash([json.loads(release.receipt_json)["gates"] for release in releases]),
        _hash([
            [row["release_id"], row["release_content_hash"]]
            for row in selection_rows
        ]),
        publication_hash,
        source_snapshot_hash,
    )


def methodology_manifest(
    selection: MethodPackSelection,
) -> dict[str, object]:
    return {
        "schema_version": SCHEMA_VERSION,
        "compiler_version": COMPILER_VERSION,
        "method_count": len(selection.release_ids),
        "selected_release_ids": list(selection.release_ids),
        "selected_release_hashes": dict(
            zip(selection.release_ids, selection.release_hashes, strict=True)
        ),
        "method_json_hash": selection.method_json_hash,
        "source_index_hash": selection.source_index_hash,
        "gate_receipt_hash": selection.gate_receipt_hash,
        "selection_input_hash": selection.selection_input_hash,
        "publication_receipt_hash": selection.publication_receipt_hash,
    }
