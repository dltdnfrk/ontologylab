"""Wave 2.1 Step 6 (6A surfaces): CLI / HTTP / queue / sample seam.

CLI, internal HTTP, queue mode, and sample collect all call
ontologylab.ingestion_service through ontologylab.ingestion_surfaces so
receipts and conflict ids stay identical. Partial failure cannot claim
full success; the sample path cannot insert around the service.
"""

from __future__ import annotations

import io
import json
import sqlite3
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from typing import Any

import pytest

from ontologylab.ingestion_surfaces import collect_sample, run_ingest
from ontologylab.kgstore import KGStore
from ontologylab.main import main
from ontologylab.paths import kg_db_path


def _item(
    *,
    operation: str = "op-1",
    doi: str = "10.1000/surface.one",
    work_id: str | None = None,
    representation_id: str | None = None,
    scheme: str = "doi",
    normalized_value: str | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "idempotency_key": operation,
        "scheme": scheme,
        "normalized_value": doi if normalized_value is None else normalized_value,
        "source": "crossref",
        "evidence_grade": "A",
        "stage": "version_of_record",
        "content_kind": "abstract",
    }
    if work_id is not None:
        payload["work_id"] = work_id
    if representation_id is not None:
        payload["representation_id"] = representation_id
    elif representation_id is None and work_id is None:
        payload["representation"] = {
            "source_kind": "paper_api",
            "source_uri": f"https://doi.org/{payload['normalized_value']}",
            "title": "Authority write surface",
            "content_hash": f"sha256:{operation}",
            "raw_text_path": f"documents/{operation}/raw.txt",
        }
    return payload


def _count(conn: sqlite3.Connection, table: str) -> int:
    return int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])


def _cli(
    data_dir: Path, items: list[dict[str, Any]], *, mode: str = "write"
) -> tuple[int, dict[str, Any], str]:
    items_path = data_dir / f"ingest-items-{mode}.json"
    items_path.write_text(json.dumps(items), encoding="utf-8")
    stdout = io.StringIO()
    stderr = io.StringIO()
    with redirect_stdout(stdout), redirect_stderr(stderr):
        try:
            main(
                [
                    "ingest",
                    "--mode",
                    mode,
                    "--items",
                    str(items_path),
                    "--data-dir",
                    str(data_dir),
                ]
            )
            code = 0
        except SystemExit as exc:
            code = 0 if exc.code is None else int(exc.code)
    text = stdout.getvalue().strip()
    body = json.loads(text) if text else {}
    return code, body, stderr.getvalue()


def _client(tmp_path: Path, data_dir: Path):
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from ontologylab.server.app import create_app

    return TestClient(create_app(data_dir=data_dir, packs_dir=tmp_path / "packs"))


def test_cli_and_http_return_identical_created_receipt_ids(tmp_path: Path) -> None:
    data_dir = tmp_path / "created"
    data_dir.mkdir()
    item = _item()

    code, cli_body, _stderr = _cli(data_dir, [item])
    assert code == 0, _stderr
    cli_receipt = cli_body["receipts"][0]
    assert cli_receipt["status"] == "created"
    assert cli_body["ok"] is True

    with _client(tmp_path, data_dir) as client:
        response = client.post("/api/ingest", json={"items": [item], "mode": "write"})
        assert response.status_code == 200
        http_receipt = response.json()["receipts"][0]

    assert http_receipt["status"] == "duplicate"
    for field in (
        "work_id",
        "representation_id",
        "observation_id",
        "identifier_id",
    ):
        assert http_receipt[field] == cli_receipt[field]
        assert cli_receipt[field]


def test_conflict_ids_match_on_cli_and_http(tmp_path: Path) -> None:
    data_dir = tmp_path / "conflict"
    data_dir.mkdir()
    first = _item()
    code, created, _stderr = _cli(data_dir, [first])
    assert code == 0, _stderr
    work_id = created["receipts"][0]["work_id"]
    representation_id = created["receipts"][0]["representation_id"]
    second = _item(
        operation="op-2",
        doi="10.1000/surface.two",
        work_id=work_id,
        representation_id=representation_id,
    )

    cli_code, cli_body, cli_err = _cli(data_dir, [second])
    assert cli_code == 2
    assert "SecondDoiAttachConflict" in cli_err
    cli_conflict = cli_body["receipts"][0]["conflict"]
    assert cli_body["receipts"][0]["status"] == "conflict"
    assert cli_conflict["kind"] == "second_doi"
    assert cli_conflict["class_name"] == "SecondDoiAttachConflict"
    assert cli_conflict["work_id"] == work_id
    assert cli_conflict["existing_value"] == "10.1000/surface.one"
    assert cli_conflict["incoming_value"] == "10.1000/surface.two"

    with _client(tmp_path, data_dir) as client:
        response = client.post(
            "/api/ingest",
            json={
                "items": [
                    _item(
                        operation="op-3",
                        doi="10.1000/surface.two",
                        work_id=work_id,
                        representation_id=representation_id,
                    )
                ]
            },
        )
        assert response.status_code == 409
        http_body = response.json()
        http_conflict = http_body["receipts"][0]["conflict"]

    assert http_conflict["kind"] == cli_conflict["kind"]
    assert http_conflict["class_name"] == cli_conflict["class_name"]
    assert http_conflict["work_id"] == cli_conflict["work_id"]
    assert http_conflict["existing_work_id"] == cli_conflict["existing_work_id"]
    assert http_conflict["existing_value"] == cli_conflict["existing_value"]
    assert http_conflict["incoming_value"] == cli_conflict["incoming_value"]
    assert http_body["error_class"] == "SecondDoiAttachConflict"


