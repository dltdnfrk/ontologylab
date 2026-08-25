"""One-snapshot evidence-self-contained pack v2 closure."""

# noqa: SIZE_OK — indivisible collect/copy/resolve; Task 8 forbids extra modules

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from enum import StrEnum, unique
from pathlib import Path
from typing import Final, Mapping, TypedDict, assert_never

from ontologylab.file_lifecycle import content_hash_for
from ontologylab.selection_types import POLICY_V1


@unique
class EvidenceMode(StrEnum):
    FULL = "full"
    EXCERPT = "excerpt"


@unique
class PackV2ClosureCode(StrEnum):
    SOURCED_NONE = "sourced_none"
    DANGLING_MEMBER = "dangling_member"
    CROSS_GENERATION = "cross_generation"
    MISSING_RECEIPT = "missing_receipt"
    INCOMPLETE_STREAM = "incomplete_stream"
    V1_REWRITE = "v1_rewrite"
    EVIDENCE_HASH_MISMATCH = "evidence_hash_mismatch"
    TAMPERED_RECEIPT = "tampered_receipt"


@dataclass(frozen=True, slots=True)
class PackV2ClosureRefused(Exception):
    code: PackV2ClosureCode
    member: str

    def __str__(self) -> str:
        return f"{self.code}:{self.member}"


CLOSURE_MEMBERS: Final = (
    "work", "identifier", "redirect", "decision", "observation",
    "representation", "source", "run", "chunk", "citation",
    "review_decision", "policy", "provenance",
)
OPTIONAL_FAMILIES: Final = frozenset({"redirect", "decision"})
V2_CAPABILITIES: Final = ("knowledge-graph-v2", "evidence-self-contained-v2")
_V2_ID_TABLES: Final = (
    ("works", "id", "work"),
    ("work_identifiers", "id", "identifier"),
    ("document_observations", "id", "observation"),
    ("work_redirect_decisions", "id", "redirect"),
    ("identifier_decisions", "id", "decision"),
    ("extraction_run_receipts", "receipt_id", "run"),
    ("extraction_chunk_receipts", "receipt_id", "chunk"),
    ("citation_receipts", "receipt_id", "citation"),
    ("grounded_review_decisions", "receipt_id", "review_decision"),
    ("preferred_selection_receipts", "receipt_id", "policy"),
    ("provenance_outbox", "event_id", "provenance"),
)
_SHIPPED_DOCS: Final = (
    "SELECT DISTINCT id FROM documents WHERE id IN ("
    "SELECT source_doc_id FROM nodes WHERE status = 'verified' "
    "UNION SELECT source_doc_id FROM edges "
    "WHERE status = 'verified' AND invalidated_ts IS NULL "
    "UNION SELECT source_doc_id FROM citations)"
)
_CITE_GAP: Final = (
    "SELECT n.id FROM nodes n WHERE n.status = 'verified' AND NOT EXISTS ("
    "SELECT 1 FROM citation_receipts c WHERE c.fact_kind = 'node' AND c.fact_id = n.id"
    ") UNION SELECT e.id FROM edges e WHERE e.status = 'verified' "
    "AND e.invalidated_ts IS NULL AND NOT EXISTS ("
    "SELECT 1 FROM citation_receipts c WHERE c.fact_kind = 'edge' AND c.fact_id = e.id)"
)
_REVIEW_GAP: Final = (
    "SELECT n.id FROM nodes n WHERE n.status = 'verified' AND NOT EXISTS ("
    "SELECT 1 FROM grounded_review_decisions d WHERE d.fact_kind = 'node' "
    "AND d.fact_id = n.id AND d.pack_ineligible = 0) UNION SELECT e.id FROM edges e "
    "WHERE e.status = 'verified' AND e.invalidated_ts IS NULL AND NOT EXISTS ("
    "SELECT 1 FROM grounded_review_decisions d WHERE d.fact_kind = 'edge' "
    "AND d.fact_id = e.id AND d.pack_ineligible = 0)"
)
_POLICY_GAP: Final = (
    "SELECT d.work_id FROM documents d WHERE d.work_id IS NOT NULL AND EXISTS ("
    "SELECT 1 FROM nodes n WHERE n.source_doc_id = d.id AND n.status = 'verified'"
    ") AND NOT EXISTS (SELECT 1 FROM preferred_selection_receipts p "
    "WHERE p.work_id = d.work_id)"
)


