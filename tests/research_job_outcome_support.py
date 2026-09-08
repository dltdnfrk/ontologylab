"""Shared Node DOM and shipped-listener drivers for job outcome tests."""

from __future__ import annotations

import json
from html.parser import HTMLParser

from ontologylab import web_assets
from tests.test_ui_failure_honesty import APP_JS, _harness, _run_js


class _HelpTemplate(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: dict[str, dict[str, str | None]] = {}

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        for name in ("error-help", "error-help-toggle"):
            if name in (values.get("class") or "").split():
                self.parts["." + name] = values


def _help_template() -> str:
    parser = _HelpTemplate()
    html = web_assets.read_asset_text("index.html")
    parser.feed(html.split('<template id="error-surface-template">', 1)[1].split("</template>", 1)[0])
    return "var helpTemplateAttrs = " + json.dumps(parser.parts, ensure_ascii=False) + ";\n"


def _declaration(name: str) -> str:
    opener = f"  var {name} = {{"
    return opener.strip() + APP_JS.split(opener, 1)[1].split("\n  };", 1)[0] + "\n};"


def _listener(opener: str) -> str:
    indent = " " * (len(opener) - len(opener.lstrip()))
    return opener.strip() + APP_JS.split(opener, 1)[1].split("\n" + indent + "});", 1)[0] + "\n});"


DOM = r"""
function textOf(html) {
  return String(html).replace(/<[^>]*>/g, "")
    .replace(/&lt;/g, "<").replace(/&gt;/g, ">")
    .replace(/&quot;/g, '"').replace(/&#39;/g, "'").replace(/&amp;/g, "&");
}
function mkEl(id) {
  var classes = new Set();
  var el = {
    id: id, tagName: "div", dataset: {}, attributes: {}, children: [],
    listeners: {}, parts: {}, _html: "", disabled: false,
    classList: {
      add: function (name) { classes.add(name); hidden[id] = classes.has("hidden"); },
      remove: function (name) { classes.delete(name); hidden[id] = classes.has("hidden"); },
      contains: function (name) { return classes.has(name); },
      toggle: function (name, on) {
        if (on) classes.add(name); else classes.delete(name);
        hidden[id] = classes.has("hidden");
      }
    },
    setAttribute: function (name, value) { el.attributes[name] = String(value); },
    appendChild: function (child) { el.children.push(child); return child; },
    addEventListener: function (name, callback) { el.listeners[name] = callback; },
    querySelector: function (selector) { return el.parts[selector] || null; },
    querySelectorAll: function () { return []; }
  };
  Object.defineProperty(el, "innerHTML", {
    get: function () {
      return el._html + el.children.map(function (child) { return child.outerHTML; }).join("");
    },
    set: function (value) { el._html = String(value); el.children = []; }
  });
  Object.defineProperty(el, "textContent", {
    get: function () { return textOf(el.innerHTML); },
    set: function (value) { el.innerHTML = escapeHtml(value); }
  });
  Object.defineProperty(el, "outerHTML", {
    get: function () {
      var attributes = " class='" + Array.from(classes).join(" ") + "'";
      Object.keys(el.dataset).forEach(function (key) {
        attributes += " data-" + key.replace(/[A-Z]/g, function (letter) {
          return "-" + letter.toLowerCase();
        }) + "='" + escapeHtml(el.dataset[key]) + "'";
      });
      return "<" + el.tagName + attributes + ">" + el.innerHTML + "</" + el.tagName + ">";
    }
  });
  return el;
}
$("#error-surface-template").content = {firstElementChild: {
  cloneNode: function () {
    var surface = mkEl("error-surface");
    [".error-surface-message", ".error-help", ".error-help-toggle", ".error-detail pre", ".error-copy", ".error-retry"]
      .forEach(function (selector) {
        var part = mkEl(selector);
        if (selector === ".error-help" || selector === ".error-help-toggle") {
          var attributes = helpTemplateAttrs[selector];
          attributes.class.split(/\s+/).forEach(function (name) { part.classList.add(name); });
          Object.keys(attributes).forEach(function (name) { part.setAttribute(name, attributes[name]); });
        }
        part.closest = function (query) {
          return query === ".error-surface" ? surface : query === selector ? part : null;
        };
        surface.parts[selector] = part;
        surface.appendChild(part);
      });
    return surface;
  }
}};
var retrySequence = 0, retryActions = {};
var researchJobId = null, chatJobBubbles = {};
var navigations = [], retries = [], clearedTimers = [];
function clearInterval(timer) { clearedTimers.push(timer); }
function renderFanout() {}
function showTab(tab) { navigations.push(tab); }
function maybeLoadTab() {}
function enqueueChat(message) { retries.push(message); }
document.addEventListener = function (name, callback) { document[name] = callback; };

function activate(html, attribute, listener) {
  var buttons = html.match(/<button\b[^>]*>/g) || [];
  for (var button of buttons) {
    var match = button.match(new RegExp(attribute + "=(['\"])(.*?)\\1"));
    if (!match) continue;
    var target = {dataset: {}, closest: function (selector) {
      return selector === "[" + attribute + "]" ? target : null;
    }};
    target.dataset[attribute.slice(5).replace(/-([a-z])/g, function (_, letter) {
      return letter.toUpperCase();
    })] = textOf(match[2]);
    listener({target: target});
    return true;
  }
  return false;
}
function snapshot() {
  var box = $("#research-result");
  var errorSurface = box.children[0];
  return {
    jobId: researchJobId,
    submitDisabled: $("#research-submit").disabled,
    cancelDisabled: $("#research-cancel").disabled,
    cancelHidden: hidden["#research-cancel"],
    form: box.innerHTML, chat: $("#bound-chat").innerHTML,
    errorVariant: errorSurface ? errorSurface.dataset.variant : null,
    errorHelp: errorSurface ? errorSurface.querySelector(".error-help").textContent : "",
    errorHelpHidden: errorSurface ? errorSurface.querySelector(".error-help").classList.contains("hidden") : null,
    errorHelpExpanded: errorSurface ? errorSurface.querySelector(".error-help-toggle").attributes["aria-expanded"] : null,
    bound: Object.keys(chatJobBubbles),
    announcements: $("#chat-announcements").textContent,
    clearedTimers: clearedTimers.slice(), reloads: reloads.slice()
  };
}
function bindRunning() {
  chatJobBubbles["g003-job"] = {
    el: $("#bound-chat"), res: {reading: "RateLimiter 실행", steps: []},
    message: 'RateLimiter <again> & "retry"', timer: 17, startedAt: 1
  };
  setResearchRunning("g003-job");
  applyJobs([{job_id: "g003-job", kind: "research", status: "running", steps: [], totals: {}}]);
}
"""


def _outcome_harness() -> str:
    declarations = "\n".join(_declaration(name) for name in ("STATUS_KO", "FAIL_KO"))
    return _harness(
        "apiSend", "retryAfterSeconds", "escapeHtml", "showResult",
        "renderErrorSurface", "classifyError", "sanitizeErrorDetail", "friendlyError",
        "statusKo", "statusBadge", "statusIcon", "totalsSummary",
        "applyJobs", "setResearchRunning", "updateChatJob", "renderBoundJob",
        "renderTrace", "announceChatMessage", "chatAnswer",
        extra=_help_template() + DOM + declarations,
    ) + _listener(
        '  document.addEventListener("click", async function (ev) {\n'
        '    var retry = ev.target.closest && ev.target.closest("[data-retry]");'
    ) + "\nvar errorClick = document.click;\n" + _listener(
        '  $("#research-cancel").addEventListener("click", async function () {'
    ) + _listener(
        '  document.addEventListener("click", function (ev) {\n'
        '    var focus = ev.target.closest("[data-focus-target]");'
    ) + _listener('    $("#chat-log").addEventListener("click", function (ev) {')


def _run(script: str) -> dict:
    return _run_js("(async function(){\n" + _outcome_harness() + script +
                   "\n})().catch(function (error) { console.error(error); process.exit(1); });")


def _cancel_response(body: dict, status: int = 200, retry_after: str | None = None) -> str:
    return """
var requests = [], finishResponse;
function fetch(path, init) {
  requests.push({path: path, method: init.method, body: JSON.parse(init.body)});
  return new Promise(function (resolve) { finishResponse = resolve; });
}
bindRunning();
var cancelPending = $("#research-cancel").listeners.click();
var during = snapshot();
finishResponse({
  ok: STATUS >= 200 && STATUS < 300, status: STATUS,
  json: async function () { return BODY; },
  headers: {get: function (name) { return name === "Retry-After" ? WAIT : null; }}
});
await cancelPending;
""".replace("STATUS", str(status)).replace("BODY", json.dumps(body, ensure_ascii=False)).replace(
        "WAIT", json.dumps(retry_after)
    )


def _terminal(status: str, totals: dict) -> dict:
    job = {"job_id": "g003-job", "kind": "research", "status": status,
           "steps": [], "totals": totals, "error": "engine <failure> & details"}
    return _run("\nbindRunning();\nvar running = snapshot();\napplyJobs([" +
                json.dumps(job) + "]);\n" + """
var ended = snapshot();
var formReview = activate(ended.form, "data-goto", document.click);
var chatReview = activate(ended.chat, "data-goto", document.click);
var retry = activate(ended.chat, "data-chat-retry", $("#chat-log").listeners.click);
console.log(JSON.stringify({running: running, ended: ended,
  formReview: formReview, chatReview: chatReview, retry: retry,
  navigations: navigations, retries: retries,
  label: statusKo(STATUS), totals: totalsSummary(TOTALS)}));
""".replace("STATUS", json.dumps(status)).replace("TOTALS", json.dumps(totals)))
