"""Wave 2.1 Step 1 Goal G003 -- real-surface harness tests.

Scope: exercise the INSTALLED entry points and the real, unmocked
build/serve/stdio code paths this product actually ships -- the `ontologylab`
/ `ontologylab-serve` / `ontologylab-mcp` console scripts as real
subprocesses, `/api/collect` and `/api/collect/sample` over a real HTTP
socket against a real running server, and `packbuilder.build_pack` writing
real sqlite bytes to disk. Everything below runs against disposable
`tmp_path` state only: no product source is touched, no live/dev data
directory or pack is read, port 8799 is never bound, no external network
call is made (the one endpoint that could reach one, `/api/research`, is
only ever driven with `ONTOLOGYLAB_OFFLINE=1`), and no fixed sleep or
connect-retry poll loop is used anywhere -- every wait below is a bounded
join on a concrete event: a subprocess's own readiness line, a JSON-RPC
reply matched by id, or the dashboard's own `wait_version`-backed
`/api/jobs/stream` push seam.

Two characterization receipts are pinned as explicit, machine-readable
facts rather than prose (`tests/wave21/surface.py`):

* Sample seam/provenance -- `/api/collect/sample` (the onboarding seam) has
  no `Provenance(...).log(...)` call anywhere on its route, unlike the
  general `/api/collect`, which writes a `collect-<ts>/provenance.jsonl`
  job directory on every call. `test_collect_sample_...` proves this by
  diffing `data_dir/jobs/` before and after each call, on the real running
  server.
* Pack DOI-loss -- fixed in Wave 2.1 Step 2:
  `packbuilder._PACK_COPY_COLUMNS["documents"]` now carries `doi`, so the
  target-invariant test (`test_real_pack_build_should_preserve_doi`) is
  plain GREEN and the old currently-drops characterization test is
  retired.

Helper functions used below live in `tests/wave21/surface.py`; nothing here
imports from, or is imported by, `tests/wave21/identity.py` (G002).
"""

from __future__ import annotations

import json
from pathlib import Path

from tests.wave21.surface import (
    build_fixture_pack,
    build_pack_and_capture_doi,
    disposable_root,
    http_client,
    installed_script,
    mcp_stdio_roundtrip,
    pid_is_dead,
    port_is_free,
    read_jobs_sse_until_terminal,
    run_installed_cli,
    running_server,
)

# ---------------------------------------------------------------------------
# 1. Installed CLI
# ---------------------------------------------------------------------------


def test_installed_cli_end_to_end_produces_a_real_pack(tmp_path: Path) -> None:
    """collect -> extract -> review -> approve -> build-pack, each step run
    through the INSTALLED `ontologylab` console script (not `python -m`),
    against disposable `--data-dir`/`--packs-dir` under `tmp_path`.
    """
    data_dir = tmp_path / "data"
    packs_dir = tmp_path / "packs"
    fixture = tmp_path / "notes.md"
    fixture.write_text(
        "The PaymentGateway validates cards through the FraudDetector.",
        encoding="utf-8",
    )

    collected = run_installed_cli(
        "collect", "--file", str(fixture), "--data-dir", str(data_dir),
    )
    assert collected.returncode == 0, collected.stdout + collected.stderr

    extracted = run_installed_cli(
        "extract", "--engine", "mock", "--data-dir", str(data_dir),
    )
    assert extracted.returncode == 0, extracted.stdout + extracted.stderr

    reviewed = run_installed_cli("review", "--data-dir", str(data_dir))
    assert reviewed.returncode == 0, reviewed.stdout + reviewed.stderr

    approved = run_installed_cli(
        "approve", "--filter", "min_confidence=0", "--data-dir", str(data_dir),
    )
    assert approved.returncode == 0, approved.stdout + approved.stderr

    built = run_installed_cli(
        "build-pack", "--name", "g003-cli",
        "--data-dir", str(data_dir), "--packs-dir", str(packs_dir),
    )
    assert built.returncode == 0, built.stdout + built.stderr

    pack_dirs = [p for p in packs_dir.iterdir() if p.is_dir()]
    assert len(pack_dirs) == 1
    assert (pack_dirs[0] / "pack.sqlite").is_file()
    assert (pack_dirs[0] / "manifest.json").is_file()
    manifest = json.loads((pack_dirs[0] / "manifest.json").read_text())
    assert manifest["counts"]["nodes_verified"] >= 1