@dataclass(frozen=True, slots=True)
class PackV2Closure:
    pack_schema_version: int
    evidence_mode: EvidenceMode
    generation: int
    members: Mapping[str, tuple[str, ...]]
    counts: Mapping[str, int]
    capabilities: tuple[str, ...]
    source_material_policy: Mapping[str, int]
    selection_policy_version: str
    excerpts: Mapping[str, str]
    representation_hashes: Mapping[str, str]
    excerpt_hashes: Mapping[str, str]
    exclusions: Mapping[str, int]
    source_inventory: tuple[tuple[str, str, str], ...]
    source_fingerprint_entries: tuple[tuple[str, str], ...]


class PackV2ManifestFields(TypedDict):
    pack_schema_version: int
    evidence_mode: str
    generation: int
    capabilities: list[str]
    selection_policy_version: str
    source_material_policy: dict[str, int]
    closure: dict[str, list[str]]
    exclusions: dict[str, int]


def parse_evidence_mode(value: str) -> EvidenceMode:
    try:
        return EvidenceMode(value)
    except ValueError:
        raise PackV2ClosureRefused(PackV2ClosureCode.SOURCED_NONE, "source") from None


def refuse_v1_rewrite(destination: Path) -> None:
    manifest = destination / "manifest.json"
    payload = json.loads(manifest.read_text(encoding="utf-8")) if manifest.is_file() else {}
    if payload.get("pack_schema_version", 1) != 2:
        raise PackV2ClosureRefused(PackV2ClosureCode.V1_REWRITE, "pack")


