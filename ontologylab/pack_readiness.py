"""F11 generation-readiness and C-036 publication-authorization gate."""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum, unique
from typing import Final, NoReturn, TypeAlias, assert_never

from ontologylab.migration import (
    MIGRATION_PHASES,
    compute_source_fingerprint,
    phase_is_complete,
    read_ledger,
)
from ontologylab.pack_receipt_seal import (
    ReceiptSealCode,
    ReceiptSealRefused,
    seal_receipt_inventory,
)

UNREVIEWED_CAPABILITIES: Final = ("knowledge-graph-v2", "evidence-self-contained-v2")
REVIEWED_CAPABILITIES: Final = (*UNREVIEWED_CAPABILITIES, "reviewed", "sourced-answer-v2")
JsonValue: TypeAlias = (
    str | int | float | bool | None | list["JsonValue"] | dict[str, "JsonValue"]
)
C036_TABLE: Final = "c036_capability_receipts"
C036_DECISION: Final = "authorize"
_C036_SCOPES: Final = frozenset({"reviewed", "sourced"})


@unique
class PackReadinessCode(StrEnum):
    NOT_READY = "not_ready"
    MIGRATING = "migrating"
    INCOMPLETE_LEDGER = "incomplete_ledger"
    AMBIGUOUS_LEDGER = "ambiguous_ledger"
    GENERATION_DRIFT = "generation_drift"
    FINGERPRINT_MISMATCH = "fingerprint_mismatch"
    MISSING_RECEIPT = "missing_receipt"
    STALE_RECEIPT = "stale_receipt"
    C036_REQUIRED = "c036_required"
    C036_STALE = "c036_stale"


@unique
class PublicationScope(StrEnum):
    UNREVIEWED = "unreviewed"
    REVIEWED = "reviewed"
    SOURCED = "sourced"


@dataclass(frozen=True, slots=True)
class PackReadinessRefused(Exception):
    code: PackReadinessCode
    member: str

    def __str__(self) -> str:
        return f"{self.code}:{self.member}"


@dataclass(frozen=True, slots=True)
class ReceiptInventory:
    members: Mapping[str, tuple[str, ...]]
    root: str


@dataclass(frozen=True, slots=True)
class PackPublication:
    generation: int
    source_fingerprint: str
    receipt_inventory_root: str
    publication_scope: PublicationScope
    capabilities: tuple[str, ...]
    c036_receipt_id: str | None


def authorize_publication(
    conn: sqlite3.Connection, *, check_generation: int | None = None,
) -> PackPublication:
    """Refuse non-ready snapshots; authorize unreviewed or C-036 publication."""
    generation, fingerprint = _bound_ledger(conn, check_generation)
    inventory = receipt_inventory(conn)
    _refuse_stale_receipts(conn)
    receipt = _c036_row(conn)
    requested = _has_row(
        conn, "review_publication",
        "SELECT 1 FROM review_publication WHERE publication_class = 'sourced' LIMIT 1",
    )
    if requested and receipt is None:
        _refuse(PackReadinessCode.C036_REQUIRED, "c036")
    if receipt is not None and (
        int(receipt[1]) != generation
        or str(receipt[2]) != fingerprint
        or str(receipt[3]) != inventory.root
        or str(receipt[5]) != C036_DECISION
        or str(receipt[4]) not in _C036_SCOPES
    ):
        _refuse(PackReadinessCode.C036_STALE, "c036")
    if receipt is None:
        scope = PublicationScope.UNREVIEWED
        receipt_id = None
    elif requested or str(receipt[4]) == PublicationScope.SOURCED.value:
        scope = PublicationScope.SOURCED
        receipt_id = str(receipt[0])
    else:
        scope = PublicationScope.REVIEWED
        receipt_id = str(receipt[0])
    match scope:
        case PublicationScope.UNREVIEWED:
            capabilities = UNREVIEWED_CAPABILITIES
        case PublicationScope.REVIEWED | PublicationScope.SOURCED:
            capabilities = REVIEWED_CAPABILITIES
        case unreachable:
            assert_never(unreachable)
    return PackPublication(
        generation=generation, source_fingerprint=fingerprint,
        receipt_inventory_root=inventory.root, publication_scope=scope,
        capabilities=capabilities, c036_receipt_id=receipt_id,
    )


