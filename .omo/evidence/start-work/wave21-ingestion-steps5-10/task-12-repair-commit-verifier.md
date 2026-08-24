# Wave 2.1 Step 8 Task 12 — Repair Commit Verification

Date: 2026-08-24
Verifier: omo senpi-task `st_01a03298`
Mode: independent READ-ONLY commit objects and repository state.
No test, checkout, reset, stash, rebase, amend, stage, commit, push,
network, Application Support contents, product/test edit, or PID
55560 / port 8799 mutation. This file is the only write.

## Verdict: PASS

HEAD identity, single parent, subject, 13-path changed set, denylist
absence, committed object bytes, exact sorted perimeter digest, and
product/test tree perimeter all match the required contract. Current
committed bytes MATCH the Round 6 executor and final receipts for
every owned path. Index empty. Origin unchanged. No push.

## Commit identity

Command:
```sh
git show -s --format='commit=%H%ntree=%T%nparent=%P%nsubject=%s' HEAD
git cat-file -p HEAD | git hash-object -t commit --stdin
git rev-parse HEAD^{tree} HEAD^
```

Result:
```text
commit=0120c0515020615f9cbeea23c875f04b6da50cab
tree=82be963d9ce7dc28d1467cc40ee5b03ac5f0d03f
parent=081d8554f814645517a29a0cef1c0e32af3d84df
subject=fix(pack): close verified v2 publication boundary
```

Independent `git hash-object -t commit` of the commit object bytes
reproduced `0120c0515020615f9cbeea23c875f04b6da50cab`. One parent only.
Subject bytes are exactly `fix(pack): close verified v2 publication boundary\n`.
All required identity values match exactly.

Author/committer (observed, not required): Hyunjun `<dltdnfrk@gmail.com>`
1787555227 +0900 (Mon Aug 24 16:07:07 2026 +0900).

## Exact changed-path boundary (13 paths)

Command:
```sh
git diff-tree --no-commit-id --name-only -r 0120c0515020615f9cbeea23c875f04b6da50cab | LC_ALL=C sort
git diff-tree --no-commit-id --name-status -r 0120c0515020615f9cbeea23c875f04b6da50cab | LC_ALL=C sort
```

Result (13):
```text
A	ontologylab/pack_source_fingerprint.py
A	ontologylab/pack_v2_derive.py
A	ontologylab/pack_v2_validate.py
A	tests/test_pack_v2_review_repair.py
M	ontologylab/mcp_server.py
M	ontologylab/pack_readiness.py
M	ontologylab/pack_receipt_seal.py
M	ontologylab/pack_v2_closure.py
M	ontologylab/pack_v2_manifest.py
M	ontologylab/pack_verifier.py
M	tests/test_pack_v2_closure.py
M	tests/test_pack_v2_verifier.py
M	tests/test_packdiff.py
```

Sorted name-only set equals the required 13 paths exactly. No extra
path. No missing path.

Denylist on the changed-path set (`\.omo`, `docs/`, `graphify`,
`artifact`, `uv.lock`): empty. `git diff --check` on
`081d8554…`..`0120c051…` exit 0.

Four paths are new vs parent (`git diff --diff-filter=A`):
`pack_source_fingerprint.py`, `pack_v2_derive.py`,
`pack_v2_validate.py`, `tests/test_pack_v2_review_repair.py`.

## Committed object-byte SHA-256

Each value is SHA-256 of the exact `git show 0120c051…:<path>` byte
stream. Working-tree `shasum -a 256` of the same path MATCHES the
committed stream for all 13. `git diff --quiet 0120c051… -- <13 paths>`
exit 0.

```text
ontologylab/mcp_server.py	137be20d2ab77f2b2efd9a64d9220e7c84eb2c137d3f72a78d18ad1eb1abba89
ontologylab/pack_readiness.py	550f695dd768af327f7cddc143afc41c341899b00ef6682643c63de40da56c21
ontologylab/pack_receipt_seal.py	aae2f5d71c933372cd7631a754b9c8102649b0cefa4a6aaba96f3cf2e905fa1c
ontologylab/pack_source_fingerprint.py	a17d5adbab1df582c27c42fc4e2e6dca99da73b4cffc19c000a157cd064789f7
ontologylab/pack_v2_closure.py	9b819f039e526e4a371cb8474e028bba11d6973360a8d209f4d121e1e02fe968
ontologylab/pack_v2_derive.py	7609a79a38a101b9cc194c19438560278fc0d531a14f721130a6a258a1131577
ontologylab/pack_v2_manifest.py	64e9494eba737f683e8e89f5bbb139453be010bf4d775e72b11cf3683bf6eb3f
ontologylab/pack_v2_validate.py	ca3c138cc1123d9753fb6f3c5cee4725f7470744cfeccfc7de58aece8767f8a6
ontologylab/pack_verifier.py	2b64a110fa3789de3a53245e950f73cb8dccc9bdb78025394fbe3316b55130ed
tests/test_pack_v2_closure.py	96f739571c3512b3d9f812c8d690d68b47d21bc07580bff3753d336b45aa91ff
tests/test_pack_v2_review_repair.py	622c7602c2f961c4dca98711d409c87123c257227d0610046e6e11a2ba417b76
tests/test_pack_v2_verifier.py	78ae23f199897c87841a9dc908bcd168dbfc93162ee4beaa1735a045b80c8ce5
tests/test_packdiff.py	296b20ead46345e1a902285c49328fcaf91993d12208081691577624d8c697d6
```

