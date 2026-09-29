#!/usr/bin/env python3
"""Offline plumbing replay of the statement harness over a copied store.

A scripted slot engine answers only when a unit has exactly one explicit arm
slot and one explicit result slot, and builds that reply from those slots'
exact quotes. Every other unit is an abstention. This is not an accuracy claim.
No model or network calls.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final, TypedDict

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ontologylab.kgstore import KGStore
from ontologylab.models import Document
from ontologylab.statement_harness import PROMPT_VERSION, run_statement_harness

BANNER: Final = (
    "development-only plumbing replay; scripted slot engine; not an accuracy claim"
)
FORBIDDEN: Final = "Application Support"
MAX_CALLS: Final = 1_000_000
_UNIT_BLOCK: Final = re.compile(r"<statement-unit>\n(.+)\n</statement-unit>")


class ReplayRefused(Exception):
    def __init__(self, code: str, detail: str) -> None:
        self.code = code
        self.detail = detail
        super().__init__(f"{code}: {detail}")


class Mention(TypedDict):
    quote: str
    start: int
    end: int


class TypedMention(TypedDict):
    quote: str
    start: int
    end: int
    entity_type: str


class StatementReply(TypedDict):
    unit_id: str
    subject: TypedMention
    object: TypedMention
    treatment: Mention
    endpoint: Mention
    arm: Mention
    result: Mention
    source: Mention
    relation_type: str
    polarity: str
    qualifiers: dict[str, str]
    qualifier_mentions: dict[str, Mention]


class ReplayReport(TypedDict):
    banner: str
    documents: int
    status: str
    calls: int
    receipts: int
    harness_edges_written: int
    harness_edges_verified: int
    rejection_reasons: dict[str, int]
    unprocessed_units: list[str]
    hash_keys: list[str]


@dataclass(frozen=True, slots=True)
class SlotQuote:
    quote: str
    start: int
    end: int


@dataclass(frozen=True, slots=True)
class UnitView:
    unit_id: str
    window: str
    arms: tuple[SlotQuote, ...]
    results: tuple[SlotQuote, ...]


def answers_unit(arm_count: int, result_count: int) -> bool:
    return arm_count == 1 and result_count == 1


class ScriptedSlotEngine:
    def name(self) -> str:
        return "scripted-slot"

    async def generate(
        self, prompt: str, *, model: str | None = None,
    ) -> tuple[str, dict[str, int]]:
        del model
        statement = _statement_for_unit(_unit_view(prompt))
        statements: list[StatementReply] = [] if statement is None else [statement]
        usage: dict[str, int] = {"calls": 1}
        return json.dumps({"statements": statements}), usage


def _unit_view(prompt: str) -> UnitView:
    match = _UNIT_BLOCK.search(prompt)
    if match is None:
        raise ReplayRefused("prompt_shape", "missing statement-unit")
    try:
        payload = json.loads(match.group(1))
    except json.JSONDecodeError as exc:
        raise ReplayRefused("prompt_shape", "statement-unit is not JSON") from exc
    if not isinstance(payload, dict):
        raise ReplayRefused("prompt_shape", "statement-unit is not an object")
    unit_id = payload.get("unit_id")
    window = payload.get("window")
    if not isinstance(unit_id, str) or not unit_id or not isinstance(window, str):
        raise ReplayRefused("prompt_shape", "statement-unit lacks id or window")
    return UnitView(
        unit_id,
        window,
        _slots(payload.get("slots"), "arm"),
        _slots(payload.get("slots"), "result"),
    )


def _slots(raw_slots: object, role: str) -> tuple[SlotQuote, ...]:
    if not isinstance(raw_slots, list):
        return ()
    found: list[SlotQuote] = []
    for slot in raw_slots:
        if not isinstance(slot, dict) or slot.get("role") != role:
            continue
        parsed = _slot_quote(slot)
        if parsed is not None:
            found.append(parsed)
    return tuple(found)


def _slot_quote(slot: dict[str, object]) -> SlotQuote | None:
    quote = slot.get("quote")
    start = slot.get("start")
    end = slot.get("end")
    if (
        not isinstance(quote, str) or not quote
        or type(start) is not int or type(end) is not int
        or start >= end
    ):
        return None
    return SlotQuote(quote, start, end)


def _statement_for_unit(unit: UnitView) -> StatementReply | None:
    if not answers_unit(len(unit.arms), len(unit.results)):
        return None
    arm = _exact_mention(unit.window, unit.arms[0])
    result = _exact_mention(unit.window, unit.results[0])
    if arm is None or result is None:
        return None
    reply: StatementReply = {
        "unit_id": unit.unit_id,
        "subject": _typed_mention(arm, "ActiveIngredient"),
        "object": _typed_mention(result, "Pest"),
        "treatment": arm,
        "endpoint": result,
        "arm": arm,
        "result": result,
        "source": {"quote": unit.window, "start": 0, "end": len(unit.window)},
        "relation_type": "controls",
        "polarity": _polarity(result["quote"]),
        "qualifiers": {},
        "qualifier_mentions": {},
    }
    return reply


def _typed_mention(mention: Mention, entity_type: str) -> TypedMention:
    return {
        "quote": mention["quote"],
        "start": mention["start"],
        "end": mention["end"],
        "entity_type": entity_type,
    }


def _exact_mention(window: str, slot: SlotQuote) -> Mention | None:
    if (
        not 0 <= slot.start < slot.end <= len(window)
        or window[slot.start:slot.end] != slot.quote
    ):
        return None
    return {"quote": slot.quote, "start": slot.start, "end": slot.end}


def _polarity(quote: str) -> str:
    if "did not" in quote or "unchanged" in quote:
        return "no_effect"
    return "supports"


def _guarded_path(label: str, raw: str) -> Path:
    if FORBIDDEN in raw:
        raise ReplayRefused("forbidden_path", f"{label} contains {FORBIDDEN!r}")
    path = Path(raw)
    resolved = path.resolve()
    if FORBIDDEN in str(path) or FORBIDDEN in str(resolved):
        raise ReplayRefused("forbidden_path", f"{label} contains {FORBIDDEN!r}")
    return path


def _rejection_counts(rejections: tuple[tuple[str, str], ...]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for _unit_id, reason in rejections:
        counts[reason] = counts.get(reason, 0) + 1
    return dict(sorted(counts.items()))


def _harness_edges(store: KGStore) -> tuple[int, int]:
    written = store.conn.execute(
        "SELECT COUNT(DISTINCT e.id) FROM edges e "
        "JOIN citations c ON c.item_id = e.id AND c.kind = 'edge' "
        "WHERE c.prompt_version = ?",
        (PROMPT_VERSION,),
    ).fetchone()
    verified = store.conn.execute(
        "SELECT COUNT(DISTINCT e.id) FROM edges e "
        "JOIN citations c ON c.item_id = e.id AND c.kind = 'edge' "
        "WHERE c.prompt_version = ? AND e.status = 'verified'",
        (PROMPT_VERSION,),
    ).fetchone()
    if written is None or verified is None:
        raise ReplayRefused("edge_count", "harness edge query returned no row")
    return int(written[0]), int(verified[0])


def _present_bare_content_hash(store: KGStore) -> None:
    # Lifecycle stores prefix the digest; the harness compares the bare digest.
    # The column stays prefixed so document_raw_text can still verify the bytes.
    original = store.get_document

    def get_document(doc_id: str) -> Document:
        document = original(doc_id)
        digest = hashlib.sha256(
            store.document_raw_text(doc_id).encode("utf-8"),
        ).hexdigest()
        if document.content_hash not in {digest, "sha256:" + digest}:
            raise ReplayRefused("hash_mismatch", doc_id)
        document.content_hash = digest
        return document

    store.get_document = get_document


def replay(store_path: Path) -> ReplayReport:
    if not store_path.is_file():
        raise ReplayRefused("store_missing", str(store_path))
    engine = ScriptedSlotEngine()
    with KGStore.open(store_path) as store:
        _present_bare_content_hash(store)
        document_ids = [document.id for document in store.list_documents()]
        run = run_statement_harness(
            store, document_ids, engine, budget=MAX_CALLS,
        )
        written, verified = _harness_edges(store)
    return {
        "banner": BANNER,
        "documents": len(document_ids),
        "status": run.status,
        "calls": run.calls,
        "receipts": len(run.receipts),
        "harness_edges_written": written,
        "harness_edges_verified": verified,
        "rejection_reasons": _rejection_counts(run.rejections),
        "unprocessed_units": list(run.unprocessed_units),
        "hash_keys": [name for name, _digest in run.hashes],
    }


def write_report(report: ReplayReport, out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--store", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args(argv)
    try:
        store_path = _guarded_path("store", args.store)
        out_path = _guarded_path("out", args.out)
        report = replay(store_path)
    except ReplayRefused as exc:
        print(f"{exc.code}: {exc.detail}", file=sys.stderr)
        return 2
    if report["harness_edges_verified"] != 0:
        print(
            f"harness_edges_verified={report['harness_edges_verified']}",
            file=sys.stderr,
        )
        write_report(report, out_path)
        return 1
    write_report(report, out_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
