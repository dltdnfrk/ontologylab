# Qualified statements in agrochem-v2

Decision: 2026-09-27. Follow the [Biolink fully-qualified-statement model](https://github.com/biolink/biolink-model/blob/master/src/docs/association-examples-with-qualifiers.md)
and [W3C n-ary relation pattern](https://www.w3.org/TR/swbp-n-aryRelations/).
Nodes are core concepts; association qualifiers compose the complete statement.
Ignoring qualifiers must leave a true core triple, except for negation, which
remains association polarity. A named disease is not its causal organism, and a
tested mixture is not an alias for one ingredient.

## Closed vocabulary

`schemas.AGROCHEM_STATEMENT_QUALIFIERS` is the source of truth for keys.
`statement_qualifiers.QUALIFIER_VOCABULARIES` defines canonical values and
explicit synonym tables. The names below
are [Biolink slots](https://biolink.github.io/biolink-model/):

- `qualified_predicate`: a more specific predicate for the full reading.
- `subject_aspect_qualifier`, `object_aspect_qualifier`: growth, oviposition,
  mortality or another explicitly measured aspect.
- `subject_direction_qualifier`, `object_direction_qualifier`: aspect direction.
- `subject_form_or_variant_qualifier`, `object_form_or_variant_qualifier`:
  isolates, strains and life stages (Biolink includes "late stage" as an example).
- `subject_part_qualifier`, `object_part_qualifier`: the affected part.
- `population_context_qualifier`: a scoped population, including cohort location
  and year when necessary to identify that population.
- `species_context_qualifier`, `anatomical_context_qualifier`: contextual species
  and anatomy; neither silently substitutes for an endpoint.
- `causal_mechanism_qualifier`: an explicitly reported mechanism.

Project-local slots, each optional:

| Slot | Meaning and reason for the local extension |
| --- | --- |
| `study_context` | Experimental setting and named assay/trial, e.g. "in vitro" or "crop trial 1". Biolink has no corresponding experimental-setting association qualifier. |
| `dose` | Source-stated dose/rate, with unit or reference rate. Recognized units convert deterministically; qualitative/reference rates never become inferred numeric doses. |
| `application_timing` | Timing of application relative to emergence or another event. Biolink has no association slot for agrochemical pre/post-emergence application timing. |
| `polarity` | Existing claim enum: supports, refutes, no_effect. Unlike Biolink's negation flag, it distinguishes a measured null from an explicit denial. Remains optional for legacy assertions; omission never defaults to supports in scoring. |
| `evidence_strength` | Existing model self-report enum: strong, moderate, weak. Preserved for compatibility; never authority to verify a fact. |

Every supplied value must be a nonempty string. Textual source labels are
accepted where no attested identifier exists: this uses Biolink slot semantics,
not a claim of full Biolink CURIE/range validation. Unknown keys raise
`UnknownQualifierError`, a `SchemaValidationError`, before any graph writes.
Existing installed agrochem-v2 schemas inherit the platform slots at validation
and prompt-read boundaries, without rewriting their stored declarations.
Other schemas do not inherit the agrochem vocabulary.

### Value normalization, reviewed 2026-09-27 (todo 30)

Engineering review against the frozen mapping and trial-4 surfaces, not
independent scientific adjudication. Tables apply globally, never by gold row,
paper, endpoint or polarity. No fuzzy matching, edit distance, stemming,
population inference or automatic aspect completion.

| Key/group | Canonical values; exact additional spellings |
| --- | --- |
| `study_context` | `in_vitro` (in vitro, in-vitro); `greenhouse` (glasshouse, glasshouse screening, greenhouse screening); `field_trial` (field, field trial, field experiment); `crop_trial` (crop trial); `bioassay`; `background` |
| Both aspect slots | `growth`, `oviposition`, `mortality`, `survival`, `yield`, `density`, `abundance`; `bubble_development` (bubble development); `fresh_weight` (fresh weight, fresh-weight); `dry_weight` (dry weight, dry-weight); `tiller_number` (tiller number); `fresh_weight_and_tiller_number` (fresh weight and tiller number) |
| `application_timing` | `pre_emergence` (pre-emergence, preemergence, pre emergence); `post_emergence` (post-emergence, postemergence, post emergence); `early_post_emergence` (early-postemergence, early postemergence, early-post-emergence, early post-emergence) |
| Both direction slots | `increased` (increase, increasing); `decreased` (decrease, decreasing); `unchanged` (no change) |
| Life stages inside both form/variant slots | `egg` (eggs), `larva` (larvae, larval), `pupa` (pupae, pupal), `nymph` (nymphs, nymphal), `adult` (adults), `seedling` (seedlings), stored as `life_stage:<value>` |
| Form/variant kinds | `strain`, `isolate`, `variant`, `life_stage`; store `kind:<label>`. Strain/isolate/variant labels use `kgstore_base.normalize_name`; a bare unclassified label stays `other:<normalized name>`, never an inferred strain. |
| `population_context_qualifier` | Free text via NFKC and `normalize_name`. Preserve location, year, sampling and list order. No aliases between R and resistant, or between broader and narrower populations. |
| `dose` | NFKC/case/whitespace plus the unit table in `unit_normalization`. Exact qualitative aliases: dilute dose, dilute doses -> dilute. Fully parsed numeric doses (including `or`/`and` alternatives) become canonical value + unit, retaining a.i./a.e. basis. Reciprocal ha/L/kg unit spellings such as `ha-1` and `ha−1` map to slash units. Unsupported units, ranges and reference rates retain normalized text and punctuation. |

All listed canonical values are also accepted. Unicode hyphens U+2010,
U+2011, U+2012, U+2013 and U+2212 are equivalent only during closed-table
lookup. A numbered setting retains its number as `bioassay:2`,
`crop_trial:1` or `field_trial:1`; assay 1 never equals assay 2.
An unlisted named study stays distinct (`other:jar bioassay` is not bioassay 1).
Composite timings/aspects are not split or reduced to a constituent.

Unknown closed values use `other:<NFKC/case/whitespace-normalized raw>`
rather than rejection. The existing slots accept nonempty source labels;
preserving unlisted named experiments and measured outcomes avoids losing
source assertions while making their unclassified status explicit. Unknown
keys still raise `UnknownQualifierError`; polarity/strength enums remain
strict. `other:` is idempotent and never grants missing-scope credit.
Other free-text slots retain the prior punctuation-preserving normalization.

At agrochem-v2 proposal insertion, all rows validate first, then normalized
values are stored and copied onto the proposal for exact citation binding.
When values change, the first inserted surface dictionary is retained in
`edges.properties_json.raw_qualifiers`, outside statement identity. This is
platform-generated provenance, not an accepted model property. Deduplicated
mentions retain their own source spans/citations, not additional raw-value
dictionaries. Existing graph rows, qualifiers keys and IDs are not rewritten:
this is a write-boundary change, not a scientific re-annotation migration.
An old noncanonical qualified row can therefore coexist with a newly
canonical row; offline scoring normalizes both without mutating either.

## Identity and compatibility

Identity is schema partition + core triple + polarity + the whole remaining
qualifier set, including `evidence_strength` if supplied. New agrochem-v2 writes
first use the value normalization above; canonical identity then uses Unicode
NFKC, casefold and collapsed whitespace; keys are exact and sorted. Numeric
doses `0.1` and `01` remain distinct values. JSON types on other
ontologies remain distinct. Qualifier order is immaterial; omitted and present
qualifiers are different statements.

`edges.qualifiers_key` materializes that canonical set. The unique index,
proposal deduplication, node-merge deduplication and citation binding all use
it. Carry-forward and pack copy preserve it. Writable-store migration adds and
backfills only this column and replaces the derived uniqueness index, not
edges, edge IDs, raw qualifier JSON or schema versions. Read-only packs are
never migrated. Empty sets retain the prior identity and edge IDs. This avoids
SQLite user-defined functions in immutable portable packs.

`claims_for` already exposes the entire qualifier object; no response keys are
removed. The contract golden gains qualifiers inside its existing objects.

## Extraction and evaluation

`extract-v9` lists the canonical values and requests every qualifier explicitly
stated by the asserting span, including aspect, dose, population and study
context. Completeness is prompt guidance, not a claim of measured model recall.
Deterministic
recovery only splits a spelled binomial plus `isolate`/`strain` suffix when
every referencing edge cites that exact qualified mention, and no supplied
qualifier conflicts. It never borrows another arm's population, stage, dose,
aspect or trial context, or records qualified mentions as species aliases.
Scripted engines test these mechanics, not model compliance or model recall.

`tests/gold/agrochem-polarity/qualified-mapping.json` is an explicitly reviewed
mapping of all 34 original rows. The script `qualify_gold.py` emits a
deterministic derived file without modifying either old gold file. Original
row indexes and names are retained for exact reconstruction. The mapping
review is an engineering annotation review against frozen contexts and quotes,
not independent expert adjudication.

The generator uses the same deterministic value normalization as new writes.
Original findings, spans, polarity, contexts and reversible coordinates remain
unchanged; `qualified-mapping.json` retains the reviewed source labels.

Qualified scoring normalizes both sides and requires the same normalized/recorded-alias core triple and
polarity, and equality for every qualifier specified by gold. Extra predicted
qualifiers are allowed. Different doses, populations, aspects or trial contexts
cannot receive credit for one another. Legacy scoring remains the default.
Historical v5-store qualified scores are diagnostics, not a v6 extraction trial.

## Bounded statement completion (todo 34)

After a successful first response, a chunk triggers completion when a parsed
statement has `population_context_qualifier` or `study_context`, or when its
agrochem-v2 relation is in `extractor.COMPARISON_RELATIONS`. This explicit set
covers effect, resistance and comparison relations, plus `reports_efficacy`;
composition and taxonomy alone do not trigger it. Empty chunks never trigger.
The request contains the original chunk and JSON first-pass statements with
chunk-local offsets. It asks only for missing reported arms (including nulls)
and qualifiers stated in each assertion's span, not inferred context.

Completion makes at most **one actual request**, without JSON or transport
retries. Its output enters the same parser, normalizers, strict store validators,
qualified identity and citation binder as the first response. Completion has an
additional strict source boundary: absent/out-of-chunk spans are refused rather
than repaired. Coordinates must be actual JSON integers, not booleans, strings,
floats or non-finite numbers, and a relation's span must contain its endpoint mentions. Typed
`extract.proposal_rejected` records retain invalid proposals' reasons.
Unexpected exceptions at the optional completion provider/parser boundary also
produce a typed response rejection; the successful first-pass proposals still
reach the common persistence path. Store-write failures are not swallowed.

In the completion request, the chunk is a JSON string and first-pass statements
are a JSON array, both serialized with `ensure_ascii=True` and literal `<`
escaped as `\u003c`. Their data therefore cannot produce opening or closing XML
delimiters. Decoding recovers source characters exactly; spans index that decoded
chunk, not the encoded representation. Both blocks are explicitly data, never
instructions. This preserves the first-pass schema and source-grounding rules
without interpolating raw source text into the completion request.

The two proposal lists are appended in first-pass order. No update/delete
operation or model-supplied ID is interpreted. A qualifier enrichment creates a
new statement because qualifiers participate in identity; the original bare
statement remains proposed. Repeated first-pass identities are ignored after
normalization: they neither manufacture duplicate citations nor rewrite the
first edge's qualifiers, confidence, status or span. Human review,
not completion, decides which statements become knowledge.

`PROMPT_VERSION` is bumped to `extract-v9` rather than versioning only the second
prompt: lifecycle identity must distinguish this two-pass extraction pipeline
from completed v8 work. Disabling completion uses `extract-v9-first-only`, so
enabling it later does not silently reuse an off-mode run. Request provenance
records `pass=first|completion`, document/chunk, sequential request number and
pipeline version. Both passes charge the same `extract` accounting step.

### Budget allocation

With N chunks and T transport retries, unrestricted requests would be
`N * (2 + T + 1)` (first response, one JSON retry, T transport retries, one
completion). At N=21 and T=2 that is **105**, not 60. The automatic wall budget
therefore uses `min(105, max_engine_calls)` request slots and the existing
timeout/backoff allowance per slot. An explicit wall budget stays binding.

Before completion, reserve `(2 + T)` requests per unvisited chunk and the
corresponding timeout allowance. If completion cannot fit, skip it and log
`extract.completion_skipped` with the budget/cancellation/disabled reason.
First-pass retries in enabled agrochem-v2 runs also leave one request for each
unvisited chunk. Thus 21 first attempts plus at most 39 optional attempts fit
60, even at worst-case timeouts; no request bypasses the global cap.
If each first pass needs its JSON retry but no transport retries, all 21 chunks
succeed and completion uses only remaining capacity. The more conservative
future-chunk reservation can leave unused slots rather than gamble on retries.

It is impossible to promise 21 successful chunks under arbitrary transport
failures: even first passes alone can require 84 requests. In that worst case,
all chunks are attempted within 60 and exhausted retries remain honestly failed,
not marked successful. A cap below 21 or an explicit short time limit can still
prevent full coverage. These tests prove mechanics, not improved model recall.

Completion defaults on. CLI: `extract --no-statement-completion`; HTTP:
`POST /api/extract` with `"statement_completion": false`. The additive request
field flows through the existing extraction job limits, with no route removal.
