"""W8 critic-model triage: a second engine pre-scores proposed extractions.

The critic reads each ``proposed`` node/edge together with the source-span
evidence it was extracted from, and returns an advisory plausibility score
in 0..1 (1 = the evidence clearly supports the extraction). Scores land in
``critic_reviews`` where the review queue uses them for **sorting and
disagreement flags only**.

Hard boundaries (anchoring-bias guard, per the HITL research):

- the critic NEVER approves or rejects anything — there is no code path
  from a score to a status change;
- the UI must not pre-select a decision from a score (no pre-checked
  approve buttons);
- a failed critic call fails open: the queue simply stays unsorted for the
  items that got no score.
"""

from __future__ import annotations

import json
from typing import Any, Optional

from ontologylab.engines import (
    CRITIC_MARKER_CLOSE,
    CRITIC_MARKER_OPEN,
    EngineError,
    extract_fenced_block,
)
from ontologylab.kgstore import (
    SPAN_EXCERPT_CONTEXT_CHARS,
    SPAN_EXCERPT_MAX_CHARS,
    KGStore,
    KGStoreError,
    span_excerpt,
)
from ontologylab.paths import CRITIC_MODEL

CRITIC_PROMPT_VERSION = "critic-v1"

# Evidence excerpt window: same definition the review views use.
EVIDENCE_CONTEXT_CHARS = SPAN_EXCERPT_CONTEXT_CHARS
MAX_EVIDENCE_CHARS = SPAN_EXCERPT_MAX_CHARS
DEFAULT_BATCH_SIZE = 20

# The critic runs on the claude engine under this registered name; only it
# gets the cheap CRITIC_MODEL default (other engines resolve their own).
_CLAUDE_ENGINE_NAME = "claude"


def resolve_critic_model(engine_name: str, explicit: Optional[str]) -> Optional[str]:
    """Pick the model the critic should score on.

    The critic is advisory triage (it sorts the queue and flags disagreements,
    never approves), so the claude engine defaults to the cheaper Haiku-class
    ``CRITIC_MODEL`` tier instead of the extraction anchor model. An explicit
    model always wins; non-claude engines are unaffected and resolve their own
    default (``None`` here means "use the engine's own default").
    """
    if explicit:
        return explicit
    if engine_name == _CLAUDE_ENGINE_NAME:
        return CRITIC_MODEL
    return None


def build_critic_prompt(items: list[dict[str, Any]]) -> str:
    """Build the critic prompt for one batch of items.

    Each item carries ``id``, ``kind``, ``type``, ``label``, ``confidence``
    and ``evidence`` (the cited source excerpt, possibly empty).
    """
    payload = json.dumps(items, indent=2, ensure_ascii=False)
    return f"""You are a second-opinion reviewer for knowledge-graph extractions. \
For each item below, score how well the cited evidence supports the extraction.

You are ADVISORY ONLY: your scores sort a human review queue. You approve
nothing; a human makes every accept/reject decision.

Scoring guide (0.0 - 1.0):
- 1.0: evidence explicitly states the entity/relation as extracted
- 0.7: evidence supports it with minor interpretation
- 0.4: evidence is related but does not establish the extraction
- 0.1: evidence contradicts it, or the label looks like an extraction
  artifact (fragment, formatting noise, hallucinated surface form)

Rules:
1. Return EXACTLY ONE fenced ```json block and nothing else.
2. The JSON is an array of objects {{"id": "<item id>", "score": <0..1>,
   "rationale": "<one short sentence>"}} — one per input item, same ids.
3. Judge ONLY evidence support. Ignore how confident the extractor was.

{CRITIC_MARKER_OPEN}
{payload}
{CRITIC_MARKER_CLOSE}"""


def parse_critic(raw_text: str, expected_ids: set[str]) -> dict[str, dict[str, Any]]:
    """Parse critic output into ``{item_id: {score, rationale}}``.

    Unknown ids and malformed entries are dropped; scores clamp to 0..1.
    Raises EngineError only when the payload as a whole is unparseable.
    """
    block = extract_fenced_block(raw_text, lang="json")
    try:
        data = json.loads(block)
    except json.JSONDecodeError as exc:
        raise EngineError(f"critic output is not valid JSON: {exc}") from exc
    if not isinstance(data, list):
        raise EngineError("critic output is not a JSON array")
    out: dict[str, dict[str, Any]] = {}
    for entry in data:
        if not isinstance(entry, dict):
            continue
        item_id = entry.get("id")
        score = entry.get("score")
        if item_id not in expected_ids or not isinstance(score, (int, float)):
            continue
        out[item_id] = {
            "score": min(1.0, max(0.0, float(score))),
            "rationale": (
                str(entry["rationale"])[:500] if entry.get("rationale") else None
            ),
        }
    return out


def _evidence_excerpt(raw_text: str, span: dict | None) -> str:
    """The cited span ± context, marked with >>> <<< around the span."""
    return span_excerpt(
        raw_text,
        span,
        context_chars=EVIDENCE_CONTEXT_CHARS,
        max_chars=MAX_EVIDENCE_CHARS,
    )


