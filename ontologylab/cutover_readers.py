"""All-reader generation-bound zero-drift proof (Step 9A Task 14)."""
# noqa: SIZE_OK — adapter registry plus six payload observers share one proof seam

from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from enum import StrEnum, unique
from pathlib import Path
from typing import Final, NoReturn, assert_never

from ontologylab.cutover_rehearsal import (
    CutoverCode,
    CutoverPhase,
    CutoverRefused,
    _in_savepoint,
    read_cutover_state,
)
from ontologylab.kgstore import KGStore
from ontologylab.mcp_server import PackSession

_SHA: Final = "sha256:"
_UNREPRESENTABLE: Final = "unrepresentable_v2_state"


@unique
class ReaderKind(StrEnum):
    KG_STORE = "kg_store"
    CLI_GRAPH = "cli_graph"
    HTTP_QUERY = "http_query"
    VERIFIED_PACK = "verified_pack"
    MCP_SESSION = "mcp_session"
    METHOD_GRAPH = "method_graph"


@unique
class ReaderStatus(StrEnum):
    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True, slots=True)
class GenerationBinding:
    generation: int
    high_water: int


@dataclass(frozen=True, slots=True)
class ReaderObservation:
    kind: ReaderKind
    binding: GenerationBinding
    status: ReaderStatus
    canonical_hash: str
    detail: str


@dataclass(frozen=True, slots=True)
class ReaderSurfaces:
    conn: sqlite3.Connection
    sqlite_path: Path
    data_dir: Path
    pack_dir: Path
    session: PackSession


def _refuse(code: CutoverCode, detail: str) -> NoReturn:
    raise CutoverRefused(code, detail)


def hash_identity(payload: dict[str, list[tuple[str, ...]]]) -> str:
    """SHA-256 over canonical JSON of a graph-identity payload."""
    body = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return _SHA + hashlib.sha256(body.encode("utf-8")).hexdigest()


def _is_sha(value: str) -> bool:
    if not value.startswith(_SHA):
        return False
    hex_part = value.removeprefix(_SHA)
    try:
        return len(hex_part) == 64 and bytes.fromhex(hex_part) is not None
    except ValueError:
        return False


def _node_tuple(node: dict[str, str] | tuple[str, ...]) -> tuple[str, ...]:
    match node:
        case dict() as row:
            return (
                str(row.get("id", "")), str(row.get("name", "")),
                str(row.get("entity_type", "")), str(row.get("status", "")),
            )
        case tuple() as row:
            return row
        case unreachable:
            assert_never(unreachable)


def _edge_tuple(edge: dict[str, str] | tuple[str, ...]) -> tuple[str, ...]:
    match edge:
        case dict() as row:
            return (
                str(row.get("id", "")),
                str(row.get("src_node_id", row.get("src", ""))),
                str(row.get("dst_node_id", row.get("dst", ""))),
                str(row.get("relation_type", row.get("relation", ""))),
                str(row.get("status", "")),
            )
        case tuple() as row:
            return row
        case unreachable:
            assert_never(unreachable)


def identity_from_payload(
    nodes: Sequence[dict[str, str] | tuple[str, ...]],
    edges: Sequence[dict[str, str] | tuple[str, ...]],
) -> dict[str, list[tuple[str, ...]]]:
    """Normalize a graph surface payload to the shared sentinel (nodes+edges)."""
    return {
        "nodes": sorted(_node_tuple(node) for node in nodes),
        "edges": sorted(_edge_tuple(edge) for edge in edges),
    }


def parse_observation(raw: ReaderObservation) -> ReaderObservation:
    """Boundary parse: typed observation, hash shape, allowlisted unavailable."""
    if type(raw) is not ReaderObservation:
        _refuse(CutoverCode.READER_SET, "observation")
    match raw.status:
        case ReaderStatus.AVAILABLE:
            if not _is_sha(raw.canonical_hash):
                _refuse(CutoverCode.READER_HASH, raw.kind.value)
        case ReaderStatus.UNAVAILABLE:
            if raw.detail != _UNREPRESENTABLE:
                _refuse(CutoverCode.READER_UNAVAILABLE, raw.detail or raw.kind.value)
        case unreachable:
            assert_never(unreachable)
    return raw


