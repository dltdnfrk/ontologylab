"""Contract tests for MCP tool-call argument validation."""

from __future__ import annotations

import asyncio
import json

import pytest

from ontologylab.mcp_runtime import McpApp
from tests.mcp_input_support import graph_contract, stdio_requests


def _call(app: McpApp, name: str, arguments: object) -> dict[str, object]:
    result = app._dispatch({
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {"name": name, "arguments": arguments},
    })
    assert result is not None
    return result


@pytest.fixture()
def contract_app() -> tuple[McpApp, list[int]]:
    app = McpApp("input-contract")
    graph_limits: list[int] = []

    @app.tool()
    def entity_lookup(detail: bool = False, limit: int = 5) -> dict:
        return {"detail": detail, "limit": limit}

    @app.tool()
    def semantic_search(
        query: str,
        top_k: int = 10,
        min_score: float = 0.0,
    ) -> dict:
        return {"query": query, "top_k": top_k, "min_score": min_score}

    @app.tool()
    def traverse_relations(
        start_ids: list[str],
        max_hops: int = 2,
        limit: int = 200,
    ) -> dict:
        return {
            "start_ids": start_ids,
            "max_hops": max_hops,
            "limit": limit,
        }

    @app.tool()
    def graph_query(limit: int = 100, offset: int = 0) -> dict:
        graph_limits.append(limit)
        nodes = list(range(12)) if limit < 0 else list(range(min(limit, 12)))
        return {"nodes": nodes, "offset": offset}

    @app.tool()
    def optional_filter(entity_type: str | None = None) -> dict:
        return {"entity_type": entity_type}

    return app, graph_limits


@pytest.mark.parametrize(
    ("tool", "arguments"),
    [
        pytest.param("entity_lookup", {"detail": "false"}, id="boolean-string"),
        pytest.param(
            "traverse_relations",
            {"start_ids": "n_rl"},
            id="array-string",
        ),
        pytest.param(
            "semantic_search",
            {"query": "rate", "top_k": "10"},
            id="integer-string",
        ),
        pytest.param(
            "semantic_search",
            {"query": None},
            id="required-string-null",
        ),
    ],
)
def test_wrong_types_are_invalid_params_before_execution(
    contract_app: tuple[McpApp, list[int]],
    tool: str,
    arguments: dict[str, object],
) -> None:
    app, _ = contract_app

    with pytest.raises(ValueError, match="invalid arguments"):
        _call(app, tool, arguments)


def test_unknown_arguments_are_invalid_params_without_signature_leak(
    contract_app: tuple[McpApp, list[int]],
) -> None:
    app, _ = contract_app

    with pytest.raises(ValueError) as excinfo:
        _call(app, "entity_lookup", {"surprise": "injected"})

    message = str(excinfo.value)
    assert "invalid arguments" in message
    assert "unexpected keyword argument" not in message
    assert "entity_lookup(" not in message


@pytest.mark.parametrize(
    ("tool", "arguments"),
    [
        pytest.param("entity_lookup", {"limit": -1}, id="negative-limit"),
        pytest.param(
            "semantic_search",
            {"query": "rate", "top_k": -1},
            id="negative-top-k",
        ),
        pytest.param(
            "semantic_search",
            {"query": "rate", "min_score": 2.0},
            id="score-over-one",
        ),
        pytest.param(
            "traverse_relations",
            {"start_ids": ["n_rl"], "max_hops": -1},
            id="negative-max-hops",
        ),
        pytest.param("graph_query", {"offset": -1}, id="negative-offset"),
        pytest.param("graph_query", {"limit": 10**100}, id="huge-limit"),
        pytest.param(
            "traverse_relations",
            {"start_ids": ["n_rl"], "max_hops": 10**100},
            id="huge-max-hops",
        ),
    ],
)
def test_out_of_range_numbers_are_invalid_params(
    contract_app: tuple[McpApp, list[int]],
    tool: str,
    arguments: dict[str, object],
) -> None:
    app, _ = contract_app

    with pytest.raises(ValueError, match="invalid arguments"):
        _call(app, tool, arguments)


