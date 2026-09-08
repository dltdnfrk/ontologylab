"""A dashboard that reports a write it did not perform is worse than one
that crashes.

Four defects share one root: the browser treats a shaped failure envelope as
if it were a success. The server answers a contended write with 503 and
``{ok: false, error_kind: "busy"}``; ``apiSend`` deliberately returns that
body rather than throwing, so ``{ok:false}`` contracts can be rendered — and
three call sites then guard with ``res.ok === undefined``, which ``false``
does not satisfy. The write is refused, the row reloads, and the operator is
told nothing. A partial extraction has the mirrored problem in the other
direction: it is now ``failed``, but it produced real proposals from the
chunks that survived, and calling it a flat failure discards them.

These tests run the shipped functions rather than reading them. Asserting on
source text pins how a fix is spelled, not whether it works: a guard can be
rewritten into something that still lets a 503 through and still match a
regex. Everything here is executed under node against a stub DOM, so the
question asked is the operator's — what appeared on screen, and did the page
reload as though the write had landed.
"""

from __future__ import annotations

import json
import shutil
import subprocess

import pytest

from ontologylab import web_assets

APP_JS = web_assets.read_asset_text("app.js")
UI_UTILS_JS = web_assets.read_asset_text("ui-utils.js")


# --------------------------------------------------------------------------
# Running the real thing
# --------------------------------------------------------------------------


def _extract(name: str) -> str:
    """Lift one top-level function out of the app's IIFE, verbatim.

    `app.js` is a single closure, so a function cannot be imported. Every
    function in it is indented exactly two spaces and closes on a line of
    two spaces plus a brace, which is what bounds the slice. A missing
    marker raises rather than silently testing nothing.
    """
    for opener in (f"  async function {name}(", f"  function {name}("):
        if opener in APP_JS:
            body = APP_JS.split(opener, 1)[1]
            body = opener.strip() + body.split("\n  }\n", 1)[0] + "\n  }"
            return body
    raise AssertionError(f"{name}() not found in app.js")


def _has(name: str) -> bool:
    return (
        f"  function {name}(" in APP_JS or f"  async function {name}(" in APP_JS
    )


def _run_js(script: str) -> dict:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed")
    proc = subprocess.run(
        [node, "-e", script], capture_output=True, text=True, check=False
    )
    if proc.returncode != 0:
        raise AssertionError(f"node failed:\n{proc.stderr}")
    return json.loads(proc.stdout.strip().splitlines()[-1])


