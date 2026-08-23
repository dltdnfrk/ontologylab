# Evidence commit boundary — wave21 steps 5-10 / task-7

Committer: omo senpi-task `st_01a030f2`
Date: 2026-08-24
Mode: base evidence-only conventional commit. No product, test, plan, boulder,
start-work ledger, or candidate-file edit. No amend, rebase, reset, checkout,
restore, stash, or push. Pytest not run.

## Verdict

The base evidence-only commit on `main` for Step 7 is:

`b328a8c66a20fbbc64b43f3ad14eb430828f9bc8`
`docs(evidence): close wave21 ingestion step 7`

Parent is the required product repair commit `362b0a6`. The 47 committed
paths are the independently confirmed stable Step 7 closure set from
`task-7-evidence-bundle-verifier.md`. Product and test bytes are identical
to `362b0a6`. No excluded path was staged or committed. `origin/main` was
not updated.

## Pre-commit boundary

| Fact | Required | Observed |
|---|---|---|
| HEAD before commit | `362b0a679483139e51d8e37748674a867d6a9b2f` | match (`git rev-parse HEAD`) |
| Parent of product | `5a6378964bfc41fe2a679453a88235c548a59f4b` | match |
| Product tree | `dce1386961684e924108ded625e56dab4031384d` | match (`git rev-parse HEAD^{tree}`) |
| Subject | `fix(extraction): preserve exact receipt identity` | match |
| Staged index | empty | empty |
| Branch | known | `main` |
| Upstream | known | `origin/main` = `4ee5465b9727a2ca3c00e7eea0f3893e2301c148` |
| Bundle verifier | `CONFIRMED` | `task-7-evidence-bundle-verifier.md` verdict `CONFIRMED` |
| Verifier self SHA-256 | `2158597fb0746430f8c51d2ea24136c7bf530b0f1466562e5985488456c973b6` | match |
| Sealed 46-path nonself perimeter | `9c0b4b8f796552d9bd6135d4464f8e0819a52cd96d92b106653a5964b3d4a49c` | match (6642 bytes) |
| Observed 47-path perimeter | `3866e5e8e41da5ad16b731348039bf36476a5d638b3675fe1ac20c54db945924` | match (6794 bytes) |
| Product/test perimeter | `9d3f579022ae33f8280753509dac75e44c4c51c5e3884253b57da930349e5867` | match; 387 `git ls-tree -r HEAD -- ontologylab tests scripts pyproject.toml` paths |
| Repair 21-path perimeter | `1bd10421c5075045e550c2b4015270dd251409c4157622e87c79fc21dc47126b` | match (2050 bytes) |
| Product/test WT | identical to `HEAD:` | `git diff --name-status HEAD -- ontologylab tests scripts pyproject.toml` empty |

`.omo/` is ignored (`.gitignore:28`). Staging used only
`git add -f -- <exact 47 paths>` after the hash/parse review below.

Every candidate existed, was nonempty, and matched the verifier SHA-256
table (46/46 non-self). JSON parse succeeded on `quality-gate.json`,
`aggregate-complete.json`, and `goals.json`. `ledger.jsonl` parsed as 12
JSON objects plus one documented blank `splitlines()` entry; bytes end
`\n\n`; digest still `5abad137…`.

`git diff --cached --check` reported trailing-blank-line warnings on 10
frozen files (including the documented extra ledger newline). Those bytes
are part of the sealed hashes. No file was edited.

Staged blob SHA-256 matched working-tree SHA-256 for all 47 paths
(0 mismatches). Extensions in the staged set: `.md` `.txt` `.json`
`.jsonl` only. Staged product/test/docs diff empty.

## Stable candidate list (verbatim, 47 paths)

Lexicographic list from `task-7-evidence-bundle-verifier.md`, used
verbatim as the `git add -f --` argument set:

