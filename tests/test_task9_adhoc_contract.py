from __future__ import annotations

import json
import os
import shutil
import subprocess
import uuid
from dataclasses import dataclass
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
HELPER_SOURCE = ROOT / "launcher" / "keychain-helper.swift"
BUILD_SCRIPT = ROOT / "launcher" / "build-macos-app.sh"
REQUIREMENT_NORMALIZER = ROOT / "launcher" / "normalize-designated-requirement.sh"
IDENTIFIER = "town.neobio.ontologylab.keychain-helper"

pytestmark = pytest.mark.skipif(
    shutil.which("swiftc") is None or shutil.which("codesign") is None,
    reason="macOS Swift and codesign are required",
)


@dataclass(frozen=True, slots=True)
class HelperCall:
    operation: str
    service: str
    account: str
    secret: str | None = None
    keychain: Path | None = None


def _compile_and_sign(source: Path, binary: Path) -> None:
    command = ["swiftc", "-O"]
    for framework in ("Security", "Foundation"):
        command.extend(("-framework", framework))
    command.extend(("-o", str(binary), str(source)))
    subprocess.run(command, check=True, capture_output=True, text=True, timeout=120)
    sign_command = (
        "codesign",
        "--force",
        "--sign",
        "-",
        "--identifier",
        IDENTIFIER,
        str(binary),
    )
    subprocess.run(sign_command, check=True, capture_output=True, text=True, timeout=30)


def _raw_requirement(binary: Path) -> str:
    completed = subprocess.run(
        ["codesign", "-d", "-r-", str(binary)],
        check=True,
        capture_output=True,
        text=True,
        timeout=15,
    )
    return f"{completed.stdout}\n{completed.stderr}".strip()


def _normalized_requirement(raw: str) -> str:
    return next(
        line.split("=> ", 1)[1]
        for line in raw.splitlines()
        if line.startswith(("designated => ", "# designated => "))
    )


def _call_helper(
    binary: Path,
    call: HelperCall,
) -> tuple[int, dict[str, bool | str]]:
    payload: dict[str, str] = {
        "operation": call.operation,
        "service": call.service,
        "account": call.account,
    }
    if call.secret is not None:
        payload["secret"] = call.secret
    if call.keychain is not None:
        payload["keychain"] = str(call.keychain)
    completed = subprocess.run(
        [str(binary)],
        input=json.dumps(payload, separators=(",", ":")),
        check=False,
        capture_output=True,
        text=True,
        timeout=15,
    )
    return completed.returncode, json.loads(completed.stdout)