def collect_v2_closure(
    conn: sqlite3.Connection,
    *,
    evidence_mode: EvidenceMode,
    source_root: Path,
) -> PackV2Closure:
    from ontologylab.pack_readiness import authorize_publication
    from ontologylab.pack_receipt_seal import seal_receipt_inventory
    from ontologylab.pack_source_fingerprint import capture_source_fingerprint_entries

    readiness = authorize_publication(conn)
    sealed = seal_receipt_inventory(conn)
    generation = readiness.generation
    _refuse_cross_generation(conn, generation)
    representations = _require_ids(conn, _SHIPPED_DOCS, "representation")
    works = _bound_works(conn, representations)
    identifiers = _scoped(
        conn, "SELECT id FROM work_identifiers WHERE work_id IN ({ph})", works, "identifier",
    )
    observations = _scoped(
        conn,
        "SELECT id FROM document_observations WHERE representation_id IN ({ph})",
        representations, "observation",
    )
    citations = _scoped(
        conn,
        "SELECT c.receipt_id FROM citation_receipts c WHERE c.representation_id IN ({ph}) "
        "AND ((c.fact_kind = 'node' AND EXISTS ("
        "SELECT 1 FROM nodes n WHERE n.id = c.fact_id AND n.status = 'verified')) "
        "OR (c.fact_kind = 'edge' AND EXISTS ("
        "SELECT 1 FROM edges e WHERE e.id = c.fact_id AND e.status = 'verified' "
        "AND e.invalidated_ts IS NULL)))",
        representations, "citation",
    )
    reviews = _require_ids(
        conn,
        "SELECT d.receipt_id FROM grounded_review_decisions d "
        "WHERE d.pack_ineligible = 0 AND ("
        "(d.fact_kind = 'node' AND EXISTS ("
        "SELECT 1 FROM nodes n WHERE n.id = d.fact_id AND n.status = 'verified')) "
        "OR (d.fact_kind = 'edge' AND EXISTS ("
        "SELECT 1 FROM edges e WHERE e.id = d.fact_id AND e.status = 'verified' "
        "AND e.invalidated_ts IS NULL)))",
        "review_decision",
    )
    runs = _scoped(
        conn,
        "SELECT DISTINCT run_receipt_id FROM citation_receipts WHERE receipt_id IN ({ph})",
        citations, "run",
    )
    chunks = _scoped(
        conn,
        "SELECT DISTINCT chunk_receipt_id FROM citation_receipts WHERE receipt_id IN ({ph})",
        citations, "chunk",
    )
    policies = _scoped(
        conn,
        "SELECT receipt_id FROM preferred_selection_receipts WHERE work_id IN ({ph})",
        works, "policy",
    )
    redirects = _scoped(
        conn,
        "SELECT id FROM work_redirect_decisions "
        "WHERE source_work_id IN ({ph}) OR target_work_id IN ({ph})",
        works, "redirect", required=False, twice=True,
    )
    decisions = _scoped(
        conn,
        "SELECT id FROM identifier_decisions WHERE identifier_id IN ({ph})",
        identifiers, "decision", required=False,
    )
    if conn.execute(_CITE_GAP).fetchone() is not None:
        raise PackV2ClosureRefused(PackV2ClosureCode.MISSING_RECEIPT, "citation")
    if conn.execute(_REVIEW_GAP).fetchone() is not None:
        raise PackV2ClosureRefused(PackV2ClosureCode.MISSING_RECEIPT, "review_decision")
    if conn.execute(_POLICY_GAP).fetchone() is not None:
        raise PackV2ClosureRefused(PackV2ClosureCode.MISSING_RECEIPT, "policy")
    _seal_citations(conn, citations)
    excerpts, sources, rep_hashes, excerpt_hashes = _source_members(
        conn, evidence_mode, representations, citations, source_root,
    )
    provenance = _scoped_provenance(conn, works, representations, observations)
    members = {
        "work": works,
        "identifier": identifiers,
        "redirect": redirects,
        "decision": decisions,
        "observation": observations,
        "representation": representations,
        "source": sources,
        "run": runs,
        "chunk": chunks,
        "citation": citations,
        "review_decision": reviews,
        "policy": policies,
        "provenance": provenance,
    }
    full_count = len(representations) if evidence_mode is EvidenceMode.FULL else 0
    excerpt_count = len(citations) if evidence_mode is EvidenceMode.EXCERPT else 0
    return PackV2Closure(
        pack_schema_version=2,
        evidence_mode=evidence_mode,
        generation=generation,
        members=members,
        counts={
            "works": len(works),
            "representations": len(representations),
            "observations": len(observations),
            "identifiers": len(identifiers),
            "citations": len(citations),
            "review_decisions": len(reviews),
            "extraction_runs": len(runs),
            "extraction_chunks": len(chunks),
            "nodes": _count(conn, "SELECT COUNT(*) FROM nodes WHERE status = 'verified'"),
            "edges": _count(
                conn,
                "SELECT COUNT(*) FROM edges WHERE status = 'verified' "
                "AND invalidated_ts IS NULL",
            ),
        },
        capabilities=readiness.capabilities,
        source_material_policy={
            "full_count": full_count,
            "excerpt_count": excerpt_count,
            "unavailable_excluded_count": 0,
        },
        selection_policy_version=POLICY_V1,
        excerpts=excerpts,
        representation_hashes=rep_hashes,
        excerpt_hashes=excerpt_hashes,
        exclusions=_exclusions(conn),
        source_inventory=sealed.entries,
        source_fingerprint_entries=capture_source_fingerprint_entries(conn),
    )


def install_v2_pack_schema(conn: sqlite3.Connection) -> None:
    from ontologylab import authority, extraction_state
    from ontologylab.citation_schema import ensure_citation_schema
    from ontologylab.extraction_receipt_schema import ensure_receipt_schema
    from ontologylab.grounded_review_schema import ensure_grounded_review_schema
    from ontologylab.selection_schema import ensure_selection_schema

    conn.executescript(authority._SCHEMA)
    conn.executescript(extraction_state._SCHEMA)
    ensure_receipt_schema(conn)
    ensure_citation_schema(conn)
    ensure_grounded_review_schema(conn)
    ensure_selection_schema(conn)
    columns = {str(row[1]) for row in conn.execute("PRAGMA table_info(documents)")}
    if "work_id" not in columns:
        conn.execute("ALTER TABLE documents ADD COLUMN work_id TEXT")
    conn.execute(
        "CREATE TABLE IF NOT EXISTS c036_capability_receipts ("
        "receipt_id TEXT PRIMARY KEY, generation INTEGER NOT NULL, "
        "source_fingerprint TEXT NOT NULL, receipt_inventory_root TEXT NOT NULL, "
        "scope TEXT NOT NULL, decision TEXT NOT NULL)"
    )


