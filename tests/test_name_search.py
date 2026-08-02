"""Substring name search — the finder behind the command palette.

`entity_lookup` resolves an identity: it wants the node the caller already
means, matching the normalized name exactly, then aliases, then falling
back to FTS. That is the wrong shape for a palette. FTS tokenizes on word
boundaries, so `Cas9` does not match `HiFiCas9` — typing three letters of
a name visible on screen returned nothing at all, which makes a palette
useless for the one thing it exists to do.

`name_search` is the finder: substring matching on the same
`normalized_name` key entity resolution uses, ranked exact → prefix →
contained.
"""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

from ontologylab import paths
from ontologylab.kgstore import KGStore
from ontologylab.models import ProposedEntity, SourceSpan
from ontologylab.server import routes
from ontologylab.server.app import create_app

# Names taken from a real research run: the Cas9 variants are exactly the
# case that motivated this — four entities sharing a suffix, which is what
# a reviewer wants to pull up as a group.
NAMES = [
    "HiFiCas9", "HypaCas9", "OptiCas9", "SuperFiCas9",
    "H3K27ac", "H3K4me1", "H3K9me3",
    "Cas9",
    # Sorts alphabetically BEFORE the exact match. Without it, plain
    # alphabetical order also happens to put `Cas9` first, so a test for
    # "exact outranks contained" passed even with the ranking deleted —
    # confirmed by mutation.
    "ACas9",
]


def _seed(tmp_path):
    store = KGStore.open(paths.kg_db_path(tmp_path / "data"))
    text = " ".join(NAMES)
    doc, _ = store.insert_document(
        source_kind="upload",
        source_uri="file:///n.md",
        title="n",
        raw_text=text,
        content_hash="sha256:" + "c" * 64,
    )
    store.insert_proposed(
        [
            ProposedEntity(
                id=uuid.uuid4().hex,   # chunk-minted, as the parser does
                name=name,
                entity_type="Component",
                confidence=0.9,
                source_span=SourceSpan(start=0, end=len(name)),
            )
            for name in NAMES
        ],
        [],
        source_doc_id=doc.id,
        extractor_engine="mock",
        extractor_model=None,
        prompt_version="v1",
    )
    return store


def _names(results):
    return [item["name"] for item in results]


# --------------------------------------------------------------------------
# The gap this closes
# --------------------------------------------------------------------------


def test_a_suffix_finds_every_entity_that_carries_it(tmp_path) -> None:
    """The measured failure: FTS could not see `Cas9` inside `HiFiCas9`."""
    store = _seed(tmp_path)
    try:
        found = _names(store.name_search("Cas9", limit=10))
    finally:
        store.close()

    assert {"HiFiCas9", "HypaCas9", "OptiCas9", "SuperFiCas9"} <= set(found)


def test_entity_lookup_still_cannot_do_this(tmp_path) -> None:
    """Kept as a live record of *why* a second method exists.

    If `entity_lookup` ever gains substring matching this test fails, and
    the right response is to delete `name_search`, not to loosen this.
    """
    store = _seed(tmp_path)
    try:
        resolved = _names(
            store.entity_lookup(name="ypaCas", include_proposed=True, limit=10)
        )
        found = _names(store.name_search("ypaCas", limit=10))
    finally:
        store.close()

    assert "HypaCas9" not in resolved, "entity_lookup grew substring matching"
    assert found == ["HypaCas9"]


def test_a_prefix_finds_the_family(tmp_path) -> None:
    store = _seed(tmp_path)
    try:
        found = _names(store.name_search("H3K", limit=10))
    finally:
        store.close()

    assert set(found) == {"H3K27ac", "H3K4me1", "H3K9me3"}


# --------------------------------------------------------------------------
# Ranking: exact → prefix → contained
# --------------------------------------------------------------------------


