# Task 2 commit verification receipt

Date: 2026-08-23
Verifier: omo senpi-task `st_01a02eb2`
Mode: read-only Git/object verification; no tests, product edits, Git writes, network, live-data, or port-8799 activity.

## Verdict

**confirmed**

Commit `49ac5249fbfaecf0e18a00d08392166ea79250d5` is exactly the confirmed Task 2 extraction-receipt product/test increment.

## Commit identity

| Check | Required | Observed | Result |
|---|---|---|---|
| Commit | `49ac5249fbfaecf0e18a00d08392166ea79250d5` | `49ac5249fbfaecf0e18a00d08392166ea79250d5` | MATCH |
| Parent | `63e326f27c60b81f8a3e3daaf27518e82564da5c` | `63e326f27c60b81f8a3e3daaf27518e82564da5c` | MATCH |
| Subject | `feat(extraction): bind runs and chunks to representations` | `feat(extraction): bind runs and chunks to representations` | MATCH |
| Tree | recorded product-commit tree | `2023a1bbf0e851c8bcb24b16ea072bcbc2953dc7` | MATCH |
| HEAD | target commit | `49ac5249fbfaecf0e18a00d08392166ea79250d5` on `main` | MATCH |

Evidence: `git show -s --format='hash=%H%nparent=%P%nsubject=%s%ntree=%T' 49ac524...`; `git rev-parse HEAD`.

## Exact path and blob boundary

`git diff-tree --no-commit-id --name-status -r 49ac524...` reports exactly seven paths (six adds, one modification), and no other path:

```text
A  ontologylab/extraction_receipt_ids.py
A  ontologylab/extraction_receipt_schema.py
A  ontologylab/extraction_receipt_store.py
A  ontologylab/extraction_receipt_types.py
A  ontologylab/extraction_receipts.py
M  ontologylab/extraction_state.py
A  tests/test_extraction_receipts.py
```

The seven-path set exactly equals the required set. It contains no Task 3+ path, `.omo/` path, documentation path, or unrelated product/test path.

Committed byte SHA-256 values recomputed from `49ac524...:<path>` match the verifier-approved table in `task-2-verifier.md` and the product-commit receipt:

```text
ontologylab/extraction_receipt_ids.py     c8c0fd4b431bfaa5ae9687fa869e0d8cffe5338557a625dc461ac110c6d9daae
ontologylab/extraction_receipt_schema.py  4f68452dcbad35e3e85443751071786ac156a1c62ad3ca5e1510e2443a044ea8
ontologylab/extraction_receipt_store.py   42ad7c6be247587304a5ad6fd4ef29da5d199ce4f4f27f5d7c58d3084dc64f86
ontologylab/extraction_receipt_types.py   bc2b07d241cd3392760035a96803ebef61f0774caecdda57a38089282e834dc3
ontologylab/extraction_receipts.py        01d18f23b0c88506a3ed694eef42e33e22d29ce48e0b1cbc6042f5cfc78bd8e7
ontologylab/extraction_state.py           09bd61aeb8567c22c2a2abca8717296db7089f51a2f7be77068d8fcc1bac880e
tests/test_extraction_receipts.py         b1a0f2b465267163c813e0c60da982e83f0ffc73da799c36296bc3a9b55be52e
```

Raw Git blob IDs were also inspected for all seven changed paths. The specified perimeter recipe (sorted `path<TAB>file-sha256\n`, SHA-256) recomputed to exactly:

```text
1287ca36f8f7062cf5de44140d7fe2ac4fa4494bc359f802bf2d39ce736494c8
```

## Evidence-chain consistency

- `task-2-executor.md` identifies these same seven receipt product/test paths and the same implementation boundary.
- `task-2-verifier.md` has strict verdict `confirmed`, confidence `0.91`, and lists the identical seven approved SHA-256 values.
- `task-2-product-commit.md` records the same parent, subject, tree, exact seven-path set, seven SHA-256 values, and perimeter hash.

## Repository and origin state

- Staging is empty: `git diff --cached --name-status` produced no paths.
- Index tree is `2023a1bbf0e851c8bcb24b16ea072bcbc2953dc7`, exactly the target commit tree.
- `HEAD` equals the target commit; there is no tracked working-tree diff.
- Upstream is `origin/main`; current `origin/main` is `4ee5465b9727a2ca3c00e7eea0f3893e2301c148`, equal to the unchanged origin value recorded before/after the Task 2 commit. The target is not contained by any origin remote branch, and local `main` is ahead of `origin/main` by 44 commits. This supports the recorded no-push condition without contacting the network.

## Residual dirt classification

All residual status entries are untracked and outside the commit boundary:

- `.sisyphus/`, `artifacts/`, `graphify-out/`, `ontologylab/graphify-out/`, and `uv.lock`: unrelated tooling, artifacts, generated output, or user lockfile.
- Eight `docs/` files: unrelated planning, authority, backup, or smoke material; none is committed by Task 2.

No Task 2 product/test path is dirty or staged.

## Commands inspected

- `git show`, `git diff-tree --name-status/--raw`, and `git ls-tree` for commit/tree/path/blob evidence.
- `git show 49ac524...:<path> | shasum -a 256` for each committed byte stream; sorted perimeter rehash.
- `git status --porcelain=v2 --branch`, `git diff --cached --name-status`, `git diff --name-status`, `git write-tree`.
- `git rev-parse origin/main`, `git merge-base HEAD origin/main`, `git rev-list --left-right --count origin/main...HEAD`, `git branch -r --contains`, and reflog inspection.

No tests were run, as required by this verification task.
