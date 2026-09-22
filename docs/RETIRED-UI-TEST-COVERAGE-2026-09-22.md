# Retired UI-behavior coverage

2026-09-22. The vanilla dashboard file `ontologylab/web/app.js` is gone. The
modules below loaded that file, or a helper that loaded it, at import time
through `web_assets.read_asset_text("app.js")`. Pytest collection then raised
`FileNotFoundError`. They executed or scanned functions lifted out of that
script under Node. They are removed from collection. That is a coverage gap,
not a claim that the React UI still implements these contracts.

`frontend/package.json` has no test script (`dev`, `build`, `preview` only).
`frontend/tests/` is a Home/Graph browser regression against the served app.
It does not cover the contracts below. Restoring them needs a React-side
test runner against `frontend/src`.

## Removed from collection

| File | Coverage lost |
| --- | --- |
| `tests/test_ui_failure_honesty.py` | A busy/503 or `{ok:false}` write is shown as a refusal, not reloaded as success. 422 and array `detail` render as text. A partial extraction says results survived; a total failure does not invent them. The engine-failure string matches the server. An unusable pack directory is not a pack row, a diff option, or a connect command. |
| `tests/test_p0_ui_ux_contract.py` | Destructive actions use the shared confirm dialog before dispatch. Typed error surface, retry, and pending-failure preservation. Live chat trace. Palette focus returns to the invoker. Job identity and tab-motion contracts. |
| `tests/test_p1_ui_ux_contract.py` | Empty-state CTA, review "load more" only from the explicit button, keyboard-reachable disabled reasons, live regions limited to activity and appended chat, tablist shape, job/artifact machine contracts, graph pointer and keyboard activation, chat-session persistence, review-table overflow and identity floor. Also the only checks for `POST /api/sources/semanticscholar/test` mapping 200/401/429 without echoing the secret URL, and for the branded favicon being local, manifest-verified, and served. |
| `tests/test_p2_ui_ux_contract.py` | Copyable machine paths, settings path reveal, competency-question ids with Korean copy, engine-fallback warning, builtin ontology Korean copy, manifest-invalid copy, graph key guidance, pack overflow, relative timestamps with exact details, asset URLs bound to content hashes, copyable provider URL and term IRI. Also the only checks that an unregistered `default_engine` is rejected, and that MockEngine routes the Korean storage-status phrases to `status`. |
| `tests/test_agent_drivable_ui.py` | Agent-drivable names: every screen's navigation tab states `aria-label` rather than inferring it, icons are hidden from the tree, the status bar names location and activity, row actions name the proposal, and inputs are not named by placeholder, value, or help text. |
| `tests/test_agent_drivable_ontology.py` | Same naming contract on the ontology screen. Term definitions, aliases, and xref labels reach the DOM through `escapeHtml` or `textContent`. A literal NUL used as a JS map-key separator fails the scan. |
| `tests/test_dashboard_load_state.py` | Tab loader exposes loading, then settled, state. Executed through the honesty harness against `app.js`. |
| `tests/test_queue_auto_activation.py` | Conformal and calibration badges switch on only when triage/calibration report `available`. `calibratedConfidence` executed under Node against the shipped function. |
| `tests/test_review_request_ownership.py` | Shipped review loaders under ordered API completions: in-flight pagination, current-page errors preserving the queue, and fail-open controls. |
| `tests/test_research_job_outcomes.py` | Shipped job listeners and renderers against controlled wire fixtures, including busy 503, `{ok:false}`, cancel, and terminal states. |
| `tests/test_no_duplicated_constants.py` | The browser must not re-spell constants that already exist in Python (`DEFAULT_PAPER_SOURCE`, `DEFAULT_ENGINE`, `time_budget`, `max_engine_calls`, and the other drifted call sites that module named). |

## Helper removed with them

`tests/research_job_outcome_support.py` was the Node DOM and shipped-listener
driver for `tests/test_research_job_outcomes.py`. After that module was
removed, nothing else imported it.

## Left in place

`tests/test_proposals_pagination.py` and `tests/test_research_source_surface.py`
import retired helpers, but only inside functions that themselves read
`app.js`. Those functions are not passing tests, so they were not a reason
to keep the retired modules. They still fail when executed:

- `test_review_ui_row_cap` reads `app.js` directly.
- `test_review_scroll_listener_catches_the_real_scroll_container` imports `tests.test_review_request_ownership._run`.
- `test_the_ui_renders_badges_and_an_all_failed_banner` imports `tests.test_ui_failure_honesty._harness` and `_run_js`.

Other modules still call `web_assets.read_asset_text("app.js")` inside test
functions, so collection does not see them. They are the same gap, still
present, and were outside this retirement: `tests/test_artifacts.py`,
`tests/test_chat.py`, `tests/test_document_panel.py`,
`tests/test_engine_defaults.py`, `tests/test_enrichment.py`,
`tests/test_evidence_grade.py`, `tests/test_korean_ui.py`,
`tests/test_pack_completeness.py`, `tests/test_schema_install.py`,
`tests/test_searxng_source.py`.
