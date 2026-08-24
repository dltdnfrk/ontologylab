# Wave 2.1 Step 8 Task 12 — Full-Suite Repair Commit Verification

Date: 2026-08-24
Verifier: omo senpi-task `st_01a032b5`
Mode: independent READ-ONLY commit objects and repository state.
No test, checkout, reset, stash, rebase, amend, stage, commit, push,
network, Application Support contents, product/test edit, or PID
55560 / port 8799 mutation. This file is the only write.

## Verdict: PASS

HEAD identity, single parent, subject, one-path changed set, denylist
absence, recomputed commit/tree/blob SHAs, one-path content perimeter,
product/test tree perimeter, working-tree bytes, index, origin, and
no-push all match the required contract exactly. Diff adds only the
three expected machine-consumed pack dict fields.

## Commit identity

Command:
```sh
git show -s --format='commit=%H%ntree=%T%nparent=%P%nsubject=%s' HEAD
git cat-file -p HEAD | git hash-object -t commit --stdin
python3 -c 'import hashlib,subprocess; raw=subprocess.check_output(["git","cat-file","commit","HEAD"]); print(hashlib.sha1(f"commit {len(raw)}\0".encode()+raw).hexdigest())'
git rev-parse HEAD^{tree} HEAD^ HEAD^@
```

Result:
```text
commit=cc3fd42513db4eaabff1a78a996fa5339f70615e
tree=2278180afad39b1eb2903a91cd6739774496f689
parent=0120c0515020615f9cbeea23c875f04b6da50cab
subject=test(mcp): expect verified legacy provenance
```

Independent recomputes of the 465-byte commit object:

- `git hash-object -t commit` → `cc3fd42513db4eaabff1a78a996fa5339f70615e`
- `sha1(b"commit 465\0"+raw)` → `cc3fd42513db4eaabff1a78a996fa5339f70615e`
- commit-object SHA-256 → `e3091b8c1f1272357afd129eff7a09eaf53bab6ab34a993f8f506597ea36823c`

Independent tree recompute (`git cat-file tree` + `git hash-object -t tree`
and `sha1(b"tree 648\0"+raw)`): `2278180afad39b1eb2903a91cd6739774496f689`.

`git rev-parse HEAD^@` returned exactly one parent:
`0120c0515020615f9cbeea23c875f04b6da50cab`.
`git rev-list --parents -n 1 HEAD` is
`cc3fd42513db4eaabff1a78a996fa5339f70615e 0120c0515020615f9cbeea23c875f04b6da50cab`.
Subject bytes are exactly `test(mcp): expect verified legacy provenance\n`.

Author/committer (observed, not required): Hyunjun `<dltdnfrk@gmail.com>`
1787557130 +0900 (Mon Aug 24 16:38:50 2026 +0900).

## Exact changed-path boundary (1 path)

Command:
```sh
git diff-tree --no-commit-id --name-only -r HEAD
git diff-tree --no-commit-id --name-status -r HEAD
git diff-tree -r HEAD^ HEAD
git diff --name-only HEAD^ HEAD -- . ':!tests/test_communities.py'
```

Result:
```text
M	tests/test_communities.py
:100644 100644 293707e9868d5fd55b0da89a682744ca9659471e e53f11492ea60454d6071016f8fbbbae84c34904 M	tests/test_communities.py
```

Name-only set is exactly `tests/test_communities.py`. Extra-path check
empty. Rename/copy (`-M -C`) still one `M`. Numstat `7	2	tests/test_communities.py`.
Shortstat `1 file changed, 7 insertions(+), 2 deletions(-)`.
`git diff --check HEAD^ HEAD` exit 0.

Denylist on the changed-path set (`.omo`, `.gjc`, `.sisyphus`,
`artifacts`, `docs`, `graphify-out`, `uv.lock`): empty.

No product path. No other test. No evidence. No docs.

Subtree object IDs vs parent:

