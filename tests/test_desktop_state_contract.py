from __future__ import annotations

import importlib
import logging
import os
import stat
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from ontologylab import paths
from ontologylab.server import settings as settings_mod
from ontologylab.server.app import create_app
from ontologylab.server.schemas import Settings


def test_ordinary_defaults_remain_root_relative(tmp_path: Path) -> None:
    # Given an ordinary non-desktop caller with an explicit project root.
    root = tmp_path / "checkout"
    # When its default mutable locations are derived.
    data_dir = paths.default_data_dir(root)
    packs_dir = paths.default_packs_dir(root)
    # Then the established checkout-relative CLI contract remains unchanged.
    assert (data_dir, packs_dir) == (root / "data", root / "packs")


def test_ordinary_default_settings_remain_checkout_relative() -> None:
    # Given the ordinary settings path without a desktop runtime context.
    # When defaults are constructed.
    settings = settings_mod.default_settings()
    # Then existing CLI users still see the checkout defaults.
    assert settings.data_dir == str(paths.ROOT / "data")
    assert settings.packs_dir == str(paths.ROOT / "packs")


def test_api_reports_the_paths_opened_by_the_running_app(tmp_path: Path) -> None:
    # Given persisted path fields that disagree with this app instance.
    data_dir = tmp_path / "actual-data"
    packs_dir = tmp_path / "actual-packs"
    settings_mod.save_settings(
        Settings(data_dir="/misleading/data", packs_dir="/misleading/packs"),
        data_dir,
    )
    app = create_app(data_dir=data_dir, packs_dir=packs_dir)
    # When the authenticated settings API reports its paths.
    with TestClient(app) as client:
        response = client.get(
            "/api/settings",
            headers={"X-OntologyLab-Session": app.state.session_token},
        )
    # Then the report agrees exactly with the files the app opens.
    assert response.json()["data_dir"] == str(data_dir.resolve())
    assert response.json()["packs_dir"] == str(packs_dir.resolve())


def test_fresh_desktop_bootstrap_uses_declared_roots_and_private_modes(
    tmp_path: Path,
) -> None:
    # Given a disposable home and a read-only app resource directory.
    desktop_state = importlib.import_module("ontologylab.desktop_state")
    home = tmp_path / "home"
    resources = tmp_path / "OntologyLab.app/Contents/Resources"
    resources.mkdir(parents=True)
    resources.chmod(0o555)
    contract = desktop_state.DesktopPaths.for_home(home, resources)
    # When the canonical mutable state is prepared.
    contract.prepare()
    # Then every mutable directory is declared, outside the app, and owner-only.
    assert contract.data_dir == home / "Library/Application Support/ontologylab/data"
    assert contract.packs_dir == home / "Library/Application Support/ontologylab/packs"
    assert contract.backups_dir == home / "Library/Application Support/ontologylab/backups"
    assert contract.logs_dir == home / "Library/Logs/ontologylab"
    assert contract.runtime_dir == home / "Library/Caches/ontologylab/runtime"
    for directory in contract.mutable_directories:
        assert stat.S_IMODE(directory.stat().st_mode) == 0o700
        assert resources.resolve() not in directory.resolve().parents


def test_desktop_bootstrap_refuses_symlink_to_icloud_before_mutation(
    tmp_path: Path,
) -> None:
    # Given Application Support redirected into iCloud Documents.
    desktop_state = importlib.import_module("ontologylab.desktop_state")
    home = tmp_path / "home"
    synced = home / "Library/Mobile Documents/com~apple~CloudDocs/Documents/state"
    synced.mkdir(parents=True)
    app_parent = home / "Library/Application Support"
    app_parent.mkdir(parents=True)
    (app_parent / "ontologylab").symlink_to(synced)
    contract = desktop_state.DesktopPaths.for_home(home, tmp_path / "App/Resources")
    # When bootstrap preflights the path, then it refuses before creating data.
    with pytest.raises(desktop_state.DesktopStateRefused) as refused:
        contract.prepare()
    assert refused.value.member == "icloud"
    assert not (synced / "data").exists()


def test_desktop_icloud_refusal_survives_macos_private_var_alias(
    tmp_path: Path,
) -> None:
    # Given macOS spelling the same temporary home through /var and /private/var.
    desktop_state = importlib.import_module("ontologylab.desktop_state")
    if not str(tmp_path).startswith("/private/var/"):
        pytest.skip("macOS /var alias is unavailable")
    home = Path(str(tmp_path).removeprefix("/private")) / "home"
    cloud = home / "Library/Mobile Documents/com~apple~CloudDocs/Documents/state"
    cloud.mkdir(parents=True)
    app_parent = home / "Library/Application Support"
    app_parent.mkdir(parents=True)
    (app_parent / "ontologylab").symlink_to(cloud)
    contract = desktop_state.DesktopPaths.for_home(home, tmp_path / "App/Resources")
    # When canonical and aliased spellings meet, then iCloud remains the refusal reason.
    with pytest.raises(desktop_state.DesktopStateRefused) as refused:
        contract.prepare()
    assert refused.value.member == "icloud"
    assert not (cloud / "data").exists()


