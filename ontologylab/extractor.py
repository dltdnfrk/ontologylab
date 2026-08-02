"""LLM extraction pipeline: chunking, prompt building, parse + validate.

The model contract (ARCHITECTURE.md §7.1): the engine returns a single
fenced ```json block of ``{"entities": [...], "relations": [...]}`` where
each relation references its endpoints by ``{name, entity_type}`` — never by
array index and never by a model-invented id. ``parse_and_validate_extraction``
calls ``extract_fenced_block`` internally (callers pass RAW model text),
validates against the active ontology schema (off-schema items are rejected
and logged, never coerced), mints a uuid per valid entity, resolves relation
endpoints through the per-chunk ``(normalized_name, entity_type)`` map
(synthesizing a flagged placeholder for a relation naming an un-emitted
entity), and rebases every chunk-local ``source_span`` to document
coordinates so a stored span always indexes ``documents.raw_text``.

Citation integrity is enforced at parse time: a span that does not contain
its claimed surface form is re-located by searching the chunk; an entity
whose name cannot be found at all is dropped with a warning, never stored
with a fabricated offset.
"""

from __future__ import annotations

import json
import re
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from ontologylab.engines import (
    CHUNK_MARKER_CLOSE,
    CHUNK_MARKER_OPEN,
    EngineError,
    extract_fenced_block,
)
from ontologylab.extraction_state import ExtractionState
from ontologylab.kgstore import normalize_name
from ontologylab.models import ProposedEntity, ProposedRelation, SourceSpan
from ontologylab.normalization import (
    ACTIVE_ENTITY_TYPE,
    ORGANISM_ENTITY_TYPES,
    normalize_proposal,
)
from ontologylab.registry import CASRegistryCache, MoARegistryCache, RegistryCache

PROMPT_VERSION = "extract-v1"

# Heuristic tokenizer: ~4 chars/token (no model-specific tokenizer dep).
CHARS_PER_TOKEN = 4
TARGET_CHUNK_TOKENS = 3000
OVERLAP_TOKENS = 150


@dataclass
class Chunk:
    """One chunk of a document, tracked for span rebasing."""

    index: int
    char_offset: int  # offset of chunk start within the original document
    text: str


@dataclass
class ExtractionResult:
    """Validated output of one chunk extraction."""

    entities: list[ProposedEntity]
    relations: list[ProposedRelation]
    warnings: list[str] = field(default_factory=list)


