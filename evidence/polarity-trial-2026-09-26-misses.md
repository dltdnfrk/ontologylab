# Todo 16: all 102 original polarity misses

Gold numbers are the unchanged 1-based order in `tests/gold/agrochem-polarity/gold.json`. R1/R2/R3 are the retained stores named in the trial addendum. Full edge IDs, exact resolved endpoint IDs, all tied identity neighbors, and scorer outputs are in [the JSON receipt](polarity-trial-2026-09-26-rescore.json).

## Diagnostic method

Exact identity uses the project normalize_name keys and node_aliases, canonical names first, with ambiguous same-schema/type aliases refused. Identity neighbors are ranked only by the number of exact endpoint identities shared (forward or reverse), then exact relation type; every tie is retained. No edit distance, token similarity, fuzzy or semantic matching is used. An empty neighbor list means no endpoint resolves, not permission to infer one.

The source-linked candidate column explains the original miss after inspecting the frozen source spans; it is NOT an additional scorer match. Where exact identity cannot select a unique neighbor, the candidate is an explicitly labeled diagnostic example. Species abbreviations, omitted population scope, and disease wording stay unmatched without a recorded alias. Combination treatments cannot be replaced by single ingredients.

Primary categories are mutually exclusive: absent assertion (missing combination or missing candidate edge), else relation-type mismatch (also record any changed endpoint), else entity surface mismatch. There are no reversed exact endpoint pairs. Surface mismatch does not establish semantic equivalence: population scope was lost in 17 of these instances. All 21 relation-type rows also lose endpoint detail (species prefix or oviposition); they are not recoverable by relation remapping.

| Primary original miss | R1 | R2 | R3 | Total |
| --- | ---: | ---: | ---: | ---: |
| Entity surface mismatch | 23 | 24 | 22 | 69 |
| Relation-type mismatch | 7 | 7 | 7 | 21 |
| Direction mismatch | 0 | 0 | 0 | 0 |
| Truly absent | 4 | 3 | 5 | 12 |
| Total | 34 | 34 | 34 | 102 |

Surface subgroups: 7 recorded abbreviation aliases (all recovered in R1), 36 unrecorded species abbreviations, 9 disease/strain expressions, 17 population-scope losses, and 0 case/punctuation-only failures. After repair: 7 matched and 95 missing (62 surface, 21 relation type, 0 direction, 12 absent).

## Frozen gold index

| Gold | Paper | Source / relation / target | Polarity |
| ---: | --- | --- | --- |
| 1 | PMC12632097 | prochloraz / inhibits / Lecanicillium fungicola isolate 620 | supports |
| 2 | PMC12632097 | metrafenone / inhibits / Lecanicillium fungicola isolate 620 | supports |
| 3 | PMC12632097 | prochloraz / inhibits / Lecanicillium fungicola isolate 1722 | supports |
| 4 | PMC12632097 | prochloraz / controls / dry bubble disease | no_effect |
| 5 | PMC12632097 | Bacillus velezensis QST 713 / controls / dry bubble disease | no_effect |
| 6 | PMC12632097 | Bacillus velezensis Kos / controls / dry bubble disease | no_effect |
| 7 | PMC12546283 | cyantraniliprole / inhibits / Drosophila suzukii oviposition | no_effect |
| 8 | PMC12546283 | spinosad / inhibits / Drosophila suzukii oviposition | no_effect |
| 9 | PMC12546283 | lambda-cyhalothrin / inhibits / Drosophila suzukii oviposition | supports |
| 10 | PMC12546283 | deltamethrin / inhibits / Drosophila suzukii oviposition | supports |
| 11 | PMC12546283 | deltamethrin + PB / controls / Drosophila suzukii | refutes |
| 12 | PMC12546283 | PB / controls / Drosophila suzukii | no_effect |
| 13 | PMC12546283 | cyantraniliprole + PB / controls / Drosophila suzukii | supports |
| 14 | PMC12563837 | clodinafop-propargyl / controls / R blackgrass population | no_effect |
| 15 | PMC12563837 | fenoxaprop-P-ethyl / controls / R blackgrass population | no_effect |
| 16 | PMC12563837 | pinoxaden / controls / R blackgrass population | no_effect |
| 17 | PMC12563837 | PBO / controls / R blackgrass population | no_effect |
| 18 | PMC12563837 | prosulfocarb / controls / R blackgrass population | supports |
| 19 | PMC12563837 | chlorotoluron + diflufenican / controls / R blackgrass population | supports |
| 20 | PMC12563837 | R blackgrass population / damages / winter wheat | supports |
| 21 | PMC12713700 | indaziflam / controls / Poa annua | no_effect |
| 22 | PMC12713700 | glufosinate / controls / Poa annua | no_effect |
| 23 | PMC12713700 | fluridone / controls / Poa annua | refutes |
| 24 | PMC12713700 | rimsulfuron / controls / Poa annua | supports |
| 25 | PMC12713700 | glyphosate / controls / Poa annua | supports |
| 26 | PMC12713700 | napropamide / controls / Poa annua | supports |
| 27 | PMC12713700 | dichlobenil / controls / Poa annua | supports |
| 28 | PMC12713700 | pyroxasulfone / controls / Poa annua | supports |
| 29 | PMC11298438 | Botrytis cinerea / resistant_to / fludioxonil | refutes |
| 30 | PMC11298438 | Botrytis cinerea / resistant_to / fenhexamid | refutes |
| 31 | PMC11298438 | Botrytis cinerea / resistant_to / iprodione | refutes |
| 32 | PMC11298438 | Botrytis cinerea / resistant_to / pyraclostrobin | supports |
| 33 | PMC11298438 | Botrytis cinerea / resistant_to / boscalid | supports |
| 34 | PMC11298438 | Botrytis cinerea / resistant_to / thiabendazole | supports |

