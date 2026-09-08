from __future__ import annotations

import hashlib
import sqlite3
import subprocess
import sys
from collections.abc import Callable
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
    run,
    stop,
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _database(app: AppFixture) -> Path:
    root = Path(app.environment["ONTOLOGYLAB_APP_SUPPORT_ROOT"])
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    data_dir = root / "data"
    data_dir.mkdir(mode=0o700, exist_ok=True)
    return data_dir / "kg.sqlite"


def _real_backend(app: AppFixture) -> None:
    backend = app.executable.parent.parent / "Resources/ontologylab-serve-desktop"
    backend.unlink()
    backend.write_text(
        f"#!{sys.executable}\nfrom ontologylab.serve_desktop import main\nmain()\n",
        encoding="utf-8",
    )
    backend.chmod(0o755)


def _persist(path: Path, sql: str) -> None:
    connection = sqlite3.connect(path)
    try:
        connection.execute("PRAGMA journal_mode=DELETE")
        connection.execute(sql)
        connection.commit()
    finally:
        connection.close()


def _older(app: AppFixture) -> Path:
    path = _database(app)
    KGStore.open(path).close()
    _persist(path, "DROP TABLE ontologylab_storage_metadata")
    return path


def _newer(app: AppFixture) -> Path:
    path = _database(app)
    KGStore.open(path).close()
    _persist(path, "UPDATE ontologylab_storage_metadata SET storage_version = 999")
    return path


def _unknown(app: AppFixture) -> Path:
    path = _database(app)
    connection = sqlite3.connect(path)
    try:
        connection.execute("CREATE TABLE unrelated (value TEXT)")
        connection.commit()
    finally:
        connection.close()
    return path


def _missing_version(app: AppFixture) -> Path:
    path = _database(app)
    KGStore.open(path).close()
    _persist(
        path,
        "DELETE FROM ontologylab_storage_metadata WHERE component = 'settings'",
    )
    return path


def _corrupt(app: AppFixture) -> Path:
    path = _database(app)
    path.write_bytes(b"malformed sqlite")
    return path


def test_current_storage_reaches_supervisor_ready_and_exits_exactly(
    tmp_path: Path,
) -> None:
    app = build_supervisor(tmp_path / "current")
    _real_backend(app)
    path = _database(app)
    KGStore.open(path).close()

    with managed_process(
        launch(app, "real", ONTOLOGYLAB_READY_TIMEOUT_MS="10000")
    ) as process:
        read_event(process, "OPEN:", timeout=10)
        _stdout, stderr = stop(process)

    assert process.returncode == 0, stderr
    with sqlite3.connect(path) as connection:
        versions = {
            row[0]
            for row in connection.execute(
                "SELECT storage_version FROM ontologylab_storage_metadata"
            )
        }
    assert versions == {1}


def test_supervisor_upgrades_supported_older_before_ready(tmp_path: Path) -> None:
    app = build_supervisor(tmp_path / "older-upgrade")
    _real_backend(app)
    path = _older(app)
    root = Path(app.environment["ONTOLOGYLAB_APP_SUPPORT_ROOT"])
    old_token = "f" * 64
    (path.parent / "session.token").write_text(old_token, encoding="utf-8")

    with managed_process(
        launch(app, "real", ONTOLOGYLAB_READY_TIMEOUT_MS="10000")
    ) as process:
        read_event(process, "OPEN:", timeout=10)
        _stdout, stderr = stop(process)

    assert process.returncode == 0, stderr
    with sqlite3.connect(path) as connection:
        assert {
            row[0]
            for row in connection.execute(
                "SELECT storage_version FROM ontologylab_storage_metadata"
            )
        } == {1}
    assert tuple((root / "backups").glob("*/data/kg.sqlite"))
    assert (path.parent / "session.token").read_text() != old_token


def test_real_process_recovery_refuses_late_live_write(tmp_path: Path) -> None:
    app = build_supervisor(tmp_path / "late-write")
    _real_backend(app)
    path = _older(app)
    root = Path(app.environment["ONTOLOGYLAB_APP_SUPPORT_ROOT"])

    stage_code = """
from pathlib import Path
import sys
from ontologylab.storage_upgrade import UpgradeRequest, run_staged_upgrade
from tests.storage_upgrade_support import quiescence_proof
root = Path(sys.argv[1])
def stop(point):
    if point.value == 'pre-activation':
        raise KeyboardInterrupt
try:
    run_staged_upgrade(
        UpgradeRequest(
            root,
            root / 'data',
            root / 'packs',
            root / 'backups',
            quiescence_proof(root),
        ),
        failpoint=stop,
    )
except KeyboardInterrupt:
    pass
"""
    subprocess.run(
        [sys.executable, "-c", stage_code, str(root)],
        check=True,
        capture_output=True,
        text=True,
    )
    connection = sqlite3.connect(path)
    try:
        connection.execute("CREATE TABLE late_live_write (value TEXT)")
        connection.execute("INSERT INTO late_live_write VALUES ('keep')")
        connection.commit()
    finally:
        connection.close()

    result = run(app, "real", ONTOLOGYLAB_READY_TIMEOUT_MS="10000")

    assert result.returncode != 0
    assert open_arguments(result.stdout) == []
    assert "live-diverged-forward-recovery-required" in result.stderr
    with sqlite3.connect(path) as connection:
        assert connection.execute("SELECT value FROM late_live_write").fetchone() == (
            "keep",
        )


@pytest.mark.parametrize(
    ("prepare", "state"),
    [
        (_newer, "newer"),
        (_unknown, "unknown"),
        (_missing_version, "unknown"),
        (_corrupt, "corrupt"),
    ],
)
def test_supervisor_refuses_incompatible_storage_before_ready_or_write(
    tmp_path: Path,
    prepare: Callable[[AppFixture], Path],
    state: str,
) -> None:
    app = build_supervisor(tmp_path / state)
    _real_backend(app)
    path = prepare(app)
    before = (_sha256(path), path.stat().st_mtime_ns)

    result = run(app, "real", ONTOLOGYLAB_READY_TIMEOUT_MS="10000")

    assert result.returncode != 0
    assert open_arguments(result.stdout) == []
    assert f"state={state}" in result.stderr
    assert not (path.parent / "session.token").exists()
    assert (_sha256(path), path.stat().st_mtime_ns) == before
    assert not tuple(path.parent.glob(f"{path.name}-*"))
