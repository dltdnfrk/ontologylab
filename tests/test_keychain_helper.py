"""Native Keychain helper transport: malformed, unauthorized, migration, lifecycle.

Unit cases stay on monkeypatch so they run without macOS Security.framework.
The compile/sign/roundtrip case is Darwin-only and always cleans its temp
service, account, binary, and directory.
"""

from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
import sys
import uuid
from pathlib import Path

import pytest

from ontologylab import keychain
from ontologylab.keychain import KeychainError, delete_key, read_key, write_key

HELPER_SRC = (
    Path(__file__).resolve().parents[1] / "launcher" / "keychain-helper.swift"
)
MALFORMED_CANARY = "CANARY-malformed-helper-7f2c"
UNAUTHORIZED_CANARY = "CANARY-unauthorized-helper-7f2c"
MIGRATE_FAIL_CANARY = "CANARY-migrate-order-7f2c"
MIGRATE_OK_CANARY = "CANARY-migrate-success-7f2c"
REAL_CANARY = "CANARY-real-helper-roundtrip-7f2c"

needs_macos_swiftc = pytest.mark.skipif(
    sys.platform != "darwin" or shutil.which("swiftc") is None,
    reason="macOS swiftc required for native helper",
)

TEST_SERVICE = "ontologylab-pytest-helper"
TEST_SERVICE_LEGACY = "ontologylab-pytest-helper-legacy"
_REAL_RUN = subprocess.run


@pytest.fixture(autouse=True)
def _isolate_helper_service(monkeypatch, request):
    if request.node.name == "test_product_service_is_v2":
        yield
        return
    monkeypatch.setattr(keychain, "KEYCHAIN_SERVICE", TEST_SERVICE)
    monkeypatch.setattr(keychain, "KEYCHAIN_SERVICE_LEGACY", TEST_SERVICE_LEGACY)
    yield
    if shutil.which("security") is None:
        return
    for service in (TEST_SERVICE, TEST_SERVICE_LEGACY):
        for _ in range(20):
            found = _REAL_RUN(
                ["security", "find-generic-password", "-s", service],
                capture_output=True, text=True, timeout=15,
            )
            if found.returncode != 0:
                break
            account = ""
            for line in found.stdout.splitlines():
                if '"acct"<blob>=' in line:
                    account = line.split('="', 1)[-1].rstrip('"')
            if not account:
                break
            _REAL_RUN(
                ["security", "delete-generic-password",
                 "-s", service, "-a", account],
                capture_output=True, text=True, timeout=15,
            )


def _dummy_helper(tmp_path: Path) -> Path:
    helper = tmp_path / "keychain-helper"
    helper.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    helper.chmod(0o755)
    return helper


def test_helper_malformed_response_fails_typed_without_secret(
    monkeypatch, tmp_path
) -> None:
    helper = _dummy_helper(tmp_path)
    monkeypatch.setenv("ONTOLOGYLAB_KEYCHAIN_HELPER", str(helper))
    calls: list[list[str]] = []

    def _run(argv, **kwargs):
        calls.append(list(argv))
        return subprocess.CompletedProcess(argv, 0, "{not-json", "")

    monkeypatch.setattr(keychain, "keychain_available", lambda: True)
    monkeypatch.setattr(keychain.subprocess, "run", _run)

    with pytest.raises(KeychainError) as excinfo:
        write_key("ontologylab.test.malformed", MALFORMED_CANARY)

    assert getattr(excinfo.value, "kind", None) == "malformed"
    assert MALFORMED_CANARY not in str(excinfo.value)
    for argv in calls:
        assert MALFORMED_CANARY not in argv
        assert "add-generic-password" not in argv


def test_helper_unauthorized_response_fails_typed_without_secret(
    monkeypatch, tmp_path
) -> None:
    helper = _dummy_helper(tmp_path)
    monkeypatch.setenv("ONTOLOGYLAB_KEYCHAIN_HELPER", str(helper))
    calls: list[list[str]] = []

    def _run(argv, **kwargs):
        calls.append(list(argv))
        return subprocess.CompletedProcess(
            argv, 3, '{"ok":false,"error":"unauthorized"}', ""
        )

    monkeypatch.setattr(keychain, "keychain_available", lambda: True)
    monkeypatch.setattr(keychain.subprocess, "run", _run)

    with pytest.raises(KeychainError) as excinfo:
        write_key("ontologylab.test.unauthorized", UNAUTHORIZED_CANARY)

    assert getattr(excinfo.value, "kind", None) == "unauthorized"
    assert UNAUTHORIZED_CANARY not in str(excinfo.value)
    for argv in calls:
        assert UNAUTHORIZED_CANARY not in argv
        assert "add-generic-password" not in argv