def copy_v2_tables(pack_conn: sqlite3.Connection, closure: PackV2Closure) -> None:
    for table, key, member in _V2_ID_TABLES:
        _insert_claimed(pack_conn, table, key, closure.members[member])
    works = closure.members["work"]
    observations = closure.members["observation"]
    identifiers = closure.members["identifier"]
    representations = closure.members["representation"]
    reviews = closure.members["review_decision"]
    _insert_dual(pack_conn, "work_relations", "source_work_id", works, "target_work_id", works)
    _insert_dual(
        pack_conn, "identifier_assertions",
        "identifier_id", identifiers, "observation_id", observations,
    )
    _insert_where(
        pack_conn, "v2_migration_ledger", "generation = ?", (str(closure.generation),),
    )
    _insert_claimed(pack_conn, "extraction_runs", "document_id", representations)
    pack_conn.execute(
        "INSERT INTO main.extraction_chunks ("
        + _columns(pack_conn, "extraction_chunks")
        + ") SELECT "
        + _columns(pack_conn, "extraction_chunks")
        + " FROM live.extraction_chunks WHERE run_id IN (SELECT id FROM main.extraction_runs)"
    )
    _insert_where(
        pack_conn, "grounded_review_current", "receipt_id IN ({ph})", reviews,
    )
    path_sql = (
        "'evidence/' || id || '/full.txt'"
        if closure.evidence_mode is EvidenceMode.FULL
        else "''"
    )
    _copy_c036(pack_conn)
    pack_conn.execute(
        "UPDATE main.documents SET work_id = ("
        "SELECT work_id FROM live.documents AS src WHERE src.id = main.documents.id), "
        f"raw_text_path = {path_sql}"
    )


def _copy_c036(pack_conn: sqlite3.Connection) -> None:
    present = {
        str(row[0])
        for row in pack_conn.execute(
            "SELECT name FROM live.sqlite_master WHERE type = 'table'",
        )
    }
    if "c036_capability_receipts" not in present:
        return
    pack_conn.execute(
        "INSERT INTO main.c036_capability_receipts SELECT * "
        "FROM live.c036_capability_receipts"
    )


def _exclusions(conn: sqlite3.Connection) -> dict[str, int]:
    from ontologylab.pack_v2_derive import derive_exclusions

    return derive_exclusions(conn)


def write_v2_evidence(
    pack_dir: Path, closure: PackV2Closure, source_root: Path,
) -> None:
    match closure.evidence_mode:
        case EvidenceMode.FULL:
            for rep_id in closure.members["representation"]:
                dest = pack_dir / "evidence" / rep_id / "full.txt"
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes((source_root / "documents" / rep_id / "raw.txt").read_bytes())
                if content_hash_for(dest.read_bytes()) != closure.representation_hashes[rep_id]:
                    raise PackV2ClosureRefused(PackV2ClosureCode.EVIDENCE_HASH_MISMATCH, "source")
        case EvidenceMode.EXCERPT:
            for citation_id, text in closure.excerpts.items():
                dest = pack_dir / "evidence" / citation_id / "window.txt"
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_text(text, encoding="utf-8")
                expected = closure.excerpt_hashes[citation_id]
                if content_hash_for(dest.read_bytes()) != expected:
                    raise PackV2ClosureRefused(PackV2ClosureCode.EVIDENCE_HASH_MISMATCH, "source")
        case unreachable:
            assert_never(unreachable)
    from ontologylab.pack_source_fingerprint import write_source_fingerprint
    from ontologylab.pack_v2_derive import write_source_receipt_inventory

    write_source_receipt_inventory(pack_dir, closure.source_inventory)
    write_source_fingerprint(pack_dir, closure.source_fingerprint_entries)


def v2_manifest_fields(closure: PackV2Closure) -> PackV2ManifestFields:
    return {
        "pack_schema_version": 2,
        "evidence_mode": str(closure.evidence_mode),
        "generation": closure.generation,
        "capabilities": list(closure.capabilities),
        "selection_policy_version": closure.selection_policy_version,
        "source_material_policy": dict(closure.source_material_policy),
        "closure": {name: list(ids) for name, ids in closure.members.items()},
        "exclusions": dict(closure.exclusions),
    }


