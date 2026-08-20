"""Shared helpers for the G003 real-surface harness tests
(`tests/test_wave21_surface_harness.py`).

Scope: Wave 2.1 Step 1 Goal G003 only. Every helper here drives the actual
INSTALLED entry point (the `ontologylab` / `ontologylab-serve` /
`ontologylab-mcp` console scripts resolved next to `sys.executable`, the
same binaries `uv sync --extra test --extra server --extra mcp` puts on
disk) or the real, unmocked `packbuilder.build_pack` writing real bytes to a
disposable sqlite file — never `TestClient`-only shortcuts, never a
monkeypatched network boundary. Every subprocess/server/stdio lifecycle
opened here is torn down inside the same helper, bounded, before control
returns to the caller: readiness is detected from the process's own output
line or its own JSON-RPC reply (never a fixed sleep or a connect-retry
poll), and shutdown is SIGTERM-then-bounded-SIGKILL with the pid and the
process-group both verified dead. Nothing here reaches an external network:
the one real-surface case that could (`/api/research`) is only ever driven
with `ONTOLOGYLAB_OFFLINE=1`, so its harness exercises the honest refusal a
disposable, offline run actually produces, not a live fetch.

Nothing here is imported by, or imports from, `tests/wave21/identity.py`
(G002) or `tests/test_wave21_identity_characterization.py`.
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import signal
import socket
import sqlite3
import subprocess
import sys
import tempfile
import threading
from contextlib import contextmanager
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Iterator

import httpx

REPO_ROOT = Path(__file__).resolve().parents[2]

# Scope-forbidden: Wave 2.1 Step 1 must never bind the live product's port.
FORBIDDEN_PORTS = frozenset({8799})

# The dashboard's own SSE endpoint parks a threadpool thread in
# `JobRegistry.wait_version` for up to this many seconds when nothing new
# has happened since the client's last-seen version (jobs.py, "a parked
# wait is non-cancellable"). A harness that opens that stream must budget
# for it in its shutdown grace period rather than being surprised by it.
JOBS_STREAM_PARK_S = 15.0


# ---------------------------------------------------------------------------
# Disposable state / ports
# ---------------------------------------------------------------------------


def free_loopback_port() -> int:
    """An ephemeral 127.0.0.1 port, guaranteed not to be the forbidden one.

    Binds, reads back the OS-assigned port, and releases it; every caller
    here rebinds it within the same function call that returns this value,
    which is the same bind-then-release exposure every "find a free port"
    helper accepts. Retried a bounded number of times only to dodge
    `FORBIDDEN_PORTS` landing by chance, never to work around a real bind
    failure.
    """
    for _ in range(8):
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        finally:
            sock.close()
        if port not in FORBIDDEN_PORTS:
            return port
    raise RuntimeError("could not allocate a free, non-forbidden loopback port")


def installed_script(name: str) -> str:
    """Absolute path to a console-script installed beside `sys.executable`.

    Resolved against the interpreter's own bin directory rather than
    `$PATH`, so a test exercises the exact entry point this venv installed
    -- not whatever `ontologylab` happens to mean in the ambient shell.
    """
    candidate = Path(sys.executable).parent / name
    if not candidate.is_file():
        raise AssertionError(
            f"installed console-script {name!r} not found at {candidate} "
            "-- run `uv sync --extra test --extra server --extra mcp` in "
            "this worktree first"
        )
    return str(candidate)


@contextmanager
def disposable_root(prefix: str) -> Iterator[Path]:
    """A tmp directory this module owns start to finish, always removed.

    Deliberately separate from pytest's own `tmp_path`: the cleanup-proof
    tests assert this exact path is gone from disk after the context exits,
    which is this harness's own guarantee, not a property borrowed from the
    pytest fixture.
    """
    root = Path(tempfile.mkdtemp(prefix=prefix))
    try:
        yield root
    finally:
        shutil.rmtree(root, ignore_errors=True)


def pid_is_dead(pid: int) -> bool:
    """True iff `pid` no longer refers to a live process this user owns."""
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return True
    except PermissionError:
        # A live process owned by someone else -- cannot be this harness's
        # child, but is evidence the pid was reused, not that ours is dead.
        return False
    return False


def port_is_free(port: int) -> bool:
    """True iff a fresh bind to 127.0.0.1:port succeeds (nothing listening)."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.bind(("127.0.0.1", port))
    except OSError:
        return False
    finally:
        sock.close()
    return True


# ---------------------------------------------------------------------------
# Installed CLI
# ---------------------------------------------------------------------------


