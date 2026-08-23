"""Tampered ready bytes: approve refuses; reject/quarantine still append."""

from __future__ import annotations

from io import StringIO
from pathlib import Path

import pytest

from ontologylab.file_lifecycle import store_root_from_conn
from ontologylab.grounded_review import list_review_decisions
from ontologylab.kgstore import GroundingPreflightError, KGStore
from tests.step7_integration_support import (
    decision_count,
    plant_and_extract,
    probe_node_id,
)


def _ready_path(store: KGStore, representation_id: str) -> Path:
    row = store.conn.execute(
        "SELECT raw_text_path FROM documents WHERE id = ?",
        (representation_id,),
    ).fetchone()
    assert row is not None
    return store_root_from_conn(store.conn) / str(row["raw_text_path"])


def _tamper(store: KGStore, pmc_id: str) -> None:
    path = _ready_path(store, pmc_id)
    path.write_bytes(path.read_bytes() + b"X")


def test_tampered_approve_still_writes_zero(tmp_path: Path) -> None:
    store, _work, _pub, pmc_id = plant_and_extract(tmp_path / "live")
    try:
        fact_id = probe_node_id(store)
        _tamper(store, pmc_id)
        with pytest.raises(GroundingPreflightError):
            store.approve(fact_id, by="integrator", note="no")
        assert decision_count(store) == 0
        assert store.conn.execute(
            "SELECT status FROM nodes WHERE id = ?", (fact_id,),
        ).fetchone()[0] == "proposed"
    finally:
        store.close()


def test_tampered_reject_appends_pack_ineligible_decision(tmp_path: Path) -> None:
    store, _work, _pub, pmc_id = plant_and_extract(tmp_path / "live")
    try:
        fact_id = probe_node_id(store)
        _tamper(store, pmc_id)
        result = store.reject(fact_id, by="integrator", note="bad bytes")
        assert result["decision_receipt_ids"]
        decisions = list_review_decisions(store.conn, "node", fact_id)
        assert len(decisions) == 1
        assert decisions[0].pack_ineligible is True
        assert decisions[0].action.value == "reject"
        assert store.conn.execute(
            "SELECT status FROM nodes WHERE id = ?", (fact_id,),
        ).fetchone()[0] == "rejected"
    finally:
        store.close()


def test_tampered_quarantine_appends_pack_ineligible_decision(
    tmp_path: Path,
) -> None:
    store, _work, _pub, pmc_id = plant_and_extract(tmp_path / "live")
    try:
        fact_id = probe_node_id(store)
        _tamper(store, pmc_id)
        result = store.quarantine(fact_id, by="integrator", note="hold")
        assert result["decision_receipt_ids"]
        decision = list_review_decisions(store.conn, "node", fact_id)[0]
        assert decision.pack_ineligible is True
        assert decision.action.value == "quarantine"
        assert store.conn.execute(
            "SELECT status FROM nodes WHERE id = ?", (fact_id,),
        ).fetchone()[0] == "rejected"
    finally:
        store.close()


def test_cli_tampered_reject_prints_receipt(tmp_path: Path) -> None:
    from contextlib import redirect_stdout

    from ontologylab.main import main

    live = tmp_path / "live"
    store, _work, _pub, pmc_id = plant_and_extract(live)
    fact_id = probe_node_id(store)
    _tamper(store, pmc_id)
    store.close()
    buf = StringIO()
    with redirect_stdout(buf), pytest.raises(SystemExit) as exited:
        main([
            "reject", "--id", fact_id, "--by", "cli-actor",
            "--note", "cli reject", "--data-dir", str(live),
        ])
    assert exited.value.code == 0
    store = KGStore.open(live / "kg.sqlite")
    try:
        receipt = list_review_decisions(store.conn, "node", fact_id)[0].receipt_id
        assert f"decision_receipt_ids {receipt}" in buf.getvalue()
        assert list_review_decisions(store.conn, "node", fact_id)[0].pack_ineligible
    finally:
        store.close()


def test_http_tampered_reject_returns_receipt_approve_409(tmp_path: Path) -> None:
    from fastapi.testclient import TestClient

    from ontologylab.server.app import create_app

    live = tmp_path / "live"
    store, _work, _pub, pmc_id = plant_and_extract(live)
    fact_id = probe_node_id(store)
    _tamper(store, pmc_id)
    store.close()
    client = TestClient(create_app(data_dir=live))
    rejected = client.post(
        "/api/proposals/reject",
        json={"id": fact_id, "by": "http-actor", "note": "http reject"},
    )
    assert rejected.status_code == 200, rejected.text
    assert rejected.json()["decision_receipt_ids"]
    approved = client.post(
        "/api/proposals/approve",
        json={"id": fact_id, "by": "http-actor", "note": "no"},
    )
    assert approved.status_code == 409
    store = KGStore.open(live / "kg.sqlite")
    try:
        assert list_review_decisions(store.conn, "node", fact_id)[0].pack_ineligible
        assert store.conn.execute(
            "SELECT status FROM nodes WHERE id = ?", (fact_id,),
        ).fetchone()[0] == "rejected"
    finally:
        store.close()
