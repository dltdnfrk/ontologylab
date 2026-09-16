"""sqlite knowledge-graph store for ontologylab (successor to drylab's memory.py).

One sqlite file holds the ontology schema tables, collected documents, and
the graph itself (``nodes`` / ``edges``), each row carrying a status in
``proposed | verified | rejected``. The load-bearing invariant, carried over
from drylab's ``Finding.verified``: **nothing is ever verified except by an
explicit human approval call.** The write API is split so the extraction path
(``insert_proposed``) is physically incapable of writing ``verified``; only
``approve()`` may set it.

The same ``KGStore`` class serves the mutable working DB (read-write, WAL)
and immutable knowledge packs. Read-only callers explicitly distinguish an
immutable finalized database from a mutable WAL-backed live store so live
reads participate in SQLite's normal WAL snapshot semantics.

Entity resolution (ARCHITECTURE.md §5.5) runs inside ``insert_proposed``:
nodes are deduped by ``(schema_version_id, entity_type, normalized_name)``
across proposed+verified rows (plus an alias lookup), and every relation
endpoint is bound to the resolved node id — so the KG is one connected graph,
not per-chunk stars.

Search is tier-1 FTS5 **lexical** search (not vector/semantic); the raw BM25
rank is normalized to a 0..1 higher-is-better ``match_score`` (§5.4).
"""

from __future__ import annotations

import contextlib
import json
import math
import re
import sqlite3
import time
import uuid
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Optional

from ontologylab import evidence
from ontologylab import kg_records
from ontologylab import ontology_schema as default_schema
from ontologylab.connectors.base import normalize_doi
from ontologylab.models import Document, ProposedEntity, ProposedRelation
from ontologylab.paths import DEFAULT_ACTOR
from ontologylab.storage_compatibility import (
    bootstrap_metadata_sql,
    require_writer_compatible,
)
from ontologylab.kgstore_base import (
    DOCUMENT_PANEL_MAX_CHARS,
    MATCH_SCORE_PRECISION,
    REVIEW_STATUSES,
    SPAN_EXCERPT_CONTEXT_CHARS,
    SPAN_EXCERPT_MAX_CHARS,
    VEC_SHORTLIST_FACTOR,
    VEC_SHORTLIST_MIN_MARGIN,
    DocumentIdentityConflict,
    EndpointNotVerified,
    GroundingPreflightError,
    InvalidTransition,
    KGStoreError,
    OntologyTermValidationError,
    SchemaValidationError,
    UnknownItem,
    XrefValidationError,
    normalize_name,
    span_excerpt,
    _execute_sql_script,
    _edge_dict,
    _node_dict,
    _NODE_COLUMNS,
    _SCHEMA,
    _status_clause,
)
from ontologylab.kgstore_lifecycle import LifecycleMixin
from ontologylab.kgstore_schema import SchemaMixin
from ontologylab.kgstore_documents import DocumentsMixin
from ontologylab.kgstore_validation import ValidationMixin
from ontologylab.kgstore_proposed import ProposedMixin
from ontologylab.kgstore_review import ReviewMixin
from ontologylab.kgstore_queue import QueueMixin
from ontologylab.kgstore_context import ReviewContextMixin
from ontologylab.kgstore_communities import CommunitiesMixin
from ontologylab.kgstore_query import QueryMixin
from ontologylab.kgstore_search import SearchMixin
from ontologylab.kgstore_graph import GraphMixin


class KGStore(
    LifecycleMixin,
    SchemaMixin,
    DocumentsMixin,
    ValidationMixin,
    ProposedMixin,
    ReviewMixin,
    QueueMixin,
    ReviewContextMixin,
    CommunitiesMixin,
    QueryMixin,
    SearchMixin,
    GraphMixin,
):
    """Owns one sqlite connection to a working KG or an immutable pack.

    Construct via :meth:`KGStore.open` — a real rewrite of drylab's
    ``memory.open()``: takes an explicit **file** path (not a directory) and
    a ``read_only`` flag. Read-write mode enables WAL; read-only mode executes
    no DDL and defaults to immutable pack semantics. Mutable live stores pass
    ``immutable=False`` to retain normal read-only WAL behavior.
    """



__all__ = [
    "KGStore",
    "KGStoreError",
    "EndpointNotVerified",
    "InvalidTransition",
    "UnknownItem",
    "normalize_name",
    "span_excerpt",
]