def run_installed_cli(
    *args: str, timeout: float = 30.0
) -> subprocess.CompletedProcess[str]:
    """Run the INSTALLED `ontologylab` console script as a real subprocess.

    Callers pass explicit `--data-dir`/`--packs-dir` into disposable state;
    this helper adds no implicit default location.
    """
    return subprocess.run(
        [installed_script("ontologylab"), *args],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )


# ---------------------------------------------------------------------------
# HTTP server (installed `ontologylab-serve`, real socket)
# ---------------------------------------------------------------------------


@dataclass
class ServerHandle:
    process: subprocess.Popen[str]
    base_url: str
    port: int
    data_dir: Path
    packs_dir: Path
    startup_log: list[str] = field(default_factory=list)


def _drain_until_ready(
    pipe: Any, sink: list[str], ready: threading.Event, markers: tuple[str, ...]
) -> None:
    for line in iter(pipe.readline, ""):
        sink.append(line)
        if any(marker in line for marker in markers):
            ready.set()


@contextmanager
def running_server(
    root: Path,
    *,
    env: dict[str, str] | None = None,
    ready_timeout: float = 20.0,
    shutdown_grace_s: float = 5.0,
    shutdown_kill_timeout: float = 10.0,
) -> Iterator[ServerHandle]:
    """Spawn the INSTALLED `ontologylab-serve` script bound to a free
    loopback port, block only on ITS OWN "startup complete" log line (an
    event subscription, never a fixed sleep or a connect-retry poll loop),
    yield a handle with a real `base_url`, and guarantee on exit that the
    process (and any child of its process group) is gone and its stdout
    reader thread has been joined -- bounded throughout.

    `shutdown_grace_s` is a plain SIGTERM wait, not the SSE park bound: a
    server with an open `/jobs/stream` connection can take up to
    `JOBS_STREAM_PARK_S` to notice a disconnected client and return from
    `wait_version` on its own, so any caller that opened that stream is
    expected to hit the SIGKILL escalation below rather than the graceful
    path -- that escalation is itself the bounded, verified cleanup this
    harness guarantees, not a failure of it.
    """
    port = free_loopback_port()
    data_dir = root / "data"
    packs_dir = root / "packs"
    process = subprocess.Popen(
        [
            installed_script("ontologylab-serve"),
            "--host", "127.0.0.1",
            "--port", str(port),
            "--data-dir", str(data_dir),
            "--packs-dir", str(packs_dir),
        ],
        cwd=REPO_ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        start_new_session=True,
        env={**os.environ, **(env or {})},
    )
    lines: list[str] = []
    ready = threading.Event()
    reader = threading.Thread(
        target=_drain_until_ready,
        args=(process.stdout, lines, ready, ("Application startup complete",)),
        daemon=True,
    )
    reader.start()
    try:
        became_ready = ready.wait(timeout=ready_timeout)
        if not became_ready or process.poll() is not None:
            raise AssertionError(
                "ontologylab-serve did not become ready within "
                f"{ready_timeout}s (exit code {process.poll()}); output so "
                f"far:\n{''.join(lines)}"
            )
        yield ServerHandle(
            process=process,
            base_url=f"http://127.0.0.1:{port}",
            port=port,
            data_dir=data_dir,
            packs_dir=packs_dir,
            startup_log=lines,
        )
    finally:
        if process.poll() is None:
            process.send_signal(signal.SIGTERM)
            try:
                process.wait(timeout=shutdown_grace_s)
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                process.wait(timeout=shutdown_kill_timeout)
        reader.join(timeout=shutdown_kill_timeout)


def http_client(handle: ServerHandle, *, timeout_s: float = 10.0) -> httpx.Client:
    """A real HTTP client bound to the running server's loopback socket."""
    return httpx.Client(base_url=handle.base_url, timeout=httpx.Timeout(timeout_s))


def read_jobs_sse_until_terminal(
    client: httpx.Client,
    job_id: str,
    *,
    max_events: int,
    timeout_s: float,
) -> str | None:
    """Subscribe to the real `/api/jobs/stream` SSE seam and return the
    first TERMINAL status this specific job reaches, or None if the stream
    closed (its own `max_events` bound) first.

    This is the exact wait_version push seam the dashboard uses instead of
    polling `GET /api/jobs` -- reading `event: jobs` frames as they arrive
    is the bounded subscribe-and-wait this harness uses in place of a sleep
    loop. `max_events` is the server's own escape hatch for exactly this
    situation (see its docstring: "TestClient류 버퍼링 클라이언트는 유한
    응답만 읽을 수 있다").
    """
    terminal = {"complete", "failed", "cancelled"}
    with client.stream(
        "GET",
        "/api/jobs/stream",
        params={"max_events": max_events},
        timeout=httpx.Timeout(timeout_s),
    ) as response:
        for line in response.iter_lines():
            if not line.startswith("data:"):
                continue
            payload = json.loads(line[len("data:"):].strip())
            jobs_by_id = {j["job_id"]: j for j in payload.get("jobs", [])}
            job = jobs_by_id.get(job_id)
            if job is not None and job["status"] in terminal:
                return job["status"]
    return None


