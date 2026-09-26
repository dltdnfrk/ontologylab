"""claims_for / find_contradictions / compare_claims over a real built pack."""

from __future__ import annotations

import asyncio
import hashlib
import json
import sqlite3
from pathlib import Path

import pytest

from ontologylab.kgstore import KGStore
from ontologylab.mcp_server import PackSession, build_mcp_app
from ontologylab.models import ProposedEntity, ProposedRelation
from ontologylab.packbuilder import build_pack
from ontologylab.schemas import preset


def _entity(eid: str, etype: str, name: str, **props) -> ProposedEntity:
    return ProposedEntity(id=eid, entity_type=etype, name=name, properties=props)


def _controls(rid: str, src: str, dst: str, polarity: str) -> ProposedRelation:
    return ProposedRelation(
        id=rid, relation_type="controls", src_entity_id=src, dst_entity_id=dst,
        qualifiers={"polarity": polarity},
    )


def _paper(store: KGStore, tag: str):
    doc, _ = store.insert_document(
        source_kind="upload", source_uri=f"https://doi.org/10.1/{tag}", title=tag,
        raw_text=f"Paper {tag} on Fluopyram and Botrytis", content_hash=f"sha256:{tag}",
    )
    return doc


@pytest.fixture()
def session(tmp_path: Path):
    kg = tmp_path / "kg.sqlite"
    store = KGStore.open(kg)
    schema = preset("agrochem-v2")
    store.install_schema(
        label=schema["label"], description=schema["description"],
        entity_types=schema["entity_types"], relation_types=schema["relation_types"],
    )
    papers = {tag: _paper(store, tag) for tag in ("a", "b", "c", "d")}
    fluo = ("fluo", "ActiveIngredient", "Fluopyram")
    boscalid = ("bosc", "ActiveIngredient", "Boscalid")
    botrytis = ("botr", "Pathogen", "Botrytis cinerea")
    alternaria = ("alt", "Pathogen", "Alternaria solani")
    batches = [
        ("a", [fluo, botrytis], [_controls("e1", "fluo", "botr", "supports")]),
        ("b", [fluo, botrytis], [_controls("e2", "fluo", "botr", "no_effect")]),
        ("c", [fluo, boscalid, botrytis, alternaria], [
            _controls("e3", "fluo", "alt", "supports"),
            _controls("e4", "bosc", "botr", "supports"),
            _controls("e5", "bosc", "botr", "refutes"),
        ]),
        ("d", [boscalid, alternaria], [
            _controls("e6", "bosc", "alt", "refutes"),
            _controls("e7", "bosc", "alt", "no_effect"),
        ]),
    ]
    for tag, ents, rels in batches:
        store.insert_proposed(
            [_entity(*e) for e in ents], rels,
            source_doc_id=papers[tag].id, extractor_engine="mock",
        )
    for table in ("nodes", "edges"):
        for (item,) in store.conn.execute(
            f"SELECT id FROM {table} WHERE status='proposed'"
        ).fetchall():
            store.approve(item)
    ids = dict(store.conn.execute("SELECT name, id FROM nodes").fetchall())
    store.close()
    manifest = build_pack(
        kg, tmp_path / "packs", name="claims", allow_incomplete_extraction=True,
        incomplete_extraction_intent="claims fixture",
    )
    pack_session = PackSession(tmp_path / "packs")
    pack_session.load_pack(manifest.pack_id)
    yield pack_session, ids
    pack_session.close()


def test_claims_for_returns_both_polarities_with_evidence(session) -> None:
    pack, ids = session
    result = pack.claims_for(subject_id=ids["Fluopyram"], object_id=ids["Botrytis cinerea"])
    assert result["count"] == 2
    assert result["polarity_counts"]["supports"] == 1
    assert result["polarity_counts"]["no_effect"] == 1
    claim = result["claims"][0]
    assert claim["origin"] == "extracted" and claim["status"] == "verified"
    assert claim["evidence"]["source_uri"].startswith("https://doi.org/10.1/")
    assert claim["evidence"]["retrieved_at"] is not None
    assert result["pack"]["pack_id"]


def test_claims_for_filters_by_polarity(session) -> None:
    pack, ids = session
    only_null = pack.claims_for(subject_id=ids["Fluopyram"], polarity="no_effect")
    assert [c["object"]["name"] for c in only_null["claims"]] == ["Botrytis cinerea"]


def test_claims_for_rejects_unscoped_and_unknown_polarity(session) -> None:
    pack, ids = session
    with pytest.raises(ValueError):
        pack.claims_for()
    with pytest.raises(ValueError):
        pack.claims_for(subject_id=ids["Fluopyram"], polarity="maybe")