# A stub DOM recording what the page was actually told to display. Only the
# handful of APIs these functions touch are provided; anything else throwing
# is a signal the harness drifted from the code, not a thing to paper over.
HARNESS = r"""
var shown = {};      // element id -> text/html written into it
var hidden = {};     // element id -> is the element hidden
var reloads = [];    // which reload paths ran (a "the write landed" signal)
var confirmed = true;

function mkEl(id) {
  var el = {
    id: id, _html: "", _text: "",
    dataset: {},
    classList: {
      add: function (c) { if (c === "hidden") hidden[id] = true; },
      remove: function (c) { if (c === "hidden") hidden[id] = false; },
      toggle: function (c, on) { if (c === "hidden") hidden[id] = !!on; },
      contains: function () { return false; }
    },
    setAttribute: function (name, value) {
      attrs[id] = attrs[id] || {};
      attrs[id][name] = String(value);
    },
    appendChild: function () {},
    addEventListener: function () {}, querySelectorAll: function () { return []; },
    forEach: function () {},
    // The advisory host is created on demand and spliced in before the
    // error paragraph, so the stub has to model that much of the tree.
    insertBefore: function (node) { node.parentNode = el; return node; }
  };
  el.parentNode = { insertBefore: function (node) { node.parentNode = el; return node; } };
  Object.defineProperty(el, "innerHTML", {
    get: function () { return el._html; },
    set: function (v) { el._html = v; shown[id] = v; }
  });
  Object.defineProperty(el, "textContent", {
    get: function () { return el._text; },
    set: function (v) { el._text = String(v); shown[id] = String(v); }
  });
  return el;
}

var ELS = {};
var attrs = {};
function $(sel) { if (!ELS[sel]) ELS[sel] = mkEl(sel); return ELS[sel]; }
var document = {
  querySelector: $,
  querySelectorAll: function () { return []; },
  getElementById: function (id) { return $("#" + id); },
  createElement: function (tag) {
    var e = mkEl("<" + tag + ">");
    e.tagName = tag;
    // An element created here is anonymous until the code names it; once
    // it has an id, what is written into it must be observable under that
    // id or the advisory would look absent to these tests.
    Object.defineProperty(e, "id", {
      get: function () { return e._id || ""; },
      set: function (v) { e._id = v; ELS["#" + v] = e; }
    });
    return e;
  },
  body: { dataset: {} }
};
var window = {};
async function requestConfirmation() { return confirmed; }

function escapeHtml(value) {
  return String(value == null ? "" : value)
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
}
function friendlyError(e) { return String((e && e.message) || e); }
function ontologyLabelKo(v) { return String(v || ""); }
function showResult(el, html, isError) {
  el.innerHTML = html;
  shown[el.id + ":isError"] = !!isError;
}
function statusBadge(s) { return "<span class='badge st-" + s + "'>" + s + "</span>"; }
function errorKindBadge(k) { return "<span class='badge'>" + String(k || "error").toUpperCase() + "</span>"; }
function fmtTs(t) { return String(t || ""); }
function fmtRelative(t) { return String(t || ""); }
function timeHtml(t) { return "<time datetime='" + t + "' title='" + fmtTs(t) + "'>" + fmtRelative(t) + "</time>"; }
function showTableLoading(tb) { tb.innerHTML = "<tr><td class='muted'>불러오는 중…</td></tr>"; }
function totalsSummary(t) {
  t = t || {};
  return "개념 +" + (t.nodes_new || 0) + "/~" + (t.nodes_merged || 0) +
         " · 관계 +" + (t.edges_new || 0) + "/~" + (t.edges_merged || 0);
}
function copyText() { return Promise.resolve(); }
function flashButton() {}
function renderCompetencyReceipt() {}
function loadEntityPanel() { reloads.push("entity"); }
function loadProposals() { reloads.push("proposals"); }
async function loadMergeCandidates() { reloads.push("merge"); }
function renderJobs() {}
function renderStatusRun() {}
function updateChatJob() {}
function reconcileChatJobs() {}
var prevJobStatuses = {};
var PACK_FAILURE_KO = {
  "manifest invalid": "팩 매니페스트가 유효하지 않습니다.",
  "manifest is not an object": "팩 매니페스트 형식이 유효하지 않습니다.",
  "kg.sqlite is not a database": "팩 데이터베이스를 읽을 수 없습니다."
};
var actPending = false;
var selectedJobId = null;
function renderJobDetail() {}
"""


# Load the shipped browser utilities rather than stubbing the normalizer;
# otherwise the page could still emit `[object Object]` while tests passed.
# Screen-specific functions remain lifted verbatim from the app closure.
SHARED = ("termErrorText", "retryHint",
          "shortMachineValue", "copyableMachineValueHtml",
          "packFailureCopy", "renderUnusablePacks")


def _harness(*functions: str, extra: str = "") -> str:
    # A shared helper that does not exist yet is simply absent here, so these
    # tests still *run* against unfixed code and fail on what they assert
    # rather than erroring in the harness. The functions named by the caller
    # are required, and a missing one is a hard error.
    parts = [_extract(f) for f in SHARED if f not in functions and _has(f)]
    parts += [_extract(f) for f in functions]
    utilities = (
        "require('node:vm').runInNewContext("
        + json.dumps(UI_UTILS_JS, ensure_ascii=False)
        + ", window);\nvar uiUtils = window.ontologylabUiUtils;\n"
    )
    return HARNESS + utilities + extra + "\n" + "\n".join(parts)


def _emit(expr: str) -> str:
    """Print the observation after the async call settles.

    A microtask drain, not a timer: the stubs resolve immediately, so
    queueing behind them is deterministic. `setTimeout` here would be a
    sleep pretending to be a wait.
    """
    return (
        "\n.then(function(){ console.log(JSON.stringify("
        + expr
        + ")); }, function(e){ console.error(e); process.exit(1); });"
    )


