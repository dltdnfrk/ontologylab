# Task 4 commit verifier

Date: 2026-08-24
Mode: read-only Git/history and filesystem-metadata verification. No tests, network, live-data, port-8799, index, or worktree mutation.

## Verdict: confirmed

`7c159fd3efa24a5b9839e0ae32643e7f90560124` is the exact confirmed Task 4 Citation increment.

- `git show -s --format='%P%n%s' 7c159fd...` returned parent exactly `1afd0f85b038475a3b0a43f477febd1b25bfce01` and subject exactly `feat(citations): seal representation grounding receipts`.
- `git diff-tree --no-commit-id --name-status -r 7c159fd...` returned exactly 11 paths: seven new Citation modules (`citation.py`, `_bind`, `_ids`, `_schema`, `_store`, `_types`, `_verify`), the `extractor.py` persistence hook, the `extraction_state.py` schema hook, and the two focused/decision tests. It contained no `research_extract.py`, ReviewDecision/review-grounding path, `docs/`, `.omo/`, or other unrelated path.
- The committed path set is:

```
A ontologylab/citation.py
A ontologylab/citation_bind.py
A ontologylab/citation_ids.py
A ontologylab/citation_schema.py
A ontologylab/citation_store.py
A ontologylab/citation_types.py
A ontologylab/citation_verify.py
M ontologylab/extraction_state.py
M ontologylab/extractor.py
A tests/test_citation_receipt_decisions.py
A tests/test_citation_receipts.py
```

- Recomputed SHA-256 for each committed `commit:path` blob; all 11 match the approved executor/repair/repair-verifier freeze recorded in `task-4-product-commit.md`. The sorted `path<TAB>sha256\n` perimeter recomputes exactly to `bbf7f76bf97397001a50d495cace5e94542b058c239417618cddb460ec5f8487`.
- Evidence chain: executor recorded the original product freeze; recovery reported `clean-for-reverification`; retry reported `needs-fix`; repair added only the decision test; repair verifier recorded `confirmed`; the product-commit report records this exact commit and the same 11 hashes/perimeter.
- Current index is empty (`git diff --staged --name-status` produced no output). `origin/main` remains `4ee5465b9727a2ca3c00e7eea0f3893e2301c148`, matching the Task 4 commit report; branch is `main...origin/main [ahead 46]`. The report and current remote-tracking ref support no observed push/origin change.

## Excluded Task 5-like residue

All six paths are currently untracked (`??`), absent from `HEAD`, absent from the index, and have no Git diff base. `git diff-tree` confirms Task 4 touched none of them.

| Path | State / base | Filesystem mtime | Size | Provenance clues |
| --- | --- | --- | ---: | --- |
| `ontologylab/review_decision.py` | untracked; HEAD base absent | 2026-08-23T23:46:10+0900 | 6279 | Explicitly excluded as Task 5 in Task 4 product-commit report |
| `ontologylab/review_decision_ids.py` | untracked; HEAD base absent | 2026-08-23T23:46:00+0900 | 1652 | same |
| `ontologylab/review_decision_schema.py` | untracked; HEAD base absent | 2026-08-23T23:46:05+0900 | 2229 | same |
| `ontologylab/review_decision_store.py` | untracked; HEAD base absent | 2026-08-23T23:46:10+0900 | 6434 | same |
| `ontologylab/review_decision_types.py` | untracked; HEAD base absent | 2026-08-23T23:45:55+0900 | 1928 | same |
| `ontologylab/review_grounding.py` | untracked; HEAD base absent | 2026-08-23T23:46:10+0900 | 5697 | Explicitly excluded as Task 5 waiver/grounding work |

Task 4 retry evidence says these concurrent untracked paths appeared after recovery at 23:44, with mtimes 23:45-23:46, and were neither read nor edited by its verifier. The product-commit report independently lists the same six paths as excluded and never staged. This establishes Task 4 non-ownership and their presence before the commit; it does not establish which Task 5 actor created them or that their content is an approved Task 5 baseline.

Associated test check: `tests/test_entity_review.py` is tracked, exists in `HEAD`, has no staged or unstaged diff, and has mtime `2026-07-21T20:41:51+0900`; no uncommitted Task-5-named test path is present in status. It is not Task 5 residue on the available metadata.

## Residual-ownership recommendation

Treat the six untracked review source files as an **unknown-owner conflict**, not safely adoptable pre-existing Task 5 work: preserve them untouched and require an owner/baseline attestation before a Task 5 executor reads, edits, stages, or incorporates them.