def test_an_exact_hit_outranks_the_names_containing_it(tmp_path) -> None:
    """`Cas9` is itself an entity here as well as a suffix of four others.

    Someone typing the whole name means that node; burying it under four
    partial matches would make the palette feel wrong in the one case where
    the user was most specific.
    """
    store = _seed(tmp_path)
    try:
        found = _names(store.name_search("Cas9", limit=10))
    finally:
        store.close()

    assert found[0] == "Cas9"
    # `ACas9` sorts first alphabetically, so this is the assertion that
    # actually distinguishes "ranked" from "sorted by name".
    assert found.index("Cas9") < found.index("ACas9")


def test_normalization_matches_the_store_s_own_rule(tmp_path) -> None:
    """Case and punctuation are folded the same way entity resolution
    folds them, so the palette and the graph cannot disagree about what
    "the same name" means."""
    store = _seed(tmp_path)
    try:
        assert _names(store.name_search("hificas9")) == ["HiFiCas9"]
        assert _names(store.name_search("hi-fi cas 9")) == ["HiFiCas9"]
    finally:
        store.close()


def test_shorter_names_come_first_within_a_bucket(tmp_path) -> None:
    """A tie-break that is stated rather than incidental: the shortest
    containing name is the closest thing to what was typed."""
    store = _seed(tmp_path)
    try:
        found = _names(store.name_search("Cas", limit=10))
    finally:
        store.close()

    lengths = [len(name) for name in found]
    assert lengths == sorted(lengths)


# --------------------------------------------------------------------------
# Edges
# --------------------------------------------------------------------------


@pytest.mark.parametrize("query", ["", "   ", "!!!", "…"])
def test_a_query_with_no_searchable_characters_finds_nothing(
    tmp_path, query
) -> None:
    """Normalization strips these to empty; a bare `LIKE '%%'` would
    otherwise return the entire graph on a keystroke of punctuation."""
    store = _seed(tmp_path)
    try:
        assert store.name_search(query) == []
    finally:
        store.close()


def test_a_wildcard_is_matched_literally(tmp_path) -> None:
    """`%` and `_` are LIKE metacharacters. Normalization removes them
    before they reach SQL, so they cannot widen the match — this pins that
    they do not, whatever normalization does later."""
    store = _seed(tmp_path)
    try:
        assert store.name_search("%") == []
        assert store.name_search("_") == []
    finally:
        store.close()


def test_the_limit_is_honoured(tmp_path) -> None:
    store = _seed(tmp_path)
    try:
        assert len(store.name_search("Cas", limit=2)) == 2
    finally:
        store.close()


def test_proposals_are_included_by_default(tmp_path) -> None:
    """The palette's most useful question during review is "have I seen
    this name before?", and every one of these is still `proposed`."""
    store = _seed(tmp_path)
    try:
        assert store.name_search("HiFiCas9")
        assert store.name_search("HiFiCas9", include_proposed=False) == []
    finally:
        store.close()


# --------------------------------------------------------------------------
# Through the endpoint the palette calls
# --------------------------------------------------------------------------


def _client(tmp_path) -> TestClient:
    data_dir = tmp_path / "data"
    return TestClient(create_app(data_dir=data_dir))


def test_the_endpoint_returns_what_the_palette_renders(tmp_path) -> None:
    _seed(tmp_path).close()
    client = _client(tmp_path)

    body = client.get("/api/search", params={"q": "Cas9", "limit": 5}).json()

    assert body["results"]
    for item in body["results"]:
        # The palette shows kind (from status), name, and type. Anything
        # missing here renders as a blank column.
        assert set(item) >= {"id", "name", "entity_type", "status"}


def test_the_endpoint_refuses_an_empty_query(tmp_path) -> None:
    """It runs on every keystroke; an unbounded query is not a 500."""
    _seed(tmp_path).close()
    client = _client(tmp_path)

    assert client.get("/api/search", params={"q": ""}).status_code == 422


def test_the_endpoint_bounds_the_result_count(tmp_path) -> None:
    _seed(tmp_path).close()
    client = _client(tmp_path)

    assert client.get("/api/search", params={"q": "a", "limit": 999}).status_code == 422


def test_an_empty_store_answers_with_an_empty_list(tmp_path) -> None:
    """A fresh install opens the palette before collecting anything."""
    client = _client(tmp_path)

    body = client.get("/api/search", params={"q": "anything"}).json()

    assert body == {"results": []}
