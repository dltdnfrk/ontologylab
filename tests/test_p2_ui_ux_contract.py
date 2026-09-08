from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

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
        raise AssertionError("node is required for UI rendering contracts")
    result = subprocess.run(
        [node, "-e", script], cwd=ROOT, capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout.strip())


def test_mcp_machine_paths_and_commands_are_secondary_copyable_values() -> None:
    renderer = _function("loadMcp")
    assert 'copyableMachineValueHtml((data && data.packs_dir)' in renderer
    assert "copyableMachineValueHtml(" in renderer and 'pack.serve_command || ""' in renderer
    assert "pre.textContent = pack.serve_command" not in renderer
    assert "data-copy-identifier" in _function("copyableMachineValueHtml")
    assert "data-secondary-machine-value" in _function("copyableMachineValueHtml")


def test_settings_paths_rest_shortened_and_reveal_exact_edit_values() -> None:
    for field in ("data", "packs"):
        assert f'id="settings-{field}-dir-rest"' in HTML
        tag = HTML.split(f'id="settings-{field}-dir"', 1)[1].split(">", 1)[0]
        assert "path-edit-input hidden" in tag
    assert 'id="settings-searxng-url-rest"' in HTML
    searxng = HTML.split('id="settings-searxng-url"', 1)[1].split(">", 1)[0]
    assert "path-edit-input hidden" in searxng
    renderer = _function("renderEditablePath")
    assert "input.value = value" in renderer
    assert "copyableMachineValueHtml" in renderer
    assert "data-reveal-path" in renderer
    submit = APP.split('$("#settings-form").addEventListener("submit"', 1)[1].split("\n  });", 1)[0]
    assert '$("#settings-data-dir").value.trim()' in submit
    assert '$("#settings-packs-dir").value.trim()' in submit


def test_competency_questions_render_formal_korean_with_stable_machine_ids() -> None:
    catalogue = "var COMPETENCY_QUESTION_KO = {" + APP.split(
        "var COMPETENCY_QUESTION_KO = {", 1
    )[1].split("};", 1)[0] + "};"
    result = _run_node(
        "const nodes={body:{innerHTML:''},box:{classList:{add(){},remove(){}}}};"
        "function $(s){return s==='#competency-body'?nodes.body:nodes.box;}"
        "function escapeHtml(v){return String(v == null ? '' : v)};"
        + catalogue + _function("competencyQuestionCopy")
        + _function("renderCompetencyReceipt")
        + "\nrenderCompetencyReceipt({available:true,all_passed:true,passed_count:3,total_count:3,questions:["
        "{question_id:'Q1',question:'Can every verified fact be traced?',passed:true},"
        "{question_id:'Q2',question:'Does the extractor work?',passed:true},"
        "{question_id:'Q3',question:'Does a built pack answer?',passed:true}]});"
        "console.log(JSON.stringify({html:nodes.body.innerHTML}));"
    )
    rendered = result["html"]
    for question_id in ("Q1", "Q2", "Q3"):
        assert f'data-question-id="{question_id}"' in rendered
    assert "검증된 모든 사실" in rendered
    assert "예상한 개체와 관계를 정확하게" in rendered
    assert "사용자 질의에 정확한 답" in rendered
    assert "<small>Can every" not in rendered and "<small>Does the" not in rendered
    assert 'title="원문: Can every verified fact be traced?"' in rendered
    assert ">통과<" in rendered
    assert ">PASS<" not in rendered
    assert 'data-machine-status="PASS"' in rendered


def test_engine_fallback_warning_is_adjacent_and_accessibly_related() -> None:
    assert 'id="settings-engine-warning"' in HTML
    assert 'role="status"' in HTML.split('id="settings-engine-warning"', 1)[1].split(">", 1)[0]
    assert 'aria-live="polite"' in HTML.split('id="settings-engine-warning"', 1)[1].split(">", 1)[0]
    for control in ("settings-default-engine", "settings-default-model"):
        tag = HTML.split(f'id="{control}"', 1)[1].split(">", 1)[0]
        assert "settings-engine-warning" in tag
    assert '$("#settings-engine-warning")' in _function("populateSettingsEngineModelSelects")


def test_builtin_ontology_definitions_use_korean_primary_copy_with_fallback() -> None:
    catalogue = "var BUILTIN_DEFINITION_KO = {" + APP.split(
        "var BUILTIN_DEFINITION_KO = {", 1
    )[1].split("};", 1)[0] + "};"
    result = _run_node(
        catalogue + _function("builtinDefinitionCopy") +
        "\nconsole.log(JSON.stringify({known:builtinDefinitionCopy({reviewer:'ontologylab-bundled-schema',definition:'A concrete software artifact: module, service, library, tool, API.'}),"
        "fallback:builtinDefinitionCopy({reviewer:'ontologylab-bundled-schema',definition:'Future bundled English definition.'}),"
        "user:builtinDefinitionCopy({reviewer:'curator',definition:'User supplied definition.'})}));"
    )
    assert result["known"]["primary"].startswith("모듈")
    assert "A concrete software artifact" not in result["known"]["primary"]
    assert result["fallback"]["primary"] == "번들 온톨로지에 포함된 기본 용어입니다."
    assert result["user"]["primary"] == "User supplied definition."
    renderer = _function("renderTermDetail")
    assert "builtinDefinitionCopy(term)" in renderer
    assert "definitionCopy.original" in renderer


