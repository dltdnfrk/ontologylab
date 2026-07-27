"""Attach curated-resource records to nodes the human already approved.

The paper fan-out answers "what has been written about this topic". This
answers a different question — "what is already known about *this thing*" —
and it runs against the graph rather than against a query.

Two rules shape it, and both come from what a resource record actually is.

**Only verified nodes are enriched.** A proposal is a model's guess that a
person has not accepted yet; looking it up would spend requests on names
that may be rejected within the hour, and would put a UniProt record
against an entity that might never exist. Enrichment is for the part of the
graph that is real.

**A match is a proposal, not a fact.** Nothing UniProt returns is false, so
there is nothing to fact-check — the reviewable question is whether the
record belongs to this node at all. `connectors.resources` makes that
answerable by refusing to guess: exact, field-qualified lookups only, so a
match means the resource has an entry under precisely this symbol. Even
then a human confirms, because symbols collide and a graph node named
`TP53` might be the paper, the pathway, or the protein.

What this deliberately does NOT do is write to the node. An approved
annotation lands in `properties_json` under the resource's own key, at
approval time, in `decide_annotation`. Enrichment only fills a queue.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from ontologylab.connectors.resources import (
    ORGANISM,
    RESOURCE_ORDER,
    ResourceError,
    looks_like_symbol,
    lookup,
)
from ontologylab.kgstore import KGStore


@dataclass
class EnrichmentReport:
    """What one enrichment pass did, in the terms the operator asked in."""

    nodes_considered: int = 0
    lookups: int = 0
    matched: int = 0
    proposed: int = 0
    refreshed: int = 0
    already_decided: int = 0
    skipped_decided: int = 0
    # Names that never reached the network because they cannot be a symbol.
    # Kept apart from `lookups` so the report does not claim to have tried
    # something it declined to try — the two used to be added together, and
    # "19 lookups, 9 matches" read as ten failed requests when most of them
    # were never sent.
    skipped_shape: int = 0
    missed: int = 0
    failures: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "nodes_considered": self.nodes_considered,
            "lookups": self.lookups,
            "matched": self.matched,
            "proposed": self.proposed,
            "refreshed": self.refreshed,
            "already_decided": self.already_decided,
            "skipped_decided": self.skipped_decided,
            "skipped_shape": self.skipped_shape,
            "missed": self.missed,
            # The scope every gene lookup was narrowed to. Reported on every
            # run, not only on a bad one: a graph of plant or microbial
            # genes matches nothing here, and without this the operator sees
            # only "0 matches" and concludes the feature is broken.
            "organism": ORGANISM["label"],
            "failures": list(self.failures),
        }


def _decided_pairs(store: KGStore) -> set[tuple[str, str]]:
    """(node_id, resource) pairs a human has already accepted or rejected.

    Read once per pass rather than per node: it is one small query against
    an indexed status column, and doing it inside the loop would trade the
    network cost this exists to avoid for a database cost.
    """
    try:
        rows = store.conn.execute(
            "SELECT node_id, resource FROM annotations WHERE status != 'proposed'"
        ).fetchall()
    except Exception:
        # A store predating the table has nothing decided; enrich normally.
        return set()
    return {(row["node_id"], row["resource"]) for row in rows}


def verified_node_names(store: KGStore, *, limit: int) -> list[tuple[str, str]]:
    """(id, name) for verified nodes, oldest first.

    Oldest first so a capped run makes steady progress through the graph
    instead of re-examining whatever was approved most recently.
    """
    rows = store.conn.execute(
        "SELECT id, name FROM nodes WHERE status = 'verified' "
        "ORDER BY COALESCE(verified_ts, created_ts) ASC LIMIT ?",
        (limit,),
    ).fetchall()
    return [(row["id"], row["name"]) for row in rows]


def enrich(
    store: KGStore,
    *,
    resources: list[str] | None = None,
    limit: int = 50,
    on_event: Callable[[str, str, Any], None] | None = None,
    lookup_fn: Callable[[str, str], Any] | None = None,
) -> EnrichmentReport:
    """Look every verified node up in each resource; queue what matches.

    `lookup_fn` exists so tests can drive this without a network, and so a
    caller can substitute a cache. It defaults to the real connector.

    A resource that raises is recorded and skipped for that node only. One
    resource being down is not a reason to abandon the pass — the same
    partial-success posture the paper fan-out takes.
    """
    resources = list(resources or RESOURCE_ORDER)
    unknown = [r for r in resources if r not in RESOURCE_ORDER]
    if unknown:
        raise ResourceError(f"unknown resource(s): {sorted(unknown)}")
    do_lookup = lookup_fn or lookup

    # Progressive disclosure, applied to the resource catalog: the catalog
    # may grow without every node paying for every resource on every pass.
    # A (node, resource) pair a human already decided has nothing left to
    # learn — the old code still fetched it and then threw the answer away
    # in `upsert_annotation`, so the cost grew as O(nodes x resources) on
    # every run and none of it could change anything.
    decided = _decided_pairs(store)

    report = EnrichmentReport()
    for node_id, name in verified_node_names(store, limit=limit):
        report.nodes_considered += 1
        for resource in resources:
            if (node_id, resource) in decided:
                report.skipped_decided += 1
                continue
            if not looks_like_symbol(name):
                # Declined locally: no request, so not a lookup.
                report.skipped_shape += 1
                continue
            if on_event is not None:
                on_event("lookup_start", resource, name)
            report.lookups += 1
            try:
                match = do_lookup(resource, name)
            except Exception as exc:  # ResourceError, HTTP, parse — all skippable
                # The message can quote a URL, and these endpoints are
                # keyless, so there is nothing to redact; the name is the
                # operator's own text.
                report.failures.append(f"{resource}/{name}: {type(exc).__name__}")
                if on_event is not None:
                    on_event("lookup_failed", resource, name)
                continue
            if match is None:
                report.missed += 1
                if on_event is not None:
                    on_event("lookup_miss", resource, name)
                continue

            report.matched += 1
            _id, created = store.upsert_annotation(
                node_id=node_id,
                resource=match.resource,
                external_id=match.external_id,
                record_url=match.record_url,
                matched_name=match.matched_name,
                facts=match.facts,
            )
            if created:
                report.proposed += 1
            else:
                # Either a pending row was refreshed, or a decided one was
                # left alone. Distinguishing them tells the operator whether
                # the queue actually grew.
                pending = store.conn.execute(
                    "SELECT status FROM annotations WHERE id = ?", (_id,)
                ).fetchone()
                if pending is not None and pending["status"] == "proposed":
                    report.refreshed += 1
                else:
                    report.already_decided += 1
            if on_event is not None:
                on_event("lookup_match", resource, match.external_id)
    return report