## Per-instance miss table

IDs below are unique 8-character prefixes within their run. The exact-neighbor column retains ties. Candidate polarity is reported without selecting the label that agrees with gold.

| Run | Gold | Primary original miss | Exact identity neighbors | Source-linked candidate (diagnostic only unless credited) | Corrected match |
| --- | ---: | --- | --- | --- | --- |
| R1 | 1 | relation-type mismatch | 2d1524ef, 668e9f95, 71039d69, dea6c52a | 71039d69: Prochloraz / controls / isolate 620 [supports] | no |
| R1 | 2 | relation-type mismatch | 95a34602 | 95a34602: Metrafenone / controls / isolate 620 [supports] | no |
| R1 | 3 | relation-type mismatch | 2d1524ef, 668e9f95, 71039d69, dea6c52a | 668e9f95: Prochloraz / controls / isolate 1722 [supports] | no |
| R1 | 4 | entity surface mismatch | 2d1524ef, 668e9f95, 71039d69 | 2d1524ef: Prochloraz / controls / bubble development [no_effect] | no |
| R1 | 5 | entity surface mismatch | none | 9c2e9bc2: B. velezensis QST 713 / controls / bubble development [no_effect] | no |
| R1 | 6 | entity surface mismatch | none | 7033d2bb: Kos / controls / bubble development [no_effect] | no |
| R1 | 7 | relation-type mismatch | 4b031c1c, f679be94 | 4b031c1c: cyantraniliprole / controls / D. suzukii [no_effect] | no |
| R1 | 8 | relation-type mismatch | 292b5722, 4e830b94 | 292b5722: spinosad / controls / D. suzukii [no_effect] | no |
| R1 | 9 | relation-type mismatch | f3407e66 | f3407e66: lambda-cyhalothrin / controls / D. suzukii [supports] | no |
| R1 | 10 | relation-type mismatch | 2be28b5c, cf1f86d7 | 2be28b5c: deltamethrin / controls / D. suzukii [supports] | no |
| R1 | 11 | truly absent | 292b5722, 2be28b5c, 4b031c1c, 7fbda0da, f3407e66, fc741bf3 | None: Combination entity is absent; ingredient-only or synergizes_with rows cannot stand in for the combination. | no |
| R1 | 12 | entity surface mismatch | 7fbda0da | 7fbda0da: PB / controls / D. suzukii [no_effect] | yes |
| R1 | 13 | truly absent | 292b5722, 2be28b5c, 4b031c1c, 7fbda0da, f3407e66, fc741bf3 | None: Combination entity is absent; ingredient-only or synergizes_with rows cannot stand in for the combination. | no |
| R1 | 14 | entity surface mismatch | 55515ba0 | 55515ba0: clodinafop-propargyl / controls / blackgrass [supports] | no |
| R1 | 15 | entity surface mismatch | 6eb97c8d | 6eb97c8d: fenoxaprop-P-ethyl / controls / blackgrass [supports] | no |
| R1 | 16 | entity surface mismatch | 1f6768a0 | 1f6768a0: pinoxaden / controls / blackgrass [supports] | no |
| R1 | 17 | entity surface mismatch | f10a9d86 | f10a9d86: PBO / controls / blackgrass [no_effect] | no |
| R1 | 18 | entity surface mismatch | e814096c | e814096c: prosulfocarb / controls / blackgrass [supports] | no |
| R1 | 19 | truly absent | none | None: Combination entity is absent; ingredient-only or synergizes_with rows cannot stand in for the combination. | no |
| R1 | 20 | entity surface mismatch | 128b95d9 | 128b95d9: blackgrass / damages / winter wheat [supports] | no |
| R1 | 21 | entity surface mismatch | c97f0070 | c97f0070: indaziflam / controls / P. annua [supports] | no |
| R1 | 22 | entity surface mismatch | 1ce2a77a | 1ce2a77a: glufosinate / controls / P. annua [no_effect] | no |
| R1 | 23 | truly absent | none | None: No extracted edge for the diagnostic target; other relations/targets do not supply this assertion. | no |
| R1 | 24 | entity surface mismatch | e0d6faad | e0d6faad: rimsulfuron / controls / P. annua [supports] | no |
| R1 | 25 | entity surface mismatch | e09dc063 | e09dc063: glyphosate / controls / P. annua [supports] | no |
| R1 | 26 | entity surface mismatch | 2579cede | 2579cede: napropamide / controls / P. annua [supports] | no |
| R1 | 27 | entity surface mismatch | 3988c2c4 | 3988c2c4: dichlobenil / controls / P. annua [supports] | no |
| R1 | 28 | entity surface mismatch | 8906faa7 | 8906faa7: pyroxasulfone / controls / P. annua [supports] | no |
| R1 | 29 | entity surface mismatch | ce12d72b | ce12d72b: B. cinerea / resistant_to / fludioxonil [refutes] | yes |
| R1 | 30 | entity surface mismatch | c1f86371 | c1f86371: B. cinerea / resistant_to / fenhexamid [refutes] | yes |
| R1 | 31 | entity surface mismatch | d230ffd8 | d230ffd8: B. cinerea / resistant_to / iprodione [supports] | yes |
| R1 | 32 | entity surface mismatch | fa3f6c68 | fa3f6c68: B. cinerea / resistant_to / pyraclostrobin [supports] | yes |
| R1 | 33 | entity surface mismatch | df2dccac | df2dccac: B. cinerea / resistant_to / boscalid [supports] | yes |
| R1 | 34 | entity surface mismatch | 04204072 | 04204072: B. cinerea / resistant_to / thiabendazole [supports] | yes |
| R2 | 1 | relation-type mismatch | 408ce9db, 6f543506, c7c5d180, e7f0cf1e | c7c5d180: Prochloraz / controls / isolate 620 [supports] | no |
| R2 | 2 | relation-type mismatch | 8d0c1b20 | 8d0c1b20: Metrafenone / controls / isolate 620 [supports] | no |
| R2 | 3 | relation-type mismatch | 408ce9db, 6f543506, c7c5d180, e7f0cf1e | 408ce9db: Prochloraz / controls / isolate 1722 [supports] | no |
| R2 | 4 | entity surface mismatch | 408ce9db, c7c5d180, e7f0cf1e | e7f0cf1e: Prochloraz / controls / bubble development [no_effect] | no |
| R2 | 5 | entity surface mismatch | none | 463aa02f: B. velezensis QST 713 / controls / bubble development [no_effect] | no |
| R2 | 6 | entity surface mismatch | none | 8cbd0c61: Kos / controls / bubble development [no_effect] | no |
| R2 | 7 | relation-type mismatch | 0d705b2f, 2110232c, 81bf8fff | 0d705b2f: cyantraniliprole / controls / D. suzukii [supports]; 2110232c: cyantraniliprole / controls / D. suzukii [no_effect] | no |
| R2 | 8 | relation-type mismatch | c98d0022 | c98d0022: spinosad / controls / D. suzukii [supports] | no |
| R2 | 9 | relation-type mismatch | 0e4bbe8b | 0e4bbe8b: lambda-cyhalothrin / controls / D. suzukii [supports] | no |
| R2 | 10 | relation-type mismatch | 85652999, d3f7e28e | 85652999: deltamethrin / controls / D. suzukii [supports]; d3f7e28e: deltamethrin / controls / D. suzukii [no_effect] | no |
| R2 | 11 | truly absent | none | None: Combination entity is absent; ingredient-only or synergizes_with rows cannot stand in for the combination. | no |
| R2 | 12 | entity surface mismatch | ebf41aac | ebf41aac: PB / controls / D. suzukii [no_effect] | no |
| R2 | 13 | truly absent | none | None: Combination entity is absent; ingredient-only or synergizes_with rows cannot stand in for the combination. | no |
| R2 | 14 | entity surface mismatch | a5f9773b | a5f9773b: clodinafop-propargyl / controls / blackgrass [supports] | no |
| R2 | 15 | entity surface mismatch | 918b56e1 | 918b56e1: fenoxaprop-P-ethyl / controls / blackgrass [supports] | no |
| R2 | 16 | entity surface mismatch | fa84cf9c | fa84cf9c: pinoxaden / controls / blackgrass [supports] | no |
| R2 | 17 | entity surface mismatch | 6692f31e | 6692f31e: PBO / controls / blackgrass [no_effect] | no |
| R2 | 18 | entity surface mismatch | f7f4d6f7 | f7f4d6f7: prosulfocarb / controls / blackgrass [supports] | no |
| R2 | 19 | truly absent | none | None: Combination entity is absent; ingredient-only or synergizes_with rows cannot stand in for the combination. | no |
| R2 | 20 | entity surface mismatch | da5139b3 | da5139b3: blackgrass / damages / winter wheat [supports] | no |
| R2 | 21 | entity surface mismatch | 25f5705b | 25f5705b: indaziflam / controls / P. annua [supports] | no |
| R2 | 22 | entity surface mismatch | 34af91d5 | 34af91d5: glufosinate / controls / P. annua [refutes] | no |
| R2 | 23 | entity surface mismatch | 087a1774 | 087a1774: Fluridone / controls / P. annua [refutes] | no |
| R2 | 24 | entity surface mismatch | 9451e983 | 9451e983: rimsulfuron / controls / P. annua [supports] | no |
| R2 | 25 | entity surface mismatch | 99221888 | 99221888: glyphosate / controls / P. annua [supports] | no |
| R2 | 26 | entity surface mismatch | 45a8d024 | 45a8d024: napropamide / controls / P. annua [supports] | no |
| R2 | 27 | entity surface mismatch | 29b713bb | 29b713bb: dichlobenil / controls / P. annua [supports] | no |
| R2 | 28 | entity surface mismatch | e657036e | e657036e: pyroxasulfone / controls / P. annua [supports] | no |
| R2 | 29 | entity surface mismatch | 33f8c570 | 33f8c570: B. cinerea / resistant_to / fludioxonil [refutes] | no |
| R2 | 30 | entity surface mismatch | afda32d1 | afda32d1: B. cinerea / resistant_to / fenhexamid [refutes] | no |
| R2 | 31 | entity surface mismatch | 9f1b70f2 | 9f1b70f2: B. cinerea / resistant_to / iprodione [supports] | no |
| R2 | 32 | entity surface mismatch | e62b9707 | e62b9707: B. cinerea / resistant_to / pyraclostrobin [supports] | no |
| R2 | 33 | entity surface mismatch | 1b70f867 | 1b70f867: B. cinerea / resistant_to / boscalid [supports] | no |
| R2 | 34 | entity surface mismatch | 13709ede | 13709ede: B. cinerea / resistant_to / thiabendazole [supports] | no |
| R3 | 1 | relation-type mismatch | 0dce97b4, 184b7aa5, a0b0fe95, defdda65 | 184b7aa5: Prochloraz / controls / isolate 620 [supports] | no |
| R3 | 2 | relation-type mismatch | 0452d467 | 0452d467: Metrafenone / controls / isolate 620 [supports] | no |
| R3 | 3 | relation-type mismatch | 0dce97b4, 184b7aa5, a0b0fe95, defdda65 | a0b0fe95: Prochloraz / controls / isolate 1722 [supports] | no |
| R3 | 4 | entity surface mismatch | 184b7aa5, a0b0fe95, defdda65 | defdda65: Prochloraz / controls / bubble development [no_effect] | no |
| R3 | 5 | entity surface mismatch | none | a07a96e4: B. velezensis QST 713 / controls / bubble development [no_effect] | no |
| R3 | 6 | entity surface mismatch | none | be0c1363: Kos / controls / bubble development [no_effect] | no |
| R3 | 7 | relation-type mismatch | 09ba63fe, 8706045b | 8706045b: cyantraniliprole / controls / D. suzukii [no_effect] | no |
| R3 | 8 | relation-type mismatch | 5fe6e387, c5e8e6c1 | 5fe6e387: spinosad / controls / D. suzukii [no_effect] | no |
| R3 | 9 | relation-type mismatch | a186cef9 | a186cef9: lambda-cyhalothrin / controls / D. suzukii [supports] | no |
| R3 | 10 | relation-type mismatch | 67677515 | 67677515: deltamethrin / controls / D. suzukii [supports] | no |
| R3 | 11 | truly absent | none | None: Combination entity is absent; ingredient-only or synergizes_with rows cannot stand in for the combination. | no |
| R3 | 12 | truly absent | 461eac2e | None: No extracted edge for the diagnostic target; other relations/targets do not supply this assertion. | no |
| R3 | 13 | truly absent | none | None: Combination entity is absent; ingredient-only or synergizes_with rows cannot stand in for the combination. | no |
| R3 | 14 | entity surface mismatch | 57728c0a | 57728c0a: clodinafop-propargyl / controls / blackgrass [supports] | no |
| R3 | 15 | entity surface mismatch | 81d65066 | 81d65066: fenoxaprop-P-ethyl / controls / blackgrass [supports] | no |
| R3 | 16 | entity surface mismatch | ce93420f | ce93420f: pinoxaden / controls / blackgrass [supports] | no |
| R3 | 17 | truly absent | 6fc53e9f, fe92c17d | None: No extracted edge for the diagnostic target; other relations/targets do not supply this assertion. | no |
| R3 | 18 | entity surface mismatch | 8cb07c8f | 8cb07c8f: prosulfocarb / controls / blackgrass [supports] | no |
| R3 | 19 | truly absent | none | None: Combination entity is absent; ingredient-only or synergizes_with rows cannot stand in for the combination. | no |
| R3 | 20 | entity surface mismatch | 7025ae20 | 7025ae20: blackgrass / damages / winter wheat [supports] | no |
| R3 | 21 | entity surface mismatch | e7b5d3c9 | e7b5d3c9: indaziflam / controls / P. annua [supports] | no |
| R3 | 22 | entity surface mismatch | 8f4fba97 | 8f4fba97: glufosinate / controls / P. annua [refutes] | no |
| R3 | 23 | entity surface mismatch | bec8c2a0 | bec8c2a0: fluridone / controls / P. annua [refutes] | no |
| R3 | 24 | entity surface mismatch | 9dfadbb2 | 9dfadbb2: rimsulfuron / controls / P. annua [supports] | no |
| R3 | 25 | entity surface mismatch | 33ab85f7 | 33ab85f7: glyphosate / controls / P. annua [supports] | no |
| R3 | 26 | entity surface mismatch | aead9210 | aead9210: napropamide / controls / P. annua [supports] | no |
| R3 | 27 | entity surface mismatch | ef629966 | ef629966: dichlobenil / controls / P. annua [supports] | no |
| R3 | 28 | entity surface mismatch | 7ad97795 | 7ad97795: pyroxasulfone / controls / P. annua [supports] | no |
| R3 | 29 | entity surface mismatch | 686c6611 | 686c6611: B. cinerea / resistant_to / fludioxonil [refutes] | no |
| R3 | 30 | entity surface mismatch | 240c6021 | 240c6021: B. cinerea / resistant_to / fenhexamid [refutes] | no |
| R3 | 31 | entity surface mismatch | 8c4f8b29 | 8c4f8b29: B. cinerea / resistant_to / iprodione [supports] | no |
| R3 | 32 | entity surface mismatch | 79c35885 | 79c35885: B. cinerea / resistant_to / pyraclostrobin [supports] | no |
| R3 | 33 | entity surface mismatch | 8b8b92ea | 8b8b92ea: B. cinerea / resistant_to / boscalid [supports] | no |
| R3 | 34 | entity surface mismatch | 34ac146b | 34ac146b: B. cinerea / resistant_to / thiabendazole [supports] | no |
