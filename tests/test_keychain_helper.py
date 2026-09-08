"""Native Keychain transport units for typed failures and migration safety.

Real helper lifecycle runs only against the pre-authorized disposable keychain
in test_task9_adhoc_contract.py.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from ontologylab import keychain
from ontologylab.keychain import KeychainError, write_key

MALFORMED_CANARY = "CANARY-malformed-helper-7f2c"
UNAUTHORIZED_CANARY = "CANARY-unauthorized-helper-7f2c"
LOCKED_CANARY = "CANARY-locked-helper-7f2c"
DENIED_CANARY = "CANARY-denied-helper-7f2c"
REAUTH_CANARY = "CANARY-reauthorization-helper-7f2c"
TIMEOUT_CANARY = "CANARY-timeout-helper-7f2c"
MIGRATE_FAIL_CANARY = "CANARY-migrate-order-7f2c"
MIGRATE_OK_CANARY = "CANARY-migrate-success-7f2c"

TEST_SERVICE = "ontologylab-pytest-helper"
TEST_SERVICE_LEGACY = "ontologylab-pytest-helper-legacy"


@pytest.fixture(autouse=True)
def _isolate_helper_service(monkeypatch, request):
    if request.node.name == "test_product_service_is_v2":
        yield
        return
    monkeypatch.setattr(keychain, "KEYCHAIN_SERVICE", TEST_SERVICE)
    monkeypatch.setattr(keychain, "KEYCHAIN_SERVICE_LEGACY", TEST_SERVICE_LEGACY)
    yield


def _dummy_helper(tmp_path: Path) -> Path:
    helper = tmp_path / "keychain-helper"
    helper.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    helper.chmod(0o755)
    return helper


def test_legacy_reads_use_absolute_security_binary(monkeypatch) -> None:
    calls: list[list[str]] = []

    def _run(argv, **kwargs):
        calls.append(list(argv))
        return subprocess.CompletedProcess(argv, 1, "", "")

    monkeypatch.setattr(
        shutil,
        "which",
        lambda name: "/usr/bin/security" if name == "/usr/bin/security" else None,
    )
    monkeypatch.setattr(keychain.subprocess, "run", _run)

    assert keychain._read_legacy("ontologylab.test.absolute") is None
    assert calls[0][0] == "/usr/bin/security"


def test_failed_legacy_cleanup_rolls_back_native_migration(monkeypatch) -> None:
    stored: dict[str, str] = {}
    operations: list[tuple[str, str]] = []

    def _invoke(operation, account, secret=None, service=None):
        del service
        operations.append((operation, account))
        if operation == "write" and secret is not None:
            stored[account] = secret
        elif operation == "delete":
            stored.pop(account, None)
        return {"ok": True}

    monkeypatch.setattr(keychain, "_resolved_helper_path", lambda: "/helper")
    monkeypatch.setattr(keychain, "_invoke_helper", _invoke)
    monkeypatch.setattr(keychain, "_read_native", stored.get)
    monkeypatch.setattr(keychain, "_delete_legacy", lambda account: False)

    assert (
        keychain._try_migrate("ontologylab.test.cleanup", MIGRATE_FAIL_CANARY) is False
    )
    assert ("delete", "ontologylab.test.cleanup") in operations
    assert stored == {}


def test_helper_path_rejects_group_writable_binary(monkeypatch, tmp_path) -> None:
    helper = _dummy_helper(tmp_path)
    helper.chmod(0o775)
    monkeypatch.setenv("ONTOLOGYLAB_KEYCHAIN_HELPER", str(helper))

    assert keychain._resolved_helper_path() is None


def test_helper_path_enforces_configured_codesign_requirement(
    monkeypatch, tmp_path
) -> None:
    helper = _dummy_helper(tmp_path)
    helper.chmod(0o700)
    monkeypatch.setenv("ONTOLOGYLAB_KEYCHAIN_HELPER", str(helper))
    monkeypatch.setenv(
        "ONTOLOGYLAB_KEYCHAIN_HELPER_REQUIREMENT",
        'identifier "town.neobio.ontologylab.keychain-helper"',
    )
    calls: list[list[str]] = []

    def _run(argv, **kwargs):
        calls.append(list(argv))
        return subprocess.CompletedProcess(argv, 1, "", "invalid signature")

    monkeypatch.setattr(keychain.subprocess, "run", _run)

    assert keychain._resolved_helper_path() is None
    assert calls[0][:3] == ["/usr/bin/codesign", "--verify", "--strict"]


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


@pytest.mark.parametrize(
    ("helper_error", "canary"),
    [
        ("locked", LOCKED_CANARY),
        ("denied", DENIED_CANARY),
        ("reauthorization_required", REAUTH_CANARY),
    ],
)
def test_helper_preserves_typed_credential_states_without_secret(
    monkeypatch, tmp_path, helper_error: str, canary: str
) -> None:
    helper = _dummy_helper(tmp_path)
    monkeypatch.setenv("ONTOLOGYLAB_KEYCHAIN_HELPER", str(helper))

    def _run(argv, **kwargs):
        return subprocess.CompletedProcess(
            argv, 3, json.dumps({"ok": False, "error": helper_error}), ""
        )

    monkeypatch.setattr(keychain.subprocess, "run", _run)

    with pytest.raises(KeychainError) as excinfo:
        write_key(f"ontologylab.test.{helper_error}", canary)

    assert excinfo.value.kind == helper_error
    assert canary not in str(excinfo.value)


def test_hung_helper_is_bounded_and_secret_safe(monkeypatch, tmp_path) -> None:
    helper = _dummy_helper(tmp_path)
    monkeypatch.setenv("ONTOLOGYLAB_KEYCHAIN_HELPER", str(helper))
    calls: list[list[str]] = []

    def _run(argv, **kwargs):
        calls.append(list(argv))
        raise subprocess.TimeoutExpired(argv, kwargs["timeout"])

    monkeypatch.setattr(keychain.subprocess, "run", _run)

    with pytest.raises(KeychainError) as excinfo:
        write_key("ontologylab.test.timeout", TIMEOUT_CANARY)

    assert excinfo.value.kind == "timeout"
    assert TIMEOUT_CANARY not in str(excinfo.value)
    assert all(TIMEOUT_CANARY not in argv for argv in calls)


def test_tampered_requirement_is_a_typed_refusal(monkeypatch, tmp_path) -> None:
    helper = _dummy_helper(tmp_path)
    monkeypatch.setenv("ONTOLOGYLAB_KEYCHAIN_HELPER", str(helper))
    monkeypatch.setenv(
        "ONTOLOGYLAB_KEYCHAIN_HELPER_REQUIREMENT",
        'identifier "stale.helper"',
    )

    def _run(argv, **kwargs):
        return subprocess.CompletedProcess(argv, 1, "", "requirement failed")

    monkeypatch.setattr(keychain.subprocess, "run", _run)

    with pytest.raises(KeychainError) as excinfo:
        write_key("ontologylab.test.requirement", "value")

    assert excinfo.value.kind == "missing_helper"


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
    monkeypatch.setattr(keychain, "read_key", lambda _acct: "should-not-be-used")

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
