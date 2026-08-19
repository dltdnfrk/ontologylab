"""Small stdio MCP registry with no optional HTTP or validation imports."""
from __future__ import annotations

import asyncio
from dataclasses import asdict, dataclass
import inspect
import json
import re
from typing import Any, Callable, Coroutine, Mapping, cast

from ontologylab.mcp_protocol import run_stdio

@dataclass(frozen=True, slots=True)
class ToolDescription:
    name: str
    description: str
    inputSchema: dict[str, Any]

@dataclass(frozen=True, slots=True)
class ResourceTemplateDescription:
    uriTemplate: str
    name: str
    description: str
    mimeType: str = "application/json"

@dataclass(frozen=True, slots=True)
class _Tool:
    description: ToolDescription
    function: Callable[..., Any]

@dataclass(frozen=True, slots=True)
class _Resource:
    description: ResourceTemplateDescription
    function: Callable[..., Any]
    pattern: re.Pattern[str]

def _json_type(annotation: object) -> str:
    value = str(annotation)
    if "bool" in value:
        return "boolean"
    if "int" in value:
        return "integer"
    if "float" in value:
        return "number"
    if "dict" in value or "Mapping" in value:
        return "object"
    if "list" in value or "tuple" in value:
        return "array"
    return "string"

_NUMERIC_BOUNDS: dict[str, tuple[int | float | None, int | float | None]] = {
    "limit": (1, 1000),
    "top_k": (1, 1000),
    "max_hops": (0, 100),
    "min_score": (0.0, 1.0),
    "offset": (0, None),
}


def _input_schema(function: Callable[..., Any]) -> dict[str, Any]:
    signature = inspect.signature(function)
    properties: dict[str, Any] = {}
    required: list[str] = []
    for name, parameter in signature.parameters.items():
        json_type: str | list[str] = _json_type(parameter.annotation)
        if parameter.default is None:
            json_type = [json_type, "null"]
        properties[name] = {"type": json_type}
        if parameter.default is inspect.Parameter.empty:
            required.append(name)
        else:
            properties[name]["default"] = parameter.default
        if name in _NUMERIC_BOUNDS:
            minimum, maximum = _NUMERIC_BOUNDS[name]
            if minimum is not None:
                properties[name]["minimum"] = minimum
            if maximum is not None:
                properties[name]["maximum"] = maximum
    return {
        "type": "object",
        "properties": properties,
        "required": required,
        "additionalProperties": False,
    }


def _matches_json_type(value: object, expected: str) -> bool:
    if expected == "null":
        return value is None
    if expected == "boolean":
        return isinstance(value, bool)
    if expected == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if expected == "string":
        return isinstance(value, str)
    if expected == "array":
        return isinstance(value, list)
    if expected == "object":
        return isinstance(value, dict)
    return False


def _validate_arguments(
    tool_name: str,
    arguments: dict[str, Any],
    schema: Mapping[str, Any],
) -> None:
    properties = schema["properties"]
    unknown = arguments.keys() - properties.keys()
    if unknown:
        name = sorted(unknown)[0]
        raise ValueError(
            f"invalid arguments for tool {tool_name!r}: unknown argument {name!r}"
        )
    missing = set(schema["required"]) - arguments.keys()
    if missing:
        name = sorted(missing)[0]
        raise ValueError(
            f"invalid arguments for tool {tool_name!r}: missing required argument {name!r}"
        )
    for name, value in arguments.items():
        rule = properties[name]
        expected = rule["type"]
        expected_types = [expected] if isinstance(expected, str) else expected
        if not any(_matches_json_type(value, item) for item in expected_types):
            label = " or ".join(expected_types)
            raise ValueError(
                f"invalid arguments for tool {tool_name!r}: {name!r} must be {label}"
            )
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            if "minimum" in rule and value < rule["minimum"]:
                raise ValueError(
                    f"invalid arguments for tool {tool_name!r}: {name!r} is below minimum"
                )
            if "maximum" in rule and value > rule["maximum"]:
                raise ValueError(
                    f"invalid arguments for tool {tool_name!r}: {name!r} exceeds maximum"
                )

def _resource_pattern(template: str) -> re.Pattern[str]:
    parts: list[str] = []
    cursor = 0
    for match in re.finditer(r"\{([A-Za-z_][A-Za-z0-9_]*)\}", template):
        parts.append(re.escape(template[cursor:match.start()]))
        parts.append(f"(?P<{match.group(1)}>[^/]+)")
        cursor = match.end()
    parts.append(re.escape(template[cursor:]))
    return re.compile("".join(parts) + r"\Z")