```text
ontologylab     e6472be7d85abc8651d2f5458bad8367a94d8061  equal
scripts         226af2c10d0aef14cdc2da5698c78738954a126a  equal
pyproject.toml  ab8fd7f3646d6f3b86aaf9b25059242dbec1dfb8  equal
tests           96d56e5544d175d1a519c1a9447a2e6b217eb976  ≠ parent d542759cb0b298db3aa442d7e1204b60b79b22fc
```

`git ls-tree -r` over `ontologylab tests scripts pyproject.toml` shows
the only blob change is `tests/test_communities.py`
`293707e9868d5fd55b0da89a682744ca9659471e` →
`e53f11492ea60454d6071016f8fbbbae84c34904` (mode `100644` both sides).
Zero added/removed paths in that perimeter.

## Diff contract (machine-consumed pack fields only)

Single hunk in `test_legacy_pack_without_communities_degrades`:

```diff
@@ -209,8 +209,13 @@ def test_legacy_pack_without_communities_degrades(community_pack, tmp_path):
     try:
         assert session.get_communities() == {
             "communities": [], "members": [], "count": 0,
-            "pack": {"pack_id": manifest.pack_id,
-                     "content_hash": legacy_hash},
+            "pack": {
+                "pack_id": manifest.pack_id,
+                "content_hash": legacy_hash,
+                "pack_schema_version": 1,
+                "integrity_level": "legacy-graph-only",
+                "evidence_mode": None,
+            },
         }
```

Preserved: `pack_id`, `content_hash`.
Added only:

- `pack_schema_version`: `1`
- `integrity_level`: `"legacy-graph-only"`
- `evidence_mode`: `None`

No other assertion, import, helper, or product call changed.

## Committed object-byte identity

`tests/test_communities.py`:

```text
git blob (HEAD)     e53f11492ea60454d6071016f8fbbbae84c34904
git blob (parent)   293707e9868d5fd55b0da89a682744ca9659471e
SHA-256 (HEAD)      66d726357eca454ef29303dae10d5f46aed38d444d15f4309baa1338094abed6
SHA-256 (parent)    a2d8d4e5101e769d952270b7f2bd7120ff6d6d072cb00213bd49db068c048a2c
size HEAD/working   12030
size parent         11867
```

Independent `sha1(b"blob {len}\0"+bytes)` reproduced both blob IDs.
Working-tree `shasum -a 256 tests/test_communities.py` equals the
committed stream. `working == git cat-file blob HEAD:tests/test_communities.py`
is True. Index stage-0 blob is `e53f11492ea60454d6071016f8fbbbae84c34904`.

## Deterministic perimeters

### One-path content perimeter

Command:
```sh
git diff-tree --no-commit-id --name-only -r cc3fd42513db4eaabff1a78a996fa5339f70615e | LC_ALL=C sort |
while IFS= read -r p; do
  printf '%s\t' "$p"
  git show "cc3fd42513db4eaabff1a78a996fa5339f70615e:$p" | shasum -a 256 | awk '{print $1}'
done
# SHA-256 of the LC_ALL=C sorted path<TAB>content-sha256\n stream
# (1 LF-terminated record, 91 bytes)
```

Record:
```text
tests/test_communities.py	66d726357eca454ef29303dae10d5f46aed38d444d15f4309baa1338094abed6
```

Result:
```text
cc1397818f8eb71a6a9b0f8929c0ff78a8974804ca8f98d21087f2d41f19fcdb
```

Independent Python `hashlib.sha256` over the identical 91-byte record
reproduced the same digest.

### Product/test tree perimeter

Command:
```sh
git ls-tree -r cc3fd42513db4eaabff1a78a996fa5339f70615e -- ontologylab tests scripts pyproject.toml | LC_ALL=C sort | shasum -a 256
```

Result (408 paths):
```text
47aa97763afad2b921bd0d1ee6867bf25ed3d650137611cf3b663c6b4f1aea07
```

Parent product/test perimeter on `0120c051…` is
`029d4ad6b5fd7b9551420fe453f4c55ab80d72104c33bdefc17c365235724f23`
(408 paths). Path count unchanged; the digest delta is exactly the one
blob replacement above. That parent digest matches the previous Task 12
repair-commit verifier's HEAD perimeter.

## Index, worktree, untracked, origin, no-push