def test_desktop_bootstrap_refuses_world_readable_state_without_repairing_it(
    tmp_path: Path,
) -> None:
    # Given an existing canonical root with unsafe permissions.
    desktop_state = importlib.import_module("ontologylab.desktop_state")
    home = tmp_path / "home"
    state_root = home / "Library/Application Support/ontologylab"
    state_root.mkdir(parents=True)
    state_root.chmod(0o755)
    contract = desktop_state.DesktopPaths.for_home(home, tmp_path / "App/Resources")
    # When bootstrap checks existing state, then it refuses before mutation.
    with pytest.raises(desktop_state.DesktopStateRefused) as refused:
        contract.prepare()
    assert refused.value.member == "permissions"
    assert stat.S_IMODE(state_root.stat().st_mode) == 0o755
    assert not contract.logs_dir.exists()


def test_desktop_bootstrap_refuses_checkout_state_before_mutation(
    tmp_path: Path,
) -> None:
    # Given a forged HOME that would place desktop state beneath the checkout.
    desktop_state = importlib.import_module("ontologylab.desktop_state")
    home = paths.ROOT / ".desktop-state-adversary"
    contract = desktop_state.DesktopPaths.for_home(home, tmp_path / "App/Resources")
    # When desktop preflight runs, then checkout writes are refused before creation.
    with pytest.raises(desktop_state.DesktopStateRefused) as refused:
        contract.prepare()
    assert refused.value.member == "checkout_write"
    assert not home.exists()


def test_desktop_bootstrap_refuses_symlink_home_before_mutation(tmp_path: Path) -> None:
    # Given HOME itself as an alias to another filesystem location.
    desktop_state = importlib.import_module("ontologylab.desktop_state")
    real_home = tmp_path / "real-home"
    real_home.mkdir()
    linked_home = tmp_path / "linked-home"
    linked_home.symlink_to(real_home)
    contract = desktop_state.DesktopPaths.for_home(
        linked_home, tmp_path / "OntologyLab.app/Contents/Resources"
    )
    # When desktop preflight runs, then it refuses the alias before creating state.
    with pytest.raises(desktop_state.DesktopStateRefused) as refused:
        contract.prepare()
    assert refused.value.member == "symlink"
    assert not (real_home / "Library").exists()


def test_desktop_environment_refuses_bundle_writable_paths_before_mutation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Given supervisor fields whose data path points beneath the app bundle.
    from ontologylab.serve_desktop import DesktopEnvironment

    home = tmp_path / "home"
    bundle = tmp_path / "OntologyLab.app"
    resources = bundle / "Contents/Resources"
    resources.mkdir(parents=True)
    values = {
        "HOME": str(home),
        "ONTOLOGYLAB_LISTENER_FD": "0",
        "ONTOLOGYLAB_READY_FD": "1",
        "ONTOLOGYLAB_NONCE": "0123456789abcdef0123456789abcdef",
        "ONTOLOGYLAB_APP_VERSION": "0.1.0",
        "ONTOLOGYLAB_STORAGE_VERSION": "1",
        "ONTOLOGYLAB_SUPERVISOR_PID": str(os.getppid()),
        "ONTOLOGYLAB_QUIESCENCE_RECEIPT": str(tmp_path / "quiescence.json"),
        "ONTOLOGYLAB_RESOURCES_DIR": str(resources),
        "ONTOLOGYLAB_DATA_DIR": str(resources / "data"),
        "ONTOLOGYLAB_PACKS_DIR": str(home / "Library/Application Support/ontologylab/packs"),
        "ONTOLOGYLAB_LOG_DIR": str(home / "Library/Logs/ontologylab"),
        "ONTOLOGYLAB_RUNTIME_DIR": str(home / "Library/Caches/ontologylab/runtime"),
    }
    for name, value in values.items():
        monkeypatch.setenv(name, value)
    # When the desktop boundary is parsed, then the mismatch is typed and no file appears.
    with pytest.raises(Exception, match="data_dir"):
        DesktopEnvironment.from_process()
    assert not (resources / "data").exists()


def test_desktop_log_rotates_and_redacts_secret_and_home_path(tmp_path: Path) -> None:
    # Given a canonical log with a canary token and private home path.
    desktop_logging = importlib.import_module("ontologylab.desktop_logging")
    desktop_state = importlib.import_module("ontologylab.desktop_state")
    home = tmp_path / "private-home"
    resources = tmp_path / "OntologyLab.app/Contents/Resources"
    resources.mkdir(parents=True)
    contract = desktop_state.DesktopPaths.for_home(home, resources)
    contract.prepare()
    desktop_logging.configure_desktop_logging(
        contract,
        desktop_logging.DesktopLogPolicy(
            sensitive_values=("canary-secret-293ab",),
            max_bytes=180,
            backup_count=2,
        ),
    )
    logger = logging.getLogger("ontologylab.server.routes")
    # When enough bounded application records are emitted to rotate.
    for index in range(20):
        logger.info(
            "desktop.qa index=%s token=%s source=%s",
            index,
            "canary-secret-293ab",
            home / "private/source.txt",
        )
    for handler in logger.handlers:
        handler.flush()
    # Then rotation occurs, all files are private, and sensitive values are absent.
    log_files = sorted(contract.logs_dir.glob("ontologylab.log*"))
    assert len(log_files) > 1
    combined = b"".join(path.read_bytes() for path in log_files)
    assert b"canary-secret-293ab" not in combined
    assert os.fsencode(home) not in combined
    assert b"<redacted>" in combined
    assert all(stat.S_IMODE(path.stat().st_mode) == 0o600 for path in log_files)
    logging.shutdown()
