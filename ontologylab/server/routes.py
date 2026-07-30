"""FastAPI API routes for the ontologylab local web layer.

Exposes /api/engines, /api/settings, /api/cost, /api/proposals
(list / approve / reject), and the M8 dashboard surface:
/api/documents, /api/collect, /api/extract, /api/jobs, /api/packs,
/api/mcp/status — everything needed to drive collect → extract →
review → build → serve status from the browser, no CLI required.
"""

from __future__ import annotations

import asyncio
import dataclasses
import json
import logging
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any, AsyncIterator, Optional
from urllib.error import URLError
from xml.etree.ElementTree import ParseError

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import StreamingResponse

from ontologylab import paths
from ontologylab.connectors.allowlist import (
    NotAllowlisted,
    check_collect_file,
    check_paper_query,
    check_url,
    loggable_collect_inputs,
)
from ontologylab.connectors.base import RawDocument
from ontologylab.connectors.paper_api import (
    DEFAULT_PAPER_SOURCE,
    PAPER_SOURCE_LABELS,
    CONNECTABLE_SOURCES,
    KEYED_SOURCES,
    SOURCE_ORDER,
    MissingSourceKey,
    ResponseTooLarge,
    PaperApiConnector,
    UnsupportedPaperSource,
    available_sources,
    check_source_implemented,
    resolve_source_key,
)
from ontologylab.connectors.resources import (
    ORGANISM,
    RESOURCE_LABELS,
    RESOURCE_ORDER,
)
from ontologylab.connectors.web_crawl import WebCrawlConnector
from ontologylab.kgstore import EndpointNotVerified, KGStore, KGStoreError, UnknownItem
from ontologylab.mcp_server import serve_args
from ontologylab.packbuilder import PackBuildError, build_pack, list_packs
from ontologylab.paths import default_data_dir, default_packs_dir, kg_db_path
from ontologylab.providers import (
    Provider,
    ProviderError,
    add_provider,
    get_provider,
    load_providers,
    remove_provider,
    resolve_api_key,
)
from ontologylab.chatstore import MAX_TURNS, ChatStore
from ontologylab.provenance import Provenance
from ontologylab.trace import Step
from ontologylab.keychain import (
    KeychainError,
    delete_key,
    keychain_available,
    read_key,
    write_key,
)
from ontologylab.sources import (
    Source,
    SourceError,
    add_source,
    get_source,
    load_sources,
    remove_source,
    source_public,
    validate_source,
)
from ontologylab.server import settings as settings_mod
from ontologylab.server.jobs import JobAlreadyRunning, JobRegistry
from ontologylab.server.schemas import (
    AnnotationDecision,
    ChatMessage,
    CollectRequest,
    CostSummary,
    CriticRunRequest,
    EngineInfo,
    ExtractRequest,
    JobStatus,
    MergeAction,
    MergeDismiss,
    MergeScanRequest,
    PackBuildRequest,
    ProposalAction,
    ProviderCreate,
    ProviderModel,
    ProviderTestResult,
    ResearchRequest,
    Settings,
    SourceCreate,
)

if TYPE_CHECKING:  # `Intent` is only ever a type here — importing it at
    from ontologylab.intent import Intent  # runtime would be a cycle.

_log = logging.getLogger(__name__)

router = APIRouter(prefix="/api")

# Bound once by app.create_app(); holds the data-dir Path for the working KG.
_data_dir: Path = default_data_dir()

# Bound once by app.create_app(); holds the packs output directory.
_packs_dir: Path = default_packs_dir()

# Bound once by app.create_app(); holds the extraction-job registry.
_jobs_registry: JobRegistry | None = None


def attach_data_dir(data_dir: Path) -> None:
    global _data_dir
    _data_dir = Path(data_dir)


def attach_packs_dir(packs_dir: Path) -> None:
    global _packs_dir
    _packs_dir = Path(packs_dir)


def attach_jobs_registry(registry: JobRegistry) -> None:
    global _jobs_registry
    _jobs_registry = registry


def _registry() -> JobRegistry:
    # create_app always attaches; the fallback keeps bare-router usage working.
    global _jobs_registry
    if _jobs_registry is None:
        _jobs_registry = JobRegistry(_data_dir)
    return _jobs_registry


def _open_store() -> KGStore:
    # Creates an empty store on first open, so the review UI boots cleanly
    # even before any collect job has run.
    return KGStore.open(kg_db_path(_data_dir))


# ---------------------------------------------------------------------------
# Engines / settings / cost
# ---------------------------------------------------------------------------


@router.get("/engines", response_model=list[EngineInfo])
def get_engines() -> list[EngineInfo]:
    return settings_mod.engines()


@router.get("/paper-sources")
def get_paper_sources() -> dict[str, Any]:
    """List the paper sources this build can actually fetch from.

    The browser renders its picker from this, so the option list cannot
    drift from the dispatch table the fetcher uses. `SOURCE_ORDER` is the
    declaration order in `paper_api._SOURCE_DISPATCH`, which is also the
    tie-break order, so the UI offers them in the order the system prefers.

    `available` says whether picking it would work right now: a publisher
    source with no key connected is implemented but not usable, and offering
    it as an ordinary choice would hand the user a guaranteed failure.
    """
    usable = set(available_sources(_data_dir))
    return {
        "sources": [
            {
                "id": source,
                "label": PAPER_SOURCE_LABELS.get(source, source),
                # `keyed` means "refuses without a key" — the picker
                # disables those. `connectable` is wider: OpenAlex and
                # Semantic Scholar work anonymously but share a rate-limited
                # pool, so they stay selectable while still being offered a
                # key on the settings screen.
                "keyed": source in KEYED_SOURCES,
                "connectable": source in CONNECTABLE_SOURCES,
                "key_present": bool(resolve_source_key(source, _data_dir)),
                "available": source in usable,
            }
            for source in SOURCE_ORDER
        ],
        "default": DEFAULT_PAPER_SOURCE,
    }


@router.get("/settings", response_model=Settings)
def get_settings() -> Settings:
    return settings_mod.load_settings(_data_dir)


@router.put("/settings", response_model=Settings)
def put_settings(new_settings: Settings) -> Settings:
    """Save settings, refusing a SearXNG address that could never be used.

    Validated here rather than at fetch time. Storing a public instance and
    reporting it thirty seconds into a research run — as one refused source
    among six — is a bad way to learn that the address was never going to
    work. The gate is the same one the fetch applies; this just moves the
    message to the moment the value is typed.
    """
    from ontologylab.connectors.allowlist import check_searxng_base_url

    if new_settings.searxng_url:
        try:
            check_searxng_base_url(new_settings.searxng_url)
        except NotAllowlisted as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    saved = settings_mod.save_settings(new_settings, _data_dir)
    # Takes effect now, not at the next restart. A setting that only
    # applies after a restart is one people conclude does not work.
    settings_mod.apply_to_environment(saved)
    return saved


