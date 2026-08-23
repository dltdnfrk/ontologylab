# Task 7 Hangfix Commit Verifier

## Confirmed

- Target object `5a6378964bfc41fe2a679453a88235c548a59f4b` is a commit.
- Its sole parent is `4878c2f262e6909deb94ff61ef6d04a7e990edd7`.
- Its exact subject is `test(server): synchronize jobs stream change`.
- Its complete changed-path list has exactly one entry: `M\ttests/test_server.py`.
- The SHA-256 of committed blob `5a6378964bfc41fe2a679453a88235c548a59f4b:tests/test_server.py` is `8a420db2bb95e77817afb369061dee0ba772b134e4520ea54c210393689eb3cb`.
- The index was empty (`git diff --cached --quiet` exit 0).
- Before this evidence record was written, tracked worktree content equaled `HEAD` (`git diff --quiet HEAD` exit 0). Existing untracked files were not inspected.
- `HEAD` is the target commit. Its upstream is `origin/main`, currently `4ee5465b9727a2ca3c00e7eea0f3893e2301c148`.
- `origin/main` is an ancestor of the target, `origin/main..target` includes the target, and no cached remote branch contains the target. This verifies the target has not been pushed to the configured remote-tracking branches and `origin/main` was not advanced to it.

## Needs fix

- None.

## Commands used

```text
git show -s --format='commit=%H%nparents=%P%nsubject=%s' 5a6378964bfc41fe2a679453a88235c548a59f4b
git diff-tree --no-commit-id --name-status -r 5a6378964bfc41fe2a679453a88235c548a59f4b
git cat-file blob 5a6378964bfc41fe2a679453a88235c548a59f4b:tests/test_server.py | shasum -a 256
git diff --cached --quiet
git diff --quiet HEAD
git rev-parse --abbrev-ref '@{upstream}'
git rev-parse --verify origin/main
git merge-base --is-ancestor origin/main 5a6378964bfc41fe2a679453a88235c548a59f4b
git log --oneline origin/main..5a6378964bfc41fe2a679453a88235c548a59f4b
git branch -r --contains 5a6378964bfc41fe2a679453a88235c548a59f4b
```

No denylist file content was read or hashed; only Git metadata was queried.
