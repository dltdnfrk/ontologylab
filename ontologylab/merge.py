"""W7 fuzzy duplicate detection for the entity-merge review queue.

``scan_merge_candidates`` proposes same-entity-type node PAIRS that look
like the same real-world entity under one of four signals:

- **name similarity** — difflib ratio over normalized names (exact matches
  can't occur: entity resolution already dedups them at insert time);
- **containment** — one normalized name contained in the other;
- **shared alias** — the two nodes share a normalized alias key;
- **embedding cosine** — both nodes carry embeddings from the SAME model
  and their cosine similarity clears a high threshold.

The scanner only *proposes*: every pair lands in ``merge_candidates`` for a
human to merge or dismiss (dismissed pairs are never re-proposed). Nothing
here mutates the graph.
"""

from __future__ import annotations

from difflib import SequenceMatcher
from typing import Any

from ontologylab.embeddings import cosine, unpack_vector
from ontologylab.kgstore import KGStore

# Signal thresholds. Conservative on purpose: a false merge candidate costs
# one human glance; a merge itself is always a human decision anyway.
NAME_SIMILARITY_THRESHOLD = 0.82
CONTAINMENT_MIN_LEN = 4
CONTAINMENT_SCORE = 0.85
SHARED_ALIAS_SCORE = 0.95
EMBEDDING_COSINE_THRESHOLD = 0.90


def _pair_signals(
    node_a: dict[str, Any],
    node_b: dict[str, Any],
    *,
    name_threshold: float,
    cosine_threshold: float,
) -> tuple[float, list[str]]:
    """Score one pair; returns (score, reasons). Empty reasons = no candidate."""
    score = 0.0
    reasons: list[str] = []

    key_a, key_b = node_a["normalized_name"], node_b["normalized_name"]
    ratio = SequenceMatcher(None, key_a, key_b).ratio()
    if ratio >= name_threshold:
        score = max(score, ratio)
        reasons.append(f"name-similarity:{ratio:.2f}")

    shorter, longer = sorted((key_a, key_b), key=len)
    if len(shorter) >= CONTAINMENT_MIN_LEN and shorter != longer and shorter in longer:
        score = max(score, CONTAINMENT_SCORE)
        reasons.append(f"name-containment:{shorter}")

    shared = node_a["alias_keys"] & node_b["alias_keys"]
    if shared:
        score = max(score, SHARED_ALIAS_SCORE)
        reasons.append(f"shared-alias:{sorted(shared)[0]}")

    vec_a, vec_b = node_a["embedding"], node_b["embedding"]
    if (
        vec_a is not None
        and vec_b is not None
        and node_a["embedding_model"] == node_b["embedding_model"]
    ):
        sim = cosine(vec_a, vec_b)
        if sim >= cosine_threshold:
            score = max(score, sim)
            reasons.append(f"embedding-cosine:{sim:.2f}")

    return score, reasons


def scan_merge_candidates(
    store: KGStore,
    *,
    name_threshold: float = NAME_SIMILARITY_THRESHOLD,
    cosine_threshold: float = EMBEDDING_COSINE_THRESHOLD,
) -> dict[str, Any]:
    """Scan proposed+verified nodes for duplicate pairs; record candidates.

    O(n²) within each entity type — fine at local single-user scale. Returns
    scan stats; the candidates themselves are read back via
    ``store.merge_candidates_pending()``.
    """
    rows = store.conn.execute(
        "SELECT id, entity_type, name, normalized_name, aliases_json, "
        "embedding, embedding_model FROM nodes "
        "WHERE status IN ('proposed','verified') ORDER BY entity_type, created_ts"
    ).fetchall()

    alias_map: dict[str, set[str]] = {}
    for arow in store.conn.execute(
        "SELECT node_id, normalized_alias FROM node_aliases"
    ):
        alias_map.setdefault(arow["node_id"], set()).add(arow["normalized_alias"])

    by_type: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        by_type.setdefault(row["entity_type"], []).append(
            {
                "id": row["id"],
                "normalized_name": row["normalized_name"],
                "alias_keys": alias_map.get(row["id"], set()),
                "embedding": (
                    unpack_vector(row["embedding"])
                    if row["embedding"] is not None
                    else None
                ),
                "embedding_model": row["embedding_model"],
            }
        )

    stats = {"nodes": len(rows), "pairs_checked": 0, "candidates_new": 0,
             "candidates_existing": 0}
    for group in by_type.values():
        for i in range(len(group)):
            for j in range(i + 1, len(group)):
                stats["pairs_checked"] += 1
                score, reasons = _pair_signals(
                    group[i],
                    group[j],
                    name_threshold=name_threshold,
                    cosine_threshold=cosine_threshold,
                )
                if not reasons:
                    continue
                created = store.record_merge_candidate(
                    group[i]["id"], group[j]["id"], score=score, reasons=reasons
                )
                stats["candidates_new" if created else "candidates_existing"] += 1
    return stats


__all__ = ["scan_merge_candidates"]