@router.get("/cost", response_model=CostSummary)
def get_cost() -> CostSummary:
    # The active data dir, not the repository's — they differ on every
    # install started with `--data-dir`, which the launchd agent always does.
    return settings_mod.cost_summary(data_dir=_data_dir)


# ---------------------------------------------------------------------------
# Providers (configurable API model backends — registry only, keys stay in env)
# ---------------------------------------------------------------------------


def _provider_public(provider: Provider) -> ProviderModel:
    """Public projection of a Provider: env-var NAME + presence, never the key."""
    return ProviderModel(
        id=provider.id,
        kind=provider.kind,
        base_url=provider.base_url,
        api_key_env=provider.api_key_env,
        models=list(provider.models),
        label=provider.label,
        key_present=resolve_api_key(provider) is not None,
    )


@router.get("/providers")
def list_providers() -> dict[str, Any]:
    providers = [_provider_public(p) for p in load_providers(_data_dir)]
    return {"providers": providers}


@router.post("/providers")
def create_provider(body: ProviderCreate) -> dict[str, Any]:
    provider = Provider(
        id=body.id,
        kind=body.kind,
        base_url=body.base_url,
        api_key_env=body.api_key_env,
        models=tuple(body.models or ()),
        label=body.label or "",
    )
    try:
        add_provider(_data_dir, provider)
    except ProviderError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True, "provider": _provider_public(provider)}


@router.delete("/providers/{provider_id}")
def delete_provider(provider_id: str) -> dict[str, Any]:
    removed = remove_provider(_data_dir, provider_id)
    return {"ok": True, "removed": removed}


@router.post("/providers/{provider_id}/test", response_model=ProviderTestResult)
async def test_provider(provider_id: str) -> ProviderTestResult:
    """One-shot ping via ApiEngine. Errors (incl. missing key) are returned as
    ``ok:false`` with a redacted message — the key is never leaked."""
    from ontologylab.engines import EngineError, get_engine

    provider = get_provider(_data_dir, provider_id)
    if provider is None:
        return ProviderTestResult(
            ok=False, error=f"등록되지 않은 프로바이더예요: {provider_id}"
        )
    if resolve_api_key(provider) is None:
        return ProviderTestResult(
            ok=False,
            error=(
                f"환경변수 {provider.api_key_env} 가 설정되지 않았어요. "
                "키를 넣고 서버를 다시 시작해주세요."
            ),
        )
    engine = get_engine(f"api:{provider_id}", data_dir=_data_dir)
    start = time.monotonic()
    try:
        text, _usage = await engine.generate(
            "ping — reply with the single word: pong"
        )
    except EngineError as exc:
        return ProviderTestResult(ok=False, error=str(exc))
    latency_ms = int((time.monotonic() - start) * 1000)
    return ProviderTestResult(ok=True, latency_ms=latency_ms, sample=text[:40])


# ---------------------------------------------------------------------------
# Proposals (HITL review)
# ---------------------------------------------------------------------------


@router.get("/review/triage")
def get_triage(alpha: float = Query(0.05, gt=0.0, lt=1.0)) -> dict[str, Any]:
    """The conformal triage line for the review queue, if history supports one.

    Read-only by construction: the threshold orders and badges the queue,
    it never approves. When there are not yet enough rejected-and-scored
    items the response says so (`available: false`) with how many are
    needed — an honest absence rather than an uncalibrated number.
    """
    from ontologylab.conformal import triage

    store = _open_store()
    try:
        return triage(store, alpha=alpha).to_dict()
    finally:
        store.close()


@router.get("/review/calibration")
def get_calibration() -> dict[str, Any]:
    """How honest the extractor's confidence numbers are, measured.

    Raw ECE against review outcomes plus the fitted isotonic curve.
    Read-only like the triage line: calibrated values annotate and order,
    stored confidences are never rewritten (the claim is provenance).
    """
    from ontologylab.calibration import calibration_report

    store = _open_store()
    try:
        return calibration_report(store)
    finally:
        store.close()


@router.get("/proposals")
def list_proposals(
    kind: str | None = Query(None, description="node | edge"),
    type_name: str | None = Query(None),
    source_doc_id: str | None = Query(None),
    order: str = Query(
        "created",
        description="created | confidence (least-certain first) | "
        "confidence_desc | critic (lowest critic score first)",
    ),
    limit: int = Query(100, ge=1, le=1000),
) -> dict[str, Any]:
    store = _open_store()
    try:
        try:
            items = store.pending_review(
                kind=kind,
                type_name=type_name,
                source_doc_id=source_doc_id,
                order=order,
                limit=limit,
            )
        except KGStoreError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        counts = store.counts()
        return {"items": items, "counts": counts, "count": len(items)}
    finally:
        store.close()


@router.post("/proposals/approve")
def approve_proposal(body: ProposalAction) -> dict[str, Any]:
    store = _open_store()
    try:
        result = store.approve(
            body.id, by=body.by, note=body.note, cascade=body.cascade
        )
        return {"ok": True, **result}
    except EndpointNotVerified as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except UnknownItem as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except KGStoreError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    finally:
        store.close()


@router.post("/edges/{edge_id}/invalidate")
def invalidate_edge(edge_id: str, body: ProposalAction) -> dict[str, Any]:
    """W13: mark a verified edge as no-longer-current (kept as history)."""
    store = _open_store()
    try:
        result = store.invalidate_edge(edge_id, by=body.by, reason=body.note)
        return {"ok": True, **result}
    except UnknownItem as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except KGStoreError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    finally:
        store.close()


@router.post("/proposals/reject")
def reject_proposal(body: ProposalAction) -> dict[str, Any]:
    store = _open_store()
    try:
        result = store.reject(body.id, by=body.by, note=body.note)
        return {"ok": True, **result}
    except UnknownItem as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except KGStoreError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    finally:
        store.close()


@router.post("/proposals/reopen")
def reopen_proposal(body: ProposalAction) -> dict[str, Any]:
    """Undo one approve/reject by putting the row back in the review queue.

    400 when a verified edge still depends on the node being reopened — the
    message names the blocking edges so the UI can say what to do next.
    """
    store = _open_store()
    try:
        result = store.reopen(body.id, by=body.by, note=body.note)
        return {"ok": True, **result}
    except UnknownItem as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except KGStoreError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    finally:
        store.close()


# ---------------------------------------------------------------------------
# Entity-centric review (W11 — read-only aggregation for one entity)
# ---------------------------------------------------------------------------


@router.get("/search")
def search_entities(
    q: str = Query(..., min_length=1, max_length=200),
    limit: int = Query(8, ge=1, le=25),
) -> dict[str, Any]:
    """Name search across the graph, for the command palette.

    `KGStore.entity_lookup` has existed since the MCP server was written and
    was reachable only from there and the CLI — the browser had no way to
    ask "where is this entity?" at all, which is why the dashboard's only
    navigation was clicking through ten tabs.

    Proposals are included. The palette's most useful question during a
    review session is "have I seen this name before?", and answering it
    only for already-approved nodes would hide precisely the items the
    reviewer is deciding about right now. `status` rides along so the
    caller can show which is which.
    """
    store = _open_store()
    try:
        matches = store.name_search(q, limit=limit, include_proposed=True)
    except KGStoreError:
        # An unparseable query is an empty result, not a 500: this runs on
        # every keystroke.
        matches = []
    finally:
        store.close()
    return {
        "results": [
            {
                "id": item["id"],
                "name": item["name"],
                "entity_type": item["entity_type"],
                "status": item["status"],
                "score": item.get("match_score"),
            }
            for item in matches
        ]
    }


