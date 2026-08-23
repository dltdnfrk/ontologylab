# Task 6 commit verifier

Date: 2026-08-23
Mode: read-only Git verification; this report is the sole durable write. No staging, commit, test, push, or product/test-file edit was performed.

## Verdict

`confirmed`

Commit `8f0e45fdfa1d70e39a91c03737ecb31cb1add3fb` exactly matches the approved Task 6 product-commit boundary and the Task 6 repair-verifier freeze.

## Commit identity

Verified with `git show -s --format='commit=%H%nparent=%P%nsubject=%s%ntree=%T' 8f0e45f...` and `git rev-list --parents -n 1 8f0e45f...`:

| Field | Confirmed value |
|---|---|
| Commit | `8f0e45fdfa1d70e39a91c03737ecb31cb1add3fb` |
| Parent count / sole parent | 1 / `0a3c7a21d5ee8fbcfb7aa7bf521921e0e333ea29` |
| Subject | `feat(migration): backfill historical grounding receipts` |
| Tree | `c69020eb85c3f1d78893f256310d8a4b8d67eeb8` |

## Exact committed perimeter

`git diff-tree --no-commit-id --name-status -r 8f0e45f...` was compared byte-for-byte to the approved 17-entry name-status set: `MATCH`.

```
A	ontologylab/h1.py
A	ontologylab/h1_bytes.py
A	ontologylab/h1_classify.py
A	ontologylab/h1_classify_cite.py
A	ontologylab/h1_cli.py
A	ontologylab/h1_decisions.py
A	ontologylab/h1_finalize.py
A	ontologylab/h1_ids.py
A	ontologylab/h1_inventory.py
A	ontologylab/h1_materialize.py
A	ontologylab/h1_materialize_review.py
A	ontologylab/h1_migrate.py
A	ontologylab/h1_schema.py
A	ontologylab/h1_store.py
A	ontologylab/h1_types.py
M	ontologylab/main.py
A	tests/test_h1_migration.py
```

The committed path metadata has no `.omo`, `docs`, `uv.lock`, graphify, live-data, or denylist path.

## Blob freeze

The approved SHA-256 table in both `task-6-product-commit.md` and `task-6-repair-verifier.md` agrees. I independently streamed every target blob with `git show 8f0e45f:<path> | shasum -a 256`, sorted the resulting `path<TAB>blob-sha256` records, and compared all 17 records exactly to that approved table: `MATCH`.

The independent sorted-perimeter recomputation was:

```
7edeb5bede362b8e5e7aef2e92206dccca52c79d35a16660aef9564217cadb68
```

This equals the required perimeter hash.

## Index, worktree, denylist, and remote state

- `git diff --cached --name-status` is empty; `git diff --cached --quiet` exited 0.
- `git diff --name-status HEAD -- <all 17 owned paths>` is empty, and the corresponding index-vs-HEAD comparison is empty. Owned working-tree files equal `HEAD`.
- Denylist was checked only by Git path metadata: each of the six paths has `commit=0` via `git ls-tree -r --name-only 8f0e45f -- <path>` and `index=0` via `git ls-files -- <path>`. None was opened, read, or hashed.
- `git rev-parse origin/main` remains `4ee5465b9727a2ca3c00e7eea0f3893e2301c148`.
- No remote branch contains the target commit. The target appears only as the local `commit:` reflog entry; no local Git evidence indicates a push of it.

Untracked non-owned files remain in the worktree, including the denylist paths; they are neither in the index nor in this commit.

## Verification scope

No tests or full suite were run, per instruction. Verification was Git metadata and committed-blob based only.
