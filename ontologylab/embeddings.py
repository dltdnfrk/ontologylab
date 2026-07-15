"""Tier-2 embedding layer: local, in-process, no API keys (ARCHITECTURE §5.4).

Provides the ``Embedder`` protocol plus two implementations:

- ``HashingEmbedder`` — deterministic char-n-gram feature hashing into a
  fixed-dim L2-normalized vector. Stdlib-only and fully offline, so tests,
  CI, and machines without a model download still exercise the entire
  vector path (storage, cosine, RRF fusion). **Honesty note: this is a
  lexical-overlap proxy, not a semantic model** — it captures surface
  similarity ("RateLimiter" ~ "rate limiting"), never meaning. The
  embedding_model column/manifest records ``hash-v1`` so a pack built with
  it is never mistaken for one built with a real model.
- ``SentenceTransformerEmbedder`` — small CPU semantic model (default
  all-MiniLM-L6-v2, ~46MB) via the optional ``sentence-transformers``
  dependency. Requires a one-time model download; lazily imported so the
  core package stays stdlib-only.

Vectors are stored as packed float32 BLOBs on ``nodes.embedding`` with the
producing model recorded in ``nodes.embedding_model`` — a pack built with
model A is never compared against a query embedded with model B.
"""

from __future__ import annotations

import hashlib
import math
import struct
from typing import Iterable, Protocol, runtime_checkable


@runtime_checkable
class Embedder(Protocol):
    """A local text-embedding backend."""

    def name(self) -> str:
        """Stable identifier recorded in embedding_model / the manifest."""
        ...

    @property
    def dim(self) -> int:
        ...

    def embed(self, texts: list[str]) -> list[list[float]]:
        """Embed a batch of texts into L2-normalized vectors."""
        ...


# ---------------------------------------------------------------------------
# BLOB packing (float32, little-endian)
# ---------------------------------------------------------------------------


def pack_vector(vec: Iterable[float]) -> bytes:
    values = list(vec)
    return struct.pack(f"<{len(values)}f", *values)


def unpack_vector(blob: bytes) -> list[float]:
    count = len(blob) // 4
    return list(struct.unpack(f"<{count}f", blob))


# ---------------------------------------------------------------------------
# Optional sqlite-vec acceleration (opt-in; graceful degradation)
# ---------------------------------------------------------------------------
#
# sqlite-vec's serialize_float32 emits the SAME little-endian float32 bytes as
# pack_vector above, so the ``embedding`` BLOB already stored on nodes drops
# straight into a vec0 table with no re-encoding. The extension only ever
# ACCELERATES the identical cosine ranking (KNN prefilter) — every result is
# rescored exactly, and any failure falls back to brute force — so a machine
# without the extension gets the same answers, just slower.


def load_sqlite_vec(conn) -> bool:
    """Best-effort load of the sqlite-vec extension onto ``conn``.

    Returns True only when the ``sqlite_vec`` package is installed AND this
    Python's sqlite3 permits loadable extensions AND the load succeeds. Any
    failure returns False (never raises) — the caller then uses brute force.
    """
    try:
        import sqlite_vec
    except ImportError:
        return False
    try:
        conn.enable_load_extension(True)
        sqlite_vec.load(conn)
        conn.enable_load_extension(False)
        return True
    except Exception:
        return False


def cosine(a: list[float], b: list[float]) -> float:
    """Cosine similarity; assumes same dim, tolerates zero vectors."""
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)


# ---------------------------------------------------------------------------
# Offline deterministic embedder (test/dev tier)
# ---------------------------------------------------------------------------


class HashingEmbedder:
    """Char-n-gram feature hashing. Deterministic, offline, NOT semantic."""

    def __init__(self, dim: int = 256, ngram: int = 3) -> None:
        self._dim = dim
        self._ngram = ngram

    def name(self) -> str:
        return "hash-v1"

    @property
    def dim(self) -> int:
        return self._dim

    def _features(self, text: str) -> list[str]:
        normalized = " ".join(text.casefold().split())
        padded = f" {normalized} "
        grams = [
            padded[i : i + self._ngram]
            for i in range(max(1, len(padded) - self._ngram + 1))
        ]
        return grams + normalized.split()  # ngrams + whole words

    def embed(self, texts: list[str]) -> list[list[float]]:
        out: list[list[float]] = []
        for text in texts:
            vec = [0.0] * self._dim
            for feature in self._features(text):
                digest = hashlib.md5(feature.encode("utf-8")).digest()
                bucket = int.from_bytes(digest[:4], "little") % self._dim
                sign = 1.0 if digest[4] % 2 == 0 else -1.0
                vec[bucket] += sign
            norm = math.sqrt(sum(x * x for x in vec))
            if norm > 0:
                vec = [x / norm for x in vec]
            out.append(vec)
        return out


# ---------------------------------------------------------------------------
# Real local semantic model (optional dependency)
# ---------------------------------------------------------------------------


class SentenceTransformerEmbedder:
    """CPU sentence-transformers model, loaded once per process.

    Requires `pip install 'ontologylab[embed]'` and a one-time model
    download (network). Default model: all-MiniLM-L6-v2 (23M params).
    """

    def __init__(self, model_name: str = "sentence-transformers/all-MiniLM-L6-v2") -> None:
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as exc:  # pragma: no cover - optional dep
            raise RuntimeError(
                "sentence-transformers is not installed; "
                "pip install 'ontologylab[embed]'"
            ) from exc
        self._model_name = model_name
        self._model = SentenceTransformer(model_name)
        self._dim = int(self._model.get_sentence_embedding_dimension())

    def name(self) -> str:
        return self._model_name

    @property
    def dim(self) -> int:
        return self._dim

    def embed(self, texts: list[str]) -> list[list[float]]:  # pragma: no cover
        vectors = self._model.encode(texts, normalize_embeddings=True)
        return [list(map(float, v)) for v in vectors]


def get_embedder(name: str | None) -> Embedder | None:
    """Factory: None | 'hash' | a sentence-transformers model name."""
    if not name or name == "none":
        return None
    if name in ("hash", "hash-v1"):
        return HashingEmbedder()
    return SentenceTransformerEmbedder(name)


# ---------------------------------------------------------------------------
# Reciprocal Rank Fusion
# ---------------------------------------------------------------------------

RRF_K = 60


def rrf_fuse(
    ranked_lists: list[list[str]], k: int = RRF_K
) -> list[tuple[str, float]]:
    """Fuse ranked id lists via RRF; returns (id, fused_score) best-first.

    fused_score is normalized rank-preservingly to 0..1 by dividing by the
    theoretical maximum (appearing first in every list) — consistent with
    the §5.4 match_score contract (higher is better, not a calibrated
    probability).
    """
    scores: dict[str, float] = {}
    for ranked in ranked_lists:
        for rank, item_id in enumerate(ranked):
            scores[item_id] = scores.get(item_id, 0.0) + 1.0 / (k + rank + 1)
    if not scores:
        return []
    max_possible = len(ranked_lists) / (k + 1)
    fused = [(item_id, score / max_possible) for item_id, score in scores.items()]
    fused.sort(key=lambda pair: (-pair[1], pair[0]))
    return fused