@router.get("/provenance/{kind}/{item_id}")
def get_provenance(kind: str, item_id: str) -> dict[str, Any]:
    """Why the graph believes one node or edge.

    Every field here has been stored since the first schema and none of it
    reached the browser: which engine and model proposed it, under which
    prompt version, from which span of which document, and who approved it.
    "Why does the KG believe this?" is the question this whole tool is built
    around, and answering it required opening sqlite.
    """
    store = _open_store()
    try:
        return store.provenance(kind, item_id)
    except UnknownItem as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except KGStoreError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    finally:
        store.close()


@router.get("/document/{doc_id}/review")
def document_review(doc_id: str) -> dict[str, Any]:
    """The source text and every proposal drawn from it.

    What the document panel shows. Judging a proposal means judging whether
    the paper says it, and that question is easier to answer with the
    surrounding paragraph than with the 160 characters around the span.
    """
    store = _open_store()
    try:
        return store.document_review_context(doc_id)
    except UnknownItem as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except KGStoreError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    finally:
        store.close()


@router.get("/entity/{entity_id}/review")
def entity_review(entity_id: str) -> dict[str, Any]:
    store = _open_store()
    try:
        return store.entity_review_context(entity_id)
    except UnknownItem as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except KGStoreError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    finally:
        store.close()


# ---------------------------------------------------------------------------
# Communities (W12 — read-only; rows exist only inside built packs, so the
# working-DB store returns an empty list rather than an error)
# ---------------------------------------------------------------------------


@router.get("/communities")
def get_communities(limit: int = Query(20, ge=1, le=200)) -> dict[str, Any]:
    store = _open_store()
    try:
        communities = store.list_communities(limit=limit)
        return {"communities": communities, "count": len(communities)}
    finally:
        store.close()


@router.get("/communities/{community_id}")
def get_community(community_id: str) -> dict[str, Any]:
    store = _open_store()
    try:
        # community_members 404s on an unknown id (UnknownItem); on success
        # we attach the community's own summary/metadata row for the header.
        members = store.community_members(community_id)
        community = next(
            (c for c in store.list_communities(limit=1000)
             if c["id"] == community_id),
            None,
        )
        return {"community": community, "members": members}
    except UnknownItem as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except KGStoreError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    finally:
        store.close()


# ---------------------------------------------------------------------------
# Graph browser (read-only subgraph views — the browser never mutates;
# approve/reject/invalidate stay in the Review surface, per HITL invariant)
# ---------------------------------------------------------------------------


@router.get("/graph")
def get_graph(
    include_proposed: bool = Query(
        True, description="False면 verified-only 서브그래프"
    ),
    entity_type: str | None = Query(None),
    limit: int = Query(150, ge=1, le=500),
) -> dict[str, Any]:
    """Overview subgraph: up to ``limit`` nodes plus the edges among them."""
    store = _open_store()
    try:
        return store.graph_query(
            entity_type=entity_type or None,
            include_proposed=include_proposed,
            limit=limit,
        )
    finally:
        store.close()


@router.get("/graph/neighbors/{node_id}")
def get_graph_neighbors(
    node_id: str,
    hops: int = Query(1, ge=1, le=3),
    include_proposed: bool = Query(True),
    limit: int = Query(100, ge=1, le=500),
) -> dict[str, Any]:
    """N-hop BFS neighborhood around one node (graph-browser expansion)."""
    store = _open_store()
    try:
        result = store.traverse_relations(
            [node_id],
            max_hops=hops,
            include_proposed=include_proposed,
            limit=limit,
        )
    finally:
        store.close()
    if not result["nodes"]:
        raise HTTPException(
            status_code=404, detail=f"unknown or filtered node {node_id!r}"
        )
    return result


# ---------------------------------------------------------------------------
# Critic triage (W8 — advisory scores; never a decision path)
# ---------------------------------------------------------------------------


@router.post("/critic/run")
async def critic_run(body: CriticRunRequest) -> dict[str, Any]:
    from ontologylab.critic import critic_review, resolve_critic_model
    from ontologylab.engines import get_engine

    critic_model = resolve_critic_model(body.engine, body.model)
    engine = get_engine(body.engine, critic_model, data_dir=_data_dir)
    store = _open_store()
    try:
        stats = await critic_review(
            store, engine, model=critic_model,
            limit=body.limit, batch_size=body.batch_size,
        )
        return {"ok": True, **stats}
    finally:
        store.close()


# ---------------------------------------------------------------------------
# Merge review (W7 — candidates from scan, decisions by human)
# ---------------------------------------------------------------------------


@router.post("/enrich")
def enrich_nodes(limit: int = Query(50, ge=1, le=500)) -> dict[str, Any]:
    """Look verified nodes up in the curated resources; queue what matches.

    Synchronous and capped. Unlike a research run this makes at most
    `limit x resources` small requests against keyless endpoints, so there
    is no job to poll — and a cap the caller sets is easier to reason about
    than a background task they have to remember is running.
    """
    from ontologylab.enrichment import enrich

    store = _open_store()
    try:
        report = enrich(store, limit=limit)
        return {"ok": True, **report.as_dict()}
    except Exception as exc:
        # Same discipline as the fan-out: name the kind, not the text. These
        # endpoints are keyless, but the message can still quote a URL.
        return {"ok": False, "error_kind": "failed",
                "detail": f"enrichment failed: {type(exc).__name__}"}
    finally:
        store.close()


@router.get("/annotations")
def list_annotations(limit: int = Query(100, ge=1, le=500)) -> dict[str, Any]:
    store = _open_store()
    try:
        return {
            "annotations": store.annotations_pending(limit=limit),
            "counts": store.annotation_counts(),
            "resources": [
                {"id": name, "label": RESOURCE_LABELS.get(name, name)}
                for name in RESOURCE_ORDER
            ],
            # The scope the screen states. Sent rather than written into the
            # markup so a change to ORGANISM cannot leave the UI asserting
            # an organism the lookups no longer use.
            "organism": ORGANISM["label"],
        }
    finally:
        store.close()


@router.post("/annotations/{annotation_id}/decide")
def decide_annotation(annotation_id: str, body: AnnotationDecision) -> dict[str, Any]:
    store = _open_store()
    try:
        decided = store.decide_annotation(
            annotation_id, accept=body.accept, note=body.note
        )
        if not decided:
            return {"ok": False, "error_kind": "rejected",
                    "detail": "annotation is unknown or already decided"}
        return {"ok": True, "counts": store.annotation_counts()}
    finally:
        store.close()


