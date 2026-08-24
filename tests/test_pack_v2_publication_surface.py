"""Valid v2 publication must verify, activate, serve, and diff."""
# noqa: SIZE_OK — single SUT surface matrix; Task 11 repair owns this file

from __future__ import annotations

import json
import os
import select
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Final, TypeAlias

JsonValue: TypeAlias = (
    str | int | float | bool | None | list["JsonValue"] | dict[str, "JsonValue"]
)

from ontologylab.migration import compute_source_fingerprint
from ontologylab.pack_readiness import receipt_inventory
from ontologylab.pack_verifier import verify_pack
from ontologylab.packdiff import diff_packs
from ontologylab.packbuilder import build_pack
from ontologylab.verified_pack_reader import activate_pack
from tests.test_pack_readiness_refusal import (
    _plant_c036,
    _ready_fixture,
    _request_sourced,
)


_INTEGRITY: Final = "sha256-receipt-not-signature"
_READ: Final = 0o222


def _reviewed_pack(tmp_path: Path, *, name: str) -> tuple[Path, str]:
    fixture = _ready_fixture(tmp_path / "kg")
    _request_sourced(fixture.store.conn)
    inventory = receipt_inventory(fixture.store.conn)
    _plant_c036(
        fixture.store.conn,
        generation=fixture.generation,
        fingerprint=compute_source_fingerprint(fixture.store.conn),
        root=inventory.root,
    )
    fixture.store.conn.commit()
    packs = tmp_path / "packs"
    manifest = build_pack(
        fixture.kg, packs, name=name, evidence_mode="full",
    )
    fixture.store.close()
    return packs, manifest.pack_id


def _rpc(
    proc: subprocess.Popen[str], method: str, params: dict[str, JsonValue], req_id: int,
) -> dict[str, JsonValue]:
    payload = json.dumps(
        {"jsonrpc": "2.0", "id": req_id, "method": method, "params": params},
        separators=(",", ":"),
    )
    assert proc.stdin is not None and proc.stdout is not None
    proc.stdin.write(payload + "\n")
    proc.stdin.flush()
    while True:
        ready, _, _ = select.select([proc.stdout], [], [], 15.0)
        if not ready:
            raise TimeoutError(f"stdio timeout waiting for {method}")
        raw = proc.stdout.readline()
        if not raw:
            err = proc.stderr.read() if proc.stderr is not None else ""
            raise RuntimeError(f"stdio closed on {method}: {err}")
        message = json.loads(raw)
        if message.get("id") == req_id:
            return message


def test_valid_ready_v2_pack_verifies_activates_serves_and_diffs(
    tmp_path: Path,
) -> None:
    packs_a, pack_a = _reviewed_pack(tmp_path / "a", name="v2-surf-a")
    pack_dir = packs_a / pack_a
    payload = json.loads((pack_dir / "manifest.json").read_text(encoding="utf-8"))
    assert payload["pack_schema_version"] == 2
    assert payload["integrity_model"] == _INTEGRITY
    assert isinstance(payload["artifact_inventory"], list)
    assert payload["artifact_inventory"]
    paths = [str(item["path"]) for item in payload["artifact_inventory"]]
    assert "manifest.json" not in paths
    assert paths == sorted(paths)
    assert payload["sqlite_hash"].startswith("sha256:")
    assert payload["pack_content_hash"].startswith("sha256:")
    assert "reviewed" in payload["capabilities"]
    assert "sourced-answer-v2" in payload["capabilities"]
    for path in pack_dir.rglob("*"):
        if path.is_file():
            assert (path.stat().st_mode & _READ) == 0
    receipt = verify_pack(pack_dir, working=tmp_path / "a" / "kg")
    assert receipt.pack_id == pack_a
    snapshot = activate_pack(pack_dir, working=tmp_path / "a" / "kg")
    try:
        assert snapshot.pack_id == pack_a
        assert snapshot.content_hash == payload["pack_content_hash"]
    finally:
        snapshot.close()

    proc = subprocess.Popen(
        [
            sys.executable, "-m", "ontologylab.mcp_server",
            "--packs-dir", str(packs_a), "--pack", pack_a,
        ],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,
    )
    try:
        initialized = _rpc(proc, "initialize", {
            "protocolVersion": "2025-06-18",
            "capabilities": {},
            "clientInfo": {"name": "t11-repair", "version": "1"},
        }, 1)
        assert initialized.get("result")
        assert proc.stdin is not None
        proc.stdin.write(json.dumps({
            "jsonrpc": "2.0",
            "method": "notifications/initialized",
            "params": {},
        }, separators=(",", ":")) + "\n")
        proc.stdin.flush()
        tools = _rpc(proc, "tools/list", {}, 2)
        listed_tools = tools["result"]
        assert isinstance(listed_tools, dict)
        raw_tools = listed_tools["tools"]
        assert isinstance(raw_tools, list)
        tool_names = {
            str(item["name"])
            for item in raw_tools
            if isinstance(item, dict)
        }
        assert "list_packs" in tool_names
        listed = _rpc(proc, "tools/call", {
            "name": "list_packs", "arguments": {},
        }, 3)
        assert listed.get("result")
        resources = _rpc(proc, "resources/read", {
            "uri": f"pack://{pack_a}/manifest",
        }, 4)
        assert resources.get("result")
        lookup = _rpc(proc, "tools/call", {
            "name": "entity_lookup",
            "arguments": {"name": "PaymentGateway"},
        }, 5)
        assert lookup.get("result")
    finally:
        if proc.stdin is not None:
            proc.stdin.close()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            os.killpg(proc.pid, 15)
            proc.wait(timeout=5)

    packs_b, pack_b = _reviewed_pack(tmp_path / "b", name="v2-surf-b")
    shutil.copytree(packs_b / pack_b, packs_a / pack_b)
    diff = diff_packs(packs_a, pack_a, pack_b)
    assert "nodes" in diff
    assert "edges" in diff


def test_v1_pack_omits_v2_inventory_when_evidence_mode_absent(tmp_path: Path) -> None:
    kg = tmp_path / "kg.sqlite"
    packs = tmp_path / "packs"
    from ontologylab.kgstore import KGStore
    from tests.factories import make_entity

    store = KGStore.open(kg)
    document, _created = store.insert_document(
        source_kind="upload",
        source_uri="file:///v1.txt",
        title="v1",
        raw_text="RateLimiter uses TokenBucket",
        content_hash="v1-surface-hash",
    )
    store.insert_proposed(
        [make_entity("RateLimiter")],
        [],
        source_doc_id=document.id,
        extractor_engine="mock",
    )
    node_id = store.conn.execute("SELECT id FROM nodes").fetchone()["id"]
    store.approve(node_id)
    store.close()
    manifest = build_pack(
        kg, packs, name="legacy-surface",
        allow_incomplete_extraction=True,
        incomplete_extraction_intent="v1-compat",
    )
    payload = json.loads(
        (packs / manifest.pack_id / "manifest.json").read_text(encoding="utf-8"),
    )
    assert payload.get("pack_schema_version") != 2
    assert "artifact_inventory" not in payload
    assert payload.get("integrity_model") != _INTEGRITY
