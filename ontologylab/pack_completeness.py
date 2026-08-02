"""Pure extraction-completeness policy for immutable pack builds."""

from __future__ import annotations

import sqlite3
from collections import Counter
from typing import Any


_STREAMS_SQL = """
SELECT DISTINCT
    f.source_doc_id AS document_id,
    d.content_hash AS document_content_hash,
    f.schema_version_id,
    f.extractor_engine,
    COALESCE(f.extractor_model, '') AS extractor_model,
    COALESCE(f.prompt_version, '') AS prompt_version,
    COALESCE(f.decode_params, 'null') AS decode_params
FROM (
    SELECT source_doc_id, schema_version_id, extractor_engine,
           extractor_model, prompt_version, decode_params
    FROM nodes WHERE status = 'verified'
    UNION ALL
    SELECT source_doc_id, schema_version_id, extractor_engine,
           extractor_model, prompt_version, decode_params
    FROM edges
    WHERE status = 'verified' AND invalidated_ts IS NULL
) AS f
JOIN documents d ON d.id = f.source_doc_id
ORDER BY document_id, schema_version_id, extractor_engine, extractor_model,
         prompt_version, decode_params
"""

_RUNS_SQL = """
SELECT id, status
FROM extraction_runs
WHERE document_id = ? AND document_content_hash = ? AND schema_version_id = ?
  AND extractor_engine = ? AND extractor_model = ? AND prompt_version = ?
  AND decode_params = ?
ORDER BY created_ts, id
"""


def extraction_completeness(conn: sqlite3.Connection) -> dict[str, Any]:
    """Summarize durable lifecycle state for exact streams of shipped rows.

    A stream is identified by document content, schema, engine/model, prompt,
    and canonical decode parameters. Runs from other documents or streams are
    intentionally invisible to this policy.
    """
    streams = conn.execute(_STREAMS_SQL).fetchall()
    if not streams:
        return _summary(status="not_applicable")

    run_counts: Counter[str] = Counter()
    chunk_counts: Counter[str] = Counter()
    unknown: list[dict[str, Any]] = []
    incomplete = False

    for stream in streams:
        values = tuple(stream)
        runs = conn.execute(_RUNS_SQL, values).fetchall()
        if not runs:
            unknown.append(_stream_dict(values))
            incomplete = True
            continue
        stream_satisfied = False
        for run in runs:
            run_counts[run["status"]] += 1
            chunks = conn.execute(
                "SELECT status, COUNT(*) AS count FROM extraction_chunks "
                "WHERE run_id = ? GROUP BY status ORDER BY status",
                (run["id"],),
            ).fetchall()
            chunks_succeeded = True
            for chunk in chunks:
                chunk_counts[chunk["status"]] += chunk["count"]
                if chunk["status"] != "succeeded":
                    chunks_succeeded = False
            if run["status"] == "complete" and chunks_succeeded:
                stream_satisfied = True
        if not stream_satisfied:
            incomplete = True

    return _summary(
        status="incomplete" if incomplete else "complete",
        streams=streams,
        unknown=unknown,
        run_counts=run_counts,
        chunk_counts=chunk_counts,
    )


def with_override(
    summary: dict[str, Any], *, used: bool, operator_intent: str | None
) -> dict[str, Any]:
    """Return a manifest-ready copy with its operator decision attached."""
    return {
        **summary,
        "override": {"used": used, "operator_intent": operator_intent},
    }


def _summary(
    *,
    status: str,
    streams: list[Any] | None = None,
    unknown: list[dict[str, Any]] | None = None,
    run_counts: Counter[str] | None = None,
    chunk_counts: Counter[str] | None = None,
) -> dict[str, Any]:
    streams = streams or []
    return {
        "status": status,
        "relevant_stream_count": len(streams),
        "relevant_document_ids": sorted({row[0] for row in streams}),
        "unknown_streams": unknown or [],
        "run_status_counts": dict(sorted((run_counts or {}).items())),
        "chunk_status_counts": dict(sorted((chunk_counts or {}).items())),
    }


def _stream_dict(values: tuple[Any, ...]) -> dict[str, Any]:
    keys = (
        "document_id",
        "document_content_hash",
        "schema_version_id",
        "extractor_engine",
        "extractor_model",
        "prompt_version",
        "decode_params",
    )
    return dict(zip(keys, values, strict=True))
