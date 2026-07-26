"""Manual retrieval bench: fts5 vs hybrid(hash) vs hybrid(MiniLM) — hit@5/MRR.

CI에서는 돌지 않는 수동 스크립트다 (모델 다운로드/시간 때문). 용도:
임베딩 백엔드를 바꿀 때 "체감"이 아니라 숫자로 비교하기.

    .venv/bin/python scripts/bench_retrieval.py            # hash만 (오프라인)
    .venv/bin/python scripts/bench_retrieval.py --real     # + all-MiniLM-L6-v2

gold 쿼리는 일부러 표면형이 어긋나게 짰다 — lexical이 놓치고 시맨틱이
잡아야 하는 케이스(패러프레이즈), 그 반대(정확 토큰), 두 신호가 협력해야
하는 케이스를 섞었다.
"""

from __future__ import annotations

import argparse
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ontologylab.embeddings import HashingEmbedder, get_embedder, st_available
from ontologylab.kgstore import KGStore
from ontologylab.models import ProposedEntity

# (name, entity_type) — 소프트웨어 도메인 미니 코퍼스
CORPUS = [
    ("RateLimiter", "Component"), ("OrderService", "Component"),
    ("SessionCache", "Component"), ("PaymentGateway", "Component"),
    ("KitchenDisplay", "Component"), ("MemberDatabase", "Component"),
    ("ReceiptPrinter", "Component"), ("CouponEngine", "Component"),
    ("PriorityQueue", "Component"), ("SalesReport", "Component"),
    ("LoadBalancer", "Component"), ("MessageBroker", "Component"),
    ("RetryPolicy", "Concept"), ("CircuitBreaker", "Concept"),
    ("Idempotency", "Concept"), ("EventSourcing", "Concept"),
    ("BackPressure", "Concept"), ("WriteAheadLog", "Concept"),
    ("Sharding", "Concept"), ("ConsistentHashing", "Concept"),
]

# (query, expected_name) — 정답이 top-5 안에 오면 hit
GOLD = [
    ("rate limiting requests", "RateLimiter"),
    ("throttle incoming traffic", "RateLimiter"),      # 패러프레이즈
    ("order service", "OrderService"),                 # 정확 토큰
    ("cache user sessions", "SessionCache"),
    ("process card payments", "PaymentGateway"),
    ("show orders to cooks", "KitchenDisplay"),        # 시맨틱 온리
    ("customer records storage", "MemberDatabase"),
    ("print the receipt", "ReceiptPrinter"),
    ("discount codes", "CouponEngine"),                # 시맨틱 온리
    ("job ordering by priority", "PriorityQueue"),
    ("monthly revenue summary", "SalesReport"),        # 시맨틱 온리
    ("distribute traffic across servers", "LoadBalancer"),
    ("publish subscribe messaging", "MessageBroker"),
    ("retry failed calls", "RetryPolicy"),
    ("stop cascading failures", "CircuitBreaker"),     # 시맨틱 온리
    ("exactly once semantics", "Idempotency"),         # 시맨틱 온리
    ("append only event log", "EventSourcing"),
    ("slow down fast producers", "BackPressure"),      # 시맨틱 온리
    ("wal durability", "WriteAheadLog"),
    ("split data across nodes", "Sharding"),
]

TOP_K = 5


def build_store(tmp: Path, embedder) -> KGStore:
    store = KGStore.open(tmp / f"bench-{embedder.name().replace('/', '_')}.sqlite")
    doc, _ = store.insert_document(
        source_kind="upload", source_uri="bench://corpus", title="bench",
        raw_text=" ".join(n for n, _ in CORPUS), content_hash=f"bench-{embedder.name()}",
    )
    store.insert_proposed(
        [ProposedEntity(id=f"n{i}", entity_type=t, name=n)
         for i, (n, t) in enumerate(CORPUS)],
        [], source_doc_id=doc.id, extractor_engine="mock",
    )
    store.bulk_approve()
    store.embed_nodes(embedder)
    return store


def evaluate(label: str, search_fn) -> None:
    hits, rr_sum = 0, 0.0
    for query, expected in GOLD:
        names = [r["name"] for r in search_fn(query)][:TOP_K]
        if expected in names:
            hits += 1
            rr_sum += 1.0 / (names.index(expected) + 1)
    n = len(GOLD)
    print(f"{label:<28} hit@{TOP_K}: {hits}/{n} ({hits / n:.0%})   "
          f"MRR: {rr_sum / n:.3f}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--real", action="store_true",
                        help="all-MiniLM-L6-v2도 벤치 (sentence-transformers 필요)")
    args = parser.parse_args()

    embedders = [HashingEmbedder()]
    if args.real:
        if not st_available():
            print("sentence-transformers 미설치 — pip install 'ontologylab[embed]'",
                  file=sys.stderr)
            return 2
        embedders.append(get_embedder("sentence-transformers/all-MiniLM-L6-v2"))

    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        first = build_store(tmp, embedders[0])
        try:
            evaluate("fts5 (lexical only)",
                     lambda q: first.semantic_search(q, top_k=TOP_K))
        finally:
            pass
        for emb in embedders:
            store = first if emb is embedders[0] else build_store(tmp, emb)
            try:
                evaluate(f"hybrid rrf ({emb.name().split('/')[-1]})",
                         lambda q, s=store, e=emb: s.hybrid_search(q, e, top_k=TOP_K))
            finally:
                store.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
