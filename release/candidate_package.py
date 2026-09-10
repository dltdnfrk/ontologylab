"""Sign one Task 11 candidate payload and package it as the shipped artifact.

This is the step between `release.candidate_cli` (which builds the unsigned
payload) and `release.task12_finalize` (which binds the finished artifact to an
external authority). Until 2026-09-10 it existed only as an untracked scratch
script, so the repository could build a payload it could not turn into an
installable artifact. Four defects found while reconstructing it are encoded
here rather than in a procedure:

* The receipt hash must come from the same function the installer verifies
  with, `scripts.internal_deployment_fs.tree_sha256`. A private tree hash gave
  `70fdf00d…` where the check computed `23e3f47f…`, and installation refused
  with `artifact_sha256_mismatch`.
* Signing embeds a signature into every Mach-O, which invalidates every hash
  `runtime-manifest.json` recorded before signing. Without a post-sign rewrite
  and re-seal the app installs and then refuses to start with
  `runtime_preflight_refused code=file_mutated`.
* The shipped bundle must stay writable. Freezing it read-only makes
  installation die in `shutil.rmtree` cleanup with `PermissionError`.
* The source binding is read from the issued release receipt. It used to be a
  literal, so the artifact asserted a binding nothing had checked.
"""

from __future__ import annotations

import json
import shutil
import stat
import subprocess
import sys
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from scripts.internal_deployment_fs import sha256_file, tree_sha256

_CODESIGN: Final = "/usr/bin/codesign"
_HDIUTIL: Final = "/usr/bin/hdiutil"
_FILE: Final = "/usr/bin/file"
_SIGN_ARGUMENTS: Final = ("--force", "--sign", "-", "--options", "runtime", "--timestamp=none")
_VERIFY_DEEP: Final = ("--verify", "--deep", "--strict", "--verbose=4")
_ACKNOWLEDGEMENT: Final = (
    "OntologyLab internal ad-hoc build.\n"
    "Use only on an approved internal Apple Silicon macOS 15+ system.\n"
    "Installation requires the explicit --acknowledge-unnotarized flag.\n"
    "This package carries no Apple distribution trust and is not for public "
    "distribution.\n"
)


