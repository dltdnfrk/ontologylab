# Wave 2.1 Step 7 evidence index

Authoritative closer for the committed Step 7 product/test state. This index
does not extend Step 7 semantics and does not authorize Step 8 publication or
Step 9 cutover behavior.

## Final authority

| Fact | Value |
|---|---|
| Product HEAD | `362b0a679483139e51d8e37748674a867d6a9b2f` |
| Subject | `fix(extraction): preserve exact receipt identity` |
| Tree | `dce1386961684e924108ded625e56dab4031384d` |
| Parent | `5a6378964bfc41fe2a679453a88235c548a59f4b` |
| Step 7 product commit | `4878c2f262e6909deb94ff61ef6d04a7e990edd7` |
| SSE test-seam commit | `5a6378964bfc41fe2a679453a88235c548a59f4b` |
| Final repair perimeter | `1bd10421c5075045e550c2b4015270dd251409c4157622e87c79fc21dc47126b` |
| Repair perimeter recipe | SHA-256 of `LC_ALL=C` sorted `path<TAB>content-sha256\n` for the 21 repair paths |
| Full-suite perimeter | `9d3f579022ae33f8280753509dac75e44c4c51c5e3884253b57da930349e5867` |
| Full-suite recipe | SHA-256 of `LC_ALL=C` sorted `git ls-tree -r HEAD -- ontologylab tests scripts pyproject.toml` |
| Exact suite | `2650 passed, 1 skipped, 2 xfailed`, exit 0 |
| Suite duration | `1274.66s` |
| Loop | `wave21-step7-representation-grounding-20260824` |
| Closure goal | `G007` |

Execution authority, with blueprint section 0 winning on conflict:

- `docs/OMO-INGESTION-WAVE-2.1-MASS-ULW-INTEGRATED-ANALYSIS-2026-08-20.md`
- `.omo/mass-ulw/20260820-ingestion-integration/07-synthesis-blueprint.md`
- `.omo/plans/wave21-ingestion-steps5-10.md` Task 7

Consumed baseline:

- Step 6 evidence index:
  `.omo/evidence/ulw/wave21-step6-ingestion-service-20260821/G007/a1/step6-evidence-index.md`
- Step 6 evidence commit:
  `63e326f27c60b81f8a3e3daaf27518e82564da5c`

## Conventional product/test chain

| Task | Commit | Tree | Perimeter | Subject |
|---|---|---|---|---|
| 2 | `49ac5249fbfaecf0e18a00d08392166ea79250d5` | `2023a1bbf0e851c8bcb24b16ea072bcbc2953dc7` | `1287ca36f8f7062cf5de44140d7fe2ac4fa4494bc359f802bf2d39ce736494c8` | `feat(extraction): bind runs and chunks to representations` |
| 3 | `1afd0f85b038475a3b0a43f477febd1b25bfce01` | `d60bc0ebd5961971f2809461cca842a22608d30a` | `0021ce5daae3e4031e05a6ffe1c7e92e35cf1a29e55bfedda20660519a122084` | `feat(extraction): receipt preferred representation selection` |
| 4 | `7c159fd3efa24a5b9839e0ae32643e7f90560124` | `64166739485e405086196576019f888f6ac6c426` | `bbf7f76bf97397001a50d495cace5e94542b058c239417618cddb460ec5f8487` | `feat(citations): seal representation grounding receipts` |
| 5 | `0a3c7a21d5ee8fbcfb7aa7bf521921e0e333ea29` | `be6cc43cf4fad81a6f81179e57438af2bdd46ef2` | `82ba0621f5e3a312973e9df4d0df412ae4c992d6ff9047a797b258efdab6835c` | `feat(review): require append-only grounding decisions` |
| 6 | `8f0e45fdfa1d70e39a91c03737ecb31cb1add3fb` | `c69020eb85c3f1d78893f256310d8a4b8d67eeb8` | `7edeb5bede362b8e5e7aef2e92206dccca52c79d35a16660aef9564217cadb68` | `feat(migration): backfill historical grounding receipts` |
| 7 integration | `4878c2f262e6909deb94ff61ef6d04a7e990edd7` | `4289084a254738908b811f1ae4682562fda5f751` | `da88d057e89491a35acb0feb7083e3159a70679a85cc8746d7c2c99606ba6f6f` | `feat(extraction): complete representation-grounded review flow` |
| suite seam | `5a6378964bfc41fe2a679453a88235c548a59f4b` | `d295cb05ba5967f00cec9c69f21291d8890e2143` | `tests/test_server.py` `8a420db2bb95e77817afb369061dee0ba772b134e4520ea54c210393689eb3cb` | `test(server): synchronize jobs stream change` |
| final repair | `362b0a679483139e51d8e37748674a867d6a9b2f` | `dce1386961684e924108ded625e56dab4031384d` | `1bd10421c5075045e550c2b4015270dd251409c4157622e87c79fc21dc47126b` | `fix(extraction): preserve exact receipt identity` |

