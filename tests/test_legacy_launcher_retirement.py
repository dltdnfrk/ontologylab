from __future__ import annotations

import hashlib
import json
import signal
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from ontologylab.legacy_retirement import (
    LEGACY_LAUNCHD_LABEL,
    LegacyRetirementError,
    RetirementPaths,
    RetirementRequest,
    retire_legacy_ownership,
)


@dataclass(slots=True)
class FakeSystem:
    service_loaded: bool = True
    bootout_status: int = 0
    calls: list[tuple[str, ...]] = field(default_factory=list)
    signals: list[tuple[int, int]] = field(default_factory=list)

    def launchctl(self, arguments: tuple[str, ...]) -> int:
        self.calls.append(arguments)
        match arguments[0]:
            case "print":
                return 0 if self.service_loaded else 113
            case "bootout":
                if self.bootout_status == 0:
                    self.service_loaded = False
                return self.bootout_status
            case unreachable:
                raise AssertionError(f"unexpected launchctl action: {unreachable}")

    def process_exists(self, pid: int) -> bool:
        return any(recorded == pid for recorded, _ in self.signals) is False

    def terminate(self, pid: int) -> None:
        self.signals.append((pid, signal.SIGTERM))


def _paths(root: Path) -> RetirementPaths:
    return RetirementPaths(
        launch_agent=root / "home/Library/LaunchAgents/at.ontologylab.server.plist",
        source_runtime_files=(
            root / "repo/.launcher.pid",
            root / "repo/.launcher.port",
            root / "repo/.launcher.log",
        ),
    )


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_retirement_stops_only_exact_service_and_pid_and_preserves_state(
    tmp_path: Path,
) -> None:
    # Given exact legacy ownership plus protected data, packs, backups, and credentials
    paths = _paths(tmp_path)
    paths.launch_agent.parent.mkdir(parents=True)
    paths.launch_agent.write_text("legacy plist", encoding="utf-8")
    for runtime_file in paths.source_runtime_files:
        runtime_file.parent.mkdir(parents=True, exist_ok=True)
        runtime_file.write_text("legacy runtime", encoding="utf-8")
    protected = tuple(
        tmp_path / relative
        for relative in (
            "home/Library/Application Support/OntologyLab/data/kg.sqlite",
            "home/Library/Application Support/OntologyLab/packs/core.pack",
            "home/Library/Application Support/OntologyLab/backups/kg.sqlite.bak",
            "home/Library/Keychains/login.keychain-db",
        )
    )
    for path in protected:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(path.name.encode())
    before = {path: _sha256(path) for path in protected}
    system = FakeSystem()

    # When the explicit retirement runs for one exact source PID
    receipt = retire_legacy_ownership(
        RetirementRequest(paths=paths, uid=501, source_pid=4242), system
    )

    # Then only the exact service/PID and launcher runtime are retired
    target = f"gui/501/{LEGACY_LAUNCHD_LABEL}"
    assert system.calls == [("print", target), ("bootout", target)]
    assert system.signals == [(4242, signal.SIGTERM)]
    assert receipt.launchd == "retired"
    assert receipt.source_process == "signaled"
    assert not paths.launch_agent.exists()
    assert all(not path.exists() for path in paths.source_runtime_files)
    assert {path: _sha256(path) for path in protected} == before


def test_repeated_retirement_is_idempotent_and_decoy_survives(tmp_path: Path) -> None:
    # Given no loaded legacy service and a decoy PID containing no ownership record
    paths = _paths(tmp_path)
    decoy = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(60)", "at.ontologylab.server"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    system = FakeSystem(service_loaded=False)

    try:
        # When retirement is repeated without an explicitly owned source PID
        first = retire_legacy_ownership(RetirementRequest(paths=paths, uid=501), system)
        second = retire_legacy_ownership(
            RetirementRequest(paths=paths, uid=501), system
        )

        # Then both calls settle and broad text matching never touches the decoy
        assert first.launchd == second.launchd == "absent"
        assert first.source_process == second.source_process == "absent"
        assert system.signals == []
        assert decoy.poll() is None
    finally:
        decoy.terminate()
        decoy.wait(timeout=5)


def test_failed_bootout_refuses_cleanup_and_misleading_success(tmp_path: Path) -> None:
    # Given launchd owns the exact service but refuses its bootout
    paths = _paths(tmp_path)
    paths.launch_agent.parent.mkdir(parents=True)
    paths.launch_agent.write_text("must remain", encoding="utf-8")
    system = FakeSystem(bootout_status=5)

    # When retirement cannot stop the service
    with pytest.raises(LegacyRetirementError) as excinfo:
        retire_legacy_ownership(
            RetirementRequest(paths=paths, uid=501, source_pid=999), system
        )

    # Then it fails typed before PID signaling or launcher-file deletion
    assert excinfo.value.kind == "launchd_refused"
    assert paths.launch_agent.exists()
    assert system.signals == []

    system.bootout_status = 0
    receipt = retire_legacy_ownership(
        RetirementRequest(paths=paths, uid=501, source_pid=999), system
    )
    assert receipt.launchd == "retired"
    assert system.signals == [(999, signal.SIGTERM)]
    assert not paths.launch_agent.exists()


def test_receipt_contains_no_secret_and_contract_never_deletes_credentials(
    tmp_path: Path,
) -> None:
    # Given a canary resembling a credential in an unrelated protected file
    canary = "TASK9-SECRET-CANARY-9f83"
    paths = _paths(tmp_path)
    credential = tmp_path / "home/Library/Keychains/login.keychain-db"
    credential.parent.mkdir(parents=True)
    credential.write_text(canary, encoding="utf-8")

    # When retirement completes without legacy ownership
    receipt = retire_legacy_ownership(
        RetirementRequest(paths=paths, uid=501), FakeSystem(service_loaded=False)
    )
    encoded = json.dumps(receipt.as_json(), sort_keys=True)

    # Then the credential remains and neither receipt nor contract contains it
    assert credential.read_text(encoding="utf-8") == canary
    assert canary not in encoded
    source = Path("ontologylab/legacy_retirement.py").read_text(encoding="utf-8")
    assert "delete_key" not in source
    assert "security delete-generic-password" not in source