@router.post("/merge/scan")
def merge_scan(body: MergeScanRequest) -> dict[str, Any]:
    from ontologylab.merge import scan_merge_candidates

    store = _open_store()
    try:
        stats = scan_merge_candidates(store, name_threshold=body.min_similarity)
        return {"ok": True, **stats}
    finally:
        store.close()


@router.get("/merge/candidates")
def merge_candidates(limit: int = Query(100, ge=1, le=500)) -> dict[str, Any]:
    store = _open_store()
    try:
        items = store.merge_candidates_pending(limit=limit)
        return {"items": items, "count": len(items)}
    finally:
        store.close()


@router.post("/merge/candidates/{candidate_id}/merge")
def merge_candidate_merge(candidate_id: str, body: MergeAction) -> dict[str, Any]:
    store = _open_store()
    try:
        candidate = store._merge_candidate_row(candidate_id)
        pair = {candidate["node_a_id"], candidate["node_b_id"]}
        if {body.target_id, body.source_id} != pair:
            raise HTTPException(
                status_code=400,
                detail="target/source ids do not match this candidate's pair",
            )
        if candidate["status"] != "proposed":
            raise HTTPException(
                status_code=409,
                detail=f"candidate already decided ({candidate['status']})",
            )
        report = store.merge_nodes(
            body.target_id, body.source_id, by=body.by, note=body.note
        )
        return {"ok": True, **report}
    except UnknownItem as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except KGStoreError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    finally:
        store.close()


@router.post("/merge/candidates/{candidate_id}/dismiss")
def merge_candidate_dismiss(candidate_id: str, body: MergeDismiss) -> dict[str, Any]:
    store = _open_store()
    try:
        result = store.dismiss_merge_candidate(
            candidate_id, by=body.by, note=body.note
        )
        return {"ok": True, **result}
    except UnknownItem as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except KGStoreError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    finally:
        store.close()


# ---------------------------------------------------------------------------
# Publisher sources (registry holds a reference; the key lives in the Keychain)
# ---------------------------------------------------------------------------

# Longest key this will accept. Publisher keys are tens of characters; a
# megabyte in this field is a mistake or an attempt to fill the Keychain,
# and checking it here means the limit is enforced without a 422 that would
# echo the value back.
MAX_SOURCE_KEY_LEN = 4096


@router.get("/sources")
def list_sources() -> dict[str, Any]:
    """Connected publisher sources. Presence only — never a key value."""
    return {"sources": [source_public(s) for s in load_sources(_data_dir)]}


@router.post("/sources")
def create_source(body: SourceCreate) -> dict[str, Any]:
    """Connect a source, storing its key in the Keychain.

    Gate failures answer 200 with a typed `error_kind`, like `collect` — the
    Sources screen renders them inline. Nothing here echoes the submitted
    key, including on the failure paths: the messages are written here rather
    than derived from an exception, because `security`'s command line
    contains the key and its errors could quote it.
    """
    key = (body.key or "").strip()
    if key and len(key) > MAX_SOURCE_KEY_LEN:
        # Deliberately does not report the length back either — that is a
        # small oracle, and the user knows what they pasted.
        return {"ok": False, "error_kind": "rejected",
                "detail": f"key is longer than {MAX_SOURCE_KEY_LEN} characters"}

    # A key with no home would be dropped on the floor, so default one. It is
    # derived from the source **id**, not the role: `ontologylab.{role}` gave
    # every publisher the same account name, so connecting a second publisher
    # overwrote the first one's key and then that single key was sent to all
    # three vendors. One account per publisher, one key per account.
    account = body.keychain_account or (f"ontologylab.{body.id}" if key else "")
    source = Source(
        id=body.id,
        role=body.role,
        keychain_account=account,
        api_key_env=body.api_key_env,
        label=body.label,
    )
    try:
        validate_source(source)
    except SourceError as exc:
        return {"ok": False, "error_kind": "rejected", "detail": str(exc)}

    if key:
        if not keychain_available():
            return {
                "ok": False,
                "error_kind": "unsupported",
                "detail": (
                    "this machine has no macOS Keychain; set the key as an "
                    "environment variable and give its name as api_key_env"
                ),
            }
        try:
            write_key(account, key)
        except KeychainError as exc:
            # H2 applies here, and this is the one place it bites hardest:
            # `security` is invoked with the key on its command line, so an
            # error about that invocation is the most likely thing in the
            # system to quote it. `keychain.py` writes its own messages and
            # is tested not to include the key — but forwarding a foreign
            # string means a future edit there silently reopens this. Scrub
            # rather than trust, the same way the Keychain write verifies
            # rather than trusting its exit status.
            detail = str(exc)
            if key in detail:
                detail = "the Keychain rejected the key"
            return {"ok": False, "error_kind": "failed", "detail": detail}

    add_source(_data_dir, source)
    return {"ok": True, "source": source_public(source)}


@router.delete("/sources/{source_id}")
def delete_source(source_id: str) -> dict[str, Any]:
    """Disconnect a source. The stored key is left alone.

    Removing a configuration row and destroying a credential are different
    decisions, so they are different requests. `key_retained` tells the UI
    whether to offer the second one.
    """
    source = get_source(_data_dir, source_id)
    removed = remove_source(_data_dir, source_id)
    retained = bool(
        source is not None
        and source.keychain_account
        and read_key(source.keychain_account) is not None
    )
    return {"ok": True, "removed": removed, "key_retained": retained}


@router.delete("/sources/{source_id}/key")
def forget_source_key(source_id: str) -> dict[str, Any]:
    """Delete the stored key itself, leaving the registry entry in place.

    Separated from the row deletion because it is the destructive half, and
    because a user rotating a key wants exactly this and nothing else.
    """
    source = get_source(_data_dir, source_id)
    if source is None or not source.keychain_account:
        return {"ok": True, "forgotten": False, "reason": "no stored key"}
    return {"ok": True, "forgotten": delete_key(source.keychain_account)}


# ---------------------------------------------------------------------------
# Documents / collect (Sources screen)
# ---------------------------------------------------------------------------


@router.get("/documents")
def get_documents() -> dict[str, Any]:
    store = _open_store()
    try:
        documents = [
            {
                "id": doc.id,
                "source_kind": doc.source_kind,
                "source_uri": doc.source_uri,
                "title": doc.title,
                "fetched_ts": doc.fetched_ts,
                "content_hash": doc.content_hash,
            }
            for doc in store.list_documents()
        ]
    finally:
        store.close()
    return {"documents": documents, "count": len(documents)}


