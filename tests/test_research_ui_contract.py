from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from typing import Final, TypedDict

from ontologylab import web_assets
from ontologylab.research_spec import JsonObject, JsonValue

ROOT: Final = Path(__file__).resolve().parents[1]
NODE_DRIVER: Final = r"""
const fs = require("node:fs");
const vm = require("node:vm");

class Element {
  constructor(tagName) {
    this.tagName = String(tagName).toUpperCase();
    this.className = "";
    this.dataset = {};
    this.childNodes = [];
    this.ownText = "";
  }

  appendChild(child) {
    this.childNodes.push(child);
    return child;
  }

  set textContent(value) {
    this.ownText = String(value);
    this.childNodes = [];
  }

  get textContent() {
    return this.ownText + this.childNodes.map((child) => child.textContent).join("");
  }
}

function snapshot(node) {
  return {
    tagName: node.tagName,
    className: node.className,
    dataset: {...node.dataset},
    textContent: node.textContent,
    childNodes: node.childNodes.map(snapshot),
  };
}

function tags(node) {
  return [node.tagName].concat(node.childNodes.flatMap(tags));
}

const document = {
  createElement(tagName) {
    return new Element(tagName);
  },
};
const context = {document, executionMarker: false};
context.globalThis = context;
context.window = context;
vm.createContext(context);
const globalsBefore = new Set(Object.keys(context));
const rendererSource = fs.readFileSync("ontologylab/web/research-summary.js", "utf8");
vm.runInContext(rendererSource, context, {filename: "ontologylab/web/research-summary.js"});
const exports = Object.entries(context).filter(
  ([name, value]) => !globalsBefore.has(name) && typeof value === "function"
);
if (exports.length !== 1) {
  throw new Error("research summary script must publish one global function");
}

const attacks = {
  goal: '<script>globalThis.executionMarker="script"</script>goal',
  need: '<img src=x onerror=globalThis.executionMarker="img">need',
  assumption: '<svg onload=globalThis.executionMarker="svg">assumption',
  lineage: '<img src=x onerror=globalThis.executionMarker="lineage">parent',
};
const evidenceNeeds = Array.from({length: 23}, (_, index) => ({
  need_id: "need-" + index,
  description: attacks.need + " " + index,
  mandatory: index % 2 === 0,
  kind: "kind-" + index,
  minimum_content: "content-" + index,
}));
const needOccupancy = evidenceNeeds.map((need, index) => ({
  need_id: need.need_id,
  occupied: index % 2 === 0,
  eligible_document_count: index * 2,
}));
const summary = {
  goal: attacks.goal,
  current_plan_version: '<svg onload=globalThis.executionMarker="version">23</svg>',
  parent_plan_id: attacks.lineage,
  degraded_reason: '<script>globalThis.executionMarker="degraded"</script>partial',
  evidence_needs: evidenceNeeds,
  need_occupancy: needOccupancy,
  assumptions: [attacks.assumption, attacks.goal, attacks.need],
  recommendation: "extract",
  stop_reason: "budget_exhausted",
  post_extraction_counts: {
    support: {unverified: 0, receipt_linked: 7},
    contradiction: {potential_conflict: 2, not_observed: 5},
  },
};
const root = exports[0][1](summary);
process.stdout.write(JSON.stringify({
  tree: snapshot(root),
  tags: tags(root),
  executionMarker: context.executionMarker,
  attacks,
}));
"""


