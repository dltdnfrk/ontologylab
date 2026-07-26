"""W12 community detection + summaries, computed ONCE at pack build time.

Answers corpus-level questions BFS can't ("what are the main themes of this
pack?"): the verified subgraph is partitioned into communities, each
community gets a summary, and the MCP server exposes them read-only.
Computing at build time keeps the immutable-pack philosophy intact: a
pack's communities never shift under a client.

**The partition algorithm is Leiden** (Traag, Waltman & van Eck,
*Scientific Reports* 2019) when ``leidenalg``/``igraph`` are installed —
``pip install 'ontologylab[graph]'``. Leiden is what the reference
architecture for this pipeline (GraphRAG) uses, and the paper's finding is
the reason: even Louvain leaves up to 25% of communities badly connected
and up to 16% outright disconnected, while Leiden **guarantees** connected
communities. A community summary is a claim that its members belong
together; a disconnected community makes that claim false on its face.

Without the optional dependency the module falls back to the original
deterministic label propagation — honest but weaker (no objective
function, no connectivity guarantee) — and ``community_algorithm()``
reports which one is active so a pack build can record it.

Determinism either way: Leiden runs with a fixed seed over vertices added
in sorted-id order; label propagation visits nodes in sorted-id order and
breaks label ties to the smallest label. The same graph always yields the
same partition.

Summaries are **extractive by default** (top members by degree + relation-
type counts — honest, no model involved, labeled ``extractive``). An
optional summarizer callback (e.g. LLM-backed, built by the CLI) can
replace them, labeled with its own method string; any summarizer failure
falls back to the extractive text.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any, Callable, Optional

MAX_ITERATIONS = 20
TOP_MEMBERS = 5

# Fixed seed for Leiden's internal refinement RNG. Any constant works; it
# exists so two builds of the same graph produce the same partition.
LEIDEN_SEED = 7


def _leiden_available() -> bool:
    try:  # pragma: no cover - trivially environment-dependent
        import igraph  # noqa: F401
        import leidenalg  # noqa: F401
    except ImportError:
        return False
    return True


def community_algorithm() -> str:
    """Which partitioner a build on this machine will use."""
    return "leiden" if _leiden_available() else "label_propagation"

# A summarizer takes (member_names_by_degree, relation_type_counts) and
# returns summary text, or None to keep the extractive fallback.
Summarizer = Callable[[list[str], dict[str, int]], Optional[str]]


def detect_communities(
    node_ids: list[str],
    edge_pairs: list[tuple[str, str]],
    *,
    max_iterations: int = MAX_ITERATIONS,
    algorithm: str = "auto",
) -> list[list[str]]:
    """Partition nodes into communities.

    Returns member-id lists (each sorted), largest community first (ties:
    smallest member id). Isolated nodes come out as singleton communities.

    ``algorithm``: ``"auto"`` uses Leiden when installed and label
    propagation otherwise; the explicit names force one backend (Leiden
    raises if unavailable rather than silently degrading — a caller that
    asks by name is asking for the guarantee, not the label).
    """
    known = set(node_ids)
    ordered = sorted(known)
    # One canonical edge set for both backends: undirected, deduplicated,
    # self-loops and unknown endpoints dropped.
    undirected: set[tuple[str, str]] = set()
    for src, dst in edge_pairs:
        if src in known and dst in known and src != dst:
            undirected.add((min(src, dst), max(src, dst)))

    if algorithm == "auto":
        algorithm = community_algorithm()
    if algorithm == "leiden":
        if not _leiden_available():
            raise RuntimeError(
                "leiden was requested by name but leidenalg/igraph are not "
                "installed; pip install 'ontologylab[graph]'"
            )
        groups = _leiden(ordered, sorted(undirected))
    elif algorithm == "label_propagation":
        groups = _label_propagation(ordered, undirected, max_iterations)
    else:
        raise ValueError(f"unknown community algorithm {algorithm!r}")
    return sorted(groups, key=lambda m: (-len(m), m[0]))


def _leiden(ordered_ids: list[str], edges: list[tuple[str, str]]) -> list[list[str]]:
    """Leiden with modularity, seeded — connected communities, guaranteed.

    Vertices are added in sorted-id order and the refinement RNG is seeded,
    so the partition is a pure function of the graph.
    """
    import igraph
    import leidenalg

    index = {node_id: i for i, node_id in enumerate(ordered_ids)}
    graph = igraph.Graph(
        n=len(ordered_ids),
        edges=[(index[a], index[b]) for a, b in edges],
    )
    partition = leidenalg.find_partition(
        graph,
        leidenalg.ModularityVertexPartition,
        seed=LEIDEN_SEED,
        n_iterations=-1,  # run to convergence, not a fixed pass count
    )
    return [sorted(ordered_ids[i] for i in community) for community in partition]


def _label_propagation(
    ordered: list[str],
    undirected: set[tuple[str, str]],
    max_iterations: int,
) -> list[list[str]]:
    """The original stdlib fallback: deterministic label propagation.

    Kept verbatim in behaviour for installs without the optional graph
    dependency. No objective function and no connectivity guarantee — which
    is why Leiden replaces it whenever it can.
    """
    adjacency: dict[str, set[str]] = defaultdict(set)
    for src, dst in undirected:
        adjacency[src].add(dst)
        adjacency[dst].add(src)

    labels = {node_id: node_id for node_id in ordered}
    for _ in range(max_iterations):
        changed = False
        for node_id in ordered:
            neighbors = adjacency.get(node_id)
            if not neighbors:
                continue
            counts = Counter(labels[n] for n in neighbors)
            top = max(counts.values())
            best = min(label for label, n in counts.items() if n == top)
            if best != labels[node_id]:
                labels[node_id] = best
                changed = True
        if not changed:
            break

    groups: dict[str, list[str]] = defaultdict(list)
    for node_id in ordered:
        groups[labels[node_id]].append(node_id)
    return list(groups.values())


def extractive_summary(
    member_names: list[str], relation_counts: dict[str, int]
) -> str:
    """Model-free summary: who anchors the community + how it is wired."""
    anchors = ", ".join(member_names[:TOP_MEMBERS])
    text = f"{len(member_names)} entities centered on {anchors}"
    if relation_counts:
        rels = ", ".join(
            f"{name} ×{count}"
            for name, count in sorted(
                relation_counts.items(), key=lambda kv: (-kv[1], kv[0])
            )
        )
        text += f"; internal relations: {rels}"
    return text


def build_communities(
    nodes: list[dict[str, Any]],
    edges: list[dict[str, Any]],
    *,
    summarizer: Summarizer | None = None,
    summary_method: str = "extractive",
) -> list[dict[str, Any]]:
    """Detect communities over a (verified) subgraph and summarize each.

    ``nodes``/``edges`` use the kgstore dict shapes (``id``/``name``,
    ``source_id``/``target_id``/``relation_type``). Returns rows ready for
    the ``communities`` table: id, members, top_members, summary, method.
    """
    node_ids = [n["id"] for n in nodes]
    name_by_id = {n["id"]: n["name"] for n in nodes}
    edge_pairs = [(e["source_id"], e["target_id"]) for e in edges]

    degree: Counter[str] = Counter()
    for src, dst in edge_pairs:
        degree[src] += 1
        degree[dst] += 1

    rows: list[dict[str, Any]] = []
    for index, members in enumerate(detect_communities(node_ids, edge_pairs)):
        member_set = set(members)
        member_names = [
            name_by_id[m]
            for m in sorted(members, key=lambda m: (-degree[m], name_by_id[m]))
        ]
        relation_counts: dict[str, int] = Counter(
            e["relation_type"]
            for e in edges
            if e["source_id"] in member_set and e["target_id"] in member_set
        )
        fallback = extractive_summary(member_names, dict(relation_counts))
        summary, method = fallback, "extractive"
        if summarizer is not None:
            try:
                custom = summarizer(member_names, dict(relation_counts))
            except Exception:
                custom = None  # fail open to the extractive fallback
            if custom:
                summary, method = custom.strip(), summary_method
        rows.append(
            {
                "id": f"community-{index:03d}",
                "members": members,
                "top_members": member_names[:TOP_MEMBERS],
                "summary": summary,
                "summary_method": method,
            }
        )
    return rows


def build_summary_prompt(
    member_names: list[str], relation_counts: dict[str, int]
) -> str:
    """LLM prompt for one community summary (optional tier over extractive)."""
    import json

    from ontologylab.engines import (
        COMMUNITY_MARKER_CLOSE,
        COMMUNITY_MARKER_OPEN,
    )

    payload = json.dumps(
        {"members": member_names, "relation_counts": relation_counts},
        ensure_ascii=False,
    )
    return f"""You summarize one community of a verified knowledge graph.

Write ONE plain-text sentence (no markdown, no preamble) describing what
this cluster of entities is about, grounded ONLY in the member names and
relation counts below. Do not invent facts beyond them.

{COMMUNITY_MARKER_OPEN}
{payload}
{COMMUNITY_MARKER_CLOSE}"""


def llm_summarizer(engine, *, model: str | None = None) -> Summarizer:
    """Wrap an engine as a synchronous Summarizer (fail-open per community)."""
    import asyncio

    def summarize(
        member_names: list[str], relation_counts: dict[str, int]
    ) -> Optional[str]:
        prompt = build_summary_prompt(member_names, relation_counts)
        try:
            text, _usage = asyncio.run(engine.generate(prompt, model=model))
        except Exception:
            return None  # build_communities keeps the extractive fallback
        text = text.strip()
        return text or None

    return summarize


__all__ = [
    "detect_communities",
    "extractive_summary",
    "build_communities",
    "build_summary_prompt",
    "llm_summarizer",
]