def test_find_contradictions_reports_only_polarity_conflicts(session) -> None:
    pack, _ids = session
    result = pack.find_contradictions()
    pairs = sorted(
        (c["subject"]["name"], c["object"]["name"]) for c in result["contradictions"]
    )
    # Boscalid->Alternaria has two claims, but both oppose: no conflict.
    assert pairs == [("Boscalid", "Botrytis cinerea"), ("Fluopyram", "Botrytis cinerea")]
    fluo = next(c for c in result["contradictions"] if c["subject"]["name"] == "Fluopyram")
    assert [c["polarity"] for c in fluo["opposing"]] == ["no_effect"]


def test_compare_claims_aligns_by_relation_and_object(session) -> None:
    pack, ids = session
    result = pack.compare_claims(ids["Fluopyram"], ids["Boscalid"])
    by_object = {s["object"]["name"]: s for s in result["shared"]}
    assert set(by_object) == {"Botrytis cinerea", "Alternaria solani"}
    # Fluopyram: supports + no_effect on Botrytis; Boscalid: supports + refutes.
    assert by_object["Botrytis cinerea"]["agree"] is False
    assert len(by_object["Botrytis cinerea"]["b"]) == 2
    # Fluopyram supports Alternaria; Boscalid refutes and finds no effect.
    assert by_object["Alternaria solani"]["agree"] is False
    assert result["disagreements"] == 2
    assert result["only_a"] == [] and result["only_b"] == []


def test_tools_are_registered_on_both_backends(session) -> None:
    pack, _ids = session
    for backend in ("stdlib", "auto"):
        app = build_mcp_app(pack, backend=backend)
        names = {tool.name for tool in asyncio.run(app.list_tools())}
        assert {"claims_for", "find_contradictions", "compare_claims"} <= names


@pytest.fixture()
def historical_session(session, tmp_path: Path):
    """Receipt a historical v1 snapshot; today's builder ships current edges only."""
    current, ids = session
    pack_id = "historical"
    pack_dir = tmp_path / "historical-packs" / pack_id
    pack_dir.mkdir(parents=True)
    database = pack_dir / "pack.sqlite"
    database.write_bytes((current.packs_dir / current.pack_id / "pack.sqlite").read_bytes())
    with sqlite3.connect(database) as conn:
        conn.executemany(
            "UPDATE edges SET valid_from=?, invalidated_ts=? WHERE id=?",
            [(None, 20.0, "e1"), (20.0, 30.0, "e2"), (30.0, None, "e3")],
        )
        conn.execute(
            "UPDATE edges SET source_span=?, origin='curated' WHERE id='e1'",
            (json.dumps({"start": 0, "end": 5}),),
        )
        conn.execute("UPDATE documents SET fetched_ts=123.0")
    (pack_dir / "manifest.json").write_text(json.dumps({
        "pack_id": pack_id,
        "content_hash": "sha256:" + hashlib.sha256(database.read_bytes()).hexdigest(),
    }))
    pack = PackSession(pack_dir.parent)
    pack.load_pack(pack_id)
    try:
        yield pack, ids
    finally:
        pack.close()


def test_claims_contract_aliases_preserve_existing_fields(historical_session) -> None:
    pack, ids = historical_session
    result = pack.claims_for(subject_id=ids["Fluopyram"], valid_at=10.0)
    assert result["count"] == 1
    claim = result["claims"][0]
    assert claim["edge_id"] == "e1"
    assert claim["provenance"] == claim["origin"] == "curated"
    assert claim["valid_to"] == claim["invalidated_ts"] == 20.0
    assert claim["pack_id"] == result["pack"]["pack_id"] == "historical"
    assert claim["source_uri"] == claim["evidence"]["source_uri"] == "https://doi.org/10.1/a"
    assert claim["source_span"] == claim["evidence"]["source_span"] == {"start": 0, "end": 5}
    assert claim["retrieved_at"] == claim["evidence"]["retrieved_at"] == 123.0
    assert claim["value"] is None and claim["unit"] is None


@pytest.mark.parametrize(
    ("arguments", "expected"),
    [
        ({}, ["e3"]),
        ({"valid_at": 20.0}, ["e2"]),
        ({"period_start": 20.0, "period_end": 30.0}, ["e2"]),
        ({"period_start": 19.0, "period_end": 21.0}, ["e1", "e2"]),
        ({"period_start": 30.0}, ["e3"]),
        ({"period_end": 20.0}, ["e1"]),
        ({"period_start": 20.0, "period_end": 20.0}, []),
        ({"period_start": -20.0, "period_end": -10.0}, ["e1"]),
        ({"period_start": 40.0, "period_end": 50.0}, ["e3"]),
    ],
)
def test_period_selects_half_open_overlap(historical_session, arguments, expected) -> None:
    pack, ids = historical_session
    result = pack.claims_for(subject_id=ids["Fluopyram"], **arguments)
    assert [claim["edge_id"] for claim in result["claims"]] == expected
    assert result["count"] == len(expected)
    assert sum(result["polarity_counts"].values()) == len(expected)


