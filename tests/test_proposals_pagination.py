"""Keyset pagination for the review queue (GAP-O1).

The queue used to render every pending proposal into the DOM at once —
327 pending meant 4,231 nodes and 451 buttons. The API now pages in
stable order (default 50, max 100) and the UI renders one page plus
scroll/keyboard load-more, so the initial DOM stays bounded no matter
how large the queue is.

These tests pin the API contract: stable order across pages, no
duplicates or gaps, bounded default and maximum page size, and a UI
that never asks for more than 100 rows on its first render.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pytest

_ROOT = str(Path(__file__).resolve().parent.parent)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

try:
    from fastapi.testclient import TestClient
except ImportError:  # pragma: no cover
    TestClient = None  # type: ignore[assignment]

if TestClient is None:
    pytest.skip("fastapi is not installed", allow_module_level=True)

from ontologylab.kgstore import KGStore  # noqa: E402
from ontologylab.models import ProposedEntity  # noqa: E402
from ontologylab.server.app import WEB_DIR, create_app  # noqa: E402


def _client(tmp_path: Path, n: int) -> TestClient:
    """Client with ``n`` proposed nodes, confidence varying by index."""
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    store = KGStore.open(data_dir / "kg.sqlite")
    doc, _ = store.insert_document(
        source_kind="upload",
        source_uri="file:///t.txt",
        title="t",
        raw_text="Alpha component",
        content_hash="pg-h1",
    )
    for i in range(n):
        store.insert_proposed(
            [ProposedEntity(
                id=f"n_{i:04d}",
                entity_type="Component",
                name=f"Alpha{i}",
                confidence=(i % 10) / 10.0,
            )],
            [],
            source_doc_id=doc.id,
            extractor_engine="mock",
        )
    store.close()
    return TestClient(create_app(data_dir=data_dir))


def _walk(client: TestClient, order: str, limit: int) -> list[dict]:
    """Walk every page of the queue, returning all items in order."""
    items: list[dict] = []
    cursor: str | None = None
    pages = 0
    while True:
        url = f"/api/proposals?limit={limit}&order={order}"
        if cursor:
            url += "&cursor=" + cursor
        body = client.get(url).json()
        items.extend(body["items"])
        pages += 1
        assert pages <= 100, "runaway pagination loop"
        if not body["has_more"]:
            assert body["next_cursor"] is None
            break
        assert body["next_cursor"] is not None
        cursor = body["next_cursor"]
    return items


def test_proposals_cursor_stable_order(tmp_path: Path) -> None:
    client = _client(tmp_path, 25)
    seen = _walk(client, "created", 10)
    assert len(seen) == 25
    ids = [i["id"] for i in seen]
    assert len(set(ids)) == 25, "cursor pagination must not skip or repeat rows"
    # created ASC, id ASC tiebreak → deterministic insertion order
    assert ids == sorted(ids)


def test_proposals_cursor_confidence_order(tmp_path: Path) -> None:
    client = _client(tmp_path, 25)
    seen = _walk(client, "confidence", 8)
    assert len(seen) == 25
    assert len({i["id"] for i in seen}) == 25
    confs = [i["confidence"] for i in seen]
    # least-certain first: ascending, NULLs last
    seen_null = False
    for conf in confs:
        if conf is None:
            seen_null = True
        else:
            assert seen_null is False, "NULL confidence must sort last"
    for a, b in zip(confs, confs[1:]):
        if a is not None and b is not None:
            assert a <= b


def test_proposals_default_page_is_bounded(tmp_path: Path) -> None:
    client = _client(tmp_path, 150)
    body = client.get("/api/proposals").json()
    assert len(body["items"]) == 50, "default page must stay at 50 rows"
    assert body["has_more"] is True
    assert body["next_cursor"] is not None
    assert body["count"] == 50

    # the cursor round-trips: the second page starts where the first ended
    two = client.get(
        "/api/proposals?limit=50&order=created&cursor=" + body["next_cursor"]
    ).json()
    assert len(two["items"]) == 50
    first_ids = {i["id"] for i in body["items"]}
    assert not (first_ids & {i["id"] for i in two["items"]})


def test_proposals_limit_cap(tmp_path: Path) -> None:
    client = _client(tmp_path, 150)
    assert client.get("/api/proposals?limit=100").json()["count"] == 100
    assert client.get("/api/proposals?limit=101").status_code == 422
    assert client.get("/api/proposals?limit=0").status_code == 422


def test_proposals_bad_cursor_is_400(tmp_path: Path) -> None:
    client = _client(tmp_path, 5)
    assert client.get("/api/proposals?cursor=not-json").status_code == 400
    assert client.get("/api/proposals?cursor=%5B1%5D").status_code == 400


def test_review_ui_row_cap() -> None:
    """The UI's first render must never exceed 100 rows (DoD)."""
    script = (WEB_DIR / "app.js").read_text(encoding="utf-8")
    size = re.search(r"var reviewPageSize = (\d+);", script)
    assert size is not None, "reviewPageSize constant must exist"
    assert int(size.group(1)) <= 100
    # the first-page request must use the paged URL, not a hardcoded 200
    assert re.search(
        r'"/api/proposals\?limit=" \+ reviewPageSize', script
    ), "loadProposals must request exactly reviewPageSize rows"


def test_review_scroll_listener_catches_the_real_scroll_container() -> None:
    """The page scrolls inside <main> (overflow-y: auto), not the window.

    A window listener never fired on wheel — the smoke test (2026-08-06)
    reproduced scroll-to-bottom loading nothing. The hook must be attached
    at document level in the capture phase so it sees any container's
    scroll.
    """
    script = (WEB_DIR / "app.js").read_text(encoding="utf-8")
    assert re.search(
        r'document\.addEventListener\("scroll", reviewMaybeLoadMore, \{\s*capture: true',
        script,
    ), "scroll hook must be document-level capture, not window"