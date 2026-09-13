# Home and Graph browser regression

Run from the repository root with Bun 1.4+ and an installed Chrome. The runner
starts its own headless Chrome, not the user's browser. It uses the production
assets served by FastAPI and a real, disposable SQLite store.

Choose a new directory under `/private/tmp/ontologylab-recovery-...` and an unused
loopback port. In the example below, replace both paths consistently; never use
the live server on port 8799.

```sh
PYTHONPATH=. uv run python frontend/tests/seed.py /private/tmp/ontologylab-recovery-example/data
ONTOLOGYLAB_OFFLINE=1 uv run python -m ontologylab.serve \
  --port 18876 \
  --data-dir /private/tmp/ontologylab-recovery-example/data \
  --packs-dir /private/tmp/ontologylab-recovery-example/packs
```

From another terminal:

```sh
bun frontend/tests/recovery.browser.mjs \
  http://127.0.0.1:18876 /private/tmp/ontologylab-recovery-example
```

The seed refuses an existing database. The browser runner checks the fixture
document before changing only the named fixture proposals. Subsequent runs
reopen those proposals, so approve/reject checks execute again. Failed checks
produce a nonzero exit. Screenshots stay in the supplied output directory.
The Graph race holds an actual API response and releases it after the second
selection; it does not manufacture entity-detail payloads.

The related package checks are:

```sh
uv run --all-extras pytest tests/test_dashboard_assets.py \
  tests/test_dashboard_routes.py tests/test_dashboard_wheel.py \
  tests/test_candidate_package.py tests/test_macos_runtime_package.py -v
```

The wheel test builds a fresh temporary source tree. Reusing `build/lib` after
the vanilla-to-React migration can bundle retired assets from that old cache.