def _send_stub(body: dict, status: int = 200, retry_after: str | None = None) -> str:
    """`apiSend` as the server would answer it — body returned, not thrown."""
    return (
        "var SENT = [];\n"
        "async function apiSend(path, payload, method) {\n"
        "  SENT.push(path);\n"
        f"  return {json.dumps(body)};\n"
        "}\n"
        f"var RES_STATUS = {status};\n"
        f"var RES_RETRY = {json.dumps(retry_after)};\n"
    )


def _api_stub(payload: dict) -> str:
    return "async function api(path) { return " + json.dumps(payload) + "; }\n"


BUSY = {
    "ok": False,
    "error_kind": "busy",
    "detail": (
        "The knowledge base is busy — an extraction job is writing to it. "
        "Try again in a moment."
    ),
}


# --------------------------------------------------------------------------
# BASELINE — what must not regress
# --------------------------------------------------------------------------


def test_a_successful_extraction_still_reports_success() -> None:
    """The success path is the thing the honesty fix must not trade away."""
    script = _harness("applyJobs") + (
        "\nprevJobStatuses['j1'] = 'running';"
        "\napplyJobs([{job_id: 'j1', kind: 'extract', status: 'complete',"
        " totals: {nodes_new: 4}}]);"
        "\nconsole.log(JSON.stringify({shown: shown, reloads: reloads}));"
    )
    out = _run_js("(function(){" + script + "})()")

    assert "추출 완료!" in out["shown"]["#extract-result"]
    assert "proposals" in out["reloads"], "the review queue must refresh"


@pytest.mark.parametrize(
    ("fn", "args", "reload_signal"),
    [
        ("invalidateEdge", "'e1', 'n1'", "entity"),
        ("mergeAct", "'c1', 't1', 's1'", "merge"),
        ("mergeDismiss", "'c1'", "merge"),
    ],
)
def test_an_accepted_write_still_reloads(fn: str, args: str, reload_signal: str) -> None:
    """A normal `{ok:true}` write reloads the view it changed."""
    script = (
        _harness(fn, extra=_send_stub({"ok": True}))
        + f"\n{fn}({args})"
        + _emit("{reloads: reloads, shown: shown, hidden: hidden}")
    )
    out = _run_js(script)

    assert reload_signal in out["reloads"]


def test_the_term_error_normalizer_keeps_its_existing_behaviour() -> None:
    """`termErrorText` is promoted to shared use, so its own contract — the
    `{field, detail}` object form its caller depends on — is pinned first."""
    script = _harness("termErrorText") + (
        "\nconsole.log(JSON.stringify({"
        "obj: termErrorText({detail: {field: 'name', detail: '너무 길어요'}}),"
        " arr: termErrorText({detail: [{loc: ['body', 'name'], msg: 'bad'}]}),"
        " str: termErrorText({detail: '평범한 문자열'}),"
        " none: termErrorText({})}));"
    )
    out = _run_js("(function(){" + script + "})()")

    assert out["obj"] == "name: 너무 길어요"
    assert out["arr"] == "name: bad"
    assert out["str"] == "평범한 문자열"
    assert out["none"].strip() and "[object Object]" not in out["none"]


@pytest.mark.parametrize(
    ("result", "expected_id"),
    [
        (
            {"manifest": {"pack_id": "chat-pack-20260905-223532"}},
            "chat-pack-20260905-223532",
        ),
        ({"pack_id": "stored-pack"}, "stored-pack"),
        (
            {"manifest": {"pack_id": "current-pack"}, "pack_id": "stale-pack"},
            "current-pack",
        ),
        (
            {"manifest": {"pack_id": "<pack & \"new\" 'id'>"}},
            "&lt;pack &amp; &quot;new&quot; &#39;id&#39;&gt;",
        ),
        (
            {"pack_id": "<pack & \"old\" 'id'>"},
            "&lt;pack &amp; &quot;old&quot; &#39;id&#39;&gt;",
        ),
        ({"manifest": {}, "pack_id": "stored-pack"}, "stored-pack"),
        ({"manifest": None, "pack_id": "stored-pack"}, "stored-pack"),
    ],
    ids=["nested", "flat", "nested-wins", "nested-escaped", "flat-escaped",
         "empty-manifest", "null-manifest"],
)
def test_chat_pack_answer_displays_pack_id_as_escaped_text(result, expected_id) -> None:
    """Run both the shipped renderer and escaper, including saved responses."""
    response = {"reading": "팩 요청 결과", "result": {"kind": "pack", **result}}
    script = _extract("escapeHtml") + "\n" + _extract("chatAnswer") + (
        "\nconsole.log(JSON.stringify({html: chatAnswer("
        + json.dumps(response, ensure_ascii=False)
        + ")}));"
    )
    html = _run_js(script)["html"]

    assert f"<code>{expected_id}</code>" in html
    assert html.startswith("<p>팩 요청 결과</p>")
    assert "data-goto='packs'" in html