class PackageRefused(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class PackageRequest:
    candidate_app: Path
    native_inventory: Path
    output: Path
    version: str
    runtime_contract: Path
    manifest_writer: Path
    release_receipt: Path


@dataclass(frozen=True, slots=True)
class PackageResult:
    app_tree_sha256: str
    dmg_sha256: str
    zip_sha256: str
    receipt_sha256: str
    natives_signed: int
    source_snapshot_sha256: str
    operations: tuple[str, ...]


def stage_writable_copy(source: Path, destination: Path) -> None:
    """Copy the candidate payload and restore owner-write on every entry.

    `release.candidate_cli` seals its output read-only, and the packaging steps
    below rewrite files inside the bundle. The shipped bundle stays writable:
    the installer's own cleanup removes its staging copy with `shutil.rmtree`,
    which cannot descend into read-only directories.
    """
    if destination.exists():
        raise PackageRefused(f"destination_exists:{destination}")
    shutil.copytree(source, destination, symlinks=True)
    for path in (destination, *sorted(destination.rglob("*"), reverse=True)):
        if path.is_symlink():
            continue
        path.chmod(stat.S_IMODE(path.stat().st_mode) | 0o200)


def write_artifact_receipt(app: Path, destination: Path) -> tuple[str, str]:
    """Write the install receipt for `app`, returning its tree and file hashes.

    The tree hash is `scripts.internal_deployment_fs.tree_sha256` because that
    is what `install` recomputes; producing it any other way ships a receipt
    the artifact itself fails.
    """
    signed_tree = tree_sha256(app)
    payload = {
        "schema": "ontologylab.internal-artifact-receipt.v1",
        "artifact_name": app.name,
        "app_tree_sha256": signed_tree,
    }
    destination.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")
    return signed_tree, sha256_file(destination)


def _run(command: list[str], log: Path) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(
        command, check=False, capture_output=True, text=True, timeout=180
    )
    log.write_text(
        json.dumps(
            {
                "command": command,
                "returncode": completed.returncode,
                "stdout": completed.stdout,
                "stderr": completed.stderr,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    if completed.returncode != 0:
        raise PackageRefused(f"{Path(command[0]).name}:{completed.stderr[-2000:]}")
    return completed


def _native_paths(inventory: Path) -> tuple[str, ...]:
    files = json.loads(inventory.read_text(encoding="utf-8"))["files"]
    return tuple(
        item["path"]
        for item in files
        if isinstance(item, dict) and isinstance(item.get("path"), str)
    )


def _prove_nested_signatures_are_checked(app: Path, first_native: str, logs: Path) -> None:
    """Strip one nested signature and require `--verify --deep --strict` to fail.

    Without this the deep verification below could be passing vacuously.
    """
    probe = app / "Contents" / "Resources" / "unsigned-nested-probe"
    shutil.copy2(app / first_native, probe)
    _run([_CODESIGN, "--remove-signature", str(probe)], logs / "red-remove-signature.json")
    red = subprocess.run(
        [_CODESIGN, "--verify", "--deep", "--strict", str(app)],
        check=False,
        capture_output=True,
        text=True,
        timeout=60,
    )
    (logs / "red-unsigned-nested.json").write_text(
        json.dumps(
            {
                "path": probe.relative_to(app).as_posix(),
                "returncode": red.returncode,
                "stderr": red.stderr,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    probe.unlink()
    if red.returncode == 0:
        raise PackageRefused("nested_unsigned_probe_accepted")


def _sign_native(app: Path, relative: str, logs: Path) -> dict[str, str | int | bool]:
    target = app / relative
    slug = relative.replace("/", "__")
    _run([_CODESIGN, *_SIGN_ARGUMENTS, str(target)], logs / f"sign-{slug}.json")
    verify = _run([_CODESIGN, "--verify", "--strict", str(target)], logs / f"verify-{slug}.json")
    display = subprocess.run(
        [_CODESIGN, "-dv", "--verbose=4", str(target)],
        check=False,
        capture_output=True,
        text=True,
        timeout=60,
    )
    architecture = subprocess.run(
        [_FILE, str(target)], check=True, capture_output=True, text=True, timeout=30
    )
    adhoc = "Signature=adhoc" in display.stderr or "flags=0x2(adhoc)" in display.stderr
    arm64 = "arm64" in architecture.stdout
    if not adhoc or not arm64:
        raise PackageRefused(f"unexpected_identity:{relative}")
    return {
        "path": relative,
        "verify_exit": verify.returncode,
        "signature": "adhoc",
        "runtime": "runtime" in display.stderr,
        "arm64": arm64,
        "entitlements_bytes": 0,
    }


def _write_zip(app: Path, destination: Path) -> None:
    with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(app.rglob("*")):
            if path.is_dir():
                continue
            info = zipfile.ZipInfo(
                str(Path(app.name) / path.relative_to(app)), date_time=(1980, 1, 1, 0, 0, 0)
            )
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, path.read_bytes())


def package_candidate(request: PackageRequest) -> PackageResult:
    """Sign the candidate inside-out and emit the DMG, ZIP, receipt, and sums."""
    logs = request.output / "logs"
    artifacts = request.output / "artifacts"
    manifests = request.output / "manifests"
    scratch = request.output / "scratch"
    for path in (logs, artifacts, manifests, scratch):
        path.mkdir(parents=True, exist_ok=True)

    operations: list[str] = []
    app = scratch / request.candidate_app.name
    stage_writable_copy(request.candidate_app, app)
    operations.append("stage_writable_copy")

    natives = _native_paths(request.native_inventory)
    if not natives:
        raise PackageRefused("native_inventory_empty")
    _prove_nested_signatures_are_checked(app, natives[0], logs)
    operations.append("prove_nested_signatures_are_checked")

    inventory = [_sign_native(app, relative, logs) for relative in natives]
    operations.append("sign_natives")
    _run([_CODESIGN, *_SIGN_ARGUMENTS, str(app)], logs / "sign-outer.json")
    _run([_CODESIGN, *_VERIFY_DEEP, str(app)], logs / "verify-deep.json")
    operations.append("sign_outer")
    (manifests / "signatures.json").write_text(
        json.dumps(inventory, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    # Signing rewrote every Mach-O, so the pre-sign runtime manifest now
    # describes bytes that no longer exist. Rewrite it against the signed
    # bundle and re-seal, or the app installs and refuses to start.
    _run(
        [
            sys.executable,
            str(request.manifest_writer),
            str(app / "Contents/Resources/runtime"),
            request.version,
            str(request.runtime_contract),
        ],
        logs / "post-sign-manifest.json",
    )
    operations.append("write_manifest")
    _run([_CODESIGN, *_SIGN_ARGUMENTS, str(app)], logs / "sign-outer-postmanifest.json")
    _run([_CODESIGN, *_VERIFY_DEEP, str(app)], logs / "verify-deep-postmanifest.json")
    operations.append("reseal")

    receipt_path = artifacts / "OntologyLab.receipt.json"
    signed_tree, receipt_sha = write_artifact_receipt(app, receipt_path)
    (artifacts / "OntologyLab.receipt.sha256").write_text(
        receipt_sha + "\n", encoding="utf-8"
    )
    operations.append("write_artifact_receipt")

    stage = scratch / "dmg-root"
    stage.mkdir()
    shutil.copytree(app, stage / app.name, symlinks=True)
    (stage / "UNNOTARIZED-INTERNAL-INSTALL.txt").write_text(
        _ACKNOWLEDGEMENT, encoding="utf-8"
    )
    stem = f"OntologyLab-{request.version}-internal-arm64"
    dmg = artifacts / f"{stem}.dmg"
    _run(
        [
            _HDIUTIL, "create", "-srcfolder", str(stage), "-volname", "OntologyLab",
            "-fs", "APFS", "-format", "UDZO", "-ov", str(dmg),
        ],
        logs / "hdiutil-create.json",
    )
    _run([_HDIUTIL, "verify", str(dmg)], logs / "hdiutil-verify.json")
    zip_path = artifacts / f"{stem}.zip"
    _write_zip(app, zip_path)
    (artifacts / "UNNOTARIZED-INTERNAL-INSTALL.txt").write_text(
        _ACKNOWLEDGEMENT, encoding="utf-8"
    )
    operations.append("package")

    dmg_sha = sha256_file(dmg)
    zip_sha = sha256_file(zip_path)
    (artifacts / "SHA256SUMS").write_text(
        f"{dmg_sha}  {dmg.name}\n{zip_sha}  {zip_path.name}\n"
        f"{receipt_sha}  {receipt_path.name}\n",
        encoding="utf-8",
    )
    snapshot = json.loads(request.release_receipt.read_text(encoding="utf-8"))[
        "source_snapshot_sha256"
    ]
    result = PackageResult(
        app_tree_sha256=signed_tree,
        dmg_sha256=dmg_sha,
        zip_sha256=zip_sha,
        receipt_sha256=receipt_sha,
        natives_signed=len(inventory),
        source_snapshot_sha256=snapshot,
        operations=tuple(operations),
    )
    (manifests / "package-manifest.json").write_text(
        json.dumps(
            {
                "schema": "ontologylab.task12.package-manifest.v1",
                # `hdiutil` stamps creation time and volume identity into the
                # image, so re-imaging identical bytes yields a different DMG
                # hash. The app tree and the ZIP do reproduce exactly, so they
                # are the integrity anchors and the DMG hash identifies one
                # specific image.
                "integrity_anchors": ["app_tree_sha256", "zip_sha256"],
                "image_identifier": "dmg_sha256",
                "app_tree_sha256": signed_tree,
                "zip_sha256": zip_sha,
                "dmg_sha256": dmg_sha,
                "dmg_bytes": dmg.stat().st_size,
                "natives_signed": len(inventory),
                "source_snapshot_sha256": snapshot,
                "operations": list(result.operations),
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    return result


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(prog="release.candidate_package")
    parser.add_argument("--candidate-app", type=Path, required=True)
    parser.add_argument("--native-inventory", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--runtime-contract", type=Path, required=True)
    parser.add_argument("--manifest-writer", type=Path, required=True)
    parser.add_argument("--release-receipt", type=Path, required=True)
    parsed = parser.parse_args(argv)
    result = package_candidate(
        PackageRequest(
            candidate_app=parsed.candidate_app,
            native_inventory=parsed.native_inventory,
            output=parsed.output,
            version=parsed.version,
            runtime_contract=parsed.runtime_contract,
            manifest_writer=parsed.manifest_writer,
            release_receipt=parsed.release_receipt,
        )
    )
    print(json.dumps(result.__dict__ | {"operations": list(result.operations)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