1. `.omo/evidence/start-work/wave21-ingestion-steps5-10/task-2-commit-verifier.md`
2. `.omo/evidence/start-work/wave21-ingestion-steps5-10/task-2-executor.md`
3. `.omo/evidence/start-work/wave21-ingestion-steps5-10/task-2-product-commit.md`
4. `.omo/evidence/start-work/wave21-ingestion-steps5-10/task-2-verifier.md`
5. `.omo/evidence/start-work/wave21-ingestion-steps5-10/task-3-commit-verifier.md`
6. `.omo/evidence/start-work/wave21-ingestion-steps5-10/task-3-product-commit.md`
7. `.omo/evidence/start-work/wave21-ingestion-steps5-10/task-3-repair-verifier.md`
8. `.omo/evidence/start-work/wave21-ingestion-steps5-10/task-3-repair.md`
9. `.omo/evidence/start-work/wave21-ingestion-steps5-10/task-4-commit-verifier.md`
10. `.omo/evidence/start-work/wave21-ingestion-steps5-10/task-4-product-commit.md`
11. `.omo/evidence/start-work/wave21-ingestion-steps5-10/task-4-repair-verifier.md`
12. `.omo/evidence/start-work/wave21-ingestion-steps5-10/task-4-repair.md`
13. `.omo/evidence/start-work/wave21-ingestion-steps5-10/task-5-commit-verifier.md`
14. `.omo/evidence/start-work/wave21-ingestion-steps5-10/task-5-product-commit.md`
15. `.omo/evidence/start-work/wave21-ingestion-steps5-10/task-5-repair-verifier.md`
16. `.omo/evidence/start-work/wave21-ingestion-steps5-10/task-5-repair.md`
17. `.omo/evidence/start-work/wave21-ingestion-steps5-10/task-6-commit-verifier.md`
18. `.omo/evidence/start-work/wave21-ingestion-steps5-10/task-6-product-commit.md`
19. `.omo/evidence/start-work/wave21-ingestion-steps5-10/task-6-repair-verifier.md`
20. `.omo/evidence/start-work/wave21-ingestion-steps5-10/task-6-repair.md`
21. `.omo/evidence/start-work/wave21-ingestion-steps5-10/task-7-commit-verifier.md`
22. `.omo/evidence/start-work/wave21-ingestion-steps5-10/task-7-evidence-bundle-verifier.md`
23. `.omo/evidence/start-work/wave21-ingestion-steps5-10/task-7-final-context-review.md`
24. `.omo/evidence/start-work/wave21-ingestion-steps5-10/task-7-final-full-suite.md`
25. `.omo/evidence/start-work/wave21-ingestion-steps5-10/task-7-final-gate-review.md`
26. `.omo/evidence/start-work/wave21-ingestion-steps5-10/task-7-final-goal-review.md`
27. `.omo/evidence/start-work/wave21-ingestion-steps5-10/task-7-final-manual-qa.md`
28. `.omo/evidence/start-work/wave21-ingestion-steps5-10/task-7-hangfix-commit-verifier.md`
29. `.omo/evidence/start-work/wave21-ingestion-steps5-10/task-7-hangfix-commit.md`
30. `.omo/evidence/start-work/wave21-ingestion-steps5-10/task-7-product-commit.md`
31. `.omo/evidence/start-work/wave21-ingestion-steps5-10/task-7-repair-2-verifier.md`
32. `.omo/evidence/start-work/wave21-ingestion-steps5-10/task-7-repair-2.md`
33. `.omo/evidence/start-work/wave21-ingestion-steps5-10/task-7-review-code-final.md`
34. `.omo/evidence/start-work/wave21-ingestion-steps5-10/task-7-review-repair-commit-verifier.md`
35. `.omo/evidence/start-work/wave21-ingestion-steps5-10/task-7-review-repair-commit.md`
36. `.omo/evidence/start-work/wave21-ingestion-steps5-10/task-7-review-security-final.md`
37. `.omo/evidence/start-work/wave21-ingestion-steps5-10/task-7-security-repair-2.md`
38. `.omo/evidence/start-work/wave21-ingestion-steps5-10/task-7-wave21-ingestion-steps5-10.md`
39. `.omo/evidence/ulw/wave21-step7-representation-grounding-20260824/G007/a1/commit-boundary.txt`
40. `.omo/evidence/ulw/wave21-step7-representation-grounding-20260824/G007/a1/final-suite.txt`
41. `.omo/evidence/ulw/wave21-step7-representation-grounding-20260824/G007/a1/quality-gate.json`
42. `.omo/evidence/ulw/wave21-step7-representation-grounding-20260824/G007/a1/scope-cleanup.txt`
43. `.omo/evidence/ulw/wave21-step7-representation-grounding-20260824/G007/a1/step7-evidence-index.md`
44. `.omo/ulw-loop/wave21-step7-representation-grounding-20260824/aggregate-complete.json`
45. `.omo/ulw-loop/wave21-step7-representation-grounding-20260824/goals.json`
46. `.omo/ulw-loop/wave21-step7-representation-grounding-20260824/ledger.jsonl`
47. `.omo/ulw-loop/wave21-step7-representation-grounding-20260824/step8-kickoff.md`

