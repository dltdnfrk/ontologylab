"""Artifacts library (GAP-O3): documents and packs become consumable outputs.

Before this change the only way to consume stored knowledge was "review
then build a pack". Now every newly-created document registers a
source_doc artifact and every successful pack build registers a
pack_release artifact, and the API lists and fetches them so an Artifacts
screen can render Documents and Releases groups.

These tests pin the backend contract: registration on document create
(and not on dedup), pack_release registration from the build route, list
ordering and kind filtering, and 404/422 boundaries.
"""

from __future__ import annotations

import sqlite3
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier
from unittest.mock import patch

import pytest

_ROOT = str(Path(__file__).resolve().parent.parent)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

try:
    from fastapi.testclient import TestClient
except ImportError:  # pragma: no cover
    TestClient = None  # type: ignore[assignment]

if TestClient is None:
    pytest.skip("fastapi is not installed", allow_module_level=True)

from ontologylab.kgstore import KGStore  # noqa: E402
from ontologylab.models import ProposedEntity  # noqa: E402
from ontologylab.packbuilder import build_pack  # noqa: E402
from ontologylab.server.app import create_app  # noqa: E402


def _populate_pack_source(data_dir: Path, *, suffix: str) -> None:
    data_dir.mkdir()
    store = KGStore.open(data_dir / "kg.sqlite")
    doc, _ = store.insert_document(
        source_kind="upload",
        source_uri=f"file:///{suffix}.txt",
        title="T",
        raw_text="Alpha beta",
        content_hash=f"art-{suffix}",
    )
    store.insert_proposed(
        [
            ProposedEntity(
                id=f"n_{suffix}",
                entity_type="Component",
                name="ApiGateway",
            )
        ],
        [],
        source_doc_id=doc.id,
        extractor_engine="mock",
    )
    store.approve(f"n_{suffix}", by="tester")
    store.close()


def _store(tmp_path: Path) -> KGStore:
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    return KGStore.open(data_dir / "kg.sqlite")


def test_new_document_registers_a_source_doc_artifact(tmp_path: Path) -> None:
    store = _store(tmp_path)
    doc, created = store.insert_document(
        source_kind="upload",
        source_uri="file:///t.txt",
        title="Title A",
        raw_text="Alpha beta",
        content_hash="art-h1",
    )
    assert created is True

    rows = store.list_artifacts(kind="source_doc")
    assert len(rows) == 1
    art = rows[0]
    assert art["kind"] == "source_doc"
    assert art["source_doc_id"] == doc.id
    assert art["filename"] == "Title A"
    store.close()