| Check | Observed | Result |
|---|---|---|
| `git diff --cached --quiet` | exit 0 | index empty |
| `git diff --quiet HEAD` | exit 0 | all tracked == HEAD |
| `git diff --quiet HEAD -- ontologylab tests scripts pyproject.toml` | exit 0 | tracked product/test == HEAD |
| `git update-index --refresh` | no output | index refresh clean |
| working SHA-256 == commit SHA-256 | `66d726357eca454ef29303dae10d5f46aed38d444d15f4309baa1338094abed6` | working bytes equal commit |
| `git rev-parse HEAD` | `cc3fd42513db4eaabff1a78a996fa5339f70615e` | HEAD is the commit under test |
| `git show-ref --verify refs/heads/main` | `cc3fd42513db4eaabff1a78a996fa5339f70615e` | branch tip is HEAD |
| branch | `main` | known |
| upstream | `origin/main` | known |
| `git rev-parse origin/main` / `refs/remotes/origin/main` | `4ee5465b9727a2ca3c00e7eea0f3893e2301c148` | unchanged vs prior verifiers |
| `git status -sb` first line | `## main...origin/main [ahead 57]` | local only |
| `git rev-list --left-right --count origin/main...HEAD` | `0	57` | not on origin |
| `git merge-base HEAD origin/main` | `4ee5465b9727a2ca3c00e7eea0f3893e2301c148` | origin still ancestor |
| `git merge-base --is-ancestor cc3fd425… origin/main` | exit 1 | commit not pushed |
| `git merge-base --is-ancestor origin/main HEAD` | exit 0 | origin still ancestor |
| `git branch -r --contains cc3fd425…` | empty | no remote branch contains it |
| `git reflog -1` | `cc3fd425… commit: test(mcp): expect verified legacy provenance` | local commit only |

No `git push`, `git fetch`, `ls-remote`, or other network command was run.
`origin/main` remains the same object recorded by prior Task 12 verifiers.

`git status --porcelain=v1 --untracked-files=normal` shows only the
pre-existing unrelated untracked set (none staged):

```text
?? .gjc/
?? .sisyphus/
?? artifacts/
?? docs/CONANSSAM-PROMPT-2026-08-08.bak
?? docs/INGESTION-WAVE-2.1-RECURSIVE-PLAN-R10-2026-08-20.md
?? docs/OMO-INGESTION-WAVE-2.1-IMPLEMENTATION-HANDOFF-2026-08-20.md
?? docs/OMO-INGESTION-WAVE-2.1-MASS-ULW-INTEGRATED-ANALYSIS-2026-08-20.md
?? docs/ONTOLOGYLAB-DETAILED-SMOKE-RESULT-2026-08-08 2.md
?? docs/WAVE-2.1-DEEP-RESEARCH-REMEDIATION-GJC-2026-08-20.md
?? graphify-out/
?? ontologylab/graphify-out/
?? uv.lock
```

This is the same unrelated dirty set recorded by prior Task 12
verifiers. `.omo/` is gitignored (`.gitignore:28:.omo/`); this report
is not staged.

## PID 55560 / port 8799 — observe only

```text
PID 55560 PPID 1 STAT S STARTED Thu Aug 6 13:51:44 2026
COMMAND .venv/bin/python -m ontologylab.serve --host 127.0.0.1 --port 8799
LISTEN  TCP 127.0.0.1:8799  DEVICE 0x1ff51c806b197195
```

PID 8799 does not exist (`ps -p 8799` exit 1). Port 8799 is the
listen port of PID 55560. Device `0x1ff51c806b197195` matches the
prior Task 12 observe-only record. No request was sent. No
Application Support path was read.

## Commands that were not run

pytest / full suite / network / push / Application Support contents /
any Git write other than creating this ignored evidence file.

## Worktree after this report

HEAD `cc3fd42513db4eaabff1a78a996fa5339f70615e` on `main`, ahead 57 of
unchanged `origin/main` `4ee5465b9727a2ca3c00e7eea0f3893e2301c148`.
Index empty. Tracked product/test bytes equal the commit. Only the
unrelated untracked paths listed above remain dirty.
