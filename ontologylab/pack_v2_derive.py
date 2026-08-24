"""Re-derive v2 counts, exclusions, capabilities, and pack evidence bytes."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from enum import StrEnum, unique
from pathlib import Path
from typing import Final

from ontologylab.migration import read_ledger
from ontologylab.pack_readiness import (
    C036_DECISION,
    C036_TABLE,
    REVIEWED_CAPABILITIES,
    UNREVIEWED_CAPABILITIES,
    PublicationScope,
)
from ontologylab.pack_receipt_seal import ReceiptSealRefused, seal_receipt_inventory
from ontologylab.pack_source_fingerprint import source_fingerprint_matches

SOURCE_INVENTORY_NAME: Final = "receipt-inventory.json"

_COUNT_SQL: Final = (
    ("works", "SELECT COUNT(*) FROM works"),
    ("representations", "SELECT COUNT(*) FROM documents"),
    ("observations", "SELECT COUNT(*) FROM document_observations"),
    ("identifiers", "SELECT COUNT(*) FROM work_identifiers"),
    ("citations", "SELECT COUNT(*) FROM citation_receipts"),
    ("review_decisions", "SELECT COUNT(*) FROM grounded_review_decisions"),
    ("extraction_runs", "SELECT COUNT(*) FROM extraction_run_receipts"),
    ("extraction_chunks", "SELECT COUNT(*) FROM extraction_chunk_receipts"),
    ("nodes", "SELECT COUNT(*) FROM nodes"),
    ("edges", "SELECT COUNT(*) FROM edges"),
    ("nodes_verified", "SELECT COUNT(*) FROM nodes WHERE status = 'verified'"),
    (
        "edges_verified",
        "SELECT COUNT(*) FROM edges WHERE status = 'verified' "
        "AND invalidated_ts IS NULL",
    ),
)
_EXCLUSION_SQL: Final = (
    (
        "ungrounded",
        "SELECT (SELECT COUNT(*) FROM nodes WHERE status != 'verified') + "
        "(SELECT COUNT(*) FROM edges WHERE status != 'verified' "
        "OR invalidated_ts IS NOT NULL)",
    ),
    (
        "waived",
        "SELECT COUNT(*) FROM grounded_review_decisions WHERE pack_ineligible = 1",
    ),
    (
        "invalid_legacy_evidence",
        "SELECT COUNT(*) FROM h1_anchor_receipts WHERE classification = 'quarantined'",
    ),
    (
        "identity_conflicts",
        "SELECT COUNT(*) FROM identifier_decisions WHERE action = 'resolve_collision'",
    ),
)


@unique
class EvidenceAvailability(StrEnum):
    FULL = "full"
    EXCERPT = "excerpt"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True, slots=True)
class PackEvidence:
    representation_id: str
    evidence_mode: str
    available: bool
    text: str | None
    limitation: str | None
    path: str | None


def derive_v2_counts(conn: sqlite3.Connection) -> dict[str, int]:
    """Count packed v2 tables and verified node/edge status."""
    return {key: _count(conn, sql) for key, sql in _COUNT_SQL}


def derive_exclusions(conn: sqlite3.Connection) -> dict[str, int]:
    """Count snapshot rows excluded from default v2 closure."""
    return {key: _count(conn, sql) for key, sql in _EXCLUSION_SQL}


def write_source_receipt_inventory(
    pack_dir: Path, entries: tuple[tuple[str, str, str], ...],
) -> None:
    """Write the live C-036 inventory witness as pack payload."""
    (pack_dir / SOURCE_INVENTORY_NAME).write_text(
        json.dumps({"entries": [list(item) for item in entries]},
                   separators=(",", ":"), sort_keys=True),
        encoding="utf-8",
    )


def source_inventory_root(entries: tuple[tuple[str, str, str], ...]) -> str:
    payload = [list(item) for item in entries]
    return hashlib.sha256(json.dumps(payload, separators=(",", ":")).encode()).hexdigest()


def load_source_receipt_inventory(
    pack_root: Path,
) -> tuple[tuple[str, str, str], ...] | None:
    path = pack_root / SOURCE_INVENTORY_NAME
    if not path.is_file():
        return None
    raw = json.loads(path.read_text(encoding="utf-8"))
    rows = raw.get("entries") if isinstance(raw, dict) else None
    if not isinstance(rows, list):
        return None
    parsed: list[tuple[str, str, str]] = []
    for item in rows:
        if not isinstance(item, list) or len(item) != 3:
            return None
        parsed.append((str(item[0]), str(item[1]), str(item[2])))
    return tuple(parsed)


def derive_capabilities(
    conn: sqlite3.Connection,
    *,
    has_evidence: bool,
    pack_root: Path | None = None,
) -> tuple[str, ...]:
    """Authoritative labels from packed C-036 + live inventory witness."""
    base = UNREVIEWED_CAPABILITIES if has_evidence else ("knowledge-graph-v2",)
    previous = conn.row_factory
    conn.row_factory = sqlite3.Row
    try:
        return _derive_capabilities(conn, base=base, pack_root=pack_root)
    finally:
        conn.row_factory = previous


def _derive_capabilities(
    conn: sqlite3.Connection,
    *,
    base: tuple[str, ...],
    pack_root: Path | None,
) -> tuple[str, ...]:
    if not _has_table(conn, C036_TABLE) or pack_root is None:
        return base
    rows = conn.execute(
        f"SELECT generation, source_fingerprint, receipt_inventory_root, "
        f"scope, decision FROM {C036_TABLE}",
    ).fetchall()
    if len(rows) != 1:
        return base
    row = rows[0]
    witness = load_source_receipt_inventory(pack_root)
    if witness is None:
        return base
    try:
        packed = seal_receipt_inventory(conn)
        ledger = read_ledger(conn)
    except (sqlite3.OperationalError, ReceiptSealRefused):
        return base
    generations = {item.generation for item in ledger}
    if len(generations) != 1:
        return base
    generation = next(iter(generations))
    if (
        int(row[0]) != generation
        or not source_fingerprint_matches(conn, pack_root, str(row[1]))
        or str(row[2]) != source_inventory_root(witness)
        or str(row[4]) != C036_DECISION
        or str(row[3]) not in {
            PublicationScope.REVIEWED.value, PublicationScope.SOURCED.value,
        }
        or not set(packed.entries).issubset(set(witness))
    ):
        return base
    return (
        REVIEWED_CAPABILITIES if "evidence-self-contained-v2" in base
        else (*base, "reviewed", "sourced-answer-v2")
    )


def resolve_pack_evidence(
    pack_root: Path, conn: sqlite3.Connection, representation_id: str,
) -> PackEvidence:
    """Read FULL evidence from the process-owned pack tree only."""
    if ".." in representation_id or "/" in representation_id or "\\" in representation_id:
        return PackEvidence(
            representation_id, EvidenceAvailability.UNAVAILABLE.value,
            False, None, "invalid_representation_id", None,
        )
    row = conn.execute(
        "SELECT raw_text_path FROM documents WHERE id = ?", (representation_id,),
    ).fetchone()
    if row is None:
        return PackEvidence(
            representation_id, EvidenceAvailability.UNAVAILABLE.value,
            False, None, "unknown_representation", None,
        )
    claimed = "" if row[0] is None else str(row[0])
    if not claimed or claimed.endswith("/window.txt"):
        return PackEvidence(
            representation_id, EvidenceAvailability.EXCERPT.value,
            False, None, "excerpt_only", None,
        )
    expected = f"evidence/{representation_id}/full.txt"
    if claimed != expected:
        return PackEvidence(
            representation_id, EvidenceAvailability.UNAVAILABLE.value,
            False, None, "path_not_in_inventory", None,
        )
    root = pack_root.resolve()
    candidate = (pack_root / claimed).resolve()
    if not candidate.is_relative_to(root) or not str(candidate).startswith(str(root / "evidence")):
        return PackEvidence(
            representation_id, EvidenceAvailability.UNAVAILABLE.value,
            False, None, "path_escapes_pack", None,
        )
    if not candidate.is_file():
        return PackEvidence(
            representation_id, EvidenceAvailability.UNAVAILABLE.value,
            False, None, "missing_evidence", None,
        )
    return PackEvidence(
        representation_id, EvidenceAvailability.FULL.value,
        True, candidate.read_text(encoding="utf-8"), None, claimed,
    )


def fact_receipts(
    conn: sqlite3.Connection, fact_kind: str, fact_id: str,
) -> dict[str, str | int | None]:
    """Compact Work/Representation/Citation receipts for one packed fact."""
    try:
        cite = conn.execute(
            "SELECT receipt_id, representation_id, selected_text_hash, "
            "start_offset, end_offset, policy_identity FROM citation_receipts "
            "WHERE fact_kind = ? AND fact_id = ? ORDER BY receipt_id LIMIT 1",
            (fact_kind, fact_id),
        ).fetchone()
    except sqlite3.OperationalError:
        return {}
    if cite is None:
        return {}
    doc = conn.execute(
        "SELECT work_id, content_hash FROM documents WHERE id = ?",
        (cite[1],),
    ).fetchone()
    return {
        "work_id": None if doc is None else doc[0],
        "representation_id": str(cite[1]),
        "representation_content_hash": None if doc is None else doc[1],
        "citation_id": str(cite[0]),
        "selected_text_hash": str(cite[2]),
        "start_offset": int(cite[3]),
        "end_offset": int(cite[4]),
        "policy_identity": None if cite[5] is None else str(cite[5]),
    }


def _count(conn: sqlite3.Connection, sql: str) -> int:
    try:
        row = conn.execute(sql).fetchone()
    except sqlite3.OperationalError:
        return 0
    return 0 if row is None else int(row[0])


def _has_table(conn: sqlite3.Connection, name: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (name,),
    ).fetchone() is not None
