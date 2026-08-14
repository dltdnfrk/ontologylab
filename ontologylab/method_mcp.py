"""Read-only queries over selected immutable Method pack rows."""

from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any, Mapping

from ontologylab.method_pack_contract import MethodPackError
from ontologylab.method_validation import MethodValidationError
from ontologylab.method_mcp_queries import (
    MethodCapabilityUnavailable,
    MethodDetailResult,
    MethodGapsResult,
    MethodListResult,
    MethodListRow,
    MethodQueryError,
    MethodTraceResult,
    PackProvenance,
    field_path as validate_field_path,
    json_object,
    list_inputs,
    list_row,
    method_id as validate_method_id,
    ordered_rows,
    selected_version,
    source_envelope,
)
from ontologylab.method_mcp_publication import (
    PackedPublication,
    PublicationAuthority,
    publication_authority,
)
from ontologylab.method_mcp_sql import CAPABILITY_TABLES, MethodPackSql


@dataclass(frozen=True, slots=True)
class _MethodRow:
    release_id: str
    method_id: str
    version: int
    name: str
    method: Mapping[str, Any]
    compiler_receipt: Mapping[str, Any]
    content_hash: str


@dataclass(frozen=True, slots=True)
class _PublishedRows:
    authority: PublicationAuthority
    method_rows: tuple[tuple[Any, ...], ...]
    source_rows: tuple[tuple[Any, ...], ...]


class MethodPackReader:
    """Typed, bounded queries over one already-open immutable pack."""

    def __init__(
        self,
        pack_sql: MethodPackSql,
        *,
        pack_id: str,
        pack_hash: str,
        methodology: Mapping[str, Any],
    ) -> None:
        self._sql = pack_sql
        self._methodology = methodology
        self._pack = PackProvenance(
            pack_id=pack_id,
            content_hash=pack_hash,
        )
    def _require_capability(self) -> None:
        if self._sql.capability_tables() != CAPABILITY_TABLES:
            raise MethodCapabilityUnavailable(
                "active pack does not provide methodology-v1"
            )
    def _publication(self) -> _PublishedRows:
        self._require_capability()
        receipt_rows = self._sql.publication_receipt_rows()
        if len(receipt_rows) != 1:
            raise MethodQueryError(
                "packed methodology publication receipt is ambiguous"
            )
        method_rows = self._sql.compiled_method_rows()
        source_rows = self._sql.compiled_method_source_rows()
        packed = PackedPublication(
            str(receipt_rows[0][0]),
            str(receipt_rows[0][1]),
            self._methodology,
            method_rows,
            source_rows,
        )
        try:
            authority = publication_authority(packed)
        except (
            MethodPackError,
            MethodValidationError,
            json.JSONDecodeError,
            KeyError,
        ) as exc:
            raise MethodQueryError(
                "packed publication receipt is invalid"
            ) from exc
        return _PublishedRows(authority, method_rows, source_rows)
    def _row(
        self,
        published: _PublishedRows,
        method_id: str,
    ) -> _MethodRow:
        selected = published.authority.selected(
            validate_method_id(method_id)
        )
        row = next(
            row for row in published.method_rows
            if (
                row[0],
                row[1],
                row[7],
            ) == (
                selected.release_id,
                selected.method_id,
                selected.content_hash,
            )
        )
        return _MethodRow(
            str(row[0]),
            str(row[1]),
            int(row[2]),
            str(row[3]),
            json_object(str(row[4]), "Method"),
            json_object(str(row[6]), "compiler receipt"),
            str(row[7]),
        )
    def list_methods(
        self,
        search: str | None = None,
        limit: int = 20,
    ) -> MethodListResult:
        needle = list_inputs(search, limit)
        published = self._publication()
        rows = sorted(
            published.method_rows,
            key=lambda row: (str(row[3]), str(row[1])),
        )
        methods: list[MethodListRow] = []
        for row in rows:
            method = json_object(str(row[4]), "Method")
            if needle is not None and needle not in (
                str(row[3]) + "\n" + str(row[1])
            ).casefold():
                continue
            methods.append(list_row(row, method))
            if len(methods) == limit:
                break
        return MethodListResult(
            methods=methods,
            count=len(methods),
            query=search,
            limit=limit,
            publication_receipt_hash=published.authority.receipt_hash,
            pack=self._pack,
        )
    def get_method(
        self,
        method_id: str,
        version: int | None = None,
    ) -> MethodDetailResult:
        published = self._publication()
        row = self._row(published, method_id)
        selected_version(version, row.version)
        return MethodDetailResult(
            method=row.method,
            release={
                "release_id": row.release_id,
                "method_id": row.method_id,
                "version": row.version,
                "name": row.name,
                "content_hash": row.content_hash,
                "publication_receipt_hash": (
                    published.authority.receipt_hash
                ),
            },
            compiler_receipt=row.compiler_receipt,
            publication_receipt=published.authority.receipt,
            publication_receipt_hash=published.authority.receipt_hash,
            pack=self._pack,
        )
    def trace_method(
        self,
        method_id: str,
        field_path: str | None = None,
    ) -> MethodTraceResult:
        published = self._publication()
        row = self._row(published, method_id)
        field_path = validate_field_path(field_path)
        sources: list[dict[str, Any]] = []
        for source in published.source_rows:
            if source[0] != row.release_id or source[1] != row.method_id:
                continue
            if field_path is None or source[2] == field_path:
                sources.append(source_envelope(source[2:]))
        links = ordered_rows(row.method, "links", "Method links")
        assumptions = ordered_rows(
            row.method,
            "bridge_assumptions",
            "Method bridge assumptions",
        )
        return MethodTraceResult(
            method_id=row.method_id,
            release_id=row.release_id,
            field_path=field_path,
            sources=sources,
            links=links,
            assumptions=assumptions,
            publication_receipt_hash=published.authority.receipt_hash,
            pack=self._pack,
        )
    def list_method_gaps(self, method_id: str) -> MethodGapsResult:
        published = self._publication()
        row = self._row(published, method_id)
        gaps = ordered_rows(row.method, "gaps", "Method gaps")
        return MethodGapsResult(
            method_id=row.method_id,
            release_id=row.release_id,
            gaps=gaps,
            count=len(gaps),
            publication_receipt_hash=published.authority.receipt_hash,
            pack=self._pack,
        )
