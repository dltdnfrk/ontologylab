"""W14 pack diff: what changed between two immutable knowledge packs.

Packs are additive and immutable — a rebuild mints a new pack_id instead of
mutating anything — so "what changed since the pack my client is pinned to?"
is answered by comparing two pack directories. Node/edge identity is the
row id (rebuilds from the same working DB keep ids stable; entity
resolution reuses them), so the diff distinguishes *added*, *removed*, and
*changed* (same id, different content) rather than guessing by name.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ontologylab.kgstore import KGStore
from ontologylab.packbuilder import (
    PackBuildError,
    pack_sqlite_path,
    safe_pack_component,
)

# Manifest fields worth surfacing when they differ between two packs.
_MANIFEST_FIELDS = (
    "schema_label",
    "search_tier",
    "embedding_model",
    "ontologylab_version",
)

# Content fields that make a same-id row count as "changed".
_NODE_FIELDS = ("name", "entity_type", "aliases", "properties", "confidence")
_EDGE_FIELDS = (
    "relation_type",
    "source_id",
    "target_id",
    "properties",
    "confidence",
)


def _load_manifest(packs_dir: Path, pack_id: str) -> dict[str, Any]:
    safe_pack_component(pack_id, kind="pack id")
    manifest_path = packs_dir / pack_id / "manifest.json"
    if not manifest_path.is_file():
        raise PackBuildError(f"pack {pack_id!r} has no manifest under {packs_dir}")
    return json.loads(manifest_path.read_text(encoding="utf-8"))


def _snapshot(packs_dir: Path, pack_id: str) -> tuple[dict, dict]:
    """(nodes_by_id, edges_by_id) of one pack, as comparable dicts."""
    store = KGStore.open(pack_sqlite_path(packs_dir, pack_id), read_only=True)
    try:
        nodes, edges = store.verified_subgraph()
    finally:
        store.close()
    return (
        {n["id"]: n for n in nodes},
        {e["id"]: e for e in edges},
    )


def _canonical(value: Any) -> str:
    """Order-insensitive comparison key for lists/dicts."""
    if isinstance(value, list):
        value = sorted(map(str, value))
    return json.dumps(value, sort_keys=True, default=str)


def _diff_items(
    a_items: dict[str, dict],
    b_items: dict[str, dict],
    fields: tuple[str, ...],
    label_key: str,
) -> dict[str, list[dict[str, Any]]]:
    added = [
        {"id": item_id, "label": b_items[item_id].get(label_key)}
        for item_id in sorted(set(b_items) - set(a_items))
    ]
    removed = [
        {"id": item_id, "label": a_items[item_id].get(label_key)}
        for item_id in sorted(set(a_items) - set(b_items))
    ]
    changed = []
    for item_id in sorted(set(a_items) & set(b_items)):
        fields_changed = [
            field
            for field in fields
            if _canonical(a_items[item_id].get(field))
            != _canonical(b_items[item_id].get(field))
        ]
        if fields_changed:
            changed.append(
                {
                    "id": item_id,
                    "label": b_items[item_id].get(label_key),
                    "fields": fields_changed,
                }
            )
    return {"added": added, "removed": removed, "changed": changed}


def diff_packs(
    packs_dir: str | Path, pack_a_id: str, pack_b_id: str
) -> dict[str, Any]:
    """Diff pack A -> pack B (manifests + verified node/edge sets)."""
    packs_dir = Path(packs_dir)
    manifest_a = _load_manifest(packs_dir, pack_a_id)
    manifest_b = _load_manifest(packs_dir, pack_b_id)

    manifest_changes: dict[str, dict[str, Any]] = {}
    for field in _MANIFEST_FIELDS:
        if manifest_a.get(field) != manifest_b.get(field):
            manifest_changes[field] = {
                "a": manifest_a.get(field),
                "b": manifest_b.get(field),
            }

    nodes_a, edges_a = _snapshot(packs_dir, pack_a_id)
    nodes_b, edges_b = _snapshot(packs_dir, pack_b_id)

    # Edge labels read better with endpoint names than raw ids.
    names = {n_id: n["name"] for n_id, n in {**nodes_a, **nodes_b}.items()}
    for edges in (edges_a, edges_b):
        for edge in edges.values():
            edge["triple"] = (
                f"{names.get(edge['source_id'], edge['source_id'])} "
                f"-[{edge['relation_type']}]-> "
                f"{names.get(edge['target_id'], edge['target_id'])}"
            )

    nodes_diff = _diff_items(nodes_a, nodes_b, _NODE_FIELDS, "name")
    edges_diff = _diff_items(edges_a, edges_b, _EDGE_FIELDS, "triple")
    return {
        "pack_a": {
            "pack_id": pack_a_id,
            "content_hash": manifest_a.get("content_hash"),
            "created_ts": manifest_a.get("created_ts"),
        },
        "pack_b": {
            "pack_id": pack_b_id,
            "content_hash": manifest_b.get("content_hash"),
            "created_ts": manifest_b.get("created_ts"),
        },
        "identical": (
            manifest_a.get("content_hash") == manifest_b.get("content_hash")
        ),
        "manifest_changes": manifest_changes,
        "nodes": nodes_diff,
        "edges": edges_diff,
        "summary": {
            "nodes_added": len(nodes_diff["added"]),
            "nodes_removed": len(nodes_diff["removed"]),
            "nodes_changed": len(nodes_diff["changed"]),
            "edges_added": len(edges_diff["added"]),
            "edges_removed": len(edges_diff["removed"]),
            "edges_changed": len(edges_diff["changed"]),
        },
    }


__all__ = ["diff_packs"]