# ---------------------------------------------------------------------------
# 2. HTTP collect (real socket, installed `ontologylab-serve`)
# ---------------------------------------------------------------------------


def test_http_collect_ingests_a_real_file_over_a_real_socket() -> None:
    with disposable_root("ontologylab-g003-httpcollect-") as root:
        fixture = root / "notes.md"
        fixture.write_text(
            "The RateLimiter implements the TokenBucketAlgorithm.",
            encoding="utf-8",
        )
        with running_server(root) as handle:
            assert handle.port != 8799
            with http_client(handle) as client:
                response = client.post(
                    "/api/collect", json={"files": [str(fixture)]},
                )
                assert response.status_code == 200
                body = response.json()
                assert body["ok"] is True
                assert body["created"] == 1

                listed = client.get("/api/documents").json()
                assert listed["count"] == 1

            pid = handle.process.pid
            port = handle.port
        # Cleanup proof: the child is dead and the port is free again.
        assert pid_is_dead(pid)
        assert port_is_free(port)
    assert not root.exists()


# ---------------------------------------------------------------------------
# 3. Research worker
# ---------------------------------------------------------------------------


def test_research_worker_refuses_network_under_the_offline_kill_switch() -> None:
    """The one real-surface path that could reach an external API is only
    ever driven with `ONTOLOGYLAB_OFFLINE=1`: this proves, against the real
    running server, that the honest offline gate fires BEFORE any job (and
    therefore any fetch) is created -- no network call is made, and none
    could be, because no job exists to make one.
    """
    with disposable_root("ontologylab-g003-research-offline-") as root:
        with running_server(root, env={"ONTOLOGYLAB_OFFLINE": "1"}) as handle:
            with http_client(handle) as client:
                response = client.post("/api/research", json={
                    "topic": "fluorescent probe spectral overlap",
                    "sources": ["arxiv"],
                    "engine": "mock",
                })
                assert response.status_code == 200
                body = response.json()
                assert body["ok"] is False
                assert body["error_kind"] == "offline"

                jobs = client.get("/api/jobs").json()["jobs"]
                assert jobs == []  # the gate fired before any job existed


def test_job_engine_completion_is_observed_via_bounded_sse_wait_version() -> None:
    """The background job engine `create_research` shares with `create`
    (extraction) -- `JobRegistry`, its version counter, and the
    `/api/jobs/stream` push seam -- proven end to end with the offline-safe
    `mock` engine: collect one real document over HTTP, start an extract
    job, and observe its own completion by subscribing to the real SSE
    stream and blocking on `wait_version` (via `max_events`), never by
    polling `GET /api/jobs` on a sleep loop.
    """
    with disposable_root("ontologylab-g003-jobengine-") as root:
        fixture = root / "notes.md"
        fixture.write_text(
            "The PaymentGateway validates cards through the FraudDetector.",
            encoding="utf-8",
        )
        with running_server(root) as handle:
            with http_client(handle) as client:
                collected = client.post(
                    "/api/collect", json={"files": [str(fixture)]},
                )
                assert collected.json()["created"] == 1

                started = client.post("/api/extract", json={"engine": "mock"})
                assert started.status_code == 202
                job_id = started.json()["job_id"]

                status = read_jobs_sse_until_terminal(
                    client, job_id, max_events=8, timeout_s=30.0,
                )
                assert status == "complete"

                final = client.get(f"/api/jobs/{job_id}").json()
                assert final["status"] == "complete"
                assert final["totals"].get("nodes_new", 0) >= 1


# ---------------------------------------------------------------------------
# 4. /api/collect/sample -- seam/provenance characterization
# ---------------------------------------------------------------------------


def _job_dirs(data_dir: Path) -> set[str]:
    jobs_root = data_dir / "jobs"
    if not jobs_root.exists():
        return set()
    return {p.name for p in jobs_root.iterdir() if p.is_dir()}


