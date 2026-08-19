"""KG store invariants: entity resolution, the human gate, read-only packs."""

import sqlite3
from pathlib import Path

import pytest

from ontologylab.kgstore import (
    EndpointNotVerified,
    InvalidTransition,
    KGStore,
    KGStoreError,
    normalize_name,
)
from tests.conftest import insert, make_entity, make_relation


def test_open_tolerates_wal_disappearing_before_permissions(
    tmp_path, monkeypatch
) -> None:
    db_path = tmp_path / "kg.sqlite"
    wal_path = tmp_path / "kg.sqlite-wal"
    original_glob = Path.glob
    original_chmod = Path.chmod

    def racing_glob(path: Path, pattern: str):
        if path == tmp_path and pattern == "kg.sqlite-*":
            wal_path.touch()
            return iter((wal_path,))
        return original_glob(path, pattern)

    def racing_chmod(
        path: Path, mode: int, *, follow_symlinks: bool = True
    ) -> None:
        if path == wal_path:
            wal_path.unlink()
            raise FileNotFoundError(wal_path)
        original_chmod(path, mode, follow_symlinks=follow_symlinks)

    monkeypatch.setattr(Path, "glob", racing_glob)
    monkeypatch.setattr(Path, "chmod", racing_chmod)

    store = KGStore.open(db_path)
    store.close()


def test_normalize_name_folds_case_space_punct():
    assert normalize_name("Rate Limiter") == normalize_name("rate-limiter")
    assert normalize_name("RateLimiter") == normalize_name("Rate Limiter".replace(" ", ""))
    assert normalize_name("A") != normalize_name("B")


# ---------------------------------------------------------------------------
# entity resolution
# ---------------------------------------------------------------------------


def test_same_normalized_name_merges_across_inserts(store, doc):
    stats1 = insert(store, doc, [make_entity("RateLimiter")])
    assert stats1["nodes_new"] == 1
    stats2 = insert(store, doc, [make_entity("rate limiter")])
    assert stats2["nodes_new"] == 0
    assert stats2["nodes_merged"] == 1
    counts = store.counts()
    assert counts["nodes_proposed"] == 1


def test_same_name_different_type_stays_separate(store, doc):
    insert(store, doc, [make_entity("Caching", entity_type="Component")])
    stats = insert(store, doc, [make_entity("Caching", entity_type="Concept")])
    assert stats["nodes_new"] == 1
    assert store.counts()["nodes_proposed"] == 2


def test_relation_endpoints_bound_to_resolved_nodes(store, doc):
    a, b = make_entity("ApiGateway"), make_entity("RateLimiter")
    insert(store, doc, [a, b], [make_relation(a, b)])
    # re-insert the same surface forms with fresh chunk-minted ids
    a2, b2 = make_entity("ApiGateway"), make_entity("RateLimiter")
    stats = insert(store, doc, [a2, b2], [make_relation(a2, b2)])
    assert stats["nodes_new"] == 0
    assert stats["edges_new"] == 0  # duplicate edge merged, not duplicated
    counts = store.counts()
    assert counts["nodes_proposed"] == 2
    assert counts["edges_proposed"] == 1


# ---------------------------------------------------------------------------
# the human gate
# ---------------------------------------------------------------------------


def test_rows_are_born_proposed(store, doc):
    insert(store, doc, [make_entity("ApiGateway")])
    rows = store.pending_review()
    assert len(rows) == 1
    assert store.counts()["nodes_verified"] == 0


def test_approve_promotes_and_reject_keeps_audit_row(store, doc):
    a, b = make_entity("ApiGateway"), make_entity("RateLimiter")
    insert(store, doc, [a, b])
    (row_a, row_b) = store.pending_review()
    store.approve(row_a["id"], by="tester")
    store.reject(row_b["id"], by="tester", note="wrong extraction")
    counts = store.counts()
    assert counts["nodes_verified"] == 1
    assert counts["nodes_proposed"] == 0
    # rejected row still exists for audit
    (rejected,) = store.conn.execute(
        "SELECT status, verified_by FROM nodes WHERE id = ?", (row_b["id"],)
    ).fetchall()
    assert rejected["status"] == "rejected"
    assert rejected["verified_by"] == "tester"


