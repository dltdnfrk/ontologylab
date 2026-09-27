# Published-statement annotation protocol, v1

This protocol audits published claims, not extraction performance. Annotators
work independently from the same full texts and vocabulary. No gold labels,
model extraction, trial evidence, other annotator output, logs or prior
sessions are inputs. Model agreement is not independent human validation.

## Scope and unit

One statement is a core subject-relation-object triple, polarity, and every
qualifier explicitly present in its asserting sentence. Use a named chemical
crop-protection product or active ingredient and the crop, weed, pest, disease
or endpoint actually asserted. A named disease is not its causal organism.
Keep a tested mixture intact, never project its result onto an ingredient.
Use document-local expansions of an unambiguous abbreviated species name;
do not invent identifiers, synonyms, species, mechanisms or missing scope.

Read Results, Discussion and Conclusion claims. Methods, materials, culture,
preparation and treatment-schedule sections are out of scope. Do not copy
operational instructions or parameters for making, obtaining, enhancing,
screening or delivering an organism or toxin. Do not compile strain-linked
failure maps. Skip such statements, recording only an exclusion category,
not their operational content. Licensed full texts are retained as source
documents; they are not methods transcriptions or annotation instructions.
For new papers, select published chemical-product field or greenhouse
performance studies, not organism/toxin development or delivery studies.

Enumerate all eligible claims, including measured nulls, without a label
quota. Include positive and negative outcomes. Do not infer nulls from a
missing effect, a nonsignificant comparison between two effective products,
or an absent table entry. Tables alone are not asserting sentences.

## Arm splitting

Split explicitly enumerated products, targets, populations or settings into
separate statements only when the sentence assigns an outcome to each.
Retain the same exact quote for split arms. Preserve mixtures as mixtures.
Split positive and null arms in the same sentence. Do not create a Cartesian
product of lists unless the wording actually asserts every combination.
Never borrow dose, setting, timing or population from a neighboring sentence
or methods section. Do not split a composite measured aspect into invented
independent measurements. Repeated citations of the same complete statement
do not create additional statements; retain its clearest eligible sentence.

## Polarity

- `supports`: the sentence asserts the relation or a positive measured effect.
- `no_effect`: a measured absence of a significant effect, including
  "ineffective", "not significantly different", "did not reduce" or measured
  absence of resistant individuals. Negative wording alone is not refutation.
- `refutes`: explicit contradiction of a stated claim. A measured null remains
  `no_effect`; a separate contradiction needs its own asserting span.

Compare the intended relation, not word sentiment. A detrimental crop effect
can support `phytotoxic_to`. A weaker but effective product is still positive.

## Existing vocabulary

The accompanying `annotation-vocabulary.json` is a data-only snapshot of
agrochem-v2 entity types, claim relations, qualifier keys and canonical value
tables from `ontologylab/schemas.py` and `statement_qualifiers.py`.

Qualifier keys: `qualified_predicate`, `subject_aspect_qualifier`,
`object_aspect_qualifier`, `subject_direction_qualifier`,
`object_direction_qualifier`, `subject_form_or_variant_qualifier`,
`object_form_or_variant_qualifier`, `subject_part_qualifier`,
`object_part_qualifier`, `population_context_qualifier`,
`species_context_qualifier`, `anatomical_context_qualifier`,
`causal_mechanism_qualifier`, `study_context`, `dose`, `application_timing`.
Polarity is stored separately. Do not add model confidence as evidence strength.

Canonical setting values: in_vitro, greenhouse, field_trial, crop_trial,
bioassay, background. Preserve explicit trial numbers.
Aspect values: growth, oviposition, mortality, survival, yield, density,
abundance, bubble_development, fresh_weight, dry_weight, tiller_number,
fresh_weight_and_tiller_number. Direction: increased, decreased, unchanged.
Timing: pre_emergence, post_emergence, early_post_emergence.
Life stages: egg, larva, pupa, nymph, adult, seedling.
Unlisted source labels remain source labels; existing normalization uses
`other:` rather than inventing an alias. The key vocabulary is closed, but
many values are explicitly open text. Include each raw short source value in
`qualifier_quotes`, where it must be a literal substring of the claim quote.
Use source spellings in `qualifiers`; the lead applies existing normalization.
Do not invent a dose or schedule, infer a null direction, or supply an
operational biological parameter as a qualifier.

## Spans and output

Copy one complete eligible asserting sentence verbatim from the stored text,
including Unicode, punctuation and whitespace. Never paraphrase or repair it.
For a sentence that includes excluded operational biological information,
skip it rather than trimming away the information and changing its meaning.
Return `pmcid`, `src`, `src_type`, `relation`, `dst`, `dst_type`, `polarity`,
`quote`, `qualifiers`, `qualifier_quotes`, and `rationale`.
The rationale is a single sentence about the evidence, not a method.
Return a JSON object with `relations`, `excluded` (paper + category only),
and `files_read` (the complete input list). Empty qualifiers are valid.

The lead locates quotes exactly, rejects missing/ambiguous occurrences, and
records zero-based half-open Unicode character offsets as `char_start` and
`char_end`, plus zero-based half-open UTF-8 byte `span.start` / `span.end`
for compatibility with the existing scorer. Never use bytes as characters.

## Agreement and adjudication

Before adjudication, compare normalized core triples using the existing
`qualifiers_cover` matcher. Report A-as-reference and B-as-reference match
rates including polarity, since the production subset matcher is asymmetric.
Also report reciprocal maximum one-to-one matches (both directions cover).
Cohen's kappa uses one-to-one core/scope matches without polarity as the
pairing criterion, with marginal counts and a confusion matrix. No pairs or
constant identical marginals give undefined kappa (`null`), not perfect kappa.
Pair within paper, not across different studies; no fuzzy endpoint matching.
Report unmatched selections and scope/endpoint differences separately from
polarity disagreements. Selection disagreements count as disagreements.

A fresh adjudicator sees this protocol and disagreement packets containing
only the asserting spans and the two annotations (one may be absent).
It receives neither gold nor extraction outputs. It chooses A, B, neither,
or a corrected annotation grounded entirely in the supplied span, with a
one-line rationale quoting the decisive words. For an unresolved endpoint,
omit rather than use inaccessible context. Gold comparisons happen only at
the lead; absent blind coverage is not evidence that historical gold is wrong.
Changes to historical rows require an explicit adjudication decision.

New silver files say `model-annotated, not human ground truth` at the top
level and remain in a separate directory. Negative totals are observations,
not targets to manufacture. Original human-reviewed gold remains immutable.