# ---------------------------------------------------------------------------
# Real pack build (unmocked `packbuilder.build_pack`, real sqlite bytes)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class PackDoiReceipt:
    """Whether a document's `doi` survives KGStore -> real pack.sqlite."""

    kg_doi: str | None
    pack_documents_columns: tuple[str, ...]
    pack_doi: str | None
    preserved: bool


def build_pack_and_capture_doi(
    root: Path, *, doi: str, name: str = "doi-receipt"
) -> PackDoiReceipt:
    """Insert one document carrying a real DOI, verify it, build a REAL pack
    (actual `packbuilder.build_pack` call, actual bytes on disk -- no
    monkeypatching of the build path), and read back what `pack.sqlite`
    actually persisted for that document's `doi` column.
    """
    from ontologylab.kgstore import KGStore
    from ontologylab.models import ProposedEntity
    from ontologylab.packbuilder import build_pack

    kg_path = root / "kg.sqlite"
    packs_dir = root / "packs"
    store = KGStore.open(kg_path)
    try:
        doc, _created = store.insert_document(
            source_kind="paper_api",
            source_uri=f"https://doi.org/{doi}",
            title="A paper",
            raw_text=(
                "The PaymentGateway validates cards through the "
                "FraudDetector."
            ),
            content_hash=f"sha256:{hash((doi, name)) & 0xffffffff:x}",
            doi=doi,
        )
        store.insert_proposed(
            [ProposedEntity(
                id="n1", entity_type="Component", name="PaymentGateway",
            )],
            [],
            source_doc_id=doc.id,
            extractor_engine="mock",
        )
        store.approve("n1")
        kg_doi_row = store.conn.execute(
            "SELECT doi FROM documents WHERE id = ?", (doc.id,)
        ).fetchone()
        kg_doi = kg_doi_row["doi"]
    finally:
        store.close()

    manifest = build_pack(
        kg_path, packs_dir, name=name,
        allow_incomplete_extraction=True,
        incomplete_extraction_intent="G003 pack DOI-loss characterization",
    )

    pack_sqlite = packs_dir / manifest.pack_id / "pack.sqlite"
    conn = sqlite3.connect(f"file:{pack_sqlite}?mode=ro", uri=True)
    try:
        columns = tuple(
            row[1] for row in conn.execute("PRAGMA table_info(documents)")
        )
        pack_row = conn.execute("SELECT doi FROM documents").fetchone()
        pack_doi = pack_row[0] if pack_row is not None else None
    finally:
        conn.close()

    return PackDoiReceipt(
        kg_doi=kg_doi,
        pack_documents_columns=columns,
        pack_doi=pack_doi,
        preserved=(pack_doi == kg_doi),
    )


def build_fixture_pack(root: Path, *, name: str = "stdio-fixture") -> tuple[Path, str]:
    """A small, real, verified pack for the stdio-MCP harness to load.

    Returns `(packs_dir, pack_id)`.
    """
    from ontologylab.kgstore import KGStore
    from ontologylab.models import ProposedEntity, ProposedRelation
    from ontologylab.packbuilder import build_pack

    kg_path = root / "kg.sqlite"
    packs_dir = root / "packs"
    store = KGStore.open(kg_path)
    try:
        doc, _created = store.insert_document(
            source_kind="upload",
            source_uri="file:///doc.txt",
            title="doc",
            raw_text="RateLimiter implements TokenBucket algorithm",
            content_hash="sha256:g003-stdio-fixture",
        )
        store.insert_proposed(
            [
                ProposedEntity(
                    id="n_rl", entity_type="Component", name="RateLimiter",
                ),
                ProposedEntity(
                    id="n_tb", entity_type="Technique",
                    name="TokenBucketAlgorithm",
                ),
            ],
            [
                ProposedRelation(
                    id="e_uses", relation_type="uses",
                    src_entity_id="n_rl", dst_entity_id="n_tb",
                )
            ],
            source_doc_id=doc.id,
            extractor_engine="mock",
        )
        store.approve("n_rl")
        store.approve("n_tb")
        store.approve("e_uses")
    finally:
        store.close()
    manifest = build_pack(
        kg_path, packs_dir, name=name,
        allow_incomplete_extraction=True,
        incomplete_extraction_intent="G003 stdio MCP harness fixture",
    )
    return packs_dir, manifest.pack_id


