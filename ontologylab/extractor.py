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

import asyncio
import json
import re
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from ontologylab.citation import persist_chunk_citations
from ontologylab.citation_types import ChunkCitationBatch
from ontologylab.engines import (
    ApiEngine,
    CHUNK_MARKER_CLOSE,
    CHUNK_MARKER_OPEN,
    EngineError,
    MAX_TRANSPORT_BACKOFF_S,
    TransientEngineError,
    _DEFAULT_TIMEOUT_S,
    extract_fenced_block,
)
from ontologylab.extraction_eligibility import (
    NOT_FULL_TEXT,
    extraction_eligibilities,
    refusal_message,
)
from ontologylab.extraction_state import ExtractionState, effective_extractor_model
from ontologylab.kgstore import SchemaValidationError, normalize_name
from ontologylab.models import ProposedEntity, ProposedRelation, SourceSpan
from ontologylab.normalization import (
    ACTIVE_ENTITY_TYPE,
    ORGANISM_ENTITY_TYPES,
    normalize_proposal,
)
from ontologylab.provenance import Provenance
from ontologylab.paths import DEFAULT_MAX_TRANSPORT_RETRIES
from ontologylab.unit_normalization import normalize_measurement
from ontologylab.registry import CASRegistryCache, MoARegistryCache, RegistryCache
from ontologylab.safety import Caps
from ontologylab.species_abbreviation import resolve_species_abbreviation
from ontologylab.qualified_extraction import split_grounded_variants

PROMPT_VERSION = "extract-v7"
ENGINE_FAILURE_SUMMARY = "extraction engine failed"

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


