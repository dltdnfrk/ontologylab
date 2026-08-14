"""Sole read-only SQL owner for selected immutable Method pack rows."""

from __future__ import annotations

from typing import Any
import sqlite3

CAPABILITY_TABLES = frozenset({
    "compiled_method",
    "compiled_method_source",
    "methodology_publication_receipt",
})


class MethodPackSql:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def capability_tables(self) -> frozenset[str]:
        return frozenset(
            str(row[0])
            for row in self._connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' "
                "AND name IN ('compiled_method','compiled_method_source',"
                "'methodology_publication_receipt')"
            )
        )

    def publication_receipt_rows(self) -> tuple[tuple[str, str], ...]:
        return tuple(
            (str(row[0]), str(row[1]))
            for row in self._connection.execute(
                "SELECT receipt_json,receipt_hash "
                "FROM methodology_publication_receipt"
            )
        )

    def compiled_method_rows(self) -> tuple[tuple[Any, ...], ...]:
        return tuple(map(tuple, self._connection.execute(
            "SELECT release_id,method_id,version,name,canonical_json,"
            "source_index_json,compiler_receipt_json,content_hash "
            "FROM compiled_method ORDER BY method_id,release_id"
        )))

    def compiled_method_source_rows(self) -> tuple[tuple[Any, ...], ...]:
        return tuple(map(tuple, self._connection.execute(
            "SELECT release_id,method_id,field_path,document_id,"
            "document_content_hash,span_start,span_end,selected_text_hash,"
            "evidence_role,epistemic_class,statement_occurrence_id,"
            "receipt_ref FROM compiled_method_source "
            "ORDER BY method_id,release_id,field_path,"
            "statement_occurrence_id"
        )))