def observe_kg_store(conn: sqlite3.Connection, binding: GenerationBinding) -> ReaderObservation:
    """Direct KGStore query output (verified nodes/edges)."""
    nodes = conn.execute(
        "SELECT id, name, entity_type, status FROM nodes "
        "WHERE status = 'verified' ORDER BY id",
    ).fetchall()
    edges = conn.execute(
        "SELECT id, src_node_id, dst_node_id, relation_type, status FROM edges "
        "WHERE status = 'verified' AND invalidated_ts IS NULL ORDER BY id",
    ).fetchall()
    payload = {
        "nodes": [tuple(str(item) for item in row) for row in nodes],
        "edges": [tuple(str(item) for item in row) for row in edges],
    }
    return ReaderObservation(
        ReaderKind.KG_STORE, binding, ReaderStatus.AVAILABLE, hash_identity(payload), "",
    )


def observe_cli_graph(sqlite_path: str, binding: GenerationBinding) -> ReaderObservation:
    """Hash `KGStore.graph_query` return — the CLI entity/search graph path."""
    store = KGStore.open(sqlite_path)
    try:
        graph = store.graph_query(include_proposed=False, limit=500)
    finally:
        store.close()
    payload = identity_from_payload(graph["nodes"], graph["edges"])
    return ReaderObservation(
        ReaderKind.CLI_GRAPH, binding, ReaderStatus.AVAILABLE, hash_identity(payload), "",
    )


def observe_http_query(data_dir: Path, binding: GenerationBinding) -> ReaderObservation:
    """Hash FastAPI `/api/graph` JSON body."""
    from fastapi.testclient import TestClient
    from ontologylab.server.app import create_app

    app = create_app(data_dir=data_dir, packs_dir=data_dir / "packs")
    headers = {"host": "127.0.0.1"}
    with TestClient(app) as client:
        response = client.get(
            "/api/graph", params={"include_proposed": False, "limit": 500}, headers=headers,
        )
    if response.status_code != 200:
        _refuse(CutoverCode.READER_FAILED, "http")
    body = response.json()
    payload = identity_from_payload(body.get("nodes") or [], body.get("edges") or [])
    return ReaderObservation(
        ReaderKind.HTTP_QUERY, binding, ReaderStatus.AVAILABLE, hash_identity(payload), "",
    )


def observe_verified_pack(pack_dir: Path, binding: GenerationBinding) -> ReaderObservation:
    """Hash graph_query output from the verified serving snapshot."""
    from ontologylab.pack_verifier import verify_pack
    from ontologylab.verified_pack_reader import activate_pack

    verify_pack(pack_dir)
    snapshot = activate_pack(pack_dir)
    try:
        store = snapshot.open_store()
        try:
            graph = store.graph_query(include_proposed=False, limit=500)
        finally:
            store.close()
    finally:
        snapshot.close()
    payload = identity_from_payload(graph["nodes"], graph["edges"])
    return ReaderObservation(
        ReaderKind.VERIFIED_PACK, binding, ReaderStatus.AVAILABLE, hash_identity(payload), "",
    )


def observe_mcp_session(
    session: PackSession, pack_id: str, binding: GenerationBinding,
) -> ReaderObservation:
    """Hash PackSession.graph_query tool payload."""
    if session.pack_id != pack_id:
        session.load_pack(pack_id)
    graph = session.graph_query(include_proposed=False, limit=500)
    payload = identity_from_payload(graph.get("nodes") or [], graph.get("edges") or [])
    return ReaderObservation(
        ReaderKind.MCP_SESSION, binding, ReaderStatus.AVAILABLE, hash_identity(payload), "",
    )


def observe_method_graph(session: PackSession, pack_id: str, binding: GenerationBinding) -> ReaderObservation:
    """Invoke list_methods; AVAILABLE only when published methods exist."""
    if session.pack_id != pack_id:
        session.load_pack(pack_id)
    try:
        listed = session.list_methods()
    except (OSError, sqlite3.Error, RuntimeError, TypeError, KeyError, ValueError):
        return ReaderObservation(
            ReaderKind.METHOD_GRAPH, binding, ReaderStatus.UNAVAILABLE, "", _UNREPRESENTABLE,
        )
    methods = listed["methods"] if isinstance(listed, dict) else getattr(listed, "methods", [])
    if not methods:
        return ReaderObservation(
            ReaderKind.METHOD_GRAPH, binding, ReaderStatus.UNAVAILABLE, "", _UNREPRESENTABLE,
        )
    graph = session.graph_query(include_proposed=False, limit=500)
    payload = identity_from_payload(graph.get("nodes") or [], graph.get("edges") or [])
    return ReaderObservation(
        ReaderKind.METHOD_GRAPH, binding, ReaderStatus.AVAILABLE, hash_identity(payload), "",
    )


