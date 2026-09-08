"""Canonical Research run orchestration.

Size exception marker: # noqa: SIZE_OK - the approved plan requires one
indivisible plan-to-post-assessment state machine with shared lineage state.
"""

from __future__ import annotations

import json
from dataclasses import replace
from types import SimpleNamespace

from ontologylab import paths, research_plan, research_spec
from ontologylab.connectors.allowlist import loggable_collect_inputs
from ontologylab.connectors.base import RawDocument, collapse_duplicates
from ontologylab.connectors.fulltext import enrich_with_fulltext
from ontologylab.connectors.paper_api import (
    SOURCE_ORDER,
    SourceFailure,
    available_sources,
    fetch_sources,
)
from ontologylab.extraction_state import effective_extractor_model
from ontologylab.extractor import (
    ENGINE_FAILURE_SUMMARY,
    ExtractionOutcome,
    extraction_decode_params,
)
from ontologylab.ingestion import (
    PartialIngestionError,
    ingest_raw_documents_batched,
)
from ontologylab.kgstore import KGStore
from ontologylab.literature import (
    ScholarlyQuery,
    corpus_summary,
    expand_citation_neighborhood,
    formulate_research_plan,
)
from ontologylab.literature_artifacts import write_corpus_artifacts
from ontologylab.post_extraction_assessment import (
    derive_post_extraction_assessment,
    post_extraction_assessment_value,
)
from ontologylab.post_extraction_store import (
    current_document_scope,
    post_extraction_input,
    snapshot_fact_ids,
)
from ontologylab.provenance import Provenance
from ontologylab.research_artifacts import ResearchArtifactStore
from ontologylab.research_assessment import (
    AcquisitionInput,
    AcquisitionRecommendation,
    AcquisitionStopReason,
    acquisition_assessment_value,
    assess_acquisition,
)
from ontologylab.research_extract import (
    ResearchExtractSession,
    extract_research_documents,
)
from ontologylab.research_run_types import (
    EngineFactory,
    ResearchRunCallbacks,
    ResearchRunInput,
    ResearchRunResult,
)
from ontologylab.safety import Caps


