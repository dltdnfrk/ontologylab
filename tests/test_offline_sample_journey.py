"""Offline onboarding journey through public collect/review/pack surfaces."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from ontologylab.main import main
from ontologylab.pack_verifier import verify_pack
from ontologylab.server.app import create_app


def test_sample_mock_review_pack_verifies_without_credentials(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Given a fresh install with no credentials and egress disabled
    data_dir = tmp_path / "data"
    packs_dir = tmp_path / "packs"
    monkeypatch.setenv("ONTOLOGYLAB_OFFLINE", "1")
    client = TestClient(create_app(data_dir=data_dir, packs_dir=packs_dir))

    # When the bundled sample is collected and extracted by the offline mock
    collected = client.post("/api/collect/sample")
    assert collected.status_code == 200
    assert collected.json()["ok"] is True
    with pytest.raises(SystemExit) as extraction:
        main([
            "extract",
            "--engine",
            "mock",
            "--data-dir",
            str(data_dir),
        ])
    assert extraction.value.code == 0

    # And every proposed item is explicitly reviewed by the local operator
    proposals = client.get("/api/proposals").json()["items"]
    assert proposals
    for proposal in proposals:
        approved = client.post(
            "/api/proposals/approve",
            json={"id": proposal["id"], "cascade": True},
        )
        if approved.status_code == 409:
            continue
        assert approved.status_code == 200, approved.text

    # And the reviewed pack is built through the dashboard API
    built = client.post("/api/packs/build", json={"name": "offline-sample"})
    assert built.status_code == 200
    assert built.json()["ok"] is True, built.text
    pack_id = built.json()["manifest"]["pack_id"]

    # Then the independent verifier accepts the exact emitted pack
    receipt = verify_pack(packs_dir / pack_id)
    assert receipt.pack_id == pack_id
    assert receipt.integrity_level
    assert receipt.pack_content_hash.startswith("sha256:")