def resolve_v2_closure(pack_dir: Path) -> PackV2Closure:
    payload = json.loads((pack_dir / "manifest.json").read_text(encoding="utf-8"))
    mode = parse_evidence_mode(str(payload["evidence_mode"]))
    database = pack_dir / "pack.sqlite"
    connection = sqlite3.connect(
        f"{database.resolve().as_uri()}?mode=ro",
        uri=True,
    )
    try:
        members = {
            "work": _ids(connection, "SELECT id FROM works ORDER BY id"),
            "identifier": _ids(connection, "SELECT id FROM work_identifiers ORDER BY id"),
            "redirect": _ids(connection, "SELECT id FROM work_redirect_decisions ORDER BY id"),
            "decision": _ids(connection, "SELECT id FROM identifier_decisions ORDER BY id"),
            "observation": _ids(connection, "SELECT id FROM document_observations ORDER BY id"),
            "representation": _ids(connection, "SELECT id FROM documents ORDER BY id"),
            "run": _ids(connection, "SELECT receipt_id FROM extraction_run_receipts ORDER BY 1"),
            "chunk": _ids(connection, "SELECT receipt_id FROM extraction_chunk_receipts ORDER BY 1"),
            "citation": _ids(connection, "SELECT receipt_id FROM citation_receipts ORDER BY 1"),
            "review_decision": _ids(
                connection, "SELECT receipt_id FROM grounded_review_decisions ORDER BY 1",
            ),
            "policy": _ids(
                connection, "SELECT receipt_id FROM preferred_selection_receipts ORDER BY 1",
            ),
            "provenance": _ids(connection, "SELECT event_id FROM provenance_outbox ORDER BY 1"),
        }
    finally:
        connection.close()
    evidence = pack_dir / "evidence"
    pattern = "*/full.txt" if mode is EvidenceMode.FULL else "*/window.txt"
    members["source"] = (
        tuple(sorted(path.parent.name for path in evidence.glob(pattern)))
        if evidence.is_dir() else ()
    )
    claimed = payload["closure"]
    for family in CLOSURE_MEMBERS:
        have = set(members[family])
        want = set(claimed[family])
        if have != want or (family not in OPTIONAL_FAMILIES and not have):
            raise PackV2ClosureRefused(PackV2ClosureCode.DANGLING_MEMBER, family)
    excerpts = {
        citation_id: (pack_dir / "evidence" / citation_id / "window.txt").read_text(
            encoding="utf-8",
        )
        for citation_id in members["source"]
        if mode is EvidenceMode.EXCERPT
    }
    return PackV2Closure(
        pack_schema_version=2, evidence_mode=mode, generation=int(payload["generation"]),
        members=members, counts=payload["counts"], capabilities=V2_CAPABILITIES,
        source_material_policy=payload["source_material_policy"],
        selection_policy_version=str(payload["selection_policy_version"]),
        excerpts=excerpts, representation_hashes={}, excerpt_hashes={},
        exclusions=payload.get("exclusions") or {},
        source_inventory=(),
        source_fingerprint_entries=(),
    )


def _ids(conn: sqlite3.Connection, sql: str) -> tuple[str, ...]:
    return tuple(str(row[0]) for row in conn.execute(sql))


def _require_ids(conn: sqlite3.Connection, sql: str, member: str) -> tuple[str, ...]:
    values = _ids(conn, sql)
    if not values:
        raise PackV2ClosureRefused(PackV2ClosureCode.MISSING_RECEIPT, member)
    return values


def _count(conn: sqlite3.Connection, sql: str) -> int:
    return int(conn.execute(sql).fetchone()[0])


def _refuse_cross_generation(conn: sqlite3.Connection, bound: int) -> None:
    for (payload,) in conn.execute("SELECT payload_json FROM provenance_outbox"):
        generation = json.loads(str(payload)).get("generation")
        if generation is not None and int(generation) != bound:
            raise PackV2ClosureRefused(PackV2ClosureCode.CROSS_GENERATION, "provenance")


