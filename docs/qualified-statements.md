# Qualified statements in agrochem-v2

Decision: 2026-09-27. Follow the [Biolink fully-qualified-statement model](https://github.com/biolink/biolink-model/blob/master/src/docs/association-examples-with-qualifiers.md)
and [W3C n-ary relation pattern](https://www.w3.org/TR/swbp-n-aryRelations/).
Nodes are core concepts; association qualifiers compose the complete statement.
Ignoring qualifiers must leave a true core triple, except for negation, which
remains association polarity. A named disease is not its causal organism, and a
tested mixture is not an alias for one ingredient.

## Closed vocabulary

`schemas.AGROCHEM_STATEMENT_QUALIFIERS` is the source of truth. The names below
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
| `dose` | Source-stated dose/rate, with unit or reference rate, e.g. "1x recommended rate". Biolink exposure magnitude is an exposure attribute, not this association qualifier. No unit conversion or inferred numeric dose. |
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

## Identity and compatibility

Identity is schema partition + core triple + polarity + the whole remaining
qualifier set, including `evidence_strength` if supplied. Values use Unicode
NFKC, casefold and collapsed whitespace; keys are exact and sorted. Punctuation
is retained, so doses `0.1` and `01` do not collapse. JSON types on other
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

`extract-v6` requests core entities plus relation qualifiers. Deterministic
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

Qualified scoring requires the same normalized/recorded-alias core triple and
polarity, and equality for every qualifier specified by gold. Extra predicted
qualifiers are allowed. Different doses, populations, aspects or trial contexts
cannot receive credit for one another. Legacy scoring remains the default.
Historical v5-store qualified scores are diagnostics, not a v6 extraction trial.