Composition: 5 G007/a1 + 4 loop completion + 20 Task 2–6 index-cited
receipts + 18 Task 7 final/hangfix/closer/verifier.

`git diff --staged --name-only` before commit listed exactly those 47
paths. Exclusion regex over that list (`aggregate-active`, `brief.md`,
`boulder`, `start-work/ledger`, `plans/`, `drafts/`, `ontologylab/`,
`tests/`, `review_decision`, `review_grounding`): no hits.

## Excluded (not staged, not committed)

| Path / class | Reason |
|---|---|
| `aggregate-active.json` | sibling still `status=active` (Step 4/5/6 rule) |
| `brief.md` | loop brief, not a closure artifact |
| `.omo/start-work/ledger.jsonl` | excluded active ledger |
| `.omo/boulder.json` | excluded orchestration |
| `.omo/plans/`, `.omo/drafts/` | excluded planning/drafts |
| `task-{3,4,5,6,7}-executor.md` (except Task 2) | superseded by cited repair / repair-2 |
| `task-{3,4,5,6,7}-verifier.md` and related pre-fix receipts | superseded |
| `ontologylab/`, `tests/`, `scripts/`, `pyproject.toml`, `docs/` | product / tests / docs |
| six `review_decision*` / `review_grounding.py` | denylist; still `??` |
| `.gjc/`, `.sisyphus/`, `artifacts/`, `graphify-out/`, `uv.lock` | unrelated residuals |

All four named excluded `.omo` files still exist on disk and are absent
from `HEAD:` (`git cat-file -e` exit 128).

## Commit identity

| Field | Value |
|---|---|
| Commit | `b328a8c66a20fbbc64b43f3ad14eb430828f9bc8` |
| Tree | `e044733fb4d4762f18623dfb1b581c16da2912a6` |
| Parent | `362b0a679483139e51d8e37748674a867d6a9b2f` |
| Parent tree | `dce1386961684e924108ded625e56dab4031384d` |
| Subject | `docs(evidence): close wave21 ingestion step 7` |
| Author / committer | Hyunjun `<dltdnfrk@gmail.com>` |
| AuthorDate / CommitDate | 2026-08-24 08:29:40 +0900 |
| Diffstat | 47 files changed, 7142 insertions(+) |

Body (repo `docs(evidence)` style):

```
Freeze the final C-024/F9/C-032/H1 receipts, final suite/review gate,
aggregate completion, and Step 8 kickoff while preserving product and
test bytes.
```

### Committed path list with content SHA-256 and git blobs

`git show HEAD:<path>` SHA-256 matched the sealed table (and the
observed verifier self-hash) for 47/47. Working-tree bytes equal
committed bytes.