def _bound_works(
    conn: sqlite3.Connection, representations: tuple[str, ...],
) -> tuple[str, ...]:
    works: list[str] = []
    for rep_id in representations:
        row = conn.execute("SELECT work_id FROM documents WHERE id = ?", (rep_id,)).fetchone()
        work_id = None if row is None else row[0]
        if work_id is None or conn.execute(
            "SELECT id FROM works WHERE id = ?", (str(work_id),),
        ).fetchone() is None:
            raise PackV2ClosureRefused(PackV2ClosureCode.DANGLING_MEMBER, "work")
        if str(work_id) not in works:
            works.append(str(work_id))
    if not works:
        return ()
    placeholders = ",".join("?" * len(works))
    for source, target in conn.execute(
        "SELECT source_work_id, target_work_id FROM work_redirect_decisions "
        f"WHERE source_work_id IN ({placeholders}) OR target_work_id IN ({placeholders})",
        (*works, *works),
    ):
        for work_id in (str(source), str(target)):
            if conn.execute("SELECT id FROM works WHERE id = ?", (work_id,)).fetchone() is None:
                raise PackV2ClosureRefused(PackV2ClosureCode.DANGLING_MEMBER, "work")
            if work_id not in works:
                works.append(work_id)
    return tuple(works)


def _scoped(
    conn: sqlite3.Connection,
    sql: str,
    ids: tuple[str, ...],
    member: str,
    *,
    required: bool = True,
    twice: bool = False,
) -> tuple[str, ...]:
    if not ids:
        if required:
            raise PackV2ClosureRefused(PackV2ClosureCode.MISSING_RECEIPT, member)
        return ()
    placeholders = ",".join("?" * len(ids))
    params = (*ids, *ids) if twice else ids
    values = tuple(
        str(row[0]) for row in conn.execute(sql.format(ph=placeholders), params)
    )
    if required and not values:
        raise PackV2ClosureRefused(PackV2ClosureCode.MISSING_RECEIPT, member)
    return values


def _scoped_provenance(
    conn: sqlite3.Connection,
    works: tuple[str, ...],
    representations: tuple[str, ...],
    observations: tuple[str, ...],
) -> tuple[str, ...]:
    kept: list[str] = []
    claimed = {
        "work_id": set(works),
        "representation_id": set(representations),
        "observation_id": set(observations),
    }
    for event_id, payload in conn.execute("SELECT event_id, payload_json FROM provenance_outbox"):
        data = json.loads(str(payload))
        if any(str(data[key]) in values for key, values in claimed.items() if key in data):
            kept.append(str(event_id))
    if not kept:
        raise PackV2ClosureRefused(PackV2ClosureCode.MISSING_RECEIPT, "provenance")
    return tuple(kept)


def _seal_citations(conn: sqlite3.Connection, citations: tuple[str, ...]) -> None:
    if not citations:
        raise PackV2ClosureRefused(PackV2ClosureCode.MISSING_RECEIPT, "citation")
    placeholders = ",".join("?" * len(citations))
    rows = conn.execute(
        "SELECT receipt_id, representation_id, run_receipt_id, chunk_receipt_id, "
        "selection_receipt_id, policy_identity, selected_text, selected_text_hash "
        f"FROM citation_receipts WHERE receipt_id IN ({placeholders})",
        citations,
    ).fetchall()
    for row in rows:
        selected = str(row["selected_text"])
        if content_hash_for(selected.encode("utf-8")) != str(row["selected_text_hash"]):
            raise PackV2ClosureRefused(PackV2ClosureCode.EVIDENCE_HASH_MISMATCH, "citation")
        run = conn.execute(
            "SELECT representation_id FROM extraction_run_receipts WHERE receipt_id = ?",
            (row["run_receipt_id"],),
        ).fetchone()
        chunk = conn.execute(
            "SELECT run_receipt_id FROM extraction_chunk_receipts WHERE receipt_id = ?",
            (row["chunk_receipt_id"],),
        ).fetchone()
        if run is None or chunk is None:
            raise PackV2ClosureRefused(PackV2ClosureCode.MISSING_RECEIPT, "run")
        if str(run["representation_id"]) != str(row["representation_id"]):
            raise PackV2ClosureRefused(PackV2ClosureCode.TAMPERED_RECEIPT, "citation")
        if str(chunk["run_receipt_id"]) != str(row["run_receipt_id"]):
            raise PackV2ClosureRefused(PackV2ClosureCode.TAMPERED_RECEIPT, "citation")
        selection_id = row["selection_receipt_id"]
        policy = row["policy_identity"]
        if selection_id is None or not str(selection_id):
            raise PackV2ClosureRefused(PackV2ClosureCode.MISSING_RECEIPT, "policy")
        selection = conn.execute(
            "SELECT policy_hash FROM preferred_selection_receipts WHERE receipt_id = ?",
            (str(selection_id),),
        ).fetchone()
        if selection is None:
            raise PackV2ClosureRefused(PackV2ClosureCode.MISSING_RECEIPT, "policy")
        if policy is not None and str(policy) != str(selection["policy_hash"]):
            raise PackV2ClosureRefused(PackV2ClosureCode.TAMPERED_RECEIPT, "citation")


