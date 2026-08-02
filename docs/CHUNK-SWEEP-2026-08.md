# Agrochem chunk-size sweep - 2026-08-02

## Decision

**Change `TARGET_CHUNK_TOKENS` from 1,500 to 3,000.** On the five-document
agrochem mini gold set, 3,000 preserved recall, slightly improved precision,
and halved Claude calls per document. The triple-F1 bootstrap intervals overlap,
so this is not a claim that 3,000 is significantly more accurate; it is evidence
that it was not worse in this run while its cost was materially lower.

Decision rule fixed before the run: 3,000 wins only if triple F1 is not worse
beyond CI overlap **and** cost per document is materially lower. A tie keeps
1,500. The observed result passes both gates.

## Protocol

- Fixture: `tests/gold/agrochem-mini/docs.json` (five constructed passages;
  28 distinct normalized gold entities and 27 gold triples).
- Each passage is just over the 1,500-token heuristic boundary and below the
  3,000-token boundary. It therefore produces two chunks at 1,500 and one at
  3,000. Repeated direct-claim prose supplies length without changing the
  fixture's unique entity/triple labels.
- Schema: active `agrochem-v1` preset (26 entity types, 30 relation types).
- Engine: `get_engine("claude", model=None)`, which resolved to
  `claude-fable-5`; one extraction per chunk, no retries.
- Stream scored: engine `claude`, model `claude-fable-5`, prompt
  `extract-v1`, decode params `null`.
- Scoring: existing `evaluate_store` and `bootstrap_f1_interval` defaults
  (2,000 resamples, seed 7, 95% percentile interval).
- Command:

  ```sh
  .venv/bin/python scripts/sweep_chunk_size.py --engine claude \
    --output-dir /tmp/ontologylab-chunk-sweep-2026-08
  ```

Both arms completed. There were no engine errors and no parse rejections.

## Results

| Target tokens | Chunks / calls | Calls / doc | Estimated prompt tokens | Entity P / R / F1 (95% CI) | Triple P / R / F1 (95% CI) | Nominal scaffold share | Observed scaffold share | Engine elapsed |
|---:|---:|---:|---:|---|---|---:|---:|---:|
| 1,500 | 10 / 10 | 2.0 | 32,331 | 1.0000 / 1.0000 / 1.0000 ([1.0000, 1.0000]) | 0.9310 / 1.0000 / 0.9643 ([0.9057, 1.0000]) | 61.36% | 73.68% | 421.786 s |
| 3,000 | 5 / 5 | 1.0 | 19,674 | 1.0000 / 1.0000 / 1.0000 ([1.0000, 1.0000]) | 0.9643 / 1.0000 / 0.9818 ([0.9434, 1.0000]) | 44.26% | 60.54% | 189.858 s |

The 1,500 arm found 28 entities and 29 triples: all 27 gold triples plus two
spurious triples. The 3,000 arm found the same 28 entities and 28 triples: all
27 gold triples plus one spurious triple.

Relative to 1,500, the 3,000 arm used:

- 50% fewer calls and chunks (2.0 to 1.0 calls/document),
- 39.15% fewer estimated prompt tokens (32,331 to 19,674), and
- 54.99% less engine elapsed time (421.786 s to 189.858 s).

## Token and scaffold accounting

`ClaudeEngine` exposes calls, elapsed time, engine, and model, but the Claude
CLI adapter does not expose provider input/output token counts. Token numbers
above are therefore explicitly **estimates**, using the production heuristic
`len(text) // 4`; output tokens are unavailable.

`build_extraction_prompt(preset("agrochem"), "")` measured the empty-document
scaffold at **2,382 estimated tokens** in this checkout. The nominal share is
`2382 / (2382 + target)`: 61.36% at 1,500 and 44.26% at 3,000. The observed
share uses actual prompt totals. It is higher because each 1,500-token passage
has a short overlap-only tail, while each 3,000-token passage does not fill its
full target.

## Limits

Five synthetic, constructed passages are a small sample, and repeated direct
claims are easier than heterogeneous real abstracts. The evaluator's bootstrap
unit is an entity/triple outcome rather than a document, so correlated facts
within a document can make these intervals optimistic. The overlapping triple
intervals correctly prevent claiming an accuracy win. They do support the
narrow decision made here: no observed quality regression, with a material
cost reduction. Re-run this harness on the first representative real corpus
before treating 3,000 as a domain-independent optimum.