def receipt_inventory(conn: sqlite3.Connection) -> ReceiptInventory:
    """Canonical Step 7 receipt inventory and root for this snapshot."""
    try:
        sealed = seal_receipt_inventory(conn)
    except ReceiptSealRefused as refused:
        match refused.code:
            case ReceiptSealCode.STALE_RECEIPT:
                _refuse(PackReadinessCode.STALE_RECEIPT, refused.member)
            case ReceiptSealCode.MISSING_RECEIPT:
                _refuse(PackReadinessCode.MISSING_RECEIPT, refused.member)
            case unreachable:
                assert_never(unreachable)
    return ReceiptInventory(members=sealed.members, root=sealed.root)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m ontologylab.pack_readiness")
    parser.add_argument("kg")
    parser.add_argument("--check-generation", type=int, default=None)
    parser.add_argument("--publish", default=None)
    parser.add_argument("--name", default="pack")
    parser.add_argument("--evidence-mode", default="full")
    args = parser.parse_args(argv)
    connection = sqlite3.connect(args.kg)
    connection.row_factory = sqlite3.Row
    try:
        granted = authorize_publication(connection, check_generation=args.check_generation)
    except PackReadinessRefused as refused:
        _emit({"ok": False, "code": refused.code.value, "member": refused.member})
        return 2
    finally:
        connection.close()
    payload: dict[str, JsonValue] = {
        "ok": True, "generation": granted.generation,
        "source_fingerprint": granted.source_fingerprint,
        "receipt_inventory_root": granted.receipt_inventory_root,
        "publication_scope": granted.publication_scope.value,
        "capabilities": list(granted.capabilities),
        "c036_receipt_id": granted.c036_receipt_id,
    }
    if args.publish is not None:
        from ontologylab.packbuilder import (
            IncompleteExtractionError,
            PackBuildError,
            build_pack,
        )
        from ontologylab.pack_v2_closure import PackV2ClosureRefused
        try:
            manifest = build_pack(
                args.kg, args.publish, args.name, evidence_mode=args.evidence_mode,
            )
        except PackReadinessRefused as refused:
            _emit({"ok": False, "code": refused.code.value, "member": refused.member})
            return 2
        except PackV2ClosureRefused as refused:
            _emit({"ok": False, "code": refused.code.value, "member": refused.member})
            return 2
        except IncompleteExtractionError as refused:
            _emit({"ok": False, "code": refused.code, "member": "stream"})
            return 2
        except PackBuildError as refused:
            _emit({"ok": False, "code": "pack_build_refused", "member": type(refused).__name__})
            return 2
        payload["pack_id"] = manifest.pack_id
    _emit(payload)
    return 0


def _bound_ledger(conn: sqlite3.Connection, check_generation: int | None) -> tuple[int, str]:
    rows = read_ledger(conn)
    if not rows:
        _refuse(PackReadinessCode.INCOMPLETE_LEDGER, "ledger")
    generations = {row.generation for row in rows}
    if len(generations) != 1:
        _refuse(PackReadinessCode.AMBIGUOUS_LEDGER, "generation")
    fingerprints = set()
    for row in rows:
        value = row.source_fingerprint
        if value is None or not str(value).strip():
            _refuse(PackReadinessCode.INCOMPLETE_LEDGER, "source_fingerprint")
        fingerprints.add(str(value))
    if len(fingerprints) != 1:
        _refuse(PackReadinessCode.AMBIGUOUS_LEDGER, "source_fingerprint")
    generation, ledger_fp = next(iter(generations)), next(iter(fingerprints))
    if check_generation is not None and check_generation != generation:
        _refuse(PackReadinessCode.GENERATION_DRIFT, "generation")
    started = [
        phase for phase in MIGRATION_PHASES
        if any(row.phase == phase for row in rows) and not phase_is_complete(conn, phase)
    ]
    if started:
        _refuse(PackReadinessCode.MIGRATING, started[-1])
    missing = [phase for phase in MIGRATION_PHASES if not any(row.phase == phase for row in rows)]
    if missing:
        _refuse(PackReadinessCode.INCOMPLETE_LEDGER, missing[0])
    if not all(phase_is_complete(conn, phase) for phase in MIGRATION_PHASES):
        _refuse(PackReadinessCode.NOT_READY, "ledger")
    if compute_source_fingerprint(conn) != ledger_fp:
        _refuse(PackReadinessCode.FINGERPRINT_MISMATCH, "source_fingerprint")
    return generation, ledger_fp


def _refuse_stale_receipts(conn: sqlite3.Connection) -> None:
    try:
        rows = conn.execute(
            "SELECT representation_id, representation_content_hash FROM citation_receipts",
        ).fetchall()
    except sqlite3.OperationalError:
        return
    for representation_id, claimed in rows:
        live = conn.execute(
            "SELECT content_hash FROM documents WHERE id = ?", (representation_id,),
        ).fetchone()
        if live is None or str(live[0]) != str(claimed):
            _refuse(PackReadinessCode.STALE_RECEIPT, "citation")


def _c036_row(conn: sqlite3.Connection) -> sqlite3.Row | None:
    if not _table_exists(conn, C036_TABLE):
        return None
    rows = conn.execute(
        f"SELECT receipt_id, generation, source_fingerprint, "
        f"receipt_inventory_root, scope, decision FROM {C036_TABLE}",
    ).fetchall()
    if not rows:
        return None
    if len(rows) != 1:
        _refuse(PackReadinessCode.C036_STALE, "c036")
    return rows[0]


def _has_row(conn: sqlite3.Connection, table: str, sql: str) -> bool:
    if not _table_exists(conn, table):
        return False
    try:
        return conn.execute(sql).fetchone() is not None
    except sqlite3.OperationalError:
        return False


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (name,),
    ).fetchone() is not None


def _refuse(code: PackReadinessCode, member: str) -> NoReturn:
    raise PackReadinessRefused(code, member)


def _emit(payload: dict[str, JsonValue]) -> None:
    sys.stdout.write(json.dumps(payload, sort_keys=True, separators=(",", ":")))
    sys.stdout.write("\n")


if __name__ == "__main__":
    raise SystemExit(main())
