# Task 5 commit verifier

Date: 2026-08-23
Mode: read-only commit verification (durable report only; no Git mutation and no tests)
Commit: `0a3c7a21d5ee8fbcfb7aa7bf521921e0e333ea29`

## Verdict

`confirmed`

The commit exactly matches the approved Task 5 final perimeter in
`task-5-product-commit.md`; its final repair bytes also match
`task-5-repair-verifier.md`. The earlier `task-5-verifier.md` is a pre-repair
freeze: it differs only for the subsequently repaired `main.py` and
`tests/test_grounded_review.py`, as explicitly recorded by the repair verifier.

## Commit identity

| Assertion | Independent result |
| --- | --- |
| Commit | `0a3c7a21d5ee8fbcfb7aa7bf521921e0e333ea29` |
| Parent count | 1 |
| Exact parent | `7c159fd3efa24a5b9839e0ae32643e7f90560124` |
| Subject | `feat(review): require append-only grounding decisions` |
| Tree | `be6cc43cf4fad81a6f81179e57438af2bdd46ef2` |

Evidence: `git show -s --format='hash=%H%nparents=%P%nsubject=%s%ntree=%T' <commit>` and `git rev-parse <commit>^`.

## Exact committed name-status perimeter

`git diff-tree --no-commit-id --name-status -r <commit>` exactly equals:

```text
M	ontologylab/extraction_state.py
A	ontologylab/grounded_review.py
A	ontologylab/grounded_review_ids.py
A	ontologylab/grounded_review_payload.py
A	ontologylab/grounded_review_preflight.py
A	ontologylab/grounded_review_schema.py
A	ontologylab/grounded_review_store.py
A	ontologylab/grounded_review_types.py
M	ontologylab/kgstore.py
M	ontologylab/main.py
M	ontologylab/server/routes.py
M	ontologylab/server/schemas.py
A	tests/test_grounded_review.py
```

## Blob approval and perimeter proof

Each SHA-256 was independently computed from `git show <commit>:<path> |
shasum -a 256`, and equals the approved final table in the product-commit
report (also the repair-verifier final freeze):

```text
ontologylab/extraction_state.py	7fba7e0f397cd81837412d4857b4c68e0886c275a2dff646774fc0da15bc993e
ontologylab/grounded_review.py	105e45da8363e8737f5b4156f8d75d4b929e88a12d0f5649e387897500e417e0
ontologylab/grounded_review_ids.py	4af4a46e68a9a4d62e3e040fd09d9452a3e05bfdfc7da01f41c6cb92bb19c226
ontologylab/grounded_review_payload.py	692b9a5a6b733cd1afda10ec5c33fea88b887c4e29f693a676b206db1cf3dc7a
ontologylab/grounded_review_preflight.py	b6c754bf500a9e384be4dc19fe024bca7d5efbc03dc764e588d6fd9291dc2a45
ontologylab/grounded_review_schema.py	cdc9ef8790d0f5ee01e4b57c214f4811d835b6fb04ec7f8457d109b9550a1771
ontologylab/grounded_review_store.py	c98f3a38cd8a3ec311b857fcb943acd8b173d684999001f9284dde6f9e09af5a
ontologylab/grounded_review_types.py	d64716d46155d66d42a958aa4b5cc6cdbeca06b34a302e985e5b6a8a0d4610ba
ontologylab/kgstore.py	0f37cc1d511917ff4b766c51301ec623ea02d539a1b7298bc62a0c3b1eb64013
ontologylab/main.py	50e32fc1a1cc6a3921a2c8b481790b4c727593b3067f483d62d370ee4a0c6d36
ontologylab/server/routes.py	d4905eb8b12bb820553fa1547473f345ed48dc2fba77de872f2691d907778ab9
ontologylab/server/schemas.py	a1993b8c25ec5781c6f6b92a4601728a19dc75a698eeb4cf780972032edaeea3
tests/test_grounded_review.py	8b990e2fecd84407680ce42aac9660fd4401f9e4c95b465df3777d5428222cbc
```

I independently constructed sorted records as `path<TAB>blob-sha256<LF>` and
ran `LC_ALL=C sort | shasum -a 256`. Result:

```text
82ba0621f5e3a312973e9df4d0df412ae4c992d6ff9047a797b258efdab6835c
```

This is the required perimeter SHA-256.

## Exclusions, index, remote, and worktree

- Commit path metadata contains no `.omo/`, `docs/`, `uv.lock`, or `graphify` path.
- Metadata-only checks confirm all six critical denylist paths are absent from the commit. Their contents were not opened, read, or hashed.
- `git diff --cached --quiet` passed and staged path count is `0`; the staged set is empty.
- `origin/main` is `4ee5465b9727a2ca3c00e7eea0f3893e2301c148`.
- No push evidence exists for this commit: `refs/remotes/origin/main` remains at that hash and its latest reflog entry is that same hash; HEAD's latest reflog entry is the local commit.
- Every one of the 13 owned working-tree files has the same SHA-256 as its committed blob; `git diff --quiet HEAD -- <13 paths>` passed.

The worktree retains unrelated untracked paths, including the six denylist paths, but none is staged or part of the verified commit.

## Commands run

```text
git show -s --format='hash=%H%nparents=%P%nsubject=%s%ntree=%T' <commit>
git rev-parse <commit>^
git diff-tree --no-commit-id --name-status -r <commit>
git show <commit>:<approved-path> | shasum -a 256
git diff --cached --quiet
git diff --cached --name-only
git rev-parse origin/main
git reflog show -1 refs/remotes/origin/main
git reflog show -1 HEAD
git diff --quiet HEAD -- <13 owned paths>
```

No test or full-suite command was run.