```
f9bd0e1519cd8997586e39f7bdfabb1cd7bbc67db3b7254f09c7048035f40b28  git=40a0705dcc29f04f63ff03c8001c5167451a5f52  task-2-commit-verifier.md
9339fc228bc05c8e25fd5192289f9f5bb9c28ac22bd2228b7aeb9f7a7ce358c0  git=577a8f8507f3eea0e1d0f4c699d5c67b7530f2de  task-2-executor.md
228086b00f2d17aa9c7f3d125a15871eacbccd7411b42f77dcfbb95de10f1821  git=7867ba429151b88be6a6456e90c50f303a041105  task-2-product-commit.md
92f42339da0ddafc865c8e824c83b328a2380af0876ba892ed9f19976f80eba1  git=4001ce7c256ae241af11ae86f97d4d0eabbda1f0  task-2-verifier.md
ec31486afb44a782e2f4bf38826689b48c6a78bfd5b765f3ab8cb477dbf1372c  git=2ba871816411bd07c754a9a8ecca337e3f871988  task-3-commit-verifier.md
624a0e62803ed89c1b04e48082370e6ad6836249b0b82e1f0c184a2972f8792e  git=2e92274828823cee90c5a96249d6fac6c7299758  task-3-product-commit.md
d2929a06151b8289895af2eec66de0db38b859c1175252ac5a02ca23efdcfb04  git=368ba23646e90ceab3004c19679ec0260f48adeb  task-3-repair-verifier.md
162a3e750e3de9cdb507a2cdf90a832466d5ee6d6bf474855b2e8587bdc5d523  git=0be165f2d43466fbbcbfe4b87b1d83ae5794f819  task-3-repair.md
39e80929609aba7ee8fe89b52b8c6df7b32516bea980c82f1064f9dfabe6c719  git=3875aa44d2038dd41963e03ae9bf696a7ee3481f  task-4-commit-verifier.md
52437d986b8e5e349c1e1b83344bc409067ddc8e4a61b34ecbb887f0a5c0d40f  git=c27d8dba48c15b90eec184505269bbc0a29ed303  task-4-product-commit.md
779a30a7829fc47a63853d6003e403becd95c1764e13ec3d984b9b6fd5990a29  git=58e19a5b89997a6c68ddad24981c2f08f8a76a2c  task-4-repair-verifier.md
959f5db0e1ab2251c529559fe6d14f7ade00b11d98898907bb3738610ab41302  git=d212abc61848ce856a880fe9a1e9f30ecd3711b5  task-4-repair.md
c7db2dade1358d2b6b2593f48a5014e75790a788b9605779e7eb5c2ff4814a3a  git=56dd192b8711e5fce2fb85522c86e8de570cc6a6  task-5-commit-verifier.md
821986773c7d2aab1db47a55d9fd00a98155d7ea6f395a7ceec31782169fb8e4  git=76294c46f41de7168e19ea411463a9a51b703466  task-5-product-commit.md
5c1d19da9fd3a2214da7ee725f8fb6b20b3607039070447c23c9c2186cd11289  git=33254ab8921e44e410eb928829b3e09efaa4763e  task-5-repair-verifier.md
746752371d8fda80552a4c0ddfbc349ba52a5c7a63bdcc96d184ab07118f38ae  git=eda922067477a8f40bd4fc2da7d0e9c254270932  task-5-repair.md
f0826e822b8e4f9f2b4fb627810cfa21725134a014ba94f31eadb60322c49926  git=2cb828a19764589ada81d032b95fa29cc5dfb0ae  task-6-commit-verifier.md
ca5fa405461fe3f8a19d6091c1225429bc9b867508db08eacb0aab634e695a94  git=ba79b33038f1aa42ef0b373f1734641caf563488  task-6-product-commit.md
4775cd3053b5efd15809a625ef5526f4246bcdfbc46c42cedd502c9fe72c1039  git=dfdcc919685c677187509e1ab37559701d702f4b  task-6-repair-verifier.md
59320d4c084949c6bb5437cb7f8bd075f2d9a14a12e687a4fb6009f4e8c6a82b  git=61110a44a8f678c3365f3ce836f717e622181de2  task-6-repair.md
572425ece54d610863a6f739d7e34494b07d86d7dadd760791bd6b4f985e6a41  git=25290821421ad20550129104aed54f24f2ed3f92  task-7-commit-verifier.md
2158597fb0746430f8c51d2ea24136c7bf530b0f1466562e5985488456c973b6  git=5e9b6a4b009ed684e76903149c6a6f2dc3085d02  task-7-evidence-bundle-verifier.md
63c34690eaf164e440b245c3aca221dfee2bec519d12f22ebca0541530b35bb4  git=dd460f678be4db85e806fc133131beafdadfb508  task-7-final-context-review.md
c047fe84a6fc5c6aa185a1d48195f89a4b9c4e2a223f25f8a10bcb955c47c261  git=690148b3b00ad54bb67c20cbb4867cb45e4c0ebc  task-7-final-full-suite.md
bb398a788b2b025a9c8f01818f07f448a4ec4863b7ea5a006193a20289e86430  git=fff034388a69f76b1170c312f53b5c5ec8373f76  task-7-final-gate-review.md
4ce20fa4b2d36f6cb4376dba715b6d80bdbeb4fd65d911adeb775bf0b153f5a4  git=843f815f15ff78af8662c8eab05a30746489174a  task-7-final-goal-review.md
48f71153a869aac74acc86be4920e66882e7556e38939f321eb925c0ce51518a  git=baf9d06d1d92bf02f7963b9915b21bb9a75d0d36  task-7-final-manual-qa.md
f47a255dc144e79f4ee95ae9555a7491e2a363dde6961881a257ef74cf8ae6e3  git=60c03ba1ab61f10be0f00e6e61736f7b067aa936  task-7-hangfix-commit-verifier.md
bcb49df9b862e359b3ceb345fd4be6501a65530ed09545e601a2c4c5f9dabcb5  git=59124a6e166875c75680f8281ec3059f78a9f22d  task-7-hangfix-commit.md
83b10c30ea6772060915edcc4087efa4358db6b9546c6ffc1e9078baa63dc440  git=16e450f44c83f5a325ace13ed4c969f64f09c0bb  task-7-product-commit.md
4e3910dc1f802f04e4dda6b192819fddce3a32378604bd78687512b00faa2f63  git=d21a9afd587832fdb8cff940e0d3ed0b12e0e36c  task-7-repair-2-verifier.md
f57db204432ed702c468c5fe27265c7e1dcddcb8f2cc58921635fc15949d6af5  git=c10e9d5de2276166e9f467ab558a978840aa3276  task-7-repair-2.md
aeb97646b9bc71a667df00462d42d65e57eb1eaa774849b2e52b6a608dc8c9fc  git=94fc115fb904154fb52be9614b5ddd6936b206aa  task-7-review-code-final.md
2bf08af3c725649acaeca3e6930c443e14fdf18d0c9f777064769ee59b1a9cd0  git=5273179d5406af287129a0cf6181fb6fcfb34c32  task-7-review-repair-commit-verifier.md
563c0dd2d347cfd6f277cd3308544e965289244b094c8c4c5b32031183190b61  git=c5c63e826113bb734ed4e314f8c00b1c6b51e1b0  task-7-review-repair-commit.md
522a1bef03c0552e4646b840ff61f8df8750165dd52b1b43e2a289deda3b0580  git=04e6b90df3da27b54bc17e8229c957e7ee9f59b6  task-7-review-security-final.md
356c23a9fcfa339a512848fc5d05ddbf9039bf75d62395a9d4455d7d88bc19dc  git=81a0b62f98c8321b390b79074c9a370ba2846c10  task-7-security-repair-2.md
9a57b6f994a43701e8fc7c6098bfee4dc38d3c615d100cef8d604e986786ac28  git=b586ebea593efd56113755d4ad9b50e448fbabfa  task-7-wave21-ingestion-steps5-10.md
31b5629f11d86cca8219d1e77d421092c4bacf2bc644127fc4737680521f1fd4  git=335ea42afeb79bed39021d004a1b16dee6aa5f16  G007/a1/commit-boundary.txt
a1bb8963f2ff3190a8d447d8ef8f4800b3e025ea561748575f4631e024431d02  git=762bc41b961180e149fe0cf18af5201e1caf571e  G007/a1/final-suite.txt
b63e9e9d8c5123417ae69fa67329e476b2653e40eb0ea8b0a6ee70e017fbf79b  git=b044151204803e62c62ffad521ed9477bd60fb16  G007/a1/quality-gate.json
375113cd441050683f0b54df73c0d37e5a3fab9bef833477130c2d14e879818b  git=b75cab63fb5b4f4f0568a73d0612898be4ebd3e2  G007/a1/scope-cleanup.txt
64b4ac4f2a8bf6724f8cbc231a44458db4cf6f507f76eb36cebba93578aaa3cc  git=61013616b8a0c55987d80cb1bb45ff0c3e3b61fa  G007/a1/step7-evidence-index.md
ef14b1e22b4879337da10c75613612e06880a58b96a1a682cd69d8b0d1bec4db  git=f94e75d6782ea4ce8f876da834e876bdb7a37d4b  aggregate-complete.json
2ca52a5117222a9eea4859de3f3a71d32abba783d290f1cdb57ddf570d77c353  git=4c8ff6ba6d0d0962a20dced2baae23e0759ff906  goals.json
5abad1374ff1511ca1f19945f98c5b2fa854435a815ba81c3975e3a1d8b848b7  git=098d8564b212f95a00eab76a301988fdacb9b771  ledger.jsonl
eefb09a27b3bd4d27afb3b1d56d7baafc3177c363e3bdc40f426a2d7b70e17df  git=e6718758f89e173490347189bb234d51eb7f0058  step8-kickoff.md
```