@router.post("/collect")
def collect(body: CollectRequest) -> dict[str, Any]:
    """Run a collect synchronously, mirroring main.cmd_collect's gate order.

    Gate failures return 200 with {"ok": false, "error_kind", "detail"} so
    the dashboard can render them inline — never a 4xx/5xx.
    """
    job_dir = paths.new_job_dir(_data_dir, "collect")
    provenance = Provenance(str(job_dir), seed=0)
    # Logged before the gates so a rejected attempt still leaves a trace,
    # and bounded because that ordering means these values have passed no
    # validation yet (M2 — see `loggable_collect_inputs`).
    provenance.log(
        "collect.start",
        {
            "urls": loggable_collect_inputs(body.urls),
            "files": loggable_collect_inputs(body.files),
            "paper_queries": loggable_collect_inputs(body.paper_queries),
        },
    )

    if not (body.urls or body.files or body.paper_queries):
        detail = (
            "nothing to collect: pass urls, files, and/or paper_queries"
        )
        provenance.log("collect.rejected", {"error": detail})
        return {"ok": False, "error_kind": "rejected", "detail": detail}

    # Mixed-run pre-validation (mirrors cmd_collect): every gate for every
    # input is checked BEFORE any fetch, so one rejected/unsupported input
    # can never let an earlier input reach the network first.
    try:
        for url in body.urls:
            check_url(url)
        for file_arg in body.files:
            check_collect_file(file_arg, _data_dir)
        for paper_query in body.paper_queries:
            check_paper_query(body.paper_source, paper_query)
            check_source_implemented(body.paper_source)
    except NotAllowlisted as exc:
        provenance.log("collect.rejected", {"error": str(exc)})
        return {"ok": False, "error_kind": "rejected", "detail": str(exc)}
    except UnsupportedPaperSource as exc:
        provenance.log("collect.unsupported", {"error": str(exc)})
        return {"ok": False, "error_kind": "unsupported", "detail": str(exc)}

    # Offline is checked HERE — after the allowlist gate, before any fetch.
    #
    # After, because `NotAllowlisted` above logs `collect.rejected`, and
    # offline mode is the normal resting state for this system. Checking
    # offline first would mean that for as long as the kill switch is on,
    # every allowlist violation returns before it is recorded — the audit
    # trail for a security boundary would go silent exactly while the system
    # is at its most locked down. A boundary violation must be logged
    # regardless of whether the network was reachable.
    #
    # Before the fetch, because the connectors raise `NetworkBlocked` per
    # source. Under a fan-out's `return_exceptions=True` that arrives five
    # times and reads as "five sources failed" — a network problem — instead
    # of "the operator turned egress off". The per-fetch
    # `assert_network_allowed` stays as defence in depth.
    # Only a request that would actually leave the machine is refused: the
    # kill switch governs egress, and collecting a local file is not egress.
    needs_network = bool(body.urls or body.paper_queries)
    if needs_network and paths.offline_mode():
        detail = (
            "offline mode (ONTOLOGYLAB_OFFLINE) blocks network collection; "
            "unset it to fetch, or collect local files instead"
        )
        provenance.log("collect.offline", {"error": detail})
        return {"ok": False, "error_kind": "offline", "detail": detail}

    error: dict[str, Any] | None = None

    def _run_connector(connector, spec: dict) -> list[RawDocument] | None:
        """Fetch via one connector; None means a logged, returnable failure.

        NotAllowlisted / UnsupportedPaperSource are re-checked in-fetch as
        defense in depth; URLError (incl. HTTPError) and Atom ParseError
        are fetch failures — all must end as a clean JSON error, never a
        500 (with no network, URL fetches fail here as fetch_failed).
        """
        nonlocal error
        try:
            return asyncio.run(connector.fetch(spec))
        except NotAllowlisted as exc:
            provenance.log("collect.rejected", {"error": str(exc)})
            error = {"ok": False, "error_kind": "rejected", "detail": str(exc)}
        except UnsupportedPaperSource as exc:
            provenance.log("collect.unsupported", {"error": str(exc)})
            error = {"ok": False, "error_kind": "unsupported", "detail": str(exc)}
        except MissingSourceKey as exc:
            # Ordinary first-use, not a fault: the user picked a publisher
            # they have not connected. `_classify` already names this kind for
            # the research path, and this route's docstring promises the same
            # typed answer — it raised a 500 instead.
            provenance.log("collect.unconfigured", {"error": str(exc)})
            error = {"ok": False, "error_kind": "unconfigured", "detail": str(exc)}
        except ResponseTooLarge as exc:
            provenance.log("collect.too_large", {"error": str(exc)})
            error = {"ok": False, "error_kind": "too_large", "detail": str(exc)}
        except (URLError, ParseError) as exc:
            provenance.log("collect.fetch_failed", {"error": str(exc)})
            error = {"ok": False, "error_kind": "fetch_failed", "detail": str(exc)}
        except (ValueError, OSError) as exc:
            provenance.log("collect.failed", {"error": str(exc)})
            error = {"ok": False, "error_kind": "fetch_failed", "detail": str(exc)}
        return None

    raw_docs: list[RawDocument] = []
    if body.urls:
        fetched = _run_connector(WebCrawlConnector(), {"urls": body.urls})
        if fetched is None:
            return error or {"ok": False, "error_kind": "fetch_failed",
                             "detail": "web crawl failed"}
        raw_docs.extend(fetched)
    for paper_query in body.paper_queries:
        fetched = _run_connector(
            PaperApiConnector(),
            {
                "source": body.paper_source,
                "query": paper_query,
                "limit": body.limit,
                # Without this the connector cannot find the registry, so a
                # keyed source is refused as `unconfigured` even when its key
                # is connected — the research path passed it, this one did
                # not, and the two disagreed about the same configuration.
                "data_dir": _data_dir,
            },
        )
        if fetched is None:
            return error or {"ok": False, "error_kind": "fetch_failed",
                             "detail": "paper API fetch failed"}
        raw_docs.extend(fetched)
    for file_arg in body.files:
        path = Path(file_arg)
        try:
            raw_text = path.read_text(encoding="utf-8")
        except (OSError, ValueError) as exc:
            provenance.log("collect.fetch_failed", {"error": str(exc)})
            return {"ok": False, "error_kind": "fetch_failed", "detail": str(exc)}
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
        return {"ok": True, "documents": 0, "created": 0, "duplicates": 0}

    store = _open_store()
    try:
        created_count = 0
        for raw in raw_docs:
            doc, created = store.insert_document(
                source_kind=raw.source_kind,
                source_uri=raw.source_uri,
                title=raw.title,
                raw_text=raw.raw_text,
                content_hash=raw.content_hash,
            )
            created_count += 1 if created else 0
            provenance.log(
                "collect.doc",
                {
                    "doc_id": doc.id,
                    "source_uri": doc.source_uri,
                    "created": created,
                    "chars": len(raw.raw_text),
                },
            )
        provenance.log(
            "collect.end",
            {"documents": len(raw_docs), "created": created_count},
        )
    finally:
        store.close()
    return {
        "ok": True,
        "documents": len(raw_docs),
        "created": created_count,
        "duplicates": len(raw_docs) - created_count,
    }


# Onboarding sample for the dashboard "따라하기" journey: a bundled static
# document, no network, no filesystem path. Idempotent — re-posting dedupes
# on content_hash exactly like any other collect. Collect/extract may be
# automated for onboarding; APPROVAL never is (HITL).
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


