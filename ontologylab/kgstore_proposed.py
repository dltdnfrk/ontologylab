"""Proposed writes: insert_proposed and entity resolution.

Split from ontologylab/kgstore.py — methods are mixed into KGStore
via ontologylab.kgstore. No behavior change intended.
"""

from __future__ import annotations

import json
import sqlite3
import time
from typing import Any, Iterable, Optional

from ontologylab.models import ProposedEntity, ProposedRelation

from ontologylab.kgstore_base import (
    EDGE_POLARITY_SQL,
    KGStoreError,
    SchemaValidationError,
    edge_polarity,
    normalize_name,
)

class ProposedMixin:

    # ------------------------------------------------------------------
    # Proposed writes (extraction path — physically cannot write 'verified')
    # ------------------------------------------------------------------

    def insert_proposed(
        self,
        entities: Iterable[ProposedEntity],
        relations: Iterable[ProposedRelation],
        *,
        source_doc_id: str,
        extractor_engine: str,
        extractor_model: str | None = None,
        prompt_version: str | None = None,
        decode_params: dict[str, Any] | None = None,
        commit: bool = True,
    ) -> dict[str, Any]:
        """Insert extraction output as ``proposed`` rows, resolving entities.

        Every entity is deduped by ``(schema_version_id, entity_type,
        normalized_name)`` (then by alias) against existing proposed+verified
        nodes; a hit reuses that node id and merges aliases/properties
        non-destructively, a miss inserts the minted id. Relation endpoints
        are then bound to resolved ids; duplicate triples append a citation
        instead of a second edge. Returns per-batch stats.
        """
        self._assert_writable()
        sv_id = self.active_schema_version()["id"]
        entity_rows = list(entities)
        relation_rows = list(relations)
        schema = self._schema_definition(sv_id)
        entity_types: dict[str, str] = {}
        for ent in entity_rows:
            if ent.synthesized:
                # Persist the marker where review can see it (stats alone
                # used to count it, invisibly to the queue).
                ent.properties.setdefault("synthesized_endpoint", "true")
            self._validate_properties(
                schema_version_id=sv_id,
                entity_type=ent.entity_type,
                properties=ent.properties,
                schema=schema,
            )
            entity_types[ent.id] = ent.entity_type
        for rel in relation_rows:
            try:
                src_type = entity_types[rel.src_entity_id]
                dst_type = entity_types[rel.dst_entity_id]
            except KeyError as exc:
                raise SchemaValidationError(
                    f"relation {rel.id} references unknown entity id {exc}"
                ) from exc
            self._validate_relation(
                schema_version_id=sv_id,
                relation_type=rel.relation_type,
                src_type=src_type,
                dst_type=dst_type,
                properties=rel.properties,
                qualifiers=rel.qualifiers,
                schema=schema,
            )
        now = time.time()
        # Canonical JSON (keys sorted, no spaces): one setting must store as
        # one string regardless of the caller's dict order, or scoping a
        # score to a sampler would split it into two streams.
        decode_json = (
            json.dumps(decode_params, sort_keys=True, separators=(",", ":"))
            if decode_params is not None
            else None
        )
        stats: dict[str, Any] = {
            "nodes_new": 0,
            "nodes_merged": 0,
            "edges_new": 0,
            "edges_merged": 0,
            "synthesized_endpoints": 0,
        }
        id_map: dict[str, str] = {}

        for ent in entity_rows:
            resolved = self._resolve_node(sv_id, ent.entity_type, ent.name)
            span_json = ent.source_span.as_json() if ent.source_span else None
            if resolved is not None:
                node_id = resolved["id"]
                self._merge_mention(resolved, ent)
                stats["nodes_merged"] += 1
            else:
                node_id = ent.id
                self.conn.execute(
                    "INSERT INTO nodes "
                    "(id, schema_version_id, entity_type, name, normalized_name, "
                    " aliases_json, properties_json, status, confidence, "
                    " source_doc_id, source_span, extractor_engine, extractor_model, "
                    " prompt_version, created_ts, decode_params) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, 'proposed', ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        node_id,
                        sv_id,
                        ent.entity_type,
                        ent.name,
                        normalize_name(ent.name),
                        json.dumps(ent.aliases),
                        json.dumps(ent.properties),
                        ent.confidence,
                        source_doc_id,
                        span_json,
                        extractor_engine,
                        extractor_model,
                        prompt_version,
                        now,
                        decode_json,
                    ),
                )
                for alias in ent.aliases:
                    self._add_alias(node_id, alias)
                stats["nodes_new"] += 1
                # 4C/C-033: a distinct node already carrying the same
                # canonical registry identity is a mandatory human-decided
                # review candidate - never an automatic merge.
                for key in ("cas_number", "eppo_code"):
                    value = ent.properties.get(key)
                    if not value:
                        continue
                    holder = self.conn.execute(
                        "SELECT id FROM nodes WHERE entity_type = ? AND "
                        "status IN ('proposed','verified') AND id != ? AND "
                        "json_extract(properties_json, ?) = ? LIMIT 1",
                        (ent.entity_type, node_id, f"$.{key}", value),
                    ).fetchone()
                    if holder is not None:
                        self.record_merge_candidate(
                            holder["id"], node_id, score=1.0,
                            reasons=[f"same-{key}:{value}"],
                        )
            if ent.synthesized:
                stats["synthesized_endpoints"] += 1
            id_map[ent.id] = node_id
            self._add_citation(
                "node",
                node_id,
                source_doc_id,
                span_json,
                now,
                extractor_engine,
                extractor_model,
                prompt_version,
                decode_json,
            )

        for rel in relation_rows:
            try:
                src = id_map[rel.src_entity_id]
                dst = id_map[rel.dst_entity_id]
            except KeyError as exc:
                raise KGStoreError(
                    f"relation {rel.id} references unknown entity id {exc}"
                ) from exc
            span_json = rel.source_span.as_json() if rel.source_span else None
            cur = self.conn.execute(
                "SELECT id FROM edges WHERE schema_version_id = ? AND "
                "relation_type = ? AND src_node_id = ? AND dst_node_id = ? AND "
                f"{EDGE_POLARITY_SQL} = ? AND "
                "status IN ('proposed','verified') AND "
                f"{self._edge_current_sql()}",
                (sv_id, rel.relation_type, src, dst, edge_polarity(rel.qualifiers)),
            )
            dup = cur.fetchone()
            if dup is not None:
                edge_id = dup["id"]
                stats["edges_merged"] += 1
            else:
                edge_id = rel.id
                self.conn.execute(
                    "INSERT INTO edges "
                    "(id, schema_version_id, relation_type, src_node_id, dst_node_id, "
                    " properties_json, qualifiers_json, status, confidence, "
                    " source_doc_id, source_span, extractor_engine, extractor_model, "
                    " prompt_version, created_ts, valid_from, decode_params) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, 'proposed', ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        edge_id,
                        sv_id,
                        rel.relation_type,
                        src,
                        dst,
                        json.dumps(rel.properties),
                        json.dumps(rel.qualifiers),
                        rel.confidence,
                        source_doc_id,
                        span_json,
                        extractor_engine,
                        extractor_model,
                        prompt_version,
                        now,
                        now,  # valid_from: assertion time defaults to ingestion
                        decode_json,
                    ),
                )
                stats["edges_new"] += 1
            self._add_citation(
                "edge",
                edge_id,
                source_doc_id,
                span_json,
                now,
                extractor_engine,
                extractor_model,
                prompt_version,
                decode_json,
            )

        if commit:
            self.conn.commit()
        stats["id_map"] = id_map
        return stats

    def _resolve_node(
        self, sv_id: int, entity_type: str, name: str
    ) -> Optional[sqlite3.Row]:
        """Exact-key resolution over proposed+verified nodes, then aliases."""
        key = normalize_name(name)
        cur = self.conn.execute(
            "SELECT * FROM nodes WHERE schema_version_id = ? AND entity_type = ? "
            "AND normalized_name = ? AND status IN ('proposed','verified')",
            (sv_id, entity_type, key),
        )
        row = cur.fetchone()
        if row is not None:
            return row
        rows = self.conn.execute(
            "SELECT n.* FROM node_aliases a JOIN nodes n ON n.id = a.node_id "
            "WHERE a.normalized_alias = ? AND n.schema_version_id = ? "
            "AND n.entity_type = ? AND n.status IN ('proposed','verified')",
            (key, sv_id, entity_type),
        ).fetchall()
        if len(rows) > 1:
            # Shared alias: LIMIT 1 used to merge into an arbitrary holder,
            # letting an unreviewed alias steer identity. A collision is a
            # merge-queue question for a human, not a coin flip.
            self.record_merge_candidate(
                rows[0]["id"],
                rows[1]["id"],
                score=1.0,
                reasons=[f"shared-alias:{key}"],
            )
            return None
        return rows[0] if rows else None

    def _merge_mention(self, existing: sqlite3.Row, ent: ProposedEntity) -> None:
        """Non-destructive merge of a re-mention into an existing node.

        Union aliases (the new surface name too, if it differs), fill only
        absent property keys, keep the earliest created_ts (already the case:
        created_ts is never touched).
        """
        aliases = json.loads(existing["aliases_json"])
        known = {normalize_name(a) for a in aliases}
        known.add(existing["normalized_name"])
        new_surfaces = [ent.name] + list(ent.aliases)
        changed_aliases = False
        for surface in new_surfaces:
            key = normalize_name(surface)
            if key and key not in known:
                aliases.append(surface)
                known.add(key)
                changed_aliases = True
            self._add_alias(existing["id"], surface)

        properties = json.loads(existing["properties_json"])
        changed_props = False
        for prop_key, value in ent.properties.items():
            if prop_key not in properties:
                properties[prop_key] = value
                changed_props = True

        if changed_aliases or changed_props:
            self.conn.execute(
                "UPDATE nodes SET aliases_json = ?, properties_json = ? WHERE id = ?",
                (json.dumps(aliases), json.dumps(properties), existing["id"]),
            )

    def _add_alias(self, node_id: str, surface: str) -> None:
        key = normalize_name(surface)
        if not key:
            return
        self.conn.execute(
            "INSERT OR IGNORE INTO node_aliases (node_id, normalized_alias, surface) "
            "VALUES (?, ?, ?)",
            (node_id, key, surface),
        )

    def _add_citation(
        self,
        kind: str,
        item_id: str,
        source_doc_id: str,
        span_json: str | None,
        ts: float,
        extractor_engine: str,
        extractor_model: str | None,
        prompt_version: str | None,
        decode_params: str | None,
    ) -> None:
        self.conn.execute(
            "INSERT INTO citations "
            "(kind, item_id, source_doc_id, source_span, created_ts, "
            "extractor_engine, extractor_model, prompt_version, decode_params) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                kind,
                item_id,
                source_doc_id,
                span_json,
                ts,
                extractor_engine,
                extractor_model,
                prompt_version,
                decode_params,
            ),
        )

    def citations(self, kind: str, item_id: str) -> list[dict[str, Any]]:
        cur = self.conn.execute(
            "SELECT source_doc_id, source_span, created_ts FROM citations "
            "WHERE kind = ? AND item_id = ? ORDER BY created_ts ASC",
            (kind, item_id),
        )
        return [
            {
                "source_doc_id": r["source_doc_id"],
                "source_span": json.loads(r["source_span"]) if r["source_span"] else None,
            }
            for r in cur.fetchall()
        ]
