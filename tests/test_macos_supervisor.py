from __future__ import annotations

import fcntl
import http.client
import json
import os
import stat
import subprocess
import sys
from contextlib import closing
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from ontologylab import serve
from tests.macos_supervisor_support import (
    FIXTURES,
    ROOT,
    AppFixture,
    build_supervisor,
    launch,
    managed_process,
    open_arguments,
    read_event,
    run,
    stop,
)


@pytest.fixture(scope="module")
def supervisor_app(tmp_path_factory: pytest.TempPathFactory) -> AppFixture:
    return build_supervisor(tmp_path_factory.mktemp("macos-supervisor"))


def test_ordinary_serve_startup_and_session_readiness_are_preserved(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Given an ordinary ontologylab.serve invocation with disposable state.
    observed_app: list[FastAPI] = []
    observed_bind: list[tuple[str, int]] = []

    def capture_run(app: FastAPI, *, host: str, port: int) -> None:
        observed_app.append(app)
        observed_bind.append((host, port))

    monkeypatch.setattr("uvicorn.run", capture_run)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "ontologylab.serve",
            "--port",
            "43210",
            "--data-dir",
            str(tmp_path / "data"),
            "--packs-dir",
            str(tmp_path / "packs"),
        ],
    )

    # When the established CLI starts.
    serve.main()

    # Then it keeps its loopback bind and root/session readiness behavior.
    assert observed_bind == [("127.0.0.1", 43210)]
    with TestClient(observed_app[0]) as client:
        response = client.get("/")
    assert response.status_code == 200
    session_path = tmp_path / "data" / "session.token"
    assert len(session_path.read_text(encoding="utf-8")) == 64
    assert stat.S_IMODE(session_path.stat().st_mode) == 0o600


@pytest.mark.parametrize(
    "mode",
    [
        "malformed",
        "duplicate",
        "trailing",
        "extra_line",
        "version_mismatch",
        "storage_mismatch",
        "nonce_mismatch",
        "port_mismatch",
        "type_mismatch",
    ],
)
def test_browser_is_refused_when_ready_payload_is_invalid(
    supervisor_app: AppFixture, mode: str
) -> None:
    # Given a backend that emits one invalid protocol variant.
    # When the supervisor consumes readiness.
    result = run(supervisor_app, mode)
    # Then it refuses deterministically before browser activation.
    assert result.returncode != 0
    assert open_arguments(result.stdout) == []
    assert "readiness_refused" in result.stderr


def test_supervisor_refuses_stale_storage_matrix_before_backend_launch(
    tmp_path: Path,
) -> None:
    # Given a bundled matrix bound to a different release version.
    app = build_supervisor(tmp_path / "stale-storage-matrix")
    matrix_path = (
        app.executable.parent.parent / "Resources" / "storage-compatibility.json"
    )
    matrix = json.loads(matrix_path.read_text(encoding="utf-8"))
    matrix["release_version"] = "9.9.9"
    matrix_path.write_text(json.dumps(matrix), encoding="utf-8")

    # When the supervisor loads configuration, then no backend/browser is started.
    result = run(app, "valid")
    assert result.returncode != 0
    assert "configuration_refused member=storage_matrix" in result.stderr
    assert "BACKEND_PID:" not in result.stderr
    assert open_arguments(result.stdout) == []


def test_exact_valid_payload_opens_actual_ephemeral_port(
    supervisor_app: AppFixture,
) -> None:
    # Given a backend inheriting the supervisor's ephemeral listener.
    # When it emits exact readiness and exits.
    result = run(supervisor_app, "valid")
    # Then Aside receives exactly the validated loopback URL.
    assert result.returncode == 0, result.stderr
    calls = open_arguments(result.stdout)
    assert len(calls) == 1
    assert calls[0][:2] == ["-b", "at.studio.AsideBrowser"]
    url = calls[0][2]
    assert url.startswith("http://127.0.0.1:") and url.endswith("/")
    assert int(url.removeprefix("http://127.0.0.1:").removesuffix("/")) > 0


def test_default_browser_is_used_when_aside_refuses(
    supervisor_app: AppFixture,
) -> None:
    # Given Aside returning a nonzero status.
    # When valid readiness activates the browser.
    result = run(supervisor_app, "valid", FAKE_OPEN_ASIDE="fail")
    # Then the exact same URL is retried with the default browser.
    calls = open_arguments(result.stdout)
    assert result.returncode == 0
    assert calls[0][:2] == ["-b", "at.studio.AsideBrowser"]
    assert calls[1] == [calls[0][2]]


@pytest.mark.parametrize("mode", ["immediate_exit", "eof", "timeout"])
def test_backend_failure_never_opens_browser(
    supervisor_app: AppFixture, mode: str
) -> None:
    # Given a backend that cannot complete readiness.
    # When the bounded readiness wait finishes.
    result = run(supervisor_app, mode)
    # Then startup fails and browser invocation remains absent.
    assert result.returncode != 0
    assert open_arguments(result.stdout) == []


def test_second_launch_activates_same_version_instance(
    supervisor_app: AppFixture,
) -> None:
    # Given one ready same-version supervisor holding the canonical lock.
    with managed_process(launch(supervisor_app, "hold")) as first:
        read_event(first, "OPEN:")
        # When a second supervisor launches against that state.
        second = run(supervisor_app, "immediate_exit")
        # Then it activates the existing URL without spawning another backend.
        assert second.returncode == 0, second.stderr
        assert len(open_arguments(second.stdout)) == 1
        assert "BACKEND_PID:" not in second.stderr


