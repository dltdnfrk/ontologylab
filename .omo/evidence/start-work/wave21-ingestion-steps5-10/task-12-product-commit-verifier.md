# Wave 2.1 Step 8 Task 12 - Product Commit Boundary Verification

## Verdict: CONFIRMED

Verification used commit objects only; no checkout, reset, stash, rebase, amend, push, test, network, server, authority, or plan operation was performed. Product and test paths were read-only. The only repository write by this verifier is this report.

## Commit identity

Command:
```sh
git show -s --format='commit=%H%ntree=%T%nparent=%P%nsubject=%s' d740a646574b843e3bb8958823c20fa0e883499f
```

Result:
```text
commit=d740a646574b843e3bb8958823c20fa0e883499f
tree=3ff4a69d910df6deea70e9bb26f6fa5924e6482d
parent=1c06fef63451c836e3d9366b707e89d34e8ff037
subject=feat(pack): complete verified v2 publication boundary
```

All required identity values match exactly.

## Exact committed path boundary (23 paths)

Command:
```sh
git diff-tree --no-commit-id --name-only -r d740a646574b843e3bb8958823c20fa0e883499f | LC_ALL=C sort
```

Result (23):
```text
ontologylab/mcp_server.py
ontologylab/pack_readiness.py
ontologylab/pack_receipt_seal.py
ontologylab/pack_v2_closure.py
ontologylab/pack_v2_manifest.py
ontologylab/pack_verifier.py
ontologylab/packbuilder.py
ontologylab/packdiff.py
ontologylab/review_decision.py
ontologylab/review_decision_ids.py
ontologylab/review_decision_schema.py
ontologylab/review_decision_store.py
ontologylab/review_decision_types.py
ontologylab/review_grounding.py
ontologylab/verified_pack_reader.py
tests/test_mcp_pack_integrity.py
tests/test_ontology_pack_publication.py
tests/test_pack_readiness_refusal.py
tests/test_pack_v2_closure.py
tests/test_pack_v2_publication_surface.py
tests/test_pack_v2_verifier.py
tests/test_packdiff.py
tests/test_verified_pack_reader.py
```

Command:
```sh
git diff-tree --no-commit-id --name-only -r "$commit" | grep -Ev '^(ontologylab/(mcp_server|pack_readiness|pack_receipt_seal|pack_v2_closure|pack_v2_manifest|pack_verifier|packbuilder|packdiff|review_decision|review_decision_ids|review_decision_schema|review_decision_store|review_decision_types|review_grounding|verified_pack_reader)\.py|tests/test_(mcp_pack_integrity|ontology_pack_publication|pack_readiness_refusal|pack_v2_closure|pack_v2_publication_surface|pack_v2_verifier|packdiff|verified_pack_reader)\.py)$'
```

Result: no output; whitelist check `PASS`. The boundary contains only integrated Step 8 pack product/tests and the six clean-checkout review dependency modules.

## Committed object-byte SHA-256 values

Each value is SHA-256 of the exact `git show "$commit:$path"` byte stream:

```text
ontologylab/mcp_server.py	a0767807ea3cd3c44b57edb438f598b34bc99ef55ba4d204dde4321c915f262d
ontologylab/pack_readiness.py	c2c4b13f673f8e46ad2bcd985234e947b184f4d3edbfb2a7a4cfb5b1ce92e0e5
ontologylab/pack_receipt_seal.py	93a51a1e0d32f558da3e6ee4c960e400bd4191849690b57198f2f733dea17751
ontologylab/pack_v2_closure.py	3c82878de02f385584ee3d60970407a362e37d338727f695065eee4e831006e2
ontologylab/pack_v2_manifest.py	f1f629c9b6e492285eaa1ac4e78b6c523fef22275546af80fa419f92332267a4
ontologylab/pack_verifier.py	052ec3d12ece21b4afd31485357a8082b131a55ec19f82527fc02ebc7037872c
ontologylab/packbuilder.py	e903936ec8df14e37396d2c3db579713840cd64f82df8aeb83d4e012e81867b7
ontologylab/packdiff.py	cc148c3d4bd444f2f0cae1e4764ed03b28f6194472c5893d22e2edf5addb0292
ontologylab/review_decision.py	6aa8781ac58ad736d7155b0ac7390dfdfdf6ae2b982a07ed418e145e7eecc405
ontologylab/review_decision_ids.py	278aef15a0d6d612af48ad2ff97d0f3553e911a1413dd1d377a43606e290933e
ontologylab/review_decision_schema.py	d69db550d29b3bcb29dbd8d2aff3ddc547f52ce6e4d3d29f5d7bdaa0c40c58a9
ontologylab/review_decision_store.py	cd5820505d07de22eb0efa56ae319af1e8a10d1e78855cfb22931f1ddf5e6be3
ontologylab/review_decision_types.py	abf7171f23efd4eaaf332d457028809ce7b5e504ff774a9fd5cc79179d8d1c17
ontologylab/review_grounding.py	4bc5f793bf4bda6b93ab03c702a8dbe4f59a57c295747a06e63f442957b343fb
ontologylab/verified_pack_reader.py	6607a5523f03ac9c70ecb4686478e5b53a62baf9ef283575b656fb310d0a4ca1
tests/test_mcp_pack_integrity.py	25e109033875766b5a24a20b81984e241274341b6eff1b10b204f005e2d7e322
tests/test_ontology_pack_publication.py	cfa25516f0a1fa7aacf03698ad5f5dc29ab9235d736a6b631138f58e8a01f7d2
tests/test_pack_readiness_refusal.py	fc3985fe9d04a31e92d71dbae0cc69d142019d025f498c1e789bfea42868e8e7
tests/test_pack_v2_closure.py	105f97fb4979abcf640e1318dfaac515171466beba96a7e5df39443d5cb1895d
tests/test_pack_v2_publication_surface.py	5ae476936ccc00ae2ad2a3c2576513abb1f3946fbd136ae87bb742500dc5d9ba
tests/test_pack_v2_verifier.py	9bb61f372a09efdac483a04c0b7996ac7a60a369eb9e018e11575d8f819d3660
tests/test_packdiff.py	daae25385e55492289dafd662bb8a5a4a6bc51c4e3ebcd9a9fcca646e74281bc
tests/test_verified_pack_reader.py	7bdfa1c4a2da2fbb472c77d7e629525762eeaa0cd0509fae0ba614d79e7ec095
```