def _pending_items(
    store: KGStore,
    *,
    engine_name: str,
    limit: int,
    docs_unloadable: Optional[set[str]] = None,
) -> list[dict]:
    """Proposed nodes/edges that this critic has not scored yet.

    ``docs_unloadable`` (optional out-parameter): any doc_id whose source
    text could not be loaded is added to this set. Such items still get an
    item with **empty** evidence (fail-open — a document read failure must
    not crash the run), but the caller can surface the degradation instead
    of silently scoring against blank context.
    """
    doc_text_cache: dict[str, str] = {}

    def doc_text(doc_id: str) -> str:
        if doc_id not in doc_text_cache:
            try:
                doc_text_cache[doc_id] = store.document_raw_text(doc_id)
            except (KGStoreError, OSError):
                # Narrow to the real failure modes of document_raw_text:
                # UnknownItem (a KGStoreError) for a missing row, OSError for
                # an unreadable/missing raw-text file. Record the doc_id so
                # the empty-evidence fallback is visible, not silent.
                doc_text_cache[doc_id] = ""
                if docs_unloadable is not None:
                    docs_unloadable.add(doc_id)
        return doc_text_cache[doc_id]

    items: list[dict] = []
    node_rows = store.conn.execute(
        "SELECT n.* FROM nodes n WHERE n.status = 'proposed' AND NOT EXISTS "
        "(SELECT 1 FROM critic_reviews c WHERE c.kind = 'node' "
        " AND c.item_id = n.id AND c.engine = ? AND c.prompt_version = ?) "
        "ORDER BY n.created_ts ASC LIMIT ?",
        (engine_name, CRITIC_PROMPT_VERSION, limit),
    ).fetchall()
    for row in node_rows:
        span = json.loads(row["source_span"]) if row["source_span"] else None
        items.append(
            {
                "id": row["id"],
                "kind": "node",
                "type": row["entity_type"],
                "label": row["name"],
                "confidence": row["confidence"],
                "evidence": _evidence_excerpt(doc_text(row["source_doc_id"]), span),
            }
        )
    remaining = limit - len(items)
    if remaining > 0:
        edge_rows = store.conn.execute(
            "SELECT e.*, s.name AS src_name, d.name AS dst_name FROM edges e "
            "JOIN nodes s ON s.id = e.src_node_id "
            "JOIN nodes d ON d.id = e.dst_node_id "
            "WHERE e.status = 'proposed' AND NOT EXISTS "
            "(SELECT 1 FROM critic_reviews c WHERE c.kind = 'edge' "
            " AND c.item_id = e.id AND c.engine = ? AND c.prompt_version = ?) "
            "ORDER BY e.created_ts ASC LIMIT ?",
            (engine_name, CRITIC_PROMPT_VERSION, remaining),
        ).fetchall()
        for row in edge_rows:
            span = json.loads(row["source_span"]) if row["source_span"] else None
            items.append(
                {
                    "id": row["id"],
                    "kind": "edge",
                    "type": row["relation_type"],
                    "label": (
                        f"{row['src_name']} -[{row['relation_type']}]-> "
                        f"{row['dst_name']}"
                    ),
                    "confidence": row["confidence"],
                    "evidence": _evidence_excerpt(
                        doc_text(row["source_doc_id"]), span
                    ),
                }
            )
    return items


async def critic_review(
    store: KGStore,
    engine,
    *,
    model: Optional[str] = None,
    limit: int = 200,
    batch_size: int = DEFAULT_BATCH_SIZE,
) -> dict[str, Any]:
    """Score pending proposed items with ``engine``; store advisory reviews.

    Fails open per batch: an engine/parse failure skips that batch (logged
    in the returned stats) and never raises out of the loop.
    """
    engine_name = engine.name() if hasattr(engine, "name") else str(engine)
    docs_unloadable: set[str] = set()
    items = _pending_items(
        store, engine_name=engine_name, limit=limit, docs_unloadable=docs_unloadable
    )
    stats: dict[str, Any] = {
        "candidates": len(items),
        "scored": 0,
        "disagreements": 0,
        "batches_failed": 0,
        # doc_ids whose source text failed to load: their items were scored
        # against empty evidence (fail-open). Non-empty = degraded run.
        "docs_unloadable": sorted(docs_unloadable),
        "errors": [],
    }
    for start in range(0, len(items), batch_size):
        batch = items[start : start + batch_size]
        prompt = build_critic_prompt(batch)
        try:
            raw_text, _usage = await engine.generate(prompt, model=model)
            reviews = parse_critic(raw_text, {i["id"] for i in batch})
        except Exception as exc:
            stats["batches_failed"] += 1
            stats["errors"].append(str(exc))
            continue
        by_id = {i["id"]: i for i in batch}
        for item_id, review in reviews.items():
            item = by_id[item_id]
            store.record_critic_review(
                item["kind"],
                item_id,
                engine=engine_name,
                model=model,
                prompt_version=CRITIC_PROMPT_VERSION,
                score=review["score"],
                rationale=review["rationale"],
            )
            stats["scored"] += 1
            conf = item["confidence"]
            if (
                conf is not None
                and abs(conf - review["score"])
                >= KGStore.CRITIC_DISAGREEMENT_THRESHOLD
            ):
                stats["disagreements"] += 1
    return stats


__all__ = [
    "CRITIC_PROMPT_VERSION",
    "build_critic_prompt",
    "parse_critic",
    "critic_review",
]
