# Task 3 commit verifier

Date: 2026-08-23
Mode: read-only Git/history verification; no tests, product/test edits, commit, push, network, live-data, or port-8799 activity.

## Verdict

`confirmed`

Commit `1afd0f85b038475a3b0a43f477febd1b25bfce01` is the exact confirmed Task 3 F9 selection/research-consumer increment, including the isolated raw-path regression test.

## Commit identity and boundary

- `git show -s --format='commit=%H%nparent=%P%nsubject=%s' 1afd0f...`:
  - commit: `1afd0f85b038475a3b0a43f477febd1b25bfce01`
  - parent: `49ac5249fbfaecf0e18a00d08392166ea79250d5` (exact)
  - subject: `feat(extraction): receipt preferred representation selection` (exact)
- Commit tree: `d60bc0ebd5961971f2809461cca842a22608d30a`.
- `git diff-tree --name-only -r 1afd0f...` returned exactly 14 paths:
  - selection types/policy/IDs/schema/store/facade: `ontologylab/selection_types.py`, `selection_policy.py`, `selection_ids.py`, `selection_schema.py`, `selection_store.py`, `selection.py`
  - selection/research wiring: `ontologylab/research_extract.py`, `ontologylab/work_view.py`, `ontologylab/server/jobs.py`, `ontologylab/ingestion_shadow.py`, `ontologylab/connectors/base.py`
  - Task 3 tests: `tests/test_preferred_selection.py`, `tests/test_research_selection.py`, `tests/test_research_ready_boundary.py`
- The changed-path set has no `.omo/`, `docs/`, Task 4+, Citation, review, migration, or pack path. A committed-content scan for Task 4+ symbols returned no matches.
- Recomputed perimeter using the product-commit recipe (sorted `path<TAB>sha256(blob)\n` for those 14 paths): `0021ce5daae3e4031e05a6ffe1c7e92e35cf1a29e55bfedda20660519a122084` (exact).

## Contract evidence

- `selection_policy.py` V1 key is `(ready_rank, usable_full_text_rank, grade_rank, source_rank, stage_rank, -byte_length, content_hash)`; it refuses a V1 winner whose usable-full-text rank is nonzero.
- `research_extract.py` selects with `put_selection_receipt(..., PolicyVersion.V1)`, raises typed `NO_ELIGIBLE_READY_FULL_TEXT` when no selection exists, binds the selected representation, and obtains bytes through `read_ready_text(...)` before extraction.
- The committed isolated regression test `test_research_refuses_when_selected_ready_bytes_are_tampered` tampers the selected PMC ready file, requires `FileIntegrityError.reason == "hash_mismatch"`, and asserts no leak token plus zero run/chunk/node rows.
- The reviewed repair-verifier evidence (`task-3-repair-verifier.md`) records the isolated reader-only `Path(raw_text_path).read_text()` mutant failing this test, followed by byte-identical restore and GREEN; the committed test blob is the approved hash below.

## Approved blobs

`git show HEAD:<path>` and `git show :<path>` each SHA-256-match the repair-verifier approved value for all 14 paths:

```text
ontologylab/connectors/base.py 554e095301108e683c747447d98c86145dc3092a0a6d16642956eff3dbd81fdc
ontologylab/ingestion_shadow.py dfcd1d02c43c710e913fddb0c46afc5e7cc36b7dcc33b0e3e75de0fdc81a29fc
ontologylab/research_extract.py d2da049dd2c822a8ea2d9c1208d2ffec4010f104869489175b5b2c4ad33a20c3
ontologylab/selection.py 702fc8431d53422108ca82f7ec7d917039c8a832e1bcc12d86c8ae5fc25e90c9
ontologylab/selection_ids.py 242d3fb56eeac0c25c465505a7f1ecc7b5bc548ea75cd6715af9f6ad36f8fdfe
ontologylab/selection_policy.py 0c4c7ccfeeabccd6f846c3a629ebe02e9f853b103d2be3ef037b1e31881e556f
ontologylab/selection_schema.py 017795e17b2deb70b380ad1542a23cd0bc092e165a943537cc4564370a4cf7de
ontologylab/selection_store.py 60f12ee19fe58eaf0cdf27bf60892f4bbffe90d916b2e3ccd6951a6bd3cc47de
ontologylab/selection_types.py b06e489f58a45b30f77ad4325d71f7b9fcf5c8be34daf39cd5b6cfae3f90159a
ontologylab/server/jobs.py 6fd412136a097d6cc5bea3d0766cdd65061b3bda68ebdc49165603bef0e19023
ontologylab/work_view.py c771d04559f7387ae79fb654c5959fa4ccbff0975ae318d6c90ad8e4800044bf
tests/test_preferred_selection.py 0296cf4622522c0f79884c7956b85717dfaf8d0f0bbda4ee17c33c6cd6801fd2
tests/test_research_ready_boundary.py 7f037cc32caaa8cf20bb65589bf08a41b51e024c6163f9e6297feb27cb4657c3
tests/test_research_selection.py 0ab337b2e73376ac08669d7af27fde5331defaf50f529289f4d9b77ace57541c
```

## Repository state

- `HEAD` is `1afd0f85b038475a3b0a43f477febd1b25bfce01` on `main`; upstream is `origin/main`.
- Index is empty (`git diff --cached --name-status` produced no paths). All committed Task 3 paths have identical HEAD and index blobs.
- `origin/main` is `4ee5465b9727a2ca3c00e7eea0f3893e2301c148`; `git rev-list --left-right --count origin/main...HEAD` is `0 45`, and `git status --branch --short` reports `main...origin/main [ahead 45]`. This matches the product-commit report's unchanged origin/no-push evidence; no remote operation was performed here.
- Residual dirt is untracked and outside Task 3: `.sisyphus/`, `artifacts/`, seven listed `docs/` files, `graphify-out/`, `ontologylab/graphify-out/`, and `uv.lock`. There are no tracked or staged residual changes.