def reader_probes(
    surfaces: ReaderSurfaces, binding: GenerationBinding,
) -> tuple[Callable[[], ReaderObservation], ...]:
    """Complete built-in adapter registry for one rehearsal copy."""
    return (
        lambda: observe_kg_store(surfaces.conn, binding),
        lambda: observe_cli_graph(str(surfaces.sqlite_path), binding),
        lambda: observe_http_query(surfaces.data_dir, binding),
        lambda: observe_verified_pack(surfaces.pack_dir, binding),
        lambda: observe_mcp_session(surfaces.session, surfaces.pack_dir.name, binding),
        lambda: observe_method_graph(surfaces.session, surfaces.pack_dir.name, binding),
    )


def _run_probes(
    probes: Sequence[Callable[[], ReaderObservation]],
) -> tuple[ReaderObservation, ...]:
    collected: list[ReaderObservation] = []
    for probe in probes:
        try:
            collected.append(parse_observation(probe()))
        except CutoverRefused:
            raise
        except (OSError, sqlite3.Error, RuntimeError, TypeError, KeyError, ValueError) as exc:
            _refuse(CutoverCode.READER_FAILED, type(exc).__name__)
    return tuple(collected)


def _validate_set(observations: tuple[ReaderObservation, ...]) -> None:
    kinds = [item.kind for item in observations]
    expected = [kind.value for kind in ReaderKind]
    if sorted(kind.value for kind in kinds) != sorted(expected):
        _refuse(CutoverCode.READER_SET, "kinds")
    if len(kinds) != len(set(kinds)):
        _refuse(CutoverCode.READER_SET, "duplicate")


def record_all_reader_observation(
    conn: sqlite3.Connection,
    binding: GenerationBinding,
    surfaces: ReaderSurfaces | None = None,
    *,
    probes: Sequence[Callable[[], ReaderObservation]] | None = None,
) -> None:
    """Sole public streak path: run adapters, persist bundle, apply drift."""
    if probes is None:
        if surfaces is None:
            _refuse(CutoverCode.READER_SET, "surfaces")
        probes = reader_probes(surfaces, binding)
    state = read_cutover_state(conn)
    observations = _run_probes(probes)

    def _write() -> None:
        _validate_set(observations)
        for item in observations:
            if item.binding != binding:
                _refuse(CutoverCode.READER_BINDING, item.kind.value)
        available = tuple(
            item for item in observations if item.status is ReaderStatus.AVAILABLE
        )
        if not available:
            _refuse(CutoverCode.READER_UNAVAILABLE, "none_available")
        hashes = {item.canonical_hash for item in available}
        bind_ok = (
            binding.generation == state.generation
            and binding.high_water == state.high_water
        )
        drift = 0 if bind_ok and len(hashes) == 1 else 1
        rows = [
            {
                "kind": item.kind.value, "status": item.status.value,
                "hash": item.canonical_hash, "detail": item.detail,
            }
            for item in sorted(observations, key=lambda item: item.kind.value)
        ]
        encoded = json.dumps({"readers": rows}, sort_keys=True, separators=(",", ":"))
        bundle_hash = _SHA + hashlib.sha256(encoded.encode()).hexdigest()
        match state.phase:
            case CutoverPhase.CATCH_UP:
                pass
            case (
                CutoverPhase.DRAINED | CutoverPhase.FENCED
                | CutoverPhase.CONSTRAINTS_REBUILT | CutoverPhase.FULL_V2
                | CutoverPhase.AUTHORITY_FLIPPED
            ):
                if drift == 0:
                    _refuse(CutoverCode.WRONG_PHASE, state.phase.value)
            case CutoverPhase.EXPAND | CutoverPhase.SHADOW_WRITE | CutoverPhase.BACKFILL:
                _refuse(CutoverCode.WRONG_PHASE, state.phase.value)
            case unreachable:
                assert_never(unreachable)
        conn.execute(
            "INSERT INTO cutover_receipts (kind, phase, detail) VALUES (?, ?, ?)",
            (
                "reader_bundle", state.phase.value,
                json.dumps({"hash": bundle_hash, "readers": rows}, sort_keys=True, separators=(",", ":")),
            ),
        )
        streak = state.zero_drift_streak + 1 if drift == 0 else 0
        conn.execute(
            "UPDATE cutover_state SET zero_drift_streak = ?, bundle_hash = ? WHERE id = 1",
            (streak, bundle_hash),
        )
        conn.execute(
            "INSERT INTO cutover_receipts (kind, phase, detail) VALUES (?, ?, ?)",
            ("observation", state.phase.value, "zero" if drift == 0 else "reset"),
        )

    _in_savepoint(conn, _write)
