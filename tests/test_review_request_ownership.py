"""Execute shipped review loaders with deliberately ordered API completions."""

from __future__ import annotations

import json
import re

import pytest

from tests.test_ui_failure_honesty import APP_JS, _harness, _run_js

DRIVER = r"""
var makeElement = mkEl;
mkEl = function (id) {
  var el = makeElement(id), proxy, parts = {};
  el.children = [];
  el.appendChild = function (child) { child.parentNode = proxy; el.children.push(child); return child; };
  el.remove = function () {
    if (el.parentNode && el.parentNode.children) {
      el.parentNode.children = el.parentNode.children.filter(function (child) { return child !== proxy; });
    }
    el.parentNode = null;
  };
  el.querySelector = function (selector) { return parts[selector] || (parts[selector] = mkEl(selector)); };
  el.scrollIntoView = function () {};
  proxy = new Proxy(el, {set: function (target, key, value) {
    if (key === "innerHTML" || key === "textContent") {
      target.children.forEach(function (child) { child.parentNode = null; });
      target.children = [];
    }
    target[key] = value;
    return true;
  }});
  return proxy;
};
document.createTextNode = function (value) { var el = mkEl("text"); el.textContent = value; return el; };
var evidenceId = null, bulkUpdates = 0;
function renderEvidence(item) { evidenceId = item && item.id; }
function updateBulkButtons() { bulkUpdates++; }
function act() { throw new Error("unexpected review decision"); }
var Q = "/api/proposals?limit=50&order=confidence";
var TRI = "/api/review/triage", CAL = "/api/review/calibration";
var responses = {}, unexpected = [];
var requestEvents = new (require("node:events").EventEmitter)();
function queue(path, values) { responses[path] = values.slice(); }
async function api(path) {
  requestEvents.emit(path);
  if (!responses[path] || !responses[path].length) {
    unexpected.push(path);
    throw new Error("unplanned request: " + path);
  }
  var value = responses[path].shift();
  if (value instanceof Error) throw value;
  return value;
}
function deferred() {
  var resolve, reject;
  var promise = new Promise(function (yes, no) { resolve = yes; reject = no; });
  return {promise: promise, resolve: resolve, reject: reject};
}
function reached(path) {
  return new Promise(function (resolve, reject) {
    function onRequest() {
      clearTimeout(deadline);
      resolve();
    }
    var deadline = setTimeout(function () {
      requestEvents.removeListener(path, onRequest);
      reject(new Error("request not reached: " + path));
    }, 1000);
    requestEvents.once(path, onRequest);
  });
}
function page(prefix, n, total, cursor) {
  return {items: Array.from({length: n}, function (_, i) {
    return {id: prefix + i, kind: i < 8 ? "node" : "edge", name: prefix + i,
      confidence: 0.5, critic_score: 0.9};
  }), counts: {nodes_proposed: Math.min(total, 8), edges_proposed: Math.max(0, total - 8)},
  has_more: !!cursor, next_cursor: cursor || null};
}
function advice(value) {
  return {available: true, threshold: value, curve: {boundaries: [0], values: [value]}};
}
function configure(pages, triage, calibration) {
  queue(Q, pages);
  queue(TRI, triage || [{available: false}]);
  queue(CAL, calibration || [{available: false}]);
}
function snapshot() {
  var children = $("#proposals-body").children;
  return {rows: reviewRows.map(function (row) { return row.id; }),
    dom: children.map(function (tr) { var id = tr.innerHTML.match(/data-id='([^']+)'/); return id && id[1]; }).filter(Boolean),
    progress: $("#review-progress").textContent.match(/\d+/g).map(Number),
    counts: $("#counts-box").innerHTML, badge: $("#review-badge").textContent,
    cursor: reviewCursor, evidence: evidenceId, next: reviewNextCursor, more: reviewHasMore,
    loading: reviewLoadingMore, moreDisabled: $("#review-more-btn").disabled,
    spinner: children.some(function (tr) { return tr.id === "review-loading-row"; }),
    checked: !!$("#review-check-all").checked, bulkUpdates: bulkUpdates,
    emptyHidden: hidden["#review-empty"], errorHidden: hidden["#review-error"],
    error: $("#review-error").textContent, triage: reviewTriage, calibration: reviewCalibration,
    unexpected: unexpected.slice()};
}
"""


def _run(script: str) -> dict:
    state = "\n".join(re.findall(r"^  var review\w+ = [^\n;]+;", APP_JS, re.M))
    body = _harness(
        "loadProposals", "reviewLoadMore", "loadProposalAdvisories", "appendReviewRow",
        "updateReviewProgress", "focusRow", "renderCounts", "updateReviewBadge",
        "itemLabel", "itemLabelHtml", "kindKo", "calibratedConfidence", "safeToReviewLast",
        extra=state + "\n" + DRIVER,
    ) + script
    return _run_js('(async function(){"use strict";\n' + body +
                   '\n})().catch(function(e){console.error(e);process.exit(1);});')


def test_overlapping_refreshes_keep_fifteen_rows_not_thirty() -> None:
    out = _run("""
var gate = deferred();
configure([page("sample-", 15, 15), page("sample-", 15, 15)], [gate.promise, advice(0.8)], [advice(0.8), advice(0.1)]);
var requestArrived = reached(TRI);
var old = loadProposals();
await requestArrived;
await loadProposals();
gate.resolve(advice(0.1));
await old;
console.log(JSON.stringify(snapshot()));
""")
    expected = [f"sample-{i}" for i in range(15)]
    assert out["rows"] == out["dom"] == expected
    assert out["progress"] == [15, 15]
    assert out["badge"] == "15"
    assert out["unexpected"] == []


