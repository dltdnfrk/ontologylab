"""Contract tests for MCP tool-call argument validation."""

from __future__ import annotations

from contextlib import redirect_stdout
import io
import json
from types import SimpleNamespace

import pytest

from ontologylab.mcp_protocol import run_stdio
from ontologylab.mcp_runtime import McpApp


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
    raw = "".join(json.dumps(request) + "\n" for request in requests).encode()
    monkeypatch.setattr("sys.stdin", SimpleNamespace(buffer=io.BytesIO(raw)))
    stdout = io.StringIO()

    with redirect_stdout(stdout):
        run_stdio(app._dispatch)

    responses = [json.loads(line) for line in stdout.getvalue().splitlines()]
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
