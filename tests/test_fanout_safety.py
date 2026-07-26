"""Two guards a five-source fan-out needs before it exists.

R1: a paper API's response is read with a cap, because the fan-out multiplies
whatever one endpoint sends by the number of sources, and the XML path then
expands entities on top of that.

M4: `UNIQUE (content_hash)` refusing a concurrent insert must not destroy the
run. The store had no `IntegrityError` handling anywhere, so a second collect
touching the same paper raised through `jobs._run`'s broad except and marked
the entire job failed — discarding every other document it had gathered.
"""

from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path

import pytest

from ontologylab.connectors import paper_api
from ontologylab.connectors.paper_api import (
    MAX_RESPONSE_BYTES,
    ResponseTooLarge,
    _http_get_text,
)
from ontologylab.kgstore import KGStore


class _Response:
    """Enough of an http.client.HTTPResponse for the fetch helper."""

    def __init__(self, payload: bytes) -> None:
        self._payload = payload
        self.headers = _Headers()
        self.reads: list[int | None] = []

    def read(self, amount: int | None = None) -> bytes:
        self.reads.append(amount)
        return self._payload if amount is None else self._payload[:amount]

    def __enter__(self):
        return self

    def __exit__(self, *exc) -> None:
        return None


class _Headers:
    def get_content_charset(self) -> str:
        return "utf-8"


def _serve(monkeypatch, payload: bytes) -> _Response:
    response = _Response(payload)
    monkeypatch.setattr(paper_api, "assert_network_allowed", lambda _: None)
    monkeypatch.setattr(paper_api, "urlopen", lambda *a, **k: response)
    return response


URL = "https://api.crossref.org/works?query=x"


# --------------------------------------------------------------------------
# R1
# --------------------------------------------------------------------------


def test_a_normal_response_is_returned(monkeypatch) -> None:
    _serve(monkeypatch, b"a legitimate answer")
    assert _http_get_text(URL) == "a legitimate answer"


def test_a_response_at_the_cap_is_still_accepted(monkeypatch) -> None:
    _serve(monkeypatch, b"x" * MAX_RESPONSE_BYTES)
    assert len(_http_get_text(URL)) == MAX_RESPONSE_BYTES


def test_an_oversized_response_is_refused_not_truncated(monkeypatch) -> None:
    """Truncating would hand a half-parsed document to the parser."""
    _serve(monkeypatch, b"x" * (MAX_RESPONSE_BYTES + 1))
    with pytest.raises(ResponseTooLarge):
        _http_get_text(URL)


def test_the_read_itself_is_bounded(monkeypatch) -> None:
    """An unbounded `read()` would buffer the whole body before any check."""
    response = _serve(monkeypatch, b"x" * 32)

    _http_get_text(URL)

    assert response.reads, "the helper must have read something"
    assert all(
        amount is not None and amount <= MAX_RESPONSE_BYTES + 1
        for amount in response.reads
    ), f"unbounded read: {response.reads}"


def test_the_offline_refusal_names_only_the_host(monkeypatch) -> None:
    """A URL can carry a publisher key; this message reaches logs and HTTP."""
    seen: list[str] = []

    def _refuse(message: str) -> None:
        seen.append(message)

    monkeypatch.setattr(paper_api, "assert_network_allowed", _refuse)
    monkeypatch.setattr(paper_api, "urlopen", lambda *a, **k: _Response(b""))

    _http_get_text("https://api.elsevier.com/search?apiKey=ELS-secret-value")

    assert seen
    assert "ELS-secret-value" not in seen[0]
    assert "apiKey" not in seen[0]
    assert "api.elsevier.com" in seen[0]


# --------------------------------------------------------------------------
# M4
# --------------------------------------------------------------------------

TEXT = "One paper, fetched by two sources at once."
HASH = "sha256:" + hashlib.sha256(TEXT.encode()).hexdigest()


def _insert(store: KGStore, uri: str):
    return store.insert_document(
        source_kind="paper_api",
        source_uri=uri,
        title="A paper",
        raw_text=TEXT,
        content_hash=HASH,
    )


def test_the_same_document_twice_is_reported_as_not_created(tmp_path) -> None:
    store = KGStore.open(tmp_path / "kg.sqlite")
    try:
        first, created_first = _insert(store, "https://doi.org/10.1/a")
        second, created_second = _insert(store, "https://doi.org/10.1/a")
    finally:
        store.close()

    assert created_first is True
    assert created_second is False
    assert first.id == second.id


