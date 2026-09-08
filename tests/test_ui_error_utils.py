"""Behavior of the shipped error utilities under both UMD loading modes."""

from __future__ import annotations

import json
import shutil
import subprocess

import pytest

from ontologylab import web_assets


@pytest.fixture(params=["browser", "commonjs"])
def run_utils(request):
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed")
    source = json.dumps(web_assets.read_asset_text("ui-utils.js"), ensure_ascii=False)
    setup = (
        "const scope = {};"
        if request.param == "browser"
        else "const scope = {module: {exports: {}}};"
    )
    export = (
        "scope.ontologylabUiUtils"
        if request.param == "browser"
        else "scope.module.exports"
    )

    def run(script: str):
        proc = subprocess.run(
            [node],
            input=(
                setup
                + f"require('node:vm').runInNewContext({source}, scope);"
                + f"const ui = {export};\n"
                + script
            ),
            capture_output=True,
            text=True,
            check=False,
        )
        assert proc.returncode == 0, proc.stderr
        return json.loads(proc.stdout)

    return run


@pytest.mark.parametrize(
    ("response", "fallback", "expected"),
    [
        ("undefined", "undefined", "요청을 처리하지 못했습니다."),
        ("null", "'대체 메시지'", "대체 메시지"),
        ("{}", "''", "요청을 처리하지 못했습니다."),
        ("{detail: '거절', error: '다른 오류'}", "'대체'", "거절"),
        ("{error: '오류'}", "'대체'", "오류"),
        ("{detail: '', error: '오류'}", "'대체'", "오류"),
        ("{detail: false}", "'대체'", "대체"),
        ("{detail: 0}", "'대체'", "대체"),
        ("{detail: 42}", "'대체'", "42"),
        ("{detail: true}", "'대체'", "true"),
        ("{detail: {field: 'name', detail: '너무 길어요'}}", "'대체'", "name: 너무 길어요"),
        ("{detail: {detail: '거절'}}", "'대체'", "거절"),
        ("{detail: {field: 'name'}}", "'대체'", "name: 대체"),
        ("{detail: {}, error: '다른 오류'}", "'대체'", "대체"),
        ("{detail: {field: 'name', detail: ''}}", "'대체'", "name: 대체"),
        ("{detail: []}", "'대체'", ""),
        ("{detail: [{loc: ['body', 'name'], msg: 'bad'}]}", "'대체'", "name: bad"),
        (
            "{detail: [{loc: ['body', 'items', 0], msg: 'bad'}, {msg: 'required'}]}",
            "'대체'",
            "0: bad · : required",
        ),
        ("{detail: [{loc: []}, {}]}", "'대체'", ":  · : "),
    ],
)
def test_error_text_preserves_envelope_precedence(run_utils, response, fallback, expected):
    out = run_utils(f"console.log(JSON.stringify(ui.errorText({response}, {fallback})));")
    assert out == expected


@pytest.mark.parametrize(
    "response",
    [
        "undefined", "null", "false", "0", "''", "{}",
        "{ok: true}",
        "{ok: true, detail: 'informational', error: 'ignored', retry_after: 3}",
        "{ok: 0}", "{ok: 'false'}", "{ok: null}",
        "{detail: '', error: '', error_kind: 'busy', retry_after: 5}",
    ],
)
def test_non_refusals_return_without_throwing(run_utils, response):
    out = run_utils(
        f"console.log(JSON.stringify({{returnedUndefined: ui.throwIfRefused({response}) === undefined}}));"
    )
    assert out == {"returnedUndefined": True}


@pytest.mark.parametrize(
    ("response", "message", "kind"),
    [
        ("{ok: false}", "서버가 요청을 받아들이지 않았습니다.", None),
        ("{ok: false, detail: '거절', error_kind: 'busy'}", "거절", "busy"),
        ("{detail: {field: 'name', detail: 'bad'}}", "name: bad", None),
        ("{detail: [{loc: ['body', 'name'], msg: 'bad'}]}", "name: bad", None),
        ("{error: '거절', error_kind: ''}", "거절", None),
        ("{ok: null, detail: '거절'}", "거절", None),
        ("{ok: 1, error: '거절'}", "거절", None),
        ("{ok: 'true', error: '거절'}", "거절", None),
        ("{detail: []}", "", None),
    ],
)
def test_refusal_throws_a_typed_error(run_utils, response, message, kind):
    out = run_utils(
        f"try {{ ui.throwIfRefused({response}); console.log(JSON.stringify({{refused: false}})); }}"
        "catch (e) { console.log(JSON.stringify({refused: true, name: e.name,"
        " message: e.message, kind: e.errorKind, hasRetry: Object.hasOwn(e, 'retryAfter')})); }"
    )
    assert out == {
        "refused": True, "name": "Error", "message": message,
        "kind": kind, "hasRetry": False,
    }


@pytest.mark.parametrize("retry", ["undefined", "null", "0", "5", "'5'", "false", "''"])
def test_retry_metadata_preserves_presence_and_value(run_utils, retry):
    out = run_utils(
        f"const response = Object.freeze({{ok: false, retry_after: {retry}}});"
        "try { ui.throwIfRefused(response); console.log(JSON.stringify({refused: false})); }"
        "catch (e) { console.log(JSON.stringify({refused: true,"
        " hasRetry: Object.hasOwn(e, 'retryAfter'), retry: e.retryAfter})); }"
    )
    expected = {"refused": True, "hasRetry": retry not in ("undefined", "null")}
    if expected["hasRetry"]:
        expected["retry"] = {"0": 0, "5": 5, "'5'": "5", "false": False, "''": ""}[retry]
    assert out == expected


def test_helpers_do_not_mutate_frozen_validation_envelopes(run_utils):
    out = run_utils(
        "const item = Object.freeze({loc: Object.freeze(['body', 'name']), msg: 'bad'});"
        "const response = Object.freeze({ok: false, detail: Object.freeze([item])});"
        "const message = ui.errorText(response);"
        "try { ui.throwIfRefused(response); console.log(JSON.stringify({refused: false})); }"
        "catch (e) { console.log(JSON.stringify({message, refusal: e.message,"
        " response, sameItem: response.detail[0] === item})); }"
    )
    assert out == {
        "message": "name: bad", "refusal": "name: bad", "sameItem": True,
        "response": {"ok": False, "detail": [{"loc": ["body", "name"], "msg": "bad"}]},
    }
