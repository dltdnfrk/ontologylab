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

`extract-v8` lists the canonical values and requests every qualifier explicitly
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
