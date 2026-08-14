from __future__ import annotations

import asyncio
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

import pytest

from ontologylab.mcp_server import PackSession, build_mcp_app
from ontologylab.packbuilder import build_pack
from tests.test_method_pack import seed_method_pack_database


METHOD_TOOLS = {
    "get_method",
    "list_method_gaps",
    "list_methods",
    "trace_method",
}
FORBIDDEN = {
    "execute_method",
    "resolve_gap",
    "approve_bridge",
    "send_setpoint",
    "control_device",
    "write_method",
}


def _selected_pack(
    tmp_path: Path,
    *,
    name: str = "method-mcp",
) -> tuple[Path, str]:
    source_path = tmp_path / "source.sqlite"
    source = seed_method_pack_database(source_path)
    source.close()
    packs = tmp_path / "packs"
    manifest = build_pack(
        source_path,
        packs,
        name=name,
        allow_incomplete_extraction=True,
        incomplete_extraction_intent="Task8 selected Method MCP fixture",
        method_release_ids=("release-1",),
    )
    return packs, manifest.pack_id


def test_pack_session_method_queries_and_resources_preserve_bytes(
    tmp_path: Path,
) -> None:
    packs, pack_id = _selected_pack(tmp_path)
    pack_path = packs / pack_id / "pack.sqlite"
    before = pack_path.read_bytes()
    before_hash = hashlib.sha256(before).hexdigest()
    os.chmod(pack_path, 0o444)
    session = PackSession(packs)
    try:
        session.load_pack(pack_id)
        listed = session.list_methods(query="heat", limit=5)
        assert listed["methods"][0]["method_id"] == "method-1"
        assert listed["pack"]["pack_id"] == pack_id
        assert session.get_method("method-1", version=1)["method"]["id"] == (
            "method-1"
        )
        trace = session.trace_method("method-1", field_path="/temperature")
        assert trace["sources"][0]["receipt_ref"]
        assert session.list_method_gaps("method-1")["gaps"] == []
        assert session.resource_method(pack_id, "method-1")["method"]["id"] == (
            "method-1"
        )
        resource_trace = session.resource_method_trace(
            pack_id,
            "method-1",
            "%2Ftemperature",
        )
        assert resource_trace["field_path"] == "/temperature"
    finally:
        session.close()
    after = pack_path.read_bytes()
    assert after == before
    assert hashlib.sha256(after).hexdigest() == before_hash
    assert not list(pack_path.parent.glob("pack.sqlite-*"))


def test_method_resource_rejects_inactive_valid_pack(tmp_path: Path) -> None:
    # Given
    packs, active_id = _selected_pack(tmp_path / "active")
    other_packs, inactive_id = _selected_pack(
        tmp_path / "inactive",
        name="inactive-method-mcp",
    )
    (other_packs / inactive_id).rename(packs / inactive_id)
    session = PackSession(packs)
    try:
        session.load_pack(active_id)

        # When / Then
        with pytest.raises(ValueError, match="active physical pack"):
            session.resource_method(inactive_id, "method-1")
    finally:
        session.close()
def test_method_query_detects_deleted_active_database(tmp_path: Path) -> None:
    # Given
    packs, pack_id = _selected_pack(tmp_path)
    database = packs / pack_id / "pack.sqlite"
    session = PackSession(packs)
    try:
        session.load_pack(pack_id)
        database.unlink()

        # When / Then
        with pytest.raises(Exception, match="not found|integrity"):
            session.list_methods()
    finally:
        session.close()

def test_method_query_detects_manifest_methodology_mismatch(
    tmp_path: Path,
) -> None:
    # Given
    packs, pack_id = _selected_pack(tmp_path)
    manifest_path = packs / pack_id / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    session = PackSession(packs)
    try:
        session.load_pack(pack_id)
        manifest["methodology"]["method_count"] = 2
        manifest_path.write_text(
            json.dumps(manifest, sort_keys=True),
            encoding="utf-8",
        )

        # When / Then
        with pytest.raises(Exception, match="manifest|integrity"):
            session.list_methods()
    finally:
        session.close()