@pytest.mark.parametrize("stage", ["query", "triage", "calibration"])
@pytest.mark.parametrize("fail", [False, True])
def test_late_refresh_result_or_failure_cannot_replace_current_state(stage: str, fail: bool) -> None:
    script = "var stage = " + json.dumps(stage) + "; var fail = " + json.dumps(fail) + ";\n"
    out = _run(script + """
var gate = deferred(), oldPage = page("old-", 1, 11, "old-cursor");
configure([stage === "query" ? gate.promise : oldPage, page("new-", 3, 4, "new-cursor")],
  stage === "query" ? [advice(0.8), advice(0.1)] : [stage === "triage" ? gate.promise : advice(0.1), advice(0.8)],
  stage === "calibration" ? [gate.promise, advice(0.8)] : [advice(0.8), advice(0.1)]);
var requestArrived = reached(stage === "query" ? Q : stage === "triage" ? TRI : CAL);
var old = loadProposals();
await requestArrived;
await loadProposals(2);
$("#review-check-all").checked = true;
var before = snapshot();
if (fail) gate.reject(new Error("old failure")); else gate.resolve(stage === "query" ? oldPage : advice(0.1));
await old;
console.log(JSON.stringify({before: before, after: snapshot()}));
""")
    assert out["before"]["dom"] == ["new-0", "new-1", "new-2"]
    assert out["before"]["cursor"] == 2
    assert out["before"]["next"] == "new-cursor"
    assert out["before"]["triage"]["threshold"] == 0.8
    assert out["before"]["calibration"]["values"] == [0.8]
    assert out["after"] == out["before"]
    assert out["after"]["unexpected"] == []


@pytest.mark.parametrize("fail", [False, True])
def test_refresh_supersedes_load_more_without_releasing_new_page(fail: bool) -> None:
    out = _run("var fail = " + json.dumps(fail) + ";\n" + """
configure([page("old-", 1, 2, "old-page"), page("new-", 1, 3, "new-page")], [advice(0.1), advice(0.8)], [advice(0.1), advice(0.8)]);
await loadProposals();
var oldGate = deferred(), newGate = deferred();
queue(Q + "&cursor=old-page", [oldGate.promise]);
queue(Q + "&cursor=new-page", [newGate.promise]);
var oldMore = reviewLoadMore();
await loadProposals();
var newMore = reviewLoadMore();
var before = snapshot();
if (fail) oldGate.reject(new Error("stale page failure")); else oldGate.resolve(page("stale-", 1, 20));
await oldMore;
var after = snapshot();
newGate.resolve(page("next-", 1, 3));
await newMore;
console.log(JSON.stringify({before: before, after: after, final: snapshot()}));
""")
    assert out["before"]["spinner"] is True
    assert out["before"]["loading"] is True
    assert out["after"] == out["before"]
    assert out["final"]["rows"] == out["final"]["dom"] == ["new-0", "next-0"]
    assert out["final"]["progress"] == [2, 3]
    assert out["final"]["loading"] is out["final"]["spinner"] is False
    assert out["final"]["unexpected"] == []


def test_normal_pagination_and_current_page_error_preserve_queue() -> None:
    out = _run("""
configure([page("first-", 2, 4, "page &2")]);
await loadProposals(1);
queue(Q + "&cursor=page%20%262", [new Error("current page failure"), page("last-", 2, 4)]);
await reviewLoadMore();
var failed = snapshot();
await reviewLoadMore();
console.log(JSON.stringify({failed: failed, final: snapshot()}));
""")
    assert out["failed"]["rows"] == out["failed"]["dom"] == ["first-0", "first-1"]
    assert out["failed"]["errorHidden"] is False
    assert out["failed"]["error"] == "current page failure"
    assert out["failed"]["next"] == "page &2"
    assert out["failed"]["loading"] is out["failed"]["spinner"] is False
    assert out["final"]["rows"] == out["final"]["dom"] == ["first-0", "first-1", "last-0", "last-1"]
    assert out["final"]["progress"] == [4, 4]
    assert out["final"]["cursor"] == 1
    assert out["final"]["next"] is None
    assert out["final"]["unexpected"] == []


@pytest.mark.parametrize("mode", ["empty", "query-error", "advisory-error", "unavailable"])
def test_empty_error_and_advisory_fail_open_controls(mode: str) -> None:
    out = _run("var mode = " + json.dumps(mode) + ";\n" + """
configure([mode === "query-error" ? new Error("current query failure") : page("row-", mode === "empty" ? 0 : 1, mode === "empty" ? 0 : 1)],
  [mode === "advisory-error" ? new Error("triage failure") : {available: false}],
  [mode === "advisory-error" ? new Error("calibration failure") : {available: false}]);
await loadProposals();
console.log(JSON.stringify(snapshot()));
""")
    expected = [] if mode in ("empty", "query-error") else ["row-0"]
    assert out["rows"] == out["dom"] == expected
    assert out["progress"] == [len(expected), len(expected)]
    assert out["emptyHidden"] is (mode != "empty")
    assert out["errorHidden"] is (mode != "query-error")
    assert out["triage"] is out["calibration"] is None
    assert out["unexpected"] == []