class _StaleReadConnection:
    """Real connection whose first documents-SELECT reports a miss.

    This is the interleaving that matters and the one a sequential test
    cannot otherwise produce: the loser's fast-path SELECT ran *before* the
    winner committed, so it saw nothing, and by the time it INSERTs the row
    exists. Only the SELECT is faked; the INSERT reaches the real database
    and the real `UNIQUE (content_hash)` refuses it, so the recovery path
    under test is driven by an actual constraint violation.
    """

    def __init__(self, inner: sqlite3.Connection) -> None:
        self._inner = inner
        self._stale_read_pending = True

    def execute(self, sql: str, *args):
        upper = sql.lstrip().upper()
        if self._stale_read_pending and upper.startswith("SELECT * FROM DOCUMENTS"):
            self._stale_read_pending = False
            return self._inner.execute(
                "SELECT * FROM documents WHERE 0", ()
            )
        return self._inner.execute(sql, *args)

    def __getattr__(self, name: str):
        return getattr(self._inner, name)


def test_a_concurrent_insert_returns_the_winner_instead_of_raising(
    tmp_path,
) -> None:
    """Two writers both miss the SELECT; the constraint refuses the second.

    Before this, the refusal escaped as `sqlite3.IntegrityError`, and
    `jobs._run`'s broad except turned it into a failed job — discarding every
    other document the run had already gathered over one duplicate the caller
    already had.
    """
    db = tmp_path / "kg.sqlite"
    first = KGStore.open(db)
    second = KGStore.open(db)
    try:
        winner, created = _insert(first, "https://doi.org/10.1/a")
        assert created is True

        second.conn = _StaleReadConnection(second.conn)  # type: ignore[assignment]
        loser, created_again = _insert(second, "https://doi.org/10.1/a")

        assert created_again is False, "the loser must not claim it created a row"
        assert loser.id == winner.id, "the loser must be handed the winner's row"
        rows = first.conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
        assert rows == 1
    finally:
        first.close()
        second.close()


class _RefusingConnection:
    """Delegates everything, but fails the documents INSERT for another reason.

    `sqlite3.Connection.execute` is read-only, so the connection is wrapped
    rather than patched.
    """

    def __init__(self, inner: sqlite3.Connection) -> None:
        self._inner = inner

    def execute(self, sql: str, *args):
        if sql.lstrip().upper().startswith("INSERT INTO DOCUMENTS"):
            raise sqlite3.IntegrityError("FOREIGN KEY constraint failed")
        return self._inner.execute(sql, *args)

    def __getattr__(self, name: str):
        return getattr(self._inner, name)


def test_a_constraint_that_is_not_the_content_hash_still_raises(tmp_path) -> None:
    """Recovery must not swallow an integrity failure it cannot explain.

    The recovery path exists for one constraint. If the row is still absent
    after the refusal, something else failed and hiding it would report a
    document as stored when it is not.
    """
    store = KGStore.open(tmp_path / "kg.sqlite")
    try:
        store.conn = _RefusingConnection(store.conn)  # type: ignore[assignment]
        with pytest.raises(sqlite3.IntegrityError):
            _insert(store, "https://doi.org/10.1/a")
    finally:
        store.close()


def test_the_store_is_still_usable_after_a_recovered_race(tmp_path) -> None:
    """A recovered duplicate must not leave the connection in a bad state.

    This is what makes the recovery worth having: the run continues and its
    remaining documents are still stored.
    """
    db = tmp_path / "kg.sqlite"
    first = KGStore.open(db)
    second = KGStore.open(db)
    try:
        _insert(first, "https://doi.org/10.1/a")
        second.conn = _StaleReadConnection(second.conn)  # type: ignore[assignment]
        _insert(second, "https://doi.org/10.1/a")

        other = "A different paper entirely."
        doc, created = second.insert_document(
            source_kind="paper_api",
            source_uri="https://doi.org/10.1/b",
            title="Another",
            raw_text=other,
            content_hash="sha256:" + hashlib.sha256(other.encode()).hexdigest(),
        )
        assert created is True
        assert doc.id
        rows = second.conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
        assert rows == 2
    finally:
        first.close()
        second.close()
