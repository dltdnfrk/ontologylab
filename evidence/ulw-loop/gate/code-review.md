# Code review: InvalidateAction schema binding

**Scope:** uncommitted working-tree delta of

- `ontologylab/server/schemas.py` (`+InvalidateAction`)
- `ontologylab/server/routes.py` (import + one binding change)
- `tests/test_bitemporal.py` (test updates)

**Stated intent:** `POST /api/edges/{edge_id}/invalidate` previously bound
`ProposalAction` (required body `id`, never read — id is in the path), so the
dashboard's `{note}`-only request always 422'd. The fix adds a minimal
`InvalidateAction(by, note)` schema and binds it on that one route.
`ProposalAction` must remain untouched for the body-addressed
`/proposals/approve|reject|reopen` routes.

**Out of scope (noted, not judged):** the rest of the dirty tree is separately
verified prior work. In particular `routes.py` also contains `list_packs` →
`scan_packs` / `unusable` changes that are **not** part of this review. Other
modified/untracked files (`packbuilder.py`, docs, `web/app.js`, etc.) are
likewise ignored except where they supply contract evidence for this change.

Review is read-only. No files were edited except this report.

---

## 1. Correctness — PASS

The route still addresses the edge from the path and still forwards `by` /
`note` into the store. There is no behavioral change beyond the request-body
schema.

Evidence:

- Binding only (`routes.py:499-504`):

```499:504:ontologylab/server/routes.py
@router.post("/edges/{edge_id}/invalidate")
def invalidate_edge(deps: AppDependency, edge_id: str, body: InvalidateAction) -> dict[str, Any]:
    """W13: mark a verified edge as no-longer-current (kept as history)."""
    store = _open_store(deps)
    try:
        result = store.invalidate_edge(edge_id, by=body.by, reason=body.note)
```

- Handler body is otherwise unchanged: same `UnknownItem` → 404 /
  `KGStoreError` → 400 mapping, same `{"ok": True, **result}` return, same
  `finally: store.close()`.
- `store.invalidate_edge` still takes path `edge_id` plus keyword `by` /
  `reason` (`ontologylab/kgstore.py:2826-2831`, write at `2854-2858`). The
  route never read `body.id` before this change; dropping it from the schema
  cannot change which row is invalidated.
- Dashboard contract this unblocks (`web/app.js:3359-3360`):

```3359:3360:web/app.js
        "/api/edges/" + encodeURIComponent(edgeId) + "/invalidate",
        { note: "invalidated via dashboard" }
```

- `InvalidateAction` supplies the same defaults the old schema did
  (`by=DEFAULT_ACTOR`, `note=None`; `schemas.py:218-219`), so an empty `{}`
  body is now a valid invalidate (previously 422 on missing `id`). That is
  the intended fix, not a side-effect.

**Verdict:** correct. Only the binder changed.

---

## 2. Contract safety — PASS

`ProposalAction` is untouched. Body-addressed proposal routes still require
`id`. Extra-body-field ignore is acceptable here.

Evidence:

- `git diff -- ontologylab/server/schemas.py` is insert-only after
  `ProposalAction`. The class itself is byte-identical:

```202:208:ontologylab/server/schemas.py
class ProposalAction(BaseModel):
    """Approve or reject a single proposed node/edge."""

    id: str
    by: str = DEFAULT_ACTOR
    note: Optional[str] = None
    cascade: bool = False
```

- Proposal routes still bind `ProposalAction` and still consume `body.id`:
  - `approve_proposal` `routes.py:481-486` → `store.approve(body.id, ...)`
  - `reject_proposal` `routes.py:514-518` → `store.reject(body.id, ...)`
  - `reopen_proposal` `routes.py:528-537` → `store.reopen(body.id, ...)`
- Runtime check (pydantic 2.13.4):
  - `ProposalAction.model_validate({"note": "x"})` → `ValidationError`,
    `id` Field required.
  - `InvalidateAction.model_validate({"note": "x"})` and
    `InvalidateAction.model_validate({"id": "e1", "note": "x"})` both succeed;
    extras are ignored (default `model_config`, no `extra="forbid"` anywhere
    in `ontologylab/server/schemas.py`).

**Extra-field tolerance:** acceptable, not a risk for this endpoint.

- Identity is the path param. A leftover body `id` cannot retarget the write.
- A leftover `cascade` (old `ProposalAction` field) is likewise ignored and
  was never forwarded to `invalidate_edge`.
- Forbidding extras would 422 any client that worked around the old required
  `id` by sending it. The new test documents that compatibility on purpose
  (`tests/test_bitemporal.py:275-308`).
- Proposal routes keep the strict required-`id` contract because they have
  no path id.

**Verdict:** proposal contract preserved; extra ignore is the right call.

---

## 3. Security / robustness — PASS

No injection, no mass-assignment surface beyond the two intended fields, no
validation weakening except the deliberate removal of unused required `id`.

Evidence:

- New model fields are only `by: str = DEFAULT_ACTOR` and
  `note: Optional[str] = None` (`schemas.py:218-219`). Same types/defaults
  as `ProposalAction` and `MergeDismiss` (`schemas.py:206-207`, `272-273`).
