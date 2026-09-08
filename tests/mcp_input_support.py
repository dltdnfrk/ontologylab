"""Real packed-session and stdin drivers for MCP input-boundary tests."""

from __future__ import annotations

from contextlib import ExitStack, contextmanager, redirect_stdout
import io
import json
from types import SimpleNamespace
from unittest.mock import patch

from ontologylab.mcp_protocol import run_stdio
from ontologylab.mcp_server import PackSession, build_mcp_app
from tests.test_mcp_session import _build_fixture_pack


@contextmanager
def graph_contract(tmp_path):
    packs, pack_id, _source, _target = _build_fixture_pack(tmp_path)
    session = PackSession(packs)
    try:
        session.load_pack(pack_id)
        with ExitStack() as stack:
            calls = {
                name: stack.enter_context(
                    patch.object(session, name, wraps=getattr(session, name))
                )
                for name in ("traverse_relations", "find_path", "graph_query")
            }
            yield build_mcp_app(session), calls
    finally:
        session.close()


def stdio_requests(app, requests, monkeypatch):
    raw = "".join(json.dumps(request) + "\n" for request in requests).encode()
    stdout = io.StringIO()
    with monkeypatch.context() as scoped:
        scoped.setattr("sys.stdin", SimpleNamespace(buffer=io.BytesIO(raw)))
        with redirect_stdout(stdout):
            run_stdio(app._dispatch)
    return [json.loads(line) for line in stdout.getvalue().splitlines()]
