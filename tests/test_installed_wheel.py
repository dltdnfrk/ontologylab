"""The installed wheel alone must serve the complete dashboard.

Builds the wheel and sdist into a disposable directory, inspects both
archives for the packaged resource tree, installs the wheel into a clean
venv with the checkout hidden (cwd outside the repo, no PYTHONPATH,
interpreter safe-path), starts ``ontologylab-serve`` on an ephemeral port,
and requires the document, every manifest asset, and the health endpoint
over HTTP — byte-identical to the source tree.

Run directly:

    uv run --all-extras pytest tests/test_installed_wheel.py -v
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import tarfile
import threading
import urllib.error
import urllib.request
import zipfile
from collections.abc import Iterator
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SOURCE_ASSET_DIR = ROOT / "ontologylab" / "web"
# The machine-consumed set the wheel must ship (mirrors the prep map).
REQUIRED_ASSETS: tuple[str, ...] = (
    "index.html",
    "favicon.svg",
    "app.js",
    "chat-session.js",
    "localize.js",
    "research-summary.js",
    "ui-utils.js",
    "style.css",
    "fonts/PretendardVariable.woff2",
    "manifest.json",
)
_READY_DEADLINE_S = 30.0


def _run(cmd: list[str], **kwargs) -> subprocess.CompletedProcess[str]:  # type: ignore[type-arg]
    kwargs.setdefault("timeout", 300)
    return subprocess.run(cmd, capture_output=True, text=True, check=True, **kwargs)


def _get(url: str, timeout: float = 5.0) -> tuple[int, dict[str, str], bytes]:
    request = urllib.request.Request(url)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            headers = {k.lower(): v for k, v in response.headers.items()}
            return response.status, headers, response.read()
    except urllib.error.HTTPError as exc:
        return exc.code, {k.lower(): v for k, v in exc.headers.items()}, exc.read()


@pytest.fixture(scope="module")
def dist_dir(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Wheel + sdist built into a disposable directory."""
    out = tmp_path_factory.mktemp("dist")
    _run(
        ["uv", "build", "--sdist", "--wheel", "--out-dir", str(out)], cwd=ROOT
    )
    return out


def _wheel_path(dist: Path) -> Path:
    wheels = list(dist.glob("*.whl"))
    assert len(wheels) == 1, f"expected exactly one wheel in {dist}"
    return wheels[0]


def _sdist_path(dist: Path) -> Path:
    sdists = list(dist.glob("*.tar.gz"))
    assert len(sdists) == 1, f"expected exactly one sdist in {dist}"
    return sdists[0]


def test_wheel_contains_dashboard_resource_tree(dist_dir: Path) -> None:
    # Given the built wheel
    names = set(zipfile.ZipFile(_wheel_path(dist_dir)).namelist())
    # When the dashboard resource members are looked up
    missing = [
        f"ontologylab/web/{rel}"
        for rel in REQUIRED_ASSETS
        if f"ontologylab/web/{rel}" not in names
    ]
    # Then every asset and the manifest are packaged
    assert not missing, f"wheel is missing dashboard resources: {missing}"


def test_sdist_contains_dashboard_resource_tree(dist_dir: Path) -> None:
    # Given the built sdist
    with tarfile.open(_sdist_path(dist_dir)) as archive:
        names = set(archive.getnames())
    # When the dashboard resource members are looked up
    missing = [
        rel
        for rel in REQUIRED_ASSETS
        if not any(name.endswith(f"ontologylab/web/{rel}") for name in names)
    ]
    # Then every asset and the manifest are packaged
    assert not missing, f"sdist is missing dashboard resources: {missing}"