Git blob IDs (`git rev-parse 0120c051…:<path>`):

```text
ontologylab/mcp_server.py	9367dd64d0dcb66f130d8a30a42af8966ba7139b
ontologylab/pack_readiness.py	e38b82b2478ff61e6c50f4e243e1e67d4d6751ea
ontologylab/pack_receipt_seal.py	29de8858d670ecc5d72230187698cc1a46c83542
ontologylab/pack_source_fingerprint.py	15c0be9104c94d4c0fdcb410c2cbf240dcfca576
ontologylab/pack_v2_closure.py	e7928bb877525e05d9554bad06e75cc01cf45a55
ontologylab/pack_v2_derive.py	ba4bc9ec8912fc099019a04ce7f60fdc73d68b3f
ontologylab/pack_v2_manifest.py	975f988dbf6c56ca748fb5cccbb301b0ce110443
ontologylab/pack_v2_validate.py	d406783c5f4950a6b08361f709dc38c583bb8f48
ontologylab/pack_verifier.py	003836e8399f6cf2bb8c5b0633198205962dc1c6
tests/test_pack_v2_closure.py	fe088526c38bd1e671b689dcbaafaece964852af
tests/test_pack_v2_review_repair.py	08bb8d26e152acf6e6cbd244148d2d471a75225d
tests/test_pack_v2_verifier.py	7b3bc2cc9fc2aedcb7c5f0fe82a23a8981a3210b
tests/test_packdiff.py	5ae85e90c87d7d093feb89e380dcf15d83a135f9
```

Unchanged freeze (not in the 13-path set; blob equal to parent):
`ontologylab/verified_pack_reader.py` SHA-256
`6607a5523f03ac9c70ecb4686478e5b53a62baf9ef283575b656fb310d0a4ca1`
git blob `333cde527ea25297efbf4ff85740587abe7da25b` on both
`0120c051…` and `081d8554…`.

## Deterministic perimeters

### Exact sorted 13-path content perimeter

Command:
```sh
git diff-tree --no-commit-id --name-only -r 0120c0515020615f9cbeea23c875f04b6da50cab | LC_ALL=C sort |
while IFS= read -r p; do
  printf '%s\t' "$p"
  git show "0120c0515020615f9cbeea23c875f04b6da50cab:$p" | shasum -a 256 | awk '{print $1}'
done
# SHA-256 of the LC_ALL=C sorted path<TAB>content-sha256\n stream (13 LF-terminated records, 1247 bytes)
```

Result:
```text
c6f799fceb7dd18cf4a390574e07a28ae896d09b0339bb61930bf7fb3fb63b2a
```

Independent Python `hashlib.sha256` over the identical 13-line
LF-terminated record stream reproduced the same digest.

### Product/test tree perimeter

Command:
```sh
git ls-tree -r 0120c0515020615f9cbeea23c875f04b6da50cab -- ontologylab tests scripts pyproject.toml | LC_ALL=C sort | shasum -a 256
```

Result (408 paths):
```text
029d4ad6b5fd7b9551420fe453f4c55ab80d72104c33bdefc17c365235724f23
```

Parent product/test perimeter on `081d8554…` is
`5bfc7bbd2dcd61ceddc43c31ba5afc2c8590fa36007d6af6748fa8b15f8850e6`
(404 paths). The +4 paths are the four Added files above.

## Round 6 executor / final receipt comparison

Receipts treated as claims and rehashed against committed bytes:

- `task-12-review-repair-6-executor.md` (R6 changed + R5 freeze)
- `task-12-review-round6-code.md` exact SHA table
- `task-12-review-round6-security.md` working-tree SHA table
- `task-12-review-final-gate-after-repair.md` entry=exit SHA table