# --------------------------------------------------------------------------
# F6 — a refused write must not read as a completed one
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("fn", "args", "err_id", "reload_signal"),
    [
        ("invalidateEdge", "'e1', 'n1'", "#entity-panel-error", "entity"),
        ("mergeAct", "'c1', 't1', 's1'", "#merge-error", "merge"),
        ("mergeDismiss", "'c1'", "#merge-error", "merge"),
    ],
)
def test_a_busy_refusal_is_surfaced_and_not_reloaded_as_success(
    fn: str, args: str, err_id: str, reload_signal: str
) -> None:
    """The core defect.

    `{ok: false}` is not `undefined`, so the `res.ok === undefined` guard
    never fires: the code falls through to the reload and the operator sees
    the list refresh, which is what a successful write looks like. Nothing
    on screen distinguishes "invalidated" from "refused".
    """
    script = (
        _harness(fn, extra=_send_stub(BUSY, status=503, retry_after="5"))
        + f"\n{fn}({args})"
        + _emit("{reloads: reloads, shown: shown, hidden: hidden}")
    )
    out = _run_js(script)

    assert out["hidden"].get(err_id) is False, "the refusal must be visible"
    assert out["shown"].get(err_id), "the refusal must say something"
    assert reload_signal not in out["reloads"], (
        "a refused write must not refresh the view as though it landed"
    )


# --------------------------------------------------------------------------
# F5 — a validation error names the field, never `[object Object]`
# --------------------------------------------------------------------------


VALIDATION_422 = {
    "detail": [
        {"type": "string_pattern_mismatch", "loc": ["body", "name"],
         "msg": "String should match pattern '^[A-Za-z0-9_.-]+$'"}
    ]
}


def test_a_422_array_detail_renders_the_field_and_message() -> None:
    """FastAPI answers a rejected body with a *list* of errors. Interpolating
    that list into a string yields `[object Object]` — a message that names
    neither the field nor the rule, on the one screen where the operator
    could have fixed it.

    This runs the shared normalizer itself; the test below pins that the
    call sites actually route through it.
    """
    script = _harness("termErrorText") + (
        "\nconsole.log(JSON.stringify({out: termErrorText("
        + json.dumps(VALIDATION_422)
        + ")}));"
    )
    out = _run_js("(function(){" + script + "})()")["out"]

    assert "[object Object]" not in out
    assert "name" in out, "the rejected field must be named"
    assert "pattern" in out, "the rule that rejected it must be shown"


@pytest.mark.parametrize(
    ("body", "message"),
    [
        ({"detail": {"field": "name", "detail": "너무 길어요"}}, "name: 너무 길어요"),
        ({"detail": [{"loc": ["body", "name"], "msg": "bad"}]}, "name: bad"),
        ({"detail": "거절된 요청"}, "거절된 요청"),
        ({"error": "검증 실패"}, "검증 실패"),
        (None, "Unprocessable Entity"),
    ],
)
def test_api_failure_preserves_readable_details_and_metadata(body, message) -> None:
    """Exercise the HTTP caller, not a textual assertion about its helpers."""
    script = _harness("api", "retryAfterSeconds", extra=(
        "var BODY = " + json.dumps(body, ensure_ascii=False) + ";\n"
        "async function fetch() { return {ok: false, status: 422,"
        " statusText: 'Unprocessable Entity', json: async function() { return BODY; },"
        " headers: {get: function() { return '5'; }}}; }\n"
    )) + (
        "api('/api/test').then(function() { throw new Error('failure accepted'); },"
        " function(e) { console.log(JSON.stringify({message: e.message,"
        " status: e.httpStatus, retry: e.retryAfter, sameBody: e.responseBody === BODY})); });"
    )
    out = _run_js(script)

    assert out == {"message": message, "status": 422, "retry": 5, "sameBody": True}


