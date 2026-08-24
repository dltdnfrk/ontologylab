# Wave 2.1 Step 8 Task 12 - Signature Repair Commit Verification

## Verdict: CONFIRMED

Commit objects and repository state were inspected read-only. No test, checkout, reset, stash, rebase, amend, push, network, server, authority, plan, product, or test operation was performed. The only write is this report.

## Commit identity

```text
commit   081d8554f814645517a29a0cef1c0e32af3d84df
parent   d740a646574b843e3bb8958823c20fa0e883499f
tree     8677230e75080e5fae606b8dfac568619bfd569c
subject  test(pack): include evidence mode in signature contract
HEAD     081d8554f814645517a29a0cef1c0e32af3d84df
```

All required identity values match exactly.

## Path, blob, diff, and assertion contract

`git diff-tree --no-commit-id --name-status -r 081d8554f814645517a29a0cef1c0e32af3d84df` returned only:

```text
M	tests/test_methodology_foundation_baseline.py
```

The exact committed object-byte hash is:

```text
tests/test_methodology_foundation_baseline.py
SHA-256 60bdd4c07ad1b386a9eeb9f61714e9c604e7b52246b99916e4275016db849048
Git blob bfc185ec0c5b6e597f5b9b9465f4badb5b4006f6
```

The complete commit diff is one replacement in `CURRENT_BUILD_PACK_SIGNATURE`:

```diff
-    "method_release_ids: 'Sequence[str]' = ()) -> 'PackManifest'"
+    "method_release_ids: 'Sequence[str]' = (), "
+    "evidence_mode: 'str | None' = None) -> 'PackManifest'"
```

Thus `evidence_mode` is appended after the existing keyword-only parameter list (which begins after `*`), with the specified default and unchanged return annotation. No assertion was removed or weakened. The previously failing test remains present:

```python
def test_build_pack_signature_has_explicit_method_selection() -> None:
    signature = inspect.signature(build_pack)
    assert str(signature) == CURRENT_BUILD_PACK_SIGNATURE
    assert signature.parameters["method_release_ids"].default == ()
```

It still asserts equality to the signature sentinel.

`git diff d740a646574b843e3bb8958823c20fa0e883499f 081d8554f814645517a29a0cef1c0e32af3d84df --check` exited `0`.

## Perimeter

The committed product/test perimeter was independently computed from Git tree records:

```sh
git ls-tree -r 081d8554f814645517a29a0cef1c0e32af3d84df -- ontologylab tests scripts pyproject.toml | LC_ALL=C sort | shasum -a 256
```

Result (404 paths):

```text
5bfc7bbd2dcd61ceddc43c31ba5afc2c8590fa36007d6af6748fa8b15f8850e6
```

This exactly matches the required repaired product/test perimeter. The one-path changed-blob content perimeter (`LC_ALL=C` sorted `path<TAB>content-sha256\n`) is `a88509c1e5772f485bb7f3a58efbcce42baf1c9399a05a7acfcec1d4dffc1652`.

## Index, exclusions, upstream, and no-push evidence

- `git diff --cached --quiet` exited `0`: index empty.
- `git diff --quiet HEAD -- ontologylab tests scripts pyproject.toml` exited `0`: tracked product/test perimeter matches HEAD.
- The commit path list has no `.gjc`, `.sisyphus`, `artifacts`, `docs`, `graphify-out`, or `uv.lock` entry. Pre-existing unrelated untracked paths are excluded and unstaged.
- Upstream is `origin/main`, at `4ee5465b9727a2ca3c00e7eea0f3893e2301c148`; local `main` is `ahead 55` at the verified commit.
- `git branch -r --contains 081d8554f814645517a29a0cef1c0e32af3d84df` returned no remote branch. `origin/main` remains unchanged and does not contain the commit; no push occurred.
- HEAD remains `081d8554f814645517a29a0cef1c0e32af3d84df` throughout verification.