## Deterministic perimeters

Command for the 23-path content perimeter:
```sh
git diff-tree --no-commit-id --name-only -r "$commit" | LC_ALL=C sort |
while IFS= read -r p; do
  printf '%s\t' "$p"
  git show "$commit:$p" | shasum -a 256 | awk '{print $1}'
done > /tmp/wave21-commit-blobs.tsv
shasum -a 256 /tmp/wave21-commit-blobs.tsv
```

Result (`LC_ALL=C` sorted `path<TAB>content-sha256\n` stream):
```text
4d00b6a6140696ec1d36c838e2a7c865e9554e9ce812bfb4251619c71944d08a
```

Command for the committed product/test tree perimeter:
```sh
git ls-tree -r "$commit" -- ontologylab tests scripts pyproject.toml | LC_ALL=C sort | shasum -a 256
```

Result:
```text
40aa6d5af0054ed89d24ee4f9a2e5bd71a394d3644ac7c7c9966291583b08ca8
```

This exactly matches the required committed product/test perimeter. The tree command covers 404 paths.

## Six review-module clean-checkout correction

Command:
```sh
for p in ontologylab/review_decision.py ontologylab/review_decision_ids.py ontologylab/review_decision_schema.py ontologylab/review_decision_store.py ontologylab/review_decision_types.py ontologylab/review_grounding.py; do
  git cat-file -e "$commit^:$p" 2>/dev/null || true
  git log --format=%H "$commit^" -- "$p"
  git ls-tree -r --name-only "$commit" -- "$p"
done
```

Result for every listed module: direct parent `ABSENT`; all ancestor history before the commit `ABSENT`; commit tree `TRACKED`. Therefore these six files are newly tracked clean-checkout dependencies, not unrelated scope.

## Integrity, exclusions, and repository state

Command:
```sh
git diff d740a646574b843e3bb8958823c20fa0e883499f^ d740a646574b843e3bb8958823c20fa0e883499f --check
git diff --cached --quiet
```

Result: both exit `0` (clean diff check; empty index).

Command:
```sh
git diff-tree --no-commit-id --name-only -r "$commit" | rg '(^|/)(\.gjc|\.sisyphus|artifacts|docs|graphify-out)(/|$)|(^|/)uv\.lock$'
```

Result: no output. No `.gjc`, `.sisyphus`, `artifacts`, `docs`, `graphify-out`, or `uv.lock` path is committed.

Command:
```sh
git rev-parse HEAD
git rev-parse --abbrev-ref --symbolic-full-name '@{upstream}'
git rev-parse origin/main
git status -sb | head -1
```

Result:
```text
d740a646574b843e3bb8958823c20fa0e883499f
origin/main
4ee5465b9727a2ca3c00e7eea0f3893e2301c148
## main...origin/main [ahead 54]
```

HEAD remains the commit under test. Upstream remains `origin/main`; the local branch is ahead by 54 and `origin/main` remains `4ee5465...`, so this commit has not been pushed. Pre-existing untracked unrelated paths were observed but were not staged or committed; the index remained empty.
