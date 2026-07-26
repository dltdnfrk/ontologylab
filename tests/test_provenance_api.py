"""Why the graph believes one node or edge.

Every field assembled here has been stored since the first schema —
extractor engine and model, prompt version, source document and span, who
approved it and when — and none of it left the database. The review screen
showed the evidence excerpt and nothing more, so the question this tool is
built around could only be answered by opening sqlite.

Returned as one record on purpose: a lineage split across three requests
is a lineage nobody reads.
"""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

from ontologylab import paths
from ontologylab.kgstore import KGStore, KGStoreError, UnknownItem
from ontologylab.models import ProposedEntity, ProposedRelation, SourceSpan
from ontologylab.server import routes
from ontologylab.server.app import create_app

TEXT = (
    "The PaymentGateway validates cards through the FraudDetector. "
    "The FraudDetector reports to the RiskEngine."
)


def _seed(tmp_path, *, engine="claude", model="haiku"):
    store = KGStore.open(paths.kg_db_path(tmp_path / "data"))
    doc, _ = store.insert_document(
        source_kind="paper_api",
        source_uri="https://doi.org/10.1/a",
        title="A study of gateways",
        raw_text=TEXT,
        content_hash="sha256:" + "d" * 64,
    )
    src = ProposedEntity(
        id=uuid.uuid4().hex, name="PaymentGateway", entity_type="Component",
        confidence=0.83, source_span=SourceSpan(start=4, end=18),
    )
    dst = ProposedEntity(
        id=uuid.uuid4().hex, name="FraudDetector", entity_type="Component",
        confidence=0.77, source_span=SourceSpan(start=44, end=57),
    )
    rel = ProposedRelation(
        id=uuid.uuid4().hex, relation_type="part_of",
        src_entity_id=src.id, dst_entity_id=dst.id,
        confidence=0.61, source_span=SourceSpan(start=4, end=57),
    )
    store.insert_proposed(
        [src, dst], [rel],
        source_doc_id=doc.id,
        extractor_engine=engine,
        extractor_model=model,
        prompt_version="extract-v1",
    )
    return store, doc


def _a_node(store):
    return store.conn.execute(
        "SELECT id FROM nodes WHERE name = 'PaymentGateway'"
    ).fetchone()["id"]


def _an_edge(store):
    return store.conn.execute("SELECT id FROM edges LIMIT 1").fetchone()["id"]


# --------------------------------------------------------------------------
# What one record has to carry
# --------------------------------------------------------------------------


def test_a_node_carries_the_whole_chain(tmp_path) -> None:
    """Engine, prompt, document, span, excerpt — the answer to "why?"."""
    store, doc = _seed(tmp_path)
    try:
        record = store.provenance("node", _a_node(store))
    finally:
        store.close()

    assert record["extraction"]["engine"] == "claude"
    assert record["extraction"]["model"] == "haiku"
    assert record["extraction"]["prompt_version"] == "extract-v1"
    assert record["extraction"]["created_ts"]
    assert record["document"]["id"] == doc.id
    assert record["document"]["title"] == "A study of gateways"
    assert record["document"]["source_uri"] == "https://doi.org/10.1/a"
    assert record["source_span"] == {"start": 4, "end": 18}
    assert "PaymentGateway" in record["excerpt"]


def test_an_edge_carries_it_too(tmp_path) -> None:
    """Relations are extracted claims exactly as much as entities are."""
    store, _doc = _seed(tmp_path)
    try:
        record = store.provenance("edge", _an_edge(store))
    finally:
        store.close()

    assert record["kind"] == "edge"
    assert record["label"] == "part_of"
    assert record["extraction"]["engine"] == "claude"
    assert record["document"] is not None


def test_an_unreviewed_item_says_so_rather_than_inventing_an_approver(
    tmp_path,
) -> None:
    store, _doc = _seed(tmp_path)
    try:
        record = store.provenance("node", _a_node(store))
    finally:
        store.close()

    assert record["status"] == "proposed"
    assert record["review"]["verified_by"] is None
    assert record["review"]["verified_ts"] is None


def test_approval_is_recorded_with_who_and_when(tmp_path) -> None:
    """The one event in this system that turns a proposal into knowledge."""
    store, _doc = _seed(tmp_path)
    try:
        node_id = _a_node(store)
        store.approve(node_id, by="hyunjun", note="확인함")
        record = store.provenance("node", node_id)
    finally:
        store.close()

    assert record["status"] == "verified"
    assert record["review"]["verified_by"] == "hyunjun"
    assert record["review"]["verified_ts"]
    assert record["review"]["note"] == "확인함"


def test_the_critic_score_is_carried_but_kept_separate(tmp_path) -> None:
    """Advisory, and structurally separate from the lineage.

    The critic never approved anything; its score belongs to the queue's
    ordering, not to the chain of custody. Nesting it under its own key is
    what keeps a reader from mistaking it for part of the provenance.
    """
    store, _doc = _seed(tmp_path)
    try:
        node_id = _a_node(store)
        store.record_critic_review(
            "node", node_id, engine="mock", model=None,
            prompt_version="critic-v1", score=0.42, rationale="근거가 약함",
        )
        record = store.provenance("node", node_id)
    finally:
        store.close()

    assert record["critic"]["score"] == pytest.approx(0.42)
    assert record["critic"]["engine"] == "mock"
    assert "critic" not in record["extraction"]
    assert "critic" not in record["review"]


def test_no_critic_run_is_none_not_a_zero(tmp_path) -> None:
    """0.0 would read as "the critic judged this worthless"."""
    store, _doc = _seed(tmp_path)
    try:
        record = store.provenance("node", _a_node(store))
    finally:
        store.close()

    assert record["critic"] is None


# --------------------------------------------------------------------------
# Refusals
# --------------------------------------------------------------------------


def test_an_unknown_id_is_refused(tmp_path) -> None:
    store, _doc = _seed(tmp_path)
    try:
        with pytest.raises(UnknownItem):
            store.provenance("node", "no-such-id")
    finally:
        store.close()


@pytest.mark.parametrize("kind", ["nodes", "NODE", "document", "", "../nodes"])
def test_only_node_and_edge_are_accepted(tmp_path, kind) -> None:
    """`kind` selects a table name. It is a closed set, not a string."""
    store, _doc = _seed(tmp_path)
    try:
        with pytest.raises(KGStoreError):
            store.provenance(kind, "any")
    finally:
        store.close()


# --------------------------------------------------------------------------
# Through the endpoint the review panel calls
# --------------------------------------------------------------------------


def _client(tmp_path) -> TestClient:
    data_dir = tmp_path / "data"
    routes.attach_data_dir(data_dir)
    return TestClient(create_app(data_dir=data_dir))


def test_the_endpoint_returns_the_record(tmp_path) -> None:
    store, _doc = _seed(tmp_path)
    node_id = _a_node(store)
    store.close()
    client = _client(tmp_path)

    body = client.get(f"/api/provenance/node/{node_id}").json()

    assert body["extraction"]["engine"] == "claude"
    assert body["document"]["title"] == "A study of gateways"


def test_an_unknown_item_is_a_404(tmp_path) -> None:
    _seed(tmp_path)[0].close()
    client = _client(tmp_path)

    assert client.get("/api/provenance/node/nope").status_code == 404


def test_a_bad_kind_is_a_400_not_a_500(tmp_path) -> None:
    """It is a client mistake, and the panel shows the detail inline."""
    _seed(tmp_path)[0].close()
    client = _client(tmp_path)

    assert client.get("/api/provenance/documents/x").status_code == 400
