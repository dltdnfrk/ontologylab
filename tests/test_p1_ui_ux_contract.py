from __future__ import annotations

import json
import re
import shutil
import subprocess
from email.message import Message
from html.parser import HTMLParser
from pathlib import Path
from urllib.error import HTTPError

import pytest
from fastapi.testclient import TestClient

from ontologylab import web_assets
from ontologylab.server.app import create_app


APP = web_assets.read_asset_text("app.js")
HTML = web_assets.read_asset_text("index.html")
CSS = web_assets.read_asset_text("style.css")
ROOT = Path(__file__).resolve().parents[1]


def _function(name: str) -> str:
    for opener in (f"  async function {name}(", f"  function {name}("):
        if opener in APP:
            tail = APP.split(opener, 1)[1]
            return opener.strip() + tail.split("\n  }\n", 1)[0] + "\n  }"
    raise AssertionError(f"missing {name}()")


def _run_node(script: str) -> dict:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed")
    result = subprocess.run(
        [node, "-e", script], cwd=ROOT, capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout.strip().splitlines()[-1])


def test_shared_empty_state_has_semantic_structure_and_real_cta() -> None:
    source = _function("emptyState")
    result = _run_node(
        "function escapeHtml(v){return String(v);}\n"
        + source
        + "\nconsole.log(JSON.stringify({html:emptyState({icon:'add',title:'T',"
        "description:'D',action:{label:'A',focusTarget:'field'}})}));"
    )["html"]
    assert "empty-state-icon" in result
    assert "empty-state-title" in result
    assert "empty-state-description" in result
    assert "data-focus-target='field'" in result
    for seam in ("aliases.length", "xrefs.length", "renderEnrichments", "providers.length"):
        assert seam in APP
    assert APP.count("emptyState({") >= 4


