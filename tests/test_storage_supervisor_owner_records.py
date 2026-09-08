from __future__ import annotations

import json
import os
import signal
import sqlite3
import subprocess
import sys
from enum import StrEnum, unique
from pathlib import Path
from typing import assert_never

import pytest
from pydantic import BaseModel, ConfigDict, Field

from ontologylab.kgstore import KGStore
from tests.macos_supervisor_support import (
    AppFixture,
    build_supervisor,
    launch,
    managed_process,
    open_arguments,
    read_event,
    run,
    stop,
)


@unique
class PathForgery(StrEnum):
    FORGED = "forged"
    SYMLINK = "symlink"
    ALIAS = "alias"


class ProcessFingerprintFixture(BaseModel):
    model_config = ConfigDict(frozen=True, strict=True, extra="forbid")

    executable_path: str = Field(alias="executablePath")
    start_seconds: int = Field(alias="startSeconds")
    start_microseconds: int = Field(alias="startMicroseconds")
    uid: int


class OwnerRecordFixture(BaseModel):
    model_config = ConfigDict(frozen=True, strict=True, extra="forbid")

    schema_name: str = Field(alias="schema")
    version: str
    port: int
    supervisor_pid: int = Field(alias="pid")
    child_pid: int = Field(alias="childPid")
    nonce: str
    bundle_identifier: str = Field(alias="bundleIdentifier")
    supervisor_executable_path: str = Field(alias="supervisorExecutablePath")
    backend_fingerprint: ProcessFingerprintFixture = Field(alias="backendFingerprint")


def _database(app: AppFixture) -> Path:
    root = Path(app.environment["ONTOLOGYLAB_APP_SUPPORT_ROOT"])
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    data = root / "data"
    data.mkdir(mode=0o700, exist_ok=True)
    return data / "kg.sqlite"


def _older(app: AppFixture) -> Path:
    path = _database(app)
    KGStore.open(path).close()
    connection = sqlite3.connect(path)
    try:
        connection.execute("PRAGMA journal_mode=DELETE")
        connection.execute("DROP TABLE ontologylab_storage_metadata")
        connection.commit()
    finally:
        connection.close()
    return path


def _capture_owner_record(app: AppFixture) -> OwnerRecordFixture:
    with managed_process(launch(app, "hold")) as process:
        read_event(process, "OPEN:")
        state = OwnerRecordFixture.model_validate_json(
            (app.state_root / "instance.json").read_bytes(), strict=True
        )
        stop(process)
    return state


def _write_owner_record(app: AppFixture, state: OwnerRecordFixture) -> None:
    app.state_root.mkdir(mode=0o700, parents=True, exist_ok=True)
    path = app.state_root / "instance.json"
    path.write_text(state.model_dump_json(by_alias=True), encoding="utf-8")
    path.chmod(0o600)


def _orphan_recorded_holder(
    app: AppFixture,
) -> tuple[OwnerRecordFixture, int]:
    first = launch(app, "hold_sqlite", ONTOLOGYLAB_READY_TIMEOUT_MS="10000")
    read_event(first, "OPEN:", timeout=10)
    state = OwnerRecordFixture.model_validate_json(
        (app.state_root / "instance.json").read_bytes(), strict=True
    )
    first.kill()
    first.wait(timeout=4)
    return state, state.child_pid


def _stop_test_holder(pid: int) -> None:
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        pid = -1


def test_forged_owner_version_refuses_before_signal(tmp_path: Path) -> None:
    app = build_supervisor(tmp_path / "forged-version")
    _older(app)
    state, old_pid = _orphan_recorded_holder(app)
    _write_owner_record(app, state.model_copy(update={"version": "9.9.9"}))
    try:
        result = run(app, "real", ONTOLOGYLAB_READY_TIMEOUT_MS="10000")

        assert result.returncode != 0
        assert "owner_identity" in result.stderr
        assert open_arguments(result.stdout) == []
        os.kill(old_pid, 0)
    finally:
        _stop_test_holder(old_pid)


