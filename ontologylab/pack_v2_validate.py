"""Read-only packed v2 closure completeness for the standalone verifier."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Final, NoReturn, assert_never

from ontologylab.pack_v2_closure import (
    CLOSURE_MEMBERS,
    EvidenceMode,
    PackV2ClosureRefused,
    resolve_v2_closure,
    _CITE_GAP,
    _POLICY_GAP,
    _REVIEW_GAP,
)
from ontologylab.pack_verifier import ManifestV2

_V2_EV: Final = "evidence-self-contained-v2"
_V2_RECEIPT_TABLES: Final = frozenset({
    "citation_receipts",
    "grounded_review_decisions",
    "extraction_run_receipts",
    "extraction_chunk_receipts",
    "preferred_selection_receipts",
})


@dataclass(frozen=True, slots=True)
class PackedV2ClosureRefused(Exception):
    member: str

    def __str__(self) -> str:
        return self.member


_CITE_FACT: str = (
    "SELECT receipt_id FROM citation_receipts c WHERE NOT ("
    "(c.fact_kind = 'node' AND EXISTS ("
    "SELECT 1 FROM nodes n WHERE n.id = c.fact_id AND n.status = 'verified')) "
    "OR (c.fact_kind = 'edge' AND EXISTS ("
    "SELECT 1 FROM edges e WHERE e.id = c.fact_id AND e.status = 'verified' "
    "AND e.invalidated_ts IS NULL)))"
)
_CITE_DOC: str = (
    "SELECT receipt_id FROM citation_receipts c WHERE NOT EXISTS ("
    "SELECT 1 FROM documents d WHERE d.id = c.representation_id)"
)
_REVIEW_FACT: str = (
    "SELECT receipt_id FROM grounded_review_decisions d "
    "WHERE d.pack_ineligible = 0 AND NOT ("
    "(d.fact_kind = 'node' AND EXISTS ("
    "SELECT 1 FROM nodes n WHERE n.id = d.fact_id AND n.status = 'verified')) "
    "OR (d.fact_kind = 'edge' AND EXISTS ("
    "SELECT 1 FROM edges e WHERE e.id = d.fact_id AND e.status = 'verified' "
    "AND e.invalidated_ts IS NULL)))"
)
_SOURCE_DOC: str = (
    "SELECT n.id FROM nodes n WHERE n.status = 'verified' AND NOT EXISTS ("
    "SELECT 1 FROM documents d WHERE d.id = n.source_doc_id) UNION "
    "SELECT e.id FROM edges e WHERE e.status = 'verified' "
    "AND e.invalidated_ts IS NULL AND NOT EXISTS ("
    "SELECT 1 FROM documents d WHERE d.id = e.source_doc_id)"
)
_DOC_WORK: str = (
    "SELECT id FROM documents d WHERE d.work_id IS NULL OR d.work_id = '' "
    "OR NOT EXISTS (SELECT 1 FROM works w WHERE w.id = d.work_id)"
)
_CITE_RUN: str = (
    "SELECT c.receipt_id FROM citation_receipts c LEFT JOIN "
    "extraction_run_receipts r ON r.receipt_id = c.run_receipt_id "
    "WHERE r.receipt_id IS NULL OR r.representation_id != c.representation_id"
)
_CITE_CHUNK: str = (
    "SELECT c.receipt_id FROM citation_receipts c LEFT JOIN "
    "extraction_chunk_receipts k ON k.receipt_id = c.chunk_receipt_id "
    "WHERE k.receipt_id IS NULL OR k.run_receipt_id != c.run_receipt_id"
)
_RUN_DOC: str = (
    "SELECT r.receipt_id FROM extraction_run_receipts r WHERE NOT EXISTS ("
    "SELECT 1 FROM documents d WHERE d.id = r.representation_id)"
)
_CHUNK_RUN: str = (
    "SELECT k.receipt_id FROM extraction_chunk_receipts k WHERE NOT EXISTS ("
    "SELECT 1 FROM extraction_run_receipts r WHERE r.receipt_id = k.run_receipt_id)"
)
_POLICY_BIND: str = (
    "SELECT receipt_id FROM preferred_selection_receipts p WHERE NOT EXISTS ("
    "SELECT 1 FROM works w WHERE w.id = p.work_id) OR ("
    "p.selected_representation_id IS NOT NULL "
    "AND p.selected_representation_id != '' AND NOT EXISTS ("
    "SELECT 1 FROM documents d WHERE d.id = p.selected_representation_id))"
)


def validate_packed_v2_closure(
    pack_dir: Path, conn: sqlite3.Connection, manifest: ManifestV2,
) -> None:
    """Refuse an internally incomplete packed v2 closure before serve."""
    try:
        _validate(pack_dir, conn, manifest)
    except PackedV2ClosureRefused:
        raise
    except sqlite3.Error:
        _refuse("pack.sqlite")


def _claims_v2_closure(pack_dir: Path) -> bool:
    try:
        payload = json.loads((pack_dir / "manifest.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    return isinstance(payload, dict) and "evidence_mode" in payload and "closure" in payload


def _packed_v2_graph_present(conn: sqlite3.Connection) -> bool:
    tables = {
        str(row[0])
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
    }
    if tables & _V2_RECEIPT_TABLES:
        return True
    columns = {str(row[1]) for row in conn.execute("PRAGMA table_info(nodes)")}
    return "status" in columns


def _typed_v2_contract_complete(pack_dir: Path) -> bool:
    try:
        payload = json.loads((pack_dir / "manifest.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    if not isinstance(payload, dict) or payload.get("pack_schema_version") != 2:
        return False
    mode = payload.get("evidence_mode")
    if not isinstance(mode, str) or mode not in EvidenceMode:
        return False
    claimed = payload.get("closure")
    if not isinstance(claimed, dict) or set(claimed) != set(CLOSURE_MEMBERS):
        return False
    return all(
        isinstance(claimed[member], list)
        and all(isinstance(item, str) for item in claimed[member])
        for member in CLOSURE_MEMBERS
    )


def _validate(
    pack_dir: Path, conn: sqlite3.Connection, manifest: ManifestV2,
) -> None:
    reviewed = "reviewed" in manifest.capabilities or "sourced-answer-v2" in manifest.capabilities
    advertised = _V2_EV in manifest.capabilities
    needs_closure = reviewed or _claims_v2_closure(pack_dir) or (
        advertised and _packed_v2_graph_present(conn)
    )
    if not needs_closure:
        return
    if not _typed_v2_contract_complete(pack_dir):
        _refuse("closure")
    _refuse_foreign_key_orphans(conn)
    mode = _refuse_manifest_sql_mismatch(pack_dir)
    _refuse_citation_incomplete(conn)
    _refuse_review_incomplete(conn)
    _refuse_source_documents(conn)
    _refuse_run_chunk_dependencies(conn)
    _refuse_policy_incomplete(conn)
    _refuse_evidence(pack_dir, conn, manifest, mode)


def _refuse(member: str) -> NoReturn:
    raise PackedV2ClosureRefused(member)


def _refuse_if(conn: sqlite3.Connection, sql: str, member: str) -> None:
    if conn.execute(sql).fetchone() is not None:
        _refuse(member)


def _refuse_foreign_key_orphans(conn: sqlite3.Connection) -> None:
    if conn.execute("PRAGMA foreign_key_check").fetchone() is not None:
        _refuse("foreign_keys")


def _refuse_manifest_sql_mismatch(pack_dir: Path) -> EvidenceMode:
    try:
        resolved = resolve_v2_closure(pack_dir)
    except PackV2ClosureRefused as refused:
        _refuse(refused.member)
    except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError):
        _refuse("closure")
    return resolved.evidence_mode


def _refuse_citation_incomplete(conn: sqlite3.Connection) -> None:
    _refuse_if(conn, _CITE_GAP, "citation")
    _refuse_if(conn, _CITE_FACT, "citation")
    _refuse_if(conn, _CITE_DOC, "citation")
    packed = {
        str(row[0]) for row in conn.execute("SELECT receipt_id FROM citation_receipts")
    }
    for raw in conn.execute(
        "SELECT citation_receipt_ids_json FROM grounded_review_decisions "
        "WHERE pack_ineligible = 0",
    ):
        try:
            ids = json.loads(str(raw[0]))
        except json.JSONDecodeError:
            _refuse("citation")
        if not isinstance(ids, list) or any(str(item) not in packed for item in ids):
            _refuse("citation")


def _refuse_review_incomplete(conn: sqlite3.Connection) -> None:
    _refuse_if(conn, _REVIEW_GAP, "review_decision")
    _refuse_if(conn, _REVIEW_FACT, "review_decision")


def _refuse_source_documents(conn: sqlite3.Connection) -> None:
    _refuse_if(conn, _SOURCE_DOC, "representation")
    _refuse_if(conn, _DOC_WORK, "representation")


def _refuse_run_chunk_dependencies(conn: sqlite3.Connection) -> None:
    _refuse_if(conn, _CITE_RUN, "run")
    _refuse_if(conn, _RUN_DOC, "run")
    _refuse_if(conn, _CITE_CHUNK, "chunk")
    _refuse_if(conn, _CHUNK_RUN, "chunk")


def _refuse_policy_incomplete(conn: sqlite3.Connection) -> None:
    _refuse_if(conn, _POLICY_GAP, "policy")
    _refuse_if(conn, _POLICY_BIND, "policy")


def _refuse_evidence(
    pack_dir: Path,
    conn: sqlite3.Connection,
    manifest: ManifestV2,
    mode: EvidenceMode,
) -> None:
    claimed = {item.path for item in manifest.inventory}
    match mode:
        case EvidenceMode.FULL:
            ids = conn.execute("SELECT id FROM documents")
            suffix = "full.txt"
        case EvidenceMode.EXCERPT:
            ids = conn.execute("SELECT receipt_id FROM citation_receipts")
            suffix = "window.txt"
        case unreachable:
            assert_never(unreachable)
    for row in ids:
        rel = f"evidence/{row[0]}/{suffix}"
        if rel not in claimed or not (pack_dir / rel).is_file():
            _refuse("source")