def test_error_surface_classification_keeps_validation_details() -> None:
    script = _harness("classifyError", "sanitizeErrorDetail") + (
        "\nconsole.log(JSON.stringify(classifyError({httpStatus: 422,"
        " responseBody: {detail: [{loc: ['body', 'name'], msg: 'bad'}]}})));"
    )
    out = _run_js(script)

    assert out["variant"] == "request"
    assert out["detail"] == "HTTP 422 · name: bad"


@pytest.mark.parametrize(
    "detail",
    [
        [{"loc": ["body", "name"], "msg": "bad"}],
        "a plain string detail",
        None,
    ],
    ids=["array", "string", "null"],
)
def test_every_detail_shape_renders_as_text(detail) -> None:
    """The three shapes the server actually produces. None may reach the
    screen as `[object Object]`, and none may render as empty."""
    script = _harness("termErrorText") + (
        "\nvar out = termErrorText({detail: " + json.dumps(detail) + "});"
        "\nconsole.log(JSON.stringify({out: out}));"
    )
    out = _run_js("(function(){" + script + "})()")

    assert "[object Object]" not in out["out"]
    assert out["out"].strip()


# --------------------------------------------------------------------------
# F1-UI — a partial failure is a failure that still produced work
# --------------------------------------------------------------------------


def test_a_partial_extraction_failure_says_results_survived() -> None:
    """A chunk-level engine failure is `failed`, but the chunks that
    succeeded still wrote real proposals. Reporting a flat failure and
    stopping there tells the operator to discard work that exists — the same
    lie as the old success banner, pointed the other way."""
    script = _harness("applyJobs") + (
        "\nprevJobStatuses['j2'] = 'running';"
        "\napplyJobs([{job_id: 'j2', kind: 'extract', status: 'failed',"
        " error: 'extraction engine failed',"
        " totals: {nodes_new: 7, edges_new: 3}}]);"
        "\nconsole.log(JSON.stringify({shown: shown, reloads: reloads}));"
    )
    out = _run_js("(function(){" + script + "})()")
    box = out["shown"]["#extract-result"]

    assert "실패" in box or "failed" in box, "it must still read as a failure"
    assert "7" in box, "the proposals that survived must be counted"
    assert "검토" in box or "재시도" in box, "a way forward must be offered"


def test_a_total_extraction_failure_does_not_invent_results() -> None:
    """The mirror case: zero totals must not be dressed up as partial work."""
    script = _harness("applyJobs") + (
        "\nprevJobStatuses['j3'] = 'running';"
        "\napplyJobs([{job_id: 'j3', kind: 'extract', status: 'failed',"
        " error: 'extraction engine failed', totals: {}}]);"
        "\nconsole.log(JSON.stringify({shown: shown}));"
    )
    out = _run_js("(function(){" + script + "})()")
    box = out["shown"]["#extract-result"]

    assert "실패" in box or "failed" in box
    assert "검토 →" not in box, "there is nothing to review"


def test_the_engine_failure_string_is_the_one_the_server_sends() -> None:
    """The redacted summary is a fixed string; raw engine text stays on disk."""
    from ontologylab.extractor import ENGINE_FAILURE_SUMMARY

    assert ENGINE_FAILURE_SUMMARY == "extraction engine failed"


# --------------------------------------------------------------------------
# F7-UI — an unusable pack directory is an advisory, not a pack
# --------------------------------------------------------------------------


PACKS_PAYLOAD = {
    "packs": [
        {"pack_id": "good-pack", "created_ts": 1,
         "counts": {"documents": 2, "nodes_verified": 5, "edges_verified": 3},
         "content_hash": "abc123def456789", "search_tier": "lexical"}
    ],
    "count": 1,
    "unusable": [
        {"pack_dir": "pack-broken-manifest", "reason": "manifest is not an object"},
        {"pack_dir": "pack-bad-sqlite", "reason": "kg.sqlite is not a database"},
    ],
    "competency": {},
}


