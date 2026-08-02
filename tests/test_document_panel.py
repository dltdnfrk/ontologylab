"""Approving a proposal means judging whether the paper says it.

The entity view answers that one 160-character excerpt at a time, which is
enough to check a single mention and not enough to notice that eleven
proposals came from the same sentence, or that the authors hedge in the
next clause. The document panel is the other direction: one source, and
everything drawn from it, with the cited spans located in the text.

What is pinned here is mostly about honesty at the edges — a span past the
truncation point, a proposal with no span at all, a document whose text is
gone. Each of those has a wrong answer that looks right on screen.
"""

from __future__ import annotations

import os
import re

import pytest
from fastapi.testclient import TestClient

from ontologylab.kgstore import DOCUMENT_PANEL_MAX_CHARS, KGStore
from ontologylab.models import ProposedEntity, ProposedRelation, SourceSpan
from ontologylab.server import routes
from ontologylab.server.app import create_app

TEXT = "TP53 is a tumor suppressor. Mutant p53 drives invasion in some tumors."


def _store(tmp_path) -> KGStore:
    return KGStore.open(tmp_path / "kg.sqlite")


def _seed(store: KGStore, text: str = TEXT):
    doc, _ = store.insert_document(
        source_kind="paper_api",
        source_uri="http://example.org/a",
        title="p53 review",
        raw_text=text,
        content_hash="hash-a",
    )
    return doc


def _entity(name: str, start: int | None = None, end: int | None = None):
    return ProposedEntity(
        id=name,
        entity_type="Gene",
        name=name,
        confidence=0.9,
        source_span=None if start is None else SourceSpan(start=start, end=end),
    )


def _insert(store, doc, entities, relations=()):
    store.insert_proposed(
        list(entities),
        list(relations),
        source_doc_id=doc.id,
        extractor_engine="mock",
        extractor_model=None,
        prompt_version="v1",
    )


def _ids_by_label(store) -> dict[str, str]:
    return {
        item["label"]: item["id"]
        for kind in ("node", "edge")
        for item in store.pending_review(kind=kind)
    }


# --------------------------------------------------------------------------
# What the panel is for
# --------------------------------------------------------------------------


def test_the_document_carries_everything_drawn_from_it(tmp_path) -> None:
    store = _store(tmp_path)
    doc = _seed(store)
    _insert(store, doc, [_entity("TP53", 0, 4), _entity("Mutant p53", 28, 38)])

    context = store.document_review_context(doc.id)

    assert context["title"] == "p53 review"
    assert [i["label"] for i in context["items"]] == ["TP53", "Mutant p53"]
    assert [i["span"] for i in context["items"]] == [
        {"start": 0, "end": 4}, {"start": 28, "end": 38}
    ]
    store.close()


def test_a_span_locates_the_words_it_claims(tmp_path) -> None:
    """The offsets are into the text this payload carries, not into some
    other copy of it. A panel that highlights the wrong words is worse than
    one that highlights nothing — it asserts evidence that is not there."""
    store = _store(tmp_path)
    doc = _seed(store)
    _insert(store, doc, [_entity("TP53", 0, 4)])

    context = store.document_review_context(doc.id)
    span = context["items"][0]["span"]

    assert context["text"][span["start"]:span["end"]] == "TP53"
    store.close()


def test_a_relation_is_labelled_by_both_endpoints(tmp_path) -> None:
    """An edge shown as `related_to` alone cannot be judged."""
    store = _store(tmp_path)
    doc = _seed(store)
    _insert(
        store, doc,
        [_entity("TP53", 0, 4), _entity("Mutant p53", 28, 38)],
        [ProposedRelation(
            id="r1", relation_type="related_to",
            src_entity_id="TP53", dst_entity_id="Mutant p53",
            confidence=0.8, source_span=SourceSpan(start=0, end=38),
        )],
    )

    items = store.document_review_context(doc.id)["items"]
    edge = [i for i in items if i["kind"] == "edge"][0]

    assert edge["label"] == "TP53 → Mutant p53"
    assert edge["type"] == "related_to"
    store.close()