- Store write is parameterized (`kgstore.py:2854-2857`):
  `UPDATE edges SET ... WHERE id = ?` with `(now, by, reason, edge_id)`.
  `note` cannot become SQL.
- Mass-assignment: pydantic will not bind unknown keys onto the model, so a
  client cannot set `invalidated_ts` / status / etc. through this body. The
  only actor-controlled values are `by` and `note`, which this route already
  accepted via `ProposalAction`.
- `by` remains an unconstrained string (no max length). That is pre-existing
  on every action schema, not introduced here. Local single-user actor
  default is unchanged (`ontologylab/paths.py:38`, `DEFAULT_ACTOR = "local-user"`).
- Status mapping is unchanged: unknown id → 404, already-invalidated /
  not-verified / not-an-edge → 400 (`routes.py:506-509` +
  `kgstore.py:2844-2852`). Empty body no longer 422s; that is the bugfix,
  not a guard being dropped.

**Verdict:** no new attack or robustness hole.

---

## 4. Test quality — PASS

Updated/new tests assert the real contract. They do not pin prose. One
assertion is slightly thinner than it could be, but not hollow.

Evidence (`tests/test_bitemporal.py`):

| Contract | Where | Assertion |
|---|---|---|
| `{note}`-only succeeds (422-on-missing-id would now be wrong) | `231-234`, `259-262` | `200` and `ok is True` with `json={"note": "superseded"}` |
| note actually lands | `265-272` | `invalidated_ts is not None`, `invalidation_reason == "superseded"` |
| double-invalidate 400 | `235-237` | second `POST` with `json={}` → `400` |
| unknown id 404 | `238-239` | `/api/edges/nope/invalidate` + `json={}` → `404` |
| redundant body `id` tolerated | `275-308` | reset row, `POST` `{"id": edge_id, "note": "again"}` → `200` |

- No 422-on-missing-id assertion remains. The old `json={"id": edge_id}`
  payloads were rewritten to `{note}` / `{}`.
- No error-message / docstring / UI-copy pinning. Status codes and DB
  columns only. (Existing store-level tests still `match=` on
  `KGStoreError` text — those were not part of this delta.)
- The new test's docstring states the regression (`243-249`) but is not
  asserted.
- Setup is real: seeds a verified edge through `_seed_verified_edge` and
  hits `TestClient` against `create_app`, then reads SQLite. Not a mock of
  the binder.

Minor observation (not a fail): the redundant-`id` branch asserts only
`status_code == 200` (`307-308`) and does not re-read
`invalidation_reason == "again"` or `ok is True`. That is enough to lock
extra-field tolerance; persistence of `note` is already covered on the
first request. The raw-SQL un-invalidate (`280-286`) bypasses the store
API to reuse the same edge — a little ugly, but deterministic and local.

**Verdict:** tests lock the real HTTP contract.

---

## 5. Style consistency — PASS

Matches the file's existing action-schema conventions.

Evidence:

- Placement: immediately after `ProposalAction`, before `CriticRunRequest`
  (`schemas.py:211-219`) — the natural neighbor.
- Shape: same as path/implicit-identity `MergeDismiss` (`by` + `note`,
  `schemas.py:269-273`), not a fork of `ProposalAction` with `id` optional.
- Docstring explains *why* the type exists (path-addressed id; dashboard
  `{note}`-only 422), same rationale-in-docstring habit as `MergeAction`
  (`256-261`) and `reopen_proposal` (`530-534`).
- Import inserted alphabetically in the `ontologylab.server.schemas`
  block (`routes.py:125`, between `ExtractRequest` and `JobStatus`).
  `ProposalAction` import remains (`routes.py:131`).
- Naming: `InvalidateAction` / `body: InvalidateAction` parallel
  `ProposalAction`, `MergeAction`, `MergeDismiss`.

**Verdict:** consistent. No style nits worth blocking on.

---

## 6. Run — PASS

Commands run on this machine (darwin/arm64). `timeout` was not used. Port
8799 was not bound.

```
$ .venv/bin/python -m pytest tests/test_bitemporal.py -v
============================= test session starts ==============================
platform darwin -- Python 3.12.12, pytest-9.1.1, pluggy-1.6.0
collected 10 items

tests/test_bitemporal.py ..........                                      [100%]
======================== 10 passed, 1 warning in 0.44s =========================
```

The single warning is the pre-existing Starlette `TestClient` deprecation
(`httpx` → `httpx2`), not caused by this change.

```
$ .venv/bin/python -c "import ontologylab.server.routes"
```

Import succeeded. `invalidate_edge.__annotations__['body']` is
`InvalidateAction`.

---

## Overall

The change is the smallest correct fix for a real 422: a new two-field
schema bound on the one path-addressed route, `ProposalAction` left alone,
dashboard `{note}`-only now succeeds, and the tests were rewritten to the
new contract instead of the old required-`id` shape.

RECOMMENDATION: APPROVE
CODE_QUALITY_STATUS: CLEAR
