from __future__ import annotations

import json
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

from scripts import internal_deployment
from scripts.internal_deployment import (
    DeploymentRefused,
    SupportRequest,
    UninstallRequest,
    build_support_bundle,
    uninstall_app,
)
from tests.test_internal_deployment import _app, _receipt


def test_default_uninstall_selects_recursive_removal_for_app_and_runtime(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Given installed app/runtime paths and a seam that records removal selection.
    app = _app(tmp_path / "Applications")
    home = tmp_path / "home"
    runtime = home / "Library/Caches/ontologylab/runtime"
    runtime.mkdir(parents=True)
    selected: list[Path] = []
    monkeypatch.setattr(
        "scripts.internal_deployment.shutil.rmtree", lambda path: selected.append(path)
    )

    # When the unchanged default uninstall behavior is selected.
    uninstall_app(UninstallRequest(app, home, False, None, False, None))

    # Then only the existing recursive-removal operation owns app/runtime removal.
    assert selected == [app, runtime]


def test_uninstall_defaults_preserve_data_and_credentials(tmp_path: Path) -> None:
    # Given installed app/runtime plus canonical data and a Keychain hash sentinel.
    app = _app(tmp_path / "Applications")
    home = tmp_path / "home"
    runtime = home / "Library/Caches/ontologylab/runtime"
    data = home / "Library/Application Support/ontologylab/data"
    runtime.mkdir(parents=True)
    data.mkdir(parents=True)
    (runtime / "state").write_text("runtime", encoding="utf-8")
    (data / "kg.sqlite").write_text("canonical", encoding="utf-8")
    keychain = tmp_path / "keychain-hash"
    keychain.write_text("unchanged", encoding="utf-8")

    # When default uninstall runs.
    uninstall_app(UninstallRequest(app, home, False, None, False, None))

    # Then app/runtime are gone while data and credentials remain byte-identical.
    assert not app.exists()
    assert not runtime.exists()
    assert (data / "kg.sqlite").read_text(encoding="utf-8") == "canonical"
    assert keychain.read_text(encoding="utf-8") == "unchanged"


@pytest.mark.parametrize(
    (
        "remove_data",
        "data_confirmation",
        "remove_credentials",
        "credentials_confirmation",
        "reason",
    ),
    [
        (True, None, False, None, "data_confirmation_required"),
        (False, None, True, None, "credentials_confirmation_required"),
        (
            True,
            "REMOVE-ONTOLOGYLAB-DATA",
            True,
            None,
            "credentials_confirmation_required",
        ),
    ],
)
def test_destructive_uninstall_requires_separate_exact_confirmations(
    tmp_path: Path,
    remove_data: bool,
    data_confirmation: str | None,
    remove_credentials: bool,
    credentials_confirmation: str | None,
    reason: str,
) -> None:
    # Given a destructive request missing at least one independent confirmation.
    app = _app(tmp_path / "Applications")
    home = tmp_path / "home"

    # When uninstall parses the request.
    with pytest.raises(DeploymentRefused, match=reason):
        uninstall_app(
            UninstallRequest(
                app,
                home,
                remove_data,
                data_confirmation,
                remove_credentials,
                credentials_confirmation,
            )
        )

    # Then validation precedes every removal, including repeated requests.
    assert app.exists()


def test_confirmed_destructive_domains_use_helper_then_remove_data(
    tmp_path: Path,
) -> None:
    # Given one configured Keychain account and an executable helper fake.
    app = _app(tmp_path / "Applications")
    home = tmp_path / "home"
    data = home / "Library/Application Support/ontologylab/data"
    data.mkdir(parents=True)
    (data / "sources.json").write_text(
        json.dumps({"sources": [{"keychain_account": "publisher"}]}),
        encoding="utf-8",
    )
    marker = tmp_path / "deleted-account"
    helper = app / "Contents/Resources/keychain-helper"
    helper.write_text(
        f"#!{sys.executable}\nimport json,sys\nopen({str(marker)!r},'w').write(json.load(sys.stdin)['account'])\n",
        encoding="utf-8",
    )
    helper.chmod(0o755)

    # When both independently confirmed destructive domains are requested.
    uninstall_app(
        UninstallRequest(
            app,
            home,
            True,
            "REMOVE-ONTOLOGYLAB-DATA",
            True,
            "REMOVE-ONTOLOGYLAB-CREDENTIALS",
        )
    )

    # Then credential deletion precedes removal and both requested domains are gone.
    assert marker.read_text(encoding="utf-8") == "publisher"
    assert not app.exists()
    assert not (home / "Library/Application Support/ontologylab").exists()


def test_support_bundle_is_local_metadata_only_and_excludes_canary(
    tmp_path: Path,
) -> None:
    # Given secrets in raw documents, settings, and logs.
    home = tmp_path / "home"
    root = home / "Library/Application Support/ontologylab"
    logs = home / "Library/Logs/ontologylab"
    (root / "data/documents").mkdir(parents=True)
    logs.mkdir(parents=True)
    canary = "TASK10_SECRET_CANARY_7c924"
    (root / "data/documents/raw.txt").write_text(canary, encoding="utf-8")
    (root / "data/settings.json").write_text(canary, encoding="utf-8")
    (logs / "backend.log").write_text(canary, encoding="utf-8")
    output = tmp_path / "support.zip"

    # When a support bundle is generated.
    result = build_support_bundle(
        SupportRequest(home=home, app=tmp_path / "OntologyLab.app", output=output)
    )

    # Then the archive contains diagnostics only, never source content or secrets.
    assert result == output
    assert canary.encode() not in output.read_bytes()
    with zipfile.ZipFile(output) as archive:
        assert set(archive.namelist()) == {"support.json"}
        payload = json.loads(archive.read("support.json"))
    assert payload["schema"] == "ontologylab.internal-support.v1"
    assert payload["data"]["document_count"] == 1


def test_cli_refusal_is_nonzero_without_misleading_success(tmp_path: Path) -> None:
    # Given a syntactically complete install command without trust acknowledgement.
    app = _app(tmp_path / "candidate")
    receipt, receipt_hash = _receipt(app, tmp_path / "receipt.json")

    # When the executable CLI is invoked.
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "scripts.internal_deployment_cli",
            "install",
            "--app",
            str(app),
            "--receipt",
            str(receipt),
            "--receipt-sha256",
            receipt_hash,
            "--destination",
            str(tmp_path / "installed.app"),
            "--home",
            str(tmp_path / "home"),
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    # Then it refuses on stderr and emits no success receipt.
    assert result.returncode == 2
    assert "acknowledgement_required" in result.stderr
    assert result.stdout == ""


def test_confirmed_credential_removal_also_clears_the_legacy_service(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A confirmed wipe must not leave a pre-helper secret behind.

    The bundled helper only knows `ontologylab.v2`. An account that was never
    migrated still holds its secret under the old `ontologylab` service, so
    deleting v2 alone means a user who typed the confirmation phrase keeps a
    live credential after the app is gone. Measured against the exact signed
    app before this was fixed: the legacy item survived an uninstall that
    reported success.
    """
    # Given a configured account, a helper fake, and an observable `security`.
    app = _app(tmp_path / "Applications")
    home = tmp_path / "home"
    data = home / "Library/Application Support/ontologylab/data"
    data.mkdir(parents=True)
    (data / "sources.json").write_text(
        json.dumps({"sources": [{"keychain_account": "publisher"}]}),
        encoding="utf-8",
    )
    helper = app / "Contents/Resources/keychain-helper"
    helper.write_text(f"#!{sys.executable}\nimport sys\nsys.exit(0)\n", encoding="utf-8")
    helper.chmod(0o755)

    calls = tmp_path / "security-calls"
    fake_security = tmp_path / "security"
    fake_security.write_text(
        f"#!{sys.executable}\n"
        "import sys\n"
        f"open({str(calls)!r},'a').write(' '.join(sys.argv[1:]) + '\\n')\n",
        encoding="utf-8",
    )
    fake_security.chmod(0o755)
    monkeypatch.setattr(
        internal_deployment, "_SECURITY_BIN", str(fake_security), raising=True
    )

    # When credential removal is confirmed.
    uninstall_app(
        UninstallRequest(
            app, home, False, None, True, "REMOVE-ONTOLOGYLAB-CREDENTIALS"
        )
    )

    # Then the legacy service was asked to delete that exact account.
    recorded = calls.read_text(encoding="utf-8")
    assert "delete-generic-password" in recorded
    assert "-s ontologylab -a publisher" in recorded


def test_uninstall_retires_the_legacy_launch_agent_before_removing_the_app(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A LaunchAgent left loaded would respawn a binary this call deletes.

    The retirement seam is patched rather than exercised for real: the legacy
    label is a live service on machines that ran the old launcher, so building
    the production adapter here would boot out a real server.
    """
    # Given a loaded legacy service and its plist.
    app = _app(tmp_path / "Applications")
    home = tmp_path / "home"
    agents = home / "Library/LaunchAgents"
    agents.mkdir(parents=True)
    plist = agents / "at.ontologylab.server.plist"
    plist.write_text("<plist/>", encoding="utf-8")
    actions: list[tuple[str, ...]] = []

    class _LoadedLegacy:
        def launchctl(self, arguments: tuple[str, ...]) -> int:
            actions.append(arguments)
            return 0  # present, and boots out cleanly

        def process_exists(self, pid: int) -> bool:
            return False

        def terminate(self, pid: int) -> None:
            raise AssertionError("no source pid should be signalled")

    monkeypatch.setattr(
        internal_deployment, "_retirement_system", _LoadedLegacy, raising=True
    )

    # When the app is uninstalled.
    uninstall_app(UninstallRequest(app, home, False, None, False, None))

    # Then the exact label was booted out and its plist is gone with the app.
    assert [name for name, _target in actions] == ["print", "bootout"]
    assert all(
        target.endswith("/at.ontologylab.server") for _name, target in actions
    )
    assert not plist.exists()
    assert not app.exists()