Every product/test commit has a separate boundary report and independent
commit verifier. `origin/main` remained
`4ee5465b9727a2ca3c00e7eea0f3893e2301c148`; no push occurred.

## Task receipts

Hashes are SHA-256 of the named evidence file under
`.omo/evidence/start-work/wave21-ingestion-steps5-10/`.

| Task | Executor / repair authority | Independent verifier | Product commit | Commit verifier |
|---|---|---|---|---|
| 2 run/chunk | `task-2-executor.md` `9339fc228bc05c8e25fd5192289f9f5bb9c28ac22bd2228b7aeb9f7a7ce358c0` | `task-2-verifier.md` `92f42339da0ddafc865c8e824c83b328a2380af0876ba892ed9f19976f80eba1` | `task-2-product-commit.md` `228086b00f2d17aa9c7f3d125a15871eacbccd7411b42f77dcfbb95de10f1821` | `task-2-commit-verifier.md` `f9bd0e1519cd8997586e39f7bdfabb1cd7bbc67db3b7254f09c7048035f40b28` |
| 3 selection/C-024 | `task-3-repair.md` `162a3e750e3de9cdb507a2cdf90a832466d5ee6d6bf474855b2e8587bdc5d523` | `task-3-repair-verifier.md` `d2929a06151b8289895af2eec66de0db38b859c1175252ac5a02ca23efdcfb04` | `task-3-product-commit.md` `624a0e62803ed89c1b04e48082370e6ad6836249b0b82e1f0c184a2972f8792e` | `task-3-commit-verifier.md` `ec31486afb44a782e2f4bf38826689b48c6a78bfd5b765f3ab8cb477dbf1372c` |
| 4 Citation | `task-4-repair.md` `959f5db0e1ab2251c529559fe6d14f7ade00b11d98898907bb3738610ab41302` | `task-4-repair-verifier.md` `779a30a7829fc47a63853d6003e403becd95c1764e13ec3d984b9b6fd5990a29` | `task-4-product-commit.md` `52437d986b8e5e349c1e1b83344bc409067ddc8e4a61b34ecbb887f0a5c0d40f` | `task-4-commit-verifier.md` `39e80929609aba7ee8fe89b52b8c6df7b32516bea980c82f1064f9dfabe6c719` |
| 5 grounded review | `task-5-repair.md` `746752371d8fda80552a4c0ddfbc349ba52a5c7a63bdcc96d184ab07118f38ae` | `task-5-repair-verifier.md` `5c1d19da9fd3a2214da7ee725f8fb6b20b3607039070447c23c9c2186cd11289` | `task-5-product-commit.md` `821986773c7d2aab1db47a55d9fd00a98155d7ea6f395a7ceec31782169fb8e4` | `task-5-commit-verifier.md` `c7db2dade1358d2b6b2593f48a5014e75790a788b9605779e7eb5c2ff4814a3a` |
| 6 H1 | `task-6-repair.md` `59320d4c084949c6bb5437cb7f8bd075f2d9a14a12e687a4fb6009f4e8c6a82b` | `task-6-repair-verifier.md` `4775cd3053b5efd15809a625ef5526f4246bcdfbc46c42cedd502c9fe72c1039` | `task-6-product-commit.md` `ca5fa405461fe3f8a19d6091c1225429bc9b867508db08eacb0aab634e695a94` | `task-6-commit-verifier.md` `f0826e822b8e4f9f2b4fb627810cfa21725134a014ba94f31eadb60322c49926` |
| 7 integration | `task-7-repair-2.md` `f57db204432ed702c468c5fe27265c7e1dcddcb8f2cc58921635fc15949d6af5` | `task-7-repair-2-verifier.md` `4e3910dc1f802f04e4dda6b192819fddce3a32378604bd78687512b00faa2f63` | `task-7-product-commit.md` `83b10c30ea6772060915edcc4087efa4358db6b9546c6ffc1e9078baa63dc440` | `task-7-commit-verifier.md` `572425ece54d610863a6f739d7e34494b07d86d7dadd760791bd6b4f985e6a41` |
| final identity repair | `task-7-security-repair-2.md` `356c23a9fcfa339a512848fc5d05ddbf9039bf75d62395a9d4455d7d88bc19dc` | code/security final below | `task-7-review-repair-commit.md` `563c0dd2d347cfd6f277cd3308544e965289244b094c8c4c5b32031183190b61` | `task-7-review-repair-commit-verifier.md` `2bf08af3c725649acaeca3e6930c443e14fdf18d0c9f777064769ee59b1a9cd0` |