# --------------------------------------------------------------------------
# The edges where a wrong answer looks right
# --------------------------------------------------------------------------


def test_a_span_past_the_truncation_point_is_reported_as_absent(
    tmp_path,
) -> None:
    """The one that would silently mislead.

    Full text of an open-access paper runs past the cap. A span at offset
    60,000 into a payload holding 40,000 characters is not a position the
    panel can draw — and drawing it at whatever happens to be at the end of
    the excerpt would attribute the wrong sentence to the proposal.
    """
    store = _store(tmp_path)
    long_text = "x" * (DOCUMENT_PANEL_MAX_CHARS + 500) + " TP53 late mention."
    doc = _seed(store, long_text)
    _insert(store, doc, [
        _entity("early", 10, 20),
        _entity("late", DOCUMENT_PANEL_MAX_CHARS + 501,
                DOCUMENT_PANEL_MAX_CHARS + 505),
    ])
    ids = _ids_by_label(store)

    context = store.document_review_context(doc.id)
    by_id = {i["id"]: i for i in context["items"]}

    assert context["truncated"] is True
    assert context["total_chars"] == len(long_text)
    assert len(context["text"]) == DOCUMENT_PANEL_MAX_CHARS
    assert by_id[ids["early"]]["span"] == {"start": 10, "end": 20}
    assert by_id[ids["late"]]["span"] is None, "a span nobody can draw"
    # The proposal is still listed — it exists and still needs reviewing.
    assert by_id[ids["late"]]["label"] == "late"
    store.close()


def test_a_proposal_without_a_span_is_still_listed(tmp_path) -> None:
    """The extractor proposes relation endpoints that do not appear in the
    chunk, with a warning. Dropping them here would hide exactly the
    proposals that most need a human."""
    store = _store(tmp_path)
    doc = _seed(store)
    _insert(store, doc, [_entity("TP53", 0, 4), _entity("unstated")])
    ids = _ids_by_label(store)

    items = store.document_review_context(doc.id)["items"]
    by_id = {i["id"]: i for i in items}

    assert ids["unstated"] in by_id
    assert by_id[ids["unstated"]]["span"] is None
    store.close()


def test_a_document_whose_text_is_gone_still_opens(tmp_path) -> None:
    """The proposals are in sqlite; the raw text is a file next to it. One
    can be missing without the other, and the panel is how a reviewer would
    find out — so it must not be the thing that breaks."""
    store = _store(tmp_path)
    doc = _seed(store)
    _insert(store, doc, [_entity("TP53", 0, 4)])
    removed = 0
    for path in tmp_path.rglob("*"):
        # The raw text only. Sweeping by "not a database file" would also
        # unlink the store and leave this passing for the wrong reason.
        if path.is_file() and path.suffix == ".txt":
            path.unlink()
            removed += 1
    assert removed, "the raw text file was not where this test thinks it is"

    context = store.document_review_context(doc.id)

    assert context["text"] == ""
    assert len(context["items"]) == 1
    store.close()


# --------------------------------------------------------------------------
# Through the endpoint
# --------------------------------------------------------------------------


@pytest.fixture()
def client(tmp_path):
    os.environ.setdefault("ONTOLOGYLAB_ALLOWED_HOSTS", "testserver")
    data_dir = tmp_path / "data"
    return TestClient(create_app(data_dir=data_dir, packs_dir=tmp_path / "packs"))


def test_an_unknown_document_is_a_404_not_a_500(client) -> None:
    assert client.get("/api/document/no-such-doc/review").status_code == 404


def test_the_server_sends_offsets_not_markup(client) -> None:
    """The browser decides how a span is drawn.

    A server that returned `<mark>` would be a server deciding what a
    document looks like — and a path for document text to reach innerHTML
    as markup rather than as text.
    """
    import inspect

    from ontologylab.kgstore import KGStore as Store

    source = inspect.getsource(Store.document_review_context)

    assert "<mark" not in source
    assert "span" in source


# --------------------------------------------------------------------------
# The browser side, as far as source can pin it
# --------------------------------------------------------------------------


