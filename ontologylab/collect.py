"""Acquire orchestration shared by CLI collect and POST /api/collect."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, assert_never
from urllib.error import URLError
from xml.etree.ElementTree import ParseError

from ontologylab import paths
from ontologylab.connectors.allowlist import (
    NotAllowlisted,
    check_collect_file,
    check_paper_query,
    check_url,
)
from ontologylab.connectors.base import RawDocument
from ontologylab.connectors.paper_api import (
    MissingSourceKey,
    PaperApiConnector,
    ResponseTooLarge,
    UnsupportedPaperSource,
    check_source_implemented,
    redact_keys,
)
from ontologylab.connectors.web_crawl import WebCrawlConnector
from ontologylab.ingestion import (
    IdentityConflict,
    IngestBatchBoundError,
    IngestedDocument,
    IngestFailure,
    ingest_onboarding_sample,
    ingest_raw_documents_and_finalize,
)
from ontologylab.kgstore import KGStore
from ontologylab.provenance import Provenance

CollectErrorKind = Literal[
    "rejected",
    "unsupported",
    "offline",
    "unconfigured",
    "too_large",
    "fetch_failed",
    "failed",
]

SAMPLE_DOC_TITLE = "샘플 — 우리 가게 주문 시스템"
SAMPLE_DOC_TEXT = """\
# 우리 가게 주문 시스템 이야기

