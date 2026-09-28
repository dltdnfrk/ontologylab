# IS-1 human-review trial-6 measurement (2026-09-28)

**FAILED: pooled reviewable coverage is 34/51 = 66.67%, below the unchanged
90% acceptance bar.** This does not establish IS-1. The earlier FAILED
model trials and their results remain unchanged.

The three retained trial-6 databases were opened with
`KGStore.open(..., read_only=True, immutable=True)`. The adjudicated gold JSON
and its five `sources/full/*.txt` files were copied as regular files under
`/private/tmp/t38-gold-20260928`; the strict loader validated all 34 spans.
Each gold null span was converted from gold UTF-8 byte offsets to store
character offsets and checked against the exact stored substring. The
qualified matcher uses the store's recorded alias resolution, core triple,
polarity and gold-specified qualifier subset. A source sentence is offered for
review only when it has a measured-null cue and no current no_effect/refutes
edge citation overlapping that sentence. Coverage counts a gold row once
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