class ExtractionOutcome(str):
    """Early-stop reason plus whether any handled chunk failed.

    This remains a string so CLI callers keep their existing stop/cancel
    semantics while the job layer can distinguish an exhausted/cancelled run
    from one that reached the end with a durable failed chunk.
    """

    chunk_failed: bool

    def __new__(cls, stopped_reason: str, *, chunk_failed: bool = False):
        outcome = super().__new__(cls, stopped_reason)
        outcome.chunk_failed = chunk_failed
        return outcome


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
```

Example for agrochem-v2 (invented text illustrating polarity, not study evidence):
Fluopyram had no significant effect on Botrytis. Boscalid suppressed Botrytis.
```json
{
  "entities": [
    { "name": "Fluopyram", "entity_type": "ActiveIngredient",
      "aliases": [], "properties": {}, "confidence": 0.9,
      "source_span": {"start": 0, "end": 9} },
    { "name": "Botrytis", "entity_type": "Pathogen",
      "aliases": [], "properties": {}, "confidence": 0.9,
      "source_span": {"start": 39, "end": 47} },
    { "name": "Boscalid", "entity_type": "ActiveIngredient",
      "aliases": [], "properties": {}, "confidence": 0.9,
      "source_span": {"start": 49, "end": 57} }
  ],
  "relations": [
    { "relation_type": "controls",
      "source": {"name": "Fluopyram", "entity_type": "ActiveIngredient"},
      "target": {"name": "Botrytis", "entity_type": "Pathogen"},
      "qualifiers": {"polarity": "no_effect"}, "confidence": 0.9,
      "source_span": {"start": 0, "end": 48} },
    { "relation_type": "controls",
      "source": {"name": "Boscalid", "entity_type": "ActiveIngredient"},
      "target": {"name": "Botrytis", "entity_type": "Pathogen"},
      "qualifiers": {"polarity": "supports"}, "confidence": 0.9,
      "source_span": {"start": 49, "end": 78} }
  ]
}
```"""


_POLARITY_GUIDANCE = """\
Polarity precedence for the exact assertion being extracted:
1. no_effect = a measured absence of a statistically significant effect.
   In a tested outcome, "no significant difference", "did not reduce",
   "not statistically different from the untreated control", and "ineffective"
   describe measured nulls. Choose no_effect before interpreting negative
   wording as refutes; a negation alone does not establish a refutation.
2. refutes = the source explicitly contradicts a claimed or expected positive
   relation, rather than merely reporting a measured null. For example,
   "Contrary to earlier accounts, Agent A does not control Moth beta."
   If a passage both challenges a prior claim and reports a measured null,
   keep the measured finding as no_effect; a separately stated contradiction
   may be its own refutes assertion with its own supporting span.
3. supports = a measured positive effect for this outcome, or an explicit
   positive assertion for a relation that is not an experimental finding.
"""


_BACKGROUND_GUIDANCE = """\
Introductory and background claims are not the study's finding. Either skip
them or, when the schema permits, emit them with study_context="background".
They must not override the finding, inherit its context or replace a null.
"""


_MULTI_ARM_GUIDANCE = """\
Comparison completeness:
When the source reports a comparison, emit a separate statement for EACH
reported treatment arm and population, including every null arm. Never drop
the null arm just because another arm has a positive effect. Enumerate the
reported outcomes before emitting relations, then check that each has its
own statement. Do not invent outcomes for arms that were not reported.
Use population_context_qualifier for the source's population label and
object_form_or_variant_qualifier for its strain, isolate or life stage.
Keep species names as core entities; different qualified statements may
share the same endpoints. Keep each arm's polarity, dose, measured aspect
and study_context attached to its own evidence span. A resistant population
with a measured null needs its own no_effect statement even when the
susceptible population supports the same relation.
"""


_AGROCHEM_GUIDANCE = """\
Agrochem relation selection and endpoint scope:
- Use the relation definitions above, not a verb-to-label substitution.
  "inhibits" describes inhibition of growth in an assay or suppression of a
  biological process (for example oviposition). "controls" describes treatment
  efficacy against a pest, weed, pathogen or its named disease, including
  mortality or weed biomass reduction in a control trial. An in-vitro growth
  result is not by itself evidence of disease control in a crop.
  "reduces" is not an agrochem-v2 relation: determine WHAT was reduced and in
  which experiment before choosing inhibits or controls.
- Use the Biolink fully-qualified-statement model: entity names are core
  concepts (species, chemical, crop or named disease), not decorated findings.
  Compose full semantics in relation qualifiers. Put isolates, strains and
  life stages in subject_form_or_variant_qualifier or
  object_form_or_variant_qualifier; populations in population_context_qualifier;
  measured aspects (growth, oviposition, mortality) in subject_aspect_qualifier
  or object_aspect_qualifier. Use species_context_qualifier and
  anatomical_context_qualifier for explicitly stated contextual species and
  anatomy. Use study_context for in vitro, field trial or a named assay; dose
  for the stated rate with units; application_timing for pre/post-emergence.
  Only use slots declared above. Keep each relation's own context separate.
  The core triple must remain true when qualifiers are ignored, except
  negation, which stays in polarity. Use qualified_predicate only when the
  full reading needs a more specific predicate; never invent a causal claim.
  Use the shortest span supporting THIS assertion and its qualifiers.
  Do not attach context from a different sentence, figure, treatment arm or
  document section. A bare-organism finding has no inferred isolate or stage.
  If an endpoint is implicit, use only its unambiguous local antecedent and
  include that antecedent in the evidence span; do not borrow distant context.
  Do not add qualified mentions as aliases of the core concept.
  Use Pathway for a standalone biological process and Disease for a named disease.
  If the chunk only says "isolate Z" or a symptom, keep that source wording;
  do not invent an absent species prefix or equate a symptom to a disease.
- A tested mixture is ONE treatment entity with the complete combination name,
  not an ingredient's alias. Use Product for a combined formulation, preserving
  every named component and connector from the source. Use the combination as
  the efficacy edge's source; ingredient-only findings remain separate.
  Co-mention of two independently tested treatments is NOT a mixture.
  A synergizes_with edge is only for an explicitly tested more-than-additive
  interaction; it does not replace the mixture's controls/inhibits finding.
- Keep each tested population, endpoint and treatment arm separate. Extract
  explicit ineffective findings and measured nulls as well as positive results.
  Choose polarity for that exact finding, not from a different dose or trial.
  A comparison between two effective treatments does not mean no_effect versus
  an untreated control. Resistance uses resistant_to, not controls.

Invented mini-examples (not study evidence; only extract the real chunk):
Input: Agent A reduced growth of Fungus alpha isolate Z in vitro.
Output: Agent A --inhibits--> Fungus alpha (Pathogen), qualifiers:
{"polarity":"supports","object_form_or_variant_qualifier":"isolate Z",
 "object_aspect_qualifier":"growth","study_context":"in vitro"}.
Input: In the cage assay, Agent A did not reduce Moth beta oviposition.
Output: Agent A --inhibits--> Moth beta (Pest), qualifiers:
{"polarity":"no_effect","object_aspect_qualifier":"oviposition",
 "study_context":"cage assay"}.
Input: Agent A suppressed ryegrass in the susceptible population.
In the resistant population, Agent A was ineffective against ryegrass.
Output: two Agent A --controls--> ryegrass (Weed) statements, qualifiers
{"polarity":"supports","population_context_qualifier":"susceptible population"} and
{"polarity":"no_effect","population_context_qualifier":"resistant population"}.
Input: Agent A controlled Moth beta larvae. Testing Moth beta adults found
no significant difference in mortality relative to untreated cages.
Output: two Agent A --controls--> Moth beta (Pest) statements, qualifiers
{"polarity":"supports","object_form_or_variant_qualifier":"larvae"} and
{"polarity":"no_effect","object_form_or_variant_qualifier":"adults",
 "object_aspect_qualifier":"mortality"}.
Input: Bacterium gamma strain K did not significantly control leaf spot disease.
Output: Bacterium gamma --controls--> leaf spot disease (Disease), qualifiers
{"polarity":"no_effect","subject_form_or_variant_qualifier":"strain K"}.
Keep the named disease; do not substitute its causal organism.
Input: Agent A + Adjuvant B controlled R ryegrass population; Agent A alone
was ineffective against R ryegrass population.
Output: Agent A + Adjuvant B (Product) --controls--> ryegrass (Weed),
{"polarity":"supports","population_context_qualifier":"R population"};
Agent A (ActiveIngredient) --controls--> ryegrass (Weed),
{"polarity":"no_effect","population_context_qualifier":"R population"}.
Do not infer synergy or transfer mixture efficacy to Agent A.
Input: Contrary to earlier accounts, Agent A does not control Moth beta.
Output: Agent A --controls--> Moth beta (Pest),
{"polarity":"refutes"}.
Input: The introduction describes Agent A as controlling Moth beta.
In the orchard trial, mortality after Agent A treatment was statistically
indistinguishable from mortality among untreated Moth beta.
Output: Agent A --controls--> Moth beta (Pest),
{"polarity":"supports","study_context":"background"} and
{"polarity":"no_effect","study_context":"orchard trial",
 "object_aspect_qualifier":"mortality"}.
The background statement may instead be skipped; the trial null must remain.
"""


def _extractable(schema: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """The part of a schema the model may produce: interpretation-overlay
    entity types are curated by people, and so is any relation touching one."""
    entity_types = [et for et in schema["entity_types"] if et.get("extractable", True)]
    curated = {et["name"] for et in schema["entity_types"]} - {et["name"] for et in entity_types}
    relation_types = [
        rt for rt in schema["relation_types"]
        if rt.get("extractable", True)
        and rt["domain_type"] not in curated and rt["range_type"] not in curated
    ]
    return entity_types, relation_types


def _schema_block(schema: dict[str, Any]) -> str:
    entity_types, relation_types = _extractable(schema)
    lines = ["Entity types:"]
    for et in entity_types:
        attrs = ""
        if et["attributes"]:
            attrs = f" Attributes: {json.dumps(et['attributes'])}"
        parent = f" (is-a {et['parent']})" if et.get("parent") else ""
        lines.append(f"- {et['name']}: {et['description']}{parent}{attrs}")
    lines.append("Relation types:")
    for rt in relation_types:
        domain = rt["domain_type"]
        range_ = rt["range_type"]
        qualifiers = rt.get("qualifiers", {})
        lines.append(
            f"- {rt['name']}: {rt['description']} (source type: {domain}, "
            f"target type: {range_}; '*' means any; qualifiers: "
            f"{json.dumps(qualifiers, sort_keys=True)})"
        )
    return "\n".join(lines)


def _rejected_feedback_block(rejected: list[dict[str, Any]] | None) -> str:
    """Render recent human rejections as a negative-examples section.

    The review→extract feedback loop: rows come from
    ``KGStore.rejected_extraction_feedback`` (status='rejected', newest
    first). An empty list renders nothing — a first-run graph has no
    rejections to teach from, and an empty section header would only
    invite the model to hallucinate one.
    """
    if not rejected:
        return ""
    lines = [
        "Previously rejected extractions (do NOT re-propose these or "
        "near-duplicates):"
    ]
    for row in rejected:
        note = (row.get("review_note") or "").strip()
        suffix = f" — {note}" if note else ""
        lines.append(
            f"- {row['type_name']} {row['label']!r} ({row['kind']}){suffix}"
        )
    return "\n".join(lines) + "\n\n"


def build_extraction_prompt(
    schema: dict[str, Any],
    chunk_text: str,
    rejected: list[dict[str, Any]] | None = None,
) -> str:
    """Build the extraction prompt for one document chunk.

    Embeds the active ontology schema and the chunk between explicit
    <document-chunk> markers, and pins the exact JSON output contract.
    ``rejected`` is the review→extract feedback: human-rejected proposals
    rendered as negative examples so the same artifact class is not
    re-proposed on the next document.
    """
    agrochem_guidance = (
        _MULTI_ARM_GUIDANCE + "\n" + _AGROCHEM_GUIDANCE
        if schema.get("schema_label", schema.get("label")) == "agrochem-v2"
        else ""
    )
    return f"""You are an information-extraction engine. Extract entities and relations \
from the document chunk below, strictly following the ontology schema.

{_schema_block(schema)}

{_rejected_feedback_block(rejected)}Rules:
1. Return EXACTLY ONE JSON object and nothing else; a single ```json fence is also accepted.
2. The JSON shape is {{"entities": [...], "relations": [...]}}.
3. Each entity: name, entity_type (one of the schema types), aliases (list),
   properties (only attribute keys declared for its type), confidence (0..1),
   source_span {{"start": int, "end": int}} — character offsets INTO THE CHUNK
   TEXT BELOW (0 = first character of the chunk) covering the mention.
