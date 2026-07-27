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


def parse_search_query(raw_text: str, topic: str) -> tuple[str, str]:
    """Parse engine output into ``(query, notes)``.

    Returns ``(topic, "")`` when the output is unusable — the caller cannot
    distinguish a refusal from a parse failure and does not need to; both
    mean "search the topic as given".
    """
    try:
        block = extract_fenced_block(raw_text, "json")
        payload: Any = json.loads(block)
    except Exception:
        return topic, ""
    if not isinstance(payload, dict):
        return topic, ""

    query = payload.get("query")
    if not isinstance(query, str):
        return topic, ""
    query = " ".join(query.split())
    if not query or len(query) > MAX_QUERY_LEN:
        return topic, ""
    # A model that ignores rule 4 would otherwise widen the very net this
    # exists to narrow.
    terms = query.split()
    if len(terms) > MAX_TERMS:
        query = " ".join(terms[:MAX_TERMS])

    notes = payload.get("notes")
    notes = " ".join(notes.split()) if isinstance(notes, str) else ""
    return query, notes[:200]


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
    if query == topic:
        usage.setdefault("error", "engine returned no usable query")
    return query, usage