def test_duplicate_document_does_not_register_twice(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.insert_document(
        source_kind="upload", source_uri="file:///t.txt", title="T",
        raw_text="same text", content_hash="art-dup",
    )
    store.insert_document(
        source_kind="upload", source_uri="file:///t.txt", title="T",
        raw_text="same text", content_hash="art-dup",
    )

    assert len(store.list_artifacts(kind="source_doc")) == 1
    store.close()


def test_artifact_roundtrip_newest_first_and_kind_filter(tmp_path: Path) -> None:
    store = _store(tmp_path)
    ids = [
        store.register_artifact(kind="other", filename=f"f{i}")
        for i in range(3)
    ]

    rows = store.list_artifacts()
    assert [r["id"] for r in rows] == ids[::-1], "newest first"
    assert store.get_artifact(ids[0])["filename"] == "f0"
    assert store.get_artifact("missing-id") is None
    assert store.list_artifacts(kind="pack_release") == []
    store.close()


def test_artifacts_api_lists_and_fetches(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    store = KGStore.open(data_dir / "kg.sqlite")
    doc, _ = store.insert_document(
        source_kind="upload", source_uri="file:///t.txt", title="Title A",
        raw_text="Alpha beta", content_hash="art-h1",
    )
    store.close()
    client = TestClient(create_app(data_dir=data_dir))

    body = client.get("/api/artifacts").json()
    assert body["count"] == 1
    art = body["artifacts"][0]
    assert art["kind"] == "source_doc"
    assert art["source_doc_id"] == doc.id
    assert art["title"] == "Title A"
    assert art["content_hash"] == "art-h1"

    one = client.get(f"/api/artifacts/{art['id']}")
    assert one.status_code == 200
    assert one.json()["source_uri"] == "file:///t.txt"


def test_artifacts_api_boundaries(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    store = KGStore.open(data_dir / "kg.sqlite")
    store.close()
    client = TestClient(create_app(data_dir=data_dir))

    empty = client.get("/api/artifacts")
    assert empty.status_code == 200
    assert empty.json()["artifacts"] == []

    assert client.get("/api/artifacts/nope").status_code == 404
    assert client.get("/api/artifacts?kind=bogus").status_code == 422
    assert client.get("/api/artifacts?limit=0").status_code == 422


def test_building_a_pack_registers_a_release_artifact(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    _populate_pack_source(data_dir, suffix="gw")
    client = TestClient(create_app(data_dir=data_dir))

    resp = client.post(
        "/api/packs/build",
        json={
            "name": "release-test",
            "allow_incomplete_extraction": True,
            "override_intent": "테스트용 부분 추출 승인",
        },
    )
    assert resp.status_code == 200, resp.text
    manifest = resp.json()["manifest"]

    rows = client.get("/api/artifacts?kind=pack_release").json()["artifacts"]
    assert len(rows) == 1
    assert rows[0]["kind"] == "pack_release"
    assert rows[0]["filename"] == manifest["pack_id"]


def test_explicit_data_dir_uses_an_app_scoped_default_packs_dir(
    tmp_path: Path,
) -> None:
    data_dir = tmp_path / "data"

    app = create_app(data_dir=data_dir)

    assert app.state.packs_dir == tmp_path / "packs"


def test_pack_registration_failure_removes_the_unregistered_pack(
    tmp_path: Path,
) -> None:
    data_dir = tmp_path / "data"
    packs_dir = tmp_path / "packs"
    _populate_pack_source(data_dir, suffix="register_failure")
    client = TestClient(create_app(data_dir=data_dir, packs_dir=packs_dir))

    with patch.object(
        KGStore,
        "register_artifact",
        side_effect=sqlite3.OperationalError("injected registration failure"),
    ):
        response = client.post(
            "/api/packs/build",
            json={
                "name": "registration-failure",
                "allow_incomplete_extraction": True,
                "override_intent": "테스트용 부분 추출 승인",
            },
        )

    assert response.status_code == 500
    assert list(packs_dir.iterdir()) == []


def test_simultaneous_pack_builds_allocate_distinct_release_ids(
    tmp_path: Path,
) -> None:
    data_dir = tmp_path / "data"
    packs_dir = tmp_path / "packs"
    _populate_pack_source(data_dir, suffix="rapid")
    barrier = Barrier(2)

    def build_one() -> str:
        barrier.wait(timeout=5)
        return build_pack(
            data_dir / "kg.sqlite",
            packs_dir,
            "rapid-release",
            allow_incomplete_extraction=True,
            incomplete_extraction_intent="테스트용 부분 추출 승인",
        ).pack_id

    pack_ids: list[str] = []
    with patch(
        "ontologylab.packbuilder.time.strftime",
        return_value="20260812-120000",
    ):
        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [executor.submit(build_one) for _ in range(2)]
            pack_ids = sorted(future.result(timeout=30) for future in futures)

    assert pack_ids == [
        "rapid-release-20260812-120000",
        "rapid-release-20260812-120000-2",
    ]


def test_the_ui_shows_a_hint_for_each_empty_group() -> None:
    """Text contract: a partially empty library must not render a bare heading.

    The reviewer flagged that a store with docs but no packs rendered the
    "릴리스" heading with nothing under it. Each group now shows its own
    empty hint unless both are empty (then the big empty-state card speaks).
    """
    from ontologylab.server.app import WEB_DIR

    script = (WEB_DIR / "app.js").read_text(encoding="utf-8")
    assert "수집한 문서가 없어요" in script
    assert "빌드한 팩이 없어요" in script
    assert "docs.length === 0 && hasAny" in script
    assert "releases.length === 0 && hasAny" in script
