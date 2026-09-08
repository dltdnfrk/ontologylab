"""Owner-only corpus artifacts emitted by one literature research job."""

from __future__ import annotations

import json
import os
from collections.abc import Sequence
from dataclasses import asdict
from pathlib import Path
from typing import Any

from ontologylab.connectors.base import RawDocument
from ontologylab.research_assessment import (
    classify_document_content,
    count_access_classes,
    document_identity,
)

CORPUS_FILENAME = "literature-corpus.jsonl"
CORPUS_SUMMARY_FILENAME = "literature-corpus-summary.json"


def _record(document: RawDocument) -> dict[str, Any]:
    return {
        "document_id": document_identity(document),
        "title": document.title,
        "doi": document.doi,
        "authors": list(document.authors),
        "year": document.year,
        "venue": document.venue,
        "cited_by": document.cited_by,
        "publication_type": document.publication_type,
        "retracted": document.retracted,
        "primary_source": document.source,
        "all_sources": list(document.all_sources),
        "source_count": document.source_count,
        "search_axes": list(document.search_axes),
        "search_queries": list(document.search_queries),
        "source_uri": document.source_uri,
        "pdf_url": document.pdf_url,
        "fulltext_url": document.fulltext_url,
        "content_kind": classify_document_content(document).value,
        "content_hash": document.content_hash,
        "text": document.raw_text,
    }


def _owner_write(path: Path, text: str) -> None:
    temp = path.with_name(f".{path.name}.tmp")
    descriptor = os.open(
        temp,
        os.O_WRONLY | os.O_CREAT | os.O_TRUNC,
        0o600,
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(text)
    except Exception:
        temp.unlink(missing_ok=True)
        raise
    os.replace(temp, path)
    path.chmod(0o600)


def write_corpus_artifacts(
    job_dir: Path,
    documents: Sequence[RawDocument],
    summary: dict[str, Any],
) -> tuple[Path, Path]:
    """Write a reusable merged corpus plus its machine-readable receipt."""
    corpus_path = job_dir / CORPUS_FILENAME
    summary_path = job_dir / CORPUS_SUMMARY_FILENAME
    lines = (
        json.dumps(_record(document), ensure_ascii=False, sort_keys=True)
        for document in documents
    )
    corpus_text = "\n".join(lines)
    if corpus_text:
        corpus_text += "\n"
    _owner_write(corpus_path, corpus_text)
    finalized_summary = {
        **summary,
        "access_class_counts": asdict(count_access_classes(documents)),
    }
    _owner_write(
        summary_path,
        json.dumps(finalized_summary, ensure_ascii=False, sort_keys=True) + "\n",
    )
    return corpus_path, summary_path
