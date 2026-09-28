# Statement harness contract

`rules_version = "units-v1"`. Frozen 2026-09-28. This is the unit, offset, section, and missing-scope contract for the statement harness. It is not an extraction score. It does not change `extract-v9`, existing gold, or approval.

## Unit

One statement is one reported finding whose wording assigns an arm or subject, a comparator when the sentence states one, a measured endpoint, an observation time when stated, and an experiment or site when stated. Serialize it as a subject-predicate-object triple, polarity `supports`, `no_effect`, or `refutes`, closed qualifier keys with attested values only, an asserting or result span, participant and qualifier mention spans, and optional linked context spans.

An unstated axis is absent. It is never guessed. A dose keeps the unit and basis the sentence states. A tested mixture is one treatment, not one statement per ingredient.

A sentence is a discovery container. A clause or coordinated result is a candidate boundary. An explicitly assigned arm/outcome pair is the assertion. One sentence may yield zero, one, or several statements. They may share an asserting quote and still have distinct arm and result anchors.

Split enumerated products, populations, dose arms, timepoints, or endpoints only when the wording assigns each an outcome. Split mixed positive and null arms. Do not take the Cartesian product of lists. Do not project a mixture onto its ingredients. Do not split a composite measured aspect. Do not multiply one identical claim because it has several citations. A clause whose attribution is unresolved is one `unresolved` container for a person, not several guessed claims.

## Offsets

Offsets are zero-based, half-open Python Unicode character offsets into the unchanged document. For every expected slot, `text[start:end] == quote`. Never use UTF-8 byte offsets as character offsets. Never normalize, trim, or repair the text before assigning offsets. Preserve original whitespace.

The unicode fixture starts with U+00B5 MICRO SIGN so a byte-offset reader mis-slices every later span. The dot in `P. annua` and the dot in a dose such as `0.1` are not sentence boundaries. Ambiguous line or table boundaries stay unresolved rather than being guessed.

## Section eligibility

The initial denominator is asserting prose in Results, Discussion, and Conclusion. Methods, materials, culture, preparation, and treatment-schedule sections are outside it. Tables without asserting prose are outside it.

Every eligible sentence is kept, including a sentence with no negation cue. Missing or uncertain headings produce `section_unresolved` records for review. They are not an invented negative, and they are not a silently omitted eligible section.

`section_spans` are sorted, non-overlapping, zero-based, half-open character spans. Labels are `results`, `discussion`, `conclusion`, `methods`, and `section_unresolved`. An arm, result, asserting sentence, or unresolved container must sit inside `results`, `discussion`, or `conclusion`.

## Missing-scope policy

Do not borrow dose, setting, timing, or population from a neighboring sentence or from Methods. A cross-sentence window may include the immediately adjacent sentence only for an explicit participant antecedent. That context span is recorded separately. The asserting span remains its own unit. Linking the antecedent does not import the neighbor's dose or other qualifiers.

`not_reported`, `not_tested`, an absent table entry, and an unresolved measurement produce no null proposal. A measured absence of a significant effect is `no_effect`. A nonsignificant comparison is that measured null; it does not prove the effect is exactly zero or that two treatments are equivalent. `refutes` needs an explicit contradiction of a stated claim, not merely "did not reduce." If a passage does both, the measured finding stays `no_effect` and the contradiction needs its own span.

Polarity is not a cue. Hedge or speculation is an evidence tag, scored separately, never a fourth polarity and never `evidence_strength`. A pseudo-cue such as "not only" does not flip polarity. An uncued positive sentence stays in the denominator. Candidate selection cannot remove an eligible sentence. No detected arm slot is not the same thing as no claim.

## Identity formula

Later slices hash this field list: `document_sha256 | rules_version | assertion_start:end | arm_anchor | result_anchor`.

Encode `unit_id` as the SHA-256 hex digest of those five fields joined by `|`. No field contains `|`. Do not strip trailing separators.

