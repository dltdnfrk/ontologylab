# Todo 20: relation and scope extraction triage

Understood as: improve extraction guidance for the approved 59 miss instances, preserve the frozen scoring contract, and verify offline. This is not the todo 21 model rerun and does not claim recovered gold matches.

The immutable inputs are [the original miss table](polarity-trial-2026-09-26-misses.md) and [the rescore receipt](polarity-trial-2026-09-26-rescore.json). Run and gold numbers retain their original meanings. Counts are instances across three runs, not 59 distinct assertions.

## Changes and limits

- R: extract-v4 explicitly distinguishes assay/process inhibition from treatment control, follows active schema definitions, and refuses the undeclared relation label reduces. Relation definitions themselves are unchanged.
- Q: names and endpoint references retain the exact source's species, population, stage, isolate/strain, disease and process wording; narrower entities are not aliases of the species. The existing document-local abbreviation resolver still preserves suffixes.
- C: a source-tested combined formulation is one Product with the full mixture name; efficacy belongs to the mixture, not an ingredient. The v2 Product description now includes source-tested formulations without implying registration. V1 and relation/type identifiers are unchanged. No live schema installation or migration occurs.
- N: guidance separates treatment arms and explicitly retains ineffective and measured-null findings without borrowing another dose/trial's polarity.

No deterministic relation remapping, qualifier guessing, disease synonym insertion or combination reconstruction was added. The parser already keys entities by full normalized name and type, and the store preserves those keys. Repairing a lost endpoint after model output would require guessing which population/strain/mixture a broad name meant. The safer decision is to request the full source-grounded name before identity resolution.

Remaining-reason codes used in every row:

- U: recovery remains unmeasured until todo 21; a scripted engine proves transport/store preservation, not LLM compliance.
- X: only explicit chunk-local names can be copied. A missing species prefix or cross-sentence composition is not reconstructed. Complete context from todo 19 may help the model but does not authorize invented spans.
- D: no automatic equivalence between symptom wording and disease, or a short strain label and a full organism name. Gold identity remains unmatched if the required full name is absent from the chunk.
- M: the mixture must actually be stated and emitted; no ingredient or synergy edge can repair an absent mixture claim.
- A: general missing-edge recall is not deterministically repaired. N requests the finding, but no extra assertion may be fabricated from a gold row.

All 59 rows receive guidance, not retrospective score credit. The three non-combination absent edges (R1/G23, R3/G12, R3/G17) remain unaddressed by a case-specific mechanism; N is only general guidance. Nine disease/strain rows remain subject to D, and all 21 relation rows also need Q, not just a different relation label.

| Category | Instances |
| --- | ---: |
| Relation type plus endpoint loss | 21 |
| Population scope | 17 |
| Disease/strain expression | 9 |
| Absent (9 combinations, 3 other findings) | 12 |
| Total | 59 |

## Every targeted instance