`git diff --name-only 362b0a679483139e51d8e37748674a867d6a9b2f HEAD`
equals this 47-path set. Exclusion regex over the delta: no hits.
All 47 are `A` (added).

## Perimeters after commit

| Perimeter | Required | Observed now |
|---|---|---|
| 47-path content SHA-256 (`path<TAB>sha\n`, LC_ALL=C / Python `sorted`) | `3866e5e8e41da5ad16b731348039bf36476a5d638b3675fe1ac20c54db945924` | match; 6794 bytes |
| 46-path sealed nonself | `9c0b4b8f796552d9bd6135d4464f8e0819a52cd96d92b106653a5964b3d4a49c` | match; 6642 bytes |
| Product/test `git ls-tree -r HEAD -- ontologylab tests scripts pyproject.toml` | `9d3f579022ae33f8280753509dac75e44c4c51c5e3884253b57da930349e5867` | match at HEAD and at parent; 387 paths |
| Repair 21-path (`git diff-tree --name-only -r 362b0a6`) | `1bd10421c5075045e550c2b4015270dd251409c4157622e87c79fc21dc47126b` | match; 2050 bytes; HEAD blobs = parent blobs |

```
git diff 362b0a679483139e51d8e37748674a867d6a9b2f..HEAD -- ontologylab tests scripts pyproject.toml
# empty (exit 0)
```