@router.post("/collect/sample")
def collect_sample() -> dict[str, Any]:
    """Ingest the bundled onboarding sample document (offline, idempotent)."""
    raw = RawDocument(
        source_kind="upload",
        source_uri="sample://onboarding/order-system",
        title=SAMPLE_DOC_TITLE,
        raw_text=SAMPLE_DOC_TEXT,
    )
    store = _open_store()
    try:
        doc, created = store.insert_document(
            source_kind=raw.source_kind,
            source_uri=raw.source_uri,
            title=raw.title,
            raw_text=raw.raw_text,
            content_hash=raw.content_hash,
        )
    finally:
        store.close()
    return {
        "ok": True,
        "created": created,
        "document_id": doc.id,
        "title": doc.title,
    }


# ---------------------------------------------------------------------------
# Extraction jobs (Extraction Jobs screen — polled, tui.py-style)
# ---------------------------------------------------------------------------


@router.post("/extract", status_code=202)
def start_extract(body: ExtractRequest) -> dict[str, Any]:
    job = _registry().create(
        engine=body.engine,
        model=body.model,
        doc_ids=body.doc_ids,
        max_engine_calls=body.max_engine_calls,
        time_budget=body.time_budget,
        seed=body.seed,
    )
    return {"job_id": job.job_id, "status": "running"}


@router.post("/research")
def start_research(body: ResearchRequest) -> dict[str, Any]:
    """Collect a topic across sources and extract it, as one job.

    Every gate runs here, synchronously, before a job exists. `Job` carries
    only `error: str` — there is nowhere on it to put an `error_kind`, so a
    rejection routed through the worker would reach the dashboard as an
    untyped failure and lose the badge the Sources screen renders. This
    mirrors `collect`'s gate order exactly: shape, then allowlist, then
    offline.
    """
    # Default to what can actually be queried: the keyless five plus any
    # publisher source that is connected. An explicit list is honoured as
    # given, so asking for `elsevier` without a key still answers with a
    # typed `unconfigured` rather than silently dropping it.
    sources = body.sources or available_sources(_data_dir)

    def _record(step: str, payload: dict[str, Any]) -> None:
        """Write a refusal to provenance, creating its run dir on demand.

        Only refusals land here. An accepted request gets its own job dir
        moments later and logs `research.start` into it, so recording every
        request eagerly would leave an empty run dir behind for each one and
        double-count research runs in the jobs listing.

        All refusals share ONE directory. Minting a fresh `research-<ts>/`
        per refusal was unbounded from the outside: `cost_summary` re-reads
        every `data/jobs/*/provenance.jsonl` on each `GET /api/cost`, so
        holding Enter on an empty topic box degraded that screen permanently.
        A rejected request is not a run and should not look like one.
        """
        rejects = paths.jobs_dir(_data_dir) / "research-rejected"
        rejects.mkdir(parents=True, exist_ok=True)
        provenance = Provenance(str(rejects), seed=0)
        provenance.log(
            step,
            {"topic": loggable_collect_inputs([body.topic]),
             "sources": sources, **payload},
        )

    try:
        for source in sources:
            check_paper_query(source, body.topic)
            check_source_implemented(source)
    except NotAllowlisted as exc:
        _record("research.rejected", {"error": str(exc)})
        return {"ok": False, "error_kind": "rejected", "detail": str(exc)}
    except UnsupportedPaperSource as exc:
        _record("research.unsupported", {"error": str(exc)})
        return {"ok": False, "error_kind": "unsupported", "detail": str(exc)}

    # After the allowlist gate, before any fetch — the same ordering and the
    # same reason as `collect`: a boundary violation must be recorded even
    # while the kill switch is on, and a fan-out under
    # `return_exceptions=True` would otherwise report the kill switch as
    # five separate source failures.
    if paths.offline_mode():
        detail = (
            "offline mode (ONTOLOGYLAB_OFFLINE) blocks network collection; "
            "unset it to run a research topic"
        )
        _record("research.offline", {"error": detail})
        return {"ok": False, "error_kind": "offline", "detail": detail}

    # No pre-check here: asking the registry "is one running?" and then
    # asking it to create is two lock acquisitions, and two concurrent
    # requests both pass. `create_research` decides under the same lock that
    # registers the job, and says no by raising.
    try:
        job = _registry().create_research(
            topic=body.topic,
            sources=sources,
            limit=body.limit,
            fulltext=body.fulltext,
            engine=body.engine,
            model=body.model,
            max_engine_calls=body.max_engine_calls,
            time_budget=body.time_budget,
            seed=body.seed,
        )
    except JobAlreadyRunning as exc:
        return {
            "ok": False,
            "error_kind": "busy",
            "detail": (
                f"research run {exc.job_id} is still going; "
                f"cancel it or wait for it to finish"
            ),
            "job_id": exc.job_id,
        }
    return {"ok": True, "job_id": job.job_id, "status": "running"}


# ---------------------------------------------------------------------------
# Chat — one sentence in, one accountable answer out
# ---------------------------------------------------------------------------

# Every parameter of a called route has to be supplied by name here, even
# when a default exists. A FastAPI route is a plain function whose defaults
# are `Query(...)` *objects*, so calling `search_entities(q=query)` bound a
# `Query` instance as `limit` and the search reached sqlite as
# `Error binding parameter 4: type 'Query' is not supported` — a 500 in
# chat, and for `enrich` a permanent "enrichment failed" that looked like a
# resource being down. `test_chat_supplies_every_query_parameter` keeps the
# next one from being added the same way.
#
# The value matches what the browser draws (`hits.slice(0, 8)`): asking the
# store for more than the bubble shows is work nobody sees.
CHAT_SEARCH_LIMIT = 8
# One conversational turn should not silently start a 50-node fan-out
# across curated resources; the Review screen's button is where a bulk run
# belongs.
CHAT_ENRICH_LIMIT = 10


def _open_chat_store() -> ChatStore:
    return ChatStore.open(paths.chat_db_path(_data_dir))


def _record_turn(body: ChatMessage, payload: dict[str, Any]) -> Optional[str]:
    """Write one turn to the transcript, or return None if that failed.

    Deliberately never raises. The transcript is a convenience — being able
    to reopen the tab and see what you asked — and an answer the person is
    looking at right now is worth more than a complete log. A chat that
    500s because its own history file is locked would be trading the
    feature for the record of the feature.
    """
    result = payload.get("result") or {}
    try:
        store = _open_chat_store()
        try:
            return store.record(
                message=body.message,
                action=payload.get("action", "unknown"),
                reading=payload.get("reading", ""),
                result=result,
                steps=payload.get("steps", []),
                job_id=result.get("job_id"),
            )
        finally:
            store.close()
    except Exception:
        # Not raising is deliberate; being silent was not. The catch stays
        # broad because anything here — a locked file, a full disk, a
        # payload json cannot encode — is still less important than the
        # answer the person is looking at. But broad also means it would
        # swallow a real bug, and a transcript that quietly stopped working
        # is the one failure nobody would ever notice.
        #
        # `logging`, not provenance: provenance wants a run directory, and
        # this fails identically on every message — which is exactly how
        # `start_research` once made `GET /api/cost` permanently slow by
        # minting one directory per refusal. uvicorn already configures the
        # root logger, so this lands in the server's own output.
        _log.warning("chat transcript not written", exc_info=True)
        return None


