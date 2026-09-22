from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Final, TypedDict

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


