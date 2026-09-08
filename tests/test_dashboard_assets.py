"""Task-2 relocation pin for the dashboard HTTP surface.

Before the dashboard assets moved from the repository ``web/`` directory
into the ``ontologylab.web`` package resources, their served bytes and
status codes were captured here. The move must not change what the browser
receives: every assertion below passed against the pre-move checkout server
and must keep passing against the manifest-verified package resources.

The authority tests at the bottom lock the new behavior: a committed
manifest (path + size + SHA-256) that must match the shipped tree exactly,
and a server that refuses to start when the installed tree is incomplete,
tampered, or has unlisted additions.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from ontologylab import web_assets
from ontologylab.server.app import create_app

# Current shipped-copy contract: served path, byte length, and SHA-256.
# /static/index.html is intentionally retained as a directly served asset.
_PINNED_ASSETS: tuple[tuple[str, int, str], ...] = (
    ("index.html", 58433, "37c4d7ff5fd1d311bc24db8651868ed2f559d51a3b8c834e917bfa7623257efa"),
    ("app.js", 268972, "1c9e4d42d4cb5a96bc105adffd290e80e3d6bd6a4933bb311d4dc88f16d6cee0"),
    ("chat-session.js", 4721, "45e80c4cc2a6f0cc311a910f2f731b6da9672bd436dc9f748b215f9c69b1e84f"),
    ("favicon.svg", 308, "4b123cf3e11827ffdf2e0a91d4b76acc37f707d764b429c09f70055ee7ae29f8"),
    ("localize.js", 6991, "544056dbaad1d1e605752d89db00d6b90f8be62f50b3fa13ba1a983802fcbff7"),
    ("research-summary.js", 4095, "29d69924c39e0dace71b25c00780b84bd6dc6fa70d011557753b2231acb524ab"),
    ("ui-utils.js", 5479, "e92a2aa7e33a05f55905486863a1a530d171cfa220782d832870855c03402c12"),
    ("style.css", 105131, "f7e93f9670ab54af82ab5938c27cffae1bb585c3757f3c07c13a520dd69bb76b"),
    ("fonts/PretendardVariable.woff2", 2057688, "9599f12fd42fc0bce1cd50b47a0c022e108d7aa64dd0d1bb0ed44f3282d900b4"),
)

# nosniff-safe families, not exact strings: StaticFiles took the MIME table
# from the OS, the packaged handler pins its own — both must stay browser-
# executable. A charset suffix is stripped before comparing.
_JS_TYPES = {"text/javascript", "application/javascript"}
_FONT_TYPES = {"font/woff2", "application/font-woff2", "application/octet-stream"}


def _expected_types(path: str) -> set[str]:
    if path.endswith(".js"):
        return _JS_TYPES
    if path.endswith(".css"):
        return {"text/css"}
    if path.endswith(".html"):
        return {"text/html"}
    if path.endswith(".svg"):
        return {"image/svg+xml"}
    return _FONT_TYPES


def _bare_type(response) -> str:  # type: ignore[no-untyped-def]
    return (response.headers.get("content-type") or "").split(";", 1)[0].strip().lower()


@pytest.fixture(scope="module")
def client(tmp_path_factory: pytest.TempPathFactory) -> TestClient:
    data_dir = tmp_path_factory.mktemp("data")
    return TestClient(create_app(data_dir=data_dir))


# --------------------------------------------------------------------------
# PIN: the pre-move HTTP surface, byte for byte
# --------------------------------------------------------------------------


def test_index_serves_pinned_html(client: TestClient) -> None:
    # Given the pinned index.html bytes
    _, size, sha256 = _PINNED_ASSETS[0]
    # When the document root is requested
    response = client.get("/")
    # Then the exact pinned document is served as HTML
    assert response.status_code == 200
    assert _bare_type(response) == "text/html"
    assert len(response.content) == size
    assert hashlib.sha256(response.content).hexdigest() == sha256


@pytest.mark.parametrize(("path", "size", "sha256"), _PINNED_ASSETS)
def test_every_pinned_asset_is_served(
    client: TestClient, path: str, size: int, sha256: str
) -> None:
    # Given a pinned asset URL
    # When it is requested
    response = client.get(f"/static/{path}")
    # Then status, byte length, body hash, and MIME family are preserved
    assert response.status_code == 200, path
    assert len(response.content) == size, path
    assert hashlib.sha256(response.content).hexdigest() == sha256, path
    assert _bare_type(response) in _expected_types(path), (
        path,
        response.headers.get("content-type"),
    )


def test_static_index_html_matches_document_root(client: TestClient) -> None:
    # Given the intentionally retained /static/index.html URL
    # When both URLs are requested
    # Then they serve the same bytes, as before the move
    assert client.get("/static/index.html").content == client.get("/").content


def test_healthz_ok(client: TestClient) -> None:
    # Given the running app, /healthz keeps answering 200 {"ok": true}
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"ok": True}


def test_unknown_asset_is_404(client: TestClient) -> None:
    # Given a path outside the shipped set, the answer stays 404
    assert client.get("/static/nope.js").status_code == 404


def test_traversal_is_not_served(client: TestClient) -> None:
    # Given an encoded dot-segment, no file outside the asset set is served
    assert client.get("/static/%2e%2e/app.js").status_code == 404


# --------------------------------------------------------------------------
# Authority: manifest verification of the packaged resource tree
# --------------------------------------------------------------------------


def _write_tree(root: Path, files: dict[str, bytes]) -> None:
    for rel, body in files.items():
        target = root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(body)


def _manifest_for(files: dict[str, bytes]) -> bytes:
    entries = [
        {
            "path": rel,
            "size": len(body),
            "sha256": hashlib.sha256(body).hexdigest(),
        }
        for rel, body in sorted(files.items())
    ]
    return (json.dumps({"version": 1, "assets": entries}) + "\n").encode()


def test_committed_manifest_matches_shipped_tree() -> None:
    # Given the committed manifest.json in the package
    # When the live tree is hashed from scratch
    # Then the two agree exactly (drift here means the manifest is stale)
    live = web_assets.compute_manifest(web_assets.resource_root())
    committed = web_assets.manifest_entries(web_assets.resource_root())
    assert live == committed


def test_verify_assets_accepts_the_shipped_tree() -> None:
    # Given the shipped package, verification passes and lists every asset
    verified = web_assets.verify_assets()
    paths = {entry.path for entry in verified.entries}
    assert paths == {path for path, _, _ in _PINNED_ASSETS}
    for path, size, sha256 in _PINNED_ASSETS:
        assert len(verified.content[path]) == size
        assert hashlib.sha256(verified.content[path]).hexdigest() == sha256


def test_verify_tree_refuses_a_missing_asset(tmp_path: Path) -> None:
    # Given a tree whose manifest names one more file than it contains
    files = {"app.js": b"js", "style.css": b"css"}
    _write_tree(tmp_path, {**files, "manifest.json": _manifest_for({**files, "gone.js": b"x"})})
    # When verified, the missing file is named and nothing is returned
    with pytest.raises(web_assets.AssetVerificationError, match="gone.js"):
        web_assets.verify_tree(tmp_path)


def test_verify_tree_refuses_a_tampered_asset(tmp_path: Path) -> None:
    # Given a tree whose bytes no longer match the manifest hash
    files = {"app.js": b"tampered"}
    _write_tree(tmp_path, {**files, "manifest.json": _manifest_for({"app.js": b"original"})})
    # When verified, the mismatch fails before anything can be served
    with pytest.raises(web_assets.AssetVerificationError, match="app.js"):
        web_assets.verify_tree(tmp_path)


def test_verify_tree_refuses_an_unlisted_addition(tmp_path: Path) -> None:
    # Given a tree carrying a second, unlisted copy of an asset
    files = {"app.js": b"js", "fallback/app.js": b"old js"}
    _write_tree(tmp_path, {**files, "manifest.json": _manifest_for({"app.js": b"js"})})
    # When verified, the duplicate authority fails the tree
    with pytest.raises(web_assets.AssetVerificationError, match="unlisted"):
        web_assets.verify_tree(tmp_path)


def test_verify_tree_refuses_a_malformed_manifest(tmp_path: Path) -> None:
    # Given a manifest that is not JSON at all
    _write_tree(tmp_path, {"app.js": b"js", "manifest.json": b"{not json"})
    # When verified, the failure is typed, not a raw JSONDecodeError
    with pytest.raises(web_assets.AssetVerificationError, match="manifest"):
        web_assets.verify_tree(tmp_path)


def test_verify_tree_refuses_a_missing_manifest(tmp_path: Path) -> None:
    # Given a tree with assets but no manifest
    _write_tree(tmp_path, {"app.js": b"js"})
    # When verified, the missing manifest fails the tree
    with pytest.raises(web_assets.AssetVerificationError, match="manifest"):
        web_assets.verify_tree(tmp_path)


def test_verify_tree_refuses_a_traversal_manifest_path(tmp_path: Path) -> None:
    # Given a manifest entry that tries to name a file outside the tree
    entries = [{"path": "../escape.js", "size": 2, "sha256": "0" * 64}]
    manifest = (json.dumps({"version": 1, "assets": entries}) + "\n").encode()
    _write_tree(tmp_path, {"app.js": b"js", "manifest.json": manifest})
    # When verified, the unsafe path is rejected
    with pytest.raises(web_assets.AssetVerificationError, match="escape"):
        web_assets.verify_tree(tmp_path)


def test_create_app_refuses_a_tampered_tree(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Given verification that fails (as it would on a tampered install)
    def _broken() -> web_assets.VerifiedAssets:
        raise web_assets.AssetVerificationError(("missing asset: app.js",))

    monkeypatch.setattr("ontologylab.server.app.verify_assets", _broken)
    # When the app is constructed, startup fails before any route can serve
    with pytest.raises(web_assets.AssetVerificationError, match="app.js"):
        create_app(data_dir=tmp_path / "data")


def test_runtime_has_no_checkout_web_fallback() -> None:
    # Given the server module source
    source = Path(web_assets.__file__).parent.joinpath(
        "server", "app.py"
    ).read_text(encoding="utf-8")
    # Then no checkout-relative asset resolution remains
    assert "WEB_DIR" not in source
    assert 'ROOT / "web"' not in source
    assert "StaticFiles" not in source


def test_packaged_javascript_passes_node_check() -> None:
    # Given the shipped JS modules, each one parses under node --check
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed")
    root = web_assets.resource_root()
    for path in web_assets.asset_paths():
        if not path.endswith(".js"):
            continue
        target = root.joinpath(*path.split("/"))
        with web_assets.as_local_file(target) as local:
            proc = subprocess.run(
                [node, "--check", str(local)],
                capture_output=True,
                text=True,
                check=False,
            )
        assert proc.returncode == 0, f"{path}: {proc.stderr}"
