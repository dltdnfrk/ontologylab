"""P2 — cross-encoder reranking over the RRF shortlist.

RRF is first-stage fusion: it merges ranked lists without ever reading the
query against a candidate. The literature is consistent that a second-stage
cross-encoder — which scores (query, candidate) *jointly* — is worth up to
~10 nDCG points over first-stage-only retrieval, so the hybrid search takes
an optional reranker and re-orders its fused shortlist with one.

Two rules keep this inside the repository's posture:

- **``auto`` never touches the network.** Loading a HuggingFace model can
  silently download ~90 MB, and a query path that phones home would bypass
  the deny-by-default egress allowlist entirely. ``auto`` therefore loads
  with ``HF_HUB_OFFLINE=1``: a locally cached model is used, an uncached
  one falls back to ``None`` (RRF order stands). Downloading is an explicit
  act: ``get_reranker(model, allow_download=True)``, wired to the CLI, not
  to any server or MCP query path.

- **Degradation is silent and safe.** No reranker → results are exactly
  the fused RRF order, which is what shipped before this module existed.

Default model: ``cross-encoder/ms-marco-MiniLM-L-6-v2`` — small enough for
CPU, the standard baseline reranker in the retrieval literature.
"""

from __future__ import annotations

import math
import os
from typing import Optional, Protocol

DEFAULT_RERANK_MODEL = "cross-encoder/ms-marco-MiniLM-L-6-v2"


class Reranker(Protocol):  # pragma: no cover — typing only
    def name(self) -> str: ...
    def score(self, query: str, texts: list[str]) -> list[float]: ...


def sigmoid(x: float) -> float:
    """Squash a cross-encoder logit into the 0..1 ``match_score`` contract."""
    if x >= 0:
        z = math.exp(-x)
        return 1.0 / (1.0 + z)
    z = math.exp(x)
    return z / (1.0 + z)


class CrossEncoderReranker:
    """CPU cross-encoder, loaded once per process."""

    def __init__(
        self,
        model_name: str = DEFAULT_RERANK_MODEL,
        *,
        allow_download: bool = False,
    ) -> None:
        try:
            from sentence_transformers import CrossEncoder
        except ImportError as exc:  # pragma: no cover — optional dep
            raise RuntimeError(
                "sentence-transformers is not installed; "
                "pip install 'ontologylab[embed]'"
            ) from exc
        self._model_name = model_name
        if allow_download:
            self._model = CrossEncoder(model_name)
        else:
            # Cached-only: HF_HUB_OFFLINE makes an uncached model an
            # exception instead of an unsanctioned download.
            prior = os.environ.get("HF_HUB_OFFLINE")
            os.environ["HF_HUB_OFFLINE"] = "1"
            try:
                self._model = CrossEncoder(model_name)
            finally:
                if prior is None:
                    os.environ.pop("HF_HUB_OFFLINE", None)
                else:
                    os.environ["HF_HUB_OFFLINE"] = prior

    def name(self) -> str:
        return self._model_name

    def score(self, query: str, texts: list[str]) -> list[float]:  # pragma: no cover
        if not texts:
            return []
        raw = self._model.predict([(query, text) for text in texts])
        return [float(value) for value in raw]


def get_reranker(
    name: str | None, *, allow_download: bool = False
) -> Optional[Reranker]:
    """Factory: None | 'none' | 'auto' | a cross-encoder model name.

    ``auto`` returns the default model when it is installed *and already
    cached*, else ``None`` — never an error, never a download. An explicit
    model name raises on failure: a caller who asked by name wants to hear
    why it did not happen.
    """
    if not name or name == "none":
        return None
    if name == "auto":
        try:
            return CrossEncoderReranker(DEFAULT_RERANK_MODEL)
        except Exception:
            return None
    return CrossEncoderReranker(name, allow_download=allow_download)


__all__ = [
    "DEFAULT_RERANK_MODEL",
    "CrossEncoderReranker",
    "Reranker",
    "get_reranker",
    "sigmoid",
]
