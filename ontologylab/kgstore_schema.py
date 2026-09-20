"""Ontology schema: versions, terms, aliases, xrefs.

Split from ontologylab/kgstore.py — methods are mixed into KGStore
via ontologylab.kgstore. No behavior change intended.
"""

from __future__ import annotations

import json
import math
import re
import sqlite3
import time
import uuid
from typing import Any

from ontologylab import ontology_schema as default_schema
from ontologylab.paths import DEFAULT_ACTOR

from ontologylab.kgstore_base import (
    KGStoreError,
    OntologyTermValidationError,
    UnknownItem,
    XrefValidationError,
)

class SchemaMixin:

    # ------------------------------------------------------------------
    # Ontology schema
    # ------------------------------------------------------------------

    @staticmethod
    def _term_text(field: str, value: str | None) -> str:
        """Parse one required reviewed-text field."""
        if not isinstance(value, str) or not value.strip():
            raise OntologyTermValidationError(field, "must be a non-empty string")
        return value.strip()

    @staticmethod
    def _insert_ontology_term_row(
        conn: sqlite3.Connection,
        *,
        preferred_label: str,
        language: str,
        definition: str,
        schema_version_id: int,
        reviewer: str,
        provenance: str,
        now: float,
        legacy_kind: str | None = None,
        legacy_id: int | None = None,
    ) -> str:
        """Insert one already-validated term without committing its caller's tx."""
        term_id = str(uuid.uuid4())
        conn.execute(
            "INSERT INTO ontology_term "
            "(id, iri, preferred_label, language, definition, lifecycle, "
            "schema_version_id, reviewer, provenance, created_ts, updated_ts, "
            "legacy_kind, legacy_id) "
            "VALUES (?, ?, ?, ?, ?, 'active', ?, ?, ?, ?, ?, ?, ?)",
            (
                term_id,
                default_schema.local_term_iri(term_id),
                preferred_label,
                language,
                definition,
                schema_version_id,
                reviewer,
                provenance,
                now,
                now,
                legacy_kind,
                legacy_id,
            ),
        )
        return term_id

    @staticmethod
    def _insert_schema_term(
        conn: sqlite3.Connection,
        item: dict[str, Any],
        *,
        schema_version_id: int,
        legacy_kind: str,
        legacy_id: int | None,
        reviewer: str,
        provenance: str,
        now: float,
    ) -> None:
        """Persist one installed type's reviewed term fields."""
        if legacy_id is None:
            raise KGStoreError("schema type insert did not return an id")
        definition = item.get("definition", item.get("description", ""))
        if not isinstance(definition, str):
            raise OntologyTermValidationError("definition", "must be a string")
        from ontologylab.kgstore import KGStore
        KGStore._insert_ontology_term_row(
            conn,
            preferred_label=KGStore._term_text(
                "preferred_label", item.get("preferred_label", item["name"])
            ),
            language=KGStore._term_text(
                "language",
                item.get("language", default_schema.DEFAULT_TERM_LANGUAGE),
            ),
            definition=definition.strip(),
            schema_version_id=schema_version_id,
            reviewer=reviewer,
            provenance=provenance,
            now=now,
            legacy_kind=legacy_kind,
            legacy_id=legacy_id,
        )

    def _seed_default_schema(self) -> None:
        if self.conn.execute(
            "SELECT COUNT(*) AS n FROM schema_version"
        ).fetchone()["n"]:
            return
        now = time.time()
        with self.conn:
            cur = self.conn.execute(
                "INSERT INTO schema_version "
                "(label, description, created_ts, is_active) VALUES (?, ?, ?, 1)",
                (
                    default_schema.DEFAULT_SCHEMA_LABEL,
                    default_schema.DEFAULT_SCHEMA_DESCRIPTION,
                    now,
                ),
            )
            if cur.lastrowid is None:
                raise KGStoreError("default schema insert did not return an id")
            sv_id = int(cur.lastrowid)
            for name, (desc, attrs) in default_schema.DEFAULT_ENTITY_TYPES.items():
                self.conn.execute(
                    "INSERT INTO entity_type "
                    "(schema_version_id, name, description, attributes_json) "
                    "VALUES (?, ?, ?, ?)",
                    (sv_id, name, desc, json.dumps(attrs)),
                )
            for name, (desc, domain, range_, directed) in (
                default_schema.DEFAULT_RELATION_TYPES.items()
            ):
                self.conn.execute(
                    "INSERT INTO relation_type "
                    "(schema_version_id, name, description, domain_type, range_type, "
                    "directed, qualifiers_json) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (
                        sv_id,
                        name,
                        desc,
                        domain,
                        range_,
                        1 if directed else 0,
                        json.dumps(
                            default_schema.DEFAULT_RELATION_QUALIFIERS.get(name, {})
                        ),
                    ),
                )
            self._backfill_legacy_ontology_terms(
                self.conn,
                reviewer=default_schema.BUNDLED_TERM_REVIEWER,
                provenance=f"bundled-schema:{default_schema.DEFAULT_SCHEMA_LABEL}",
            )

    def active_schema_version(self) -> sqlite3.Row:
        cur = self.conn.execute(
            "SELECT * FROM schema_version WHERE is_active = 1 "
            "ORDER BY id DESC LIMIT 1"
        )
        row = cur.fetchone()
        if row is None:
            raise KGStoreError("no active schema_version row")
        return row

    @staticmethod
    def _validate_qualifier_specs(relation_name: str, specs: Any) -> None:
        if not isinstance(specs, dict):
            raise KGStoreError(
                f"relation {relation_name!r} qualifiers must be an object"
            )
        supported = {"string", "boolean", "integer", "number", "array", "object"}
        for name, spec in specs.items():
            if not isinstance(name, str) or re.fullmatch(
                r"[A-Za-z_][A-Za-z0-9_]*", name
            ) is None:
                raise KGStoreError(
                    f"relation {relation_name!r} has invalid qualifier name {name!r}"
                )
            if not isinstance(spec, dict):
                raise KGStoreError(
                    f"relation {relation_name!r} qualifier {name!r} spec must be an object"
                )
            expected = spec.get("type", "string")
            if expected not in supported:
                raise KGStoreError(
                    f"relation {relation_name!r} qualifier {name!r} has unsupported "
                    f"type {expected!r}"
                )
            enum = spec.get("enum")
            if enum is not None and not isinstance(enum, list):
                raise KGStoreError(
                    f"relation {relation_name!r} qualifier {name!r} enum must be a list"
                )
            pattern = spec.get("pattern")
            if pattern is not None:
                if not isinstance(pattern, str):
                    raise KGStoreError(
                        f"relation {relation_name!r} qualifier {name!r} pattern "
                        "must be a string"
                    )
                try:
                    re.compile(pattern)
                except re.error as exc:
                    raise KGStoreError(
                        f"relation {relation_name!r} qualifier {name!r} has invalid pattern"
                    ) from exc

    def install_schema(
        self,
        *,
        label: str,
        description: str,
        entity_types: list[dict[str, Any]],
        relation_types: list[dict[str, Any]],
        term_reviewer: str = DEFAULT_ACTOR,
        term_provenance: str | None = None,
    ) -> int:
        """Add an ontology and make it the active one. Returns its id.

        The whole design already assumed this would exist — `nodes`,
        `edges` and the type tables all carry `schema_version_id` — but
        nothing could write one, so every install ran on
        `software-docs-v1`: a "neutral default ontology for software /
        technical documentation", used here on p53 papers. Measured on one
        abstract, that mismatch produced five relations, all of them
        `related_to`, and 24 rejected proposals the schema had no shape
        for; the same abstract under a biomedical ontology produced twelve
        relations across five types and nothing rejected.

        Switching is additive. A new row is inserted and the previous one
        deactivated, never edited or deleted, so proposals extracted under
        the old ontology keep pointing at the ontology they were judged
        against — the alternative would silently re-type a review queue
        somebody is halfway through.
        """
        if not entity_types:
            raise KGStoreError("a schema needs at least one entity type")
        if not label.strip():
            raise KGStoreError("a schema needs a label")

        clean_label = label.strip()
        reviewer = self._term_text("reviewer", term_reviewer)
        provenance = self._term_text(
            "provenance",
            (
                term_provenance
                if term_provenance is not None
                else f"schema-install:{clean_label}"
            ),
        )
        names = {e["name"] for e in entity_types}
        # is-a validation: a parent must be a type in this same schema, and
        # the parent chain must not cycle. Names, not ids, so the check runs
        # on the document itself before anything is inserted.
        parent_of = {
            e["name"]: e.get("parent") for e in entity_types if e.get("parent")
        }
        for name, parent in parent_of.items():
            if parent not in names:
                raise KGStoreError(
                    f"entity type {name!r} has parent {parent!r}, which is "
                    f"not an entity type in this schema "
                    f"({', '.join(sorted(names))})"
                )
        for name in parent_of:
            seen = {name}
            node = parent_of.get(name)
            while node is not None:
                if node in seen:
                    raise KGStoreError(
                        f"entity type {name!r} has a cyclic parent chain "
                        f"(reached {node!r})"
                    )
                seen.add(node)
                node = parent_of.get(node)
        for relation in relation_types:
            self._validate_qualifier_specs(
                relation["name"], relation.get("qualifiers", {})
            )
            for side in ("domain_type", "range_type"):
                declared = relation.get(side, "*")
                # `*` means any. Anything else has to be a type this same
                # schema defines, or the extractor is handed a rule that
                # can never be satisfied and every use is rejected.
                if declared != "*" and declared not in names:
                    raise KGStoreError(
                        f"relation {relation['name']!r} has {side}="
                        f"{declared!r}, which is not an entity type in this "
                        f"schema ({', '.join(sorted(names))})"
                    )

        now = time.time()
        with self.conn:
            self.conn.execute("UPDATE schema_version SET is_active = 0")
            cur = self.conn.execute(
                "INSERT INTO schema_version "
                "(label, description, created_ts, is_active) VALUES (?,?,?,1)",
                (clean_label, description, now),
            )
            if cur.lastrowid is None:
                raise KGStoreError("schema install did not return an id")
            sv_id = int(cur.lastrowid)
            for entity in entity_types:
                type_cur = self.conn.execute(
                    "INSERT INTO entity_type (schema_version_id, name, "
                    "description, attributes_json, parent_name) "
                    "VALUES (?,?,?,?,?)",
                    (sv_id, entity["name"], entity.get("description", ""),
                     json.dumps(entity.get("attributes", {})),
                     entity.get("parent")),
                )
                self._insert_schema_term(
                    self.conn,
                    entity,
                    schema_version_id=sv_id,
                    legacy_kind="entity_type",
                    legacy_id=type_cur.lastrowid,
                    reviewer=reviewer,
                    provenance=provenance,
                    now=now,
                )
            for relation in relation_types:
                type_cur = self.conn.execute(
                    "INSERT INTO relation_type (schema_version_id, name, "
                    "description, domain_type, range_type, directed, "
                    "qualifiers_json) VALUES (?,?,?,?,?,?,?)",
                    (
                        sv_id,
                        relation["name"],
                        relation.get("description", ""),
                        relation.get("domain_type", "*"),
                        relation.get("range_type", "*"),
                        1 if relation.get("directed", True) else 0,
                        json.dumps(relation.get("qualifiers", {})),
                    ),
                )
                self._insert_schema_term(
                    self.conn,
                    relation,
                    schema_version_id=sv_id,
                    legacy_kind="relation_type",
                    legacy_id=type_cur.lastrowid,
                    reviewer=reviewer,
                    provenance=provenance,
                    now=now,
                )
        return sv_id

    def list_schemas(self) -> list[dict[str, Any]]:
        """Every ontology this store has held, newest first."""
        return [
            {
                "id": row["id"],
                "label": row["label"],
                "description": row["description"],
                "created_ts": row["created_ts"],
                "active": bool(row["is_active"]),
                # How much was judged under it. A schema with proposals
                # behind it is one a reviewer's decisions depend on.
                "items": self.conn.execute(
                    "SELECT (SELECT COUNT(*) FROM nodes WHERE "
                    "schema_version_id = ?) + (SELECT COUNT(*) FROM edges "
                    "WHERE schema_version_id = ?) AS n",
                    (row["id"], row["id"]),
                ).fetchone()["n"],
            }
            for row in self.conn.execute(
                "SELECT * FROM schema_version ORDER BY id DESC"
            )
        ]

    def activate_schema(self, schema_id: int) -> None:
        """Switch back to an ontology this store already has."""
        row = self.conn.execute(
            "SELECT id FROM schema_version WHERE id = ?", (schema_id,)
        ).fetchone()
        if row is None:
            raise UnknownItem(f"unknown schema id {schema_id}")
        with self.conn:
            self.conn.execute("UPDATE schema_version SET is_active = 0")
            self.conn.execute(
                "UPDATE schema_version SET is_active = 1 WHERE id = ?",
                (schema_id,),
            )

    def type_filter_values(self, entity_type: str) -> list[str]:
        """The type plus every descendant under the is-a hierarchy.

        ``entity_type.parent_name`` made the hierarchy real, but a filter
        that only matched the named type made it decorative: asking for
        ``Chemical`` would not find a ``Herbicide``. Query-side filters
        expand through this helper; identity resolution stays exact —
        a node proposed as ``Herbicide`` must not silently become the
        ``Chemical`` another document meant.

        Descendants are collected across every schema version the store
        holds, because nodes keep pointing at the version they were
        extracted under and a parent may exist in more than one. A type
        no version declares returns itself — the filter degrades to the
        exact match it always was.
        """
        rows = self.conn.execute(
            "SELECT name, parent_name FROM entity_type"
        ).fetchall()
        children: dict[str, list[str]] = {}
        for r in rows:
            if r["parent_name"]:
                children.setdefault(r["parent_name"], []).append(r["name"])
        values = {entity_type}
        stack = [entity_type]
        while stack:
            for child in children.get(stack.pop(), []):
                if child not in values:
                    values.add(child)
                    stack.append(child)
        return sorted(values)

    def _type_filter_sql(self, entity_type: str | None, column: str) -> tuple[str, list[str]]:
        """(SQL fragment, args) for an is-a-aware entity_type filter.

        Emits ``column IN (SELECT value FROM json_each(?))`` — the same
        json_each idiom the edge id-set uses, so the parameter count stays
        one regardless of hierarchy width.
        """
        if not entity_type:
            return "", []
        return (
            f" AND {column} IN (SELECT value FROM json_each(?))",
            [json.dumps(self.type_filter_values(entity_type))],
        )

    # ------------------------------------------------------------------
    # Competency questions bound to a schema version
    # ------------------------------------------------------------------
    #
    # competency.py pins three frozen pipeline gates; these CQs are the
    # design-time counterpart — the questions a schema version must be
    # able to answer, declared before or alongside the vocabulary. A CQ
    # records the term names it depends on; check_schema_cqs reports
    # coverage so a schema that cannot express its own questions fails
    # loudly instead of drifting.

    def add_schema_cq(
        self,
        question: str,
        *,
        requires: list[str] | None = None,
        schema_version_id: int | None = None,
        reviewer: str,
        provenance: str,
    ) -> dict[str, Any]:
        """Bind a competency question to a schema version.

        ``requires`` names the entity/relation types the question needs.
        Existence is deliberately not checked here — a CQ may name a term
        the schema does not have yet, and that gap is exactly what
        ``check_schema_cqs`` reports.
        """
        self._assert_writable()
        if not question.strip():
            raise KGStoreError("competency question must not be empty")
        sv = (
            self.active_schema_version()
            if schema_version_id is None
            else self.conn.execute(
                "SELECT * FROM schema_version WHERE id = ?", (schema_version_id,)
            ).fetchone()
        )
        if sv is None:
            raise UnknownItem(f"unknown schema version id {schema_version_id!r}")
        cq_id = uuid.uuid4().hex
        self.conn.execute(
            "INSERT INTO schema_cq "
            "(id, schema_version_id, question, requires_json, reviewer, "
            "provenance, created_ts) VALUES (?,?,?,?,?,?,?)",
            (
                cq_id,
                sv["id"],
                question.strip(),
                json.dumps(requires or []),
                reviewer,
                provenance,
                time.time(),
            ),
        )
        self.conn.commit()
        return {
            "id": cq_id,
            "schema_version_id": sv["id"],
            "question": question.strip(),
            "requires": requires or [],
        }

    def list_schema_cqs(
        self, schema_version_id: int | None = None
    ) -> list[dict[str, Any]]:
        sv = (
            self.active_schema_version()
            if schema_version_id is None
            else self.conn.execute(
                "SELECT * FROM schema_version WHERE id = ?", (schema_version_id,)
            ).fetchone()
        )
        if sv is None:
            raise UnknownItem(f"unknown schema version id {schema_version_id!r}")
        return [
            {
                "id": r["id"],
                "question": r["question"],
                "requires": json.loads(r["requires_json"]),
                "reviewer": r["reviewer"],
                "provenance": r["provenance"],
                "created_ts": r["created_ts"],
            }
            for r in self.conn.execute(
                "SELECT * FROM schema_cq WHERE schema_version_id = ? "
                "ORDER BY created_ts, id",
                (sv["id"],),
            )
        ]

    def check_schema_cqs(
        self, schema_version_id: int | None = None
    ) -> dict[str, Any]:
        """Coverage check: does the schema declare every term its CQs need?

        Each CQ's ``requires`` names are looked up in the version's
        entity_type and relation_type tables. A CQ with no requirements
        is reported uncovered with reason 'unscoped' — a question that
        names nothing cannot be checked, and silently counting it as
        covered would hide the gap it was written to close.
        """
        schema = self.get_schema(schema_version_id)
        declared = {e["name"] for e in schema["entity_types"]} | {
            r["name"] for r in schema["relation_types"]
        }
        results = []
        for cq in self.list_schema_cqs(schema["schema_version_id"]):
            missing = [t for t in cq["requires"] if t not in declared]
            if not cq["requires"]:
                results.append({**cq, "covered": False, "missing": [],
                                "reason": "unscoped"})
            else:
                results.append({**cq, "covered": not missing,
                                "missing": missing, "reason": None})
        return {
            "schema_version_id": schema["schema_version_id"],
            "total": len(results),
            "covered": sum(1 for r in results if r["covered"]),
            "questions": results,
        }

    def get_schema(self, schema_version_id: int | None = None) -> dict[str, Any]:
        """Return one ontology version (entity + relation types) as plain data.

        Defaults to the active version. Pass ``schema_version_id`` to read a
        specific historical version: packs preserve verified facts judged
        under every version the store has held, so a consumer must resolve
        the exact ontology a fact was extracted against. An unknown id is a
        typed ``UnknownItem``, never a silent fallback to the active schema.
        """
        if schema_version_id is None:
            sv = self.active_schema_version()
        else:
            sv = self.conn.execute(
                "SELECT * FROM schema_version WHERE id = ?", (schema_version_id,)
            ).fetchone()
            if sv is None:
                raise UnknownItem(
                    f"unknown schema version id {schema_version_id!r}"
                )
        entity_types = [
            {
                "name": r["name"],
                "description": r["description"],
                "attributes": json.loads(r["attributes_json"]),
                "parent": r["parent_name"],
            }
            for r in self.conn.execute(
                "SELECT * FROM entity_type WHERE schema_version_id = ? ORDER BY name",
                (sv["id"],),
            )
        ]
        relation_types = [
            {
                "name": r["name"],
                "description": r["description"],
                "domain_type": r["domain_type"],
                "range_type": r["range_type"],
                "directed": bool(r["directed"]),
                "qualifiers": (
                    json.loads(r["qualifiers_json"])
                    if "qualifiers_json" in r.keys() and r["qualifiers_json"]
                    else {}
                ),
            }
            for r in self.conn.execute(
                "SELECT * FROM relation_type WHERE schema_version_id = ? ORDER BY name",
                (sv["id"],),
            )
        ]
        return {
            "schema_version_id": sv["id"],
            "schema_label": sv["label"],
            "entity_types": entity_types,
            "relation_types": relation_types,
        }

    def _ontology_term_row(self, term_id: str) -> sqlite3.Row:
        row = self.conn.execute(
            "SELECT * FROM ontology_term WHERE id = ?", (term_id,)
        ).fetchone()
        if row is None:
            raise UnknownItem(f"unknown ontology term id {term_id!r}")
        return row

    def create_ontology_term(
        self,
        *,
        preferred_label: str,
        language: str,
        definition: str,
        schema_version_id: int,
        reviewer: str,
        provenance: str,
    ) -> str:
        """Create a reviewed term with a random, immutable local identity."""
        self._assert_writable()
        clean_label = self._term_text("preferred_label", preferred_label)
        clean_language = self._term_text("language", language)
        clean_definition = self._term_text("definition", definition)
        clean_reviewer = self._term_text("reviewer", reviewer)
        clean_provenance = self._term_text("provenance", provenance)
        if self.conn.execute(
            "SELECT 1 FROM schema_version WHERE id = ?", (schema_version_id,)
        ).fetchone() is None:
            raise OntologyTermValidationError(
                "schema_version_id", f"unknown schema version {schema_version_id!r}"
            )
        with self._write_tx():
            return self._insert_ontology_term_row(
                self.conn,
                preferred_label=clean_label,
                language=clean_language,
                definition=clean_definition,
                schema_version_id=schema_version_id,
                reviewer=clean_reviewer,
                provenance=clean_provenance,
                now=time.time(),
            )

    def get_ontology_term(self, term_id: str) -> dict[str, Any]:
        """Return one ontology term without rewriting its lifecycle state."""
        return dict(self._ontology_term_row(term_id))

    def add_term_alias(
        self,
        *,
        term_id: str,
        label: str,
        language: str,
        reviewer: str,
        provenance: str,
        alias_kind: str = "alternative",
    ) -> str:
        """Append one reviewed alias; existing alias rows are never rewritten."""
        self._assert_writable()
        self._ontology_term_row(term_id)
        clean_label = self._term_text("label", label)
        clean_language = self._term_text("language", language)
        clean_reviewer = self._term_text("reviewer", reviewer)
        clean_provenance = self._term_text("provenance", provenance)
        if alias_kind not in default_schema.TERM_ALIAS_KINDS:
            raise OntologyTermValidationError(
                "alias_kind", f"unsupported value {alias_kind!r}"
            )
        alias_id = str(uuid.uuid4())
        with self._write_tx():
            self.conn.execute(
                "INSERT INTO term_alias "
                "(id, term_id, label, language, alias_kind, reviewer, provenance, "
                "created_ts) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    alias_id,
                    term_id,
                    clean_label,
                    clean_language,
                    alias_kind,
                    clean_reviewer,
                    clean_provenance,
                    time.time(),
                ),
            )
        return alias_id

    def list_term_aliases(self, term_id: str) -> list[dict[str, Any]]:
        """Return aliases in append order."""
        self._ontology_term_row(term_id)
        rows = self.conn.execute(
            "SELECT * FROM term_alias WHERE term_id = ? ORDER BY rowid",
            (term_id,),
        ).fetchall()
        return [dict(row) for row in rows]

    def rename_ontology_term(
        self,
        term_id: str,
        *,
        preferred_label: str,
        language: str,
        reviewer: str,
        provenance: str,
    ) -> None:
        """Rename a term in place and append its former preferred label."""
        self._assert_writable()
        term = self._ontology_term_row(term_id)
        if term["lifecycle"] == "replaced":
            raise OntologyTermValidationError(
                "lifecycle", "a replaced term cannot be renamed"
            )
        clean_label = self._term_text("preferred_label", preferred_label)
        clean_language = self._term_text("language", language)
        clean_reviewer = self._term_text("reviewer", reviewer)
        clean_provenance = self._term_text("provenance", provenance)
        if (
            clean_label == term["preferred_label"]
            and clean_language == term["language"]
        ):
            raise OntologyTermValidationError(
                "preferred_label", "rename must change the label or language"
            )
        now = time.time()
        with self.conn:
            self.conn.execute(
                "INSERT INTO term_alias "
                "(id, term_id, label, language, alias_kind, reviewer, provenance, "
                "created_ts) VALUES (?, ?, ?, ?, 'former-preferred', ?, ?, ?)",
                (
                    str(uuid.uuid4()),
                    term_id,
                    term["preferred_label"],
                    term["language"],
                    clean_reviewer,
                    clean_provenance,
                    now,
                ),
            )
            self.conn.execute(
                "UPDATE ontology_term SET preferred_label = ?, language = ?, "
                "reviewer = ?, provenance = ?, updated_ts = ? WHERE id = ?",
                (
                    clean_label,
                    clean_language,
                    clean_reviewer,
                    clean_provenance,
                    now,
                    term_id,
                ),
            )

    def _validate_term_lifecycle(
        self,
        *,
        term_id: str,
        lifecycle: str,
        replacement_term_id: str | None,
        change_reason: str | None,
    ) -> tuple[str | None, str | None]:
        if lifecycle not in default_schema.TERM_LIFECYCLES:
            raise OntologyTermValidationError(
                "lifecycle", f"unsupported value {lifecycle!r}"
            )
        if lifecycle == "active":
            if replacement_term_id is not None:
                raise OntologyTermValidationError(
                    "replacement_term_id", "an active term cannot have a replacement"
                )
            return None, None

        reason = self._term_text("change_reason", change_reason)
        if lifecycle == "replaced" and replacement_term_id is None:
            raise OntologyTermValidationError(
                "replacement_term_id", "a replaced term needs a replacement"
            )
        if replacement_term_id is not None:
            if replacement_term_id == term_id:
                raise OntologyTermValidationError(
                    "replacement_term_id", "a term cannot replace itself"
                )
            if self.conn.execute(
                "SELECT 1 FROM ontology_term WHERE id = ?",
                (replacement_term_id,),
            ).fetchone() is None:
                raise OntologyTermValidationError(
                    "replacement_term_id",
                    f"unknown ontology term {replacement_term_id!r}",
                )
        return replacement_term_id, reason

    def set_ontology_term_lifecycle(
        self,
        term_id: str,
        *,
        lifecycle: str,
        change_reason: str | None,
        reviewer: str,
        provenance: str,
        replacement_term_id: str | None = None,
    ) -> None:
        """Set reviewed lifecycle state without changing term identity."""
        self._assert_writable()
        term = self._ontology_term_row(term_id)
        if term["lifecycle"] == "replaced":
            raise OntologyTermValidationError(
                "lifecycle", "a replaced term is terminal"
            )
        replacement, reason = self._validate_term_lifecycle(
            term_id=term_id,
            lifecycle=lifecycle,
            replacement_term_id=replacement_term_id,
            change_reason=change_reason,
        )
        clean_reviewer = self._term_text("reviewer", reviewer)
        clean_provenance = self._term_text("provenance", provenance)
        with self._write_tx():
            self.conn.execute(
                "UPDATE ontology_term SET lifecycle = ?, replacement_term_id = ?, "
                "change_reason = ?, reviewer = ?, provenance = ?, updated_ts = ? "
                "WHERE id = ?",
                (
                    lifecycle,
                    replacement,
                    reason,
                    clean_reviewer,
                    clean_provenance,
                    time.time(),
                    term_id,
                ),
            )

    def change_ontology_term_meaning(
        self,
        term_id: str,
        *,
        preferred_label: str,
        language: str,
        definition: str,
        change_reason: str,
        reviewer: str,
        provenance: str,
    ) -> str:
        """Create a new identity and mark the old meaning as replaced."""
        self._assert_writable()
        old_term = self._ontology_term_row(term_id)
        if old_term["lifecycle"] == "replaced":
            raise OntologyTermValidationError(
                "lifecycle", "a replaced term cannot be replaced again"
            )
        clean_label = self._term_text("preferred_label", preferred_label)
        clean_language = self._term_text("language", language)
        clean_definition = self._term_text("definition", definition)
        clean_reason = self._term_text("change_reason", change_reason)
        clean_reviewer = self._term_text("reviewer", reviewer)
        clean_provenance = self._term_text("provenance", provenance)
        now = time.time()
        with self.conn:
            replacement_id = self._insert_ontology_term_row(
                self.conn,
                preferred_label=clean_label,
                language=clean_language,
                definition=clean_definition,
                schema_version_id=old_term["schema_version_id"],
                reviewer=clean_reviewer,
                provenance=clean_provenance,
                now=now,
            )
            self.conn.execute(
                "UPDATE ontology_term SET lifecycle = 'replaced', "
                "replacement_term_id = ?, change_reason = ?, reviewer = ?, "
                "provenance = ?, updated_ts = ? WHERE id = ?",
                (
                    replacement_id,
                    clean_reason,
                    clean_reviewer,
                    clean_provenance,
                    now,
                    term_id,
                ),
            )
        return replacement_id

    @staticmethod
    def _xref_text(field: str, value: str | None) -> str:
        """Parse one required xref text field."""
        if not isinstance(value, str) or not value.strip():
            raise XrefValidationError(field, "must be a non-empty string")
        return value.strip()

    @staticmethod
    def _xref_number(field: str, value: float | None) -> float:
        """Parse one finite xref number, rejecting booleans."""
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise XrefValidationError(field, "must be a finite number")
        parsed = float(value)
        if not math.isfinite(parsed):
            raise XrefValidationError(field, "must be a finite number")
        return parsed

    def _validate_xref_lifecycle(
        self,
        *,
        xref_id: str,
        term_id: str,
        lifecycle: str | None,
        replacement_xref_id: str | None,
        change_reason: str | None,
    ) -> tuple[str, str | None, str | None]:
        if lifecycle not in default_schema.TERM_LIFECYCLES:
            raise XrefValidationError(
                "lifecycle", f"unsupported value {lifecycle!r}"
            )
        if lifecycle == "active":
            if replacement_xref_id is not None:
                raise XrefValidationError(
                    "replacement_xref_id",
                    "an active xref cannot have a replacement",
                )
            return lifecycle, None, None

        reason = self._xref_text("change_reason", change_reason)
        if lifecycle == "replaced" and replacement_xref_id is None:
            raise XrefValidationError(
                "replacement_xref_id", "a replaced xref needs a replacement"
            )
        if replacement_xref_id is not None:
            if replacement_xref_id == xref_id:
                raise XrefValidationError(
                    "replacement_xref_id", "an xref cannot replace itself"
                )
            replacement = self.conn.execute(
                "SELECT term_id FROM term_xref WHERE id = ?",
                (replacement_xref_id,),
            ).fetchone()
            if replacement is None:
                raise XrefValidationError(
                    "replacement_xref_id",
                    f"unknown term xref {replacement_xref_id!r}",
                )
            if replacement["term_id"] != term_id:
                raise XrefValidationError(
                    "replacement_xref_id",
                    "replacement xref must belong to the same ontology term",
                )
        return lifecycle, replacement_xref_id, reason

    def add_term_xref(
        self,
        *,
        term_id: str,
        authority: str | None = None,
        external_id: str | None = None,
        mapping_predicate: str | None = None,
        source_uri: str | None = None,
        source_version: str | None = None,
        valid_from: float | None = None,
        valid_to: float | None = None,
        retrieved_at: float | None = None,
        confidence: float | None = None,
        reviewer: str | None = None,
        license_gate: str | None = None,
        lifecycle: str | None = "active",
        replacement_xref_id: str | None = None,
        change_reason: str | None = None,
    ) -> str:
        """Append a typed mapping record without changing local identity."""
        self._assert_writable()
        if self.conn.execute(
            "SELECT 1 FROM ontology_term WHERE id = ?", (term_id,)
        ).fetchone() is None:
            raise XrefValidationError("term_id", f"unknown ontology term {term_id!r}")
        clean_authority = self._xref_text("authority", authority)
        clean_external_id = self._xref_text("external_id", external_id)
        clean_predicate = self._xref_text(
            "mapping_predicate", mapping_predicate
        )
        if clean_predicate not in default_schema.XREF_MAPPING_PREDICATES:
            raise XrefValidationError(
                "mapping_predicate", f"unsupported value {clean_predicate!r}"
            )
        clean_source_uri = self._xref_text("source_uri", source_uri)
        clean_reviewer = self._xref_text("reviewer", reviewer)
        clean_license_gate = self._xref_text("license_gate", license_gate)
        if clean_license_gate not in default_schema.XREF_LICENSE_GATES:
            raise XrefValidationError(
                "license_gate", f"unsupported value {clean_license_gate!r}"
            )
        clean_retrieved_at = self._xref_number("retrieved_at", retrieved_at)
        clean_confidence = self._xref_number("confidence", confidence)
        if not 0.0 <= clean_confidence <= 1.0:
            raise XrefValidationError("confidence", "must be between 0 and 1")

        clean_source_version = None
        if source_version is not None:
            clean_source_version = self._xref_text(
                "source_version", source_version
            )
        clean_valid_from = (
            self._xref_number("valid_from", valid_from)
            if valid_from is not None
            else None
        )
        clean_valid_to = (
            self._xref_number("valid_to", valid_to)
            if valid_to is not None
            else None
        )
        if (
            clean_source_version is None
            and clean_valid_from is None
            and clean_valid_to is None
        ):
            raise XrefValidationError(
                "source_version_or_valid_time",
                "source_version or a valid-time bound is required",
            )
        if (
            clean_valid_from is not None
            and clean_valid_to is not None
            and clean_valid_to < clean_valid_from
        ):
            raise XrefValidationError(
                "valid_to", "must not precede valid_from"
            )

        xref_id = str(uuid.uuid4())
        clean_lifecycle, replacement, reason = self._validate_xref_lifecycle(
            xref_id=xref_id,
            term_id=term_id,
            lifecycle=lifecycle,
            replacement_xref_id=replacement_xref_id,
            change_reason=change_reason,
        )
        now = time.time()
        with self._write_tx():
            self.conn.execute(
                "INSERT INTO term_xref "
                "(id, term_id, authority, external_id, mapping_predicate, "
                "source_uri, source_version, valid_from, valid_to, retrieved_at, "
                "confidence, reviewer, lifecycle, replacement_xref_id, "
                "change_reason, license_gate, created_ts, updated_ts) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    xref_id,
                    term_id,
                    clean_authority,
                    clean_external_id,
                    clean_predicate,
                    clean_source_uri,
                    clean_source_version,
                    clean_valid_from,
                    clean_valid_to,
                    clean_retrieved_at,
                    clean_confidence,
                    clean_reviewer,
                    clean_lifecycle,
                    replacement,
                    reason,
                    clean_license_gate,
                    now,
                    now,
                ),
            )
        return xref_id

    def get_term_xref(self, xref_id: str) -> dict[str, Any]:
        """Return one xref record by immutable row identity."""
        row = self.conn.execute(
            "SELECT * FROM term_xref WHERE id = ?", (xref_id,)
        ).fetchone()
        if row is None:
            raise UnknownItem(f"unknown term xref id {xref_id!r}")
        return dict(row)

    def list_term_xrefs(self, term_id: str) -> list[dict[str, Any]]:
        """Return a term's xrefs in append order, including retired rows."""
        self._ontology_term_row(term_id)
        rows = self.conn.execute(
            "SELECT * FROM term_xref WHERE term_id = ? ORDER BY rowid",
            (term_id,),
        ).fetchall()
        return [dict(row) for row in rows]

    def set_term_xref_lifecycle(
        self,
        xref_id: str,
        *,
        lifecycle: str,
        change_reason: str | None,
        reviewer: str,
        replacement_xref_id: str | None = None,
    ) -> None:
        """Retire an xref while preserving its mapping record."""
        self._assert_writable()
        current = self.conn.execute(
            "SELECT * FROM term_xref WHERE id = ?", (xref_id,)
        ).fetchone()
        if current is None:
            raise UnknownItem(f"unknown term xref id {xref_id!r}")
        if current["lifecycle"] == "replaced":
            raise XrefValidationError("lifecycle", "a replaced xref is terminal")
        clean_lifecycle, replacement, reason = self._validate_xref_lifecycle(
            xref_id=xref_id,
            term_id=current["term_id"],
            lifecycle=lifecycle,
            replacement_xref_id=replacement_xref_id,
            change_reason=change_reason,
        )
        clean_reviewer = self._xref_text("reviewer", reviewer)
        with self.conn:
            self.conn.execute(
                "UPDATE term_xref SET lifecycle = ?, replacement_xref_id = ?, "
                "change_reason = ?, reviewer = ?, updated_ts = ? WHERE id = ?",
                (
                    clean_lifecycle,
                    replacement,
                    reason,
                    clean_reviewer,
                    time.time(),
                    xref_id,
                ),
            )
