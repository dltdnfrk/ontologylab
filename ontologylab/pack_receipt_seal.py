"""Re-derive content-addressed Step 7 receipt IDs and inventory root."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum, unique
from typing import Final, NoReturn, assert_never

from ontologylab.citation_ids import citation_receipt_id
from ontologylab.citation_types import CitationBinding
from ontologylab.extraction_receipt_ids import chunk_receipt_id, digest, run_receipt_id
from ontologylab.extraction_receipt_types import ChunkSpan, ExtractionRunBinding
from ontologylab.grounded_review_ids import historical_review_decision_id, review_decision_id
from ontologylab.grounded_review_types import ReviewAction
from ontologylab.selection_ids import parse_inventory, selection_receipt_id
from ontologylab.selection_types import PolicyVersion

@unique
class ReceiptFamily(StrEnum):
    RUN = "run"
    CHUNK = "chunk"
    CITATION = "citation"
    REVIEW_DECISION = "review_decision"
    POLICY = "policy"


_FAMILIES: Final = tuple(ReceiptFamily)


@unique
class ReceiptSealCode(StrEnum):
    STALE_RECEIPT = "stale_receipt"
    MISSING_RECEIPT = "missing_receipt"


@dataclass(frozen=True, slots=True)
class ReceiptSealRefused(Exception):
    code: ReceiptSealCode
    member: str

    def __str__(self) -> str:
        return f"{self.code}:{self.member}"


@dataclass(frozen=True, slots=True)
class SealedInventory:
    members: Mapping[str, tuple[str, ...]]
    root: str


def seal_receipt_inventory(conn: sqlite3.Connection) -> SealedInventory:
    """Re-derive every receipt ID and bind C-036 to canonical row content."""
    require = _has_verified(conn)
    members: dict[str, tuple[str, ...]] = {}
    payload: list[list[str]] = []
    for family in _FAMILIES:
        rows = _family_rows(conn, family)
        if require and not rows:
            _refuse(ReceiptSealCode.MISSING_RECEIPT, family.value)
        ids: list[str] = []
        for row in rows:
            stored = str(row["receipt_id"])
            expected = _expected_id(family, row)
            if expected != stored:
                _refuse(ReceiptSealCode.STALE_RECEIPT, family.value)
            ids.append(stored)
            payload.append([family.value, stored, _body_digest(family, row)])
        members[family.value] = tuple(ids)
    root = hashlib.sha256(
        json.dumps(payload, separators=(",", ":")).encode("utf-8"),
    ).hexdigest()
    return SealedInventory(members=members, root=root)


def _expected_id(family: ReceiptFamily, row: sqlite3.Row) -> str:
    match family:
        case ReceiptFamily.CITATION:
            return citation_receipt_id(_citation_binding(row))
        case ReceiptFamily.RUN:
            return run_receipt_id(
                _run_binding(row),
                str(row["document_content_hash"]),
                str(row["chunk_plan_receipt_id"]),
            )
        case ReceiptFamily.CHUNK:
            return chunk_receipt_id(
                str(row["run_receipt_id"]),
                str(row["plan_receipt_id"]),
                ChunkSpan(
                    index=int(row["chunk_index"]),
                    start_offset=int(row["start_offset"]),
                    end_offset=int(row["end_offset"]),
                    text="",
                    text_hash=str(row["chunk_text_hash"]),
                    coordinate_profile=str(row["coordinate_profile"]),
                ),
            )
        case ReceiptFamily.REVIEW_DECISION:
            return _review_id(row)
        case ReceiptFamily.POLICY:
            return _policy_id(row)
        case _ as unreachable:
            assert_never(unreachable)


def _citation_binding(row: sqlite3.Row) -> CitationBinding:
    selection = row["selection_receipt_id"]
    policy = row["policy_identity"]
    return CitationBinding(
        representation_id=str(row["representation_id"]),
        representation_content_hash=str(row["representation_content_hash"]),
        run_receipt_id=str(row["run_receipt_id"]),
        chunk_receipt_id=str(row["chunk_receipt_id"]),
        chunk_start_offset=int(row["chunk_start_offset"]),
        chunk_end_offset=int(row["chunk_end_offset"]),
        coordinate_profile=str(row["coordinate_profile"]),
        chunk_text_hash=str(row["chunk_text_hash"]),
        chunk_plan_receipt_id=str(row["chunk_plan_receipt_id"]),
        selection_receipt_id=None if selection is None else str(selection),
        policy_identity=None if policy is None else str(policy),
        fact_kind=str(row["fact_kind"]),
        fact_id=str(row["fact_id"]),
        proposal_id=str(row["proposal_id"]),
        fact_revision=str(row["fact_revision"]),
        start_offset=int(row["start_offset"]),
        end_offset=int(row["end_offset"]),
        selected_text=str(row["selected_text"]),
        selected_text_hash=str(row["selected_text_hash"]),
    )


def _run_binding(row: sqlite3.Row) -> ExtractionRunBinding:
    return ExtractionRunBinding(
        representation_id=str(row["representation_id"]),
        policy_identity=str(row["policy_identity"]),
        config_identity=str(row["config_identity"]),
        schema_version_id=int(row["schema_version_id"]),
        extractor_engine=str(row["extractor_engine"]),
        extractor_model=str(row["extractor_model"]),
        prompt_version=str(row["prompt_version"]),
        decode_params_json=str(row["decode_params_json"]),
    )


def _review_id(row: sqlite3.Row) -> str:
    action = ReviewAction(str(row["action"]))
    waived_facts = _json_strings(row["waived_fact_ids_json"])
    waived_cites = _json_strings(row["waived_citation_ids_json"])
    defects = _json_strings(row["scoped_defects_json"])
    current = review_decision_id(
        fact_kind=str(row["fact_kind"]),
        fact_id=str(row["fact_id"]),
        fact_revision=str(row["fact_revision"]),
        action=action,
        digest_value=str(row["citation_set_digest"]),
        actor=str(row["actor"]),
        reason=str(row["reason"]),
        predecessor_receipt_id=row["predecessor_receipt_id"],
        representation_id=row["representation_id"],
        selection_receipt_id=row["selection_receipt_id"],
        policy_identity=row["policy_identity"],
        run_receipt_id=row["run_receipt_id"],
        pack_ineligible=int(row["pack_ineligible"]) == 1,
        decided_ts=float(row["decided_ts"]),
        as_of_ts=float(row["as_of_ts"]),
        waived_fact_ids=waived_facts,
        waived_citation_ids=waived_cites,
        scoped_defects=defects,
    )
    stored = str(row["receipt_id"])
    if current == stored:
        return current
    historical = historical_review_decision_id(
        fact_kind=str(row["fact_kind"]),
        fact_id=str(row["fact_id"]),
        fact_revision=str(row["fact_revision"]),
        action=action,
        digest_value=str(row["citation_set_digest"]),
        actor=str(row["actor"]),
        reason=str(row["reason"]),
        predecessor_receipt_id=row["predecessor_receipt_id"],
        waived_fact_ids=waived_facts,
        waived_citation_ids=waived_cites,
        scoped_defects=defects,
    )
    if historical == stored:
        return historical
    return current


def _policy_id(row: sqlite3.Row) -> str:
    selected = row["selected_representation_id"]
    selected_hash = row["selected_content_hash"]
    return selection_receipt_id(
        str(row["work_id"]),
        PolicyVersion(str(row["policy_version"])),
        str(row["policy_hash"]),
        parse_inventory(str(row["inventory_json"])),
        None if selected is None else str(selected),
        None if selected_hash is None else str(selected_hash),
    )


def _body_digest(family: ReceiptFamily, row: sqlite3.Row) -> str:
    match family:
        case ReceiptFamily.CITATION:
            parts = (
                str(row["selected_text"]), str(row["selected_text_hash"]),
                str(row["representation_content_hash"]), str(row["start_offset"]),
                str(row["end_offset"]), str(row["fact_id"]),
            )
        case ReceiptFamily.RUN:
            parts = (
                str(row["extractor_engine"]), str(row["extractor_model"]),
                str(row["config_identity"]), str(row["policy_identity"]),
                str(row["document_content_hash"]), str(row["chunk_plan_receipt_id"]),
                str(row["prompt_version"]), str(row["decode_params_json"]),
            )
        case ReceiptFamily.CHUNK:
            parts = (
                str(row["chunk_text_hash"]), str(row["start_offset"]),
                str(row["end_offset"]), str(row["coordinate_profile"]),
                str(row["chunk_index"]), str(row["plan_receipt_id"]),
            )
        case ReceiptFamily.REVIEW_DECISION:
            parts = (
                str(row["actor"]), str(row["reason"]), str(row["action"]),
                str(row["citation_set_digest"]), str(row["fact_revision"]),
            )
        case ReceiptFamily.POLICY:
            parts = (
                str(row["selected_representation_id"] or ""),
                str(row["selected_content_hash"] or ""),
                str(row["policy_hash"]), str(row["inventory_json"]),
            )
        case _ as unreachable:
            assert_never(unreachable)
    return digest((family, *parts))


def _family_rows(conn: sqlite3.Connection, family: ReceiptFamily) -> tuple[sqlite3.Row, ...]:
    sql = {
        ReceiptFamily.RUN: "SELECT * FROM extraction_run_receipts ORDER BY receipt_id",
        ReceiptFamily.CHUNK: "SELECT * FROM extraction_chunk_receipts ORDER BY receipt_id",
        ReceiptFamily.CITATION: "SELECT * FROM citation_receipts ORDER BY receipt_id",
        ReceiptFamily.REVIEW_DECISION: (
            "SELECT * FROM grounded_review_decisions "
            "WHERE pack_ineligible = 0 ORDER BY receipt_id"
        ),
        ReceiptFamily.POLICY: "SELECT * FROM preferred_selection_receipts ORDER BY receipt_id",
    }[family]
    try:
        return tuple(conn.execute(sql).fetchall())
    except sqlite3.OperationalError:
        _refuse(ReceiptSealCode.MISSING_RECEIPT, family.value)


def _has_verified(conn: sqlite3.Connection) -> bool:
    try:
        return conn.execute(
            "SELECT 1 FROM nodes WHERE status = 'verified' LIMIT 1",
        ).fetchone() is not None
    except sqlite3.OperationalError:
        return False


def _json_strings(raw: str | None) -> tuple[str, ...]:
    if raw is None:
        return ()
    loaded = json.loads(str(raw))
    if not isinstance(loaded, list):
        return ()
    return tuple(str(item) for item in loaded)


def _refuse(code: ReceiptSealCode, member: str) -> NoReturn:
    raise ReceiptSealRefused(code, member)
