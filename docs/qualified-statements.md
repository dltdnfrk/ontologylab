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

### Polarity ruling, 2026-09-27 (todo 33)

For the exact assertion and experimental scope:

- `no_effect` is a measured absence of a significant effect. Tested outcomes
  described as "ineffective", "not significantly different", or "did not reduce"
  belong here; negative wording alone does not make a refutation.
- `refutes` is reserved for an explicit contradiction of a stated or expected
  claim, not merely a measured null. If a passage does both, the measured
  finding remains `no_effect`; a separate contradiction needs its own span.
- `supports` asserts a positive effect or a positive nonexperimental relation.
  A comparison between two effective treatments is not a null versus untreated.

The `extract-v8` polarity precedence and examples already implement this ruling.
Todo 33 does not change prompt text or `PROMPT_VERSION`.
Zero observed members of a category (for example, resistant isolates) is not
automatically a null treatment effect or a contradiction of a stated claim.
Where the source and this ruling do not resolve that distinction, retain the
historical label and record ambiguity rather than infer an expected claim.

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
| `dose` | NFKC/case/whitespace plus the unit table in `unit_normalization`. Exact qualitative aliases: dilute dose, dilute doses -> dilute. Fully parsed numeric doses (including `or`/`and` alternatives) become canonical value + unit, retaining a.i./a.e. basis. Reciprocal ha/L/kg unit spellings such as `ha-1` and `ha−1` map to slash units. Numeric label-rate multiples use the exact rule below; other reference rates, unsupported units and ranges retain normalized text and punctuation. |

#### Exact label-rate multiples (todo 33)

Within the agrochem `dose` slot, a bare numeric `Nx` or `N×` is label-rate
shorthand, not an arbitrary fold change. This reading is explicitly grounded
for the blackgrass gold in the full body's whole-plant rate-response section,
which defines the multiples relative to each herbicide's recommended label
field rate. Do not encode a stock dilution, control-relative ratio or
magnification using that shorthand; retain its named reference.

After NFKC, casefold and whitespace collapse, the entire value must match:
an unsigned integer or decimal with digits on both sides of the decimal point,
optional whitespace, `x` or `×`, and either no suffix, `_label_rate`, or a
single space followed by one of these exact suffixes:
`recommended rate`, `label rate`, `field label rate`,
`recommended label rate`, `recommended field label rate`,
`recommended label field rate`.

Render the number without redundant leading/trailing zeroes and append
`x_label_rate`: `1x`, `1× recommended rate` and `01.00x label rate` all become
`1x_label_rate`; `0.5x` becomes `0.5x_label_rate`, never `1x_label_rate`.
The value remains relative to the same treatment's label rate, not a mass
conversion or permission to merge different treatment/population statements.
Named alternative references, additional text, fractions, word numbers,
ranges and alternatives are not matched (`1x control rate`, `1x stock
concentration`, `1x or 2x`, and `half recommended field label rate` stay distinct).
There is no fuzzy matching or inference from neighboring assertions.
The existing store boundary and qualified scorer both call this rule through
`normalize_statement_value("dose", ...)`; raw provenance remains available.

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
mapping of all 34 original rows. The script `qualify_gold.py` emits
versioned deterministic derivations without modifying historical gold. Original
row indexes and names are retained for exact reconstruction. The mapping
review is an engineering annotation review against frozen contexts and quotes,
not independent expert adjudication.

The generator uses the same deterministic value normalization as new writes;
`qualified-mapping.json` retains the reviewed source labels.
Its default output is `gold-qualified-normalized.json` (old polarity, current
dose normalization). `--kind aligned` emits `gold-aligned.json` from
`gold-fulltext.json` and the reviewed `alignment.json`: only rows 11 and 23
(one-based) change from `refutes` to `no_effect`. All other row fields,
including historical context wording, remain identical. Rows 29-31 are
explicitly ambiguous and retain their old labels. The alignment table records
all 34 quotes, decisions, rationales and full-body context coordinates.

`--kind aligned-qualified` emits `gold-aligned-qualified.json` by applying
the existing qualified mapping and current normalization to that aligned
source. Thus polarity alignment and dose normalization are separate operations;
the only qualifier changes from archived `gold-qualified.json` are the doses
in rows 14-16. `--check` verifies the selected committed artifact byte for byte.
`gold.json`, `gold-fulltext.json`, `gold-qualified.json` and
`qualified-mapping.json` remain frozen.

Use the aligned qualified derivation for qualified scoring and
`gold-aligned.json` for legacy scoring, preserving each scorer's endpoint
representation. A rescore of trial-5's frozen export is an offline diagnostic
under the revised definition, not a new extraction trial or independent
holdout. Keep historical scores alongside it and leave thresholds unchanged.

Qualified scoring normalizes both sides and requires the same normalized/recorded-alias core triple and
polarity, and equality for every qualifier specified by gold. Extra predicted
qualifiers are allowed. Different doses, populations, aspects or trial contexts
cannot receive credit for one another. Legacy scoring remains the default.
Historical v5-store qualified scores are diagnostics, not a v6 extraction trial.