def test_manifest_invalid_is_typed_korean_primary_with_collapsed_raw_detail() -> None:
    catalogue = "var PACK_FAILURE_KO = {" + APP.split(
        "var PACK_FAILURE_KO = {", 1
    )[1].split("};", 1)[0] + "};"
    result = _run_node(
        catalogue + _function("packFailureCopy") +
        "\nconsole.log(JSON.stringify(packFailureCopy('manifest invalid')));"
    )
    assert result["primary"] == "팩 매니페스트가 유효하지 않습니다."
    assert result["raw"] == "manifest invalid"
    renderer = _function("renderUnusablePacks")
    assert "packFailureCopy" in renderer
    assert "<summary>기술 세부 정보</summary>" in renderer


def test_graph_key_guidance_is_korean_while_keyboard_semantics_remain() -> None:
    assert "Enter 또는 Space" not in HTML
    assert "엔터 또는 스페이스바" in HTML
    assert 'graph: [["엔터 / 스페이스바", "선택"], ["이스케이프", "선택 해제"]]' in APP
    assert 'ev.key !== "Enter" && ev.key !== " "' in APP


def test_packs_table_owns_overflow_cue_and_reachable_final_action() -> None:
    fragment = HTML.split('id="packs-table"', 1)[0].rsplit('<div', 1)[1]
    assert "packs-table-wrap" in fragment
    assert 'tabindex="0"' in fragment
    assert 'aria-describedby="packs-table-scroll-help"' in fragment
    assert 'id="packs-table-scroll-help"' in HTML
    assert "가로로 스크롤" in HTML
    assert ".packs-table-wrap" in CSS and "overflow-x: auto" in CSS
    assert ".packs-table-wrap::after" in CSS


def test_all_human_timestamps_are_relative_with_exact_machine_details() -> None:
    assert "function timeHtml(" in APP
    assert 'datetime=' in APP
    assert "fmtRelative(ts)" in APP
    # Direct absolute-only timestamp rendering is reserved for title/details helpers.
    assert len(re.findall(r"fmtTs\([^)]*\)", APP)) <= 4


def test_orphan_workflow_numbers_and_false_cost_label_are_removed() -> None:
    for marker in ("①", "②", "③", "④", "⑤"):
        assert marker not in HTML
    assert "비용 요약" not in HTML
    assert "사용량 요약" in HTML


def test_settings_use_validated_engine_and_model_catalogues(tmp_path: Path) -> None:
    assert '<select id="settings-default-engine"' in HTML
    assert '<select id="settings-default-model"' in HTML
    assert "function populateSettingsEngineModelSelects(" in APP
    assert "malformedSavedValue" in APP

    client = TestClient(create_app(data_dir=tmp_path / "data", packs_dir=tmp_path / "packs"))
    engines = client.get("/api/engines").json()
    mock = next(engine for engine in engines if engine["name"] == "mock")
    assert mock["models"] == []
    response = client.put("/api/settings", json={"default_engine": "not-registered"})
    assert response.status_code == 400


def test_mock_routes_storage_queries_to_status() -> None:
    import asyncio

    from ontologylab.engines import MockEngine
    from ontologylab.intent import classify

    for message in ("저장소에 뭐가 있어?", "저장 공간 현황을 알려줘"):
        intent = asyncio.run(classify(message, MockEngine()))
        assert intent.action == "status"
        assert intent.reading
        assert intent.needs_confirmation is False


def test_known_machine_labels_use_the_central_korean_catalogue() -> None:
    for machine, korean in (
        ("Concept", "개념"), ("Component", "구성 요소"),
        ("Technique", "기법"), ("Protein", "단백질"),
        ("hybrid", "혼합 검색"), ("extractive", "추출식 요약"),
    ):
        assert f'{machine}: "{korean}"' in web_assets.read_asset_text("localize.js")
    assert "ontologyLabelKo(pack.search_tier" in _function("loadPacks")
    assert "ontologyLabelKo(c.summary_method" in _function("loadCommunities")
    assert "ontologyLabelKo(node.entity_type" in _function("nodeCellHtml")


def test_help_copy_is_centralized_korean_while_machine_ids_remain_visible() -> None:
    assert "helpActions:" in APP
    assert "HELP_ACTION_KO" not in APP
    assert "data-action-id" in APP
    assert "show_review" in APP and "search_entities" in APP


def test_asset_urls_are_bound_to_full_committed_content_hashes() -> None:
    entries = {entry.path: entry.sha256 for entry in web_assets.manifest_entries(web_assets.resource_root())}
    parser = re.compile(r'(?:href|src)="/static/([^"?]+)\?v=([0-9a-f]{64})"')
    linked = dict(parser.findall(HTML))
    for path in ("favicon.svg", "style.css", "ui-utils.js", "localize.js", "chat-session.js", "research-summary.js", "app.js"):
        assert linked[path] == entries[path]
    assert not re.search(r"/static/[^\"']+\?v=\d+(?:[\"'])", HTML)


def test_provider_url_uses_copyable_identifier_not_raw_primary_display() -> None:
    renderer = _function("loadProviders")
    assert "shortIdentifier(p.base_url)" in renderer
    assert "data-copy-identifier" in renderer
    assert '"<td>" + escapeHtml(p.base_url) + "</td>"' not in renderer


def test_term_iri_uses_copyable_identifier_not_raw_primary_display() -> None:
    meta = APP.split("function termMetaLine", 1)[1].split("\n  }", 1)[0]
    assert "shortIdentifier(term.iri)" in meta
    assert "data-copy-identifier" in meta
    assert "escapeHtml(term.iri) + \"</code>\"" not in meta