4. Each relation references its endpoints by {{"name": ..., "entity_type": ...}}
   of entities you emitted — never by array index, never by an invented id;
   qualifiers is an object containing only qualifiers declared for its type.
   If the relation type declares a "polarity" qualifier, always set it:
   apply the polarity precedence below to that assertion, not to another arm.
5. Only extract facts stated in the chunk. Do not use outside knowledge.
6. If nothing is extractable, return {{"entities": [], "relations": []}}.

{_POLARITY_GUIDANCE}

<background-separation>
{_BACKGROUND_GUIDANCE}</background-separation>

{agrochem_guidance}

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

    Token boundaries are required: without them 'CAT' grounds inside
    'concatenate' and the citation asserts evidence that is not there.
    """
    match = re.search(
        r"(?<![0-9A-Za-z])" + re.escape(surface) + r"(?![0-9A-Za-z])",
        chunk_text,
        re.IGNORECASE,
    )
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
    start = offsets[pos]
    end = offsets[pos + len(target) - 1] + 1
    # Same token-boundary rule as the regex path: the skeleton strips
    # punctuation, so check the ORIGINAL text's neighbours instead —
    # otherwise 'CAT' still grounds inside 'concatenate' via the skeleton.
    if start > 0 and re.match(r"[0-9A-Za-z]", chunk_text[start - 1]):
        return None
    if end < len(chunk_text) and re.match(r"[0-9A-Za-z]", chunk_text[end]):
        return None
    return SourceSpan(start=start, end=end)


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


def _qualifier_value_matches_type(value: Any, expected: str) -> bool:
    if expected == "string":
        return isinstance(value, str) and bool(value.strip())
    if expected == "boolean":
        return isinstance(value, bool)
    if expected == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if expected == "array":
        return isinstance(value, list)
    if expected == "object":
        return isinstance(value, dict)
    return False


def _validate_relation_qualifiers(
    raw: Any, specs: Any, *, relation_index: int, relation_type: str
) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise EngineError(
            f"relation[{relation_index}] {relation_type}: qualifiers must be an object"
        )
    if not isinstance(specs, dict):
        raise EngineError(
            f"relation[{relation_index}] {relation_type}: schema qualifiers malformed"
        )
    for name, value in raw.items():
        spec = specs.get(name)
        if not isinstance(spec, dict):
            raise EngineError(
                f"relation[{relation_index}] {relation_type}: undeclared qualifier "
                f"{name!r}"
            )
        expected = spec.get("type", "string")
        if not isinstance(expected, str) or not _qualifier_value_matches_type(
            value, expected
        ):
            raise EngineError(
                f"relation[{relation_index}] {relation_type}: qualifier {name!r} "
                f"must be a non-empty {expected}"
            )
        enum = spec.get("enum")
        if enum is not None and (not isinstance(enum, list) or value not in enum):
            raise EngineError(
                f"relation[{relation_index}] {relation_type}: qualifier {name!r} "
                f"value {value!r} is outside its enum"
            )
        if isinstance(value, str):
            minimum = spec.get("minLength")
            maximum = spec.get("maxLength")
            pattern = spec.get("pattern")
            if isinstance(minimum, int) and len(value) < minimum:
                raise EngineError(
                    f"relation[{relation_index}] {relation_type}: qualifier "
                    f"{name!r} is shorter than minLength {minimum}"
                )
            if isinstance(maximum, int) and len(value) > maximum:
                raise EngineError(
                    f"relation[{relation_index}] {relation_type}: qualifier "
                    f"{name!r} is longer than maxLength {maximum}"
                )
            if isinstance(pattern, str) and re.fullmatch(pattern, value) is None:
                raise EngineError(
                    f"relation[{relation_index}] {relation_type}: qualifier "
                    f"{name!r} does not match its pattern"
                )
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            minimum = spec.get("minimum")
            maximum = spec.get("maximum")
            if isinstance(minimum, (int, float)) and value < minimum:
                raise EngineError(
                    f"relation[{relation_index}] {relation_type}: qualifier "
                    f"{name!r} is below minimum {minimum}"
                )
            if isinstance(maximum, (int, float)) and value > maximum:
                raise EngineError(
                    f"relation[{relation_index}] {relation_type}: qualifier "
                    f"{name!r} is above maximum {maximum}"
                )
    missing = [
        name
        for name, spec in specs.items()
        if isinstance(spec, dict) and spec.get("required") and name not in raw
    ]
    if missing:
        raise EngineError(
            f"relation[{relation_index}] {relation_type}: missing required "
            f"qualifiers {sorted(missing)}"
        )
    return dict(raw)


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

    extractable_entities, extractable_relations = _extractable(schema)
    entity_types = {et["name"]: et for et in extractable_entities}
    relation_types = {rt["name"]: rt for rt in extractable_relations}
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
        if not isinstance(etype, str) or etype not in entity_types:
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

        if aliases:
            # 4C/D11: parser-minted aliases are model_unattested; they can
            # never mint registry identity downstream, and any model-supplied
            # alias_authority property was already dropped as off-schema.
            properties.setdefault(
                "alias_authority",
                {alias: "model_unattested" for alias in aliases},
            )

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
            existing.properties.setdefault(
                "alias_authority",
                {alias: "model_unattested" for alias in existing.aliases},
            )
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
        if not isinstance(ref_type, str) or ref_type not in entity_types:
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
        if not isinstance(rtype, str):
            warnings.append(
                f"relation[{i}]: unknown relation_type {rtype!r}; rejected"
            )
            continue
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

        qualifiers = _validate_relation_qualifiers(
            raw_rel.get("qualifiers", {}),
            rt_spec.get("qualifiers", {}),
            relation_index=i,
            relation_type=rtype,
        )
        relations.append(
            ProposedRelation(
                id=uuid.uuid4().hex,
                relation_type=rtype,
                src_entity_id=src.id,
                dst_entity_id=dst.id,
                qualifiers=qualifiers,
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


def stamp_alias_authority(entity):
    """Expose the 4C classification as a pure boundary function (D11).

    Parser-minted aliases default to model_unattested; an existing
    classification (registry_supplied, human_asserted) is never overridden.
    The run_extraction parse path applies this inline; this function is the
    testable seam for the same rule.
    """
    if entity.aliases:
        entity.properties.setdefault(
            "alias_authority",
            {alias: "model_unattested" for alias in entity.aliases},
        )
    return entity


async def run_extract_job(
    store: Any,
    *,
    engine: Any,
    engine_name: str | None,
    model: str | None,
    job_dir: Path,
    seed: int,
    doc_ids: list[str] | None,
    max_engine_calls: int,
    time_budget: float | None,
    decode_params: dict[str, Any] | None,
    on_progress: Callable[[str], None],
    on_stats: Callable[[dict[str, int]], None],
    should_abort: Callable[[], str] | None,
    max_transport_retries: int = DEFAULT_MAX_TRANSPORT_RETRIES,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> ExtractionOutcome:
    provenance = Provenance(str(job_dir), seed=seed)
    effective_model = effective_extractor_model(engine, model)
    ids = list(doc_ids or ()) or extraction_doc_ids(store)
    # The direct entries refuse named abstract-only documents before a job
    # exists; this is the seam both of them and the unnamed "every document"
    # expansion pass through, so nothing without full text reaches the
    # engine from here either. Unknown ids stay in the list and fail loudly
    # in run_extraction as they always did.
    skipped = [
        verdict
        for verdict in extraction_eligibilities(store.conn, ids)
        if verdict.code == NOT_FULL_TEXT
    ]
    if skipped:
        blocked = {verdict.document_id for verdict in skipped}
        ids = [doc_id for doc_id in ids if doc_id not in blocked]
        on_progress(f"[ontologylab] skipped: {refusal_message(skipped)}")
        provenance.log(
            "extract.skipped",
            {
                "doc_ids": sorted(blocked),
                "reason": NOT_FULL_TEXT,
            },
        )
    if not ids:
        return ExtractionOutcome("")
    if time_budget is None:
        # One initial request, one parse retry, and N transport retries per
        # chunk share the same spend cap (including its reserve slots).
        # Account for bounded waits too; explicit wall limits stay binding.
        chunk_count = sum(
            len(chunk_document(store.document_raw_text(doc_id))) for doc_id in ids
        )
        request_slots = (2 + max_transport_retries) * chunk_count
        if max_engine_calls:
            request_slots = min(request_slots, max_engine_calls)
        request_timeout = getattr(engine, "_timeout_s", _DEFAULT_TIMEOUT_S)
        time_budget = provenance.elapsed_s + request_slots * (
            request_timeout * 1.1 + MAX_TRANSPORT_BACKOFF_S
        )
        provenance.log("extract.budget", {
            "chunks": chunk_count,
            "request_slots": request_slots,
            "request_timeout_s": request_timeout,
            "time_budget_s": time_budget,
            "max_engine_calls": max_engine_calls,
            "max_transport_retries": max_transport_retries,
        })
    caps = Caps(SimpleNamespace(
        iterations=0,
        time_budget_s=time_budget,
        max_engine_calls=max_engine_calls,
        max_transport_retries=max_transport_retries,
    ))
    provenance.log(
        "extract.start",
        {
            "engine": engine_name,
            "model": effective_model,
            "decode_params": decode_params,
            "doc_ids": ids,
        },
    )
    totals = dict.fromkeys(TOTALS_KEYS, 0)

    def _accumulate(stats: dict[str, int]) -> None:
        for key in totals:
            totals[key] += stats.get(key, 0)
        on_stats(stats)

    stopped_reason = await run_extraction(
        store,
        engine,
        provenance,
        caps,
        ids,
        extractor_engine=engine_name or "",
        extractor_model=effective_model,
        on_progress=on_progress,
        on_stats=_accumulate,
        should_abort=should_abort,
        decode_params=decode_params,
        sleep=sleep,
    )
    provenance.log("extract.end", {"totals": totals, "stopped": stopped_reason})
    # Merge reflux: extraction just minted new proposed nodes, so the
    # duplicate queue is stale until it is rescanned. Running it here — the
    # shared CLI/worker completion point — means the merge queue reflects
    # this run without a separate manual `merge-scan`. Fail-open: a scan
    # error must not fail a completed extraction.
    try:
        from ontologylab.merge import scan_merge_candidates

        merge_stats = scan_merge_candidates(store)
        provenance.log("extract.merge_scan", merge_stats)
    except Exception as exc:  # noqa: BLE001 — advisory scan, never fatal
        provenance.log("extract.merge_scan_error", {"error": str(exc)})
    return stopped_reason


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
    receipt_sets: dict[str, Any] | None = None,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> ExtractionOutcome:
    """Extract every chunk and return its stop reason and failure outcome.

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
    nothing. A parse failure gets one counted retry; transient transports
    get at most N additional requests per chunk, not N per parse attempt.
    All attempts pass the same cap and accounting boundary.
    """
    schema = store.get_schema()
    # Review→extract feedback: human rejections become negative examples in
    # every prompt this run emits. Fetched once — the run's job is to learn
    # from the queue as it stood at start, not to chase live edits.
    rejected_feedback = store.rejected_extraction_feedback()
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

    stopped_reason = ""
    abort_triggered = False
    chunk_failed = False
    max_transport_retries = getattr(
        caps.config, "max_transport_retries", DEFAULT_MAX_TRANSPORT_RETRIES
    )
    with ExtractionState(store.conn) as lifecycle:
        active_run_id: str | None = None
        try:
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
                if plan.status not in {"complete", "cancelled"}:
                    active_run_id = plan.run_id
                provenance.log(
                    "extract.doc", {"doc_id": doc_id, "chunks": len(chunks)}
                )
                if active_run_id is None:
                    continue
                for chunk in chunks:
                    if chunk.index not in plan.retryable:
                        continue
                    prompt = build_extraction_prompt(
                        schema, chunk.text, rejected=rejected_feedback
                    )
                    result = None
                    error_kind = ""
                    attempts = 0
                    parse_failures = 0
                    transport_retries = 0
                    retry_delay = 0.0
                    while parse_failures < 2:
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
                        if retry_delay:
                            provenance.log("extract.transport_retry", {
                                "doc_id": doc_id, "chunk": chunk.index,
                                "retry": transport_retries, "delay_s": retry_delay,
                            })
                            await sleep(retry_delay)
                            retry_delay = 0.0
                            # Backoff can cross the wall cap or cancellation.
                            continue
                        if attempts == 0 and not lifecycle.claim(
                            plan.run_id, chunk.index
                        ):
                            break
                        attempts += 1
                        usage = {"error": "engine_error"}
                        started = time.monotonic()
                        try:
                            try:
                                if isinstance(engine, ApiEngine):
                                    raw_response, usage = await engine.generate(
                                        prompt, model=extractor_model, expects_json=True
                                    )
                                else:
                                    raw_response, usage = await engine.generate(
                                        prompt, model=extractor_model
                                    )
                            finally:
                                provenance.track_engine_call(
                                    "extract", time.monotonic() - started, usage
                                )
                        except EngineError as exc:
                            error_kind = "engine_error"
                            provenance.log(
                                "extract.engine_error",
                                {
                                    "doc_id": doc_id,
                                    "chunk": chunk.index,
                                    "error": str(exc),
                                    "type": type(exc).__name__,
                                },
                            )
                            on_progress(
                                f"[ontologylab] engine error on "
                                f"{doc_id}#{chunk.index}: {ENGINE_FAILURE_SUMMARY}"
                            )
                            if (
                                isinstance(exc, TransientEngineError)
                                and transport_retries < max_transport_retries
                            ):
                                retry_delay = min(
                                    MAX_TRANSPORT_BACKOFF_S,
                                    max(2.0 ** min(transport_retries, 3), exc.retry_after_s),
                                )
                                transport_retries += 1
                                continue
                            break
                        try:
                            result = parse_and_validate_extraction(
                                raw_response, schema, chunk
                            )
                        except EngineError as exc:
                            error_kind = "parse_rejected"
                            parse_failures += 1
                            provenance.log(
                                "extract.parse_rejected",
                                {
                                    "doc_id": doc_id,
                                    "chunk": chunk.index,
                                    "error": str(exc),
                                },
                            )
                            continue
                        break
                    if result is None and error_kind:
                        lifecycle.failed(plan.run_id, chunk.index, error_kind)
                        chunk_failed = True
                    if stopped_reason:
                        break
                    if result is None:
                        continue
                    for warning in result.warnings:
                        provenance.log(
                            "extract.warning",
                            {
                                "doc_id": doc_id,
                                "chunk": chunk.index,
                                "warning": warning,
                            },
                        )
                    try:
                        if schema.get("schema_label") == "agrochem-v2":
                            split_grounded_variants(result.entities, result.relations, raw_text)
                        for entity in result.entities:
                            resolve_species_abbreviation(entity, raw_text)
                            if registry is not None:
                                normalize_proposal(entity, registry)
                            if cas_registry is not None:
                                normalize_proposal(
                                    entity, cas_registry, moa_registry
                                )
                            normalize_measurement(entity)
                        # 4C: alias_authority is parse-time metadata for the
                        # normalization boundary - strip it before storage so
                        # persisted properties keep their pre-4C shape (the
                        # durable record is the resolution flags).
                        for entity in result.entities:
                            entity.properties.pop("alias_authority", None)
                        # Refuse individual model proposals at the same strict
                        # boundary as insert_proposed, before any writes. Keep
                        # genuine store/transaction failures fatal.
                        sv_id = schema["schema_version_id"]
                        definition = store._schema_definition(sv_id)
                        accepted_entities = []
                        entity_types = {}
                        for entity in result.entities:
                            try:
                                store._validate_properties(
                                    schema_version_id=sv_id,
                                    entity_type=entity.entity_type,
                                    properties=entity.properties,
                                    schema=definition,
                                )
                            except SchemaValidationError as exc:
                                provenance.log(
                                    "extract.proposal_rejected",
                                    {
                                        "doc_id": doc_id, "chunk": chunk.index,
                                        "kind": "entity", "id": entity.id,
                                        "name": entity.name,
                                        "type": type(exc).__name__,
                                        "reason": "schema_validation",
                                        "error": str(exc),
                                    },
                                )
                                continue
                            accepted_entities.append(entity)
                            entity_types[entity.id] = entity.entity_type
                        accepted_relations = []
                        for relation in result.relations:
                            reason = "schema_validation"
                            try:
                                if (
                                    relation.src_entity_id not in entity_types
                                    or relation.dst_entity_id not in entity_types
                                ):
                                    reason = "rejected_endpoint"
                                    raise SchemaValidationError(
                                        "relation references a rejected entity"
                                    )
                                store._validate_relation(
                                    schema_version_id=sv_id,
                                    relation_type=relation.relation_type,
                                    src_type=entity_types[relation.src_entity_id],
                                    dst_type=entity_types[relation.dst_entity_id],
                                    properties=relation.properties,
                                    qualifiers=relation.qualifiers,
                                    schema=definition,
                                )
                            except SchemaValidationError as exc:
                                provenance.log(
                                    "extract.proposal_rejected",
                                    {
                                        "doc_id": doc_id, "chunk": chunk.index,
                                        "kind": "relation", "id": relation.id,
                                        "type": type(exc).__name__,
                                        "reason": reason, "error": str(exc),
                                    },
                                )
                                continue
                            accepted_relations.append(relation)
                        rejected_counts = {
                            "entities_rejected": len(result.entities) - len(accepted_entities),
                            "relations_rejected": len(result.relations) - len(accepted_relations),
                        }
                        if any(rejected_counts.values()):
                            # Refusals already happened, even if a later
                            # store write fails. Count them exactly once.
                            on_stats(dict.fromkeys(TOTALS_KEYS, 0) | rejected_counts)
                        result.entities = accepted_entities
                        result.relations = accepted_relations
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
                        # Bind citations to THIS run's receipts when the
                        # caller supplied them. Without the explicit ids the
                        # binder resolves a chunk by (representation, index,
                        # offset) alone, which is ambiguous once a second
                        # extraction run covers the same span — re-extracting
                        # a representation under a new model made every
                        # citation refuse as "multiple extraction chunks".
                        receipt_set = (
                            (receipt_sets or {}).get(doc_id)
                        )
                        run_receipt_id = None
                        chunk_receipt_id = None
                        if receipt_set is not None:
                            run_receipt_id = receipt_set.run.receipt_id
                            for cr in receipt_set.chunks:
                                if cr.chunk_index == chunk.index:
                                    chunk_receipt_id = cr.receipt_id
                                    break
                        persist_chunk_citations(
                            store.conn,
                            ChunkCitationBatch(
                                representation_id=doc_id,
                                chunk_index=chunk.index,
                                chunk_start_offset=chunk.char_offset,
                                entities=tuple(result.entities),
                                relations=tuple(result.relations),
                                id_map={
                                    str(key): str(value)
                                    for key, value in stats["id_map"].items()
                                },
                                run_receipt_id=run_receipt_id,
                                chunk_receipt_id=chunk_receipt_id,
                            ),
                        )
                        lifecycle.succeeded(
                            plan.run_id, chunk.index, stats | rejected_counts
                        )
                    except Exception:
                        lifecycle.failed(plan.run_id, chunk.index, "write_error")
                        raise
                    on_stats(stats)
                    on_progress(
                        f"[ontologylab] {doc_id}#{chunk.index}: "
                        f"+{stats['nodes_new']} nodes "
                        f"(+{stats['nodes_merged']} merged), "
                        f"+{stats['edges_new']} edges"
                    )
                lifecycle.finish(plan.run_id, cancelled=abort_triggered)
                active_run_id = None
                if stopped_reason:
                    break
        finally:
            if active_run_id is not None:
                lifecycle.finish(active_run_id)
    return ExtractionOutcome(stopped_reason, chunk_failed=chunk_failed)