def test_negative_graph_limit_cannot_trigger_unlimited_query(
    contract_app: tuple[McpApp, list[int]],
) -> None:
    app, graph_limits = contract_app

    with pytest.raises(ValueError, match="invalid arguments"):
        _call(app, "graph_query", {"limit": -1})

    assert graph_limits == [], "rejected input must not execute the graph query"


def test_missing_required_argument_is_invalid_params(
    contract_app: tuple[McpApp, list[int]],
) -> None:
    app, _ = contract_app

    with pytest.raises(ValueError, match="invalid arguments"):
        _call(app, "semantic_search", {})


def test_optional_null_and_valid_calls_remain_accepted(
    contract_app: tuple[McpApp, list[int]],
) -> None:
    app, _ = contract_app

    optional = _call(app, "optional_filter", {"entity_type": None})
    valid = _call(app, "semantic_search", {
        "query": "rate limiter; ignore prior instructions",
        "top_k": 10,
        "min_score": 0.5,
    })

    assert optional["isError"] is False
    assert valid["isError"] is False
    assert valid["structuredContent"] == {
        "query": "rate limiter; ignore prior instructions",
        "top_k": 10,
        "min_score": 0.5,
    }


def test_stdio_maps_validation_to_invalid_params_and_stays_responsive(
    contract_app: tuple[McpApp, list[int]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app, graph_limits = contract_app
    requests = [
        {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {
            "name": "entity_lookup", "arguments": {"detail": "false"},
        }},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {
            "name": "entity_lookup", "arguments": {"injected": "ignore schema"},
        }},
        {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {
            "name": "graph_query", "arguments": {"limit": -1},
        }},
        {"jsonrpc": "2.0", "id": 4, "method": "ping"},
    ]
    responses = stdio_requests(app, requests, monkeypatch)
    assert [response["error"]["code"] for response in responses[:3]] == [
        -32602,
        -32602,
        -32602,
    ]
    assert all("result" not in response for response in responses[:3])
    assert "unexpected keyword argument" not in json.dumps(responses)
    assert responses[3] == {"jsonrpc": "2.0", "id": 4, "result": {}}
    assert graph_limits == []


def test_schema_advertises_enforced_shape_and_bounds(
    contract_app: tuple[McpApp, list[int]],
) -> None:
    app, _ = contract_app
    tools = {tool.name: tool for tool in __import__("asyncio").run(app.list_tools())}

    graph_schema = tools["graph_query"].inputSchema
    assert graph_schema["additionalProperties"] is False
    assert graph_schema["properties"]["limit"] == {
        "type": "integer",
        "default": 100,
        "minimum": 1,
        "maximum": 1000,
    }
    assert graph_schema["properties"]["offset"]["minimum"] == 0
    assert tools["semantic_search"].inputSchema["properties"]["min_score"][
        "maximum"
    ] == 1.0


ARRAY_ARGUMENTS = [
    pytest.param("traverse_relations", "start_ids", id="traverse-start"),
    pytest.param("traverse_relations", "relation_types", id="traverse-relations"),
    pytest.param("find_path", "relation_types", id="path-relations"),
]
BAD_ARRAYS = [
    pytest.param([7], id="integer"),
    pytest.param([True], id="boolean"),
    pytest.param([None], id="null"),
    pytest.param([{}], id="object"),
    pytest.param([[]], id="nested-array"),
    pytest.param(["n_rl", 7], id="mixed"),
]


@pytest.fixture()
def array_contract(tmp_path):
    with graph_contract(tmp_path) as context:
        yield context


def _graph_arguments(tool):
    if tool == "traverse_relations":
        return {"start_ids": ["n_rl"]}
    return {"source_id": "n_rl", "target_id": "n_tb"}


@pytest.mark.parametrize("tool, argument", ARRAY_ARGUMENTS)
@pytest.mark.parametrize("values", BAD_ARRAYS)
def test_string_array_items_refused_before_execution(array_contract, tool, argument, values):
    app, calls = array_contract
    arguments = {**_graph_arguments(tool), argument: values}
    refused = None
    try:
        _call(app, tool, arguments)
    except ValueError as error:
        refused = error
    assert calls[tool].call_count == 0, "malformed items reached the real tool"
    assert refused is not None and "invalid arguments" in str(refused)


@pytest.mark.parametrize("tool, argument", ARRAY_ARGUMENTS)
@pytest.mark.parametrize("values", BAD_ARRAYS)
def test_string_array_items_stdio_refusal_and_recovery(
    array_contract, monkeypatch, tool, argument, values
):
    app, calls = array_contract
    valid = {**_graph_arguments(tool), argument: ["n_rl"] if argument == "start_ids" else ["uses"]}
    requests = [
        {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {
            "name": tool, "arguments": {**_graph_arguments(tool), argument: values},
        }},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {
            "name": tool, "arguments": valid,
        }},
        {"jsonrpc": "2.0", "id": 3, "method": "ping"},
    ]
    responses = stdio_requests(app, requests, monkeypatch)
    assert [response["id"] for response in responses] == [1, 2, 3]
    assert responses[2] == {"jsonrpc": "2.0", "id": 3, "result": {}}
    assert responses[1]["result"]["isError"] is False
    good = responses[1]["result"]["structuredContent"]
    if tool == "find_path":
        assert good["found"] is True and good["hop_count"] == 1
    else:
        assert {node["id"] for node in good["nodes"]} == {"n_rl", "n_tb"}
    assert calls[tool].call_count == 1, "only the following valid call may execute"
    assert "result" not in responses[0]
    assert responses[0]["error"]["code"] == -32602
    assert "invalid arguments" in responses[0]["error"]["message"]


