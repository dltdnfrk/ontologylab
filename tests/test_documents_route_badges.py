"""/api/documents says what text the store holds and whether it was extracted.

Plan todo 5 (W3+W4). Two additive fields per document:

* ``content_kind`` — the best ``document_observations.content_kind`` for the
  document by ``selection_policy.usable_full_text_rank``; ``metadata_only``
  when no Observation exists. A kind the policy does not know keeps its raw
  value and sorts after every known kind.
* ``extraction_status`` — the most recently updated ``extraction_runs.status``
  for the document under the ACTIVE schema version, else ``none``.

Neither is ``evidence_grade``: that is publication type (peer_reviewed,
preprint, ...) and must never decide whether a document can be extracted.
"""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path

import pytest

_ROOT = str(Path(__file__).resolve().parent.parent)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient  # noqa: E402

from ontologylab.authority_repo import insert_observation  # noqa: E402
from ontologylab.kgstore import KGStore  # noqa: E402
from ontologylab.paths import kg_db_path  # noqa: E402
from ontologylab.server.app import create_app  # noqa: E402


def _client(tmp_path: Path) -> tuple[TestClient, Path]:
    data_dir = tmp_path / "data"
    client = TestClient(create_app(data_dir=data_dir, packs_dir=tmp_path / "packs"))
    return client, data_dir


def _seed_document(store: KGStore, title: str) -> str:
    text = f"{title}: the RateLimiter feeds the OrderService."
    doc, created = store.insert_document(
        source_kind="upload",
        source_uri=f"file:///{title}.txt",
        title=title,
        raw_text=text,
        content_hash="sha256:" + hashlib.sha256(text.encode()).hexdigest(),
    )
    assert created
    return doc.id


def _observe(store: KGStore, doc_id: str, kind: str, key: str) -> None:
    insert_observation(
        store.conn, idempotency_key=key, representation_id=doc_id,
        content_kind=kind,
    )
    store.conn.commit()


def _run(
    store: KGStore,
    doc_id: str,
    *,
    schema_version_id: int,
    status: str,
    created_ts: float,
    updated_ts: float,
    engine: str = "mock",
) -> None:
    """One ``extraction_runs`` row, timestamps chosen by the test.

    ``chunk_plan_hash`` carries ``created_ts`` so two runs of one document
    never collide on the stream UNIQUE constraint.
    """
    content_hash = store.get_document(doc_id).content_hash
    store.conn.execute(
        "INSERT INTO extraction_runs (id, document_id, document_content_hash, "
        "schema_version_id, extractor_engine, extractor_model, prompt_version, "
        "decode_params, chunk_plan_hash, status, created_ts, updated_ts) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            f"run-{doc_id}-{engine}-{created_ts}", doc_id, content_hash,
            schema_version_id, engine, "", "extract-v2", "{}",
            f"plan-{created_ts}", status, created_ts, updated_ts,
        ),
    )
    store.conn.commit()


def _documents_by_title(client: TestClient) -> dict[str, dict]:
    resp = client.get("/api/documents")
    assert resp.status_code == 200, resp.text
    return {doc["title"]: doc for doc in resp.json()["documents"]}


def test_content_kind_is_the_best_observation_by_full_text_rank(tmp_path: Path) -> None:
    client, data_dir = _client(tmp_path)
    store = KGStore.open(kg_db_path(data_dir))
    try:
        fulltext = _seed_document(store, "fulltext-doc")
        abstract = _seed_document(store, "abstract-doc")
        _seed_document(store, "bare-doc")
        # The fulltext document also carries a later abstract Observation:
        # rank decides, not recency.
        _observe(store, fulltext, "fulltext", "k-full-full")
        _observe(store, fulltext, "abstract", "k-full-abs")
        _observe(store, abstract, "abstract", "k-abs")
    finally:
        store.close()

    docs = _documents_by_title(client)
    assert docs["fulltext-doc"]["content_kind"] == "fulltext"
    assert docs["abstract-doc"]["content_kind"] == "abstract"
    assert docs["bare-doc"]["content_kind"] == "metadata_only"
    # Publication type is a separate fact: every seed is `unknown` here
    # while their content kinds differ.
    assert {doc["evidence_grade"] for doc in docs.values()} == {"unknown"}


def test_unknown_content_kind_ranks_last_and_keeps_its_raw_value(tmp_path: Path) -> None:
    client, data_dir = _client(tmp_path)
    store = KGStore.open(kg_db_path(data_dir))
    try:
        only_unknown = _seed_document(store, "unknown-only")
        mixed = _seed_document(store, "unknown-and-metadata")
        _observe(store, only_unknown, "supplement", "k-u1")
        _observe(store, mixed, "supplement", "k-u2")
        _observe(store, mixed, "metadata_only", "k-u3")
    finally:
        store.close()

    docs = _documents_by_title(client)
    # Not collapsed to metadata_only: the store really holds this value.
    assert docs["unknown-only"]["content_kind"] == "supplement"
    # ...but it loses to every kind the policy knows, even the weakest.
    assert docs["unknown-and-metadata"]["content_kind"] == "metadata_only"


def test_extraction_status_is_the_latest_run_under_the_active_schema(tmp_path: Path) -> None:
    client, data_dir = _client(tmp_path)
    store = KGStore.open(kg_db_path(data_dir))
    try:
        active = int(store.active_schema_version()["id"])
        _seed_document(store, "never-run")
        done = _seed_document(store, "complete-run")
        stale = _seed_document(store, "complete-then-failed")
        _run(store, done, schema_version_id=active, status="complete",
             created_ts=100.0, updated_ts=110.0)
        # An older complete run must not outlive a newer failure.
        _run(store, stale, schema_version_id=active, status="complete",
             created_ts=100.0, updated_ts=110.0)
        _run(store, stale, schema_version_id=active, status="failed",
             created_ts=200.0, updated_ts=210.0, engine="claude")
    finally:
        store.close()

    docs = _documents_by_title(client)
    assert docs["never-run"]["extraction_status"] == "none"
    assert docs["complete-run"]["extraction_status"] == "complete"
    assert docs["complete-then-failed"]["extraction_status"] == "failed"


def test_extraction_status_ignores_runs_under_an_inactive_schema(tmp_path: Path) -> None:
    client, data_dir = _client(tmp_path)
    store = KGStore.open(kg_db_path(data_dir))
    try:
        old = int(store.active_schema_version()["id"])
        doc = _seed_document(store, "switched")
        _run(store, doc, schema_version_id=old, status="complete",
             created_ts=100.0, updated_ts=110.0)
    finally:
        store.close()
    assert _documents_by_title(client)["switched"]["extraction_status"] == "complete"

    installed = client.post("/api/schema", json={"preset": "biomedical"})
    assert installed.status_code == 200, installed.text
    # The old ontology's run says nothing about the one the queue uses now.
    assert _documents_by_title(client)["switched"]["extraction_status"] == "none"
