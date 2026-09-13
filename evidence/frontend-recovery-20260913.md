# Frontend recovery verification

Base: `4fd2091`, canonical OntologyLab checkout. This is the continuation of
abandoned session `01a0602e`; its completed page implementations were preserved.
No commit, release-receipt issuance, installation, or deployment has occurred.

## Changes and observed failures

- Home: a 375px viewport had a 311px main panel with 600px scroll width.
  The review card now allows its table wrapper, not the whole page, to scroll.
- Shared links: `--accent` is a dark surface token, not readable link ink.
  Links now use the existing `--point` action token.
- Graph: a held, genuine Alpha detail response overwrote a later Beta
  selection. Request generations now guard success, failure, and loading state.
- Graph mobile: nodes stayed outside the resized canvas and the fixed page
  height compressed the detail panel. Resize schedules fitting; narrow screens
  allow the full graph and detail content to scroll vertically.
- Direct React URLs: ten non-root routes returned 404. The server now serves
  the verified document and bootstraps the local session on the eleven known
  dashboard paths. Unknown API, asset, and page paths still return 404.
- The React Sources page still offered sample collection despite the old goal.
  Its button, state, response type, and `/collect/sample` invocation are removed.
  This is a shipped-UI change, not deletion of existing user data.
- A fresh wheel omitted both Vite assets. Package-data globs now include
  `assets/*.js` and `assets/*.css`. A separate checkout build also contained
  retired files from old `build/lib`; the regression builds a fresh temporary
  source tree and imports the wheel with `python -I`.
- HTTP byte pins still described the old nine-file vanilla dashboard. They now
  pin the current three-file React bundle without weakening integrity checks.

## Verification

All commands ran from the canonical checkout, except the explicit frontend
working directory for TypeScript/Vite. Live data and port 8799 were untouched.

```sh
# In frontend/
./node_modules/.bin/tsc --noEmit --incremental false
./node_modules/.bin/vite build \
  --outDir /private/tmp/ontologylab-recovery-01a0979e/final-build \
  --emptyOutDir false

# In repository root
uv run python -m ontologylab.web_assets check
uv run --all-extras pytest \
  tests/test_dashboard_assets.py tests/test_dashboard_routes.py \
  tests/test_dashboard_wheel.py tests/test_candidate_package.py \
  tests/test_macos_runtime_package.py tests/test_server.py \
  tests/test_security_hardening.py \
  --basetemp=/private/tmp/ontologylab-recovery-final-pytest-01a0979e -v
bun frontend/tests/recovery.browser.mjs \
  http://127.0.0.1:18876 /private/tmp/ontologylab-recovery-01a0979e/final
git diff --check
```

Results: TypeScript and Vite exit 0; three assets verified; **81 pytest cases
passed**; **14 browser checks passed**; diff check exit 0.

The browser checks exercise a real disposable SQLite store, real FastAPI
responses, and an isolated Chrome renderer. They cover summary counts,
approve/reject persistence, 409 refusal without authority change, mobile table
overflow, link visibility, graph nodes/edges, deliberately reordered details,
verified-only filtering, search, keyboard selection, mobile node visibility
and detail height, reload, and Sources navigation without sample insertion.
The red versions failed for the recorded regressions before fixes.

Final screenshots, directly inspected, are under
`/private/tmp/ontologylab-recovery-01a0979e/final/`, including Home review,
Graph selection/mobile detail, and Sources collection at desktop/mobile widths.
The fixture and rerun instructions are in `frontend/tests/`.

Verified wheel:

`/private/tmp/ontologylab-recovery-final-pytest-01a0979e/test_fresh_wheel_contains_and_0/dist/ontologylab-0.1.0-py3-none-any.whl`

SHA-256: `e025b99a7e277f4957eedd269be868521334da58563f8c59a63ff602d923bba8`.

The wheel was also run directly with `python -I`, with its ZIP import path
inserted before importing `ontologylab.server.app`. The reported module path
was inside the wheel, not the checkout. On isolated port 18878, `/`, `/graph`,
and `/sources` returned HTTP 200, the current HTML hash, and local HttpOnly
session cookies. All three `/static/` assets returned HTTP 200 with their
exact current byte lengths and hashes. A new store returned an authenticated
empty proposal queue and zero documents, without seeding sample data.
This wheel runtime check is separate from signed DMG/ZIP issuance.

Shipped JavaScript: `assets/index-BnI1lA4K.js`, 642918 bytes,
SHA-256 `5caf347192fb2d66f3f9acb2352f42ec84deed745e3b23596362e6d2a1d924f4`.
The asset patch writer adds a final newline to Vite's JavaScript output; the
manifest and byte pins hash the actual shipped bytes, including that newline.

Limitations: Graph LSP diagnostics intermittently timed out; the complete
TypeScript compiler passed. CSS/HTML/JSON Biome diagnostics were unavailable
because Biome is not installed. Vite reported its native-config warning and
the existing large-chunk warning; neither was suppressed. The full historical
test suite and unrelated deployment/upgrade trials were not rerun.

## Package scope resolution

The existing `final-v13` signed app contains the old `index-DvXbqY7w.js`.
It is not an artifact of these fixes. Its evidence was not rewritten.

The public `release.candidate_source.verify_source(Path("."))` check exits 1:

```text
source_changed_after_snapshot:ontologylab/server/app.py
```

On 2026-09-13 the user clarified that this is a web app and no DMG is needed.
The signed macOS package deliverable was therefore descoped: the verified
wheel (above) is the final package evidence for this goal — it contains the
current React frontend, serves all dashboard routes, and seeds no sample
data. Commit/receipt reissuance and a new signed DMG/ZIP are NOT part of this
work and remain available as a separate, explicitly authorized task.