def test_migration_does_not_delete_legacy_before_v2_verify(
    monkeypatch, tmp_path
) -> None:
    """A failed native write must not delete the legacy item."""
    helper = _dummy_helper(tmp_path)
    monkeypatch.setenv("ONTOLOGYLAB_KEYCHAIN_HELPER", str(helper))
    order: list[str] = []

    def _run(argv, **kwargs):
        argv = list(argv)
        if "delete-generic-password" in argv:
            order.append("legacy-delete")
            return subprocess.CompletedProcess(argv, 0, "", "")
        if "add-generic-password" in argv:
            order.append("legacy-add")
            return subprocess.CompletedProcess(argv, 1, "", "refused")
        if "find-generic-password" in argv:
            order.append("legacy-find")
            return subprocess.CompletedProcess(argv, 0, MIGRATE_FAIL_CANARY + "\n", "")
        if argv and argv[0] == str(helper):
            order.append("helper")
            return subprocess.CompletedProcess(
                argv, 1, '{"ok":false,"error":"refused"}', ""
            )
        return subprocess.CompletedProcess(argv, 1, "", "")

    monkeypatch.setattr(keychain, "keychain_available", lambda: True)
    monkeypatch.setattr(keychain.subprocess, "run", _run)

    with pytest.raises(KeychainError):
        write_key("ontologylab.test.migrate", MIGRATE_FAIL_CANARY)

    assert "legacy-delete" not in order
    assert "legacy-add" not in order


def test_migration_deletes_legacy_only_after_verified_native_write(
    monkeypatch, tmp_path
) -> None:
    helper = _dummy_helper(tmp_path)
    monkeypatch.setenv("ONTOLOGYLAB_KEYCHAIN_HELPER", str(helper))
    stored: dict[str, str] = {}
    order: list[str] = []

    def _run(argv, **kwargs):
        argv = list(argv)
        if "delete-generic-password" in argv:
            order.append("legacy-delete")
            return subprocess.CompletedProcess(argv, 0, "", "")
        if "add-generic-password" in argv:
            order.append("legacy-add")
            return subprocess.CompletedProcess(argv, 1, "", "nope")
        if "find-generic-password" in argv:
            order.append("legacy-find")
            return subprocess.CompletedProcess(argv, 1, "", "")
        if argv and argv[0] == str(helper):
            body = json.loads(kwargs.get("input") or "{}")
            op = body.get("operation")
            order.append(f"helper-{op}")
            if op == "write":
                stored["v2"] = body.get("secret") or ""
                return subprocess.CompletedProcess(argv, 0, '{"ok":true}', "")
            if op == "read":
                val = stored.get("v2")
                if val:
                    return subprocess.CompletedProcess(
                        argv, 0, json.dumps({"ok": True, "secret": val}), ""
                    )
                return subprocess.CompletedProcess(
                    argv, 0, '{"ok":false,"error":"not_found"}', ""
                )
            if op == "delete":
                stored.pop("v2", None)
                return subprocess.CompletedProcess(argv, 0, '{"ok":true}', "")
        return subprocess.CompletedProcess(argv, 1, "", "")

    monkeypatch.setattr(keychain, "keychain_available", lambda: True)
    monkeypatch.setattr(keychain.subprocess, "run", _run)

    write_key("ontologylab.test.migrateok", MIGRATE_OK_CANARY)

    assert "legacy-add" not in order
    assert "helper-write" in order
    assert "helper-read" in order
    write_idx = order.index("helper-write")
    read_after = next(
        i for i, name in enumerate(order) if i > write_idx and name == "helper-read"
    )
    assert "legacy-delete" in order
    assert order.index("legacy-delete") > read_after


def test_relative_helper_path_is_rejected(monkeypatch) -> None:
    monkeypatch.setenv("ONTOLOGYLAB_KEYCHAIN_HELPER", "relative/keychain-helper")
    monkeypatch.setattr(keychain, "keychain_available", lambda: True)
    monkeypatch.setattr(
        keychain, "read_key", lambda _acct: "should-not-be-used"
    )

    with pytest.raises(KeychainError) as excinfo:
        write_key("ontologylab.test.relhelper", "value")

    assert getattr(excinfo.value, "kind", None) == "missing_helper"
    assert "value" not in str(excinfo.value)


