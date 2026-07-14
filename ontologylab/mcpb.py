"""W10 pack distribution: bundle one knowledge pack as a single .mcpb file.

An ``.mcpb`` (MCP Bundle) is a zip archive with a ``manifest.json`` that MCP
hosts (Claude Desktop / Claude Code) can install by drag-and-drop. This
module bundles an already-built, immutable pack directory together with a
tiny launcher shim:

    <pack_id>.mcpb
      manifest.json            MCPB manifest (server config, metadata)
      server/main.py           shim -> python -m ontologylab.mcp_server
      packs/<pack_id>/...      the pack, byte-for-byte (sqlite/manifest/
                               schema/provenance)

The bundle carries DATA plus a launch config — not a Python runtime. The
host machine needs ``pip install 'ontologylab[mcp]'``; the shim fails with a
clear message otherwise. The pack inside stays verified-only and immutable:
bundling copies bytes, it never rewrites them (the pack's own
``content_hash`` still matches its ``pack.sqlite``).
"""

from __future__ import annotations

import json
import zipfile
from pathlib import Path
from typing import Any

from ontologylab import __version__
from ontologylab.packbuilder import PackBuildError

MCPB_MANIFEST_VERSION = "0.2"

_SERVER_SHIM = '''"""Launcher shim for a bundled ontologylab knowledge pack.

Requires the ontologylab package on the host:  pip install 'ontologylab[mcp]'
"""
import sys

try:
    from ontologylab.mcp_server import main
except ImportError:
    sys.stderr.write(
        "ontologylab is not installed in this Python environment; "
        "run: pip install 'ontologylab[mcp]'\\n"
    )
    raise SystemExit(2)

main()
'''


def _load_pack_manifest(pack_dir: Path) -> dict[str, Any]:
    manifest_path = pack_dir / "manifest.json"
    if not manifest_path.is_file() or not (pack_dir / "pack.sqlite").is_file():
        raise PackBuildError(f"not a pack directory: {pack_dir}")
    return json.loads(manifest_path.read_text(encoding="utf-8"))


def build_mcpb_manifest(pack_manifest: dict[str, Any]) -> dict[str, Any]:
    """The MCPB manifest for one pack (pure function; easy to test)."""
    pack_id = pack_manifest["pack_id"]
    counts = pack_manifest.get("counts") or {}
    tier = pack_manifest.get("search_tier", "fts5")
    return {
        "manifest_version": MCPB_MANIFEST_VERSION,
        "name": pack_id,
        "display_name": f"ontologylab knowledge pack: {pack_id}",
        "version": __version__,
        "description": (
            "Verified-only knowledge pack "
            f"({counts.get('nodes_verified', 0)} nodes / "
            f"{counts.get('edges_verified', 0)} edges, search tier {tier}). "
            "Read-only MCP tools: entity lookup, search, graph query, "
            "traversal, path finding. Every fact was human-approved and "
            "carries source-span provenance."
        ),
        "author": {"name": "ontologylab"},
        "server": {
            "type": "python",
            "entry_point": "server/main.py",
            "mcp_config": {
                "command": "python",
                "args": [
                    "${__dirname}/server/main.py",
                    "--packs-dir",
                    "${__dirname}/packs",
                    "--pack",
                    pack_id,
                ],
            },
        },
        "compatibility": {"runtimes": {"python": ">=3.11"}},
        "keywords": ["knowledge-graph", "ontologylab", "knowledge-pack"],
        # Extension field (hosts ignore unknown keys): the wrapped pack's own
        # manifest, so a bundle is self-describing without unzipping sqlite.
        "x_pack_manifest": pack_manifest,
    }


def build_mcpb(
    packs_dir: str | Path,
    pack_id: str,
    *,
    out_path: str | Path | None = None,
) -> Path:
    """Bundle ``packs_dir/pack_id`` into a single ``.mcpb`` zip.

    Returns the bundle path (default: ``packs_dir/<pack_id>.mcpb``).
    Rebuilding overwrites the previous bundle for the same pack_id — safe
    because the pack inside is immutable, so the bytes only differ if the
    ontologylab version (and thus the manifest) changed.
    """
    packs_dir = Path(packs_dir)
    pack_dir = packs_dir / pack_id
    pack_manifest = _load_pack_manifest(pack_dir)
    if pack_manifest.get("pack_id") != pack_id:
        raise PackBuildError(
            f"pack manifest id {pack_manifest.get('pack_id')!r} does not "
            f"match directory {pack_id!r}"
        )

    bundle_path = Path(out_path) if out_path else packs_dir / f"{pack_id}.mcpb"
    bundle_path.parent.mkdir(parents=True, exist_ok=True)

    mcpb_manifest = build_mcpb_manifest(pack_manifest)
    with zipfile.ZipFile(bundle_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("manifest.json", json.dumps(mcpb_manifest, indent=2))
        zf.writestr("server/main.py", _SERVER_SHIM)
        for file_path in sorted(pack_dir.rglob("*")):
            if file_path.is_file():
                arcname = f"packs/{pack_id}/{file_path.relative_to(pack_dir)}"
                zf.write(file_path, arcname)
    return bundle_path


__all__ = ["build_mcpb", "build_mcpb_manifest", "MCPB_MANIFEST_VERSION"]