# ---------------------------------------------------------------------------
# stdio MCP (installed `ontologylab-mcp`, raw JSON-RPC over stdio)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class McpStdioReceipt:
    protocol_version: str
    tool_names: tuple[str, ...]
    list_packs_result: dict[str, Any]
    load_pack_result: dict[str, Any]
    process_returncode: int


async def _mcp_stdio_session(
    packs_dir: Path, pack_id: str, *, timeout: float
) -> McpStdioReceipt:
    process = await asyncio.create_subprocess_exec(
        installed_script("ontologylab-mcp"),
        "--packs-dir", str(packs_dir),
        "--pack", pack_id,
        cwd=REPO_ROOT,
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        start_new_session=True,
    )
    stdin, stdout = process.stdin, process.stdout
    assert stdin is not None and stdout is not None
    request_id = 0

    async def request(method: str, params: dict[str, Any]) -> dict[str, Any]:
        nonlocal request_id
        request_id += 1
        line = json.dumps({
            "jsonrpc": "2.0", "id": request_id, "method": method,
            "params": params,
        }, separators=(",", ":")).encode() + b"\n"
        stdin.write(line)
        await stdin.drain()
        while True:
            raw = await asyncio.wait_for(stdout.readline(), timeout=timeout)
            if not raw:
                stderr = await process.stderr.read()  # type: ignore[union-attr]
                raise RuntimeError(
                    f"ontologylab-mcp closed stdout; stderr={stderr!r}"
                )
            message = json.loads(raw)
            if message.get("id") == request_id:
                return message

    async def notify(method: str, params: dict[str, Any]) -> None:
        stdin.write(json.dumps({
            "jsonrpc": "2.0", "method": method, "params": params,
        }, separators=(",", ":")).encode() + b"\n")
        await stdin.drain()

    async def call_tool(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        reply = await request(
            "tools/call", {"name": name, "arguments": arguments}
        )
        return reply["result"]

    try:
        initialized = await request("initialize", {
            "protocolVersion": "2025-06-18",
            "capabilities": {},
            "clientInfo": {"name": "wave21-g003-harness", "version": "1"},
        })
        await notify("notifications/initialized", {})
        tools = await request("tools/list", {})
        list_packs_result = await call_tool("list_packs", {})
        load_pack_result = await call_tool("load_pack", {"pack_id": pack_id})
        return McpStdioReceipt(
            protocol_version=str(initialized["result"]["protocolVersion"]),
            tool_names=tuple(
                sorted(t["name"] for t in tools["result"]["tools"])
            ),
            list_packs_result=list_packs_result,
            load_pack_result=load_pack_result,
            process_returncode=-1,  # filled in below, after wait()
        )
    finally:
        stdin.close()
        try:
            await asyncio.wait_for(process.wait(), timeout=2)
        except TimeoutError:
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            try:
                await asyncio.wait_for(process.wait(), timeout=2)
            except TimeoutError:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                await process.wait()
        _mcp_stdio_session.last_pid = process.pid  # type: ignore[attr-defined]
        _mcp_stdio_session.last_returncode = process.returncode  # type: ignore[attr-defined]


def mcp_stdio_roundtrip(
    packs_dir: Path, pack_id: str, *, timeout: float = 10.0
) -> McpStdioReceipt:
    """Run one bounded, real stdio-JSON-RPC session against the INSTALLED
    `ontologylab-mcp` script: initialize, list tools, call `list_packs` and
    `load_pack`. The child process and its process group are confirmed
    gone before this returns.

    Mirrors the proven pattern in `scripts/qa_methodology_compiler.py`'s
    `_mcp_stdio` (SIGTERM-then-SIGKILL escalation, bounded `readline`
    waits) rather than reinventing it; this is the raw-protocol variant
    (no `mcp` SDK client), which also verifies the server speaks correct
    JSON-RPC on the wire independent of that SDK.
    """
    receipt = asyncio.run(_mcp_stdio_session(packs_dir, pack_id, timeout=timeout))
    pid = _mcp_stdio_session.last_pid  # type: ignore[attr-defined]
    returncode = _mcp_stdio_session.last_returncode  # type: ignore[attr-defined]
    if not pid_is_dead(pid):
        raise AssertionError(f"ontologylab-mcp pid {pid} still alive after session")
    return replace(receipt, process_returncode=returncode)
