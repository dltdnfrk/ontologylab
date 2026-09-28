"""Offline, budgeted extraction of grounded statement-unit proposals."""

from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass
from hashlib import sha256
from typing import Final

from ontologylab.engines import EngineError, extract_fenced_block
from ontologylab.extractor import (
    Chunk, build_statement_prompt, parse_and_validate_extraction,
)
from ontologylab.kgstore import KGStore
from ontologylab.models import Engine, ProposedEntity, ProposedRelation
from ontologylab.statement_candidates import CUE_VERSION, detect_candidates
from ontologylab.statement_eval import HarnessRun as EvaluationRun
from ontologylab.statement_eval import Paper, Span, Statement
from ontologylab.statement_qualifiers import QUALIFIER_VOCABULARIES
from ontologylab.statement_units import (
    RULES_VERSION, SectionSpan, SourceUnit, enumerate_units,
)
from ontologylab.unit_normalization import UNIT_TABLE

PROMPT_VERSION: Final = "statement-harness-v1"
MAX_STATEMENTS: Final = 8
MAX_WINDOW_CHARS: Final = 12000
_MENTION_KEYS: Final = frozenset({"quote", "start", "end"})
_REQUIRED: Final = frozenset({
    "unit_id", "subject", "object", "treatment", "endpoint", "result",
    "arm", "source", "relation_type", "polarity", "qualifiers",
    "qualifier_mentions",
})
_OUTPUT_CONTRACT: Final = {
    "required": ["statements"],
    "max_statements": MAX_STATEMENTS,
    "statement_keys": sorted(_REQUIRED),
    "mention_keys": sorted(_MENTION_KEYS),
    "polarity": ["supports", "no_effect", "refutes"],
}
_HEADINGS: Final = re.compile(
    r"(?im)^(?:#+\s*)?(results|discussion|conclusion|methods)\s*:?\s*$"
)


