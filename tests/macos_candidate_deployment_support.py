"""Synthetic standalone deployment payload used by Task 11 candidate tests."""

from __future__ import annotations

import hashlib
import json
import os
import shlex
import subprocess
import sys
from pathlib import Path
from typing import Final

from release import candidate_build as candidate
from release.candidate_stage import StageLayout

ROOT: Final = Path(__file__).resolve().parents[1]
_EXECUTABLE_REL: Final = "Contents/MacOS/ontologylab-internal-deploy"
_SUPERVISOR_REL: Final = "Contents/MacOS/ontologylab-supervisor"
_DIAGNOSTIC_LIMIT: Final = 4_096


def _bounded_output(value: str | bytes | None) -> str:
    if value is None:
        return ""
    text = value.decode(errors="replace") if isinstance(value, bytes) else value
    if len(text) <= _DIAGNOSTIC_LIMIT:
        return text
    half = _DIAGNOSTIC_LIMIT // 2
    return f"{text[:half]}\n...[truncated]...\n{text[-half:]}"


def _run_pyinstaller(
    command: tuple[str, ...], cwd: Path, environment: dict[str, str]
) -> None:
    try:
        subprocess.run(
            command,
            cwd=cwd,
            env=environment,
            check=True,
            capture_output=True,
            text=True,
            timeout=300,
        )
    except subprocess.CalledProcessError as error:
        raise AssertionError(
            f"standalone build failed returncode={error.returncode} "
            f"command={shlex.join(command)}\n"
            f"stdout:\n{_bounded_output(error.stdout)}\n"
            f"stderr:\n{_bounded_output(error.stderr)}"
        ) from error
    except subprocess.TimeoutExpired as error:
        raise AssertionError(
            f"standalone build timed out timeout={error.timeout} "
            f"command={shlex.join(command)}\n"
            f"stdout:\n{_bounded_output(error.stdout)}\n"
            f"stderr:\n{_bounded_output(error.stderr)}"
        ) from error


