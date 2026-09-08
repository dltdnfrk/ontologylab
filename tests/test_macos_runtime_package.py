"""Task 4 contracts for the relocatable arm64 onedir runtime."""

from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path

import pytest

from ontologylab import (
    main,
    mcp_server,
    runtime_bundle,
    serve,
    serve_desktop,
    web_assets,
)
from ontologylab.runtime_bundle import RuntimePreflightError, preflight
from release.pyinstaller.rewrite_zip import rewrite_payload_zips
from release.pyinstaller.write_manifest import write_manifest

ROOT = Path(__file__).resolve().parents[1]
BUILD_CONTRACT = ROOT / "release" / "runtime-build.json"
SPEC = ROOT / "release" / "pyinstaller" / "ontologylab-runtime.spec"
BUILD_SCRIPT = ROOT / "scripts" / "build-macos-runtime.sh"
MCP_CONFIG = ROOT / "release" / "mcp-config.json"


def test_installed_entry_contracts_are_preserved_for_bundled_dispatch() -> None:
    # Given the installed package modules used by the four public surfaces.
    entries = (main.main, serve.main, mcp_server.main, serve_desktop.main)
    # When their call targets and packaged dashboard are inspected.
    assets = web_assets.verify_assets()
    # Then every entry remains callable and dashboard bytes are authoritative.
    assert all(callable(entry) for entry in entries)
    assert {entry.path for entry in assets.entries} == set(assets.content)


def test_relocatable_onedir_build_contract_exists() -> None:
    # Given a source checkout with no external runtime fallback.
    # When Task 4 build inputs are resolved.
    required = (BUILD_CONTRACT, SPEC, BUILD_SCRIPT)
    # Then a deterministic onedir build contract is present.
    assert all(path.is_file() for path in required), (
        "relocatable runtime behavior is absent: "
        + ", ".join(
            str(path.relative_to(ROOT)) for path in required if not path.is_file()
        )
    )
    payload = json.loads(BUILD_CONTRACT.read_text(encoding="utf-8"))
    assert payload["format"] == "onedir"
    assert payload["architecture"] == "arm64"
    assert payload["network_at_runtime"] is False
    spec = SPEC.read_text(encoding="utf-8")
    assert "exclude_binaries=True" in spec
    assert "COLLECT(" in spec
    assert "onefile" not in spec.lower()


def test_payload_zip_rewrite_pins_member_bytes_and_ignores_deflate_drift(
    tmp_path: Path,
) -> None:
    # Given two zips with identical members and different DEFLATE containers.
    payload = b"re-parser-bytecode" * 4096
    first = tmp_path / "a" / "_internal" / "base_library.zip"
    second = tmp_path / "b" / "_internal" / "base_library.zip"
    first.parent.mkdir(parents=True)
    second.parent.mkdir(parents=True)
    for path, level in ((first, 1), (second, 9)):
        with zipfile.ZipFile(
            path,
            "w",
            compression=zipfile.ZIP_DEFLATED,
            compresslevel=level,
        ) as archive:
            archive.writestr("re/_parser.pyc", payload)
    assert first.read_bytes() != second.read_bytes()

    # When each runtime tree is rewritten, then the zip bytes match.
    rewrite_payload_zips(tmp_path / "a")
    rewrite_payload_zips(tmp_path / "b")
    assert first.read_bytes() == second.read_bytes()
    with zipfile.ZipFile(first) as archive:
        info = archive.getinfo("re/_parser.pyc")
        assert archive.read("re/_parser.pyc") == payload
        assert info.compress_type == zipfile.ZIP_STORED
        assert info.date_time == (1980, 1, 1, 0, 0, 0)


def test_app_build_rewrites_runtime_zips_before_inventories() -> None:
    # Given the authoritative application payload build source.
    script = BUILD_SCRIPT.read_text(encoding="utf-8")

    # When its runtime assembly is inspected, then zip bytes are pinned.
    assert 'uv run python "$ROOT/release/pyinstaller/rewrite_zip.py"' in script
    assert '"$APP/Contents/Resources/runtime"' in script
    rewrite_at = script.index(
        'uv run python "$ROOT/release/pyinstaller/rewrite_zip.py"'
    )
    inventory_at = script.index(
        'uv run python "$ROOT/release/pyinstaller/write_sbom.py"'
    )
    assert rewrite_at < inventory_at