def test_missing_helper_write_is_typed(monkeypatch, tmp_path) -> None:
    missing = tmp_path / "no-such-helper"
    monkeypatch.setenv("ONTOLOGYLAB_KEYCHAIN_HELPER", str(missing))
    monkeypatch.setattr(keychain, "keychain_available", lambda: True)

    with pytest.raises(KeychainError) as excinfo:
        write_key("ontologylab.test.nohelper", "value")

    assert getattr(excinfo.value, "kind", None) == "missing_helper"


def test_product_service_is_v2() -> None:
    assert keychain.KEYCHAIN_SERVICE == "ontologylab.v2"


@needs_macos_swiftc
def test_real_helper_compile_sign_roundtrip(tmp_path, monkeypatch) -> None:
    """Compile, ad-hoc sign, write/read/rotate/delete, then remove everything."""
    assert HELPER_SRC.is_file(), f"missing helper source: {HELPER_SRC}"

    work = tmp_path / f"ol-helper-{uuid.uuid4().hex[:10]}"
    work.mkdir()
    binary = work / "keychain-helper"
    service = f"ontologylab.pytest.v2.{uuid.uuid4().hex[:12]}"
    legacy_service = f"ontologylab.pytest.v1.{uuid.uuid4().hex[:12]}"
    account = f"acct.{uuid.uuid4().hex[:12]}"
    compiled = False
    leftover_v2 = True
    leftover_v1 = False

    def _security_present(svc: str, acct: str) -> bool:
        found = subprocess.run(
            ["security", "find-generic-password", "-s", svc, "-a", acct],
            capture_output=True, text=True, timeout=15,
        )
        return found.returncode == 0

    def _security_delete(svc: str, acct: str) -> None:
        subprocess.run(
            ["security", "delete-generic-password", "-s", svc, "-a", acct],
            capture_output=True, text=True, timeout=15,
        )

    def _helper_call(op: str) -> dict:
        payload = json.dumps({
            "operation": op,
            "service": service,
            "account": account,
        })
        completed = subprocess.run(
            [str(binary)],
            input=payload,
            capture_output=True,
            text=True,
            timeout=15,
        )
        try:
            return json.loads(completed.stdout or "{}")
        except json.JSONDecodeError:
            return {}

    def _helper_present() -> bool:
        if not compiled or not binary.is_file():
            return False
        body = _helper_call("read")
        return bool(body.get("ok") and body.get("secret"))

    def _helper_delete() -> None:
        if not compiled or not binary.is_file():
            return
        _helper_call("delete")

    try:
        compiled_run = subprocess.run(
            [
                "swiftc", "-O",
                "-framework", "Security",
                "-framework", "Foundation",
                "-o", str(binary),
                str(HELPER_SRC),
            ],
            capture_output=True, text=True, timeout=120,
        )
        assert compiled_run.returncode == 0, compiled_run.stderr
        compiled = True
        assert binary.is_file()
        assert os.access(binary, os.X_OK)

        signed = subprocess.run(
            ["codesign", "--force", "--sign", "-", str(binary)],
            capture_output=True, text=True, timeout=30,
        )
        assert signed.returncode == 0, signed.stderr
        verified = subprocess.run(
            ["codesign", "--verify", "--verbose=2", str(binary)],
            capture_output=True, text=True, timeout=15,
        )
        assert verified.returncode == 0, verified.stderr + verified.stdout

        monkeypatch.setenv("ONTOLOGYLAB_KEYCHAIN_HELPER", str(binary))
        monkeypatch.setattr(keychain, "KEYCHAIN_SERVICE", service)
        monkeypatch.setattr(keychain, "KEYCHAIN_SERVICE_LEGACY", legacy_service)

        write_key(account, REAL_CANARY)
        assert read_key(account) == REAL_CANARY

        write_key(account, REAL_CANARY + "-rotated")
        assert read_key(account) == REAL_CANARY + "-rotated"

        assert delete_key(account) is True
        leftover_v2 = False
        assert read_key(account) is None
        leftover_v1 = _security_present(legacy_service, account)
        leftover_v2 = _helper_present() or _security_present(service, account)
        assert leftover_v1 is False
        assert leftover_v2 is False
    finally:
        _helper_delete()
        _security_delete(service, account)
        _security_delete(legacy_service, account)
        leftover_v2 = _helper_present() or _security_present(service, account)
        leftover_v1 = _security_present(legacy_service, account)
        if binary.exists():
            binary.chmod(stat.S_IRWXU)
            binary.unlink()
        if work.exists():
            shutil.rmtree(work, ignore_errors=True)
        assert leftover_v1 is False
        assert leftover_v2 is False
        assert not binary.exists()
        assert not work.exists()
