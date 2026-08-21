"""Pure preferred-representation-v1 projection (Wave 2.1 D07).

Deterministic ranking, never stored: provider-asserted stage, then kind,
then canonical evidence-grade order, then source tier, then UTF-8 byte
length, then lexical content hash. The same candidate set ranks identically
under any ingest order; a policy change affects only future explicit
selection.
"""

from __future__ import annotations

from typing import Any, Mapping

_STAGE_RANK = {"published": 0, "accepted": 1, "submitted": 2, "unknown": 3}
_KIND_RANK = {"fulltext": 0, "abstract": 1, "excerpt": 2, "metadata_only": 3}
_GRADE_RANK = {"A": 0, "B": 1, "C": 2, "D": 3}
_SOURCE_RANK = {
    "publisher": 0,
    "pmc": 0,
    "registry": 1,
    "aggregator": 2,
    "web": 3,
    "upload": 3,
    "sample": 3,
    "": 4,
}


def _rank(candidate: Mapping[str, Any]) -> tuple:
    return (
        _STAGE_RANK.get(str(candidate.get("stage") or "unknown"), 3),
        _KIND_RANK.get(str(candidate.get("kind") or "metadata_only"), 3),
        _GRADE_RANK.get(str(candidate.get("evidence_grade") or "D"), 3),
        _SOURCE_RANK.get(str(candidate.get("source") or ""), 4),
        int(candidate.get("byte_length") or 0) * -1,  # longer body first
        str(candidate.get("content_hash") or ""),
        str(candidate.get("doc_id") or ""),
    )


def preferred_representation(
    candidates: list[Mapping[str, Any]],
) -> Mapping[str, Any]:
    """The single preferred Representation for a Work's candidates.

    Deterministic: the result is a pure function of the candidates, not of
    their arrival order.
    """
    if not candidates:
        raise ValueError("preferred_representation needs at least one candidate")
    return min(candidates, key=_rank)
