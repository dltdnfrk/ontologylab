from __future__ import annotations

import json
import os
import signal
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

from ontologylab.kgstore import KGStore
from tests.macos_supervisor_support import (
    AppFixture,
    build_supervisor,
    launch,
    managed_process,
    open_arguments,
    read_event,
    stop,
)


def _database(app: AppFixture) -> Path:
    root = Path(app.environment["ONTOLOGYLAB_APP_SUPPORT_ROOT"])
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    data = root / "data"
    data.mkdir(mode=0o700, exist_ok=True)
    return data / "kg.sqlite"


def _real_backend(app: AppFixture) -> None:
    backend = app.executable.parent.parent / "Resources/ontologylab-serve-desktop"
    backend.unlink()
    backend.write_text(
        f"#!{sys.executable}\nfrom ontologylab.serve_desktop import main\nmain()\n",
        encoding="utf-8",
    )
    backend.chmod(0o755)


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


def test_real_supervisor_receipt_ignores_similarly_named_decoy(
    tmp_path: Path,
) -> None:
    app = build_supervisor(tmp_path / "decoy")
    _real_backend(app)
    _older(app)
    decoy_path = tmp_path / "ontologylab-old-backend-decoy"
    decoy_path.write_text(
        f"#!{sys.executable}\nimport sys\nsys.stdin.read()\n",
        encoding="utf-8",
    )
    decoy_path.chmod(0o755)
    decoy = subprocess.Popen([str(decoy_path)], stdin=subprocess.PIPE)
    try:
        assert decoy.poll() is None
        with managed_process(
            launch(app, "real", ONTOLOGYLAB_READY_TIMEOUT_MS="10000")
        ) as process:
            read_event(process, "OPEN:", timeout=10)
            _stdout, stderr = stop(process)
        assert process.returncode == 0, stderr
        assert decoy.poll() is None
    finally:
        decoy.terminate()
        decoy.wait(timeout=4)


def test_real_supervisor_refuses_unrecorded_canonical_sqlite_holder(
    tmp_path: Path,
) -> None:
    app = build_supervisor(tmp_path / "unrecorded-holder")
    _real_backend(app)
    path = _older(app)
    chat = path.parent / "chat.sqlite"
    connection = sqlite3.connect(chat)
    try:
        connection.execute("CREATE TABLE turns (value TEXT)")
        connection.commit()
    finally:
        connection.close()
    holder_script = tmp_path / "unrecorded-old-backend"
    holder_script.write_text(
        f"#!{sys.executable}\n"
        "import sqlite3, sys\n"
        "connections = [sqlite3.connect(path) for path in sys.argv[1:]]\n"
        "[connection.execute('SELECT name FROM sqlite_schema LIMIT 1').fetchone() "
        "for connection in connections]\n"
        "print('HOLDER:READY', flush=True)\n"
        "sys.stdin.read()\n",
        encoding="utf-8",
    )
    holder_script.chmod(0o755)
    holder = subprocess.Popen(
        [str(holder_script), str(path), str(chat)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        text=True,
    )
    try:
        read_event(holder, "HOLDER:READY", timeout=4)
        process = launch(app, "real", ONTOLOGYLAB_READY_TIMEOUT_MS="10000")
        stdout, stderr = process.communicate(timeout=10)
        assert process.returncode != 0
        assert open_arguments(stdout) == []
        assert "unrecorded_backend" in stderr
        assert holder.poll() is None
    finally:
        holder.terminate()
        holder.wait(timeout=4)


def test_recorded_exact_old_backend_stops_before_upgrade_ready(
    tmp_path: Path,
) -> None:
    app = build_supervisor(tmp_path / "recorded-holder")
    path = _older(app)
    chat = path.parent / "chat.sqlite"
    connection = sqlite3.connect(chat)
    try:
        connection.execute("CREATE TABLE turns (value TEXT)")
        connection.commit()
    finally:
        connection.close()
    first = launch(app, "hold_sqlite", ONTOLOGYLAB_READY_TIMEOUT_MS="10000")
    read_event(first, "OPEN:", timeout=10)
    state = json.loads((app.state_root / "instance.json").read_text(encoding="utf-8"))
    old_backend_pid = int(state["childPid"])
    first.kill()
    first.wait(timeout=4)
    _real_backend(app)
    try:
        with managed_process(
            launch(app, "real", ONTOLOGYLAB_READY_TIMEOUT_MS="10000")
        ) as upgraded:
            opened = read_event(upgraded, "OPEN:", timeout=10)
            _stdout, stderr = stop(upgraded)
        assert upgraded.returncode == 0, stderr
        assert len(open_arguments(opened)) == 1
        root = Path(app.environment["ONTOLOGYLAB_APP_SUPPORT_ROOT"])
        journal = json.loads(
            root.joinpath("upgrade-journal.json").read_text(encoding="utf-8")
        )
        assert journal["quiescence_proof_kind"] == "stopped_backend"
        assert journal["quiescence_initial_holder_pids"] == [old_backend_pid]
        assert journal["quiescence_verified_backend_pid"] == old_backend_pid
        assert journal["quiescence_verified_backend_version"] == "0.1.0"
        assert journal["quiescence_verified_bundle_identifier"] == (
            "test.ontologylab.supervisor"
        )
        assert journal["quiescence_verified_executable_path"]
        assert journal["quiescence_verified_start_marker"]
        assert journal["quiescence_verified_uid"] == os.getuid()
        assert journal["quiescence_final_holder_pids"] == []
        assert journal["quiescence_inspected_at_ns"] > 0
        assert journal["quiescence_exit_observed"] is True
        assert journal["quiescence_signals"][-1] == "exit-observed"
        with pytest.raises(ProcessLookupError):
            os.kill(old_backend_pid, 0)
    finally:
        try:
            os.kill(old_backend_pid, signal.SIGTERM)
        except ProcessLookupError:
            old_backend_pid = -1


def test_no_data_new_install_uses_explicit_empty_holder_proof(
    tmp_path: Path,
) -> None:
    app = build_supervisor(tmp_path / "new-install")
    _real_backend(app)
    with managed_process(
        launch(app, "real", ONTOLOGYLAB_READY_TIMEOUT_MS="10000")
    ) as process:
        read_event(process, "OPEN:", timeout=10)
        receipt = json.loads(
            (app.state_root / "quiescence.json").read_text(encoding="utf-8")
        )
        _stdout, stderr = stop(process)
    assert process.returncode == 0, stderr
    assert receipt["proof_kind"] == "no_existing_backend"
    assert receipt["initial_holder_pids"] == []
    assert receipt["final_holder_pids"] == []
    assert len(receipt["inspected_paths"]) == 6
