from __future__ import annotations

import json
import re
import shutil
import subprocess

import pytest

from ontologylab import web_assets


APP = web_assets.read_asset_text("app.js")
HTML = web_assets.read_asset_text("index.html")
CSS = web_assets.read_asset_text("style.css")


def _function(name: str) -> str:
    for opener in (f"  async function {name}(", f"  function {name}("):
        if opener in APP:
            tail = APP.split(opener, 1)[1]
            return opener.strip() + tail.split("\n  }\n", 1)[0] + "\n  }"
    raise AssertionError(f"missing {name}()")


def test_lifecycle_selection_and_destructive_actions_use_the_shared_dialog() -> None:
    detail = _function("loadTermDetail")
    assert 'lifecycle.value = payload.term.lifecycle' in detail
    assert '<dialog id="confirm-dialog"' in HTML
    assert 'aria-labelledby="confirm-dialog-title"' in HTML
    assert "function requestConfirmation(" in APP
    assert 'reasonRequired: true' in APP

    source_handler = APP.split('$("#sources-body").addEventListener', 1)[1].split(
        "\n  });", 1
    )[0]
    assert "await requestConfirmation(" in source_handler
    assert source_handler.index("await requestConfirmation(") < source_handler.index(
        'method: "DELETE"'
    )
    assert "window.confirm" not in APP
    assert "window.alert" not in APP


def test_typed_error_surface_maps_and_sanitizes_failures_with_retry_states() -> None:
    assert '<template id="error-surface-template">' in HTML
    assert "function classifyError(" in APP
    assert "function renderErrorSurface(" in APP
    classify = _function("classifyError")
    for status in (401, 403, 500, 503):
        assert str(status) in classify
    render = _function("renderErrorSurface")
    assert "copy" in render.lower()
    assert "retry" in render.lower()
    assert "pending" in render.lower()
    assert "Failed to fetch" not in render
    assert "unknown" not in render
    assert "data-error-key" in render


def test_live_chat_trace_is_elapsed_queueable_and_retryable() -> None:
    assert "var chatQueue = []" in APP
    assert "function drainChatQueue(" in APP
    send = _function("sendChat")
    assert "input.disabled" not in send
    assert "send.disabled" not in send
    assert "setInterval" in APP
    assert "live-trace-chips" in APP
    assert "data-chat-retry" in APP
    assert "chatFailureAction" in APP


def test_retry_requires_explicit_recovery_and_preserves_pending_failure_surface() -> None:
    load_jobs = _function("loadJobs")
    assert 'if (!options || options.render !== false) err.classList.add("hidden")' in load_jobs
    execute = _function("executeRetry")
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed")
    script = r"""
let release;
const deferred = new Promise(resolve => { release = resolve; });
const states = [];
const parent = { classList: { add: value => states.push(`parent:${value}`) } };
const surface = {
  parentElement: parent,
  setAttribute: (name, value) => states.push(`${name}:${value}`),
  closest: () => null,
};
const retry = { disabled: false, dataset: {}, textContent: "다시 시도" };
let rendered = null;
function renderErrorSurface(el, error, options) {
  rendered = { el: el === parent, message: error.message, retry: !!options.retry };
}
const pending = executeRetry(surface, retry, () => deferred);
states.push(`pending:${retry.disabled}:${retry.textContent}:${retry.dataset.state}`);
release({ recovered: false, error: new Error("terminal") });
pending.then(result => console.log(JSON.stringify({ states, rendered, result })));
""" + execute
    proc = subprocess.run(
        [node, "-e", script], capture_output=True, text=True, check=False
    )
    assert proc.returncode == 0, proc.stderr
    result = json.loads(proc.stdout.strip())
    assert "pending:true:다시 시도 중…:pending" in result["states"]
    assert result["rendered"] == {"el": True, "message": "terminal", "retry": True}
    assert result["result"] == "failed"


def test_every_destructive_frontend_request_is_confirmed_before_dispatch() -> None:
    named = {
        "undoLastDecision": "/api/proposals/reopen",
        "act": "/api/proposals/",
        "bulkAct": "/api/proposals/",
        "mergeAct": "/api/merge/candidates/",
        "mergeDismiss": "/api/merge/candidates/",
        "invalidateEdge": "/api/edges/",
    }
    for function, endpoint in named.items():
        body = _function(function)
        assert "requestConfirmation(" in body, function
        assert body.index("requestConfirmation(") < body.index(endpoint), function

    for marker in (
        '$("#providers-body").addEventListener',
        '$("#sources-body").addEventListener',
        '$("#annotations-list").addEventListener',
    ):
        block = APP.split(marker, 1)[1].split("\n  });", 1)[0]
        assert "requestConfirmation(" in block, marker
        destructive = min(
            (offset for token in ('method: "DELETE"', '"/decide"')
             if (offset := block.find(token)) >= 0),
            default=-1,
        )
        assert destructive >= 0
        assert block.index("requestConfirmation(") < destructive

    ontology_verify = APP.split('verify.addEventListener("click"', 1)[1].split(
        "\n    });", 1
    )[0]
    assert ontology_verify.index("requestConfirmation(") < ontology_verify.index(
        '"/api/ontology/proposals/verify"'
    )


def test_palette_modal_owns_focus_and_restores_the_invoker() -> None:
    open_body = _function("paletteOpen")
    close_body = _function("paletteClose")
    assert "paletteInvoker" in open_body
    assert "setAppInert(true)" in open_body
    assert "setAppInert(false)" in close_body
    assert "paletteInvoker.focus" in close_body
    assert 'ev.key !== "Tab"' in APP
    assert 'ev.key === "Escape"' in APP


def test_job_identity_palette_and_tab_motion_contracts_are_complete() -> None:
    assert "function formatJobIdentity(" in APP
    jobs = _function("renderJobs")
    assert "jobIdentityHtml" in jobs
    assert "data-copy-job-id" in _function("jobIdentityHtml")
    assert ".slice(0, 12)" not in jobs

    palette_block = APP.split("var PALETTE_TABS = [", 1)[1].split("];", 1)[0]
    assert len(re.findall(r'^\s*\["[^"]+",', palette_block, re.MULTILINE)) == 11
    assert '["artifacts",' in palette_block

    assert "--t-tab: 140ms" in CSS
    assert re.search(r"\.tab-panel\.active\s*\{[^}]*animation:\s*tab-enter", CSS, re.S)
    assert "@keyframes tab-enter" in CSS
    assert not re.search(r"\bmain\s*\{[^}]*transition\s*:\s*all", CSS, re.S)
    reduced = CSS.split("@media (prefers-reduced-motion: reduce)", 1)[1]
    assert ".tab-panel.active" in reduced
    assert "animation: none" in reduced