@router.post("/chat")
async def chat(body: ChatMessage) -> dict[str, Any]:
    """Read one message, run the action it names, return a rendered result.

    The model classifies; this dispatches. It never receives code, a URL or
    a query fragment from the model — only an action name from a fixed
    table plus validated parameters — so widening what chat can reach is an
    edit to `intent.ACTIONS`, visible in review.

    Mutating actions are NOT run here. They come back with
    `needs_confirmation` and the browser has to ask; `confirmed=True` on a
    second request is what actually executes. Chat moves the asking into a
    sentence, not the deciding.

    Every reply carries `steps`: what was used, in order. A chat answer is
    the one place in this app where work happens behind a sentence, so the
    sentence has to be accountable — which engine read the message, which
    sources were queried, what the store was asked. Without it the reply is
    a claim; with it the claim is checkable.
    """
    # Imported here, like the other engine-using routes: `intent` imports
    # `engines`, and `engines` is heavy enough that the module graph is kept
    # lazy on purpose.
    from ontologylab.engines import EngineError, get_engine
    from ontologylab.intent import ACTIONS, classify

    trace: list[Step] = []

    def reply(ok: bool, **extra: Any) -> dict[str, Any]:
        payload = {"ok": ok, "steps": [s.as_dict() for s in trace], **extra}
        result = payload.get("result") or {}
        # A pending confirmation is a question, not a turn: recording it
        # would put the same message in the transcript twice, once
        # unanswered and once done, and the unanswered copy would still
        # show its button — a second, stale way to authorise the change.
        if result.get("kind") != "confirm":
            payload["turn_id"] = _record_turn(body, payload)
        return payload

    try:
        engine = get_engine(body.engine, body.model, data_dir=_data_dir)
    except EngineError as exc:
        trace.append(Step(body.engine, "classify", "failed", "unavailable"))
        return reply(False, error_kind="unsupported",
                     detail=f"engine unavailable: {exc}")

    intent = await classify(body.message, engine, model=body.model)
    # `intent.error` can carry an exception's text, so this names the
    # outcome and never the reason — the reason belongs in the log, not on
    # a screen (an exception here can quote a keyed URL).
    trace.append(Step(
        body.engine, "classify",
        "failed" if intent.error else "ok",
        intent.action,
    ))
    payload = intent.as_dict()

    if intent.action == "unknown":
        payload["result"] = {
            "kind": "text",
            "actions": [
                {"name": name, "summary": action.summary}
                for name, action in ACTIONS.items()
                if name != "unknown"
            ],
        }
        return reply(True, **payload)

    if intent.needs_confirmation and not body.confirmed:
        payload["result"] = {"kind": "confirm", "action": intent.action}
        return reply(True, **payload)

    # Off the event loop. Everything `_run_intent` dispatches to is
    # synchronous and some of it is slow — `build_pack` writes a whole pack,
    # `enrich` makes network calls to curated resources. Measured against a
    # real server, a two-second action inside this `async def` delayed an
    # unrelated `GET /api/settings` by 1.72s; the jobs SSE stream shares
    # that loop, so a chat-initiated build would freeze the progress display
    # of a research run happening at the same time.
    payload["result"] = await run_in_threadpool(
        _run_intent, intent, trace, body
    )
    return reply(True, **payload)


def _run_intent(
    intent: "Intent", trace: list[Step], body: ChatMessage
) -> dict[str, Any]:
    """Perform one already-classified, already-confirmed action."""
    action, params = intent.action, intent.params

    if action == "research":
        topic = params.get("topic", "").strip()
        if not topic:
            trace.append(
                Step("ontologylab", "research", "failed", "no_topic")
            )
            return {"kind": "blocked", "error_kind": "shape",
                    "detail": "which topic should I search for?"}
        # Through `start_research`, not around it. Every gate — allowlist,
        # unsupported source, offline, already-running — lives there, and a
        # second path into the fan-out would be a second, laxer entrance to
        # the same network calls.
        started = start_research(ResearchRequest(
            topic=topic, engine=body.engine, model=body.model,
        ))
        if not started.get("ok"):
            trace.append(Step(
                "ontologylab", "research", "failed",
                started.get("error_kind", "refused"),
            ))
            return {"kind": "blocked", **started}
        trace.append(Step("ontologylab", "research", "running", topic))
        return {"kind": "job", "job_id": started["job_id"], "topic": topic}

    if action == "search_entities":
        query = params.get("query", "").strip()
        if not query:
            trace.append(Step("store", "search", "failed", "no_query"))
            return {"kind": "blocked", "error_kind": "shape",
                    "detail": "which name should I look for?"}
        found = search_entities(q=query, limit=CHAT_SEARCH_LIMIT)
        trace.append(
            Step("store", "search", "ok", str(len(found.get("results", []))))
        )
        return {"kind": "search", "query": query, **found}

    if action == "enrich":
        result = enrich_nodes(limit=CHAT_ENRICH_LIMIT)
        trace.append(
            Step("resources", "lookup", "ok", str(result.get("proposed", 0)))
        )
        return {"kind": "enrich", **result}

    if action == "build_pack":
        built = packs_build(PackBuildRequest(name=params.get("name") or None))
        trace.append(Step("ontologylab", "build", "ok",
                          str(built.get("pack_id", ""))))
        return {"kind": "pack", **built}

    # Everything else is a read. One store round-trip, and the browser
    # decides which screen the answer belongs on.
    store = _open_store()
    try:
        counts = store.counts()
    finally:
        store.close()
    trace.append(Step("store", "read", "ok", "counts"))

    screen = {
        "show_review": "review", "show_graph": "graph",
        "show_packs": "packs", "show_sources": "sources",
    }.get(action)
    if screen:
        return {"kind": "goto", "screen": screen, "counts": counts}
    if action == "help":
        from ontologylab.intent import ACTIONS as _ACTIONS

        return {
            "kind": "text",
            "actions": [
                {"name": name, "summary": act.summary}
                for name, act in _ACTIONS.items()
                if name != "unknown"
            ],
        }
    return {"kind": "status", "counts": counts}


@router.get("/chat/history")
def chat_history(limit: int = Query(100, ge=1, le=MAX_TURNS)) -> dict[str, Any]:
    """The conversation so far, oldest first."""
    store = _open_chat_store()
    try:
        return {"turns": store.history(limit=limit)}
    finally:
        store.close()


@router.delete("/chat/history")
def chat_history_clear() -> dict[str, Any]:
    """Forget the conversation.

    A local-first tool that keeps a transcript owes the person a way to end
    it. Nothing else is touched: documents, proposals and packs are the
    knowledge, and this is only the record of what was asked.
    """
    store = _open_chat_store()
    try:
        return {"ok": True, "cleared": store.clear()}
    finally:
        store.close()


