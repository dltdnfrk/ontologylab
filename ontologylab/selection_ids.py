"""Deterministic preferred-selection receipt identities."""

from __future__ import annotations

import json

from ontologylab.extraction_receipt_ids import digest
from ontologylab.selection_policy import policy_parts
from ontologylab.selection_types import (
    InventoryEntry,
    PolicyVersion,
    SelectionInventoryError,
    SelectionReceipt,
)


def policy_hash(policy: PolicyVersion) -> str:
    return digest(policy_parts(policy))


def inventory_json(inventory: tuple[InventoryEntry, ...]) -> str:
    rows = [
        {
            "representation_id": entry.representation_id,
            "ready": entry.ready_rank,
            "usable_full_text": entry.usable_full_text_rank,
            "grade": entry.grade_rank,
            "source": entry.source_rank,
            "stage": entry.stage_rank,
            "length": entry.byte_length,
            "lexical_hash": entry.content_hash,
            "rejection_reason": entry.rejection_reason,
        }
        for entry in sorted(inventory, key=lambda item: item.representation_id)
    ]
    return json.dumps(rows, sort_keys=True, separators=(",", ":"))


def parse_inventory(raw: str) -> tuple[InventoryEntry, ...]:
    payload = json.loads(raw)
    if not isinstance(payload, list):
        raise SelectionInventoryError("selection inventory must be a JSON array")
    entries: list[InventoryEntry] = []
    for item in payload:
        if not isinstance(item, dict):
            raise SelectionInventoryError(
                "selection inventory entry must be an object"
            )
        rejection = item.get("rejection_reason")
        entries.append(
            InventoryEntry(
                representation_id=str(item["representation_id"]),
                ready_rank=int(item["ready"]),
                usable_full_text_rank=int(item["usable_full_text"]),
                grade_rank=int(item["grade"]),
                source_rank=int(item["source"]),
                stage_rank=int(item["stage"]),
                byte_length=int(item["length"]),
                content_hash=str(item["lexical_hash"]),
                rejection_reason=None if rejection is None else str(rejection),
            )
        )
    return tuple(entries)


def selection_receipt_id(
    work_id: str,
    policy: PolicyVersion,
    hashed_policy: str,
    inventory: tuple[InventoryEntry, ...],
    selected_id: str | None,
    selected_hash: str | None,
) -> str:
    rows = tuple(
        (
            f"{entry.representation_id}:{entry.ready_rank}:"
            f"{entry.usable_full_text_rank}:{entry.grade_rank}:"
            f"{entry.source_rank}:{entry.stage_rank}:{entry.byte_length}:"
            f"{entry.content_hash}:{entry.rejection_reason or ''}"
        )
        for entry in sorted(inventory, key=lambda item: item.representation_id)
    )
    return digest((
        "preferred-selection-v1",
        work_id,
        str(policy),
        hashed_policy,
        selected_id or "",
        selected_hash or "",
        *rows,
    ))


def receipt_from_parts(
    work_id: str,
    policy: PolicyVersion,
    hashed_policy: str,
    inventory: tuple[InventoryEntry, ...],
    selected_id: str | None,
    selected_hash: str | None,
    *,
    created: bool,
) -> SelectionReceipt:
    return SelectionReceipt(
        receipt_id=selection_receipt_id(
            work_id, policy, hashed_policy, inventory,
            selected_id, selected_hash,
        ),
        work_id=work_id,
        policy_version=str(policy),
        policy_hash=hashed_policy,
        selected_representation_id=selected_id,
        selected_content_hash=selected_hash,
        inventory=inventory,
        created=created,
    )
