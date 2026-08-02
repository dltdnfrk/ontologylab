# ontologylab

Papers in, a reviewed knowledge graph out. Fetch → extract proposals with
character spans → a human approves → build an immutable pack an agent can
query over MCP. Nothing becomes knowledge without someone approving it.

The rest of this file is gotchas. Structure, module names and test layout
are all readable from the tree; these are the things that have actually
cost time.

## The data directory is not `./data`

The launcher and the launchd agent both run with
`--data-dir ~/Library/Application Support/ontologylab/data`, because
`move-data-out-of-icloud.sh` moved it there — `~/Documents` is iCloud-synced
on this machine, and `paths.icloud_refusal` **exits the server** rather than
sync a knowledge graph to Apple.

Consequences worth knowing before debugging:

- `./data/kg.sqlite` still exists and is stale. The live store is the
  Application Support one, and it is the larger of the two. Reading the
  wrong one makes a populated system look empty.
- Starting the server without `--data-dir` fails with a refusal **before any
  log file is created**, so `.launcher.log` is empty and the launcher looks
  broken for an unrelated reason.
- `settings.json` lives beside the data it configures. It used to be derived
  from `ROOT` regardless of `--data-dir`, which split every install in two;
  `load_settings` still reads the old location once as a fallback.

## Do not call route functions as plain functions

A FastAPI route's defaults are `Query(...)` **objects**, not values.
`search_entities(q=query)` binds a marker object as `limit`, which reaches
sqlite as `Error binding parameter 4: type 'Query' is not supported`. There
are 21 such defaults in `server/routes.py`. If you call one internally,
supply every parameter by name.

## MockEngine only finds CamelCase

It scans for tokens like `RateLimiter`. Biomedical abstracts contain none,
so `mock` legitimately extracts **zero** from a real paper — that is not a
bug, and chasing it as one wastes a lot of time. Use `--engine claude` to
judge extraction quality.

It also reads the entity and relation types out of the prompt's schema
block. Hardcoding either made it silently produce nothing under every
ontology except `software-docs`.

## The ontology decides what the extractor finds

`schemas.PRESETS` holds the bundled ones; `KGStore.install_schema` adds one
and deactivates the previous. Switching is additive on purpose: proposals
keep pointing at the `schema_version_id` they were judged against, so a
review queue someone is halfway through keeps meaning what it meant.

Measured on 20 biomedical papers: under `software-docs`, 54% of relations
came back `related_to`; under `biomed-v1`, 26%. If extraction output looks
uselessly vague, check the active ontology before changing anything else.

## Registry codes do not come from the model

EPPO and PubChem/CAS caches are **import-first** local data. If a cache is
absent, normalization is off for that registry and extraction continues with
one provenance warning; absence is not a broken network fetch. The LLM is
never the authority for EPPO or CAS codes: matching cache data supplies the
code and an unsupported model-supplied code is dropped. The CAS identity then
drives the local FRAC/IRAC/HRAC mapping.

## The agrochem gold fixture is constructed

`tests/gold/agrochem-mini/docs.json` contains five repeated, constructed
passages, not real abstracts. It is useful for controlled extraction scoring
and AC evidence, not representative-corpus claims.

`TARGET_CHUNK_TOKENS` is 3,000 because the measured 1,500/3,000 Claude sweep
preserved recall while halving calls; the protocol and limits are in
`docs/CHUNK-SWEEP-2026-08.md`. Do not reset it from the old roadmap's 1,500
without new measured evidence.

## Tests must not touch real state

`tests/conftest.py` has an autouse fixture that redirects settings writes,
because the suite overwrote the developer's real `settings.json` three
times. Anything that writes outside `tmp_path` needs the same treatment.

`pytest` is configured with `-q` in `pyproject.toml`, so passing `-q` again
gives `-qq` and suppresses the summary line — use `-v` or plain `pytest`
when you need the count.

## Verification standard

Mutation testing, not coverage: break the behaviour on purpose and confirm
a test fails. A test that passes against deliberately broken code is the
default failure mode here, and this repo has shipped several — a confirm
gate compared against a re-derivation of itself, an escaping check that
looked at one occurrence out of eight.

Commit messages explain **why**, in prose, including what was measured and
what was walked back. See `git log` for the register.
