"""End-to-end MVP loop, entirely offline:

collect (file) -> extract (mock engine) -> review/approve (human gate)
  -> build-pack (verified-only) -> query via PackSession (MCP tool logic)
"""

import json
import sqlite3

import pytest

from ontologylab.main import main
from ontologylab.mcp_server import NoActivePack, PackSession
from ontologylab.packbuilder import list_packs

from tests.conftest import SAMPLE_TEXT


def run_cli(*argv) -> int:
    with pytest.raises(SystemExit) as exc:
        main(list(argv))
    return exc.value.code


@pytest.fixture()
def workspace(tmp_path):
    notes = tmp_path / "notes.md"
    notes.write_text(SAMPLE_TEXT, encoding="utf-8")
    return {
        "notes": notes,
        "data": tmp_path / "data",
        "packs": tmp_path / "packs",
    }


def test_full_mvp_loop(workspace):
    data = str(workspace["data"])

    # collect
    assert run_cli("collect", "--data-dir", data, "--file", str(workspace["notes"])) == 0
    # duplicate collect: same content hash, no new document
    assert run_cli("collect", "--data-dir", data, "--file", str(workspace["notes"])) == 0

    # extract with the offline deterministic engine
    assert run_cli("extract", "--data-dir", data, "--engine", "mock") == 0

    # review queue is populated, nothing verified yet
    assert run_cli("review", "--data-dir", data) == 0

    # pack build of an empty verified set must not be the demo path: approve first
    assert (
        run_cli("approve", "--data-dir", data, "--filter", "min_confidence=0.5") == 0
    )

    # build the pack
    assert (
        run_cli(
            "build-pack",
            "--data-dir",
            data,
            "--name",
            "demo",
            "--packs-dir",
            str(workspace["packs"]),
        )
        == 0
    )

    packs = list_packs(workspace["packs"])
    assert len(packs) == 1
    manifest = packs[0]
    assert manifest["counts"]["documents"] == 1
    assert manifest["counts"]["nodes_verified"] == 6
    assert manifest["counts"]["edges_verified"] == 5
    assert manifest["search_tier"] == "fts5"
    assert manifest["content_hash"].startswith("sha256:")

    # query through the MCP tool logic
    session = PackSession(workspace["packs"])
    try:
        assert session.try_autoload() == manifest["pack_id"]

        lookup = session.entity_lookup(name="RateLimiter")
        assert lookup["count"] == 1
        rate_limiter = lookup["matches"][0]
        assert rate_limiter["status"] == "verified"

        search = session.semantic_search("ratelimiter")
        assert search["search_tier"] == "fts5"  # honest lexical labeling
        assert [r["name"] for r in search["results"]] == ["RateLimiter"]

        gq = session.graph_query(entity_type="Component", limit=10)
        assert len(gq["nodes"]) == 6

        api = session.entity_lookup(name="ApiGateway")["matches"][0]["id"]
        db = session.entity_lookup(name="OrderDatabase")["matches"][0]["id"]
        path = session.find_path(api, db, max_hops=6)
        assert path["found"] is True
        assert path["hop_count"] == 5

        hops = session.traverse_relations([api], max_hops=1)
        assert hops  # neighbor of ApiGateway reachable
    finally:
        session.close()


def test_pack_contains_no_proposed_rows(workspace):
    """§9.1 invariant: unreviewed data is structurally unreachable in a pack."""
    data = str(workspace["data"])
    run_cli("collect", "--data-dir", data, "--file", str(workspace["notes"]))
    run_cli("extract", "--data-dir", data, "--engine", "mock")

    # approve exactly one node by id; leave the rest proposed
    from ontologylab import paths
    from ontologylab.kgstore import KGStore

    store = KGStore.open(paths.kg_db_path(workspace["data"]))
    node_id = store.pending_review(kind="node")[0]["id"]
    store.close()
    run_cli("approve", "--data-dir", data, "--id", node_id)

    run_cli(
        "build-pack", "--data-dir", data, "--name", "partial",
        "--packs-dir", str(workspace["packs"]),
    )
    (manifest,) = list_packs(workspace["packs"])
    assert manifest["counts"]["nodes_verified"] == 1
    assert manifest["counts"]["edges_verified"] == 0

    pack_sqlite = workspace["packs"] / manifest["pack_id"] / "pack.sqlite"
    conn = sqlite3.connect(str(pack_sqlite))
    try:
        for table in ("nodes", "edges"):
            rows = conn.execute(
                f"SELECT COUNT(*) FROM {table} WHERE status != 'verified'"
            ).fetchone()[0]
            assert rows == 0, f"{table} leaked non-verified rows into the pack"
    finally:
        conn.close()


def test_collect_rejects_non_allowlisted_url(workspace, capsys):
    code = run_cli(
        "collect", "--data-dir", str(workspace["data"]),
        "--url", "https://evil.example.com/page",
    )
    assert code == 2
    assert "REJECTED" in capsys.readouterr().err


def test_edge_approve_without_endpoints_is_blocked(workspace, capsys):
    data = str(workspace["data"])
    run_cli("collect", "--data-dir", data, "--file", str(workspace["notes"]))
    run_cli("extract", "--data-dir", data, "--engine", "mock")

    from ontologylab import paths
    from ontologylab.kgstore import KGStore

    store = KGStore.open(paths.kg_db_path(workspace["data"]))
    edge_id = store.pending_review(kind="edge")[0]["id"]
    store.close()

    assert run_cli("approve", "--data-dir", data, "--id", edge_id) == 2
    assert "BLOCKED" in capsys.readouterr().err
    # --cascade approves endpoints together
    assert run_cli("approve", "--data-dir", data, "--id", edge_id, "--cascade") == 0


def test_pack_session_requires_loaded_pack(tmp_path):
    session = PackSession(tmp_path)
    assert session.try_autoload() is None  # zero packs -> nothing loaded
    with pytest.raises(NoActivePack):
        session.entity_lookup(name="x")


def test_pack_manifest_and_schema_json_readable(workspace):
    data = str(workspace["data"])
    run_cli("collect", "--data-dir", data, "--file", str(workspace["notes"]))
    run_cli("extract", "--data-dir", data, "--engine", "mock")
    run_cli("approve", "--data-dir", data, "--filter", "min_confidence=0.5")
    run_cli(
        "build-pack", "--data-dir", data, "--name", "demo",
        "--packs-dir", str(workspace["packs"]),
    )
    (manifest,) = list_packs(workspace["packs"])
    pack_dir = workspace["packs"] / manifest["pack_id"]
    schema = json.loads((pack_dir / "schema.json").read_text(encoding="utf-8"))
    assert {et["name"] for et in schema["entity_types"]} == {
        "Concept", "Component", "Technique",
    }
    assert (pack_dir / "provenance.jsonl").is_file()