class _ShippedHTML(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.research_regions: list[tuple[str, str | None]] = []
        self.script_sources: list[str] = []

    def handle_starttag(
        self, tag: str, attrs: list[tuple[str, str | None]]
    ) -> None:
        attributes = dict(attrs)
        if attributes.get("id") == "job-research-summary":
            self.research_regions.append((tag, attributes.get("aria-label")))
        if tag == "script" and (source := attributes.get("src")) is not None:
            self.script_sources.append(source.partition("?")[0])


class _NodeSnapshot(TypedDict):
    tagName: str
    className: str
    dataset: dict[str, str]
    textContent: str
    childNodes: list[_NodeSnapshot]


class _Attacks(TypedDict):
    goal: str
    need: str
    assumption: str
    lineage: str


class _RuntimeSnapshot(TypedDict):
    tree: _NodeSnapshot
    tags: list[str]
    executionMarker: bool
    attacks: _Attacks


@dataclass(frozen=True, slots=True)
class _SnapshotTypeError(TypeError):
    expected: str

    def __str__(self) -> str:
        return f"runtime snapshot expected {self.expected}"


def _json_object(value: JsonValue) -> JsonObject:
    if not isinstance(value, dict):
        raise _SnapshotTypeError("object")
    return value


def _json_string(value: JsonValue) -> str:
    if not isinstance(value, str):
        raise _SnapshotTypeError("string")
    return value


def _node_snapshot(value: JsonValue) -> _NodeSnapshot:
    raw = _json_object(value)
    children = raw["childNodes"]
    dataset = _json_object(raw["dataset"])
    if not isinstance(children, list):
        raise _SnapshotTypeError("child list")
    return {
        "tagName": _json_string(raw["tagName"]),
        "className": _json_string(raw["className"]),
        "dataset": {
            str(key): _json_string(item)
            for key, item in dataset.items()
        },
        "textContent": _json_string(raw["textContent"]),
        "childNodes": [_node_snapshot(item) for item in children],
    }


def test_shipped_html_wires_the_research_summary_before_the_dashboard() -> None:
    parser = _ShippedHTML()
    parser.feed(web_assets.read_asset_text("index.html"))

    assert parser.research_regions == [("section", "리서치 추론")]
    summary_index = parser.script_sources.index("/static/research-summary.js")
    app_index = parser.script_sources.index("/static/app.js")
    assert summary_index + 1 == app_index


def _runtime_snapshot() -> _RuntimeSnapshot:
    completed = subprocess.run(
        ["node", "-e", NODE_DRIVER],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    payload = _json_object(json.loads(completed.stdout))
    raw_tags = payload["tags"]
    marker = payload["executionMarker"]
    attacks = _json_object(payload["attacks"])
    if not isinstance(raw_tags, list) or not isinstance(marker, bool):
        raise _SnapshotTypeError("tags and marker")
    return {
        "tree": _node_snapshot(payload["tree"]),
        "tags": [_json_string(tag) for tag in raw_tags],
        "executionMarker": marker,
        "attacks": {
            "goal": _json_string(attacks["goal"]),
            "need": _json_string(attacks["need"]),
            "assumption": _json_string(attacks["assumption"]),
            "lineage": _json_string(attacks["lineage"]),
        },
    }


def test_research_summary_runtime_keeps_hostile_text_inert() -> None:
    rendered = _runtime_snapshot()
    tree = rendered["tree"]

    assert rendered["executionMarker"] is False
    assert set(rendered["tags"]).isdisjoint({"SCRIPT", "IMG", "SVG"})
    assert rendered["attacks"]["goal"] in tree["textContent"]
    assert rendered["attacks"]["lineage"] in tree["textContent"]
    assert rendered["attacks"]["assumption"] in tree["textContent"]


def test_research_summary_runtime_keeps_complete_evidence_and_authority() -> None:
    rendered = _runtime_snapshot()
    tree = rendered["tree"]
    cards = tree["childNodes"]

    needs = cards[3]["childNodes"][1]["childNodes"]
    assert len(needs) == 23
    for index, need in enumerate(needs):
        state = "확보" if index % 2 == 0 else "미충족"
        requirement = "필수" if index % 2 == 0 else "선택"
        expected_class = "is-occupied" if index % 2 == 0 else "is-missing"
        assert need["className"] == expected_class
        assert need["textContent"] == (
            f'{state} · {rendered["attacks"]["need"]} {index} · {requirement}'
            f" · kind-{index} · min content-{index} · docs {index * 2}"
        )

    assumptions = cards[4]["childNodes"][1]["childNodes"]
    assert [item["textContent"] for item in assumptions] == [
        rendered["attacks"]["assumption"],
        rendered["attacks"]["goal"],
        rendered["attacks"]["need"],
    ]
    assert cards[1]["childNodes"][1]["textContent"] == (
        'v<svg onload=globalThis.executionMarker="version">23</svg>'
        f' · parent {rendered["attacks"]["lineage"]}'
    )
    assert cards[5]["childNodes"][1]["textContent"] == (
        "extract · stop: budget_exhausted"
    )
    assert cards[6]["childNodes"][0]["textContent"] == "advisory—not approval"
    assert cards[6]["childNodes"][0]["dataset"] == {"noTranslate": ""}
    assert cards[6]["childNodes"][1]["textContent"] == (
        "support receipt_linked 7 · support unverified 0"
        " · contradiction not_observed 5 · contradiction potential_conflict 2"
    )