def test_foreign_lock_owner_is_refused(supervisor_app: AppFixture) -> None:
    # Given a foreign process lock paired with misleading same-version state.
    supervisor_app.state_root.mkdir(mode=0o700, parents=True, exist_ok=True)
    lock_path = supervisor_app.state_root / "supervisor.lock"
    with lock_path.open("w+") as lock:
        fcntl.lockf(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        (supervisor_app.state_root / "instance.json").write_text(
            json.dumps(
                {
                    "version": "0.1.0",
                    "port": 43127,
                    "pid": os.getpid(),
                    "childPid": os.getpid(),
                    "nonce": "0" * 32,
                }
            )
        )
        # When another launch meets the occupied lock.
        result = run(supervisor_app, "valid")
    (supervisor_app.state_root / "instance.json").unlink()
    # Then it refuses the foreign state and does not activate a browser.
    assert result.returncode != 0
    assert open_arguments(result.stdout) == []
    assert "instance_refused" in result.stderr


def test_sigterm_targets_exact_child_and_leaves_decoy_alive(
    supervisor_app: AppFixture,
) -> None:
    # Given a similarly named decoy and one owned backend child.
    decoy_process = subprocess.Popen(
        [str(FIXTURES / "fake_backend.py")],
        env=os.environ | {"FAKE_BACKEND_MODE": "decoy"},
        stdout=subprocess.PIPE,
        text=True,
    )
    with managed_process(decoy_process) as decoy:
        assert decoy.stdout is not None
        assert decoy.stdout.readline().startswith("DECOY_PID:")
        with managed_process(launch(supervisor_app, "hold")) as owned:
            read_event(owned, "OPEN:")
            # When the supervisor receives SIGTERM.
            stop(owned)
        # Then only its exact child exits; the decoy remains alive.
        assert decoy.poll() is None


def test_sigkill_fallback_reports_only_owned_pid(
    supervisor_app: AppFixture,
) -> None:
    # Given an owned backend that ignores graceful SIGTERM.
    with managed_process(launch(supervisor_app, "ignore_term")) as process:
        read_event(process, "OPEN:")
        # When the supervisor's bounded shutdown deadline expires.
        _stdout, stderr = stop(process)
        # Then it reports an exact-PID SIGKILL fallback and exits.
        assert process.returncode == 0, stderr
        assert "forced_kill_pid=" in stderr
        assert "BACKEND_IGNORING_TERM" in stderr


def test_state_is_owner_only_and_released_after_child_exit(
    supervisor_app: AppFixture,
) -> None:
    # Given a normal short-lived backend.
    # When the supervisor completes and reaps it.
    result = run(supervisor_app, "valid")
    # Then canonical state is private and the lock is available again.
    assert result.returncode == 0
    assert stat.S_IMODE(supervisor_app.state_root.stat().st_mode) == 0o700
    lock_path = supervisor_app.state_root / "supervisor.lock"
    assert stat.S_IMODE(lock_path.stat().st_mode) == 0o600
    with lock_path.open("r+") as lock:
        fcntl.lockf(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)


def test_real_supervisor_backend_handshake_serves_validated_port(
    tmp_path: Path,
) -> None:
    # Given the real supervisor with the real desktop backend at its bundle path.
    app = build_supervisor(tmp_path / "real-supervisor")
    backend = app.executable.parent.parent / "Resources" / "ontologylab-serve-desktop"
    backend.unlink()
    backend.write_text(
        f"#!{sys.executable}\nfrom ontologylab.serve_desktop import main\nmain()\n",
        encoding="utf-8",
    )
    backend.chmod(0o755)
    with managed_process(
        launch(app, "real", ONTOLOGYLAB_READY_TIMEOUT_MS="10000")
    ) as process:
        # When the backend receives the supervisor's child fd 0/1 wiring.
        opened = json.loads(
            read_event(process, "OPEN:", timeout=10).removeprefix("OPEN:")
        )
        url = opened[2]
        with closing(
            http.client.HTTPConnection(
                "127.0.0.1",
                int(url.removeprefix("http://127.0.0.1:").removesuffix("/")),
                timeout=3,
            )
        ) as connection:
            connection.request("GET", "/")
            response = connection.getresponse()
            body = response.read()
        # Then exact readiness was validated before the actual bound port serves root.
        assert opened[:2] == ["-b", "at.studio.AsideBrowser"]
        assert response.status == 200
        assert b"ontologylab" in body
        stop(process)
    assert process.returncode == 0


def test_build_script_packages_compiled_supervisor_without_shell_ownership(
    tmp_path: Path,
) -> None:
    # Given a bundle-relative backend artifact supplied by the packaging stage.
    output = tmp_path / "Applications"
    backend = FIXTURES / "fake_backend.py"
    # When the macOS app builder assembles the disposable bundle.
    result = subprocess.run(
        ["bash", str(ROOT / "launcher" / "build-macos-app.sh"), "--out", str(output)],
        env=os.environ | {"ONTOLOGYLAB_DESKTOP_BACKEND": str(backend)},
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    # Then process ownership is the compiled supervisor, not generated shell.
    assert result.returncode == 0, result.stderr
    executable = (
        output / "ontologylab.app" / "Contents" / "MacOS" / "ontologylab-supervisor"
    )
    assert executable.is_file() and os.access(executable, os.X_OK)
    assert executable.read_bytes()[:4] != b"#!/b"
    script = (ROOT / "launcher" / "build-macos-app.sh").read_text()
    assert "pkill" not in script
    assert "/healthz" not in script
    assert "sleep " not in script
    assert ".venv" not in script