def test_an_unusable_directory_is_never_drawn_as_a_pack_row() -> None:
    """A directory that failed validation has no counts, no hash and no
    serve command. Rendering it as a row produces a pack whose every column
    is a zero or a dash — indistinguishable from an empty but working pack,
    and offering a `.mcpb` button for something that cannot be served."""
    script = (
        _harness("loadPacks", "populateDiffSelects", extra=_api_stub(PACKS_PAYLOAD))
        + "\nloadPacks()"
        + _emit("{shown: shown, hidden: hidden}")
    )
    out = _run_js(script)
    rows = out["shown"]["#packs-body"]

    assert "good-pack" in rows
    for bad in ("pack-broken-manifest", "pack-bad-sqlite"):
        assert bad not in rows, f"{bad} was drawn as a pack row"


def test_an_unusable_directory_is_reported_somewhere_the_operator_looks() -> None:
    """Silently dropping it is the other failure: the operator built a pack,
    sees it missing, and has no way to learn the directory was rejected."""
    script = (
        _harness("loadPacks", "populateDiffSelects", extra=_api_stub(PACKS_PAYLOAD))
        + "\nloadPacks()"
        + _emit("{shown: shown, hidden: hidden}")
    )
    out = _run_js(script)
    surface = " ".join(
        str(v) for k, v in out["shown"].items() if k != "#packs-body"
    )

    assert "pack-broken-manifest" in surface, "the rejected directory is not named"
    assert "manifest is not an object" in surface, "the reason is not given"


def test_an_unusable_directory_is_never_a_diff_option() -> None:
    """A blank or unusable option in the compare dropdown yields a diff
    request against a pack that cannot be opened."""
    script = (
        _harness("populateDiffSelects")
        + "\npopulateDiffSelects("
        + json.dumps(PACKS_PAYLOAD["packs"])
        + ");\nconsole.log(JSON.stringify({a: shown['#diff-pack-a'] || '',"
        " b: shown['#diff-pack-b'] || ''}));"
    )
    out = _run_js("(function(){" + script + "})()")

    for sel in (out["a"], out["b"]):
        assert "pack-broken-manifest" not in sel
        assert "pack-bad-sqlite" not in sel
        assert "<option value=''>" not in sel, "a blank option diffs nothing"


MCP_PAYLOAD = {
    "packs_dir": "/tmp/packs",
    "packs": [
        {"pack_id": "good-pack", "created_ts": 1,
         "counts": {"documents": 2, "nodes_verified": 5, "edges_verified": 3},
         "serve_command": "ontologylab mcp serve good-pack",
         "stdio_config": {"command": "ontologylab"}}
    ],
    "count": 1,
    "unusable": [
        {"pack_dir": "pack-bad-sqlite", "reason": "kg.sqlite is not a database"}
    ],
}


def test_the_connect_screen_does_not_offer_a_command_for_a_broken_pack() -> None:
    """The MCP screen's whole payload is a command to paste into a client.
    A card for an unusable directory hands over a command that fails on the
    other side of the copy, where this app cannot explain itself."""
    script = (
        _harness("loadMcp", extra=_api_stub(MCP_PAYLOAD))
        + "\nloadMcp()"
        + _emit("{shown: shown, hidden: hidden}")
    )
    out = _run_js(script)
    surface = " ".join(str(v) for v in out["shown"].values())

    assert "pack-bad-sqlite" in surface, "the rejected directory must be named"
    assert "kg.sqlite is not a database" in surface, "with its reason"
    assert "mcp serve pack-bad-sqlite" not in surface, (
        "a broken pack must not be given a serve command"
    )


def test_an_empty_unusable_list_adds_no_advisory() -> None:
    """`unusable` is always present and usually empty. A permanently visible
    'some packs were rejected' box trains the operator to ignore it."""
    clean = dict(PACKS_PAYLOAD, unusable=[])
    script = (
        _harness("loadPacks", "populateDiffSelects", extra=_api_stub(clean))
        + "\nloadPacks()"
        + _emit("{shown: shown, hidden: hidden}")
    )
    out = _run_js(script)
    surface = " ".join(
        str(v) for k, v in out["shown"].items() if k != "#packs-body"
    )

    assert "사용할 수 없" not in surface and "unusable" not in surface.lower()