| Run | Gold | Category | Original diagnostic | Change | Remaining reason |
| --- | ---: | --- | --- | --- | --- |
| R1 | 1 | relation type + endpoint | Prochloraz / controls / isolate 620 | R + Q + N | U, X |
| R1 | 2 | relation type + endpoint | Metrafenone / controls / isolate 620 | R + Q + N | U, X |
| R1 | 3 | relation type + endpoint | Prochloraz / controls / isolate 1722 | R + Q + N | U, X |
| R1 | 4 | disease/strain | Prochloraz / controls / bubble development | Q + N | U, D, X |
| R1 | 5 | disease/strain | B. velezensis QST 713 / controls / bubble development | Q + N | U, D, X |
| R1 | 6 | disease/strain | Kos / controls / bubble development | Q + N | U, D, X |
| R1 | 7 | relation type + endpoint | cyantraniliprole / controls / D. suzukii | R + Q + N | U, X |
| R1 | 8 | relation type + endpoint | spinosad / controls / D. suzukii | R + Q + N | U, X |
| R1 | 9 | relation type + endpoint | lambda-cyhalothrin / controls / D. suzukii | R + Q + N | U, X |
| R1 | 10 | relation type + endpoint | deltamethrin / controls / D. suzukii | R + Q + N | U, X |
| R1 | 11 | absent | No combination entity | C + Q + N | U, M, X |
| R1 | 13 | absent | No combination entity | C + Q + N | U, M, X |
| R1 | 14 | population scope | clodinafop-propargyl / controls / blackgrass | Q + N | U, X |
| R1 | 15 | population scope | fenoxaprop-P-ethyl / controls / blackgrass | Q + N | U, X |
| R1 | 16 | population scope | pinoxaden / controls / blackgrass | Q + N | U, X |
| R1 | 17 | population scope | PBO / controls / blackgrass | Q + N | U, X |
| R1 | 18 | population scope | prosulfocarb / controls / blackgrass | Q + N | U, X |
| R1 | 19 | absent | No combination entity | C + Q + N | U, M, X |
| R1 | 20 | population scope | blackgrass / damages / winter wheat | Q + N | U, X |
| R1 | 23 | absent | No edge; diagnostic target: fluridone / controls / P. annua | N (general only) | U, A, X |
| R2 | 1 | relation type + endpoint | Prochloraz / controls / isolate 620 | R + Q + N | U, X |
| R2 | 2 | relation type + endpoint | Metrafenone / controls / isolate 620 | R + Q + N | U, X |
| R2 | 3 | relation type + endpoint | Prochloraz / controls / isolate 1722 | R + Q + N | U, X |
| R2 | 4 | disease/strain | Prochloraz / controls / bubble development | Q + N | U, D, X |
| R2 | 5 | disease/strain | B. velezensis QST 713 / controls / bubble development | Q + N | U, D, X |
| R2 | 6 | disease/strain | Kos / controls / bubble development | Q + N | U, D, X |
| R2 | 7 | relation type + endpoint | cyantraniliprole / controls / D. suzukii | R + Q + N | U, X |
| R2 | 8 | relation type + endpoint | spinosad / controls / D. suzukii | R + Q + N | U, X |
| R2 | 9 | relation type + endpoint | lambda-cyhalothrin / controls / D. suzukii | R + Q + N | U, X |
| R2 | 10 | relation type + endpoint | deltamethrin / controls / D. suzukii | R + Q + N | U, X |
| R2 | 11 | absent | No combination entity | C + Q + N | U, M, X |
| R2 | 13 | absent | No combination entity | C + Q + N | U, M, X |
| R2 | 14 | population scope | clodinafop-propargyl / controls / blackgrass | Q + N | U, X |
| R2 | 15 | population scope | fenoxaprop-P-ethyl / controls / blackgrass | Q + N | U, X |
| R2 | 16 | population scope | pinoxaden / controls / blackgrass | Q + N | U, X |
| R2 | 17 | population scope | PBO / controls / blackgrass | Q + N | U, X |
| R2 | 18 | population scope | prosulfocarb / controls / blackgrass | Q + N | U, X |
| R2 | 19 | absent | No combination entity | C + Q + N | U, M, X |
| R2 | 20 | population scope | blackgrass / damages / winter wheat | Q + N | U, X |
| R3 | 1 | relation type + endpoint | Prochloraz / controls / isolate 620 | R + Q + N | U, X |
| R3 | 2 | relation type + endpoint | Metrafenone / controls / isolate 620 | R + Q + N | U, X |
| R3 | 3 | relation type + endpoint | Prochloraz / controls / isolate 1722 | R + Q + N | U, X |
| R3 | 4 | disease/strain | Prochloraz / controls / bubble development | Q + N | U, D, X |
| R3 | 5 | disease/strain | B. velezensis QST 713 / controls / bubble development | Q + N | U, D, X |
| R3 | 6 | disease/strain | Kos / controls / bubble development | Q + N | U, D, X |
| R3 | 7 | relation type + endpoint | cyantraniliprole / controls / D. suzukii | R + Q + N | U, X |
| R3 | 8 | relation type + endpoint | spinosad / controls / D. suzukii | R + Q + N | U, X |
| R3 | 9 | relation type + endpoint | lambda-cyhalothrin / controls / D. suzukii | R + Q + N | U, X |
| R3 | 10 | relation type + endpoint | deltamethrin / controls / D. suzukii | R + Q + N | U, X |
| R3 | 11 | absent | No combination entity | C + Q + N | U, M, X |
| R3 | 12 | absent | No edge; diagnostic target: PB / controls / D. suzukii | N (general only) | U, A, X |
| R3 | 13 | absent | No combination entity | C + Q + N | U, M, X |
| R3 | 14 | population scope | clodinafop-propargyl / controls / blackgrass | Q + N | U, X |
| R3 | 15 | population scope | fenoxaprop-P-ethyl / controls / blackgrass | Q + N | U, X |
| R3 | 16 | population scope | pinoxaden / controls / blackgrass | Q + N | U, X |
| R3 | 17 | absent | No edge; diagnostic target: PBO / controls / blackgrass | N (general only) | U, A, X |
| R3 | 18 | population scope | prosulfocarb / controls / blackgrass | Q + N | U, X |
| R3 | 19 | absent | No combination entity | C + Q + N | U, M, X |
| R3 | 20 | population scope | blackgrass / damages / winter wheat | Q + N | U, X |
