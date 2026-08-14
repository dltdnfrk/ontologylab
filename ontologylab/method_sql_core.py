"""Explicit SQLite operations for Method lifecycle and human commands."""

from __future__ import annotations

import dataclasses
from pathlib import Path
import sqlite3
from typing import Any, Protocol

from ontologylab import method_validation as mv
from ontologylab.method_commands import DecisionKind, DecisionSubject


class _Connection(Protocol):
    def execute(
        self,
        sql: str,
        parameters: tuple[Any, ...] = (),
        /,
    ) -> sqlite3.Cursor:
        ...

class _Ownership(Protocol):
    @property
    def active(self) -> bool:
        ...

    def owns(self, connection: object, /) -> bool:
        ...


_SELECT_DOCUMENT = """
SELECT content_hash, raw_text_path FROM documents WHERE id=?
"""
_DATABASE_LIST = """
PRAGMA database_list
"""
_WORKSPACE_EXISTS = """
SELECT 1 FROM method_workspace WHERE id=?
"""
_INSERT_SOURCE_POLICY = """
INSERT INTO source_policy VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
"""
_INSERT_DOCUMENT_POLICY = """
INSERT INTO document_policy_snapshot VALUES (?,?,?,?,?,?,?)
"""
_INSERT_WORKSPACE = """
INSERT INTO method_workspace VALUES (?,?,?,?,?,?,?,?)
"""
_INSERT_FRAGMENT = """
INSERT INTO method_fragment VALUES (?,?,?,?,?,?,?,?,?)
"""
_SELECT_FRAGMENT_EPISTEMIC = """
SELECT epistemic_class FROM method_fragment WHERE id=?
"""
_INSERT_FRAGMENT_EVIDENCE = """
INSERT INTO method_fragment_evidence VALUES (?,?,?,?,?,?)
"""
_INSERT_LINK = """
INSERT INTO method_link VALUES (?,?,?,?,?,?,?,?)
"""
_SELECT_GAP_WORKSPACE = """
SELECT workspace_id FROM method_gap WHERE id=?
"""
_SELECT_FRAGMENT_WORKSPACE = """
SELECT workspace_id FROM method_fragment WHERE id=?
"""
_UPSERT_GAP = """
INSERT INTO method_gap VALUES (?,?,?,?,?,?,?,?,?,'open',?,?)
ON CONFLICT(id) DO UPDATE SET
  gap_class=excluded.gap_class,
  target_fragment_id=excluded.target_fragment_id,
  field_path=excluded.field_path,
  detector_id=excluded.detector_id,
  detector_version=excluded.detector_version,
  input_snapshot_hash=excluded.input_snapshot_hash,
  detail_json=excluded.detail_json,
  updated_ts=excluded.updated_ts
"""
_INSERT_BRIDGE = """
INSERT INTO bridge_proposal VALUES
(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
"""
_INSERT_COUNTER_SEARCH = """
INSERT INTO method_counter_evidence_search VALUES (?,?,?,?,?,?,?,?,?,?)
"""
_INSERT_BRIDGE_EVIDENCE = """
INSERT INTO bridge_evidence VALUES (?,?,?,?,?)
"""
_SELECT_DECISION_SUBJECT = """
SELECT workspace_id, status FROM statement_occurrence
 WHERE ?='occurrence' AND id=?
UNION ALL SELECT workspace_id, status FROM method_fragment
 WHERE ?='fragment' AND id=?
UNION ALL SELECT workspace_id, status FROM method_link
 WHERE ?='link' AND id=?
UNION ALL SELECT workspace_id, decision_status FROM bridge_proposal
 WHERE ?='bridge' AND id=?
UNION ALL SELECT workspace_id, status FROM method_gap
 WHERE ?='gap' AND id=?
"""
_SELECT_BRIDGE_COUNTER = """
SELECT 1 FROM method_counter_evidence_search
WHERE workspace_id=? AND gap_id=(
  SELECT gap_id FROM bridge_proposal WHERE id=?
) AND bridge_id=?
"""
_INSERT_REVIEW_EVENT = """
INSERT INTO method_review_event VALUES (?,?,?,?,?,?,?,?)
"""
_UPDATE_OCCURRENCE_DECISION = """
UPDATE statement_occurrence SET status=? WHERE id=? AND status=?
"""
_UPDATE_FRAGMENT_DECISION = """
UPDATE method_fragment SET status=? WHERE id=? AND status=?
"""
_UPDATE_LINK_DECISION = """
UPDATE method_link SET status=? WHERE id=? AND status=?
"""
_UPDATE_BRIDGE_DECISION = """
UPDATE bridge_proposal SET decision_status=? WHERE id=? AND decision_status=?
"""
_UPDATE_GAP_DECISION = """
UPDATE method_gap SET status=? WHERE id=? AND status=?
"""
_DECISION_UPDATES: dict[DecisionKind, str] = {
    "occurrence": _UPDATE_OCCURRENCE_DECISION,
    "fragment": _UPDATE_FRAGMENT_DECISION,
    "link": _UPDATE_LINK_DECISION,
    "bridge": _UPDATE_BRIDGE_DECISION,
    "gap": _UPDATE_GAP_DECISION,
}