The committed-state suite remains bound to unchanged product/test bytes on
`362b0a6` (tree `dce1386961684e924108ded625e56dab4031384d`). This commit
only adds ignored-then-forced `.omo` evidence/state.

## Post-commit index and remotes

| Check | Result |
|---|---|
| `git diff --staged --stat` | empty |
| `git log -1 --oneline` | `b328a8c docs(evidence): close wave21 ingestion step 7` |
| `git rev-parse origin/main` | still `4ee5465b9727a2ca3c00e7eea0f3893e2301c148` |
| `HEAD...@{upstream}` | 52 ahead, 0 behind |
| `git branch -r --contains b328a8c` | empty |
| `git merge-base --is-ancestor HEAD origin/main` | exit 1 |
| `git push` | not run |

## Recovery

| Fact | Value |
|---|---|
| Recoverable parent | `362b0a679483139e51d8e37748674a867d6a9b2f` |
| Recoverable parent tree | `dce1386961684e924108ded625e56dab4031384d` |
| Reflog | `HEAD@{0}` = this evidence commit; `HEAD@{1}` = `362b0a6` product repair |
| Worktree product/test | untouched vs parent and vs HEAD |
| Rewrite performed | none (no amend / rebase / reset / checkout / restore / stash) |
| Push performed | none; `origin/main` unchanged |
| Recovery path if this commit must be discarded | `git reset --soft 362b0a679483139e51d8e37748674a867d6a9b2f` (not executed) |