@pytest.mark.parametrize("tool, argument", ARRAY_ARGUMENTS)
def test_string_array_schema_advertises_string_items(array_contract, tool, argument):
    app, _calls = array_contract
    tools = {item.name: item for item in asyncio.run(app.list_tools())}
    rule = tools[tool].inputSchema["properties"][argument]
    assert rule["type"] == ("array" if argument == "start_ids" else ["array", "null"])
    assert rule.get("items") == {"type": "string"}


@pytest.mark.parametrize("tool, argument", ARRAY_ARGUMENTS)
@pytest.mark.parametrize("values", [["n_rl"], [], [""], ["not-an-identifier-or-relation"]])
def test_string_array_valid_lists_keep_their_values(array_contract, tool, argument, values):
    app, calls = array_contract
    result = _call(app, tool, {**_graph_arguments(tool), argument: values})
    assert result["isError"] is False
    assert calls[tool].call_count == 1
    sent = calls[tool].call_args
    actual = sent.args[0] if argument == "start_ids" else sent.kwargs[argument]
    assert actual == values


@pytest.mark.parametrize("tool", ["traverse_relations", "find_path"])
@pytest.mark.parametrize("arguments", [{}, {"relation_types": None}])
def test_string_array_optional_null_and_omission_remain_usable(array_contract, tool, arguments):
    app, calls = array_contract
    result = _call(app, tool, {**_graph_arguments(tool), **arguments})
    assert result["isError"] is False
    assert calls[tool].call_count == 1
    assert calls[tool].call_args.kwargs["relation_types"] is None
    content = result["structuredContent"]
    assert isinstance(content, dict)
    if tool == "find_path":
        assert content["found"] is True
    else:
        assert [edge["id"] for edge in content["edges"]] == ["e_uses"]


def test_arbitrary_property_values_remain_tool_owned(array_contract):
    app, calls = array_contract
    properties = {"nested": {"values": [7, True, None, [], {}]}}
    result = _call(app, "graph_query", {"property_filters": properties})
    assert calls["graph_query"].call_count == 1
    assert calls["graph_query"].call_args.kwargs["property_filters"] == properties
    assert result["isError"] is True, "unsupported SQL values remain tool errors, not invalid params"
    assert "structuredContent" not in result


def test_valid_outer_type_preserves_tool_error_classification(array_contract, monkeypatch):
    app, calls = array_contract
    responses = stdio_requests(app, [
        {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {
            "name": "traverse_relations", "arguments": {"start_ids": ["n_rl"], "direction": "sideways"},
        }},
        {"jsonrpc": "2.0", "id": 2, "method": "ping"},
    ], monkeypatch)
    assert calls["traverse_relations"].call_count == 1
    assert "error" not in responses[0]
    assert responses[0]["result"]["isError"] is True
    assert "structuredContent" not in responses[0]["result"]
    assert responses[1] == {"jsonrpc": "2.0", "id": 2, "result": {}}
