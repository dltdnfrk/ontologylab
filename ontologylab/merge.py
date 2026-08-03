"""W7 fuzzy duplicate detection for the entity-merge review queue.

``scan_merge_candidates`` proposes same-entity-type node PAIRS that look
like the same real-world entity under one of four signals:

- **name similarity** — difflib ratio over normalized names (exact matches
  can't occur: entity resolution already dedups them at insert time);
- **containment** — one normalized name contained in the other;
- **shared alias** — the two nodes share a normalized alias key;
- **embedding cosine** — both nodes carry embeddings from the SAME model
  and their cosine similarity clears a high threshold.

**Candidate pairs come from blocking, not from the full cross product.**
The original scan compared every pair within an entity type — O(n²) in the
expensive signals, which stops being "fine at local scale" around a few
thousand nodes. Pairs are now generated two ways and unioned:

- a **character-3-gram inverted index** over normalized names and alias
  keys: any pair similar enough for the lexical signals shares 3-grams, so
  it lands in at least one common block. Grams shared by too many nodes are
  skipped as blocking keys (they'd rebuild the cross product); a genuinely
  similar pair shares many grams, so it survives losing its hottest ones.
- **embedding nearest neighbours**: top-k cosine neighbours per node among
  same-model embeddings (NumPy accelerates this, with a stdlib fallback), so semantically
  close but lexically unrelated duplicates ("AMI" / "heart attack") are
  still found — the one recall case gram blocking cannot cover.

Blocking is standard ER practice precisely because the alternative is not
"perfect recall" but "a scan nobody runs": the cross product at 10k nodes
is 50M signal evaluations. The known loss is pathological pairs whose
similarity ≥ threshold but who share no 3-gram — constructible, not
observed in real entity names.

The scanner only *proposes*: every pair lands in ``merge_candidates`` for a
human to merge or dismiss (dismissed pairs are never re-proposed). Nothing
here mutates the graph.
"""

from __future__ import annotations

from difflib import SequenceMatcher
from itertools import combinations
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

# Blocking parameters. 3-grams rather than 4: the shortest pair the name
# signal can accept still shares a 3-gram. A gram block larger than
# MAX_GRAM_BLOCK is skipped as a key — at that frequency it is a stop-gram
# carrying no evidence of sameness. VECTOR_NEIGHBOURS bounds the embedding
# candidate list per node.
BLOCK_NGRAM = 3
MAX_GRAM_BLOCK = 64
VECTOR_NEIGHBOURS = 5


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


def _block_keys(node: dict[str, Any]) -> set[str]:
    """Blocking keys for one node: exact strings + character 3-grams.

    The exact ``a:`` keys are never frequency-capped, so the shared-alias
    signal keeps perfect candidate recall even when every gram of that
    alias is hot.
    """
    keys: set[str] = set()
    for text in {node["normalized_name"], *node["alias_keys"]}:
        if not text:
            continue
        keys.add(f"a:{text}")
        if len(text) >= BLOCK_NGRAM:
            keys.update(
                f"g:{text[i:i + BLOCK_NGRAM]}"
                for i in range(len(text) - BLOCK_NGRAM + 1)
            )
    return keys


def _blocked_pairs(group: list[dict[str, Any]]) -> set[tuple[int, int]]:
    """Candidate index pairs from the gram/exact inverted index."""
    blocks: dict[str, list[int]] = {}
    for index, node in enumerate(group):
        for key in _block_keys(node):
            blocks.setdefault(key, []).append(index)

    pairs: set[tuple[int, int]] = set()
    for key, members in blocks.items():
        if key.startswith("g:") and len(members) > MAX_GRAM_BLOCK:
            continue  # stop-gram: no evidence, near-quadratic cost
        for i, j in combinations(members, 2):
            pairs.add((i, j))
    return pairs


def _vector_pairs(group: list[dict[str, Any]]) -> set[tuple[int, int]]:
    """Top-k cosine neighbours per node, per embedding model.

    NumPy accelerates the all-neighbours ranking when sentence-transformers
    brings it along. The stdlib path preserves the same recall contract for
    core installs and hash/custom embeddings; optional acceleration must not
    decide whether an embedding-only duplicate is considered at all.
    """
    try:
        import numpy
    except ImportError:  # core install: preserve behaviour without acceleration
        numpy = None

    by_model: dict[str, list[int]] = {}
    for index, node in enumerate(group):
        if node["embedding"] is not None and node["embedding_model"]:
            by_model.setdefault(node["embedding_model"], []).append(index)

    pairs: set[tuple[int, int]] = set()
    for indices in by_model.values():
        if len(indices) < 2:
            continue
        if numpy is None:
            for a in indices:
                neighbours = sorted(
                    (b for b in indices if b != a),
                    key=lambda b: (
                        -cosine(group[a]["embedding"], group[b]["embedding"]), b
                    ),
                )[:VECTOR_NEIGHBOURS]
                for b in neighbours:
                    pairs.add((min(a, b), max(a, b)))
            continue
        matrix = numpy.array(
            [group[i]["embedding"] for i in indices], dtype=numpy.float32
        )
        norms = numpy.linalg.norm(matrix, axis=1, keepdims=True)
        norms[norms == 0.0] = 1.0
        unit = matrix / norms
        take = min(VECTOR_NEIGHBOURS + 1, len(indices))
        # Chunked so the similarity matrix never materializes at n×n for
        # large stores; 512×n float32 stays small.
        for start in range(0, len(indices), 512):
            sims = unit[start:start + 512] @ unit.T
            top = numpy.argsort(-sims, axis=1)[:, :take]
            for row, neighbours in enumerate(top):
                a = indices[start + row]
                for column in neighbours:
                    b = indices[int(column)]
                    if a != b:
                        pairs.add((min(a, b), max(a, b)))
    return pairs


def scan_merge_candidates(
    store: KGStore,
    *,
    name_threshold: float = NAME_SIMILARITY_THRESHOLD,
    cosine_threshold: float = EMBEDDING_COSINE_THRESHOLD,
) -> dict[str, Any]:
    """Scan proposed+verified nodes for duplicate pairs; record candidates.

    Candidate pairs come from blocking (see module docstring); the signal
    evaluation itself is unchanged. Returns scan stats — ``pairs_checked``
    is the number actually scored, ``pairs_possible`` the cross-product it
    replaced, so the reduction is visible rather than assumed. Candidates
    are read back via ``store.merge_candidates_pending()``.
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

    stats = {
        "nodes": len(rows),
        "pairs_possible": 0,
        "pairs_checked": 0,
        "candidates_new": 0,
        "candidates_existing": 0,
    }
    for group in by_type.values():
        stats["pairs_possible"] += len(group) * (len(group) - 1) // 2
        candidate_pairs = _blocked_pairs(group) | _vector_pairs(group)
        for i, j in sorted(candidate_pairs):
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