class _MethodSqlCore:
    """Typed lifecycle, validation, and human-command persistence."""

    def __init__(
        self,
        connection: _Connection,
        ownership: _Ownership,
    ) -> None:
        self._connection = connection
        self._ownership = ownership

    def ensure_active(self) -> None:
        if (
            not self._ownership.active
            or not self._ownership.owns(self._connection)
        ):
            raise mv.MethodStateError(
                "Method write requires an active owning UoW"
            )

    def document(self, document_id: str) -> mv.DocumentRecord | None:
        row = self._connection.execute(
            _SELECT_DOCUMENT,
            (document_id,),
        ).fetchone()
        if row is None:
            return None
        database_path = Path(
            self._connection.execute(_DATABASE_LIST).fetchone()["file"]
        )
        return mv.DocumentRecord(
            database_path.resolve(),
            row["content_hash"],
            row["raw_text_path"],
        )

    def workspace_exists(self, workspace_id: str) -> bool:
        return self._connection.execute(
            _WORKSPACE_EXISTS,
            (workspace_id,),
        ).fetchone() is not None

    def insert_source_policy(self, row: mv.SourcePolicyWrite) -> None:
        self._connection.execute(
            _INSERT_SOURCE_POLICY,
            dataclasses.astuple(row),
        )

    def insert_document_policy_snapshot(
        self,
        row: mv.DocumentPolicySnapshotWrite,
    ) -> None:
        self._connection.execute(
            _INSERT_DOCUMENT_POLICY,
            dataclasses.astuple(row),
        )

    def insert_workspace(self, row: mv.WorkspaceWrite) -> None:
        self._connection.execute(
            _INSERT_WORKSPACE,
            dataclasses.astuple(row),
        )

    def insert_fragment(self, row: mv.FragmentWrite) -> None:
        self._connection.execute(
            _INSERT_FRAGMENT,
            dataclasses.astuple(row),
        )

    def fragment_epistemic(self, fragment_id: str) -> str | None:
        row = self._connection.execute(
            _SELECT_FRAGMENT_EPISTEMIC,
            (fragment_id,),
        ).fetchone()
        return None if row is None else row["epistemic_class"]

    def insert_fragment_evidence(
        self,
        row: mv.FragmentEvidenceWrite,
    ) -> None:
        self._connection.execute(
            _INSERT_FRAGMENT_EVIDENCE,
            dataclasses.astuple(row),
        )

    def insert_link(self, row: mv.LinkWrite) -> None:
        self._connection.execute(
            _INSERT_LINK,
            dataclasses.astuple(row),
        )

    def gap_workspace(self, gap_id: str) -> str | None:
        row = self._connection.execute(
            _SELECT_GAP_WORKSPACE,
            (gap_id,),
        ).fetchone()
        return None if row is None else row["workspace_id"]

    def fragment_workspace(self, fragment_id: str) -> str | None:
        row = self._connection.execute(
            _SELECT_FRAGMENT_WORKSPACE,
            (fragment_id,),
        ).fetchone()
        return None if row is None else row["workspace_id"]

    def upsert_gap_row(self, row: mv.GapWrite) -> None:
        self._connection.execute(
            _UPSERT_GAP,
            dataclasses.astuple(row),
        )

    def insert_bridge(self, row: mv.BridgeWrite) -> None:
        self._connection.execute(
            _INSERT_BRIDGE,
            dataclasses.astuple(row),
        )

    def insert_counter_search(self, row: mv.CounterSearchWrite) -> None:
        try:
            self._connection.execute(
                _INSERT_COUNTER_SEARCH,
                dataclasses.astuple(row),
            )
        except sqlite3.IntegrityError as exc:
            raise mv.MethodConflictError(
                "counter search identity already exists"
            ) from exc

    def insert_bridge_evidence(
        self,
        row: mv.BridgeEvidenceWrite,
    ) -> None:
        self._connection.execute(
            _INSERT_BRIDGE_EVIDENCE,
            dataclasses.astuple(row),
        )

    def decision_subject(
        self,
        kind: DecisionKind,
        subject_id: str,
    ) -> DecisionSubject | None:
        parameters = mv.decision_subject_parameters(kind, subject_id)
        row = self._connection.execute(
            _SELECT_DECISION_SUBJECT,
            parameters,
        ).fetchone()
        return None if row is None else DecisionSubject(*row)

    def bridge_has_counter_search(
        self,
        workspace_id: str,
        bridge_id: str,
    ) -> bool:
        return self._connection.execute(
            _SELECT_BRIDGE_COUNTER,
            (workspace_id, bridge_id, bridge_id),
        ).fetchone() is not None

    def insert_review_event(self, row: mv.ReviewEventWrite) -> None:
        self._connection.execute(
            _INSERT_REVIEW_EVENT,
            dataclasses.astuple(row),
        )

    def apply_decision(
        self,
        kind: DecisionKind,
        subject_id: str,
        expected: str,
        decision: str,
    ) -> bool:
        parameters = (decision, subject_id, expected)
        return (
            self._connection.execute(
                _DECISION_UPDATES[kind],
                parameters,
            ).rowcount
            == 1
        )