손님이 주문하면 OrderApp 이 주문을 받아서 KitchenDisplay 로 전달해요.
KitchenDisplay 는 조리 순서를 정하려고 PriorityQueue 를 사용해요.
결제는 PaymentGateway 가 처리하고, 영수증은 ReceiptPrinter 가 출력해요.
단골 관리는 MemberDatabase 가 담당하고, OrderApp 은 주문 내역을
MemberDatabase 에 기록해요. 쿠폰 발급은 CouponEngine 이 맡는데,
CouponEngine 은 MemberDatabase 의 방문 기록을 참고해요.
매출 집계는 SalesReport 가 매일 밤 정리해요.
"""


@dataclass(frozen=True, slots=True)
class CollectInputs:
    urls: tuple[str, ...]
    files: tuple[str, ...]
    paper_queries: tuple[str, ...]
    paper_source: str
    limit: int
    data_dir: Path


@dataclass(frozen=True, slots=True)
class CollectOutcome:
    ok: bool
    error_kind: CollectErrorKind | None = None
    detail: str | None = None
    documents: int = 0
    created: int = 0
    duplicates: int = 0
    failures: tuple[IngestFailure, ...] = ()
    conflicts: tuple[IdentityConflict, ...] = ()
    entries: tuple[IngestedDocument, ...] = ()


def _fail(kind: CollectErrorKind, detail: str) -> CollectOutcome:
    return CollectOutcome(ok=False, error_kind=kind, detail=detail)


def _run_connector(
    connector: WebCrawlConnector | PaperApiConnector,
    spec: dict[str, Any],
    provenance: Provenance,
    data_dir: Path,
) -> list[RawDocument] | CollectOutcome:
    try:
        return asyncio.run(connector.fetch(spec))
    except (
        NotAllowlisted,
        UnsupportedPaperSource,
        MissingSourceKey,
        ResponseTooLarge,
        URLError,
        ParseError,
        ValueError,
        OSError,
    ) as exc:
        detail = redact_keys(str(exc), data_dir)
        match exc:
            case NotAllowlisted():
                provenance.log("collect.rejected", {"error": detail})
                return _fail("rejected", detail)
            case UnsupportedPaperSource():
                provenance.log("collect.unsupported", {"error": detail})
                return _fail("unsupported", detail)
            case MissingSourceKey():
                provenance.log("collect.unconfigured", {"error": detail})
                return _fail("unconfigured", detail)
            case ResponseTooLarge():
                provenance.log("collect.too_large", {"error": detail})
                return _fail("too_large", detail)
            case URLError() | ParseError():
                provenance.log("collect.fetch_failed", {"error": detail})
                return _fail("fetch_failed", detail)
            case ValueError() | OSError():
                provenance.log("collect.failed", {"error": detail})
                return _fail("failed", detail)
            case unreachable:
                assert_never(unreachable)


def collect_documents(
    inputs: CollectInputs,
    *,
    provenance: Provenance,
) -> CollectOutcome:
    if not (inputs.urls or inputs.files or inputs.paper_queries):
        detail = (
            "nothing to collect: pass urls, files, and/or paper_queries"
        )
        provenance.log("collect.rejected", {"error": detail})
        return _fail("rejected", detail)

    resolved_files: list[Path] = []
    try:
        for url in inputs.urls:
            check_url(url)
        for file_arg in inputs.files:
            resolved_files.append(check_collect_file(file_arg, inputs.data_dir))
        for paper_query in inputs.paper_queries:
            check_paper_query(inputs.paper_source, paper_query)
            check_source_implemented(inputs.paper_source)
    except NotAllowlisted as exc:
        provenance.log("collect.rejected", {"error": str(exc)})
        return _fail("rejected", str(exc))
    except UnsupportedPaperSource as exc:
        provenance.log("collect.unsupported", {"error": str(exc)})
        return _fail("unsupported", str(exc))

    # Allowlist first so a boundary violation is logged even while offline.
    if (inputs.urls or inputs.paper_queries) and paths.offline_mode():
        detail = (
            "offline mode (ONTOLOGYLAB_OFFLINE) blocks network collection; "
            "unset it to fetch, or collect local files instead"
        )
        provenance.log("collect.offline", {"error": detail})
        return _fail("offline", detail)

    raw_docs: list[RawDocument] = []
    if inputs.urls:
        fetched = _run_connector(
            WebCrawlConnector(),
            {"urls": list(inputs.urls)},
            provenance,
            inputs.data_dir,
        )
        match fetched:
            case CollectOutcome() as outcome:
                return outcome
            case list() as docs:
                raw_docs.extend(docs)
            case unreachable:
                assert_never(unreachable)
    for paper_query in inputs.paper_queries:
        fetched = _run_connector(
            PaperApiConnector(),
            {
                "source": inputs.paper_source,
                "query": paper_query,
                "limit": inputs.limit,
                "data_dir": inputs.data_dir,
            },
            provenance,
            inputs.data_dir,
        )
        match fetched:
            case CollectOutcome() as outcome:
                return outcome
            case list() as docs:
                raw_docs.extend(docs)
            case unreachable:
                assert_never(unreachable)
    for path in resolved_files:
        try:
            raw_text = path.read_text(encoding="utf-8")
        except (OSError, ValueError) as exc:
            provenance.log("collect.fetch_failed", {"error": str(exc)})
            return _fail(
                "fetch_failed",
                f"could not read '{path.name}' ({type(exc).__name__})",
            )
        raw_docs.append(
            RawDocument(
                source_kind="upload",
                source_uri=path.resolve().as_uri(),
                title=path.stem,
                raw_text=raw_text,
            )
        )

    if not raw_docs:
        provenance.log("collect.end", {"documents": 0, "created": 0})
        return CollectOutcome(ok=True)

    store = KGStore.open(paths.kg_db_path(inputs.data_dir))
    try:
        result = ingest_raw_documents_and_finalize(store, raw_docs, provenance)
    except IngestBatchBoundError:
        provenance.log("collect.rejected", {"error": "batch_limit"})
        return _fail("rejected", "batch exceeds 100 documents")
    except Exception:  # noqa: BLE001
        provenance.log("collect.failed", {"error": "internal_error"})
        return _fail("failed", "internal_error")
    finally:
        store.close()
    ok = result.document_count > 0 or not result.failures
    return CollectOutcome(
        ok=ok,
        error_kind=None if ok else "failed",
        detail=None if ok else "internal_error",
        documents=result.document_count,
        created=result.created_count,
        duplicates=result.duplicate_count,
        failures=result.failures,
        conflicts=result.conflicts,
        entries=result.entries,
    )


def collect_onboarding_sample(store: KGStore) -> dict[str, Any]:
    return ingest_onboarding_sample(
        store, title=SAMPLE_DOC_TITLE, text=SAMPLE_DOC_TEXT
    )