def _run_mark_spans(text: str, items: list[dict]) -> str:
    """Execute the real `markSpans` from app.js under node.

    Asserting on the source text of a function only pins how it is spelled.
    This is the one piece of browser logic where a plausible-looking rule
    silently loses data, so it is worth running rather than reading.
    """
    import json
    import shutil
    import subprocess
    from pathlib import Path

    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed")

    source = Path("web/app.js").read_text(encoding="utf-8")
    body = source.split("  function markSpans", 1)[1]
    body = "function markSpans" + body.split("\n  function ", 1)[0]

    script = (
        "function escapeHtml(s){return String(s).replace(/[&<>\"']/g,"
        "function(c){return {'&':'&amp;','<':'&lt;','>':'&gt;',"
        "'\"':'&quot;',\"'\":'&#39;'}[c];});}\n"
        + body
        + f"\nconsole.log(JSON.stringify(markSpans({json.dumps(text)},"
        f" {json.dumps(items)})));"
    )
    out = subprocess.run(
        [node, "-e", script], capture_output=True, text=True, check=True
    )
    return json.loads(out.stdout)


def _marked_text_by_item(html: str) -> dict[str, str]:
    """Concatenate, per cited item, the characters its marks actually cover.

    The panel splits overlapping spans into adjacent pieces, so one item's
    highlight is several `<mark>` elements. Judging coverage means gluing
    them back together.
    """
    out: dict[str, str] = {}
    for group, body in re.findall(
        r"<mark[^>]*data-items='([^']*)'[^>]*>(.*?)</mark>", html, re.S
    ):
        for item_id in group.split(" "):
            out[item_id] = out.get(item_id, "") + body
    return out


def test_overlapping_evidence_is_split_rather_than_dropped() -> None:
    """Evidence off the screen cannot be checked.

    Relation spans routinely contain the spans of the concepts they relate,
    and the obvious rule — "when they overlap, draw the first" — silently
    removed about a third of the evidence on a real document. The panel
    splits at span boundaries instead, so every cited item still has a mark
    carrying its id.
    """
    text = "TP53 drives invasion in tumors."
    items = [
        # The relation's span contains both concepts' spans.
        {"id": "rel", "status": "proposed", "span": {"start": 0, "end": 21}},
        {"id": "gene", "status": "proposed", "span": {"start": 0, "end": 4}},
        {"id": "verb", "status": "proposed", "span": {"start": 5, "end": 11}},
    ]

    result = _run_mark_spans(text, items)
    covered = _marked_text_by_item(result["html"])

    assert result["dropped"] == 0
    # Each item's marks must reproduce exactly the characters it cited.
    # Checking only "the id appears somewhere" is what let the first
    # version of this test pass against a rule that highlighted the first
    # four characters of a twenty-one character span.
    for item in items:
        expected = text[item["span"]["start"]:item["span"]["end"]]
        assert covered.get(item["id"]) == expected, (
            f"{item['id']} should cover {expected!r}, "
            f"got {covered.get(item['id'])!r}"
        )
    # And the document itself is unchanged once the markup is stripped.
    assert re.sub(r"<[^>]*>", "", result["html"]) == text


def test_a_degenerate_span_is_reported_rather_than_drawn() -> None:
    """An empty range cannot be highlighted, and pretending otherwise would
    emit a mark around no characters."""
    result = _run_mark_spans(
        "TP53 drives invasion.",
        [{"id": "empty", "status": "proposed", "span": {"start": 4, "end": 4}}],
    )

    assert result["dropped"] == 1
    assert "<mark" not in result["html"]


def test_document_text_is_escaped_everywhere_it_is_drawn() -> None:
    """Document text is untrusted: it comes from whatever the fan-out
    fetched. Every path from `text` into innerHTML goes through escapeHtml.
    """
    import re
    from pathlib import Path

    source = Path("web/app.js").read_text(encoding="utf-8")
    body = source.split("function markSpans", 1)[1].split("\n  function ", 1)[0]

    for match in re.finditer(r"text\.slice\(", body):
        prefix = body[max(0, match.start() - 12):match.start()]
        assert "escapeHtml(" in prefix, (
            f"unescaped text.slice at offset {match.start()} in markSpans"
        )