class McpApp:
    """Decorator-compatible MCP tool/resource registry and stdio runner."""

    def __init__(self, name: str) -> None:
        self._name = name
        self._tools: dict[str, _Tool] = {}
        self._resources: list[_Resource] = []

    def tool(self):
        def register(function: Callable[..., Any]) -> Callable[..., Any]:
            description = ToolDescription(
                function.__name__,
                inspect.getdoc(function) or "",
                _input_schema(function),
            )
            self._tools[description.name] = _Tool(description, function)
            return function
        return register

    def resource(self, template: str):
        def register(function: Callable[..., Any]) -> Callable[..., Any]:
            description = ResourceTemplateDescription(
                template,
                function.__name__,
                inspect.getdoc(function) or "",
            )
            self._resources.append(_Resource(
                description,
                function,
                _resource_pattern(template),
            ))
            return function
        return register

    async def list_tools(self) -> list[ToolDescription]:
        return [tool.description for tool in self._tools.values()]

    async def list_resource_templates(
        self,
    ) -> list[ResourceTemplateDescription]:
        return [resource.description for resource in self._resources]

    @staticmethod
    def _tool_result(value: Any, *, is_error: bool = False) -> dict[str, Any]:
        text = (
            value if isinstance(value, str)
            else json.dumps(
                value,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
        )
        result: dict[str, Any] = {
            "content": [{"type": "text", "text": text}],
            "isError": is_error,
        }
        if not is_error and isinstance(value, Mapping):
            result["structuredContent"] = value
        return result

    def _call_tool(self, params: Mapping[str, Any]) -> dict[str, Any]:
        name = params.get("name")
        arguments = params.get("arguments", {})
        if not isinstance(name, str) or name not in self._tools:
            raise ValueError("unknown MCP tool")
        if not isinstance(arguments, dict):
            raise ValueError("tool arguments must be an object")
        tool = self._tools[name]
        _validate_arguments(name, arguments, tool.description.inputSchema)
        try:
            value = tool.function(**arguments)
            if inspect.isawaitable(value):
                awaitable = cast(
                    Coroutine[Any, Any, Any],
                    value,
                )
                value = asyncio.run(awaitable)
            return self._tool_result(value)
        except Exception as exc:
            return self._tool_result(str(exc), is_error=True)

    def _read_resource(self, params: Mapping[str, Any]) -> dict[str, Any]:
        uri = params.get("uri")
        if not isinstance(uri, str):
            raise ValueError("resource uri must be a string")
        for resource in self._resources:
            match = resource.pattern.fullmatch(uri)
            if match is None:
                continue
            value = resource.function(**match.groupdict())
            return {
                "contents": [{
                    "uri": uri,
                    "mimeType": "application/json",
                    "text": str(value),
                }],
            }
        raise ValueError("unknown MCP resource")

    def _dispatch(self, message: Mapping[str, Any]) -> dict[str, Any] | None:
        method = message.get("method")
        if not isinstance(method, str):
            raise ValueError("JSON-RPC method is required")
        if method.startswith("notifications/"):
            return None
        if method == "initialize":
            params = message.get("params", {})
            version = (
                params.get("protocolVersion", "2025-06-18")
                if isinstance(params, dict)
                else "2025-06-18"
            )
            return {
                "protocolVersion": version,
                "capabilities": {
                    "tools": {"listChanged": False},
                    "resources": {
                        "subscribe": False,
                        "listChanged": False,
                    },
                },
                "serverInfo": {"name": self._name, "version": "1"},
            }
        if method == "ping":
            return {}
        if method == "tools/list":
            return {
                "tools": [
                    asdict(tool)
                    for tool in asyncio.run(self.list_tools())
                ]
            }
        if method == "tools/call":
            return self._call_tool(message.get("params", {}))
        if method == "resources/templates/list":
            return {
                "resourceTemplates": [
                    asdict(template)
                    for template in asyncio.run(
                        self.list_resource_templates()
                    )
                ]
            }
        if method == "resources/read":
            return self._read_resource(message.get("params", {}))
        raise KeyError(method)

    def run(self, *, transport: str = "stdio") -> None:
        if transport != "stdio":
            raise ValueError("only MCP stdio transport is supported")
        run_stdio(self._dispatch)