def test_app_build_declares_exact_storage_matrix_resource() -> None:
    # Given the authoritative application payload build source.
    script = BUILD_SCRIPT.read_text(encoding="utf-8")

    # When its outer resource assembly is inspected, then source and target are exact.
    assert '"$ROOT/ontologylab/storage-compatibility.json"' in script
    assert '"$APP/Contents/Resources/storage-compatibility.json"' in script


def test_runtime_configuration_is_bundle_relative() -> None:
    # Given every machine-consumed runtime build configuration.
    paths = (BUILD_CONTRACT, SPEC, MCP_CONFIG)
    # When their shipped text is inspected.
    text = "\n".join(path.read_text(encoding="utf-8") for path in paths)
    mcp = json.loads(MCP_CONFIG.read_text(encoding="utf-8"))
    # Then no development-machine path or external MCP command is encoded.
    assert "/Users/" not in text
    assert ".venv" not in text
    assert "/opt/homebrew" not in text
    assert mcp["mcpServers"]["ontologylab"]["command"].startswith("../runtime/")


def _runtime_fixture(tmp_path: Path) -> Path:
    root = tmp_path / "runtime"
    root.mkdir()
    (root / "payload.txt").write_text("self-contained\n", encoding="utf-8")
    contract = tmp_path / "contract.json"
    contract.write_text("{}\n", encoding="utf-8")
    write_manifest(root, "0.1.0", contract)
    return root


def test_runtime_preflight_accepts_content_pinned_onedir(tmp_path: Path) -> None:
    # Given a complete content-pinned onedir payload.
    root = _runtime_fixture(tmp_path)
    # When runtime preflight verifies the payload.
    manifest = preflight(root)
    # Then its version and format are available to the dispatcher.
    assert (manifest.version, manifest.format) == ("0.1.0", "onedir")


def test_runtime_preflight_refuses_missing_payload_file(tmp_path: Path) -> None:
    # Given a manifest whose declared payload was removed.
    root = _runtime_fixture(tmp_path)
    (root / "payload.txt").unlink()
    # When preflight runs, then startup refuses before product code dispatch.
    with pytest.raises(RuntimePreflightError, match="code=file_missing"):
        preflight(root)


def test_runtime_preflight_refuses_mutated_manifest(tmp_path: Path) -> None:
    # Given a manifest changed without its detached digest receipt.
    root = _runtime_fixture(tmp_path)
    manifest = root / "runtime-manifest.json"
    manifest.write_bytes(manifest.read_bytes() + b" ")
    # When preflight runs, then the altered authority is refused.
    with pytest.raises(RuntimePreflightError, match="code=manifest_digest"):
        preflight(root)


def test_runtime_preflight_refuses_missing_mcp_module(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Given a valid payload whose bundled MCP module is absent from the importer.
    root = _runtime_fixture(tmp_path)
    real_find_spec = runtime_bundle.importlib.util.find_spec
    monkeypatch.setattr(
        runtime_bundle.importlib.util,
        "find_spec",
        lambda name: None if name == "ontologylab.mcp_server" else real_find_spec(name),
    )
    # When preflight runs, then the missing product surface is refused.
    with pytest.raises(RuntimePreflightError, match="code=module_missing"):
        preflight(root)


def test_runtime_preflight_refuses_wrong_architecture(tmp_path: Path) -> None:
    # Given a correctly digested manifest claiming an unsupported architecture.
    root = _runtime_fixture(tmp_path)
    manifest = root / "runtime-manifest.json"
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    payload["architecture"] = "x86_64"
    raw = (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode()
    manifest.write_bytes(raw)
    (root / "runtime-manifest.sha256").write_text(
        hashlib.sha256(raw).hexdigest() + "\n", encoding="ascii"
    )
    # When preflight runs, then schema parsing refuses the wrong architecture.
    with pytest.raises(RuntimePreflightError, match="code=manifest_malformed"):
        preflight(root)
