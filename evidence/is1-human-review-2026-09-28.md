# IS-1 human-review trial-6 measurement (2026-09-28)

**Amended contract PASSED: pooled reviewable coverage is 51/51 = 100%, above
the unchanged 90% acceptance bar.** The first contract measured 34/51 and
FAILED; both outcomes are retained below. Earlier FAILED model trials and
their results remain unchanged.

The plan owner amended the candidate contract after finding that a sentence
with multiple measured-null arms disappeared when any one null statement
cited it. The detector now presents every sentence with a published-source
cue. Those without a null citation are `unextracted`; those with one or more
are `partially_extracted`, with the cited statement IDs, subjects, relations,
objects, polarities, qualifiers, origins, statuses and citation spans listed
for the reviewer. A cited arm no longer conceals its missing neighbors.

| Trial | Gold null rows | Extracted | Flagged rows | Reviewable | Sentences to read | Unextracted | Partially extracted | Sentences not in gold |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| r1 | 17 | 0 | 17 | 17/17 | 51 | 28 | 23 | 40 |
| r2 | 17 | 3 | 17 | 17/17 | 51 | 33 | 18 | 40 |
| r3 | 17 | 4 | 17 | 17/17 | 51 | 29 | 22 | 40 |
| **Pooled** | **51** | **7** | **51** | **51/51** | **153** | **90** | **63** | **120** |

The status counts are sentence counts, not gold-row counts; one sentence can
contain several gold arms. Cues were not derived from gold polarity labels.
The same five copied source texts, adjudicated gold and three immutable
trial-6 stores were reused; G1/G2/G3/G4 precision numbers below are
unchanged. The row-by-row machine output is reproducible with
`evidence/is1_review_score.py` and is recorded in the JSON companion.

## First contract, preserved: FAILED

**FAILED: pooled reviewable coverage was 34/51 = 66.67%, below the unchanged
90% acceptance bar.** This first contract alone did not establish IS-1.

The three retained trial-6 databases were opened with
`KGStore.open(..., read_only=True, immutable=True)`. The adjudicated gold JSON
and its five `sources/full/*.txt` files were copied as regular files under
`/private/tmp/t38-gold-20260928`; the strict loader validated all 34 spans.
Each gold null span was converted from gold UTF-8 byte offsets to store
character offsets and checked against the exact stored substring. The
qualified matcher uses the store's recorded alias resolution, core triple,
polarity and gold-specified qualifier subset. Under the first contract, a
source sentence was offered for review only when it had a measured-null cue
and no current no_effect/refutes edge citation overlapping it. Coverage counts a gold row once
when its assertion was extracted with the right polarity and qualified
identity **or** overlaps a candidate sentence. No model/provider calls ran.

| Trial | Gold null rows | Extracted | Flagged rows | Reviewable | Flagged sentences to read | Sentences not in gold |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| r1 | 17 | 0 | 10 | 10/17 | 28 | 23 |
| r2 | 17 | 3 | 8 | 10/17 | 33 | 28 |
| r3 | 17 | 4 | 11 | 14/17 | 29 | 23 |
| **Pooled** | **51** | **7** | **29** | **34/51** | **90** | **74** |

The first cue pass covered 25/51. A published source sentence describing
`0%, 4%, ... control` and another describing `0%, ... fresh weight reduction`
justify the general `0%` measured-outcome cue; adding it raised coverage to
34/51. All **17** remaining missed gold-row instances already have a
no_effect/refutes citation overlapping their sentence, despite the correct
cue also appearing in that sentence. Thus expanding cues cannot flag those
sentences under the specified detector contract. A reviewer must inspect
additional treatment arms within an already-cited sentence, or a later
review policy must address this gap; neither has been counted as covered.
`evidence/is1-human-review-2026-09-28.json` records the numbers and missed
source-row IDs.

Recomputed with `evidence/polarity6_score.py` against the same copied,
adjudicated qualified gold and three immutable stores: G1 **63/63** parsed,
G2 **432/432** polarity set, G3 polarity accuracy **12/12** (threshold
0.80), no_effect-to-supports flip **0/7** (threshold 0.15), G4 **0**
observed polarity collapses (60 coexisting supports/no_effect pairs).
All five precision conditions PASS. No_effect/refutes recall is **7/51**
and stays diagnostic; adjudicated gold has 17 no_effect and zero refutes
rows per run. This evidence tests precision and reviewable coverage
separately: precision alone does not turn the failed coverage gate green.