def test_symlink_pack_is_rejected(tmp_path: Path) -> None:
    # Given
    packs, pack_id = _selected_pack(tmp_path / "source")
    aliases = tmp_path / "aliases"
    aliases.mkdir()
    (aliases / pack_id).symlink_to(
        packs / pack_id,
        target_is_directory=True,
    )
    session = PackSession(aliases)
    try:
        # When / Then
        with pytest.raises(Exception, match="physical|symlink|canonical"):
            session.load_pack(pack_id)
    finally:
        session.close()


@pytest.mark.parametrize("filename", ["pack.sqlite", "manifest.json"])
def test_hardlinked_pack_file_is_rejected(
    tmp_path: Path,
    filename: str,
) -> None:
    # Given
    packs, pack_id = _selected_pack(tmp_path)
    target = packs / pack_id / filename
    (tmp_path / f"linked-{filename}").hardlink_to(target)
    session = PackSession(packs)
    try:
        # When / Then
        with pytest.raises(Exception, match="hard-linked"):
            session.load_pack(pack_id)
    finally:
        session.close()


def test_fastmcp_surface_is_exactly_additive(tmp_path: Path) -> None:
    pytest.importorskip("mcp")
    session = PackSession(tmp_path / "packs")
    try:
        async def surface() -> tuple[set[str], set[str]]:
            app = build_mcp_app(session)
            tools = {tool.name for tool in await app.list_tools()}
            templates = {
                str(template.uriTemplate)
                for template in await app.list_resource_templates()
            }
            return tools, templates

        first = asyncio.run(surface())
        second = asyncio.run(surface())
    finally:
        session.close()
    assert second == first
    tools, templates = second
    assert len(tools) == 15
    assert METHOD_TOOLS <= tools
    assert tools.isdisjoint(FORBIDDEN)
    assert not {
        name
        for name in tools
        if any(
            token in name
            for token in ("execute", "approve", "resolve_gap", "setpoint",
                          "control", "write")
        )
    }
    assert len(templates) == 7
    assert "pack://{pack_id}/method/{method_id}" in templates
    assert (
        "pack://{pack_id}/method/{method_id}/trace/{field_path}"
        in templates
    )


def test_mcp_qa_injected_hang_is_bounded_and_reaps_child() -> None:
    # Given
    command = [
        sys.executable,
        "scripts/qa_methodology_compiler.py",
        "mcp",
        "--timeout",
        "2",
    ]
    env = {
        **os.environ,
        "ONTOLOGYLAB_TASK8_MCP_INJECT_HANG": "1",
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONPATH": ".",
    }

    # When
    started = time.monotonic()
    result = subprocess.run(
        command,
        cwd=Path(__file__).parents[1],
        env=env,
        capture_output=True,
        text=True,
        timeout=6,
        check=False,
    )
    elapsed = time.monotonic() - started

    # Then
    assert result.returncode != 0
    assert elapsed < 6
    line = next(
        line for line in result.stdout.splitlines()
        if line.startswith("injected_child_pid=")
    )
    child_pid = int(line.partition("=")[2])
    with pytest.raises(ProcessLookupError):
        os.kill(child_pid, 0)


def test_selected_pack_method_payload_is_inert_json(tmp_path: Path) -> None:
    packs, pack_id = _selected_pack(tmp_path)
    session = PackSession(packs)
    try:
        session.load_pack(pack_id)
        payload = json.dumps(session.get_method("method-1"), sort_keys=True)
        assert "method-1" in payload
        assert session.store is not None
        assert session.store.conn.execute(
            "SELECT COUNT(*) FROM nodes"
        ).fetchone()[0] == 0
    finally:
        session.close()