- `document_sha256` is the lowercase hex SHA-256 of the unchanged document text, UTF-8 bytes.
- `rules_version` is `units-v1`.
- `assertion_start:end` is the asserting sentence, or the unresolved container when the sentence is not split.
- `arm_anchor` and `result_anchor` are `start:end` character offsets, or empty when the container is unresolved.

An explicit unit has both anchors. Each assigned arm in one sentence is its own unit. Units share the assertion span and stay distinct by arm and result offsets. Context spans are not part of `unit_id`. Quote text is not a sixth field: the offset contract already requires `text[start:end] == quote`.

Unresolved example, document hash `abc`, container `0:12`: `abc|units-v1|0:12||`

Explicit example, assertion `0:20`, arm `4:8`, result `9:12`: `abc|units-v1|0:20|4:8|9:12`

`sentence_id` is the same join with exactly three fields: `document_sha256 | rules_version | sentence_start:end`.

## Fixtures

`tests/fixtures/statement_harness/*.json` is the truth table for this version. The sentences are invented efficacy lines. They are not quotations from the development papers, and they are not a recall denominator.

Each file has `id`, `case`, `rules_version`, `text`, `section_spans`, `rationale`, and `expected_slots`. Each expected slot is a `(quote, start, end)` triple plus a `role`. Arm slots also carry `arm`, the same surface string as `quote`, and `polarity` (`supports`, `no_effect`, `refutes`, or `null`). Result slots carry `arm`, naming the arm quote they belong to.

The rationale names every arm on its first line, so the count is checkable without trusting the slot list:

- `Assigned arms: none` or `Assigned arms: <quote>; <quote>`
- `Whereas members:` when the text contains `whereas`. Same names, same order, same count as the assigned arms.
- `Respectively members:` when the text contains `respectively`. Same rule. Order is the assignment order.
- `List members unresolved:` when a list must stay unresolved. Assigned arms stay `none`. Those names are not arms.

`tests/test_statement_harness_fixtures.py` is the oracle. For every expected slot it checks `text[start:end] == quote` using the stored offsets. It does not search for the quote and repair them. The arm-slot count must equal the number of names on `Assigned arms`, and equal the `whereas` or `respectively` member count when that line is required. An unresolved list has zero arm slots.

`STATEMENT_HARNESS_FIXTURE_DIR` may point the same test at a copy. The slice mutant shifts one expected offset by one character; the slice check must fail. Deleting one arm from `expected_slots` while leaving the rationale names must also fail.

| Case | What the wording locks |
| --- | --- |
| `unicode_prefix_p_annua` | U+00B5 prefix; `P. annua` is one span |
| `decimals_doses` | `0.1` and its unit stay one dose span |
| `whereas_mixed` | Null arm and positive arm, split at whereas |
| `respectively_three_arm` | Three outcomes, assigned in order |
| `ambiguous_list_unresolved` | Named list members, zero arms |
| `tested_mixture` | One mixture arm; ingredients are not arms |
| `hedge` | `may` is a hedge tag; polarity is null |
| `pseudo_cue` | `not only` does not create `no_effect` |
| `uncued_positive` | No cue, and the positive arm remains |
| `cross_sentence_antecedent` | `It` links to the previous subject; the neighbor dose is not borrowed |

## Development-only papers

These five full-text papers are development-only. Extraction trials and the local aspect vocabulary have already seen them. They must not be assigned as test data. Sorting them by date does not undo that exposure. This contract does not edit `tests/gold/agrochem-polarity/`. The historical rows stay unchanged. Model-annotated silver papers are not human gold and are not a substitute test set.

| PMCID | DOI |
| --- | --- |
| PMC12632097 | 10.1186/s12866-025-04356-y |
| PMC12546283 | 10.1007/s10340-025-01925-y |
| PMC12563837 | 10.3390/genes16101169 |
| PMC12713700 | 10.1002/ps.70214 |
| PMC11298438 | 10.3389/fmicb.2024.1425392 |

A held-out statement score needs new papers annotated by humans. That work is not this contract.

## What this version does not do

It does not enumerate units, call a model, score precision or recall, or write `verified`. Human approval remains the only writer of `verified`. No score changes node or edge status.
