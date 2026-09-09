"""`--pin-pack`: the session answers from one pack or refuses.

Pack immutability protects integrity, not provenance of an answer. Each pack
in `packs_dir` is individually intact, so nothing in the hash chain notices a
client that switches packs mid-session and then reports facts the operator
never chose. The pin is that missing boundary.
"""

from __future__ import annotations

import pytest

from ontologylab.mcp_server import PackPinned, PackSession, build_mcp_app, main


def _tool_names(session: PackSession) -> set[str]:
    listing = build_mcp_app(session)._dispatch({"method": "tools/list"})
    return {tool["name"] for tool in listing["tools"]}


def test_pinning_removes_discovery_and_switching_from_the_tool_list(tmp_path):
    # Given: the same packs_dir served pinned and unpinned.
    unpinned = _tool_names(PackSession(tmp_path))
    pinned = _tool_names(PackSession(tmp_path, pinned_pack_id="alpha"))

    # Then: exactly the two pack-navigation tools disappear; a client cannot
    # call what it cannot see, and every read tool still ships.
    assert {"list_packs", "load_pack"} <= unpinned
    assert unpinned - pinned == {"list_packs", "load_pack"}
    assert pinned


def test_every_pack_addressed_path_refuses_a_foreign_pack(tmp_path):
    # Given: a session pinned to "alpha" and a neighbouring pack id.
    session = PackSession(tmp_path, pinned_pack_id="alpha")

    # When/Then: every entry point that accepts a pack id refuses "beta" —
    # tools, resource URIs, and discovery alike. A pin that closed only the
    # tool list would still leak through pack:// resource addressing.
    for name, call in (
        ("load_pack", lambda: session.load_pack("beta")),
        ("get_schema", lambda: session.get_schema(pack_id="beta")),
        ("resource_manifest", lambda: session.resource_manifest("beta")),
        ("resource_schema", lambda: session.resource_schema("beta")),
        ("resource_entity", lambda: session.resource_entity("beta", "n1")),
        ("list_packs", session.list_packs),
    ):
        with pytest.raises(PackPinned, match="alpha"):
            call()


def test_an_unpinned_session_keeps_reaching_other_packs(tmp_path):
    # The pin is opt-in: without it the same calls fail on the missing pack,
    # never on the boundary.
    session = PackSession(tmp_path)
    with pytest.raises(Exception) as excinfo:
        session.resource_manifest("beta")
    assert not isinstance(excinfo.value, PackPinned)


def test_pack_and_pin_pack_are_mutually_exclusive(tmp_path):
    with pytest.raises(SystemExit) as excinfo:
        main(["--packs-dir", str(tmp_path), "--pack", "alpha", "--pin-pack", "beta"])
    assert excinfo.value.code == 2
