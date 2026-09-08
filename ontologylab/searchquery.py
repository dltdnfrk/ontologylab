"""Turn a research topic into a query the paper APIs can actually answer.

The fan-out used to send the user's sentence verbatim to arXiv, Crossref,
OpenAlex and the rest. Those are keyword indexes over (overwhelmingly)
English metadata, and they OR the tokens they are given, so a Korean
sentence retrieves whatever happens to share a token with it. Measured, on
``G-11 사과대목의 하드닝 최적 생육 조건에 대해서``:

* arXiv matched only ``G-11``, which its tokenizer splits into ``g`` and
  ``11`` — returning *Muon g-2*, *k-11-representable graphs*, *g-measures*.
* Crossref matched the Korean grammatical ending ``에 대해서`` ("about") and
  the word ``조건`` → ``Optimal Conditions`` — returning a paper on the
  ordering of Wonhyo's writings, and one on shot peening of Al7075-T6.

Nothing downstream could repair that: a relevance filter cannot recover a
paper the search never retrieved. The repair has to happen before the
request, which is what this module does — it asks the configured engine to
write the query a researcher would have typed.

Fails open, exactly like `expansion`: if the engine is missing, errors, or
answers unusably, the caller gets the original topic back and the run
proceeds. A degraded search is worse than a good one; a search that refuses
to run is worse than both.
"""

from __future__ import annotations

import json
from typing import Any, Optional

from ontologylab.engines import (
    QUERY_MARKER_CLOSE,
    QUERY_MARKER_OPEN,
    extract_fenced_block,
)

SEARCH_QUERY_PROMPT_VERSION = "searchquery-v1"

# Long queries retrieve nothing: these indexes AND nothing and OR everything,
# so each extra term widens the net rather than narrowing it. A human
# searching an academic index types three or four terms.
MAX_TERMS = 6
MAX_QUERY_LEN = 120
DEFAULT_SEARCH_QUERIES = 4
MAX_SEARCH_QUERIES = 8


def build_search_query_prompt(topic: str) -> str:
    """Build the topic → search-query prompt.

    The rules exist because of specific observed failures, not style: the
    cultivar code `G-11` is meaningless to the index without its full name
    (`Malling G.11`, `Geneva 11`), and a natural-language sentence in any
    language retrieves noise.
    """
    return f"""You are writing a search query for academic paper databases \
(arXiv, Crossref, OpenAlex, Semantic Scholar, Europe PMC). Convert the \
research topic below into the query a domain researcher would type.

Rules:
1. Return EXACTLY ONE fenced ```json block and nothing else.
2. The JSON is an object: {{"query": "...", "notes": "..."}}.
3. "query" is ENGLISH keywords — these indexes are English-language. Translate
   the topic if it is in another language.
4. At most {MAX_TERMS} terms. These indexes OR their tokens, so every extra
   word adds noise instead of precision.
5. Expand domain codes and abbreviations to the names the literature uses
   (a rootstock code like "G-11" is indexed as "Geneva 11" or "Malling G.11";
   write the form a paper's title would contain).
6. Drop grammatical filler entirely — words like "about", "regarding",
   "conditions for" match everything and mean nothing to a keyword index.
7. NEVER invent a specific paper, author, or product name.
8. "notes" is one short sentence naming what you translated or expanded, for
   the person watching the run. It is never used as a query.

{QUERY_MARKER_OPEN}
{topic}
{QUERY_MARKER_CLOSE}"""


def build_search_queries_prompt(topic: str, max_queries: int) -> str:
    """Build one request for complementary scholarly-database queries."""
    count = max(1, min(max_queries, MAX_SEARCH_QUERIES))
    return f"""Write {count} complementary search queries for academic paper \
APIs. Cover distinct axes such as mechanism, method, outcome, population, or \
evidence type instead of paraphrasing one query.

Return one fenced ```json block: \
{{"queries":[{{"query":"English keywords","axis":"short label",\
"terms":["concept phrase","truncated prefix"]}}],\
"notes":"short summary"}}. Each query has at most {MAX_TERMS} terms, uses \
English metadata terms, expands domain codes, drops grammatical filler, and \
never invents a paper, author, or product. `terms` contains 2-4 concepts \
that scholarly databases should AND; use a stem such as `metabolom` only \
when plural/derived forms must match.

{QUERY_MARKER_OPEN}
{topic}
{QUERY_MARKER_CLOSE}"""