def estimate_tokens(text: str) -> int:
    return max(1, len(text) // CHARS_PER_TOKEN)


def chunk_document(
    text: str,
    *,
    target_tokens: int = TARGET_CHUNK_TOKENS,
    overlap_tokens: int = OVERLAP_TOKENS,
) -> list[Chunk]:
    """Split ``text`` into ~target_tokens chunks with ~overlap_tokens overlap.

    Boundaries snap to whitespace where possible so an entity mention is not
    cut mid-word; the overlap exists so a fact straddling a boundary is seen
    whole by at least one chunk (resolution dedups the duplicate mention).
    """
    target_chars = target_tokens * CHARS_PER_TOKEN
    overlap_chars = overlap_tokens * CHARS_PER_TOKEN
    if len(text) <= target_chars:
        return [Chunk(index=0, char_offset=0, text=text)]

    chunks: list[Chunk] = []
    start = 0
    index = 0
    while start < len(text):
        end = min(start + target_chars, len(text))
        if end < len(text):
            # snap back to the last whitespace in the second half of the chunk
            snap = text.rfind(" ", start + target_chars // 2, end)
            if snap > start:
                end = snap
        chunks.append(Chunk(index=index, char_offset=start, text=text[start:end]))
        index += 1
        if end >= len(text):
            break
        next_start = end - overlap_chars
        # snap forward to a whitespace so the overlap starts on a word boundary
        snap = text.find(" ", next_start, end)
        if snap != -1:
            next_start = snap + 1
        start = max(next_start, start + 1)  # always progress
    return chunks


# ---------------------------------------------------------------------------
# Prompt
# ---------------------------------------------------------------------------

_FEW_SHOT = """\
Example (for a chunk describing a rate limiting component):
```json
{
  "entities": [
    { "name": "RateLimiter", "entity_type": "Component",
      "aliases": ["rate-limiter"], "properties": {"language": "Go"},
      "confidence": 0.9, "source_span": {"start": 128, "end": 190} },
    { "name": "TokenBucketAlgorithm", "entity_type": "Concept",
      "aliases": [], "properties": {},
      "confidence": 0.85, "source_span": {"start": 205, "end": 260} }
  ],
  "relations": [
    { "relation_type": "uses",
      "source": {"name": "RateLimiter", "entity_type": "Component"},
      "target": {"name": "TokenBucketAlgorithm", "entity_type": "Concept"},
      "confidence": 0.8, "source_span": {"start": 128, "end": 260} }
  ]
}
```"""


def _schema_block(schema: dict[str, Any]) -> str:
    lines = ["Entity types:"]
    for et in schema["entity_types"]:
        attrs = ""
        if et["attributes"]:
            attrs = f" Attributes: {json.dumps(et['attributes'])}"
        lines.append(f"- {et['name']}: {et['description']}{attrs}")
    lines.append("Relation types:")
    for rt in schema["relation_types"]:
        domain = rt["domain_type"]
        range_ = rt["range_type"]
        lines.append(
            f"- {rt['name']}: {rt['description']} (source type: {domain}, "
            f"target type: {range_}; '*' means any)"
        )
    return "\n".join(lines)


def build_extraction_prompt(schema: dict[str, Any], chunk_text: str) -> str:
    """Build the extraction prompt for one document chunk.

    Embeds the active ontology schema and the chunk between explicit
    <document-chunk> markers, and pins the exact JSON output contract.
    """
    return f"""You are an information-extraction engine. Extract entities and relations \
from the document chunk below, strictly following the ontology schema.

{_schema_block(schema)}

Rules:
1. Return EXACTLY ONE fenced ```json block and nothing else.
2. The JSON shape is {{"entities": [...], "relations": [...]}}.
3. Each entity: name, entity_type (one of the schema types), aliases (list),
   properties (only attribute keys declared for its type), confidence (0..1),
   source_span {{"start": int, "end": int}} — character offsets INTO THE CHUNK
   TEXT BELOW (0 = first character of the chunk) covering the mention.
4. Each relation references its endpoints by {{"name": ..., "entity_type": ...}}
   of entities you emitted — never by array index, never by an invented id.
5. Only extract facts stated in the chunk. Do not use outside knowledge.
6. If nothing is extractable, return {{"entities": [], "relations": []}}.

{_FEW_SHOT}

{CHUNK_MARKER_OPEN}
{chunk_text}
{CHUNK_MARKER_CLOSE}"""


# ---------------------------------------------------------------------------
# Parse + validate
# ---------------------------------------------------------------------------


def _validate_span(raw: Any, chunk_len: int) -> SourceSpan | None:
    if not isinstance(raw, dict):
        return None
    try:
        start = int(raw["start"])
        end = int(raw["end"])
    except (KeyError, TypeError, ValueError):
        return None
    if start < 0 or end <= start or end > chunk_len:
        return None
    return SourceSpan(start=start, end=end)


def _locate(chunk_text: str, surface: str) -> SourceSpan | None:
    """Find ``surface`` in the chunk (case-insensitive), as a span.

    Uses a regex IGNORECASE search on the ORIGINAL text — searching a
    casefolded copy would return offsets shifted by any length-changing
    casefold (ß→ss, ﬁ→fi), corrupting the stored citation span.
    """
    match = re.search(re.escape(surface), chunk_text, re.IGNORECASE)
    if match is None:
        return _locate_skeleton(chunk_text, surface)
    return SourceSpan(start=match.start(), end=match.end())


def _alnum_skeleton(text: str) -> str:
    return re.sub(r"[^0-9a-z]+", "", text.casefold())


def _locate_skeleton(chunk_text: str, surface: str) -> SourceSpan | None:
    """Locate ``surface`` by alphanumeric skeleton, mapping back to offsets.

    A name the model canonicalized (RateLimiter) is still grounded when the
    document wrote it differently (rate-limiter) — rejecting those taught
    the queue to drop real mentions (2026-08-01 audit). Matching runs on the
    skeleton; the returned span indexes the ORIGINAL chunk text, and each
    casefolded character keeps its own offset so length-changing folds
    (ß→ss) cannot shift the citation."""
    target = _alnum_skeleton(surface)
    if not target:
        return None
    skeleton: list[str] = []
    offsets: list[int] = []
    for index, char in enumerate(chunk_text):
        for folded in char.casefold():
            if re.match(r"[0-9a-z]", folded):
                skeleton.append(folded)
                offsets.append(index)
    pos = "".join(skeleton).find(target)
    if pos < 0:
        return None
    return SourceSpan(start=offsets[pos], end=offsets[pos + len(target) - 1] + 1)


def _span_cites(chunk_text: str, span: SourceSpan, surface: str) -> bool:
    if surface.casefold() in chunk_text[span.start : span.end].casefold():
        return True
    return _alnum_skeleton(surface) in _alnum_skeleton(
        chunk_text[span.start : span.end]
    )


def _clamp_confidence(raw: Any) -> float | None:
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    return min(1.0, max(0.0, value))


def parse_and_validate_extraction(
    raw_text: str, schema: dict[str, Any], chunk: Chunk
) -> ExtractionResult:
    """Parse raw model text into schema-valid, document-rebased proposals.

    Off-schema entities/relations are rejected (with a warning), never
    coerced; off-schema property keys are dropped key-wise. Spans are
    validated against the claimed surface form and rebased to document
    coordinates (``doc_start = chunk.char_offset + span.start``).
    """
    warnings: list[str] = []
    block = extract_fenced_block(raw_text, lang="json")
    try:
        payload = json.loads(block)
    except json.JSONDecodeError as exc:
        raise EngineError(f"extraction JSON did not parse: {exc}") from exc
    if not isinstance(payload, dict):
        raise EngineError("extraction JSON must be an object")

    entity_types = {et["name"]: et for et in schema["entity_types"]}
    relation_types = {rt["name"]: rt for rt in schema["relation_types"]}
    chunk_len = len(chunk.text)

    entities: list[ProposedEntity] = []
    by_key: dict[tuple[str, str], ProposedEntity] = {}

    for i, raw_ent in enumerate(payload.get("entities") or []):
        if not isinstance(raw_ent, dict):
            warnings.append(f"entity[{i}]: not an object; rejected")
            continue
        name = raw_ent.get("name")
        etype = raw_ent.get("entity_type")
        if not isinstance(name, str) or not name.strip():
            warnings.append(f"entity[{i}]: missing/empty name; rejected")
            continue
        name = name.strip()
        if etype not in entity_types:
            warnings.append(
                f"entity[{i}] {name!r}: unknown entity_type {etype!r}; rejected"
            )
            continue

        # citation integrity at parse time: span must contain the name, else
        # re-locate; unfindable names are dropped, never stored fabricated.
        span = _validate_span(raw_ent.get("source_span"), chunk_len)
        if span is None or not _span_cites(chunk.text, span, name):
            relocated = _locate(chunk.text, name)
            if relocated is None:
                warnings.append(
                    f"entity[{i}] {name!r}: name not found in chunk; rejected"
                )
                continue
            if span is not None:
                warnings.append(
                    f"entity[{i}] {name!r}: span did not contain name; relocated"
                )
            span = relocated

        aliases_raw = raw_ent.get("aliases") or []
        if not isinstance(aliases_raw, list):
            raise EngineError(
                f"entity[{i}] {name!r}: aliases must be a list, got "
                f"{type(aliases_raw).__name__}"
            )
        aliases = [a.strip() for a in aliases_raw if isinstance(a, str) and a.strip()]

        allowed_attrs = entity_types[etype]["attributes"]
        properties_raw = raw_ent.get("properties") or {}
        if not isinstance(properties_raw, dict):
            raise EngineError(
                f"entity[{i}] {name!r}: properties must be an object, got "
                f"{type(properties_raw).__name__}"
            )
        properties: dict[str, Any] = {}
        for prop_key, value in properties_raw.items():
            spec = allowed_attrs.get(prop_key)
            if spec is None:
                warnings.append(
                    f"entity[{i}] {name!r}: off-schema property {prop_key!r}; dropped"
                )
                continue
            enum = spec.get("enum")
            if enum and value not in enum:
                warnings.append(
                    f"entity[{i}] {name!r}: property {prop_key!r} value {value!r} "
                    f"not in enum; dropped"
                )
                continue
            properties[prop_key] = value

        key = (normalize_name(name), etype)
        if key in by_key:
            # duplicate mention within one response: merge aliases, keep first
            existing = by_key[key]
            for alias in [name, *aliases]:
                if normalize_name(alias) != normalize_name(existing.name) and all(
                    normalize_name(alias) != normalize_name(a)
                    for a in existing.aliases
                ):
                    existing.aliases.append(alias)
            continue

        entity = ProposedEntity(
            id=uuid.uuid4().hex,
            entity_type=etype,
            name=name,
            aliases=aliases,
            properties=properties,
            confidence=_clamp_confidence(raw_ent.get("confidence")),
            source_span=SourceSpan(
                start=chunk.char_offset + span.start,
                end=chunk.char_offset + span.end,
            ),
        )
        by_key[key] = entity
        entities.append(entity)

    def resolve_endpoint(
        raw_ref: Any, rel_index: int, side: str
    ) -> ProposedEntity | None:
        if not isinstance(raw_ref, dict):
            warnings.append(f"relation[{rel_index}]: {side} endpoint not an object")
            return None
        ref_name = raw_ref.get("name")
        ref_type = raw_ref.get("entity_type")
        if not isinstance(ref_name, str) or not ref_name.strip():
            warnings.append(f"relation[{rel_index}]: {side} endpoint missing name")
            return None
        ref_name = ref_name.strip()
        if ref_type not in entity_types:
            warnings.append(
                f"relation[{rel_index}]: {side} endpoint has unknown type {ref_type!r}"
            )
            return None
        key = (normalize_name(ref_name), ref_type)
        hit = by_key.get(key)
        if hit is not None:
            return hit
        # relation names an entity the model didn't emit: mint a flagged
        # placeholder of the declared type so the edge is never dangling.
        span = _locate(chunk.text, ref_name)
        if span is None:
            # The same claim, made directly, is rejected two hundred lines
            # above with "name not found in chunk". Arriving as an endpoint
            # instead must not make it quieter: this is the only path by
            # which a name absent from the source text becomes a proposal,
            # and the reviewer approving it is entitled to know that.
            # The placeholder is still minted — a dangling edge is worse —
            # but it carries no span, which is what marks it downstream.
            warnings.append(
                f"relation[{rel_index}]: {side} endpoint {ref_name!r} does "
                f"not appear in the chunk; proposed WITHOUT a source span"
            )
        placeholder = ProposedEntity(
            id=uuid.uuid4().hex,
            entity_type=ref_type,
            name=ref_name,
            confidence=None,
            source_span=(
                SourceSpan(
                    start=chunk.char_offset + span.start,
                    end=chunk.char_offset + span.end,
                )
                if span
                else None
            ),
            synthesized=True,
        )
        by_key[key] = placeholder
        entities.append(placeholder)
        warnings.append(
            f"relation[{rel_index}]: synthesized_endpoint {ref_name!r} ({ref_type})"
        )
        return placeholder

    relations: list[ProposedRelation] = []
    for i, raw_rel in enumerate(payload.get("relations") or []):
        if not isinstance(raw_rel, dict):
            warnings.append(f"relation[{i}]: not an object; rejected")
            continue
        rtype = raw_rel.get("relation_type")
        rt_spec = relation_types.get(rtype)
        if rt_spec is None:
            warnings.append(
                f"relation[{i}]: unknown relation_type {rtype!r}; rejected"
            )
            continue
        src = resolve_endpoint(raw_rel.get("source"), i, "source")
        dst = resolve_endpoint(raw_rel.get("target"), i, "target")
        if src is None or dst is None:
            continue
        # domain/range check: '*' means any
        if rt_spec["domain_type"] != "*" and src.entity_type != rt_spec["domain_type"]:
            warnings.append(
                f"relation[{i}] {rtype}: source type {src.entity_type} violates "
                f"domain {rt_spec['domain_type']}; rejected"
            )
            continue
        if rt_spec["range_type"] != "*" and dst.entity_type != rt_spec["range_type"]:
            warnings.append(
                f"relation[{i}] {rtype}: target type {dst.entity_type} violates "
                f"range {rt_spec['range_type']}; rejected"
            )
            continue

        # relation span must cover both endpoint mentions; if the model's
        # span doesn't, synthesize the minimal document-coordinate span
        # covering both endpoint spans (guaranteed to contain both names).
        span = _validate_span(raw_rel.get("source_span"), chunk_len)
        doc_span: SourceSpan | None = None
        if span is not None:
            span_text = chunk.text[span.start : span.end]
            if (
                src.name.casefold() in span_text.casefold()
                and dst.name.casefold() in span_text.casefold()
            ):
                doc_span = SourceSpan(
                    start=chunk.char_offset + span.start,
                    end=chunk.char_offset + span.end,
                )
        if doc_span is None and src.source_span and dst.source_span:
            doc_span = SourceSpan(
                start=min(src.source_span.start, dst.source_span.start),
                end=max(src.source_span.end, dst.source_span.end),
            )

        relations.append(
            ProposedRelation(
                id=uuid.uuid4().hex,
                relation_type=rtype,
                src_entity_id=src.id,
                dst_entity_id=dst.id,
                confidence=_clamp_confidence(raw_rel.get("confidence")),
                source_span=doc_span,
            )
        )

    return ExtractionResult(entities=entities, relations=relations, warnings=warnings)


TOTALS_KEYS: tuple[str, ...] = (
    "nodes_new",
    "nodes_merged",
    "edges_new",
    "edges_merged",
)


def unprocessed_doc_ids(store: Any) -> list[str]:
    """Return documents with no extracted rows yet.

    This is a *global* query. A caller that already knows which documents it
    produced must pass those ids instead of relying on this, or it will pull
    in older documents and any produced concurrently by another run.
    """
    return [
        row["id"]
        for row in store.conn.execute(
            "SELECT id FROM documents WHERE id NOT IN "
            "(SELECT DISTINCT source_doc_id FROM nodes)"
        )
    ]


def extraction_decode_params(engine: Any) -> dict[str, Any] | None:
    """Canonical stream parameters actually selected by an engine."""
    params = getattr(engine, "_decode_params", None)
    return dict(params) if params is not None else None


def extraction_doc_ids(store: Any) -> list[str]:
    """All documents; lifecycle identity decides which need work."""
    return [
        row["id"]
        for row in store.conn.execute(
            "SELECT id FROM documents ORDER BY fetched_ts ASC"
        )
    ]


async def run_extraction(
    store: Any,
    engine: Any,
    provenance: Any,
    caps: Any,
    doc_ids: list[str],
    *,
    extractor_engine: str,
    extractor_model: str | None,
    on_progress: Callable[[str], None],
    on_stats: Callable[[dict[str, int]], None],
    should_abort: Callable[[], str] | None = None,
    decode_params: dict[str, Any] | None = None,
) -> str:
    """Extract every chunk of every document; return why it stopped, or "".

    The CLI and the server worker ran near-identical copies of this loop and
    a third caller (the research run) would have made three. They differ in
    exactly four ways, so those four are the parameters:

    * **progress** — the CLI prints, the worker appends to a job log.
    * **stats** — the CLI accumulates locally, the worker must take its job
      lock. Accumulation is the caller's, so neither has to know the other's
      locking discipline.
    * **abort** — `should_abort` returns a non-empty reason to stop. The CLI
      passes its kill switch; the server has none yet, and giving it one is
      now a matter of passing this argument rather than editing a loop.
    * **store lifetime** — owned by the caller, because sqlite connections
      are thread-bound and the worker must open its own inside the thread.

    Budget checks run *before* each engine call, so a spent budget costs
    nothing. An engine or parse failure on one chunk is logged and skipped:
    one malformed response must not discard the document's other chunks.
    """
    schema = store.get_schema()
    has_organisms = any(
        entity["name"] in ORGANISM_ENTITY_TYPES
        and "eppo_code" in entity["attributes"]
        for entity in schema["entity_types"]
    )
    has_actives = any(
        entity["name"] == ACTIVE_ENTITY_TYPE
        and "cas_number" in entity["attributes"]
        for entity in schema["entity_types"]
    )
    registry = RegistryCache(store.db_path.parent) if has_organisms else None
    cas_registry = CASRegistryCache(store.db_path.parent) if has_actives else None
    moa_registry = MoARegistryCache(store.db_path.parent) if has_actives else None
    for authoritative_cache in (registry, cas_registry):
        if authoritative_cache is None:
            continue
        warning = authoritative_cache.provenance_warning()
        if warning is not None:
            # Cache absence is one run-level configuration fact, not one
            # suspicious proposal per organism, active, or chunk.
            provenance.log("extract.warning", {"warning": warning})

    lifecycle = ExtractionState(store.conn)
    stopped_reason = ""
    abort_triggered = False
    for doc_id in doc_ids:
        raw_text = store.document_raw_text(doc_id)
        chunks = chunk_document(raw_text)
        plan = lifecycle.plan(
            doc_id,
            chunks,
            schema_version_id=schema["schema_version_id"],
            engine=extractor_engine,
            model=extractor_model,
            prompt_version=PROMPT_VERSION,
            decode_params=decode_params,
        )
        provenance.log("extract.doc", {"doc_id": doc_id, "chunks": len(chunks)})
        if plan.status in {"complete", "cancelled"}:
            continue
        for chunk in chunks:
            if chunk.index not in plan.retryable:
                continue
            stop, reason = caps.should_stop(
                {
                    "elapsed": provenance.elapsed_s,
                    "engine_calls": provenance.engine_calls,
                }
            )
            if stop:
                stopped_reason = reason
                break
            if should_abort is not None:
                aborted = should_abort()
                if aborted:
                    stopped_reason = aborted
                    abort_triggered = True
                    break
            if not lifecycle.claim(plan.run_id, chunk.index):
                continue
            prompt = build_extraction_prompt(schema, chunk.text)
            try:
                raw_response, usage = await engine.generate(
                    prompt, model=extractor_model
                )
            except EngineError as exc:
                provenance.log(
                    "extract.engine_error",
                    {"doc_id": doc_id, "chunk": chunk.index, "error": str(exc)},
                )
                on_progress(
                    f"[ontologylab] engine error on {doc_id}#{chunk.index}: {exc}"
                )
                lifecycle.failed(plan.run_id, chunk.index, "engine_error")
                continue
            provenance.track_engine_call(
                "extract", float(usage.get("elapsed") or 0.0), usage
            )
            try:
                result = parse_and_validate_extraction(raw_response, schema, chunk)
            except EngineError as exc:
                # malformed/off-schema response: rejected + logged, never
                # inserted, never a crash (M4 acceptance criterion)
                provenance.log(
                    "extract.parse_rejected",
                    {"doc_id": doc_id, "chunk": chunk.index, "error": str(exc)},
                )
                lifecycle.failed(plan.run_id, chunk.index, "parse_rejected")
                continue
            for warning in result.warnings:
                provenance.log(
                    "extract.warning",
                    {"doc_id": doc_id, "chunk": chunk.index, "warning": warning},
                )
            try:
                for entity in result.entities:
                    if registry is not None:
                        normalize_proposal(entity, registry)
                    if cas_registry is not None:
                        normalize_proposal(entity, cas_registry, moa_registry)
                stats = store.insert_proposed(
                    result.entities,
                    result.relations,
                    source_doc_id=doc_id,
                    extractor_engine=extractor_engine,
                    extractor_model=extractor_model,
                    prompt_version=PROMPT_VERSION,
                    # What the provider actually used, not merely requested.
                    decode_params=usage.get("decode_params"),
                    commit=False,
                )
                lifecycle.succeeded(plan.run_id, chunk.index, stats)
            except Exception:
                lifecycle.failed(plan.run_id, chunk.index, "write_error")
                raise
            on_stats(stats)
            on_progress(
                f"[ontologylab] {doc_id}#{chunk.index}: "
                f"+{stats['nodes_new']} nodes (+{stats['nodes_merged']} merged), "
                f"+{stats['edges_new']} edges"
            )
        lifecycle.finish(plan.run_id, cancelled=abort_triggered)
        if stopped_reason:
            break
    lifecycle.close()
    return stopped_reason