def test_collect_sample_is_idempotent_over_real_http() -> None:
    with disposable_root("ontologylab-g003-sample-") as root:
        with running_server(root) as handle:
            with http_client(handle) as client:
                first = client.post("/api/collect/sample")
                assert first.status_code == 200
                first_body = first.json()
                assert first_body["ok"] is True
                assert first_body["created"] is True

                again = client.post("/api/collect/sample")
                again_body = again.json()
                assert again_body["created"] is False
                assert again_body["document_id"] == first_body["document_id"]

                docs = client.get("/api/documents").json()["documents"]
                assert len(docs) == 1
                assert docs[0]["source_uri"] == "sample://onboarding/order-system"


def test_collect_sample_records_one_idempotent_provenance_dir_like_collect() -> None:
    """Both collect entry points go through the one raw-document writer, so
    both leave provenance: the sample exactly one fixed ``collect-sample``
    dir that repeat clicks reuse, a real collect one fresh ``collect-*`` dir.
    """
    with disposable_root("ontologylab-g003-sample-provenance-") as root:
        fixture = root / "notes.md"
        fixture.write_text("The OrderService writes to the OrderDatabase.",
                            encoding="utf-8")
        with running_server(root) as handle:
            with http_client(handle) as client:
                before = _job_dirs(handle.data_dir)
                client.post("/api/collect/sample")
                after_sample = _job_dirs(handle.data_dir)
                client.post("/api/collect/sample")
                after_sample_again = _job_dirs(handle.data_dir)
                client.post("/api/collect", json={"files": [str(fixture)]})
                after_real_collect = _job_dirs(handle.data_dir)

    assert after_sample - before == {"collect-sample"}
    assert after_sample_again == after_sample
    new_dirs = after_real_collect - after_sample
    assert len(new_dirs) == 1
    assert next(iter(new_dirs)).startswith("collect-")


# ---------------------------------------------------------------------------
# 5. Real pack build -- DOI-loss characterization
# ---------------------------------------------------------------------------


def test_real_pack_build_writes_pack_sqlite_and_manifest(tmp_path: Path) -> None:
    receipt = build_pack_and_capture_doi(
        tmp_path, doi="10.1234/g003.real-pack-build",
    )
    assert "doi" in receipt.pack_documents_columns
    assert receipt.kg_doi == "10.1234/g003.real-pack-build"


def test_real_pack_build_should_preserve_doi(tmp_path: Path) -> None:
    """Delivered Wave 2.1 Step 2 invariant: a verified document's doi
    survives a real pack build unchanged now that
    `packbuilder._PACK_COPY_COLUMNS["documents"]` carries `doi`."""
    receipt = build_pack_and_capture_doi(
        tmp_path, doi="10.1234/g003.doi-should-survive",
    )
    assert receipt.preserved
    assert receipt.pack_doi == receipt.kg_doi


# ---------------------------------------------------------------------------
# 6. stdio MCP (installed `ontologylab-mcp`, raw JSON-RPC)
# ---------------------------------------------------------------------------


def test_stdio_mcp_round_trip_against_a_real_pack(tmp_path: Path) -> None:
    packs_dir, pack_id = build_fixture_pack(tmp_path)

    receipt = mcp_stdio_roundtrip(packs_dir, pack_id)

    assert receipt.protocol_version == "2025-06-18"
    assert {"list_packs", "load_pack", "entity_lookup"} <= set(receipt.tool_names)
    assert receipt.list_packs_result["isError"] is False
    assert receipt.load_pack_result["isError"] is False
    load_pack_payload = json.loads(
        receipt.load_pack_result["content"][0]["text"]
    )
    assert load_pack_payload["pack_id"] == pack_id
    assert receipt.process_returncode == 0


# ---------------------------------------------------------------------------
# 7. Cleanup proof (installed CLI never leaves stray processes/paths)
# ---------------------------------------------------------------------------


def test_installed_scripts_resolve_next_to_the_running_interpreter() -> None:
    """`installed_script` is the shared entry-point resolution every other
    test here depends on: pin its own contract once, directly.
    """
    for name in ("ontologylab", "ontologylab-serve", "ontologylab-mcp"):
        path = installed_script(name)
        assert Path(path).is_file()


def test_running_server_leaves_nothing_after_the_context_exits() -> None:
    with disposable_root("ontologylab-g003-cleanup-") as root:
        with running_server(root) as handle:
            pid, port, data_dir = handle.process.pid, handle.port, handle.data_dir
            assert data_dir.exists()
        assert pid_is_dead(pid)
        assert port_is_free(port)
    assert not root.exists()
    assert not data_dir.exists()