async def run_research(
    inputs: ResearchRunInput,
    *,
    engine_factory: EngineFactory,
    callbacks: ResearchRunCallbacks,
) -> ResearchRunResult:
    """Run one typed Research state machine from planning through assessment."""
    start_input = inputs.start_input
    job_dir = inputs.job_dir
    controls = start_input.controls
    topic = start_input.topic
    sources = list(controls.sources) or available_sources(inputs.data_dir)
    seed = controls.seed
    provenance = Provenance(str(job_dir), seed=seed)
    totals = {
        "nodes_new": 0,
        "nodes_merged": 0,
        "edges_new": 0,
        "edges_merged": 0,
    }
    provenance.log(
        "research.start",
        {
            "topic": loggable_collect_inputs([topic]),
            "sources": sources,
            "limit": controls.limit,
            "max_queries": controls.max_queries,
            "citation_expansion": controls.citation_expansion,
        },
    )

    # sqlite connections are thread-bound: the worker owns this one for
    # both phases. Route stores belong to their request's application.
    store = KGStore.open(paths.kg_db_path(inputs.data_dir))
    try:
        # ---------------- phase 1: collect ----------------
        callbacks.on_phase("collect")
        if abort_reason := callbacks.abort_reason():
            callbacks.on_progress("[ontologylab] cancelled before collecting")
            return ResearchRunResult(ExtractionOutcome(abort_reason))

        engine = engine_factory()
        effective_model = effective_extractor_model(engine, controls.model)
        callbacks.on_model_resolved(effective_model)
        reading, query_usage = await formulate_research_plan(
            topic,
            engine,
            sources=tuple(sources),
            model=effective_model,
            max_queries=controls.max_queries,
        )
        spec = start_input.compile(reading)
        initial = research_plan.create_initial_plan(
            spec_id=spec.spec_id,
            spec_hash=research_spec.research_spec_hash(spec),
            axes=(reading.axes[0],),
            source_selection=tuple(sources),
            direct_overrides=controls,
            budgets=research_plan.PlanBudgets(
                controls.max_queries,
                controls.max_engine_calls,
                controls.time_budget,
            ),
            degraded_reason=reading.degraded_reason,
        )
        artifacts = ResearchArtifactStore(job_dir, provenance)
        artifacts.write_spec(spec)
        artifacts.write_plan(initial)

        def refresh_artifact_pointers() -> None:
            pointers = artifacts.load().pointers()
            callbacks.on_artifacts_changed(pointers)

        refresh_artifact_pointers()
        provenance.log(
            "research.query",
            {
                "topic": topic,
                "spec_id": spec.spec_id,
                "plan_id": initial.plan_id,
                "usage": query_usage,
            },
        )
        if initial.degraded_reason is not None:
            callbacks.on_progress(
                "[ontologylab] planner degraded: "
                f"{initial.degraded_reason.value}; searching the topic as typed"
            )
        else:
            callbacks.on_progress(
                f"[ontologylab] planned {len(reading.axes)} API query axis/axes"
            )

        by_source: dict[str, list[RawDocument]] = {}
        failures: list[SourceFailure] = []
        pending_axes = list(reading.axes[1:])
        lineage = [initial]
        current_plan = initial
        executed_plan_ids: tuple[str, ...] = ()
        executed_query_keys: set[tuple[str, str]] = set()
        executed_axis_labels: set[str] = set()
        executed_queries: list[ScholarlyQuery] = []
        raw_count = 0
        citation_expanded = False
        raw_docs: list[RawDocument] = []
        fulltext_cache: dict[str, RawDocument] = {}
        final_assessment = None

        def axis_queries(
            axis: research_plan.NeedLinkedAxis,
        ) -> tuple[ScholarlyQuery, dict[str, str], set[tuple[str, str]]]:
            query = ScholarlyQuery(axis.query, axis.axis, axis.terms)
            explicit = dict(axis.source_queries)
            rendered = {
                source: explicit.get(source, query.for_source(source))
                for source in sources
            }
            keys = {
                (
                    source.casefold(),
                    " ".join(value.split()).casefold(),
                )
                for source, value in rendered.items()
            }
            return query, rendered, keys

        while True:
            executed_plan_ids = research_plan.authorize_execution(
                current_plan, executed_plan_ids
            )
            for axis in current_plan.axes:
                query, rendered, keys = axis_queries(axis)
                axis_sources = [
                    source
                    for source in sources
                    if (
                        source.casefold(),
                        " ".join(rendered[source].split()).casefold(),
                    )
                    not in executed_query_keys
                ]
                if not axis_sources:
                    continue
                callbacks.on_progress(
                    f"[ontologylab] searching {axis.axis}: {axis.query}"
                )
                query_batches, query_failures = await fetch_sources(
                    axis_sources,
                    axis.query,
                    controls.limit,
                    inputs.data_dir,
                    on_event=callbacks.on_source_event,
                    source_queries={
                        source: rendered[source] for source in axis_sources
                    },
                    search_axis=axis.axis,
                    query_terms=axis.terms,
                )
                for source, documents in query_batches:
                    attributed = [
                        replace(
                            document,
                            search_axis=(
                                document.search_axis or axis.axis
                            ),
                            search_query=(
                                document.search_query or axis.query
                            ),
                            search_axes=(
                                tuple(dict.fromkeys(
                                    (*document.search_axes, axis.axis)
                                ))
                            ),
                            search_queries=(
                                tuple(dict.fromkeys(
                                    (*document.search_queries, axis.query)
                                ))
                            ),
                        )
                        for document in documents
                    ]
                    by_source.setdefault(source, []).extend(attributed)
                failures.extend(query_failures)
                executed_query_keys.update(keys)
                executed_axis_labels.add(
                    " ".join(axis.axis.split()).casefold()
                )
                executed_queries.append(query)
                raw_count += sum(
                    len(documents)
                    for _source, documents in query_batches
                )

            batch_order = (
                *SOURCE_ORDER,
                *(
                    source
                    for source in by_source
                    if source not in SOURCE_ORDER
                ),
            )
            batches = [
                (source, by_source[source])
                for source in batch_order
                if source in by_source
            ]
            raw_docs = collapse_duplicates(batches, SOURCE_ORDER)
            if (
                not citation_expanded
                and controls.citation_expansion
                and controls.citation_seed_count > 0
                and "openalex" in sources
                and raw_docs
            ):
                seeds = sorted(
                    raw_docs,
                    key=lambda document: (
                        document.cited_by or 0,
                        len(document.raw_text),
                    ),
                    reverse=True,
                )[: controls.citation_seed_count]
                expanded = await expand_citation_neighborhood(
                    seeds,
                    data_dir=inputs.data_dir,
                    backward_limit=controls.citation_limit,
                    forward_limit=controls.citation_limit,
                )
                citation_expanded = True
                if expanded:
                    by_source.setdefault("openalex", []).extend(expanded)
                    raw_count += len(expanded)
                    batches = [
                        (source, by_source[source])
                        for source in batch_order
                        if source in by_source
                    ]
                    raw_docs = collapse_duplicates(batches, SOURCE_ORDER)
                    callbacks.on_progress(
                        "[ontologylab] citation graph added "
                        f"{len(expanded)} record(s)"
                    )

            if controls.fulltext:
                uncached = [
                    document
                    for document in raw_docs
                    if (
                        document.dedupe_key not in fulltext_cache
                        or (
                            document.fulltext_url
                            and not fulltext_cache[document.dedupe_key].fulltext_url
                            and fulltext_cache[document.dedupe_key].content_kind != "fulltext"
                        )
                    )
                ]
                enriched, ft_stats = enrich_with_fulltext(uncached)
                fulltext_cache.update(
                    {document.dedupe_key: document for document in enriched}
                )
                raw_docs = [
                    (
                        replace(
                            document,
                            raw_text=fulltext_cache[
                                document.dedupe_key
                            ].raw_text,
                            content_kind=fulltext_cache[
                                document.dedupe_key
                            ].content_kind,
                        )
                        if document.dedupe_key in fulltext_cache
                        else document
                    )
                    for document in raw_docs
                ]
                provenance.log("collect.fulltext", ft_stats)
                if ft_stats["eligible"]:
                    callbacks.on_progress(
                        "[ontologylab] full text for "
                        f"{ft_stats['fetched']}/{ft_stats['eligible']} "
                        "open-access document(s)"
                    )

            if abort_reason := callbacks.abort_reason():
                callbacks.on_progress(
                    "[ontologylab] cancelled before storing documents"
                )
                return ResearchRunResult(ExtractionOutcome(abort_reason))

            remaining_slots = max(
                0, controls.max_queries - len(executed_axis_labels)
            )
            novel_candidates = []
            for axis in pending_axes:
                _query, _rendered, keys = axis_queries(axis)
                label = " ".join(axis.axis.split()).casefold()
                if (
                    label not in executed_axis_labels
                    and keys.isdisjoint(executed_query_keys)
                ):
                    novel_candidates.append(axis)
            can_broaden = (
                current_plan.plan_version == 1
                and remaining_slots > 0
                and bool(novel_candidates)
            )
            assessment = assess_acquisition(
                AcquisitionInput(
                    spec,
                    current_plan,
                    tuple(raw_docs),
                    tuple(failures),
                    remaining_slots,
                    1 if can_broaden else 0,
                    tuple(lineage[:-1]),
                )
            )
            missing_ids = tuple(
                item.need_id
                for item in assessment.need_occupancy
                if item.mandatory and not item.occupied
            )
            valid_candidates = [
                axis
                for axis in novel_candidates
                if set(axis.need_ids) <= set(missing_ids)
            ]
            if (
                assessment.recommendation
                is AcquisitionRecommendation.BROADEN
                and not valid_candidates
            ):
                assessment = assess_acquisition(
                    AcquisitionInput(
                        spec,
                        current_plan,
                        tuple(raw_docs),
                        tuple(failures),
                        remaining_slots,
                        0,
                        tuple(lineage[:-1]),
                    )
                )
            artifacts.write_acquisition(
                current_plan,
                acquisition_assessment_value(assessment),
            )
            refresh_artifact_pointers()
            if (
                assessment.recommendation
                is AcquisitionRecommendation.BROADEN
            ):
                successor_axis = valid_candidates[0]
                successor = research_plan.broaden_plan(
                    current_plan,
                    (successor_axis,),
                    missing_ids,
                    tuple(lineage),
                )
                artifacts.write_plan(successor)
                lineage.append(successor)
                current_plan = successor
                pending_axes.remove(successor_axis)
                refresh_artifact_pointers()
                continue
            final_assessment = assessment
            break

        for failure in failures:
            provenance.log(
                "research.source_failed",
                {
                    "source": failure.source,
                    "kind": failure.kind,
                    "error": failure.error,
                },
            )
        assessment_value = acquisition_assessment_value(final_assessment)
        retrieval_summary = corpus_summary(
            raw_count=raw_count,
            documents=raw_docs,
            queries=executed_queries,
            assessment=assessment_value,
        )
        provenance.log("research.corpus", retrieval_summary)
        callbacks.on_progress(
            f"[ontologylab] collected {len(raw_docs)} document(s) from "
            f"{len(by_source)} source(s)"
        )
        corpus_path, _summary_path = write_corpus_artifacts(
            job_dir, raw_docs, retrieval_summary
        )
        provenance.log(
            "research.corpus_artifact",
            {
                "file": corpus_path.name,
                "documents": len(raw_docs),
            },
        )
        callbacks.on_progress(
            f"[ontologylab] reusable corpus: {corpus_path.name}"
        )
        if (
            final_assessment.stop_reason
            is AcquisitionStopReason.BUDGET_EXHAUSTED
        ):
            callbacks.on_progress(
                "[ontologylab] acquisition warning: budget_exhausted; "
                "extracting useful partial full text"
            )

        fetched_docs = tuple(
            document
            for documents in by_source.values()
            for document in documents
        )
        try:
            result = ingest_raw_documents_batched(
                store,
                raw_docs,
                provenance,
                should_cancel=lambda: bool(callbacks.abort_reason()),
            )
        except PartialIngestionError as exc:
            callbacks.on_progress(
                "[ontologylab] ingestion stopped after "
                f"{exc.completed_batches} committed batch(es)"
            )
            if exc.kind == "cancelled":
                return ResearchRunResult(
                    ExtractionOutcome(callbacks.abort_reason())
                )
            raise
        doc_ids = result.document_ids
        callbacks.on_progress(
            f"[ontologylab] stored {result.created_count} new document(s), "
            f"{result.duplicate_count} already known"
        )

        if (
            final_assessment.recommendation
            is AcquisitionRecommendation.STOP
        ):
            reason = final_assessment.stop_reason
            callbacks.on_progress(
                "[ontologylab] no usable source; research stopped: "
                f"{reason.value if reason is not None else 'no_usable_source'}"
            )
            provenance.log(
                "research.end",
                {
                    "documents": len(raw_docs),
                    "created": result.created_count,
                    "stop_reason": (
                        reason.value if reason is not None else None
                    ),
                },
            )
            return ResearchRunResult(None)

        if not doc_ids:
            callbacks.on_progress("[ontologylab] nothing collected; no extraction to run")
            return ResearchRunResult(ExtractionOutcome(""))

        # ---------------- phase 2: extract ----------------
        callbacks.on_phase("extract")
        if abort_reason := callbacks.abort_reason():
            callbacks.on_progress("[ontologylab] cancelled before extracting")
            return ResearchRunResult(ExtractionOutcome(abort_reason))

        # `doc_ids` is passed explicitly and is never allowed to fall back
        # to `unprocessed_doc_ids(store)`. That query is global: it would
        # pull in documents from older runs and from any run executing
        # right now, spending this topic's budget on them.
        #
        # The time budget is measured from the extraction's own start.
        # `Caps` reads the clock from `provenance.elapsed_s`, which runs
        # from the job's creation — five paper APIs at a 30s timeout
        # could otherwise consume the extraction budget before the first
        # chunk, and the run would report itself budget-exhausted having
        # extracted nothing.
        caps = Caps(
            SimpleNamespace(
                iterations=0,
                time_budget_s=controls.time_budget + provenance.elapsed_s,
                max_engine_calls=controls.max_engine_calls,
            )
        )
        provenance.log(
            "extract.start",
            {
                "engine": controls.engine,
                "model": effective_model,
                "doc_ids": list(doc_ids),
            },
        )

        def _accumulate(stats: dict[str, int]) -> None:
            for key in totals:
                totals[key] += stats.get(key, 0)
            callbacks.on_stats(stats)

        decode = extraction_decode_params(engine)
        before_facts = snapshot_fact_ids(store)
        document_scope = current_document_scope(store, tuple(doc_ids))
        stopped_reason = await extract_research_documents(
            store,
            tuple(doc_ids),
            ResearchExtractSession(
                engine=engine,
                provenance=provenance,
                caps=caps,
                extractor_engine=controls.engine,
                extractor_model=effective_model or "",
                on_progress=callbacks.on_progress,
                on_stats=_accumulate,
                should_abort=callbacks.abort_reason,
                decode_params_json=(
                    json.dumps(decode, sort_keys=True) if decode else "{}"
                ),
                raw_documents=fetched_docs,
            ),
        )
        post_assessment = derive_post_extraction_assessment(
            post_extraction_input(store, before_facts, document_scope)
        )
        post_pointer = artifacts.write_post_extraction(
            current_plan,
            post_extraction_assessment_value(post_assessment),
        )
        refresh_artifact_pointers()
        provenance.log(
            "research.post_extraction",
            {
                "assessment_hash": post_assessment.assessment_hash,
                "artifact_id": post_pointer.artifact_id,
                "content_hash": post_pointer.content_hash,
            },
        )

        provenance.log(
            "research.end",
            {"documents": len(raw_docs), "created": result.created_count,
             "totals": totals, "stopped": stopped_reason},
        )
        if stopped_reason:
            callbacks.on_progress(f"[ontologylab] extraction stopped early: {stopped_reason}")
        if stopped_reason.chunk_failed:
            callbacks.on_progress(
                f"[ontologylab] research failed: {ENGINE_FAILURE_SUMMARY}"
            )
        else:
            callbacks.on_progress(
                f"[ontologylab] research done: {totals['nodes_new']} new nodes, "
                f"{totals['edges_new']} new edges (proposed; review to verify)"
            )
        return ResearchRunResult(stopped_reason)
    finally:
        store.close()
