"""Source-grounded sentences needing human review for measured-null claims."""

from __future__ import annotations

from dataclasses import dataclass
import json
import re
from typing import Iterable, Literal

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
class CitedNullStatement:
    edge_id: str
    subject: str
    relation_type: str
    object: str
    polarity: str
    qualifiers: dict[str, str]
    status: str
    origin: str
    start: int
    end: int


@dataclass(frozen=True, slots=True)
class MissedNullCandidate:
    document_id: str
    start: int
    end: int
    text: str
    cue: str
    status: Literal["unextracted", "partially_extracted"]
    existing_statements: tuple[CitedNullStatement, ...]


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
    """Return measured-null sentences, in document and source order.

    A cited sentence still needs review: one extracted null arm does not
    establish that the other arms in that sentence were extracted. Citation
    coordinates, not primary edge spans, account for merged mentions.
    """
    cited: dict[str, list[CitedNullStatement]] = {}
    for row in store.conn.execute(
        "SELECT c.source_doc_id, c.source_span, e.id AS edge_id, "
        "s.name AS subject, e.relation_type, d.name AS object, "
        "e.qualifiers_json, e.status, e.origin FROM citations c "
        "JOIN edges e ON e.id = c.item_id "
        "JOIN nodes s ON s.id = e.src_node_id "
        "JOIN nodes d ON d.id = e.dst_node_id "
        "WHERE c.kind = 'edge' AND e.status IN ('proposed','verified') "
        "AND e.invalidated_ts IS NULL "
        "AND json_extract(e.qualifiers_json, '$.polarity') IN ('no_effect','refutes') "
        "AND c.source_span IS NOT NULL ORDER BY c.rowid, e.id"
    ):
        span = json.loads(row["source_span"])
        qualifiers = json.loads(row["qualifiers_json"])
        cited.setdefault(row["source_doc_id"], []).append(CitedNullStatement(
            edge_id=row["edge_id"], subject=row["subject"],
            relation_type=row["relation_type"], object=row["object"],
            polarity=qualifiers["polarity"], qualifiers=qualifiers,
            status=row["status"], origin=row["origin"],
            start=span["start"], end=span["end"],
        ))

    candidates: list[MissedNullCandidate] = []
    for document in documents if documents is not None else store.list_documents():
        text = store.document_raw_text(document.id)
        for start, end, sentence in _sentences(text):
            cue = next((name for name, pattern in _CUES if pattern.search(sentence)), None)
            if cue is not None:
                existing = {
                    item.edge_id: item
                    for item in cited.get(document.id, ())
                    if item.start < end and start < item.end
                }
                candidates.append(MissedNullCandidate(
                    document.id, start, end, sentence, cue,
                    "partially_extracted" if existing else "unextracted",
                    tuple(existing.values()),
                ))
    return candidates