@pytest.fixture(scope="module")
def installed_server(
    dist_dir: Path, tmp_path_factory: pytest.TempPathFactory
) -> Iterator[tuple[str, Path]]:
    """Wheel installed into a clean venv; server up with checkout hidden."""
    work = tmp_path_factory.mktemp("installed")
    venv = work / "venv"
    _run(["uv", "venv", str(venv)])
    python = venv / "bin" / "python"
    _run(
        [
            "uv",
            "pip",
            "install",
            "--python",
            str(python),
            str(_wheel_path(dist_dir)),
            "fastapi",
            "uvicorn[standard]",
        ]
    )
    data_dir = work / "data"
    packs_dir = work / "packs"
    data_dir.mkdir()
    packs_dir.mkdir()
    env = {
        "PATH": os.environ.get("PATH", ""),
        "HOME": os.environ.get("HOME", ""),
        "TMPDIR": os.environ.get("TMPDIR", "/tmp"),
        "PYTHONNOUSERSITE": "1",
    }
    proc = subprocess.Popen(
        [
            str(python),
            "-P",
            "-m",
            "ontologylab.serve",
            "--port",
            "0",
            "--data-dir",
            str(data_dir),
            "--packs-dir",
            str(packs_dir),
        ],
        cwd=work,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    ready = threading.Event()
    urls: list[str] = []
    output: list[str] = []

    def observe_startup() -> None:
        assert proc.stdout is not None
        for line in proc.stdout:
            output.append(line)
            match = re.search(r"Uvicorn running on (http://127\.0\.0\.1:\d+)", line)
            if match is not None:
                urls.append(match.group(1))
                ready.set()
        ready.set()  # An early exit wakes the fixture without a polling delay.

    observer = threading.Thread(target=observe_startup, daemon=True)
    try:
        observer.start()
        assert ready.wait(timeout=_READY_DEADLINE_S), "installed server startup event timed out"
        assert len(urls) == 1, f"installed server did not publish its bound URL:\n{''.join(output)}"
        base_url = urls[0]
        status, _, _ = _get(f"{base_url}/healthz")
        assert status == 200
        yield base_url, work
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=10)
        if observer.ident is not None:
            observer.join(timeout=5)
            assert not observer.is_alive()


def _source_manifest_entries() -> list[dict[str, object]]:
    payload = json.loads((SOURCE_ASSET_DIR / "manifest.json").read_text())
    return payload["assets"]


def test_installed_server_serves_every_manifest_asset(
    installed_server: tuple[str, Path],
) -> None:
    # Given the installed server and the source manifest
    base_url, _ = installed_server
    entries = _source_manifest_entries()
    # When the document root is requested
    status, headers, body = _get(f"{base_url}/")
    # Then it serves the source index byte for byte
    assert status == 200
    assert headers.get("content-type", "").startswith("text/html")
    source_index = (SOURCE_ASSET_DIR / "index.html").read_bytes()
    assert hashlib.sha256(body).hexdigest() == hashlib.sha256(
        source_index
    ).hexdigest()
    # And every manifest path answers 200 with the source bytes
    for entry in entries:
        rel = str(entry["path"])
        status, _, body = _get(f"{base_url}/static/{rel}")
        assert status == 200, rel
        assert body == (SOURCE_ASSET_DIR / rel).read_bytes(), rel
    # And the health endpoint still answers
    status, _, _ = _get(f"{base_url}/healthz")
    assert status == 200


def test_installed_asset_tree_matches_source_byte_for_byte(
    installed_server: tuple[str, Path],
) -> None:
    # Given the installed venv and the source resource tree
    _, work = installed_server
    manifest = next((work / "venv").rglob("ontologylab/web/manifest.json"), None)
    assert manifest is not None, "installed manifest.json not found"
    installed_root = manifest.parent
    # When manifest and every manifest-listed asset are compared
    # Then installed bytes equal source bytes exactly
    assert manifest.read_bytes() == (SOURCE_ASSET_DIR / "manifest.json").read_bytes()
    for entry in _source_manifest_entries():
        rel = str(entry["path"])
        assert (installed_root / rel).read_bytes() == (
            SOURCE_ASSET_DIR / rel
        ).read_bytes(), rel
