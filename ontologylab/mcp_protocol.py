"""Minimal JSON-RPC framing for the local MCP stdio registry."""

from __future__ import annotations

import json
import sys
from typing import Any, Callable, Mapping


Dispatch = Callable[[Mapping[str, Any]], dict[str, Any] | None]


def run_stdio(dispatch: Dispatch) -> None:
    """Read newline-delimited JSON-RPC until EOF and write exact responses."""
    for raw in sys.stdin.buffer:
        request_id: object = None
        try:
            message = json.loads(raw)
            if not isinstance(message, dict):
                raise ValueError("JSON-RPC request must be an object")
            request_id = message.get("id")
            result = dispatch(message)
            if result is None or "id" not in message:
                continue
            response = {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": result,
            }
        except KeyError as exc:
            response = {
                "jsonrpc": "2.0",
                "id": request_id,
                "error": {"code": -32601, "message": str(exc)},
            }
        except Exception as exc:
            response = {
                "jsonrpc": "2.0",
                "id": request_id,
                "error": {"code": -32602, "message": str(exc)},
            }
        print(
            json.dumps(
                response,
                ensure_ascii=False,
                separators=(",", ":"),
            ),
            flush=True,
        )