def test_edge_approval_blocked_until_endpoints_verified(store, doc):
    a, b = make_entity("ApiGateway"), make_entity("RateLimiter")
    rel = make_relation(a, b)
    insert(store, doc, [a, b], [rel])
    edge_id = store.pending_review(kind="edge")[0]["id"]
    with pytest.raises(EndpointNotVerified):
        store.approve(edge_id)
    # cascade approves the endpoints together with the edge
    result = store.approve(edge_id, cascade=True)
    assert result["kind"] == "edge"
    counts = store.counts()
    assert counts["edges_verified"] == 1
    assert counts["nodes_verified"] == 2


def test_approve_and_reject_only_act_on_proposed_rows(store, doc):
    """A decided row is not silently re-decided in place — undo is reopen().

    _set_status used to be an unconditional UPDATE, so rejected → verified
    and verified → rejected were both one accidental call away.
    """
    a, b = make_entity("ApiGateway"), make_entity("RateLimiter")
    insert(store, doc, [a, b])
    (row_a, row_b) = store.pending_review()
    store.reject(row_b["id"], by="tester")

    with pytest.raises(InvalidTransition):
        store.approve(row_b["id"], by="tester")  # rejected → verified

    store.approve(row_a["id"], by="tester")
    with pytest.raises(InvalidTransition):
        store.reject(row_a["id"], by="tester")  # verified → rejected
    with pytest.raises(InvalidTransition):
        store.approve(row_a["id"], by="tester")  # verified → re-verified

    # The legal path is unchanged: reopen, then decide again.
    store.reopen(row_b["id"], by="tester")
    store.approve(row_b["id"], by="tester")
    assert store.counts()["nodes_verified"] == 2


def test_synthesized_endpoint_carries_a_review_visible_marker(store, doc):
    """An endpoint the parser minted for a relation (never observed in the
    text) must be marked where the reviewer can see it — not just counted
    in job stats. The marker rides properties, so the queue and entity
    panel both carry it."""
    ghost = make_entity("GhostEndpoint")
    ghost.synthesized = True
    insert(store, doc, [ghost])
    (row,) = store.pending_review()
    assert row["properties"].get("synthesized_endpoint") == "true"


def test_shared_alias_resolves_nothing_and_queues_merge(store, doc):
    """A shared alias is an identity question, not a coin flip: LIMIT 1 used
    to merge the mention into an arbitrary holder. Now the collision
    resolves to a new node and the pair lands in the merge queue."""
    a = make_entity("RateLimiter", aliases=["throttler"])
    b = make_entity("TokenBucket", aliases=["throttler"])
    insert(store, doc, [a, b])

    stats = insert(store, doc, [make_entity("Throttler")])
    assert stats["nodes_new"] == 1, "a shared alias must not resolve into either holder"
    assert stats["nodes_merged"] == 0

    pending = store.merge_candidates_pending()
    assert len(pending) == 1
    assert any("shared-alias" in r for r in pending[0]["reasons"])


def test_cascade_never_promotes_a_rejected_endpoint(store, doc):
    """cascade approves proposed endpoints — a REJECTED endpoint is a human
    decision the cascade must not override."""
    a, b = make_entity("ApiGateway"), make_entity("RateLimiter")
    rel = make_relation(a, b)
    insert(store, doc, [a, b], [rel])
    (row_b,) = [r for r in store.pending_review() if r["label"] == "RateLimiter"]
    store.reject(row_b["id"], by="tester")
    edge_id = store.pending_review(kind="edge")[0]["id"]
    with pytest.raises(InvalidTransition):
        store.approve(edge_id, cascade=True)
    assert store.counts()["nodes_verified"] == 0
    assert store.counts()["edges_verified"] == 0