## Residual status classification

`git status --short` after commit (and after this report file was written)
shows the same pre-existing untracked entries. None were staged.

| Residual | Class |
|---|---|
| `.gjc/` | pre-existing unowned untracked |
| `.sisyphus/` | pre-existing unowned untracked |
| `artifacts/` | pre-existing unowned untracked |
| `docs/CONANSSAM-PROMPT-2026-08-08.bak` | pre-existing unowned untracked |
| `docs/INGESTION-WAVE-2.1-RECURSIVE-PLAN-R10-2026-08-20.md` | pre-existing unowned untracked |
| `docs/OMO-INGESTION-WAVE-2.1-IMPLEMENTATION-HANDOFF-2026-08-20.md` | pre-existing unowned untracked |
| `docs/OMO-INGESTION-WAVE-2.1-MASS-ULW-INTEGRATED-ANALYSIS-2026-08-20.md` | pre-existing unowned untracked |
| `docs/ONTOLOGYLAB-DETAILED-SMOKE-RESULT-2026-08-08 2.md` | pre-existing unowned untracked |
| `docs/WAVE-2.1-DEEP-RESEARCH-REMEDIATION-GJC-2026-08-20.md` | pre-existing unowned untracked |
| `graphify-out/` | pre-existing unowned untracked |
| `ontologylab/graphify-out/` | pre-existing unowned untracked |
| six `ontologylab/review_decision*` / `review_grounding.py` | denylist; still `??` |
| `uv.lock` | pre-existing unowned untracked |
| `.omo/ulw-loop/.../aggregate-active.json` | ignored active sibling; left on disk |
| `.omo/ulw-loop/.../brief.md` | ignored loop brief; left on disk |
| superseded Task 3–7 receipts | ignored historical; left on disk |
| `.omo/plans/`, `.omo/drafts/`, `.omo/boulder.json`, `.omo/start-work/ledger.jsonl` | ignored orchestration; untouched |
| this file `task-7-evidence-commit.md` | post-commit boundary report; gitignored; not in `b328a8c` |

Tracked `ontologylab/`, `tests/`, `scripts/`, and `pyproject.toml` have no
working-tree diff vs `HEAD` or vs `362b0a6`.

## Commands run (no pytest)

```
git rev-parse HEAD HEAD^{tree} origin/main
git show -s --format='%H tree=%T parent=%P subject=%s'
git add -f -- <47 exact paths>
git diff --cached --name-only      # exactly those 47
git diff --cached --check          # trailing-blank-line warnings on frozen files
git diff --cached -- ontologylab tests scripts pyproject.toml docs   # empty
git commit                         # subject docs(evidence): close wave21 ingestion step 7
git log -1 --oneline
git diff --name-only 362b0a6 HEAD  # 47 .omo paths
git diff 362b0a6..HEAD -- ontologylab tests scripts pyproject.toml   # empty
git ls-tree -r HEAD -- ontologylab tests scripts pyproject.toml | LC_ALL=C sort | shasum -a 256
python3                            # sha256 + json/jsonl parse + 47/46/21 perimeters
```

Not run (forbidden): pytest; `git push`; amend / rebase / reset /
checkout / restore / stash.

## Stop

Base evidence-only commit. Stable 47-path set. Product/test bytes identical
to `362b0a6`. Perimeters unchanged. No excluded path committed. No push.