@pytest.mark.parametrize("prefix", ["designated => ", "# designated => "])
def test_requirement_normalizer_accepts_only_supported_prefixes(
    prefix: str,
) -> None:
    requirement = 'cdhash H"0123456789ABCDEF"'
    completed = subprocess.run(
        ["bash", str(REQUIREMENT_NORMALIZER)],
        input=f"Executable=/tmp/helper\n{prefix}{requirement}\n",
        check=False,
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert completed.returncode == 0
    assert completed.stdout == requirement + "\n"


@pytest.mark.parametrize(
    "raw",
    [
        "",
        "Executable=/tmp/helper\n",
        "# designated => \n",
        " ## designated => requirement\n",
        "designated => one\n# designated => two\n",
    ],
)
def test_requirement_normalizer_refuses_missing_or_malformed_output(
    raw: str,
) -> None:
    completed = subprocess.run(
        ["bash", str(REQUIREMENT_NORMALIZER)],
        input=raw,
        check=False,
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert completed.returncode != 0
    assert completed.stdout == ""


def test_adhoc_build_accepts_hash_prefixed_designated_requirement(
    tmp_path: Path,
) -> None:
    # Given a real ad-hoc signing identity whose codesign output uses '# designated =>'
    backend = tmp_path / "backend"
    backend.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    backend.chmod(0o755)
    environment = os.environ.copy()
    environment["CODESIGN_IDENTITY"] = "-"

    # When the product build extracts the helper's designated requirement
    completed = subprocess.run(
        [
            "bash",
            str(BUILD_SCRIPT),
            "--out",
            str(tmp_path / "out"),
            "--backend",
            str(backend),
        ],
        cwd=ROOT,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
        timeout=240,
    )

    # Then the build accepts the actual hash-prefixed format strictly
    assert completed.returncode == 0, completed.stderr
    requirement_file = (
        tmp_path / "out/ontologylab.app/Contents/Resources/keychain-helper.requirement"
    )
    requirement = requirement_file.read_text(encoding="utf-8").strip()
    assert requirement.startswith('cdhash H"')


def test_independent_adhoc_replacement_uses_pretrusted_test_keychain(
    tmp_path: Path,
) -> None:
    # Given finalized independent N/N+1 helpers and one unlocked disposable keychain
    build_n = tmp_path / "n"
    build_n1 = tmp_path / "n1"
    build_n.mkdir()
    build_n1.mkdir()
    source_n = build_n / "keychain-helper.swift"
    source_n1 = build_n1 / "keychain-helper.swift"
    source_text = HELPER_SOURCE.read_text(encoding="utf-8")
    source_n.write_text(source_text, encoding="utf-8")
    source_n1.write_text(
        source_text.replace(
            "private let maxRequestBytes = 1_048_576",
            "private let maxRequestBytes = 1_048_575",
        ),
        encoding="utf-8",
    )
    helper_n = build_n / "keychain-helper"
    helper_n1 = build_n1 / "keychain-helper"
    _compile_and_sign(source_n, helper_n)
    _compile_and_sign(source_n1, helper_n1)
    requirement_n = _normalized_requirement(_raw_requirement(helper_n))
    requirement_n1 = _normalized_requirement(_raw_requirement(helper_n1))
    service = f"ontologylab.task9.adhoc.{uuid.uuid4().hex[:12]}"
    account = f"acct.{uuid.uuid4().hex[:12]}"
    secret = "task9-public-disposable-value"
    keychain = tmp_path / "task9-test.keychain-db"
    for action in ("create-keychain", "unlock-keychain"):
        subprocess.run(
            ["/usr/bin/security", action, "-p", "", str(keychain)],
            check=True,
            capture_output=True,
            text=True,
            timeout=15,
        )
    add_item = subprocess.run(
        [
            "/usr/bin/security",
            "add-generic-password",
            "-a",
            account,
            "-s",
            service,
            "-T",
            str(helper_n),
            "-T",
            str(helper_n1),
            "-w",
            secret,
            str(keychain),
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert add_item.returncode == 0, add_item.stderr

    try:
        # When both exact finalized binaries use that pre-authorized item in one batch
        read_n = _call_helper(
            helper_n, HelperCall("read", service, account, keychain=keychain)
        )
        assert read_n[0] == 0 and read_n[1].get("secret") == secret
        assert _call_helper(
            helper_n, HelperCall("write", service, account, secret, keychain)
        ) == (0, {"ok": True})
        read_n1 = _call_helper(
            helper_n1, HelperCall("read", service, account, keychain=keychain)
        )
        assert read_n1[0] == 0 and read_n1[1].get("secret") == secret
        assert _call_helper(
            helper_n1,
            HelperCall("write", service, account, secret + "-rotated", keychain),
        ) == (0, {"ok": True})
        rotated = _call_helper(
            helper_n1, HelperCall("read", service, account, keychain=keychain)
        )
        assert rotated[0] == 0 and rotated[1].get("secret") == secret + "-rotated"
        assert _call_helper(
            helper_n1, HelperCall("delete", service, account, keychain=keychain)
        ) == (0, {"ok": True})

        # Then requirements remain distinct and N cannot authenticate N+1
        assert requirement_n != requirement_n1
        cross_verify = subprocess.run(
            [
                "codesign",
                "--verify",
                "--strict",
                "--test-requirement",
                f"={requirement_n}",
                str(helper_n1),
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=15,
        )
        assert cross_verify.returncode != 0
    finally:
        subprocess.run(
            ["/usr/bin/security", "delete-keychain", str(keychain)],
            check=False,
            capture_output=True,
            text=True,
            timeout=15,
        )
