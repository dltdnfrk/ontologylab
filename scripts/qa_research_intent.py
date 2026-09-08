"""Disposable intent-to-evidence QA runner.

Size exception marker: # noqa: SIZE_OK - scripts/AGENTS requires each evidence
producer to stay self-contained and forbids a shared scripts helper library.
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import socket
import subprocess
import sys
import tempfile
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from ontologylab import intent as intent_module
from ontologylab import paths, research_plan, research_spec
from ontologylab import research_run as research_run_module
from ontologylab.connectors.base import RawDocument
from ontologylab.intent import Intent
from ontologylab.kgstore import KGStore
from ontologylab.models import Engine
from ontologylab.research_evaluation import evaluate_research_matrix
from ontologylab.server.app import create_app
from ontologylab.server.jobs import TERMINAL_STATUSES

PAIR_TOPIC = "qa paired mechanism research"


def _need(
    kind: research_spec.EvidenceNeedKind,
    description: str,
    mandatory: bool,
) -> research_spec.EvidenceNeed:
    return research_spec.build_evidence_need(
        research_spec.EvidenceNeedDraft(
            kind, description, mandatory, research_spec.ContentClass.FULLTEXT
        )
    )


def _axis(
    name: str, need: research_spec.EvidenceNeed
) -> research_plan.NeedLinkedAxis:
    return research_plan.NeedLinkedAxis(
        name,
        f"{name} query",
        (name,),
        (need.need_id,),
        (),
        (("crossref", f"{name} query"),),
    )


def _reading(topic: str, broaden: bool) -> research_plan.PlannerReading:
    mechanism = _need(
        research_spec.EvidenceNeedKind.MECHANISM,
        "mechanism evidence",
        True,
    )
    if not broaden:
        return research_plan.PlannerReading(
            topic, (mechanism,), (), (_axis("mechanism", mechanism),), None
        )
    context = _need(
        research_spec.EvidenceNeedKind.CONTEXT, "context evidence", False
    )
    return research_plan.PlannerReading(
        topic,
        (mechanism, context),
        ("controlled QA assumption",),
        (_axis("context", context), _axis("mechanism", mechanism)),
        None,
    )


def _planner(
    broaden: bool,
    degraded_reason: research_plan.DegradedReason | None = None,
):
    async def plan(
        topic: str,
        engine: Engine,
        *,
        sources: tuple[str, ...],
        model: str | None = None,
        max_queries: int = 4,
    ):
        del engine, sources, model, max_queries
        reading = _reading(topic, broaden)
        if degraded_reason is not None:
            reading = research_plan.degraded_reading(
                topic, reading.axes[0], degraded_reason
            )
        return reading, {"calls": 1}

    return plan




def _document(source: str, axis: str, sequence: int, content: str) -> RawDocument:
    text = (
        "PaymentGateway validates cards through FraudDetector. "
        "FraudDetector reports to RiskEngine. "
    ) * 8
    return RawDocument(
        source_kind="paper_api",
        source_uri=f"https://example.invalid/{axis}/{sequence}",
        title=f"QA {axis}",
        raw_text=text if content == "fulltext" else f"QA {axis}",
        doi=f"10.1000/qa-{sequence}",
        source=source,
        content_kind=content,
        all_sources=(source,),
    )


def _source(mode: str):
    state = {"calls": 0}

    async def fetch(
        sources: list[str],
        query: str,
        limit: int | None = None,
        data_dir: Path | None = None,
        on_event=None,
        source_queries=None,
        search_axis: str = "",
        query_terms=(),
    ):
        del query, limit, data_dir, source_queries, query_terms
        state["calls"] += 1
        if on_event is not None:
            for source in sources:
                on_event("source_start", source, None)
        if mode == "zero":
            return [], []
        source = sources[0]
        content = "metadata_only" if mode == "metadata" else "fulltext"
        document = _document(source, search_axis or "topic", state["calls"], content)
        if on_event is not None:
            on_event("source_ok", source, 1)
        return [(source, [document])], []

    return fetch


async def _classify_execute(
    message: str, engine: Engine, model: str | None = None
) -> Intent:
    del message, engine, model
    return Intent(
        "research",
        params={"topic": PAIR_TOPIC},
        reading="compiler reading: paired mechanism research",
        interaction_decision=research_spec.InteractionDecision.EXECUTE,
    )


async def _classify_clarify(
    message: str, engine: Engine, model: str | None = None
) -> Intent:
    del message, engine, model
    return Intent(
        "research",
        params={"topic": PAIR_TOPIC},
        reading="compiler reading: ambiguous request",
        interaction_decision=research_spec.InteractionDecision.CLARIFY,
    )


async def _no_citations(
    seeds: list[RawDocument],
    *,
    data_dir: Path | None = None,
    backward_limit: int = 15,
    forward_limit: int = 15,
) -> list[RawDocument]:
    del seeds, data_dir, backward_limit, forward_limit
    return []


def _no_fulltext(
    documents: list[RawDocument],
) -> tuple[list[RawDocument], dict[str, int]]:
    return documents, {"eligible": 0, "fetched": 0}


def _join(
    app: FastAPI,
    job_id: str,
    timeout: float,
) -> research_spec.JsonObject:
    job = app.state.jobs.get(job_id)
    if job is None or job._thread is None:
        raise AssertionError("accepted research job has no worker")
    job._thread.join(timeout=timeout)
    if job._thread.is_alive() or job.status not in TERMINAL_STATUSES:
        raise TimeoutError(f"research worker did not terminate: {job_id}")
    return {"status": job.status, "error": job.error}


def _statuses(data_dir: Path) -> tuple[tuple[str, str, str], ...]:
    store = KGStore.open(paths.kg_db_path(data_dir))
    try:
        nodes = tuple(
            ("node", str(row[0]), str(row[1]))
            for row in store.conn.execute(
                "SELECT id, status FROM nodes ORDER BY id"
            )
        )
        edges = tuple(
            ("edge", str(row[0]), str(row[1]))
            for row in store.conn.execute(
                "SELECT id, status FROM edges ORDER BY id"
            )
        )
        return (*nodes, *edges)
    finally:
        store.close()


def _paired(root: Path, timeout: float) -> research_spec.JsonObject:
    data_dir, packs_dir = root / "paired-data", root / "paired-packs"
    app = create_app(data_dir=data_dir, packs_dir=packs_dir)
    with TestClient(
        app,
        base_url="http://127.0.0.1",
        client=("127.0.0.1", 50000),
    ) as client:
        if client.get("/").status_code != 200:
            raise AssertionError("dashboard session bootstrap failed")
        accepted = client.post(
            "/api/research",
            json={
                "topic": PAIR_TOPIC,
                "sources": ["crossref"],
                "max_queries": 2,
                "fulltext": False,
                "citation_expansion": False,
                "engine": "mock",
            },
        ).json()
        if set(accepted) != {"ok", "job_id", "status"} or not accepted["ok"]:
            raise AssertionError(f"direct accepted envelope drift: {accepted}")
        direct_state = _join(app, str(accepted["job_id"]), timeout)
        direct = client.get(f"/api/jobs/{accepted['job_id']}").json()
        corpus = client.get(f"/api/jobs/{accepted['job_id']}/corpus")
        if direct_state["status"] != "complete" or corpus.status_code != 200:
            raise AssertionError("direct research or corpus did not complete")
        summary = direct["research_summary"]
        if summary["current_plan_version"] != 2 or not summary["parent_plan_id"]:
            raise AssertionError("broadened plan lineage is not visible")

        chat = client.post(
            "/api/chat",
            json={"message": "research this mechanism", "engine": "mock"},
        ).json()
        if chat["reading"] != "compiler reading: paired mechanism research":
            raise AssertionError("chat compiler reading drifted")
        chat_job_id = str(chat["result"]["job_id"])
        chat_state = _join(app, chat_job_id, timeout)
        chat_detail = client.get(f"/api/jobs/{chat_job_id}").json()
        history = client.get("/api/chat/history").json()["turns"]
        if chat_state["status"] != "complete" or history[-1]["reading"] != chat["reading"]:
            raise AssertionError("chat transcript or worker drifted")
        if summary["goal"] != chat_detail["research_summary"]["goal"]:
            raise AssertionError("paired direct/chat semantics diverged")

        before_jobs = len(client.get("/api/jobs").json()["jobs"])
        with patch.object(intent_module, "classify", _classify_clarify):
            blocked = client.post(
                "/api/chat",
                json={"message": "research both things", "engine": "mock"},
            ).json()
        after_jobs = len(client.get("/api/jobs").json()["jobs"])
        if (
            blocked["result"]["interaction_decision"] != "clarify"
            or blocked["reading"] != "compiler reading: ambiguous request"
            or after_jobs != before_jobs
        ):
            raise AssertionError("ambiguous chat crossed the job boundary")

        rejected = client.post(
            "/api/research",
            json={"topic": PAIR_TOPIC, "sources": ["not-a-source"]},
        ).json()
        if set(rejected) != {"ok", "error_kind", "detail"} or rejected["error_kind"] != "rejected":
            raise AssertionError(f"direct refusal envelope drift: {rejected}")

        advisory = summary["post_extraction_counts"]
        if advisory is None or sum(advisory["support"].values()) < 1:
            raise AssertionError("post-extraction advisory is not visible")
        before = _statuses(data_dir)
        edges = client.get("/api/proposals", params={"kind": "edge"}).json()["items"]
        if not edges:
            raise AssertionError("QA corpus produced no reviewable edge")
        refused_review = client.post(
            "/api/proposals/approve",
            json={"id": edges[0]["id"], "by": "qa-reviewer"},
        )
        after = _statuses(data_dir)
        if refused_review.status_code != 409 or before != after:
            raise AssertionError("review refusal changed authority")
        proposals = client.get("/api/proposals").json()["items"]
        for item in [item for item in proposals if item["kind"] == "node"]:
            approved = client.post(
                "/api/proposals/approve",
                json={"id": item["id"], "by": "qa-reviewer"},
            )
            if approved.status_code != 200:
                raise AssertionError(
                    f"named reviewer could not approve node: {approved.text}"
                )
        for item in [item for item in proposals if item["kind"] == "edge"]:
            approved = client.post(
                "/api/proposals/approve",
                json={
                    "id": item["id"],
                    "by": "qa-reviewer",
                    "cascade": True,
                },
            )
            if approved.status_code != 200:
                raise AssertionError(
                    f"named reviewer could not approve edge: {approved.text}"
                )
        store = KGStore.open(paths.kg_db_path(data_dir))
        try:
            store.conn.execute(
                "UPDATE extraction_runs SET status = 'interrupted'"
            )
            store.conn.execute(
                "UPDATE extraction_chunks SET status = 'interrupted'"
            )
            store.conn.commit()
        finally:
            store.close()
        pack = client.post(
            "/api/packs/build",
            json={"name": "qa-refused"},
        )
        pack_body = pack.json()
        if (
            pack.status_code != 200
            or pack_body.get("ok") is not False
            or pack_body.get("error_code") != "incomplete_extraction"
        ):
            raise AssertionError(
                f"pack authority refusal contract drifted: {pack_body}"
            )
        if packs_dir.exists() and any(packs_dir.iterdir()):
            raise AssertionError("refused pack left visible output")
        return {
            "advisory_records": sum(advisory["support"].values()),
            "ambiguous_chat_jobs_created": after_jobs - before_jobs,
            "api_research_summary": summary,
            "broaden_plan_version": summary["current_plan_version"],
            "corpus_bytes": len(corpus.content),
            "direct_chat_goal_equal": True,
            "pack_refused": True,
            "review_refused": True,
        }


def _boundary(root: Path, mode: str, timeout: float) -> research_spec.JsonObject:
    data_dir = root / f"{mode}-data"
    app = create_app(data_dir=data_dir, packs_dir=root / f"{mode}-packs")
    with TestClient(
        app,
        base_url="http://127.0.0.1",
        client=("127.0.0.1", 50000),
    ) as client:
        if client.get("/").status_code != 200:
            raise AssertionError("dashboard session bootstrap failed")
        started = client.post(
            "/api/research",
            json={
                "topic": f"{mode} mechanism",
                "sources": ["crossref"],
                "max_queries": 1,
                "fulltext": False,
                "citation_expansion": False,
                "engine": "mock",
            },
        ).json()
        state = _join(app, str(started["job_id"]), timeout)
        detail = client.get(f"/api/jobs/{started['job_id']}").json()
        summary = detail["research_summary"]
        if mode == "invalid-planner":
            if state["status"] != "complete" or summary["degraded_reason"] != "invalid_output":
                raise AssertionError("invalid planner degradation is invisible")
        else:
            missing = any(
                item["mandatory"] and not item["occupied"]
                for item in summary["need_occupancy"]
            )
            if (
                state["status"] != "failed"
                or summary["stop_reason"] != "no_usable_source"
                or not missing
            ):
                raise AssertionError(f"{mode} source boundary drifted")
        return {
            "degraded_reason": summary["degraded_reason"],
            "status": state["status"],
            "stop_reason": summary["stop_reason"],
        }


def _run(timeout: float) -> research_spec.JsonObject:
    os.environ.pop("ONTOLOGYLAB_OFFLINE", None)
    with tempfile.TemporaryDirectory(prefix="ontologylab-task9-") as raw_root:
        root = Path(raw_root)
        with ExitStack() as stack:
            stack.enter_context(patch.object(research_run_module, "formulate_research_plan", _planner(True)))
            stack.enter_context(patch.object(research_run_module, "fetch_sources", _source("fulltext")))
            stack.enter_context(patch.object(research_run_module, "expand_citation_neighborhood", _no_citations))
            stack.enter_context(patch.object(research_run_module, "enrich_with_fulltext", _no_fulltext))
            stack.enter_context(patch.object(intent_module, "classify", _classify_execute))
            paired = _paired(root, timeout)
        with patch.object(research_run_module, "formulate_research_plan", _planner(False)), patch.object(
            research_run_module, "fetch_sources", _source("metadata")
        ):
            metadata = _boundary(root, "metadata", timeout)
        with patch.object(
            research_run_module,
            "formulate_research_plan",
            _planner(False, research_plan.DegradedReason.INVALID_OUTPUT),
        ), patch.object(
            research_run_module, "fetch_sources", _source("fulltext")
        ):
            invalid_planner = _boundary(root, "invalid-planner", timeout)
        with patch.object(research_run_module, "formulate_research_plan", _planner(False)), patch.object(
            research_run_module, "fetch_sources", _source("zero")
        ):
            zero_source = _boundary(root, "zero-source", timeout)
        matrix = evaluate_research_matrix(
            Path(__file__).resolve().parent.parent / "tests/fixtures/research"
        ).to_json_value()
        root_path = str(root)
    if Path(root_path).exists():
        raise AssertionError("disposable data directory leaked")
    return {
        "matrix_inventory": matrix["inventory"],
        "metadata_mechanism": metadata,
        "paired_surfaces": paired,
        "planner_invalid": invalid_planner,
        "status": "PASS",
        "temp_cleaned": True,
        "zero_source": zero_source,
    }


def _forbid(
    *args: research_spec.JsonValue,
    **kwargs: research_spec.JsonValue,
) -> None:
    del args, kwargs
    raise AssertionError("QA attempted network or process creation")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--timeout", type=float, default=30.0)
    args = parser.parse_args(argv)
    if args.timeout <= 0:
        parser.error("--timeout must be positive")
    previous = signal.getsignal(signal.SIGALRM)
    signal.signal(
        signal.SIGALRM,
        lambda _signum, _frame: (_ for _ in ()).throw(TimeoutError("QA timeout")),
    )
    signal.setitimer(signal.ITIMER_REAL, args.timeout)
    try:
        with patch.object(socket, "create_connection", _forbid), patch.object(
            subprocess, "Popen", _forbid
        ):
            receipt = _run(args.timeout)
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous)
    sys.stdout.write(
        json.dumps(
            receipt,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