@router.get("/jobs")
def list_jobs() -> dict[str, Any]:
    return {"jobs": [job.as_status() for job in _registry().list()]}


@router.get("/jobs/{job_id}/asked")
def job_asked(job_id: str) -> dict[str, Any]:
    """Which question started this run.

    A run records what it did in great detail and nothing about why it was
    running. That gap only became visible once a run could be started by
    typing a sentence: `research-20260728-071805` is a worse answer to
    "what is this" than the words somebody typed.

    Returns `{"turn": null}` for a run started from the form — that is an
    absence, not a failure.
    """
    store = _open_chat_store()
    try:
        return {"turn": store.turn_for_job(job_id)}
    finally:
        store.close()


@router.post("/jobs/{job_id}/cancel")
def cancel_job(job_id: str) -> dict[str, Any]:
    """Ask a running job to stop at its next checkpoint.

    Returns 200 either way: `cancelled` false means the job was unknown or
    had already reached a terminal state, which is not an error the caller
    can act on. Cancelling twice is harmless.

    This is a request, not a kill — the worker stops between chunks, and a
    blocking fetch already in flight runs to its socket timeout first.
    """
    job = _registry().get(job_id)
    if job is None:
        return {"ok": True, "cancelled": False, "reason": "unknown job"}
    if not job.cancel():
        return {"ok": True, "cancelled": False, "reason": f"already {job.status}"}
    return {"ok": True, "cancelled": True, "job": job.as_status()}


# Seconds each stream iteration waits for a change before emitting a
# keepalive comment (also bounds how long a disconnect goes unnoticed).
# Tests shrink this to keep teardown fast.
JOBS_STREAM_WAIT_S = 15.0


@router.get("/jobs/stream")
async def stream_jobs(
    request: Request,
    max_events: int | None = Query(
        None,
        ge=1,
        description="끝없는 스트림 대신 N개의 jobs 이벤트 후 종료 (테스트/진단용 "
        "— TestClient류 버퍼링 클라이언트는 유한 응답만 읽을 수 있다)",
    ),
) -> StreamingResponse:
    """Server-sent job updates: push on change instead of client polling.

    Emits an immediate ``event: jobs`` snapshot on connect, then a new
    snapshot whenever the registry version moves (job created, progress
    line, status transition). Quiet periods produce ``: keepalive``
    comments so proxies don't drop the connection. The dashboard falls
    back to GET /api/jobs polling when EventSource is unavailable.
    """
    registry = _registry()

    async def event_source() -> AsyncIterator[str]:
        last_seen = -1  # registry starts at 0 → first wait returns at once
        remaining = max_events
        while True:
            if await request.is_disconnected():
                return
            version = await run_in_threadpool(
                registry.wait_version, last_seen, JOBS_STREAM_WAIT_S
            )
            if version == last_seen:
                yield ": keepalive\n\n"
                continue
            last_seen = version
            payload = json.dumps(
                {"jobs": [job.as_status() for job in registry.list()]},
                ensure_ascii=False,
            )
            yield "event: jobs\ndata: " + payload + "\n\n"
            if remaining is not None:
                remaining -= 1
                if remaining <= 0:
                    return

    return StreamingResponse(
        event_source(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/jobs/{job_id}", response_model=JobStatus)
def get_job(job_id: str) -> JobStatus:
    job = _registry().get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"unknown job {job_id!r}")
    return JobStatus(**job.as_status())


# ---------------------------------------------------------------------------
# Packs (Packs screen)
# ---------------------------------------------------------------------------


@router.get("/packs")
def get_packs() -> dict[str, Any]:
    packs = list_packs(_packs_dir)
    return {"packs": packs, "count": len(packs)}


@router.post("/packs/build")
def packs_build(body: PackBuildRequest) -> dict[str, Any]:
    job_dir = paths.new_job_dir(_data_dir, "build-pack")
    provenance = Provenance(str(job_dir), seed=0)
    provenance.log("build_pack.start", {"name": body.name})
    # Zero collected documents / zero verified rows is still a buildable
    # (empty) pack: ensure the working DB exists before handing it over.
    _open_store().close()
    try:
        manifest = build_pack(
            kg_db_path(_data_dir),
            _packs_dir,
            body.name,
            source_job_id=job_dir.name,
            provenance_jsonl=provenance.jsonl_path,
        )
    except (PackBuildError, OSError) as exc:
        provenance.log("build_pack.failed", {"error": str(exc)})
        return {"ok": False, "detail": str(exc)}
    provenance.log(
        "build_pack.end",
        {"pack_id": manifest.pack_id, "counts": manifest.counts},
    )
    return {"ok": True, "manifest": dataclasses.asdict(manifest)}


@router.get("/packs/{pack_a_id}/diff/{pack_b_id}")
def packs_diff(pack_a_id: str, pack_b_id: str) -> dict[str, Any]:
    """W14: manifest + node/edge deltas between two built packs."""
    from ontologylab.packdiff import diff_packs

    try:
        return diff_packs(_packs_dir, pack_a_id, pack_b_id)
    except PackBuildError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/packs/{pack_id}/mcpb")
def packs_build_mcpb(pack_id: str) -> dict[str, Any]:
    """Bundle one built pack as a downloadable .mcpb file."""
    from ontologylab.mcpb import build_mcpb

    try:
        bundle = build_mcpb(_packs_dir, pack_id)
    except (PackBuildError, OSError) as exc:
        return {"ok": False, "detail": str(exc)}
    return {
        "ok": True,
        "pack_id": pack_id,
        "path": str(bundle),
        "size_bytes": bundle.stat().st_size,
        "download_url": f"/api/packs/{pack_id}/mcpb/download",
    }


@router.get("/packs/{pack_id}/mcpb/download")
def packs_download_mcpb(pack_id: str) -> Any:
    from fastapi.responses import FileResponse

    from ontologylab.mcpb import build_mcpb

    bundle = Path(_packs_dir) / f"{pack_id}.mcpb"
    if not bundle.is_file():
        try:
            bundle = build_mcpb(_packs_dir, pack_id)
        except (PackBuildError, OSError) as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
    return FileResponse(
        bundle,
        media_type="application/zip",
        filename=f"{pack_id}.mcpb",
    )


# ---------------------------------------------------------------------------
# MCP status (MCP Status screen)
# ---------------------------------------------------------------------------


@router.get("/mcp/status")
def mcp_status() -> dict[str, Any]:
    packs_abs = str(Path(_packs_dir).resolve())
    entries: list[dict[str, Any]] = []
    for manifest in list_packs(_packs_dir):
        pack_id = manifest.get("pack_id")
        entries.append(
            {
                "pack_id": pack_id,
                "counts": manifest.get("counts") or {},
                "created_ts": manifest.get("created_ts"),
                "serve_command": "python " + " ".join(
                    serve_args(packs_abs, pack_id)
                ),
                "stdio_config": {
                    "command": "python",
                    "args": serve_args(packs_abs, pack_id),
                },
            }
        )
    return {"packs_dir": packs_abs, "packs": entries, "count": len(entries)}
