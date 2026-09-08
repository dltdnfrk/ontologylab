"""Deterministic same-work merge for multi-source literature batches."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace
from typing import Any

from ontologylab.connectors.base import RawDocument

_Entry = tuple[str, int, RawDocument]


def _ordered_values(
    entries: Sequence[_Entry],
    plural: str,
    singular: str,
) -> tuple[str, ...]:
    values: list[str] = []
    for source_name, _arrival, document in entries:
        candidates = getattr(document, plural)
        if not candidates:
            value = getattr(document, singular)
            if singular == "source":
                candidates = (value or source_name,)
            else:
                candidates = (value,) if value else ()
        for value in candidates:
            if value and value not in values:
                values.append(value)
    return tuple(values)


def _first(entries: Sequence[_Entry], field: str) -> Any:
    return next(
        (
            value
            for _source, _arrival, document in entries
            if (value := getattr(document, field))
        ),
        None,
    )


def _merge_group(
    group: Sequence[_Entry],
    rank: dict[str, int],
) -> tuple[int, RawDocument]:
    unranked = len(rank)
    _source, _arrival, winner = min(
        group,
        key=lambda entry: (
            -len(entry[2].raw_text),
            rank.get(entry[0], unranked),
            entry[1],
        ),
    )
    ordered = sorted(
        group,
        key=lambda entry: (rank.get(entry[0], unranked), entry[1]),
    )
    sources = _ordered_values(ordered, "all_sources", "source")
    axes = _ordered_values(ordered, "search_axes", "search_axis")
    queries = _ordered_values(ordered, "search_queries", "search_query")
    cited = [
        document.cited_by
        for _source, _arrival, document in group
        if document.cited_by is not None
    ]
    retractions = [
        document.retracted
        for _source, _arrival, document in group
        if document.retracted is not None
    ]
    authors = max(
        (document.authors for _source, _arrival, document in group),
        key=len,
        default=(),
    )
    return (
        min(entry[1] for entry in group),
        replace(
            winner,
            all_sources=sources,
            search_axes=axes,
            search_queries=queries,
            authors=authors,
            year=_first(ordered, "year"),
            venue=_first(ordered, "venue"),
            cited_by=max(cited) if cited else None,
            publication_type=_first(ordered, "publication_type"),
            retracted=(
                True if True in retractions
                else False if retractions
                else None
            ),
            pdf_url=_first(ordered, "pdf_url"),
            fulltext_url=_first(ordered, "fulltext_url"),
        ),
    )


def merge_document_batches(
    batches: Sequence[tuple[str, Sequence[RawDocument]]],
    source_order: Sequence[str] = (),
) -> list[RawDocument]:
    """Keep richest bytes and merge metadata, independent of arrival."""
    rank = {name: index for index, name in enumerate(source_order)}
    grouped: dict[str, list[_Entry]] = {}
    arrival = 0
    for source_name, documents in batches:
        for document in documents:
            grouped.setdefault(document.dedupe_key, []).append(
                (source_name, arrival, document)
            )
            arrival += 1
    merged = [
        _merge_group(group, rank)
        for group in grouped.values()
    ]
    return [document for _arrival, document in sorted(merged)]