def test_source_credential_probe_maps_200_401_429_without_secret(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from ontologylab.connectors.paper_api import PaperApiConnector

    async def ok_fetch(_self, source_spec):  # type: ignore[no-untyped-def]
        assert source_spec["source"] == "semanticscholar"
        return []

    monkeypatch.setattr(PaperApiConnector, "fetch", ok_fetch)
    client = TestClient(create_app(data_dir=tmp_path / "data"))
    ok = client.post("/api/sources/semanticscholar/test")
    assert ok.status_code == 200
    assert ok.json() == {"ok": True, "verification_status": 200}

    async def refused(_self, _source_spec):  # type: ignore[no-untyped-def]
        raise HTTPError("https://redacted.invalid", 401, "bad", Message(), None)

    monkeypatch.setattr(PaperApiConnector, "fetch", refused)
    unauthorized = client.post("/api/sources/semanticscholar/test")
    assert unauthorized.status_code == 200
    assert unauthorized.json() == {"ok": False, "verification_status": 401}

    async def throttled(_self, _source_spec):  # type: ignore[no-untyped-def]
        raise HTTPError("https://redacted.invalid", 429, "slow", Message(), None)

    monkeypatch.setattr(PaperApiConnector, "fetch", throttled)
    limited = client.post("/api/sources/semanticscholar/test")
    assert limited.status_code == 200
    assert limited.json() == {"ok": False, "verification_status": 429}
    assert "redacted.invalid" not in json.dumps(limited.json())


def test_review_list_fetches_only_from_explicit_more_action() -> None:
    assert 'id="review-more-btn"' in HTML
    assert 'id="review-progress"' in HTML
    assert '$('# + '"review-more-btn").addEventListener("click", reviewLoadMore)' in APP
    assert 'document.addEventListener("scroll", reviewMaybeLoadMore' not in APP
    assert "reviewMaybeLoadMore();" not in _function("loadProposals")
    assert "reviewMaybeLoadMore();" not in _function("focusRow")
    row = _function("appendReviewRow")
    assert "critic_score" in row
    assert "timeHtml" in row
    assert 'item.kind === "node"' not in row.split('focusBtn.addEventListener', 1)[0]
    relative = _run_node(
        _function("fmtRelative")
        + "\nconsole.log(JSON.stringify({value:fmtRelative(900, 1000)}));"
    )["value"]
    assert "분" in relative


def test_reason_tooltips_are_keyboard_reachable_for_disabled_controls() -> None:
    for control in ("bulk-approve-btn", "bulk-reject-btn"):
        assert f'data-reason-control="{control}"' in HTML
    assert 'class="reason-tooltip" role="tooltip"' in HTML
    assert "updateReasonControl" in APP
    assert "schema-active-reason" in APP
    assert ":focus-within .reason-tooltip" in CSS


def test_only_activity_and_appended_chat_messages_are_live() -> None:
    assert 'id="chat-log" aria-live=' not in HTML
    assert 'id="research-fanout" class="fanout" aria-live=' not in HTML
    assert '<footer class="statusbar" role="status">' not in HTML
    assert 'id="statusbar-activity"' in HTML and 'aria-live="polite"' in HTML
    assert "function announceChatMessage(" in APP
    announcement = _function("announceChatMessage")
    assert 'setAttribute("role", "status")' in announcement
    assert "aria-live" in announcement


class _TablistParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.depth = 0
        self.tab_depth: int | None = None
        self.direct_children: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.depth += 1
        attr = dict(attrs)
        if tag == "nav" and attr.get("role") == "tablist":
            self.tab_depth = self.depth
        elif self.tab_depth is not None and self.depth == self.tab_depth + 1:
            self.direct_children.append(tag + ":" + str(attr.get("role")))

    def handle_endtag(self, tag: str) -> None:
        if self.tab_depth == self.depth and tag == "nav":
            self.tab_depth = None
        self.depth -= 1


def test_navigation_tablist_has_only_tabs_and_one_local_chip() -> None:
    parser = _TablistParser()
    parser.feed(HTML)
    assert parser.direct_children == ["button:tab"] * 11
    assert "nav-rail-footer" not in HTML
    assert HTML.count("로컬 전용") == 1


def test_job_results_and_artifacts_use_visible_machine_consumable_contracts() -> None:
    totals = _run_node(
        _function("totalsSummary")
        + "\nconsole.log(JSON.stringify({value:totalsSummary({nodes_new:3,"
        "nodes_merged:2,edges_new:5,edges_merged:4})}));"
    )["value"]
    assert "신규 3" in totals and "병합 2" in totals
    assert "+3/~2" not in totals
    jobs = _function("renderJobs")
    assert "statusIcon" in jobs
    assert "statusKo" in jobs
    assert '<th>날짜</th>' in HTML
    assert "shortIdentifier" in _function("loadArtifacts")
    assert "data-copy-identifier" in _function("loadArtifacts")


def test_graph_nodes_share_pointer_and_keyboard_activation() -> None:
    draw = _function("drawGraph")
    assert 'setAttribute("role", "button")' in draw
    assert 'setAttribute("tabindex", "0")' in draw
    assert "g-hit-target" in draw
    wiring = APP.split("(function wireGraph()", 1)[1]
    assert 'ev.key !== "Enter" && ev.key !== " "' in wiring
    assert "activateGraphNode" in wiring
    assert ".g-node:focus-visible" in CSS
    assert 'graph: [["엔터 / 스페이스바", "선택"]' in APP


def test_chat_sessions_persist_metadata_across_windows_and_can_be_managed() -> None:
    script = r"""
const create = require('./ontologylab/web/chat-session.js');
const memory = new Map();
let values = ['session-a', 'session-b'];
const listeners = [];
const root = {
  crypto: {randomUUID: () => values.shift()},
  localStorage: {
    getItem: key => memory.get(key) || null,
    setItem: (key, value) => { memory.set(key, value); listeners.forEach(fn => fn({key})); },
  },
  addEventListener: (name, fn) => { if (name === 'storage') listeners.push(fn); },
};
const first = create(root);
first.touch('CRISPR off-target 최신 근거를 조사합니다');
const second = create(root);
const before = second.list();
const next = first.startNew();
first.rename(next, '후속 검토');
second.switchTo(next);
console.log(JSON.stringify({
  firstId: first.current(), secondId: second.current(), before,
  sessions: second.list(), storageKeys: Array.from(memory.keys()),
  history: second.historyPath(), startsNew: second.startsNewOnEntry('sources', 'home'),
}));
"""
    result = _run_node(script)
    assert result["before"][0]["title"].startswith("CRISPR")
    assert result["firstId"] == result["secondId"] == "session-b"
    assert result["sessions"][0]["title"] == "후속 검토"
    assert all("sessionStorage" not in key for key in result["storageKeys"])
    assert "session-b" in result["history"]
    assert result["startsNew"] is False
    for element in ("chat-session-select", "chat-session-rename", "chat-session-new"):
        assert f'id="{element}"' in HTML


def test_table_overflow_cue_uses_existing_tokens() -> None:
    assert ".table-wrap::after" in CSS
    cue = CSS.split(".table-wrap::after", 1)[1].split("}", 1)[0]
    assert "--background" in cue or "--border" in cue


def test_review_table_owns_horizontal_scroll_at_inspector_and_narrow_widths() -> None:
    review_rules = re.findall(r"#tab-review \.table-scroll\s*\{([^}]*)\}", CSS)
    assert review_rules
    assert all("overflow: visible" not in rule for rule in review_rules)
    assert any("overflow-x: auto" in rule for rule in review_rules)
    narrow = CSS.split("@media (max-width: 860px)", 1)[1]
    assert "#tab-review .table-scroll" in narrow
    assert "overflow-x: auto" in narrow


def test_review_identity_column_keeps_a_readable_floor_at_every_width() -> None:
    # Given: the shipped fixed-layout review table, whose flexible column is
    # the one a person reads to know what they are approving. Measured at
    # 375px it was 0px wide (content 269px) and 58px in the 1280px inspector.
    table = re.search(r"#proposals-table \{([^}]*)\}", CSS)
    assert table is not None
    assert "table-layout: fixed" in table.group(1)
    floor = re.search(r"min-width:\s*(\d+)px", table.group(1))
    assert floor is not None, "fixed layout with no floor collapses the identity column"
    reserved = {
        int(column): int(width)
        for column, width in re.findall(
            r"#proposals-table th:nth-child\((\d)\), "
            r"#proposals-table td:nth-child\(\d\) \{ width: (\d+)px; \}",
            CSS,
        )
    }

    # When: every column except the identity column reserves its own extent
    assert sorted(reserved) == [1, 2, 4, 5, 6, 7]

    # Then: the identity column keeps a readable remainder at any container width
    assert int(floor.group(1)) - sum(reserved.values()) >= 96


def test_branded_favicon_is_local_manifest_verified_and_served(tmp_path: Path) -> None:
    assert re.search(
        r'<link rel="icon" href="/static/favicon\.svg\?v=[0-9a-f]{64}" type="image/svg\+xml" />',
        HTML,
    )
    favicon = web_assets.read_asset_bytes("favicon.svg")
    assert favicon.startswith(b"<svg")
    assert b"<script" not in favicon and b"<image" not in favicon and b"href=" not in favicon
    entries = {entry.path for entry in web_assets.manifest_entries(web_assets.resource_root())}
    assert "favicon.svg" in entries
    assert web_assets.content_type("favicon.svg") == "image/svg+xml"
    client = TestClient(create_app(data_dir=tmp_path / "data-favicon"))
    response = client.get("/static/favicon.svg")
    assert response.status_code == 200
    assert response.content == favicon