def build_standalone_pair(
    first: StageLayout, second: StageLayout, tmp_path: Path
) -> tuple[tuple[str, bytes], tuple[str, bytes]]:
    """Build and assemble the standalone executable from two derived roots."""
    home = tmp_path / "home"
    home.mkdir()
    environment = os.environ.copy()
    environment.update(
        {
            "HOME": str(home),
            "PYTHONHASHSEED": "0",
            "SOURCE_DATE_EPOCH": "0",
            "UV_FROZEN": "1",
            "UV_OFFLINE": "1",
            "UV_CACHE_DIR": os.environ.get(
                "UV_CACHE_DIR", str(Path.home() / ".cache" / "uv")
            ),
        }
    )
    results: list[tuple[str, bytes]] = []
    for label, layout in zip(("a", "b"), (first, second), strict=True):
        build = tmp_path / f"build-{label}"
        _run_pyinstaller(
            (
                "uv",
                "run",
                "--frozen",
                "--offline",
                "--extra",
                "server",
                "--with",
                "pyinstaller==6.16.0",
                "pyinstaller",
                "--noconfirm",
                "--clean",
                "--distpath",
                str(build / "dist"),
                "--workpath",
                str(build / "work"),
                str(
                    layout.build_root
                    / "release/pyinstaller/ontologylab-internal-deployment.spec"
                ),
            ),
            layout.build_root,
            environment | {"UV_PROJECT_ENVIRONMENT": sys.prefix},
        )
        executable = build / "dist/ontologylab-internal-deploy"
        app = build / "OntologyLab.app"
        deployed = app / _EXECUTABLE_REL
        deployed.parent.mkdir(parents=True)
        deployed.write_bytes(executable.read_bytes())
        (app / _SUPERVISOR_REL).write_bytes(Path("/usr/bin/true").read_bytes())
        (app / "Contents/Info.plist").write_text(
            """<?xml version="1.0" encoding="UTF-8"?>
<plist version="1.0"><dict>
<key>CFBundleIdentifier</key><string>town.neobio.ontologylab.test</string>
<key>CFBundleExecutable</key><string>ontologylab-supervisor</string>
<key>CFBundlePackageType</key><string>APPL</string>
</dict></plist>
""",
            encoding="utf-8",
        )
        resources = app / "Contents/Resources"
        resources.mkdir()
        executable_sha256 = hashlib.sha256(deployed.read_bytes()).hexdigest()
        (resources / "internal-deployment.json").write_text(
            json.dumps(
                {
                    "architecture": "arm64",
                    "executable_path": _EXECUTABLE_REL,
                    "executable_sha256": executable_sha256,
                    "schema": "ontologylab.internal-deployment-build.v1",
                    "version": "0.1.0",
                },
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        subprocess.run(
            ("codesign", "--force", "--sign", "-", "--timestamp=none", str(app)),
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
        )
        normalized = json.dumps(
            candidate.normalized_tree_manifest(
                app, frozenset({_EXECUTABLE_REL, _SUPERVISOR_REL})
            ),
            sort_keys=True,
        ).encode()
        results.append((executable_sha256, normalized))
    return results[0], results[1]


def add_storage_matrix(payload: Path) -> None:
    resources = payload / "Contents" / "Resources"
    resources.mkdir(parents=True, exist_ok=True)
    (resources / "storage-compatibility.json").write_bytes(
        (ROOT / "ontologylab" / "storage-compatibility.json").read_bytes()
    )


def add_license_fixture(
    payload: Path,
    *,
    include_storage_matrix: bool = True,
    include_internal_deployment: bool | None = None,
) -> None:
    if include_storage_matrix:
        add_storage_matrix(payload)
    runtime = payload / "Contents" / "Resources" / "runtime"
    metadata_dir = runtime / "_internal" / "fixture-1.0.dist-info"
    metadata_dir.mkdir(parents=True)
    (metadata_dir / "METADATA").write_text(
        "Name: fixture\nVersion: 1.0\nLicense: MIT\n", encoding="utf-8"
    )
    evidence = metadata_dir / "LICENSE"
    evidence.write_text("fixture license\n", encoding="utf-8")
    (runtime / "sbom.json").write_text(
        json.dumps(
            {
                "components": [{"name": "fixture", "version": "1.0", "license": "MIT"}],
                "licenses": [],
            }
        ),
        encoding="utf-8",
    )
    include_deployment = (
        include_storage_matrix
        if include_internal_deployment is None
        else include_internal_deployment
    )
    if include_deployment:
        add_internal_deployment_fixture(payload)


def add_internal_deployment_fixture(payload: Path) -> None:
    """Add one synthetic thin-arm64 deployment surface for sealing tests."""
    executable = payload / _EXECUTABLE_REL
    executable.parent.mkdir(parents=True, exist_ok=True)
    executable.write_bytes(b"\xcf\xfa\xed\xfe" + b"fixture-arm64")
    executable.chmod(0o755)
    resources = payload / "Contents/Resources"
    matrix = resources / "storage-compatibility.json"
    bundled_matrix = (
        resources / "runtime/_internal/ontologylab/storage-compatibility.json"
    )
    bundled_matrix.parent.mkdir(parents=True, exist_ok=True)
    bundled_matrix.write_bytes(matrix.read_bytes())
    manifest = {
        "architecture": "arm64",
        "executable_path": _EXECUTABLE_REL,
        "executable_sha256": hashlib.sha256(executable.read_bytes()).hexdigest(),
        "schema": "ontologylab.internal-deployment-build.v1",
        "version": "0.1.0",
    }
    (resources / "internal-deployment.json").write_text(
        json.dumps(manifest, sort_keys=True) + "\n", encoding="utf-8"
    )
    (resources / "native-inventory.json").write_text(
        json.dumps(
            {
                "architecture": "arm64",
                "files": [
                    {
                        "architecture": "arm64",
                        "dependencies": ["/usr/lib/libSystem.B.dylib"],
                        "path": _EXECUTABLE_REL,
                    }
                ],
                "schema": "ontologylab.runtime-native-inventory.v1",
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
