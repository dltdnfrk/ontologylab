"""Method publication SQL and exact source-row validation."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sqlite3
from typing import Any, Mapping, Sequence

from ontologylab.method_pack_contract import MethodPackError
from ontologylab.method_compiler_gates import canonical_hash
from ontologylab.method_store import MethodStore, MethodUnitOfWork


class MethodPackSql:
    """All Method publication SQL at the Task 7 ownership boundary."""

    def __init__(
        self,
        source: sqlite3.Connection,
        target: sqlite3.Connection | None = None,
        *,
        source_root: Path | None = None,
        snapshot_path: Path | None = None,
    ) -> None:
        self._source = source
        self._source.row_factory = sqlite3.Row
        self._target = target
        database = Path(str(source.execute(
            "SELECT file FROM pragma_database_list WHERE name='main'"
        ).fetchone()[0]))
        self._source_root = source_root or database.parent
        self._snapshot_path = snapshot_path or database

    def release(self, release_id: str) -> Sequence[Any] | None:
        columns = (
            "id,workspace_id,method_id,version,canonical_json,"
            "source_index_json,content_hash,compiler_version,"
            "input_snapshot_hash,gate_receipt_json,review_receipt_json,"
            "compiler_receipt_json,compiler_receipt_hash,attempt_id,created_ts"
        )
        return self._source.execute(
            f"SELECT {columns} FROM method_release WHERE id=?",
            (release_id,),
        ).fetchone()

    def gates(self, attempt_id: str) -> Sequence[Sequence[Any]]:
        return self._source.execute(
            "SELECT gate_id,passed,reasons_json,compiler_receipt_hash,"
            "compiler_receipt_json FROM method_compilation_gate "
            "WHERE attempt_id=? ORDER BY gate_id",
            (attempt_id,),
        ).fetchall()

    def attempt(self, attempt_id: str) -> Sequence[Any] | None:
        return self._source.execute(
            "SELECT passed,release_id,workspace_id,compiler_version,"
            "input_snapshot_hash,gate_receipt_json,compiler_receipt_json,"
            "compiler_receipt_hash FROM method_compilation_attempt WHERE id=?",
            (attempt_id,),
        ).fetchone()

    def snapshot_hash(self, workspace_id: str) -> str:
        with MethodUnitOfWork(self._source) as uow:
            snapshot = MethodStore(
                self._source, uow
            ).read_compilation_snapshot(workspace_id)
        return snapshot.content_hash

    def source_snapshot_hash(self) -> str:
        return "sha256:" + hashlib.sha256(
            self._snapshot_path.read_bytes()
        ).hexdigest()

    def validate_source(
        self,
        workspace_id: str,
        source: Mapping[str, Any],
    ) -> tuple[str, str, str, str]:
        occurrence_id = str(source.get("occurrence_id"))
        row = self._source.execute(
            "SELECT * FROM statement_occurrence WHERE id=?",
            (occurrence_id,),
        ).fetchone()
        if row is None:
            raise MethodPackError("missing statement occurrence")
        if row["workspace_id"] != workspace_id:
            raise MethodPackError("statement occurrence workspace mismatch")
        if (
            row["document_id"] != source.get("document_id")
            or row["document_content_hash"]
            != source.get("document_content_hash")
        ):
            raise MethodPackError("statement occurrence document mismatch")
        if (
            row["span_start"] != source.get("span_start")
            or row["span_end"] != source.get("span_end")
            or row["selected_text_hash"] != source.get("selected_text_hash")
            or row["status"] != "accepted"
        ):
            raise MethodPackError("statement occurrence selector mismatch")
        document = self._source.execute(
            "SELECT content_hash,raw_text_path FROM documents WHERE id=?",
            (row["document_id"],),
        ).fetchone()
        if (
            document is None
            or document["content_hash"] != row["document_content_hash"]
        ):
            raise MethodPackError("statement occurrence current source mismatch")
        raw_path = (self._source_root / document["raw_text_path"]).resolve()
        if self._source_root.resolve() not in raw_path.parents:
            raise MethodPackError("statement occurrence source path escapes root")
        try:
            raw = raw_path.read_bytes()
            text = raw.decode("utf-8")
        except (OSError, UnicodeError) as exc:
            raise MethodPackError(
                "statement occurrence current source is unavailable"
            ) from exc
        if (
            "sha256:" + hashlib.sha256(raw).hexdigest()
            != document["content_hash"]
        ):
            raise MethodPackError("statement occurrence current source mismatch")
        start, end = int(row["span_start"]), int(row["span_end"])
        selected = text[start:end]
        selected_hash = "sha256:" + hashlib.sha256(
            selected.encode("utf-8")
        ).hexdigest()
        if (
            selected != row["statement_text"]
            or selected_hash != row["selected_text_hash"]
        ):
            raise MethodPackError("statement occurrence selector mismatch")
        policy_id, policy_version = self._validate_policy(row)
        review = self._source.execute(
            "SELECT decision FROM method_review_event "
            "WHERE id=? AND workspace_id=? AND subject_kind='occurrence' "
            "AND subject_id=?",
            (source.get("receipt_ref"), workspace_id, occurrence_id),
        ).fetchone()
        if review is None or review["decision"] != "accepted":
            raise MethodPackError("statement occurrence review receipt mismatch")
        occurrence = dict(row)
        return (
            policy_id,
            policy_version,
            canonical_hash(occurrence),
            canonical_hash(["occurrences", occurrence]),
        )

    def validate_policy_snapshot(
        self,
        workspace_id: str,
        snapshot_id: str,
        policy_version: str,
    ) -> None:
        rows = self._source.execute(
            "SELECT DISTINCT p.id,s.policy_version "
            "FROM document_policy_snapshot p "
            "JOIN source_policy s ON s.id=p.source_policy_id "
            "LEFT JOIN method_extraction_runs r ON r.policy_snapshot_id=p.id "
            "LEFT JOIN statement_occurrence o ON "
            "o.document_id=p.document_id AND "
            "o.document_content_hash=p.document_content_hash "
            "WHERE p.id=? AND (r.workspace_id=? OR o.workspace_id=?)",
            (snapshot_id, workspace_id, workspace_id),
        ).fetchall()
        if len(rows) != 1 or tuple(rows[0]) != (
            snapshot_id,
            policy_version,
        ):
            raise MethodPackError("compiler policy receipt is stale")

    def accepted_object_hashes(
        self,
        workspace_id: str,
        object_id: str,
    ) -> tuple[str, str]:
        matches: list[tuple[str, Mapping[str, Any]]] = []
        for name, table, status_field, status in (
            ("occurrences", "statement_occurrence", "status", "accepted"),
            ("fragments", "method_fragment", "status", "accepted"),
            ("links", "method_link", "status", "accepted"),
            (
                "bridges",
                "bridge_proposal",
                "decision_status",
                "accepted_as_assumption",
            ),
        ):
            row = self._source.execute(
                f"SELECT * FROM {table} WHERE id=? AND workspace_id=? "
                f"AND {status_field}=?",
                (object_id, workspace_id, status),
            ).fetchone()
            if row is not None:
                matches.append((name, dict(row)))
        if len(matches) != 1:
            raise MethodPackError("compiler accepted-object receipt is stale")
        name, row = matches[0]
        return canonical_hash(row), canonical_hash([name, row])

    def _validate_policy(self, occurrence: sqlite3.Row) -> tuple[str, str]:
        policies = self._source.execute(
            "SELECT p.id,s.policy_version,p.resolution_status,"
            "s.allowed_extract,s.allowed_pack,s.allowed_processors_json,"
            "s.allowed_regions_json FROM document_policy_snapshot p "
            "JOIN source_policy s ON s.id=p.source_policy_id "
            "WHERE p.document_id=? AND p.document_content_hash=?",
            (
                occurrence["document_id"],
                occurrence["document_content_hash"],
            ),
        ).fetchall()
        if len(policies) != 1:
            raise MethodPackError("statement occurrence policy selector mismatch")
        policy = policies[0]
        if (
            policy["resolution_status"] != "resolved"
            or policy["allowed_extract"] != 1
            or policy["allowed_pack"] != 1
            or "local" not in json.loads(policy["allowed_processors_json"])
            or "local" not in json.loads(policy["allowed_regions_json"])
        ):
            raise MethodPackError("statement occurrence policy selector mismatch")
        return str(policy["id"]), str(policy["policy_version"])

    def _write(self) -> sqlite3.Connection:
        if self._target is None:
            raise MethodPackError("pack target connection is unavailable")
        return self._target

    def create_tables(self) -> None:
        self._write().executescript(
            """
            CREATE TABLE compiled_method (
              release_id TEXT PRIMARY KEY, method_id TEXT NOT NULL UNIQUE,
              version INTEGER NOT NULL, name TEXT NOT NULL,
              canonical_json TEXT NOT NULL, source_index_json TEXT NOT NULL,
              compiler_receipt_json TEXT NOT NULL, content_hash TEXT NOT NULL
            );
            CREATE TABLE compiled_method_source (
              release_id TEXT NOT NULL REFERENCES compiled_method(release_id),
              method_id TEXT NOT NULL, field_path TEXT NOT NULL,
              document_id TEXT NOT NULL, document_content_hash TEXT NOT NULL,
              span_start INTEGER NOT NULL, span_end INTEGER NOT NULL,
              selected_text_hash TEXT NOT NULL, evidence_role TEXT NOT NULL,
              epistemic_class TEXT NOT NULL,
              statement_occurrence_id TEXT NOT NULL, receipt_ref TEXT NOT NULL,
              PRIMARY KEY (
                release_id, field_path, statement_occurrence_id
              )
            );
            CREATE TABLE methodology_publication_receipt (
              receipt_json TEXT NOT NULL, receipt_hash TEXT NOT NULL
            );
            """
        )

    def insert_releases(self, rows: Sequence[Sequence[Any]]) -> None:
        self._write().executemany(
            "INSERT INTO compiled_method VALUES (?,?,?,?,?,?,?,?)",
            rows,
        )

    def insert_sources(self, rows: Sequence[Sequence[Any]]) -> None:
        self._write().executemany(
            "INSERT INTO compiled_method_source VALUES "
            "(?,?,?,?,?,?,?,?,?,?,?,?)",
            rows,
        )

    def insert_publication_receipt(
        self,
        receipt_json: str,
        receipt_hash: str,
    ) -> None:
        self._write().execute(
            "INSERT INTO methodology_publication_receipt VALUES (?,?)",
            (receipt_json, receipt_hash),
        )