@pytest.mark.parametrize(
    "arguments",
    [
        {"period_start": 30.0, "period_end": 20.0},
        {"valid_at": 0.0, "period_start": 0.0},
        {"valid_at": 0.0, "period_end": 30.0},
    ],
)
def test_period_rejects_reversed_or_mixed_time_arguments(session, arguments) -> None:
    pack, ids = session
    with pytest.raises(ValueError):
        pack.claims_for(subject_id=ids["Fluopyram"], **arguments)


@pytest.mark.parametrize(
    ("measurement", "expected"),
    [
        ({"status": "normalized", "value": 0.25, "unit": "kg/ha"}, (0.25, "kg/ha")),
        ({"status": "normalized", "value": 0.0, "unit": "%"}, (0.0, "%")),
        ({"status": "unknown_unit", "value": 25.0, "unit": None}, (None, None)),
        ({"status": "no_unit", "value": 25.0, "unit": None}, (None, None)),
        ({"status": "unparsed", "value": None, "unit": None}, (None, None)),
        (None, (None, None)),
    ],
)
def test_flat_measurement_requires_normalized_status(session, measurement, expected) -> None:
    from ontologylab.claims import claims_for

    pack, ids = session
    # Copy to an in-memory backing store, never alter the immutable source pack.
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    try:
        pack.store.conn.backup(conn)
        conn.execute(
            "UPDATE nodes SET properties_json=? WHERE id=?",
            (json.dumps({"measurement": measurement}), ids["Botrytis cinerea"]),
        )
        result = claims_for(conn, subject_id=ids["Fluopyram"], object_id=ids["Botrytis cinerea"])
        assert len(result["claims"]) == 2
        for claim in result["claims"]:
            assert claim["measurement"] == measurement
            assert (claim["value"], claim["unit"]) == expected
    finally:
        conn.close()


def test_pre_origin_pack_keeps_contract_keys_without_migration(session, tmp_path: Path) -> None:
    pack, ids = session
    legacy_dir = tmp_path / "legacy-packs" / "legacy"
    legacy_dir.mkdir(parents=True)
    database = legacy_dir / "pack.sqlite"
    database.write_bytes((pack.packs_dir / pack.pack_id / "pack.sqlite").read_bytes())
    with sqlite3.connect(database) as conn:
        conn.execute("ALTER TABLE nodes DROP COLUMN origin")
        conn.execute("ALTER TABLE edges DROP COLUMN origin")
    before = hashlib.sha256(database.read_bytes()).hexdigest()
    (legacy_dir / "manifest.json").write_text(json.dumps({
        "pack_id": "legacy", "content_hash": "sha256:" + before,
    }))
    legacy = PackSession(legacy_dir.parent)
    try:
        legacy.load_pack("legacy")
        result = legacy.claims_for(subject_id=ids["Fluopyram"], period_start=0.0)
        assert result["count"] == 3
        for claim in result["claims"]:
            assert claim["provenance"] == claim["origin"] == "extracted"
            assert claim["pack_id"] == "legacy"
            assert claim["valid_to"] is None
            assert claim["source_uri"] == claim["evidence"]["source_uri"]
            assert claim["source_span"] == claim["evidence"]["source_span"]
            assert claim["retrieved_at"] == claim["evidence"]["retrieved_at"]
            assert claim["value"] is None and claim["unit"] is None
    finally:
        legacy.close()
    assert hashlib.sha256(database.read_bytes()).hexdigest() == before


def test_stdio_period_errors_are_not_success_and_recover(historical_session, monkeypatch) -> None:
    from tests.mcp_input_support import stdio_requests

    pack, ids = historical_session
    app = build_mcp_app(pack, backend="stdlib")
    arguments = [
        {"period_start": 30.0, "period_end": 20.0},
        {"period_start": "20"},
        {"period_end": "not-an-epoch"},
        {"period_start": 20.0, "period_end": 30.0},
    ]
    responses = stdio_requests(app, [
        {"jsonrpc": "2.0", "id": index, "method": "tools/call", "params": {
            "name": "claims_for", "arguments": {"subject_id": ids["Fluopyram"], **args},
        }}
        for index, args in enumerate(arguments)
    ], monkeypatch)
    assert responses[0]["result"]["isError"] is True
    assert "structuredContent" not in responses[0]["result"]
    for response in responses[1:3]:
        assert response["error"]["code"] == -32602
        assert "result" not in response
    assert responses[3]["result"]["isError"] is False
    result = responses[3]["result"]["structuredContent"]
    assert [claim["edge_id"] for claim in result["claims"]] == ["e2"]


@pytest.mark.parametrize("argument", ["period_start", "period_end"])
@pytest.mark.parametrize("value", ["20", "not-an-epoch", True])
def test_sdk_period_arguments_reject_non_numbers(session, argument, value) -> None:
    from mcp.server.fastmcp.exceptions import ToolError

    pack, ids = session
    app = build_mcp_app(pack, backend="fastmcp")
    with pytest.raises(ToolError):
        asyncio.run(app.call_tool("claims_for", {
            "subject_id": ids["Fluopyram"], argument: value,
        }))