def test_reopen_returns_a_decided_item_to_the_queue(store, doc):
    """승인·거부는 되돌릴 수 있어야 한다 — 키 하나 차이로 확정되던 결정."""
    a = make_entity("ApiGateway")
    insert(store, doc, [a])
    store.approve(a.id)
    assert store.counts()["nodes_verified"] == 1

    result = store.reopen(a.id)
    assert result["reopened_ids"] == [a.id]
    assert store.counts()["nodes_verified"] == 0
    assert store.counts()["nodes_proposed"] == 1
    # 검토 큐에 실제로 다시 나타난다
    assert a.id in {r["id"] for r in store.pending_review(kind="node")}

    # 거부한 것도 같은 방식으로 되돌아온다
    store.reject(a.id)
    store.reopen(a.id)
    assert store.counts()["nodes_proposed"] == 1


def test_reopen_is_idempotent(store, doc):
    """이미 큐에 있는 걸 또 되돌려도 벌주지 않는다 — undo 두 번은 흔한 실수."""
    a = make_entity("ApiGateway")
    insert(store, doc, [a])
    result = store.reopen(a.id)
    assert result["already_open"] is True
    assert result["reopened_ids"] == []


def test_reopen_refuses_to_strand_a_verified_edge(store, doc):
    """승인된 관계가 매달린 개념은 되돌릴 수 없다.

    approve()는 '승인된 관계의 양끝은 승인돼 있다'를 보장한다. 끝점만 조용히
    되돌리면 그 불변식이 아무도 모르게 깨진다.
    """
    a, b = make_entity("ApiGateway"), make_entity("RateLimiter")
    insert(store, doc, [a, b], [make_relation(a, b)])
    edge_id = store.pending_review(kind="edge")[0]["id"]
    store.approve(edge_id, cascade=True)          # 관계 + 양끝 함께 승인

    with pytest.raises(KGStoreError, match="verified edge"):
        store.reopen(a.id)
    assert store.counts()["nodes_verified"] == 2  # 아무것도 바뀌지 않았다

    # 관계는 딸린 것이 없으므로 언제나 되돌아온다
    store.reopen(edge_id)
    assert store.counts()["edges_verified"] == 0
    # 관계가 비켜났으니 이제 끝점도 되돌릴 수 있다
    store.reopen(a.id)
    assert store.counts()["nodes_verified"] == 1


def test_review_rows_carry_the_evidence_they_are_judged_on(store, doc):
    """검토 큐의 각 항목은 자신이 추출된 출처 문장을 함께 실어야 한다.

    크리틱 모델은 처음부터 이 발췌를 받아 판단해 왔는데(critic.py), 정작
    결정 권한을 가진 사람은 라벨과 숫자만 보고 있었다.
    """
    a, b = make_entity("ApiGateway"), make_entity("RateLimiter")
    insert(store, doc, [a, b], [make_relation(a, b)])

    node_row = store.pending_review(kind="node")[0]
    assert node_row["doc_title"] == "notes"
    assert node_row["source_span"] == {"start": 0, "end": len(node_row["label"])}
    # 발췌는 스팬을 >>> <<< 로 감싸 어디를 근거로 삼았는지 보여준다
    assert ">>>" in node_row["excerpt"] and "<<<" in node_row["excerpt"]

    # 관계 — 이전에는 근거를 볼 경로가 아예 없던 절반
    edge_row = store.pending_review(kind="edge")[0]
    assert edge_row["excerpt"], "관계도 근거를 실어야 한다"
    assert edge_row["doc_title"] == "notes"


def test_evidence_fails_open_when_source_text_is_gone(tmp_path, store, doc):
    """원문 파일이 사라져도 검토 큐는 살아 있어야 한다 — 발췌만 비운다."""
    insert(store, doc, [make_entity("ApiGateway")])
    (tmp_path / doc.raw_text_path).unlink()
    row = store.pending_review(kind="node")[0]
    assert row["excerpt"] == ""
    assert row["label"] == "ApiGateway"     # 나머지는 그대로