def _clean_query(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    query = " ".join(value.split())
    if not query or len(query) > MAX_QUERY_LEN:
        return None
    return " ".join(query.split()[:MAX_TERMS])


def parse_search_query(raw_text: str, topic: str) -> tuple[str | None, str]:
    """Parse engine output into ``(query, notes)``, or ``(None, "")``.

    Failure is ``None``, never ``topic``. Returning the topic as the
    sentinel conflated two different outcomes: an unusable answer, and a
    correct answer that happens to equal the input — which is exactly what
    a good engine returns when the topic is already English keywords. The
    caller then reported a working formulation as an error and logged
    "searching the topic as typed" about a search it had in fact
    formulated.
    """
    try:
        block = extract_fenced_block(raw_text, "json")
        payload: Any = json.loads(block)
    except Exception:
        return None, ""
    if not isinstance(payload, dict):
        return None, ""

    query = _clean_query(payload.get("query"))
    if query is None:
        return None, ""

    notes = payload.get("notes")
    notes = " ".join(notes.split()) if isinstance(notes, str) else ""
    return query, notes[:200]


def parse_search_queries(
    raw_text: str,
    topic: str,
    *,
    max_queries: int = DEFAULT_SEARCH_QUERIES,
) -> tuple[list[str], str]:
    """Parse ordered, distinct API queries; an unusable set is empty."""
    del topic
    try:
        payload: Any = json.loads(extract_fenced_block(raw_text, "json"))
    except Exception:
        return [], ""
    if not isinstance(payload, dict):
        return [], ""
    items = payload.get("queries")
    if not isinstance(items, list):
        items = [payload.get("query")]
    cap = max(1, min(max_queries, MAX_SEARCH_QUERIES))
    queries: list[str] = []
    seen: set[str] = set()
    for item in items:
        value = item.get("query") if isinstance(item, dict) else item
        query = _clean_query(value)
        key = query.casefold() if query else ""
        if not query or key in seen:
            continue
        seen.add(key)
        queries.append(query)
        if len(queries) == cap:
            break
    notes = payload.get("notes")
    clean_notes = " ".join(notes.split()) if isinstance(notes, str) else ""
    return queries, clean_notes[:200]


async def formulate_search_query(
    topic: str, engine: Any, *, model: Optional[str] = None
) -> tuple[str, dict]:
    """Rewrite ``topic`` for the paper APIs; FAIL OPEN to ``topic``.

    Returns ``(query, usage)``. ``usage`` carries the engine's own usage
    dict plus ``"notes"`` (what was translated or expanded) and, on any
    failure, ``"error"`` — so the caller can say honestly whether the search
    it ran was the formulated one or the raw topic.
    """
    if engine is None:
        return topic, {"error": "no engine configured"}
    prompt = build_search_query_prompt(topic)
    try:
        raw_text, usage = await engine.generate(prompt, model=model)
    except Exception as exc:
        return topic, {"error": str(exc)}
    usage = dict(usage or {})
    query, notes = parse_search_query(raw_text, topic)
    usage["notes"] = notes
    if query is None:
        # Only a parse failure is an error. A query identical to the topic
        # is a legitimate answer — "already the right keywords" — and
        # calling it a failure told the operator the search was degraded
        # when it was not.
        usage.setdefault("error", "engine returned no usable query")
        return topic, usage
    return query, usage


async def formulate_search_queries(
    topic: str,
    engine: Any,
    *,
    model: Optional[str] = None,
    max_queries: int = DEFAULT_SEARCH_QUERIES,
) -> tuple[list[str], dict]:
    """Create complementary API queries; fail open to one raw topic."""
    if engine is None:
        return [topic], {"error": "no engine configured"}
    try:
        raw_text, usage = await engine.generate(
            build_search_queries_prompt(topic, max_queries),
            model=model,
        )
    except Exception as exc:
        return [topic], {"error": str(exc)}
    result = dict(usage or {})
    queries, notes = parse_search_queries(
        raw_text,
        topic,
        max_queries=max_queries,
    )
    result["notes"] = notes
    if not queries:
        result.setdefault("error", "engine returned no usable queries")
        return [topic], result
    return queries, result
