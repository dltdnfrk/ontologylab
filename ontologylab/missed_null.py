"""Source-grounded sentences needing human review for measured-null claims."""

from __future__ import annotations

from dataclasses import dataclass
import json
import re
from typing import Iterable

from ontologylab.kgstore import KGStore
from ontologylab.models import Document


# The first five cues come from the extraction polarity guidance. The remaining
# literal patterns cover the published source's measured absence, zero control,
# and unchanged outcome language; they do not encode gold labels or entities.
_CUES = (
    ("no significant", re.compile(r"\bno significant\b", re.I)),
    ("not significantly", re.compile(r"\bnot significantly\b", re.I)),
    ("did not reduce", re.compile(r"\bdid not reduce\b", re.I)),
    ("ineffective", re.compile(r"\bineffective\b", re.I)),
    ("no difference", re.compile(r"\bno difference\b", re.I)),
    ("not statistically different", re.compile(r"\bnot statistically different\b", re.I)),
    ("did not significantly", re.compile(r"\bdid not significantly\b", re.I)),
    ("did not differ", re.compile(r"\bdid not differ\b", re.I)),
    ("no resistant isolate", re.compile(r"\bno resistant isolates?\b", re.I)),
    ("zero measured percent", re.compile(r"\b0\s*%", re.I)),
)
# A line break is a paragraph boundary in the retained full-body source. A
# period breaks only before an uppercase letter or digit, preserving D. suzukii,
# P. annua, decimals and "Fig. b" within the source sentence.
_SENTENCE_END = re.compile(r"\n+|[.!?](?=[ \t]+[A-Z0-9])")


@dataclass(frozen=True, slots=True)
class MissedNullCandidate:
    document_id: str
    start: int
    end: int
    text: str
    cue: str


def _sentences(text: str) -> Iterable[tuple[int, int, str]]:
    start = 0
    for boundary in _SENTENCE_END.finditer(text):
        end = boundary.end()
        piece = text[start:end]
        left = len(piece) - len(piece.lstrip())
        right = len(piece.rstrip())
        if left < right:
            yield start + left, start + right, piece[left:right]
        start = end
    piece = text[start:]
    left = len(piece) - len(piece.lstrip())
    right = len(piece.rstrip())
    if left < right:
        yield start + left, start + right, piece[left:right]


def missed_null_candidates(
    store: KGStore, documents: Iterable[Document] | None = None,
) -> list[MissedNullCandidate]:
    """Return uncited measured-null sentences, in document and source order.

    Citation coordinates, not edge primary spans, matter: an existing edge can
    have multiple document-local citations after statement-identity merging.
    """
    cited: dict[str, list[tuple[int, int]]] = {}
    for row in store.conn.execute(
        "SELECT c.source_doc_id, c.source_span FROM citations c "
        "JOIN edges e ON e.id = c.item_id "
        "WHERE c.kind = 'edge' AND e.status IN ('proposed','verified') "
        "AND e.invalidated_ts IS NULL "
        "AND json_extract(e.qualifiers_json, '$.polarity') IN ('no_effect','refutes') "
        "AND c.source_span IS NOT NULL"
    ):
        span = json.loads(row["source_span"])
        cited.setdefault(row["source_doc_id"], []).append((span["start"], span["end"]))

    candidates: list[MissedNullCandidate] = []
    for document in documents if documents is not None else store.list_documents():
        text = store.document_raw_text(document.id)
        for start, end, sentence in _sentences(text):
            if any(a < end and start < b for a, b in cited.get(document.id, ())):
                continue
            cue = next((name for name, pattern in _CUES if pattern.search(sentence)), None)
            if cue is not None:
                candidates.append(MissedNullCandidate(document.id, start, end, sentence, cue))
    return candidates