def test_http_unknown_work_is_404_and_cli_exit_2(tmp_path: Path) -> None:
    data_dir = tmp_path / "missing"
    data_dir.mkdir()
    missing = _item(operation="op-missing", work_id="work-ghost")

    with _client(tmp_path, data_dir) as client:
        response = client.post("/api/ingest", json={"items": [missing]})
        assert response.status_code == 404
        body = response.json()
        assert body["receipts"][0]["status"] == "failed"
        assert body["error_class"] == "InvalidIngestItem"

    code, cli_body, cli_err = _cli(data_dir, [missing])
    assert code == 2
    assert "InvalidIngestItem" in cli_err
    assert cli_body["receipts"][0]["status"] == "failed"


def test_http_validation_is_400_and_cli_exit_2(tmp_path: Path) -> None:
    data_dir = tmp_path / "invalid"
    data_dir.mkdir()
    invalid = _item(
        operation="op-bad",
        scheme="unknown",
        normalized_value="",
    )

    with _client(tmp_path, data_dir) as client:
        response = client.post("/api/ingest", json={"items": [invalid]})
        assert response.status_code == 400
        assert response.json()["error_class"] == "InvalidIngestItem"

    code, _body, cli_err = _cli(data_dir, [invalid])
    assert code == 2
    assert "InvalidIngestItem" in cli_err


def test_delete_on_new_routes_returns_405(tmp_path: Path) -> None:
    data_dir = tmp_path / "delete"
    data_dir.mkdir()
    with _client(tmp_path, data_dir) as client:
        assert client.delete("/api/ingest").status_code == 405
        assert client.delete("/api/ingest/sample").status_code == 405


def test_queue_mode_returns_typed_queued_without_write(tmp_path: Path) -> None:
    data_dir = tmp_path / "queue"
    data_dir.mkdir()
    item = _item()

    store = KGStore.open(kg_db_path(data_dir))
    try:
        batch = run_ingest(store.conn, [item], mode="queue")
        assert batch.ok is True
        assert batch.http_status == 200
        assert [receipt["status"] for receipt in batch.receipts] == ["queued"]
        assert batch.receipts[0]["idempotency_key"] == "op-1"
        assert batch.receipts[0]["work_id"] is None
        for table in (
            "works",
            "documents",
            "work_identifiers",
            "document_observations",
            "identifier_assertions",
        ):
            assert _count(store.conn, table) == 0
    finally:
        store.close()

    code, cli_body, _err = _cli(data_dir, [item], mode="queue")
    assert code == 0
    assert cli_body["receipts"][0]["status"] == "queued"

    with _client(tmp_path, data_dir) as client:
        response = client.post("/api/ingest", json={"items": [item], "mode": "queue"})
        assert response.status_code == 200
        assert response.json()["receipts"][0]["status"] == "queued"

    store = KGStore.open(kg_db_path(data_dir), read_only=True)
    try:
        assert _count(store.conn, "works") == 0
        assert _count(store.conn, "document_observations") == 0
    finally:
        store.close()


def test_sample_collect_partial_failure_cannot_claim_full_success(
    tmp_path: Path,
) -> None:
    data_dir = tmp_path / "sample"
    data_dir.mkdir()
    good = _item(operation="op-good", doi="10.1000/sample.good")
    bad = _item(
        operation="op-bad",
        scheme="unknown",
        normalized_value="",
    )

    store = KGStore.open(kg_db_path(data_dir))
    try:
        batch = collect_sample(store.conn, [good, bad])
        store.conn.commit()
        assert [receipt["status"] for receipt in batch.receipts] == [
            "created",
            "failed",
        ]
        assert batch.ok is False
        assert batch.http_status == 200
        assert batch.receipts[1]["error_class"] == "InvalidIngestItem"
        assert _count(store.conn, "works") == 1
        assert _count(store.conn, "document_observations") == 1
    finally:
        store.close()

    with _client(tmp_path, data_dir) as client:
        response = client.post(
            "/api/ingest/sample",
            json={
                "items": [
                    _item(operation="op-http-good", doi="10.1000/sample.http"),
                    _item(
                        operation="op-http-bad",
                        scheme="unknown",
                        normalized_value="",
                    ),
                ]
            },
        )
        assert response.status_code == 200
        body = response.json()
        assert body["ok"] is False
        assert [receipt["status"] for receipt in body["receipts"]] == [
            "created",
            "failed",
        ]


def test_sample_path_does_not_bypass_service(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data_dir = tmp_path / "bypass"
    data_dir.mkdir()
    calls: list[int] = []

    import ontologylab.ingestion_surfaces as surfaces

    real = surfaces.ingest_work_items

    def wrapped(conn: sqlite3.Connection, items: Any, **kwargs: Any) -> Any:
        materialized = list(items)
        calls.append(len(materialized))
        return real(conn, materialized, **kwargs)

    monkeypatch.setattr(surfaces, "ingest_work_items", wrapped)

    store = KGStore.open(kg_db_path(data_dir))
    try:
        batch = collect_sample(store.conn, [_item(operation="op-sample")])
        store.conn.commit()
        assert calls == [1]
        assert batch.receipts[0]["status"] == "created"
        assert _count(store.conn, "work_identifiers") == 1
        assert _count(store.conn, "document_observations") == 1
        assert _count(store.conn, "identifier_assertions") == 1
    finally:
        store.close()
