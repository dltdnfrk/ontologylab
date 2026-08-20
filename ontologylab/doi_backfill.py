"""Dry-run DOI backfill policy for populated legacy stores (Wave 2.1).

Step 5 owns executing the backfill with cursor/ledger/collision machinery;
this module pins the POLICY (D10) as a pure, read-only classifier so the
executable contract exists before any migration runs: derivation is
exact-resolver only, a candidate already owned by another row or derived
by more than one NULL-doi row is a collision with zero accepted owner, and
everything else is left alone. Nothing here writes.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from collections import Counter
from dataclasses import asdict, dataclass

from ontologylab.connectors.base import normalize_doi

# Exact resolver shapes only (D10): a bare DOI string or any other URI is
# NOT evidence that the row's identity ever lived in source_uri.
_RESOLVER_URI_PREFIXES = (
    "https://doi.org/",
    "http://doi.org/",
    "https://dx.doi.org/",
    "http://dx.doi.org/",
)


def _exact_resolver_candidate(source_uri: str) -> str | None:
    """A DOI candidate only when the URI is exactly resolver-shaped."""
    if not source_uri.lower().startswith(_RESOLVER_URI_PREFIXES):
        return None
    return normalize_doi(source_uri)


@dataclass(frozen=True, slots=True)
class BackfillEntry:
    """One NULL-doi row's classification under the frozen policy."""

    doc_id: str
    source_uri: str
    candidate_doi: str | None
    classification: str  # backfillable | collision_owner | collision_ambiguous | non_derivable


@dataclass(frozen=True, slots=True)
class BackfillPlan:
    """Deterministic dry-run receipt over one store snapshot."""

    entries: tuple[BackfillEntry, ...]
    counts: dict[str, int]
    plan_sha256: str


def plan_doi_backfill(conn: sqlite3.Connection) -> BackfillPlan:
    """Classify every NULL-doi row without writing anything.

    Precedence per row: no exact-resolver candidate -> ``non_derivable``;
    candidate already owned by a row with a doi -> ``collision_owner``;
    candidate derived by two or more NULL-doi rows -> ``collision_ambiguous``
    (zero accepted owner until a human resolves it); otherwise
    ``backfillable``.
    """
    owned = {
        row[0]
        for row in conn.execute(
            "SELECT doi FROM documents WHERE doi IS NOT NULL"
        )
    }
    legacy = conn.execute(
        "SELECT id, source_uri FROM documents WHERE doi IS NULL ORDER BY id"
    ).fetchall()
    candidates = {
        row[0]: _exact_resolver_candidate(row[1]) for row in legacy
    }
    derived = Counter(c for c in candidates.values() if c is not None)

    entries: list[BackfillEntry] = []
    for row in legacy:
        doc_id, source_uri = row[0], row[1]
        candidate = candidates[doc_id]
        if candidate is None:
            classification = "non_derivable"
        elif candidate in owned:
            classification = "collision_owner"
        elif derived[candidate] > 1:
            classification = "collision_ambiguous"
        else:
            classification = "backfillable"
        entries.append(
            BackfillEntry(
                doc_id=doc_id,
                source_uri=source_uri,
                candidate_doi=candidate,
                classification=classification,
            )
        )

    payload = json.dumps(
        [asdict(entry) for entry in entries],
        sort_keys=True,
        separators=(",", ":"),
    )
    return BackfillPlan(
        entries=tuple(entries),
        counts=dict(Counter(entry.classification for entry in entries)),
        plan_sha256=hashlib.sha256(payload.encode("utf-8")).hexdigest(),
    )