@pytest.mark.parametrize("path_kind", tuple(PathForgery))
def test_forged_owner_supervisor_path_refuses_before_signal(
    tmp_path: Path,
    path_kind: PathForgery,
) -> None:
    app = build_supervisor(tmp_path / f"forged-path-{path_kind.value}")
    _older(app)
    state, old_pid = _orphan_recorded_holder(app)
    match path_kind:
        case PathForgery.FORGED:
            forged_path = str(tmp_path / "forged-supervisor")
        case PathForgery.SYMLINK:
            forged = tmp_path / "symlink-supervisor"
            forged.symlink_to(app.executable)
            forged_path = str(forged)
        case PathForgery.ALIAS:
            recorded = state.supervisor_executable_path
            forged_path = (
                recorded.removeprefix("/private")
                if recorded.startswith("/private/")
                else "/private" + recorded
            )
        case unreachable:
            assert_never(unreachable)
    _write_owner_record(
        app,
        state.model_copy(update={"supervisor_executable_path": forged_path}),
    )
    try:
        result = run(app, "real", ONTOLOGYLAB_READY_TIMEOUT_MS="10000")

        assert result.returncode != 0
        assert "owner_identity" in result.stderr
        assert open_arguments(result.stdout) == []
        os.kill(old_pid, 0)
    finally:
        _stop_test_holder(old_pid)


def test_fake_arbitrary_instance_record_refuses_without_counting_as_proof(
    tmp_path: Path,
) -> None:
    app = build_supervisor(tmp_path / "fake-record")
    _older(app)
    app.state_root.mkdir(mode=0o700, parents=True, exist_ok=True)
    record = app.state_root / "instance.json"
    record.write_text('{"childPid":1}', encoding="utf-8")
    record.chmod(0o600)

    result = run(app, "real")

    assert result.returncode != 0
    assert "owner_record_invalid" in result.stderr
    assert open_arguments(result.stdout) == []


def test_valid_but_stale_instance_record_refuses(tmp_path: Path) -> None:
    app = build_supervisor(tmp_path / "stale-record")
    _older(app)
    state = _capture_owner_record(app)
    _write_owner_record(app, state)

    result = run(app, "real")

    assert result.returncode != 0
    assert "stale_owner_record" in result.stderr
    assert open_arguments(result.stdout) == []


def test_reused_pid_fingerprint_mismatch_refuses_without_signal(
    tmp_path: Path,
) -> None:
    app = build_supervisor(tmp_path / "reused-pid")
    path = _older(app)
    state = _capture_owner_record(app)
    holder_script = tmp_path / "reused-pid-holder"
    holder_script.write_text(
        f"#!{sys.executable}\n"
        "import sqlite3, sys\n"
        "connection = sqlite3.connect(sys.argv[1])\n"
        "connection.execute('SELECT name FROM sqlite_schema LIMIT 1').fetchone()\n"
        "print('HOLDER:READY', flush=True)\n"
        "sys.stdin.read()\n",
        encoding="utf-8",
    )
    holder_script.chmod(0o755)
    holder = subprocess.Popen(
        [str(holder_script), str(path)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        text=True,
    )
    try:
        read_event(holder, "HOLDER:READY", timeout=4)
        _write_owner_record(
            app,
            state.model_copy(update={"child_pid": holder.pid}),
        )

        result = run(app, "real")

        assert result.returncode != 0
        assert "owner_fingerprint_mismatch" in result.stderr
        assert holder.poll() is None
        assert open_arguments(result.stdout) == []
    finally:
        holder.terminate()
        holder.wait(timeout=4)


def test_malformed_record_never_authorizes_live_writer(tmp_path: Path) -> None:
    app = build_supervisor(tmp_path / "malformed-live")
    path = _older(app)
    writer_script = tmp_path / "exact-old-backend"
    writer_script.write_text(
        f"#!{sys.executable}\n"
        "import os, sqlite3, sys\n"
        "db = sqlite3.connect(os.environ['WRITER_DB'])\n"
        "db.execute('BEGIN IMMEDIATE')\n"
        "print('WRITER:READY', flush=True)\n"
        "sys.stdin.read()\n",
        encoding="utf-8",
    )
    writer_script.chmod(0o755)
    writer = subprocess.Popen(
        [str(writer_script)],
        env=app.environment | {"WRITER_DB": str(path)},
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        text=True,
    )
    try:
        read_event(writer, "WRITER:READY", timeout=4)
        app.state_root.mkdir(mode=0o700, parents=True, exist_ok=True)
        instance = app.state_root / "instance.json"
        instance.write_text(
            json.dumps({"childPid": writer.pid}), encoding="utf-8"
        )
        instance.chmod(0o600)

        result = run(app, "real", ONTOLOGYLAB_READY_TIMEOUT_MS="10000")

        assert result.returncode != 0
        assert "owner_record_invalid" in result.stderr
        assert writer.poll() is None
        assert open_arguments(result.stdout) == []
    finally:
        writer.terminate()
        writer.wait(timeout=4)