## Product goals and mutation proof

### Representation-scoped extraction receipts

Runs bind immutable Representation, document hash, policy and config. Chunks
bind run, byte window, profile, text hash and plan receipt. Same
Representation/config retry converges; another Representation remains
distinct. Savepoints never take caller transaction ownership. Task 2 killed
and restored all seven receipt/schema/transaction mutants.

### F9 selection and C-024 research consumer

`preferred-representation-v1` is
`ready > usable full text > grade > source > stage > length > lexical hash`.
The publisher `publishedVersion` abstract beside unknown-stage PMC full text
selects and extracts only PMC on the real research path. Historical v1 is
stable when v2 differs. The isolated raw-path-read survivor found by the first
review was turned RED, repaired, killed and byte-restored before commit.

### Citation grounding

Citation receipts bind exact Representation/run/chunk/selection, window,
text, hash and policy. Multi-run or multi-selection context is typed
`AMBIGUOUS`; explicit exact context binds the current family. Tampered text,
cross-bind, stale context and partial writes fail closed. The final 21-path
repair freeze preserves these identities on HEAD.

### C-032 grounded append-only decisions

Ordinary cascades preflight every member and write zero on one invalid member.
Scoped waivers are explicit, durable, include exact defects, and are
pack-ineligible. Generic approval cannot waive. Decisions are immutable and
idempotent; `grounded_review_current` moves inside the same SAVEPOINT.
Reject/quarantine/compensate use only current active-member cites and remain
pack-ineligible.

### H1 backup-copy rehearsal

H1 uses SQLite backup-API copies only. It preserves document/node/edge/citation
anchors, seals raw bytes, links exact run/chunk/Citation/review families and
quarantines unverifiable spans. Current-pointer exact match wins; historical
fallback must be unique. Existing history prevents minting an eligible twin.
Colliding stale approvals/waivers cannot displace the live scoped waiver.
Interrupt/resume and pass two are idempotent.

Named implementation mutants for run lookup, chunk fields, altered selected
text, root-only cascade, generic waiver, policy retarget, stage-first F9,
hash-run H1, guessed spans, first-tip review, pointer omission, mint guard,
stored-cite bypass, pack eligibility and transaction leakage all died and were
restored. Final code/security reviews re-killed the 21-path decision set on
the exact bytes later committed as HEAD.

## Exact full suite

`task-7-final-full-suite.md`
SHA-256 `c047fe84a6fc5c6aa185a1d48195f89a4b9c4e2a223f25f8a10bcb955c47c261`
is the only final full-suite authority:

```text
2650 passed, 1 skipped, 2 xfailed, 1 warning in 1274.66s
PYTEST_STATUS=0
HEAD_BEFORE=HEAD_AFTER=362b0a679483139e51d8e37748674a867d6a9b2f
PERIMETER_BEFORE=PERIMETER_AFTER=9d3f579022ae33f8280753509dac75e44c4c51c5e3884253b57da930349e5867
WORKTREE_CODE_TEST_CLEAN_AFTER=true
```

The test-only commit `5a637896...` replaces a timing-luck SSE teardown wake
with an event handshake. It contains only `tests/test_server.py`; product jobs
code is unchanged. This final suite traversed the previously stalled boundary
and supersedes both interrupted attempts and the earlier 2630-test receipt.

## Final independent review bundle

| Lane | Receipt SHA-256 | Binding | Verdict |
|---|---|---|---|
| Goal | `task-7-final-goal-review.md` `4ce20fa4b2d36f6cb4376dba715b6d80bdbeb4fd65d911adeb775bf0b153f5a4` | HEAD/tree/`1bd10421`/`9d3f5790` | PASSED 0.92 |
| Code | `task-7-review-code-final.md` `aeb97646b9bc71a667df00462d42d65e57eb1eaa774849b2e52b6a608dc8c9fc` | 21/21 HEAD blobs | PASSED 0.94 |
| Manual QA | `task-7-final-manual-qa.md` `48f71153a869aac74acc86be4920e66882e7556e38939f321eb925c0ce51518a` | committed HEAD real surfaces | PASS |
| Security | `task-7-review-security-final.md` `522a1bef03c0552e4646b840ff61f8df8750165dd52b1b43e2a289deda3b0580` | 21/21 HEAD blobs | PASSED |
| Context | `task-7-final-context-review.md` `63c34690eaf164e440b245c3aca221dfee2bec519d12f22ebca0541530b35bb4` | HEAD/tree/two perimeters | PASS |
| Gate | `task-7-final-gate-review.md` `bb398a788b2b025a9c8f01818f07f448a4ec4863b7ea5a006193a20289e86430` | all current survivors | APPROVED |

Manual QA used installed CLI help/approve/migrate-h1, a real uvicorn server
with SSE subscribed before extraction, HTTP approve/repeat/tamper/
reject/compensate, and direct H1 classify/materialize/finalize. It observed
typed failures with zero partial writes and exact current machine IDs.

## Cleanup and protected boundary

- All Task 7 disposable roots, listeners and server processes are gone.
- PID `55560`, device `0x1ff51c806b197195`, remains on
  `127.0.0.1:8799`.
- Live Application Support inode/mtime remained unchanged; contents were not
  read.
- No external network action, production cutover, Step 9C action or authority
  flip occurred.
- Canonical planning documents were not edited.
- The six untracked `review_decision*` / `review_grounding` denylist drafts
  were not read, hashed, imported, staged or committed.
- Index and tracked product/test worktree were clean after final reviews.
- Unrelated untracked `.gjc`, `.sisyphus`, `artifacts`, docs, graphify and
  `uv.lock` remain preserved.

See sibling `scope-cleanup.txt`, `commit-boundary.txt`,
`quality-gate.json`, and `final-suite.txt`.

## Superseded evidence

Do not use these as final authority:

- task-local verifier reports marked `needs-fix` before their repair verifier
- `task-7-review-goal.md` and `task-7-review-qa.md` on parent `5a637896...`
- the 2630-test parent receipt
- interrupted suite receipts
- the temporary locale-dependent `1eac91b2...` perimeter diagnosis
- append-only ledger events naming `1eac91b2...` before later correction

The required 21-path perimeter is
`1bd10421c5075045e550c2b4015270dd251409c4157622e87c79fc21dc47126b`.

## Honest boundary

This index does not claim:

- evidence-self-contained pack v2
- strict dynamic pack inventory or standalone verifier
- one immutable verified reader snapshot
- F11 generation readiness
- C-036 reviewed/sourced publication authority
- full v2 authority or production migration
- Step 9A/9B completion
- Step 9C authorization or execution

Step 8 kickoff:
`.omo/ulw-loop/wave21-step7-representation-grounding-20260824/step8-kickoff.md`.