def test_edge_review_rows_name_their_endpoints(store, doc):
    """검토 큐의 관계 행은 hex id가 아니라 양끝 '이름'으로 읽혀야 한다.

    pending_review 뷰는 src/dst id를 이어붙일 수밖에 없어서, 사용자는
    "74116a11… -> 36d5bf4d…" 를 승인/거부하라는 요구를 받고 있었다.
    """
    a, b = make_entity("ApiGateway"), make_entity("RateLimiter")
    insert(store, doc, [a, b], [make_relation(a, b)])
    row = store.pending_review(kind="edge")[0]
    assert row["label"] == "ApiGateway → RateLimiter"
    assert row["src_label"] == "ApiGateway"
    assert row["dst_label"] == "RateLimiter"
    assert row["src_id"] == a.id and row["dst_id"] == b.id
    # 노드 행은 건드리지 않는다
    assert {r["label"] for r in store.pending_review(kind="node")} == {
        "ApiGateway",
        "RateLimiter",
    }


def test_edge_label_degrades_when_endpoint_missing(store, doc):
    """해석 안 되는 엔드포인트는 짧은 id로 물러난다 — 전체 hex로 돌아가지 않는다.

    외래키가 켜져 있어 정상 DB에서는 끊긴 엔드포인트가 생기지 않으므로
    (노드를 지우려 하면 IntegrityError), 방어 분기를 직접 호출해 확인한다.
    """
    a = make_entity("ApiGateway")
    insert(store, doc, [a])
    missing = "f" * 32
    rows = [
        {"kind": "edge", "id": "e1", "label": f"{a.id} -> {missing}"},
        {"kind": "node", "id": a.id, "label": "ApiGateway"},
    ]
    store._label_edge_endpoints(rows)
    assert rows[0]["src_label"] == "ApiGateway"
    assert rows[0]["dst_label"] == missing[:10]
    assert rows[0]["label"] == f"ApiGateway → {missing[:10]}"
    assert rows[1]["label"] == "ApiGateway"      # 노드 행은 그대로


def test_edge_label_pass_is_idempotent_and_skips_malformed(store, doc):
    """이미 이름이 박힌 행을 다시 돌려도 망가지지 않고, 형식이 다르면 건너뛴다."""
    a, b = make_entity("ApiGateway"), make_entity("RateLimiter")
    insert(store, doc, [a, b], [make_relation(a, b)])
    rows = store.pending_review(kind="edge")
    once = rows[0]["label"]
    store._label_edge_endpoints(rows)               # 두 번째 통과
    assert rows[0]["label"] == once

    odd = [{"kind": "edge", "id": "e9", "label": "구분자없음"}]
    store._label_edge_endpoints(odd)
    assert odd[0]["label"] == "구분자없음"
    assert "src_label" not in odd[0]


def test_edge_labels_resolve_on_read_only_store(tmp_path, store, doc):
    """읽기 전용(팩)에서도 이름 해석이 돌아야 한다 — SELECT만 쓰므로."""
    a, b = make_entity("ApiGateway"), make_entity("RateLimiter")
    insert(store, doc, [a, b], [make_relation(a, b)])
    store.close()
    ro = KGStore.open(tmp_path / "kg.sqlite", read_only=True)
    try:
        assert ro.pending_review(kind="edge")[0]["label"] == "ApiGateway → RateLimiter"
    finally:
        ro.close()


def test_bulk_approve_skips_edges_with_unverified_endpoints(store, doc):
    a, b = make_entity("HighConf", confidence=0.95), make_entity("LowConf", confidence=0.2)
    rel = make_relation(a, b, confidence=0.9)
    insert(store, doc, [a, b], [rel])
    report = store.bulk_approve(min_confidence=0.5)
    assert len(report["nodes_approved"]) == 1  # only HighConf
    assert report["edges_approved"] == []
    assert len(report["edges_skipped"]) == 1  # LowConf endpoint not verified


