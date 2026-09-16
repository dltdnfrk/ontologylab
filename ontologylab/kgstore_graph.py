"""Filtered subgraphs, neighbor expansion, path finding.

Split from ontologylab/kgstore.py — methods are mixed into KGStore
via ontologylab.kgstore. No behavior change intended.
"""

from __future__ import annotations

from collections import deque
import json
import sqlite3
from typing import Any

from ontologylab.kgstore_base import (
    KGStoreError,
    _edge_dict,
    _node_dict,
    _status_clause,
)

class GraphMixin:

    def graph_query(
        self,
        *,
        entity_type: str | None = None,
        relation_type: str | None = None,
        property_filters: dict[str, Any] | None = None,
        include_proposed: bool = False,
        limit: int = 100,
        offset: int = 0,
    ) -> dict[str, Any]:
        """Filtered subgraph: matching nodes plus the edges among them."""
        status_sql = _status_clause(include_proposed)
        where = [status_sql]
        args: list[Any] = []
        if entity_type:
            where.append("entity_type = ?")
            args.append(entity_type)
        for prop_key, value in (property_filters or {}).items():
            where.append("json_extract(properties_json, ?) = ?")
            args.extend([f"$.{prop_key}", value])
        args.extend([limit, offset])
        node_rows = self.conn.execute(
            f"SELECT * FROM nodes WHERE {' AND '.join(where)} "
            "ORDER BY name LIMIT ? OFFSET ?",
            args,
        ).fetchall()
        nodes = [_node_dict(r) for r in node_rows]
        node_ids = {n["id"] for n in nodes}
        edges: list[dict[str, Any]] = []
        if node_ids:
            # id 집합은 json_each로 한 번만 바인딩 — IN (?,?,…) 확장은 2×N
            # 파라미터라 sqlite<3.32의 host-param 한도(999)를 limit≈500에서
            # 넘어선다 (JSON1의 json_each는 3.9+라 안전).
            ids_json = json.dumps(sorted(node_ids))
            id_set = "(SELECT value FROM json_each(?))"
            edge_where = [
                status_sql,
                self._edge_current_sql(),
                f"src_node_id IN {id_set}",
                f"dst_node_id IN {id_set}",
            ]
            edge_args: list[Any] = [ids_json, ids_json]
            if relation_type:
                edge_where.insert(1, "relation_type = ?")
                edge_args.insert(0, relation_type)
            edges = [
                _edge_dict(r)
                for r in self.conn.execute(
                    f"SELECT * FROM edges WHERE {' AND '.join(edge_where)}", edge_args
                )
            ]
        return {"nodes": nodes, "edges": edges}

    def _neighbors(
        self,
        node_id: str,
        relation_types: list[str] | None,
        direction: str,
        include_proposed: bool,
        mode: str = "structural",
    ) -> list[sqlite3.Row]:
        status_sql = _status_clause(include_proposed, "e")
        rel_sql = ""
        rel_args: list[Any] = []
        if relation_types:
            rel_sql = (
                " AND e.relation_type IN ("
                + ",".join("?" for _ in relation_types)
                + ")"
            )
            rel_args = list(relation_types)
        clauses: list[tuple[str, str, str]] = []
        if direction in ("out", "both"):
            clauses.append(("e.src_node_id = ?", "e.dst_node_id", ""))
        if direction in ("in", "both"):
            semantic_guard = " AND rt.directed = 0" if mode == "semantic" else ""
            clauses.append(("e.dst_node_id = ?", "e.src_node_id", semantic_guard))
        rows: list[sqlite3.Row] = []
        node_status_sql = _status_clause(include_proposed, "n")
        current_sql = self._edge_current_sql("e")
        for where_col, other_col, semantic_guard in clauses:
            rows.extend(
                self.conn.execute(
                    f"SELECT e.*, {other_col} AS other_id FROM edges e "
                    "LEFT JOIN relation_type rt ON rt.schema_version_id = e.schema_version_id "
                    "AND rt.name = e.relation_type "
                    f"JOIN nodes n ON n.id = {other_col} "
                    f"WHERE {where_col} AND {status_sql} AND {current_sql} "
                    f"AND {node_status_sql}{semantic_guard}{rel_sql}",
                    [node_id, *rel_args],
                ).fetchall()
            )
        return rows

    def traverse_relations(
        self,
        start_ids: list[str],
        *,
        relation_types: list[str] | None = None,
        direction: str = "both",
        mode: str = "structural",
        max_hops: int = 2,
        include_proposed: bool = False,
        limit: int = 200,
    ) -> dict[str, Any]:
        """N-hop BFS neighborhood from seed nodes (naive, local-scale)."""
        if direction not in ("in", "out", "both"):
            raise KGStoreError("direction must be 'in', 'out', or 'both'")
        if mode not in ("semantic", "structural"):
            raise KGStoreError("mode must be 'semantic' or 'structural'")
        visited: dict[str, int] = {}
        edge_ids: set[str] = set()
        edges: list[dict[str, Any]] = []
        frontier = deque()
        # Seeds obey the same §9.1 status filter as discovered nodes — a
        # rejected/proposed seed id must not leak through the traversal.
        for node_id in self._filter_ids_by_status(start_ids, include_proposed):
            visited[node_id] = 0
            frontier.append((node_id, 0))
        while frontier:
            node_id, depth = frontier.popleft()
            if depth >= max_hops or len(visited) >= limit:
                continue
            for row in self._neighbors(
                node_id, relation_types, direction, include_proposed, mode
            ):
                if row["id"] not in edge_ids:
                    edge_ids.add(row["id"])
                    edges.append(_edge_dict(row))
                other = row["other_id"]
                if other not in visited and len(visited) < limit:
                    visited[other] = depth + 1
                    frontier.append((other, depth + 1))
        nodes = []
        if visited:
            placeholders = ",".join("?" for _ in visited)
            hydrated = {
                row["id"]: row
                for row in self.conn.execute(
                    f"SELECT * FROM nodes WHERE id IN ({placeholders})",
                    list(visited),
                )
            }
            for node_id, depth in visited.items():
                row = hydrated.get(node_id)
                if row is not None:
                    item = _node_dict(row)
                    item["hop"] = depth
                    nodes.append(item)
        return {"nodes": nodes, "edges": edges}

    def _filter_ids_by_status(
        self, node_ids: list[str], include_proposed: bool
    ) -> list[str]:
        """Return the subset of ``node_ids`` visible under the status filter."""
        if not node_ids:
            return []
        placeholders = ",".join("?" for _ in node_ids)
        visible = {
            row["id"]
            for row in self.conn.execute(
                f"SELECT id FROM nodes WHERE id IN ({placeholders}) "
                f"AND {_status_clause(include_proposed)}",
                list(node_ids),
            )
        }
        return [node_id for node_id in node_ids if node_id in visible]

    def find_path(
        self,
        source_id: str,
        target_id: str,
        *,
        max_hops: int = 6,
        relation_types: list[str] | None = None,
        include_proposed: bool = False,
        mode: str = "structural",
    ) -> dict[str, Any]:
        """Shortest relation path in semantic or structural exploration mode.

        ``structural`` preserves the historical undirected walk. ``semantic``
        follows directed assertions only from source to target while allowing
        undirected relation types in either direction.
        """
        if mode not in ("semantic", "structural"):
            raise KGStoreError("mode must be 'semantic' or 'structural'")
        not_found = {"found": False, "hop_count": None, "path": [], "path_edges": []}
        if source_id == target_id:
            # The trivial self-path only exists if the node itself exists AND
            # is visible under the §9.1 status filter.
            row = self.conn.execute(
                f"SELECT id, name FROM nodes WHERE id = ? "
                f"AND {_status_clause(include_proposed)}",
                (source_id,),
            ).fetchone()
            if row is None:
                return not_found
            return {
                "found": True,
                "hop_count": 0,
                "path": [{"node_id": source_id, "name": row["name"]}],
                "path_edges": [],
            }
        if len(self._filter_ids_by_status([source_id, target_id], include_proposed)) != 2:
            return not_found
        parents: dict[str, tuple[str, sqlite3.Row]] = {}
        visited = {source_id}
        frontier = deque([(source_id, 0)])
        while frontier:
            node_id, depth = frontier.popleft()
            if depth >= max_hops:
                continue
            for row in self._neighbors(
                node_id, relation_types, "both", include_proposed, mode
            ):
                other = row["other_id"]
                if other in visited:
                    continue
                visited.add(other)
                parents[other] = (node_id, row)
                if other == target_id:
                    return self._materialize_path(source_id, target_id, parents)
                frontier.append((other, depth + 1))
        return {"found": False, "hop_count": None, "path": [], "path_edges": []}

    def _materialize_path(
        self,
        source_id: str,
        target_id: str,
        parents: dict[str, tuple[str, sqlite3.Row]],
    ) -> dict[str, Any]:
        path_edges: list[dict[str, Any]] = []
        node_ids = [target_id]
        cursor = target_id
        while cursor != source_id:
            prev, edge_row = parents[cursor]
            path_edges.append(_edge_dict(edge_row))
            node_ids.append(prev)
            cursor = prev
        node_ids.reverse()
        path_edges.reverse()
        path = []
        for node_id in node_ids:
            row = self.conn.execute(
                "SELECT id, name FROM nodes WHERE id = ?", (node_id,)
            ).fetchone()
            path.append({"node_id": node_id, "name": row["name"] if row else None})
        return {
            "found": True,
            "hop_count": len(path_edges),
            "path": path,
            "path_edges": path_edges,
        }
