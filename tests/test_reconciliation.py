"""Wave 2.1 Step 4 (4A-4C surfaces): CLI and HTTP reconciliation parity.

Both surfaces call one shared typed seam (ontologylab.reconciliation) so
list/inspect/attach/retract/compensate/resolve-collision return the same
typed state and conflict ids. No hard-delete endpoint exists.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from ontologylab.authority_repo import attach_identifier, create_work
from ontologylab.kgstore import KGStore
from ontologylab.reconciliation import list_state

CLI = shutil.which("ontologylab") or f"{sys.executable}"
CLI_ARGS = [] if shutil.which("ontologylab") else ["-m", "ontologylab.main"]


def _cli(data_dir: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [CLI, *CLI_ARGS, "reconcile", *args, "--data-dir", str(data_dir)],
        capture_output=True, text=True,
    )


@pytest.fixture()
def seeded(tmp_path: Path) -> Path:
    data_dir = tmp_path / "data"
    store = KGStore.open(data_dir / "kg.sqlite")
    create_work(store.conn, "w-a")
    create_work(store.conn, "w-b")
    store.conn.commit()
    store.close()
    return data_dir


def _client(tmp_path: Path, data_dir: Path):
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from ontologylab.server.app import create_app

    app = create_app(data_dir=data_dir, packs_dir=tmp_path / "packs")
    return TestClient(app)


def test_cli_attach_is_visible_through_http_inspect(seeded, tmp_path) -> None:
    res = _cli(
        seeded, "attach", "--work-id", "w-a", "--scheme", "doi",
        "--value", "10.1000/rec.a", "--key", "op-rec-a",
        "--actor", "curator", "--reason", "verified against Crossref",
    )
    assert res.returncode == 0, res.stderr
    identifier_id = re.search(r"identifier_id=(\S+)", res.stdout).group(1)
    decision_id = re.search(r"decision_id=(\S+)", res.stdout).group(1)

    with _client(tmp_path, seeded) as client:
        body = client.get("/api/reconcile/works/w-a").json()
        assert body["work"]["id"] == "w-a"
        assert body["identifiers"][0]["id"] == identifier_id
        assert any(d["id"] == decision_id for d in body["decisions"])


def test_duplicate_doi_attach_is_typed_on_both_surfaces(seeded, tmp_path) -> None:
    store = KGStore.open(seeded / "kg.sqlite")
    attach_identifier(
        store.conn, work_id="w-a", scheme="doi",
        normalized_value="10.1000/rec.dup", idempotency_key="op-dup",
    )
    store.conn.commit()
    store.close()

    with _client(tmp_path, seeded) as client:
        res = client.post(
            "/api/reconcile/attach",
            json={
                "work_id": "w-b", "scheme": "doi",
                "normalized_value": "10.1000/rec.dup",
                "idempotency_key": "op-dup-b", "actor": "curator",
                "reason": "conflicting claim",
            },
        )
        assert res.status_code == 409
        assert "IdentifierOwnedConflict" in res.json()["detail"]

    res = _cli(
        seeded, "attach", "--work-id", "w-b", "--scheme", "doi",
        "--value", "10.1000/rec.dup", "--key", "op-dup-cli",
        "--actor", "curator", "--reason", "conflicting claim",
    )
    assert res.returncode == 2
    assert "IdentifierOwnedConflict" in res.stderr


def test_retract_twice_is_typed_on_both_surfaces(seeded, tmp_path) -> None:
    store = KGStore.open(seeded / "kg.sqlite")
    result = attach_identifier(
        store.conn, work_id="w-a", scheme="doi",
        normalized_value="10.1000/rec.rt", idempotency_key="op-rt",
    )
    store.conn.commit()
    store.close()
    iid = result.identifier_id

    with _client(tmp_path, seeded) as client:
        ok = client.post(
            "/api/reconcile/retract",
            json={"identifier_id": iid, "actor": "curator",
                  "reason": "publisher withdrew"},
        )
        assert ok.status_code == 200
        again = client.post(
            "/api/reconcile/retract",
            json={"identifier_id": iid, "actor": "curator",
                  "reason": "second attempt"},
        )
        assert again.status_code == 409
        assert "IdentifierAlreadyRetracted" in again.json()["detail"]

    res = _cli(
        seeded, "retract", "--identifier-id", iid,
        "--actor", "curator", "--reason", "third attempt",
    )
    assert res.returncode == 2
    assert "IdentifierAlreadyRetracted" in res.stderr


def test_unknown_identifier_is_typed_not_found_on_both_surfaces(
    seeded, tmp_path,
) -> None:
    with _client(tmp_path, seeded) as client:
        res = client.post(
            "/api/reconcile/retract",
            json={"identifier_id": "wi-ghost", "actor": "curator",
                  "reason": "no such id"},
        )
        assert res.status_code == 404
    res = _cli(
        seeded, "retract", "--identifier-id", "wi-ghost",
        "--actor", "curator", "--reason", "no such id",
    )
    assert res.returncode == 2
    assert "UnknownIdentifier" in res.stderr


def test_empty_actor_is_a_client_error_on_both_surfaces(seeded, tmp_path) -> None:
    with _client(tmp_path, seeded) as client:
        res = client.post(
            "/api/reconcile/attach",
            json={
                "work_id": "w-a", "scheme": "doi",
                "normalized_value": "10.1000/rec.empty",
                "idempotency_key": "op-empty", "actor": "",
                "reason": "no actor",
            },
        )
        assert res.status_code == 400
    res = _cli(
        seeded, "attach", "--work-id", "w-a", "--scheme", "doi",
        "--value", "10.1000/rec.empty", "--key", "op-empty-cli",
        "--actor", "", "--reason", "no actor",
    )
    assert res.returncode == 2
    assert "DecisionInputInvalid" in res.stderr


def test_collision_resolution_ids_match_across_surfaces(seeded, tmp_path) -> None:
    res = _cli(
        seeded, "resolve-collision", "--scheme", "doi",
        "--value", "10.1000/rec.col", "--work-ids", "w-a", "w-b",
        "--actor", "migration-planner",
        "--reason", "two legacy rows derive the same DOI",
    )
    assert res.returncode == 0, res.stderr
    pending = set(re.findall(r"pend-[0-9a-f]+", res.stdout))
    assert len(pending) == 2

    with _client(tmp_path, seeded) as client:
        body = client.get("/api/reconcile").json()
        listed = {
            row["id"]
            for row in body["pending_identifiers"]
            if row["normalized_value"] == "10.1000/rec.col"
        }
        assert listed == pending
        assert all(row["status"] == "pending" for row in body["pending_identifiers"])


def test_no_hard_delete_endpoint_exists(seeded, tmp_path) -> None:
    with _client(tmp_path, seeded) as client:
        # A route that exists must refuse DELETE by method; a path with no
        # route at all cannot host a delete endpoint either (404).
        assert client.delete("/api/reconcile/works/w-a").status_code == 405
        assert client.delete(
            "/api/reconcile/identifiers/wi-x"
        ).status_code == 404


def test_list_state_is_a_pure_read(seeded) -> None:
    store = KGStore.open(seeded / "kg.sqlite", read_only=True)
    try:
        state = list_state(store.conn)
        assert state["works"] == 2
        assert state["pending_identifiers"] == []
    finally:
        store.close()
