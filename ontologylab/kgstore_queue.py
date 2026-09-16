"""Review queues, critic scores, runs, artifacts, enrichments.

Split from ontologylab/kgstore.py — methods are mixed into KGStore
via ontologylab.kgstore. No behavior change intended.
"""

from __future__ import annotations

import json
import time
import uuid
from typing import Any

from ontologylab import evidence
from ontologylab.paths import DEFAULT_ACTOR

from ontologylab.kgstore_base import (
    EndpointNotVerified,
    GroundingPreflightError,
    InvalidTransition,
    KGStoreError,
    REVIEW_STATUSES,
    UnknownItem,
    span_excerpt,
)

class QueueMixin:

    # Queue orderings for pending_review. Confidence orderings put NULLs
    # last; "confidence" (ascending) surfaces the least-certain extractions
    # first — the triage default recommended by the HITL literature.
    # "critic" surfaces the items the critic model scored lowest (unscored
    # items last), for W8 triage.
    # Every ordering ends with a pr.id tiebreak so the sort is total and a
    # keyset cursor can be advanced unambiguously — without it, rows with
    # equal sort keys come back in an arbitrary order and pagination would
    # skip or duplicate them.
    _REVIEW_ORDERINGS = {
        "created": "pr.created_ts ASC, pr.id ASC",
        "confidence": (
            "pr.confidence IS NULL, pr.confidence ASC, "
            "pr.created_ts ASC, pr.id ASC"
        ),
        "confidence_desc": (
            "pr.confidence IS NULL, pr.confidence DESC, "
            "pr.created_ts ASC, pr.id ASC"
        ),
        "critic": "cr.score IS NULL, cr.score ASC, pr.created_ts ASC, pr.id ASC",
    }

    # Keyset key per ordering, as a SQL row-value expression that is
    # strictly ASC under `>` even where the visible ordering mixes
    # directions: NULLs are folded into a leading 0/1 flag (never NULL in
    # a row value) and DESC columns are negated. The extractor below must
    # produce exactly these values from the last row of a page.
    _REVIEW_KEYSET = {
        "created": "(pr.created_ts, pr.id)",
        "confidence": (
            "(pr.confidence IS NULL, COALESCE(pr.confidence, -1), "
            "pr.created_ts, pr.id)"
        ),
        "confidence_desc": (
            "(pr.confidence IS NULL, COALESCE(-pr.confidence, 0), "
            "pr.created_ts, pr.id)"
        ),
        "critic": (
            "(cr.score IS NULL, COALESCE(cr.score, -1), "
            "pr.created_ts, pr.id)"
        ),
    }

    # An extractor-vs-critic gap at/above this flags the row as a
    # disagreement — the highest-value rows for a human to look at.
    CRITIC_DISAGREEMENT_THRESHOLD = 0.35

    def pending_review(
        self,
        *,
        kind: str | None = None,
        type_name: str | None = None,
        source_doc_id: str | None = None,
        order: str = "created",
        limit: int = 100,
        cursor: list[Any] | None = None,
    ) -> list[dict[str, Any]]:
        try:
            order_sql = self._REVIEW_ORDERINGS[order]
        except KeyError:
            raise KGStoreError(
                f"unknown review order {order!r} "
                f"(allowed: {sorted(self._REVIEW_ORDERINGS)})"
            ) from None
        where = ["1=1"]
        args: list[Any] = []
        if kind:
            where.append("pr.kind = ?")
            args.append(kind)
        if type_name:
            where.append("pr.type_name = ?")
            args.append(type_name)
        if source_doc_id:
            where.append("pr.source_doc_id = ?")
            args.append(source_doc_id)
        if cursor is not None:
            key_sql = self._REVIEW_KEYSET[order]
            if len(cursor) != self._review_keyset_arity(order):
                raise KGStoreError(
                    f"cursor for order {order!r} must have "
                    f"{self._review_keyset_arity(order)} values"
                )
            placeholders = ",".join("?" * len(cursor))
            where.append(f"({key_sql}) > ({placeholders})")
            args.extend(cursor)
        # Latest critic review per item, restricted to the CURRENT critic
        # stream per kind (`_current_critic_stream`): a queue that kept
        # serving a retired stream's scores contradicted `conformal` on the
        # same items — a number beside a proposal reads as "the critic judged
        # this", and after a switch the current critic has not. Advisory
        # columns only: approval paths never read this join. Read-only stores
        # built before W8 have no critic_reviews table and degrade to NULL
        # critic columns.
        critic_args: list[Any] = []
        if self._table_exists("critic_reviews"):
            scopes: list[str] = []
            for item_kind in ("node", "edge"):
                stream = self._current_critic_stream(item_kind)
                if stream is None:
                    continue
                scopes.append(
                    "(c.kind = ? AND c.engine = ? AND c.model IS ? "
                    "AND c.prompt_version = ?)"
                )
                critic_args.extend((item_kind, *stream))
            critic_join = (
                "LEFT JOIN (SELECT kind, item_id, engine, score, rationale, "
                "           MAX(created_ts) AS ts FROM critic_reviews c "
                f"          WHERE {' OR '.join(scopes) if scopes else '0 = 1'} "
                "           GROUP BY kind, item_id) cr "
                "ON cr.kind = pr.kind AND cr.item_id = pr.id "
            )
        else:
            critic_join = (
                "LEFT JOIN (SELECT NULL AS kind, NULL AS item_id, "
                "           NULL AS engine, NULL AS score, NULL AS rationale) cr "
                "ON cr.item_id = pr.id "
            )
        cur = self.conn.execute(
            "SELECT pr.*, cr.score AS critic_score, "
            "cr.rationale AS critic_rationale, cr.engine AS critic_engine "
            "FROM pending_review pr "
            f"{critic_join}"
            f"WHERE {' AND '.join(where)} ORDER BY {order_sql} LIMIT ?",
            [*critic_args, *args, limit],
        )
        out = []
        for r in cur.fetchall():
            row = dict(r)
            conf, score = row.get("confidence"), row.get("critic_score")
            row["critic_disagreement"] = bool(
                conf is not None
                and score is not None
                and abs(conf - score) >= self.CRITIC_DISAGREEMENT_THRESHOLD
            )
            out.append(row)
        self._label_edge_endpoints(out)
        self._attach_properties(out)
        self._attach_evidence(out)
        return out

    @staticmethod
    def _review_keyset_arity(order: str) -> int:
        return {"created": 2, "confidence": 4, "confidence_desc": 4, "critic": 4}[order]

    def review_cursor_values(self, order: str, row: dict[str, Any]) -> list[Any]:
        """Keyset cursor values for one row, in sort-key order.

        Must mirror ``_REVIEW_KEYSET`` exactly: the list is what the next
        ``pending_review(cursor=...)`` call compares against, so a mismatch
        would silently skip or duplicate rows across pages.
        """
        if order == "created":
            return [row["created_ts"], row["id"]]
        conf = row.get("confidence")
        if order == "confidence":
            return [
                0 if conf is not None else 1,
                conf if conf is not None else -1,
                row["created_ts"],
                row["id"],
            ]
        if order == "confidence_desc":
            return [
                0 if conf is not None else 1,
                -conf if conf is not None else 0,
                row["created_ts"],
                row["id"],
            ]
        if order == "critic":
            score = row.get("critic_score")
            return [
                0 if score is not None else 1,
                score if score is not None else -1,
                row["created_ts"],
                row["id"],
            ]
        raise KGStoreError(f"unknown review order {order!r}")

    def decided_review(
        self,
        *,
        decision: str | None = None,
        kind: str | None = None,
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        """Server-backed review history: verified/rejected rows, newest first.

        ``pending_review`` only ever serves proposed rows, so the dashboard's
        decided tabs were session-memory — a reload erased them. This reads
        the same rows the store persists (verified_ts/verified_by/review_note
        are set by ``_set_status`` on every approve/reject), so history
        survives reloads and reports who decided what and why.
        """
        statuses = (
            ("verified", "rejected")
            if decision is None
            else (decision,)
        )
        if any(s not in ("verified", "rejected") for s in statuses):
            raise KGStoreError(
                f"decision must be 'verified' or 'rejected', got {decision!r}"
            )
        if kind not in (None, "node", "edge"):
            raise KGStoreError(f"kind must be 'node' or 'edge', got {kind!r}")
        placeholders = ",".join("?" * len(statuses))
        rows: list[dict[str, Any]] = []
        if kind in (None, "node"):
            cur = self.conn.execute(
                "SELECT 'node' AS kind, id, entity_type AS type_name, "
                "name AS label, confidence, source_doc_id, created_ts, "
                "status, verified_ts, verified_by, review_note "
                f"FROM nodes WHERE status IN ({placeholders}) "
                "ORDER BY verified_ts DESC LIMIT ?",
                [*statuses, limit],
            )
            rows.extend(dict(r) for r in cur.fetchall())
        if kind in (None, "edge"):
            cur = self.conn.execute(
                "SELECT 'edge' AS kind, id, relation_type AS type_name, "
                "src_node_id || ' -> ' || dst_node_id AS label, "
                "confidence, source_doc_id, created_ts, "
                "status, verified_ts, verified_by, review_note "
                f"FROM edges WHERE status IN ({placeholders}) "
                "ORDER BY verified_ts DESC LIMIT ?",
                [*statuses, limit],
            )
            rows.extend(dict(r) for r in cur.fetchall())
        rows.sort(key=lambda r: (r.get("verified_ts") or 0), reverse=True)
        rows = rows[:limit]
        self._label_edge_endpoints(rows)
        self._attach_properties(rows)
        self._attach_evidence(rows)
        return rows

    def stale_decisions(self) -> list[dict[str, Any]]:
        """Verified items whose source document has a newer fetch.

        Documents are immutable (UNIQUE content_hash), so a re-fetch of the
        same source_uri creates a new row. A verified node/edge is stale when
        its source_doc_id points to a doc that has a newer sibling — the
        reviewer approved against evidence that has since changed.
        """
        cur = self.conn.execute(
            "SELECT 'node' AS kind, n.id, n.name AS label, "
            "n.entity_type AS type_name, n.verified_ts, n.verified_by, "
            "d.title AS doc_title, d.fetched_ts AS doc_ts, "
            "d2.fetched_ts AS newer_ts, d2.id AS newer_doc_id "
            "FROM nodes n "
            "JOIN documents d ON n.source_doc_id = d.id "
            "JOIN documents d2 ON d2.source_uri = d.source_uri "
            "  AND d2.fetched_ts > d.fetched_ts "
            "WHERE n.status = 'verified' "
            "UNION ALL "
            "SELECT 'edge' AS kind, e.id, "
            "e.src_node_id || ' -> ' || e.dst_node_id AS label, "
            "e.relation_type AS type_name, e.verified_ts, e.verified_by, "
            "d.title AS doc_title, d.fetched_ts AS doc_ts, "
            "d2.fetched_ts AS newer_ts, d2.id AS newer_doc_id "
            "FROM edges e "
            "JOIN documents d ON e.source_doc_id = d.id "
            "JOIN documents d2 ON d2.source_uri = d.source_uri "
            "  AND d2.fetched_ts > d.fetched_ts "
            "WHERE e.status = 'verified' "
            "ORDER BY verified_ts DESC"
        )
        return [dict(r) for r in cur.fetchall()]

    def approve_many(
        self,
        item_ids: list[str],
        *,
        by: str = DEFAULT_ACTOR,
        note: str | None = None,
    ) -> dict[str, Any]:
        """Approve an explicit selection: nodes first, then edges.

        The review UI hands the ids the human checked — unlike
        ``bulk_approve``'s filter sweep, nothing outside the list is touched.
        An edge whose endpoints are not verified (and not themselves in this
        batch) is reported as skipped, never silently approved; a row that
        fails its own transition is reported as failed with the reason.
        """
        self._assert_writable()
        if not item_ids:
            raise KGStoreError("approve_many needs at least one id")
        approved: list[str] = []
        skipped: list[dict[str, str]] = []
        failed: list[dict[str, str]] = []

        kinds: dict[str, str] = {}
        for item_id in item_ids:
            try:
                kind, _row = self._find_kind(item_id)
            except UnknownItem:
                failed.append({"id": item_id, "reason": "unknown item"})
                continue
            kinds[item_id] = kind

        # Nodes first: an edge in the same batch may depend on them.
        for item_id in item_ids:
            if kinds.get(item_id) != "node":
                continue
            try:
                self.approve(item_id, by=by, note=note)
                approved.append(item_id)
            except (InvalidTransition, EndpointNotVerified, GroundingPreflightError, KGStoreError) as exc:
                failed.append({"id": item_id, "reason": str(exc)})

        for item_id in item_ids:
            if kinds.get(item_id) != "edge":
                continue
            try:
                self.approve(item_id, by=by, note=note)
                approved.append(item_id)
            except EndpointNotVerified as exc:
                skipped.append({"id": item_id, "reason": str(exc)})
            except (InvalidTransition, GroundingPreflightError, KGStoreError) as exc:
                failed.append({"id": item_id, "reason": str(exc)})

        return {
            "approved": approved,
            "skipped": skipped,
            "failed": failed,
        }

    def _attach_properties(self, rows: list[dict[str, Any]]) -> None:
        """Expose stored properties and edge qualifiers on the review surface."""
        for kind, table in (("node", "nodes"), ("edge", "edges")):
            targets = {row["id"]: row for row in rows if row.get("kind") == kind}
            ids = list(targets)
            for start in range(0, len(ids), 500):
                chunk = ids[start : start + 500]
                placeholders = ",".join("?" * len(chunk))
                qualifier_column = (
                    ", qualifiers_json"
                    if kind == "edge" and self._edges_have_qualifiers()
                    else ""
                )
                for row in self.conn.execute(
                    f"SELECT id, properties_json{qualifier_column} FROM {table} "
                    f"WHERE id IN ({placeholders})",
                    chunk,
                ):
                    target = targets[row["id"]]
                    target["properties"] = json.loads(row["properties_json"])
                    if kind == "edge":
                        target["qualifiers"] = (
                            json.loads(row["qualifiers_json"])
                            if "qualifiers_json" in row.keys()
                            and row["qualifiers_json"]
                            else {}
                        )

    def _attach_evidence(self, rows: list[dict[str, Any]]) -> None:
        """Attach the source excerpt each proposal was extracted from, in place.

        The reviewer is asked to judge whether an extraction is true, and the
        only thing that settles that is the sentence it came from. The critic
        model has always been handed exactly this (critic.py builds it from
        the same span), while the person holding the decision saw only a label
        and a number — so the queue payload is where that asymmetry lives.

        ``pending_review`` cannot supply it: the view predates spans and is
        created with CREATE VIEW IF NOT EXISTS, so redefining it would leave
        every existing database on the old definition. Spans are fetched here
        instead, the same way endpoint names are.

        Adds ``source_span``, ``excerpt``, ``doc_title``, ``doc_source``
        and ``evidence_grade``. Every step fails
        open to an empty excerpt — a deleted raw.txt must not break review.
        """
        if not rows:
            return

        spans: dict[str, dict | None] = {}
        for kind, table in (("node", "nodes"), ("edge", "edges")):
            ids = [r["id"] for r in rows if r.get("kind") == kind and r.get("id")]
            for start in range(0, len(ids), 500):
                chunk = ids[start : start + 500]
                placeholders = ",".join("?" * len(chunk))
                for row in self.conn.execute(
                    f"SELECT id, source_span FROM {table} "
                    f"WHERE id IN ({placeholders})",
                    chunk,
                ).fetchall():
                    try:
                        spans[row["id"]] = (
                            json.loads(row["source_span"])
                            if row["source_span"]
                            else None
                        )
                    except (TypeError, ValueError):
                        spans[row["id"]] = None

        raw_cache: dict[str, str] = {}
        # Title, source and grade come from one `get_document` per document —
        # the grade is what tells a reviewer whether the sentence they are
        # about to trust was reviewed by anyone before them.
        doc_cache: dict[str, tuple[str | None, str, str]] = {}

        def _raw(doc_id: str) -> str:
            if doc_id not in raw_cache:
                try:
                    raw_cache[doc_id] = self.document_raw_text(doc_id)
                except (KGStoreError, OSError):
                    raw_cache[doc_id] = ""
            return raw_cache[doc_id]

        def _doc(doc_id: str) -> tuple[str | None, str, str]:
            if doc_id not in doc_cache:
                try:
                    d = self.get_document(doc_id)
                    doc_cache[doc_id] = (
                        d.title, d.source, evidence.normalize(d.evidence_grade)
                    )
                except (UnknownItem, KGStoreError, OSError):
                    doc_cache[doc_id] = (None, "", evidence.UNKNOWN)
            return doc_cache[doc_id]

        for row in rows:
            row_id = row.get("id")
            span = spans.get(row_id) if isinstance(row_id, str) else None
            row["source_span"] = span
            doc_id = row.get("source_doc_id")
            if not doc_id:
                row["excerpt"], row["doc_title"] = "", None
                row["doc_source"], row["evidence_grade"] = "", evidence.UNKNOWN
                continue
            title, source, grade = _doc(doc_id)
            row["doc_title"] = title
            row["doc_source"] = source
            row["evidence_grade"] = grade
            row["excerpt"] = span_excerpt(_raw(doc_id), span)

    def _label_edge_endpoints(self, rows: list[dict[str, Any]]) -> None:
        """Rewrite edge labels from endpoint ids to endpoint NAMES, in place.

        The ``pending_review`` view can only concatenate the two node ids
        (``src -> dst``), so the review queue asked the user to approve
        rows reading ``74116a11… -> 36d5bf4d…`` — the one screen where the
        decision must be informed was the one screen showing nothing
        decidable. Endpoint names are resolved here, in one batched lookup,
        rather than in the view, so existing databases need no migration and
        read-only packs keep working.

        ``src_label``/``dst_label``/``src_id``/``dst_id`` are added alongside
        so callers that need the raw ids still have them. A node that cannot
        be resolved keeps its short id, which is still better than the full
        hex string.
        """
        edges = [r for r in rows if r.get("kind") == "edge"]
        if not edges:
            return
        endpoints: dict[str, tuple[str, str]] = {}
        wanted: set[str] = set()
        for row in edges:
            label = row.get("label") or ""
            src, sep, dst = label.partition(" -> ")
            if not sep:
                continue
            endpoints[row["id"]] = (src, dst)
            wanted.update((src, dst))
        if not wanted:
            return
        names: dict[str, str] = {}
        ids = list(wanted)
        # Chunked so a large queue cannot exceed SQLite's variable limit.
        for start in range(0, len(ids), 500):
            chunk = ids[start : start + 500]
            placeholders = ",".join("?" * len(chunk))
            for row in self.conn.execute(
                f"SELECT id, name FROM nodes WHERE id IN ({placeholders})", chunk
            ).fetchall():
                names[row["id"]] = row["name"]
        for row in edges:
            pair = endpoints.get(row["id"])
            if pair is None:
                continue
            src, dst = pair
            src_label = names.get(src, src[:10])
            dst_label = names.get(dst, dst[:10])
            row["src_id"], row["dst_id"] = src, dst
            row["src_label"], row["dst_label"] = src_label, dst_label
            row["label"] = f"{src_label} → {dst_label}"

    def record_critic_review(
        self,
        kind: str,
        item_id: str,
        *,
        engine: str,
        model: str | None,
        prompt_version: str,
        score: float,
        rationale: str | None = None,
    ) -> None:
        """Upsert one advisory critic score. Never touches nodes/edges."""
        self._assert_writable()
        if kind not in ("node", "edge"):
            raise KGStoreError(f"bad critic review kind {kind!r}")
        score = min(1.0, max(0.0, float(score)))
        self.conn.execute(
            "INSERT INTO critic_reviews "
            "(kind, item_id, engine, model, prompt_version, score, rationale, "
            " created_ts) VALUES (?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT (kind, item_id, engine, prompt_version) DO UPDATE SET "
            "score = excluded.score, rationale = excluded.rationale, "
            "model = excluded.model, created_ts = excluded.created_ts",
            (kind, item_id, engine, model, prompt_version, score, rationale,
             time.time()),
        )
        self.conn.commit()

    def run_upsert(self, run: dict[str, Any]) -> None:
        """Insert or replace one durable job-history row, keyed by job id.

        The job registry always persists a complete snapshot, so REPLACE is
        the right merge: a stale partial row never survives an update.
        """
        self.conn.execute(
            "INSERT OR REPLACE INTO runs "
            "(id, kind, status, phase, engine, model, started_ts, "
            " finished_ts, error, totals_json, ask_json) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                run["id"],
                run.get("kind"),
                run.get("status", "running"),
                run.get("phase", ""),
                run.get("engine"),
                run.get("model"),
                run.get("started_ts"),
                run.get("finished_ts"),
                run.get("error"),
                json.dumps(run.get("totals") or {}),
                run.get("ask"),
            ),
        )
        self.conn.commit()

    def list_runs(self, limit: int = 500) -> list[dict[str, Any]]:
        """Durable job rows, newest first — the jobs screen after a restart."""
        rows = self.conn.execute(
            "SELECT * FROM runs ORDER BY started_ts DESC LIMIT ?", (limit,)
        ).fetchall()
        out = []
        for row in rows:
            rec = dict(row)
            rec["totals"] = json.loads(rec.pop("totals_json") or "{}")
            rec["ask"] = rec.pop("ask_json")
            out.append(rec)
        return out

    def _artifact_insert(
        self,
        artifact_id: str,
        *,
        kind: str,
        source_doc_id: str | None,
        run_id: str | None,
        filename: str | None,
        created_ts: float,
    ) -> None:
        """Execute one artifacts INSERT without committing (caller owns the tx)."""
        self.conn.execute(
            "INSERT INTO artifacts "
            "(id, kind, source_doc_id, run_id, filename, created_ts) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (artifact_id, kind, source_doc_id, run_id, filename, created_ts),
        )

    def register_artifact(
        self,
        *,
        kind: str,
        filename: str | None,
        source_doc_id: str | None = None,
        run_id: str | None = None,
    ) -> str:
        """Record one consumable output (document or pack) in the library."""
        artifact_id = uuid.uuid4().hex
        self._artifact_insert(
            artifact_id, kind=kind, source_doc_id=source_doc_id,
            run_id=run_id, filename=filename, created_ts=time.time(),
        )
        self.conn.commit()
        return artifact_id

    def list_artifacts(
        self, *, kind: str | None = None, limit: int = 100
    ) -> list[dict[str, Any]]:
        """Artifact rows, newest first (created_ts desc, id desc tiebreak)."""
        where, args = "1=1", []
        if kind:
            where = "kind = ?"
            args.append(kind)
        args.append(limit)
        rows = self.conn.execute(
            f"SELECT * FROM artifacts WHERE {where} "
            "ORDER BY created_ts DESC, id DESC LIMIT ?",
            args,
        ).fetchall()
        return [dict(r) for r in rows]

    def get_artifact(self, artifact_id: str) -> dict[str, Any] | None:
        """One artifact row, or None when the id is unknown."""
        row = self.conn.execute(
            "SELECT * FROM artifacts WHERE id = ?", (artifact_id,)
        ).fetchone()
        return dict(row) if row is not None else None

    def upsert_enrichment(
        self,
        *,
        node_id: str,
        registry: str,
        identifier: str,
        label: str,
        description: str = "",
        fetched_ts: float,
        error: str | None = None,
    ) -> None:
        """Record what a registry said about one proposed entity."""
        self.conn.execute(
            "INSERT OR REPLACE INTO entity_enrichments "
            "(node_id, registry, identifier, label, description, fetched_ts, error) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (node_id, registry, identifier, label, description, fetched_ts, error),
        )
        self.conn.commit()

    def list_enrichments(self, node_id: str) -> list[dict[str, Any]]:
        """Every stored registry answer for one entity, newest answer first."""
        rows = self.conn.execute(
            "SELECT * FROM entity_enrichments WHERE node_id = ? "
            "ORDER BY fetched_ts DESC",
            (node_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def counts(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for status in REVIEW_STATUSES:
            out[f"nodes_{status}"] = self.conn.execute(
                "SELECT COUNT(*) AS n FROM nodes WHERE status = ?", (status,)
            ).fetchone()["n"]
            # edges_{verified} is current-truth inventory: an invalidated
            # edge is history, not stock.
            out[f"edges_{status}"] = self.conn.execute(
                f"SELECT COUNT(*) AS n FROM edges WHERE status = ? "
                f"AND {self._edge_current_sql()}",
                (status,),
            ).fetchone()["n"]
        out["documents"] = self.conn.execute(
            "SELECT COUNT(*) AS n FROM documents"
        ).fetchone()["n"]
        out["merge_candidates_pending"] = (
            self.conn.execute(
                "SELECT COUNT(*) AS n FROM merge_candidates "
                "WHERE status = 'proposed'"
            ).fetchone()["n"]
            if self._table_exists("merge_candidates")
            else 0
        )
        return out
