"""The real pack and MCP JSON-RPC surface preserve qualifier objects."""

from ontologylab.mcp_server import PackSession, build_mcp_app
from tests.mcp_input_support import stdio_requests
from tests.test_claims_contract import contract_response


def test_mcp_forwards_qualified_claims_without_losing_existing_fields(tmp_path, monkeypatch):
    baseline = contract_response(tmp_path)
    pack = PackSession(tmp_path / "packs")
    try:
        pack.load_pack(baseline["pack"]["pack_id"])
        app = build_mcp_app(pack, backend="stdlib")
        response = stdio_requests(app, [{
            "jsonrpc": "2.0", "id": 1, "method": "tools/call",
            "params": {"name": "claims_for", "arguments": {"subject_id": "fluo"}},
        }], monkeypatch)[0]
        assert response["result"]["isError"] is False
        payload = response["result"]["structuredContent"]
        assert payload == baseline
        assert payload["claims"][0]["qualifiers"] == {
            "polarity": "supports", "study_context": "field trial",
            "object_form_or_variant_qualifier": "isolate A",
        }
        assert payload["claims"][1]["qualifiers"] == {
            "polarity": "no_effect", "study_context": "in vitro",
        }
    finally:
        pack.close()
