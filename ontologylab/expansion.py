"""LLM query expansion for tier-2 search (fail-open, honest labeling).

Design intent: lexical FTS5/BM25 search stays the primary tier. An LLM
optionally expands a query with short lexical variants (synonyms, aliases,
split/joined compound-word forms); the caller composes them into the same
FTS5 MATCH as ``" ".join([query, *variants])`` — kgstore is untouched.
Expansion NEVER gates search: any engine or parse failure fails open to the
plain lexical query, surfaced via an ``"error"`` key in the returned usage
dict. This is query expansion, not vector/embedding search — embeddings
remain an explicitly deferred, opt-in external backend.
"""

from __future__ import annotations

import json
from typing import Optional

from ontologylab.engines import (
    QUERY_MARKER_CLOSE,
    QUERY_MARKER_OPEN,
    EngineError,
    extract_fenced_block,
)

EXPANSION_PROMPT_VERSION = "expand-v1"

MAX_VARIANTS = 8
MAX_VARIANT_LEN = 50


def build_expansion_prompt(query: str) -> str:
    """Build the query-expansion prompt.

    Embeds the query between explicit <query-expansion> markers and pins
    the exact JSON output contract (one fenced json array of strings).
    """
    return f"""You are a search-query expansion engine for a lexical (FTS5/BM25) \
knowledge-graph search. Produce short lexical variants of the query below to \
improve recall.

Rules:
1. Return EXACTLY ONE fenced ```json block and nothing else.
2. The JSON is a flat array of at most {MAX_VARIANTS} short strings — strings
   only, no objects, no explanations.
3. Each variant is a short lexical variant of the query: a synonym, an alias,
   a split or joined compound-word form (e.g. "rate limiter" <-> "ratelimiter"
   <-> "RateLimiter"), or a closely related technical term.
4. Prefer domain-neutral technical variants. NEVER invent product names.
5. Return an empty array [] if nothing useful can be added.

{QUERY_MARKER_OPEN}
{query}
{QUERY_MARKER_CLOSE}"""


def parse_expansion(raw_text: str, original_query: str) -> list[str]:
    """Parse engine output into a validated list of expansion variants.

    Expects one fenced json block containing a flat array of strings.
    Strips items; drops empties, items longer than ``MAX_VARIANT_LEN``,
    and casefold-duplicates of each other or of ``original_query``; caps
    at ``MAX_VARIANTS``. Raises EngineError on unparseable output.
    """
    block = extract_fenced_block(raw_text, lang="json")
    try:
        data = json.loads(block)
    except json.JSONDecodeError as exc:
        raise EngineError(f"expansion output is not valid JSON: {exc}") from exc
    if not isinstance(data, list) or not all(isinstance(x, str) for x in data):
        raise EngineError("expansion output is not a JSON array of strings")

    seen = {original_query.strip().casefold()}
    variants: list[str] = []
    for item in data:
        term = item.strip()
        if not term or len(term) > MAX_VARIANT_LEN:
            continue
        key = term.casefold()
        if key in seen:
            continue
        seen.add(key)
        variants.append(term)
        if len(variants) >= MAX_VARIANTS:
            break
    return variants


async def expand_query(
    query: str, engine, *, model: Optional[str] = None
) -> tuple[list[str], dict]:
    """Expand ``query`` via ``engine``; FAIL OPEN to no variants on error.

    Returns ``(variants, usage)``. When the engine call or output parsing
    fails, returns ``([], usage)`` with an ``"error"`` key in ``usage``
    instead of raising — search must never break because expansion did.
    """
    prompt = build_expansion_prompt(query)
    try:
        raw_text, usage = await engine.generate(prompt, model=model)
    except Exception as exc:
        return [], {"error": str(exc)}
    usage = dict(usage or {})
    try:
        variants = parse_expansion(raw_text, query)
    except Exception as exc:
        usage["error"] = str(exc)
        return [], usage
    return variants, usage
