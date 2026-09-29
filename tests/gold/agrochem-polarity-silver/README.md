# Published product-performance silver corpus

**model-annotated, not human ground truth**

This directory is deliberately separate from the human-reviewed
`../agrochem-polarity/` gold. Its ten additional Europe PMC papers are
CC-BY-4.0. `sources/full/manifest.json` records each JATS license element,
author attribution, DOI, source URL, retrieval date and SHA-256 hashes.
The original JATS is stored with one added LF; `jats_sha256` identifies the
download response and `stored_jats_sha256` identifies the stored XML.
Text files are complete production-converted bodies plus one LF.

Annotations follow
[`annotation-protocol.md`](../agrochem-polarity/annotation-protocol.md).
Only published asserting sentences are copied into annotations; methods,
culture, preparation and treatment schedules are outside annotation scope.
The downloaded source documents are retained for exact-span verification.
No extraction trial, product behavior change or threshold change is involved.

Two fresh model contexts annotate independently. A third fresh context
adjudicates disagreement sentences without gold or extraction output.
`annotations/` retains both raw responses, pre-adjudication agreement,
disagreement packets and adjudication decisions. Exact prompts and file
allowlists are in
[`blinding-record.json`](../agrochem-polarity/annotations/blinding-record.json).
Blinding is instruction-scoped, not an operating-system access sandbox.
The annotators share a model family, so high agreement would not establish
human validity or independent scientific ground truth.

`gold-silver.json` retains source-valued qualifiers;
`gold-silver-qualified.json` applies the existing deterministic normalizer.
Both retain explicit scope and must be loaded with `qualified=True` or the
CLI's `--qualified`, since a core triple can have multiple scoped outcomes.
The legacy unqualified loader intentionally rejects conflicting core triples.
Character offsets and UTF-8 byte offsets are separately identified.
Repeated full statement identities are deduplicated, not counted as extra
claims; their provenance is retained in the build receipt.

```sh
uv run --all-extras python -m ontologylab.polarity_eval \
  tests/gold/agrochem-polarity-silver/gold-silver-qualified.json --qualified
uv run --all-extras python tests/gold/agrochem-polarity/annotation_audit.py --check
```

Agreement is reported before adjudication. The existing qualifier matcher
is asymmetric, so both directions are reported. Kappa uses one-to-one
reciprocal core/scope matches with polarity withheld from pairing; unmatched
selections are reported separately. Undefined kappa is `null`. The negative
target is not a quota: the final receipt reports the actual supported count,
including a shortfall when fewer than 100 null/refutation statements survive.

## Version 1 result

The final corpus has **98 statements: 88 supports, 10 no_effect, 0 refutes**.
The 100-negative target was not reached in these ten papers; this does not
establish that the wider literature lacks 100 suitable negative findings.

Annotators submitted 104 and 121 rows, representing 104 and 119 unique
statements. Reciprocal statement matching is 44.843%; polarity kappa is 1.0
on only 50 matched statements (48 supports and 2 no_effect). Sixty sentences
needed selection or scope adjudication. Perfect matched-label agreement
therefore does not imply complete coverage or scientific correctness.

The second submission had 13 paper IDs swapped between two documents.
`annotator-b-submitted.json` preserves that response; exact unchanged quotes
resolved the paper IDs, and `source_binding_corrections` records every fix.
No polarity or qualifier label was changed during that binding correction.
The initial and clarified adjudications are both retained. Packet-only
adjudicators inherit unanimously document-resolved cores from the two
full-text annotators; they do not independently verify those coreferences.
