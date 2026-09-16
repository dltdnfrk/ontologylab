"""Collected source documents.

Split from ontologylab/kgstore.py — methods are mixed into KGStore
via ontologylab.kgstore. No behavior change intended.
"""

from __future__ import annotations

from pathlib import Path
import sqlite3
import time
import uuid

from ontologylab import evidence
from ontologylab import kg_records
from ontologylab.connectors.base import normalize_doi
from ontologylab.models import Document

from ontologylab.kgstore_base import (
    DocumentIdentityConflict,
    KGStoreError,
    UnknownItem,
)

class DocumentsMixin:

    # ------------------------------------------------------------------
    # Documents
    # ------------------------------------------------------------------

    def insert_document(
        self,
        *,
        source_kind: str,
        source_uri: str,
        title: str | None,
        raw_text: str,
        content_hash: str,
        source: str = "",
        evidence_grade: str = "",
        doi: str | None = None,
    ) -> tuple[Document, bool]:
        """Insert a document (deduped by DOI, then content hash).

        Returns (document, created) — ``created`` False means an identical
        document already existed and was returned instead.

        The SELECT below is a fast path, not the guarantee. Two collects that
        overlap — a server job and a CLI run, or a fan-out that produced the
        same paper twice — can both miss it and both reach the INSERT, where
        ``UNIQUE (content_hash)`` refuses the second. That refusal carries
        exactly the fact the SELECT was looking for, so it is recovered from
        rather than raised: discarding a whole run's other documents over a
        duplicate the caller already has would be data loss, not safety.
        """
        self._assert_writable()
        normalized_doi = normalize_doi(doi)
        existing = None
        if normalized_doi is not None:
            existing = self.conn.execute(
                "SELECT * FROM documents WHERE doi = ?", (normalized_doi,)
            ).fetchone()
        if existing is None:
            existing = self.conn.execute(
                "SELECT * FROM documents WHERE content_hash = ?", (content_hash,)
            ).fetchone()
            if (
                existing is not None
                and normalized_doi is not None
                and existing["doi"] is not None
                and existing["doi"] != normalized_doi
            ):
                # Same bytes under a different explicit DOI: content-hash
                # equality cannot establish work identity (D05), so refuse
                # the merge instead of returning the other DOI's document.
                raise DocumentIdentityConflict(
                    existing_doc_id=existing["id"],
                    existing_doi=existing["doi"],
                    incoming_doi=normalized_doi,
                    content_hash=content_hash,
                )
        if existing is not None:
            return self._row_to_document(existing), False

        doc_id = uuid.uuid4().hex
        rel_path = f"documents/{doc_id}/raw.txt"
        abs_path = self.db_path.parent / rel_path
        abs_path.parent.mkdir(parents=True, exist_ok=True)
        abs_path.write_text(raw_text, encoding="utf-8")

        doc = Document(
            id=doc_id,
            source_kind=source_kind,
            source_uri=source_uri,
            title=title,
            fetched_ts=time.time(),
            content_hash=content_hash,
            raw_text_path=rel_path,
            source=source,
            evidence_grade=evidence.normalize(evidence_grade),
            doi=normalized_doi,
        )
        try:
            self.conn.execute(
                "INSERT INTO documents "
                "(id, source_kind, source_uri, title, fetched_ts, content_hash, "
                "raw_text_path, source, evidence_grade, doi) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    doc.id,
                    doc.source_kind,
                    doc.source_uri,
                    doc.title,
                    doc.fetched_ts,
                    doc.content_hash,
                    doc.raw_text_path,
                    doc.source,
                    doc.evidence_grade,
                    doc.doi,
                ),
            )
        except sqlite3.IntegrityError:
            # Another writer won the race on DOI or content hash.
            self.conn.rollback()
            abs_path.unlink(missing_ok=True)
            row = None
            if normalized_doi is not None:
                row = self.conn.execute(
                    "SELECT * FROM documents WHERE doi = ?", (normalized_doi,)
                ).fetchone()
            if row is None:
                row = self.conn.execute(
                    "SELECT * FROM documents WHERE content_hash = ?", (content_hash,)
                ).fetchone()
            if row is None:
                # The constraint fired for something other than document identity.
                raise
            if (
                normalized_doi is not None
                and row["doi"] is not None
                and row["doi"] != normalized_doi
            ):
                # The race winner holds the same bytes under a different
                # explicit DOI: same refusal as the fast path.
                raise DocumentIdentityConflict(
                    existing_doc_id=row["id"],
                    existing_doi=row["doi"],
                    incoming_doi=normalized_doi,
                    content_hash=content_hash,
                ) from None
            return self._row_to_document(row), False
        # The document is a library output from its first moment: register it
        # in the same transaction so a stored document can never exist
        # without its source_doc artifact row.
        self._artifact_insert(
            uuid.uuid4().hex,
            kind="source_doc",
            source_doc_id=doc.id,
            run_id=None,
            filename=title or source_uri or doc.id,
            created_ts=doc.fetched_ts,
        )
        self.conn.commit()
        return doc, True

    @staticmethod
    def _row_to_document(row: sqlite3.Row) -> Document:
        return kg_records.document_from_row(row)

    def get_document(self, doc_id: str) -> Document:
        cur = self.conn.execute("SELECT * FROM documents WHERE id = ?", (doc_id,))
        row = cur.fetchone()
        if row is None:
            raise UnknownItem(f"unknown document id {doc_id!r}")
        return self._row_to_document(row)

    def list_documents(self) -> list[Document]:
        cur = self.conn.execute("SELECT * FROM documents ORDER BY fetched_ts ASC")
        return [self._row_to_document(r) for r in cur.fetchall()]

    def document_raw_text(self, doc_id: str) -> str:
        from ontologylab.file_lifecycle import (
            READY,
            FileLifecycleError,
            read_ready_text,
        )

        row = self.conn.execute(
            "SELECT raw_text_path, representation_state, work_id "
            "FROM documents WHERE id = ?",
            (doc_id,),
        ).fetchone()
        if row is None:
            raise UnknownItem(f"unknown document id {doc_id!r}")
        try:
            if row["work_id"] is not None:
                return read_ready_text(self.conn, self.db_path.parent, doc_id)
            if row["representation_state"] != READY:
                raise KGStoreError(
                    f"representation {doc_id} is "
                    f"{row['representation_state']}"
                )
            raw = Path(str(row["raw_text_path"]))
            candidate = raw if raw.is_absolute() else self.db_path.parent / raw
            resolved = candidate.resolve()
            root = self.db_path.parent.resolve()
            if (
                not resolved.is_relative_to(root)
                or resolved.name in {"sources.json", "providers.json", ".env"}
            ):
                raise KGStoreError("legacy raw_text_path escapes safe storage")
            data = resolved.read_bytes()
            return data.decode("utf-8")
        except (FileLifecycleError, OSError, UnicodeDecodeError) as exc:
            raise KGStoreError(str(exc)) from exc