def test_unknown_item_errors(store):
    with pytest.raises(KGStoreError):
        store.approve("nonexistent")
    with pytest.raises(KGStoreError):
        store.reject("nonexistent")


# ---------------------------------------------------------------------------
# queries respect the verified-only default
# ---------------------------------------------------------------------------


def test_queries_hide_proposed_by_default(store, doc):
    a, b = make_entity("ApiGateway"), make_entity("RateLimiter")
    insert(store, doc, [a, b])
    # 승인 대상을 이름으로 특정한다 — pending_review()[0]는 같은 created_ts
    # 끼리의 순서에 기대지 않아야 한다(배치 삽입은 created_ts를 공유한다).
    store.approve(a.id)

    assert len(store.entity_lookup(name="ApiGateway")) == 1
    assert store.entity_lookup(name="RateLimiter") == []
    assert (
        len(store.entity_lookup(name="RateLimiter", include_proposed=True)) == 1
    )

    store.rebuild_fts()
    assert store.semantic_search("RateLimiter") == []
    assert len(store.semantic_search("RateLimiter", include_proposed=True)) == 1


# ---------------------------------------------------------------------------
# read-only mode
# ---------------------------------------------------------------------------


def test_read_only_store_refuses_writes(tmp_path, store, doc):
    insert(store, doc, [make_entity("ApiGateway")])
    store.close()
    ro = KGStore.open(tmp_path / "kg.sqlite", read_only=True)
    try:
        node_id = ro.pending_review()[0]["id"]
        with pytest.raises(KGStoreError):
            ro.approve(node_id)
        with pytest.raises(KGStoreError):
            ro.insert_document(
                source_kind="upload",
                source_uri="file:///x",
                title=None,
                raw_text="x",
                content_hash="sha256:x",
            )
    finally:
        ro.close()


def test_same_doi_with_changed_body_is_one_document(tmp_path):
    # Given: the same paper arrives once as an abstract and later as full text.
    store = KGStore.open(tmp_path / "kg.sqlite")
    first, first_created = store.insert_document(
        source_kind="paper_api",
        source_uri="https://doi.org/10.1000/example",
        title="Paper",
        raw_text="Abstract only.",
        content_hash="sha256:abstract",
        doi="10.1000/example",
    )

    # When: the second representation has different bytes but the same DOI.
    second, second_created = store.insert_document(
        source_kind="paper_api",
        source_uri="https://doi.org/10.1000/example",
        title="Paper",
        raw_text="Full text with substantially more evidence.",
        content_hash="sha256:fulltext",
        doi="10.1000/example",
    )

    # Then: DOI identity wins over representation bytes.
    assert first_created is True
    assert second_created is False
    assert second.id == first.id
    assert second.doi == "10.1000/example"
    assert len(store.list_documents()) == 1
    store.close()


def test_existing_store_gains_doi_identity(tmp_path):
    # Given: a database created before DOI persistence existed.
    path = tmp_path / "kg.sqlite"
    store = KGStore.open(path)
    store.close()
    conn = sqlite3.connect(path)
    conn.execute("DROP INDEX idx_documents_doi")
    conn.execute("ALTER TABLE documents DROP COLUMN doi")
    conn.commit()
    conn.close()

    # When: the current store opens and migrates it.
    migrated = KGStore.open(path)
    first, _ = migrated.insert_document(
        source_kind="paper_api",
        source_uri="https://doi.org/10.1000/legacy",
        title="Legacy",
        raw_text="Old abstract.",
        content_hash="sha256:legacy-a",
        doi="https://doi.org/10.1000/LEGACY",
    )
    duplicate, created = migrated.insert_document(
        source_kind="paper_api",
        source_uri="https://doi.org/10.1000/legacy",
        title="Legacy",
        raw_text="Changed body.",
        content_hash="sha256:legacy-b",
        doi="10.1000/legacy",
    )

    # Then: migration added normalized DOI identity before either write.
    assert created is False
    assert duplicate.id == first.id
    assert first.doi == "10.1000/legacy"
    migrated.close()