class StatementRejected(ValueError):
    """A model record failed local schema or source-grounding checks."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


@dataclass(frozen=True, slots=True)
class HarnessBudget:
    max_calls: int
    max_window_chars: int = MAX_WINDOW_CHARS


@dataclass(frozen=True, slots=True)
class ValidatedStatement:
    entities: tuple[ProposedEntity, ProposedEntity]
    relation: ProposedRelation
    arm: Span
    result: Span
    qualifiers: tuple[tuple[str, str], ...]


@dataclass(frozen=True, slots=True)
class HarnessRun(EvaluationRun):
    status: str = "complete"
    unprocessed_units: tuple[str, ...] = ()
    rejections: tuple[tuple[str, str], ...] = ()
    calls: int = 0


def _sections(text: str) -> tuple[SectionSpan, ...]:
    headings = tuple(_HEADINGS.finditer(text))
    if not headings:
        return (SectionSpan("section_unresolved", 0, len(text)),) if text else ()
    sections: list[SectionSpan] = []
    for index, heading in enumerate(headings):
        end = headings[index + 1].start() if index + 1 < len(headings) else len(text)
        start = heading.end()
        while start < end and text[start].isspace():
            start += 1
        if start < end:
            label = heading[1].lower()
            if label == "results":
                sections.append(SectionSpan("results", start, end))
            elif label == "discussion":
                sections.append(SectionSpan("discussion", start, end))
            elif label == "conclusion":
                sections.append(SectionSpan("conclusion", start, end))
            else:
                sections.append(SectionSpan("methods", start, end))
    return tuple(sections)


def _mention(raw: object, window: str, base: int, allowed: tuple[tuple[int, int], ...],
             reason: str) -> Span:
    if not isinstance(raw, dict) or set(raw) not in (
        _MENTION_KEYS, _MENTION_KEYS | {"entity_type"},
    ):
        raise StatementRejected("malformed_schema")
    quote, start, end = raw["quote"], raw["start"], raw["end"]
    if (not isinstance(quote, str) or not quote.strip()
            or type(start) is not int or type(end) is not int
            or not 0 <= start < end <= len(window)
            or window[start:end] != quote):
        raise StatementRejected(reason)
    absolute = Span(base + start, base + end, quote)
    if not any(left <= absolute.start < absolute.end <= right for left, right in allowed):
        if not (reason == "source_quote_mismatch" and len(allowed) == 2
                and allowed[1][0] <= absolute.start < allowed[0][1]
                and allowed[0][0] < absolute.end <= allowed[0][1]):
            raise StatementRejected("outside_unit_window")
    return absolute


def _anchor(span: Span, anchor: str) -> bool:
    start, end = (int(part) for part in anchor.split(":"))
    return start <= span.start < span.end <= end


def validate_statement_output(
    raw: object, unit: SourceUnit, original_text: str, schema: dict,
) -> ValidatedStatement:
    """Reject wrong-arm or relocated quotes before and after document rebasing."""
    if not isinstance(raw, dict) or set(raw) != _REQUIRED:
        raise StatementRejected("malformed_schema")
    if raw["unit_id"] != unit.unit_id:
        raise StatementRejected("wrong_unit")
    start = min((item[0] for item in unit.context_spans), default=unit.sentence_start)
    window = original_text[start:unit.sentence_end]
    allowed = ((unit.sentence_start, unit.sentence_end), *unit.context_spans)
    mentions = {
        key: _mention(raw[key], window, start, allowed, f"{key}_quote_mismatch")
        for key in ("subject", "object", "treatment", "endpoint", "result", "arm", "source")
    }
    for key, span in mentions.items():
        if original_text[span.start:span.end] != span.quote:
            raise StatementRejected(f"{key}_document_mismatch")
    if (not unit.arm_anchor or not unit.result_anchor
            or not _anchor(mentions["arm"], unit.arm_anchor)
            or not _anchor(mentions["result"], unit.result_anchor)):
        raise StatementRejected("wrong_arm_or_result")
    if (not _anchor(mentions["treatment"], unit.arm_anchor)
            and not (unit.context_spans and any(
                left <= mentions["treatment"].start < mentions["treatment"].end <= right
                for left, right in unit.context_spans
            ))):
        raise StatementRejected("wrong_treatment")
    source = mentions["source"]
    if (not source.start <= mentions["arm"].start < mentions["arm"].end <= source.end
            or not source.start <= mentions["result"].start < mentions["result"].end <= source.end
            or not source.start <= mentions["endpoint"].start < mentions["endpoint"].end <= source.end
            or not source.start <= mentions["subject"].start < mentions["subject"].end <= source.end
            or not source.start <= mentions["object"].start < mentions["object"].end <= source.end):
        raise StatementRejected("ungrounded_source_span")
    if source.start < unit.sentence_start and not unit.context_spans:
        raise StatementRejected("unrecorded_context")
    polarity = raw["polarity"]
    if polarity not in ("supports", "no_effect", "refutes") or type(polarity) is not str:
        raise StatementRejected("malformed_schema")
    qualifiers = raw["qualifiers"]
    qualifier_mentions = raw["qualifier_mentions"]
    relation_type = raw["relation_type"]
    relations = {row["name"]: row for row in schema["relation_types"]
                 if row.get("extractable", True)}
    entities = {row["name"] for row in schema["entity_types"]
                if row.get("extractable", True)}
    relation_spec = relations.get(relation_type) if isinstance(relation_type, str) else None
    if (relation_spec is None or not isinstance(qualifiers, dict)
            or len(qualifiers) > 16 or not isinstance(qualifier_mentions, dict)
            or set(qualifier_mentions) != set(qualifiers)
            or any(key not in relation_spec.get("qualifiers", {}) for key in qualifiers)):
        raise StatementRejected("malformed_schema")
    if (any(type(value) is not str or not value.strip() for value in qualifiers.values())
            or any(value != _mention(qualifier_mentions[key], window, start, allowed,
                                     "qualifier_quote_mismatch").quote
                   for key, value in qualifiers.items())):
        raise StatementRejected("qualifier_quote_mismatch")
    for key, value in qualifiers.items():
        spec = relation_spec["qualifiers"][key]
        if spec.get("enum") and value not in spec["enum"]:
            raise StatementRejected("malformed_schema")
    qualifiers = {**qualifiers, "polarity": polarity}
    payload_entities = []
    for key in ("subject", "object"):
        ent = raw[key]
        if (not isinstance(ent, dict) or set(ent) != _MENTION_KEYS | {"entity_type"}
                or not isinstance(ent["entity_type"], str)
                or ent["entity_type"] not in entities):
            raise StatementRejected("malformed_schema")
        span = mentions[key]
        payload_entities.append({
            "name": span.quote, "entity_type": ent["entity_type"],
            "source_span": {"start": span.start - start, "end": span.end - start},
        })
    payload = {
        "entities": payload_entities,
        "relations": [{
            "relation_type": relation_type,
            "source": {"name": mentions["subject"].quote,
                       "entity_type": raw["subject"]["entity_type"]},
            "target": {"name": mentions["object"].quote,
                       "entity_type": raw["object"]["entity_type"]},
            "qualifiers": qualifiers,
            "source_span": {"start": source.start - start, "end": source.end - start},
        }],
    }
    parsed = parse_and_validate_extraction(
        json.dumps(payload), schema, Chunk(0, start, window),
        require_source_spans=True, no_relocation=True,
    )
    if parsed.rejections or len(parsed.entities) != 2 or len(parsed.relations) != 1:
        raise StatementRejected("parser_rejected")
    for entity in parsed.entities:
        if entity.source_span is None or original_text[
            entity.source_span.start:entity.source_span.end
        ] != entity.name:
            raise StatementRejected("post_parse_relocation")
    relation = parsed.relations[0]
    if (relation.source_span is None
            or original_text[relation.source_span.start:relation.source_span.end]
            != source.quote):
        raise StatementRejected("post_parse_relocation")
    return ValidatedStatement(
        (parsed.entities[0], parsed.entities[1]), relation,
        mentions["arm"], mentions["result"], tuple(sorted(qualifiers.items())),
    )


def run_statement_harness(
    store: KGStore, document_ids: tuple[str, ...] | list[str], engine: Engine | None,
    *, budget: HarnessBudget | int, live: bool = False,
) -> HarnessRun:
    """Enumerate all eligible units, make at most one offline call per unit."""
    if live:
        raise EngineError("live statement engine is not configured")
    if engine is None:
        raise ValueError("a configured engine is required")
    limit = budget if isinstance(budget, HarnessBudget) else HarnessBudget(budget)
    if limit.max_calls < 0 or limit.max_window_chars < 1:
        raise ValueError("invalid harness budget")
    schema = store.get_schema()
    papers: list[Paper] = []
    work: list[tuple[str, str, SourceUnit]] = []
    for doc_id in document_ids:
        doc = store.get_document(doc_id)
        text = store.document_raw_text(doc_id)
        digest = sha256(text.encode("utf-8")).hexdigest()
        if doc.content_hash != digest:
            raise ValueError("source document hash mismatch")
        papers.append(Paper(doc.doi or doc.id, "", text, digest))
        work.extend((doc_id, text, unit) for unit in enumerate_units(
            text, _sections(text), source_sha256=digest, rules_version=RULES_VERSION,
        ) if unit.section in ("results", "discussion", "conclusion"))
    receipts: list[Statement] = []
    rejections: list[tuple[str, str]] = []
    unprocessed: list[str] = []
    calls = 0
    for doc_id, text, unit in work:
        start = min((span[0] for span in unit.context_spans), default=unit.sentence_start)
        if calls >= limit.max_calls or unit.sentence_end - start > min(
            limit.max_window_chars, MAX_WINDOW_CHARS,
        ):
            unprocessed.append(unit.unit_id)
            continue
        # The cue detector consumes a sentence view; it never selects or drops units.
        sentence = text[unit.sentence_start:unit.sentence_end]
        view = _SentenceView(text, unit.sentence_start, unit.sentence_end, sentence)
        cues = detect_candidates(view, cue_version=CUE_VERSION)
        prompt = build_statement_prompt(
            schema, unit, output_contract=_OUTPUT_CONTRACT, text=text, cues=cues,
        )
        raw_text, _usage = asyncio.run(engine.generate(prompt))
        calls += 1
        try:
            output = json.loads(extract_fenced_block(raw_text))
        except (EngineError, json.JSONDecodeError):
            rejections.append((unit.unit_id, "malformed_schema"))
            continue
        if (not isinstance(output, dict) or set(output) != {"statements"}
                or not isinstance(output["statements"], list)
                or len(output["statements"]) > MAX_STATEMENTS):
            rejections.append((unit.unit_id, "malformed_schema"))
            continue
        for item in output["statements"]:
            try:
                validated = validate_statement_output(item, unit, text, schema)
            except StatementRejected as exc:
                rejections.append((unit.unit_id, exc.reason))
                continue
            try:
                with store.atomic():
                    store.insert_proposed(
                        validated.entities, (validated.relation,),
                        source_doc_id=doc_id, extractor_engine=engine.name(),
                        prompt_version=PROMPT_VERSION, origin="extracted",
                    )
                    edge = store.conn.execute(
                        "SELECT c.item_id, e.status FROM citations c "
                        "JOIN edges e ON e.id = c.item_id "
                        "WHERE c.kind = 'edge' AND c.source_doc_id = ? "
                        "AND c.prompt_version = ? ORDER BY c.rowid DESC LIMIT 1",
                        (doc_id, PROMPT_VERSION),
                    ).fetchone()
                    if edge["status"] != "proposed":
                        raise StatementRejected("existing_verified_edge")
            except StatementRejected as exc:
                rejections.append((unit.unit_id, exc.reason))
                continue
            receipt = Statement(
                edge["item_id"], papers[next(i for i, paper in enumerate(papers)
                                if paper.source_sha256 == unit.source_sha256)].doi,
                unit.unit_id, validated.entities[0].name,
                validated.relation.relation_type, validated.entities[1].name,
                validated.relation.qualifiers["polarity"],
                tuple(sorted((key, value) for key, value in
                             validated.relation.qualifiers.items() if key != "polarity")),
                tuple(sorted((key, value) for key, value in
                             validated.relation.qualifiers.items() if key != "polarity")),
                validated.arm, validated.result,
            )
            receipts.append(receipt)
    hashes = tuple(
        (name, sha256(value.encode("utf-8")).hexdigest())
        for name, value in (
            ("rules", RULES_VERSION),
            ("cue", CUE_VERSION),
            ("prompt", PROMPT_VERSION),
            ("schema", json.dumps(schema, sort_keys=True)),
            ("qualifier", json.dumps(QUALIFIER_VOCABULARIES, sort_keys=True)),
            ("normalization", json.dumps(
                {
                    key: [unit.code, unit.dimension, unit.factor]
                    for key, unit in UNIT_TABLE.items()
                },
                sort_keys=True,
            )),
            ("completion", "completion:off"),
        )
    )
    return HarnessRun(
        tuple(receipts), tuple(papers), hashes, not unprocessed,
        status="incomplete" if unprocessed else "complete",
        unprocessed_units=tuple(unprocessed), rejections=tuple(rejections), calls=calls,
    )


@dataclass(frozen=True, slots=True)
class _SentenceView:
    text: str
    start: int
    end: int
    sentence: str