| Path | Committed SHA-256 | R6 executor / final | Result |
|---|---|---|---|
| `ontologylab/mcp_server.py` | `137be20d2ab77f2b2efd9a64d9220e7c84eb2c137d3f72a78d18ad1eb1abba89` | same | MATCH |
| `ontologylab/pack_readiness.py` | `550f695dd768af327f7cddc143afc41c341899b00ef6682643c63de40da56c21` | same | MATCH |
| `ontologylab/pack_receipt_seal.py` | `aae2f5d71c933372cd7631a754b9c8102649b0cefa4a6aaba96f3cf2e905fa1c` | same | MATCH |
| `ontologylab/pack_source_fingerprint.py` | `a17d5adbab1df582c27c42fc4e2e6dca99da73b4cffc19c000a157cd064789f7` | same | MATCH |
| `ontologylab/pack_v2_closure.py` | `9b819f039e526e4a371cb8474e028bba11d6973360a8d209f4d121e1e02fe968` | same (R6 freeze) | MATCH |
| `ontologylab/pack_v2_derive.py` | `7609a79a38a101b9cc194c19438560278fc0d531a14f721130a6a258a1131577` | same | MATCH |
| `ontologylab/pack_v2_manifest.py` | `64e9494eba737f683e8e89f5bbb139453be010bf4d775e72b11cf3683bf6eb3f` | same | MATCH |
| `ontologylab/pack_v2_validate.py` | `ca3c138cc1123d9753fb6f3c5cee4725f7470744cfeccfc7de58aece8767f8a6` | same (R6 freeze) | MATCH |
| `ontologylab/pack_verifier.py` | `2b64a110fa3789de3a53245e950f73cb8dccc9bdb78025394fbe3316b55130ed` | same (R6 changed) | MATCH |
| `tests/test_pack_v2_closure.py` | `96f739571c3512b3d9f812c8d690d68b47d21bc07580bff3753d336b45aa91ff` | same | MATCH |
| `tests/test_pack_v2_review_repair.py` | `622c7602c2f961c4dca98711d409c87123c257227d0610046e6e11a2ba417b76` | same (R6 changed) | MATCH |
| `tests/test_pack_v2_verifier.py` | `78ae23f199897c87841a9dc908bcd168dbfc93162ee4beaa1735a045b80c8ce5` | same (R6 changed) | MATCH |
| `tests/test_packdiff.py` | `296b20ead46345e1a902285c49328fcaf91993d12208081691577624d8c697d6` | same | MATCH |
| `ontologylab/verified_pack_reader.py` (unchanged) | `6607a5523f03ac9c70ecb4686478e5b53a62baf9ef283575b656fb310d0a4ca1` | same (R6 freeze) | MATCH |

No discrepancy. Earlier R1 executor hashes that were superseded by R2–R6
are not the comparison baseline.

## Index, worktree, untracked, origin, no-push

| Check | Observed | Result |
|---|---|---|
| `git diff --cached --quiet` | exit 0 | index empty |
| `git diff --quiet HEAD -- ontologylab tests scripts pyproject.toml` | exit 0 | tracked product/test == HEAD |
| `git rev-parse HEAD` | `0120c0515020615f9cbeea23c875f04b6da50cab` | HEAD is the commit under test |
| branch | `main` | known |
| upstream | `origin/main` | known |
| `git rev-parse origin/main` / `refs/remotes/origin/main` | `4ee5465b9727a2ca3c00e7eea0f3893e2301c148` | unchanged vs prior verifiers |
| `git status -sb` first line | `## main...origin/main [ahead 56]` | local only |
| `git rev-list --left-right --count origin/main...HEAD` | `0	56` | not on origin |
| `git merge-base --is-ancestor 0120c051… origin/main` | exit 1 | commit not pushed |
| `git merge-base --is-ancestor origin/main HEAD` | exit 0 | origin still ancestor |
| `git branch -r --contains 0120c051…` | empty | no remote branch contains it |
| `git reflog -1` | `0120c051… commit: fix(pack): close verified v2 publication boundary` | local commit only |

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
Round 6 / final-gate observe-only record. No request was sent. No
Application Support path was read.

## Commands that were not run

pytest / full suite / network / push / Application Support contents /
any Git write other than creating this ignored evidence file.

## Worktree after this report

HEAD `0120c0515020615f9cbeea23c875f04b6da50cab` on `main`, ahead 56 of
unchanged `origin/main` `4ee5465b9727a2ca3c00e7eea0f3893e2301c148`.
Index empty. Owned product/test bytes equal the commit. Only the
unrelated untracked paths listed above remain dirty.
