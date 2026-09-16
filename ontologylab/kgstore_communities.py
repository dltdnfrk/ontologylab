"""W12 community rows (written by the pack builder).

Split from ontologylab/kgstore.py — methods are mixed into KGStore
via ontologylab.kgstore. No behavior change intended.
"""

from __future__ import annotations

import json
import time
from typing import Any

from ontologylab.kgstore_base import (
    UnknownItem,
)

class CommunitiesMixin:

    # ------------------------------------------------------------------
    # W12 communities (read side; rows are written by the pack builder)
    # ------------------------------------------------------------------

    def list_communities(self, *, limit: int = 20) -> list[dict[str, Any]]:
        """Communities of this store, largest first. Empty when the store
        predates W12 or no build has computed them (never an error)."""
        if not self._table_exists("communities"):
            return []
        rows = self.conn.execute(
            "SELECT * FROM communities ORDER BY member_count DESC, id LIMIT ?",
            (limit,),
        ).fetchall()
        return [
            {
                "id": r["id"],
                "member_count": r["member_count"],
                "top_members": json.loads(r["top_members_json"]),
                "summary": r["summary"],
                "summary_method": r["summary_method"],
            }
            for r in rows
        ]

    def community_members(self, community_id: str) -> list[dict[str, Any]]:
        """Member nodes of one community (id/name/type/status)."""
        if not self._table_exists("communities"):
            raise UnknownItem(f"unknown community id {community_id!r}")
        exists = self.conn.execute(
            "SELECT 1 FROM communities WHERE id = ?", (community_id,)
        ).fetchone()
        if exists is None:
            raise UnknownItem(f"unknown community id {community_id!r}")
        rows = self.conn.execute(
            "SELECT n.id, n.name, n.entity_type, n.status "
            "FROM community_members m JOIN nodes n ON n.id = m.node_id "
            "WHERE m.community_id = ? ORDER BY n.name",
            (community_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def write_communities(self, rows: list[dict[str, Any]]) -> None:
        """Replace this store's community rows (pack build time only)."""
        self._assert_writable()
        now = time.time()
        self.conn.execute("DELETE FROM community_members")
        self.conn.execute("DELETE FROM communities")
        for row in rows:
            self.conn.execute(
                "INSERT INTO communities (id, member_count, top_members_json, "
                "summary, summary_method, created_ts) VALUES (?, ?, ?, ?, ?, ?)",
                (
                    row["id"],
                    len(row["members"]),
                    json.dumps(row["top_members"]),
                    row["summary"],
                    row["summary_method"],
                    now,
                ),
            )
            for node_id in row["members"]:
                self.conn.execute(
                    "INSERT INTO community_members (community_id, node_id) "
                    "VALUES (?, ?)",
                    (row["id"], node_id),
                )
        self.conn.commit()