def _source_members(
    conn: sqlite3.Connection,
    evidence_mode: EvidenceMode,
    representations: tuple[str, ...],
    citations: tuple[str, ...],
    source_root: Path,
) -> tuple[dict[str, str], tuple[str, ...], dict[str, str], dict[str, str]]:
    hashes: dict[str, str] = {}
    for rep_id in representations:
        row = conn.execute("SELECT content_hash FROM documents WHERE id = ?", (rep_id,)).fetchone()
        if row is None or row[0] is None:
            raise PackV2ClosureRefused(PackV2ClosureCode.DANGLING_MEMBER, "source")
        hashes[rep_id] = str(row[0])
    match evidence_mode:
        case EvidenceMode.FULL:
            for rep_id, expected in hashes.items():
                raw = source_root / "documents" / rep_id / "raw.txt"
                if not raw.is_file():
                    raise PackV2ClosureRefused(PackV2ClosureCode.DANGLING_MEMBER, "source")
                if content_hash_for(raw.read_bytes()) != expected:
                    raise PackV2ClosureRefused(PackV2ClosureCode.EVIDENCE_HASH_MISMATCH, "source")
            return {}, representations, hashes, {}
        case EvidenceMode.EXCERPT:
            excerpts: dict[str, str] = {}
            excerpt_hashes: dict[str, str] = {}
            if not citations:
                raise PackV2ClosureRefused(PackV2ClosureCode.SOURCED_NONE, "source")
            placeholders = ",".join("?" * len(citations))
            for receipt_id, text, digest in conn.execute(
                "SELECT receipt_id, selected_text, selected_text_hash "
                f"FROM citation_receipts WHERE receipt_id IN ({placeholders})",
                citations,
            ):
                if not text:
                    raise PackV2ClosureRefused(PackV2ClosureCode.SOURCED_NONE, "source")
                excerpts[str(receipt_id)] = str(text)
                excerpt_hashes[str(receipt_id)] = str(digest)
            return excerpts, tuple(excerpts), hashes, excerpt_hashes
        case unreachable:
            assert_never(unreachable)


def _columns(conn: sqlite3.Connection, table: str) -> str:
    return ", ".join(
        str(row[1])
        for row in conn.execute(f"PRAGMA table_info({table})")
        if str(row[1]) != "seq"
    )


def _insert_claimed(
    conn: sqlite3.Connection, table: str, key: str, ids: tuple[str, ...],
) -> None:
    if not ids:
        return
    columns = _columns(conn, table)
    placeholders = ",".join("?" * len(ids))
    conn.execute(
        f"INSERT INTO main.{table} ({columns}) SELECT {columns} FROM live.{table} "
        f"WHERE {key} IN ({placeholders})",
        ids,
    )


def _insert_where(
    conn: sqlite3.Connection, table: str, where: str, params: tuple[str, ...],
) -> None:
    if not params:
        return
    columns = _columns(conn, table)
    if "{ph}" in where:
        placeholders = ",".join("?" * len(params))
        where_sql = where.format(ph=placeholders)
    else:
        where_sql = where
    conn.execute(
        f"INSERT INTO main.{table} ({columns}) SELECT {columns} FROM live.{table} "
        f"WHERE {where_sql}",
        params,
    )


def _insert_dual(
    conn: sqlite3.Connection,
    table: str,
    column_a: str,
    ids_a: tuple[str, ...],
    column_b: str,
    ids_b: tuple[str, ...],
) -> None:
    if not ids_a or not ids_b:
        return
    columns = _columns(conn, table)
    ph_a = ",".join("?" * len(ids_a))
    ph_b = ",".join("?" * len(ids_b))
    conn.execute(
        f"INSERT INTO main.{table} ({columns}) SELECT {columns} FROM live.{table} "
        f"WHERE {column_a} IN ({ph_a}) AND {column_b} IN ({ph_b})",
        (*ids_a, *ids_b),
    )
