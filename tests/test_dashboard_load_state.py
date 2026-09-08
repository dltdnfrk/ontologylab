"""Machine-readable dashboard loading and settled-state contracts."""

from __future__ import annotations

import re

from tests.test_ui_failure_honesty import APP_JS, _harness, _run_js


def test_tab_loader_exposes_loading_then_settled_state() -> None:
    script = _harness(
        "maybeLoadTab",
        extra="""
var finishTabLoad;
var tabLoaders = {
  artifacts: function () {
    return new Promise(function (resolve) { finishTabLoad = resolve; });
  }
};
function loadHome() { return Promise.resolve(); }
""",
    ) + """
var pending = maybeLoadTab("artifacts");
var panel = $('.tab-panel[data-tab-panel="artifacts"]');
var during = {
  state: panel.dataset.loadState,
  busy: (attrs['.tab-panel[data-tab-panel="artifacts"]'] || {})["aria-busy"]
};
Promise.resolve().then(function () {
  finishTabLoad();
  return pending;
}).then(function () {
  console.log(JSON.stringify({
    during: during,
    after: {
      state: panel.dataset.loadState,
      busy: (attrs['.tab-panel[data-tab-panel="artifacts"]'] || {})["aria-busy"]
    }
  }));
});
"""

    result = _run_js("(function(){" + script + "})()")

    assert result == {
        "during": {"state": "loading", "busy": "true"},
        "after": {"state": "settled", "busy": "false"},
    }


def test_artifacts_show_loading_then_an_empty_terminal_state() -> None:
    script = _harness(
        "loadArtifacts",
        extra="""
var finishArtifacts;
async function api(path) {
  if (path === "/api/artifacts") {
    return new Promise(function (resolve) { finishArtifacts = resolve; });
  }
  return {packs: []};
}
""",
    ) + """
var pending = loadArtifacts();
var during = {
  documents: shown["#artifacts-docs"],
  releases: shown["#artifacts-releases"]
};
finishArtifacts({artifacts: []});
Promise.resolve(pending).then(function () {
  console.log(JSON.stringify({
    during: during,
    after: {
      emptyHidden: hidden["#artifacts-empty"],
      documents: shown["#artifacts-docs"],
      releases: shown["#artifacts-releases"]
    }
  }));
});
"""

    result = _run_js("(function(){" + script + "})()")

    assert "불러오는 중" in result["during"]["documents"]
    assert "불러오는 중" in result["during"]["releases"]
    assert result["after"] == {
        "emptyHidden": False,
        "documents": "",
        "releases": "",
    }


def test_review_advisory_state_is_declared_under_strict_mode() -> None:
    declarations = "\n".join(
        re.findall(
            r"var review(?:Triage|Calibration)\s*=\s*null;",
            APP_JS,
        )
    )
    script = '"use strict";\n' + _harness(
        "loadProposalAdvisories",
        extra=declarations + """
async function api(path) {
  if (path === "/api/review/triage") {
    return {available: true, threshold: 0.8};
  }
  return {available: true, curve: {boundaries: [], values: [0.5]}};
}
""",
    ) + """
loadProposalAdvisories().then(function (advisories) {
  console.log(JSON.stringify({
    triage: advisories.triage,
    calibration: advisories.calibration,
    originalTriage: reviewTriage,
    originalCalibration: reviewCalibration
  }));
});
"""

    result = _run_js("(function(){" + script + "})()")

    assert result["triage"] == {"available": True, "threshold": 0.8}
    assert result["calibration"] == {"boundaries": [], "values": [0.5]}
    assert result["originalTriage"] is result["originalCalibration"] is None
