"""The ontology is the largest lever on what reaches the review queue.

The extractor is told what to look for, so the vocabulary it is given
decides what comes back. Everything in the store was built for this to be
changeable — `nodes`, `edges` and both type tables carry
`schema_version_id` — but nothing could write one, so every corpus ran on
`software-docs-v1`, "a neutral default ontology for software / technical
documentation", including a corpus of p53 papers.

Measured on one abstract before this existed: five relations, every one of
them `related_to`, and 24 proposals the schema had no shape to hold, all
rejected. The same abstract under a biomedical ontology: twelve relations
across five types, nothing rejected, and entities typed as Gene, Protein,
Variant and Disease instead of `Concept` seven times.

What is pinned here is that switching is additive. A review queue somebody
is halfway through must keep meaning what it meant.
"""

from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient

from ontologylab.kgstore import KGStore, KGStoreError, UnknownItem
from ontologylab.models import ProposedEntity, SourceSpan
from ontologylab.schemas import PRESETS, preset
from ontologylab.server import routes
from ontologylab.server.app import create_app


def _store(tmp_path) -> KGStore:
    return KGStore.open(tmp_path / "kg.sqlite")


# --------------------------------------------------------------------------
# Installing one
# --------------------------------------------------------------------------


def test_a_fresh_store_starts_on_the_software_default(tmp_path) -> None:
    """Not a criticism of the default — it has to be something. The point
    is that it is now visible and replaceable."""
    store = _store(tmp_path)

    assert store.get_schema()["schema_label"] == "software-docs-v1"
    store.close()


def test_installing_a_preset_changes_what_the_extractor_is_told(
    tmp_path,
) -> None:
    store = _store(tmp_path)

    store.install_schema(**preset("biomedical"))
    schema = store.get_schema()

    names = {e["name"] for e in schema["entity_types"]}
    assert {"Gene", "Protein", "Variant", "Disease"} <= names
    relations = {r["name"] for r in schema["relation_types"]}
    assert {"encodes", "has_variant", "inhibits"} <= relations
    store.close()


def test_the_biomedical_preset_keeps_an_honest_vague_relation() -> None:
    """`associated_with` is deliberate, not an oversight.

    Papers report associations without a mechanism. Removing the honest
    word for that pushes the model toward claiming `causes`, and a
    confident wrong relation is worse than a vague right one.
    """
    relations = {r["name"] for r in PRESETS["biomedical"]["relation_types"]}

    assert "associated_with" in relations
    assert "causes" in relations, "and the specific one is still available"


# --------------------------------------------------------------------------
# Switching is additive
# --------------------------------------------------------------------------


def test_proposals_keep_pointing_at_the_ontology_they_were_judged_against(
    tmp_path,
) -> None:
    """The property that makes switching safe mid-review.

    Re-typing a queue somebody is halfway through would change what their
    earlier decisions meant — a node approved as a `Concept` does not
    become an approved `Gene` because the vocabulary moved on.
    """
    store = _store(tmp_path)
    doc, _ = store.insert_document(
        source_kind="paper_api", source_uri="u://a", title="t",
        raw_text="TP53 is a tumor suppressor.", content_hash="h",
    )
    store.insert_proposed(
        [ProposedEntity(id="e1", entity_type="Concept", name="TP53",
                        confidence=0.9, source_span=SourceSpan(0, 4))],
        [], source_doc_id=doc.id, extractor_engine="mock",
        extractor_model=None, prompt_version="v1",
    )
    before = store.active_schema_version()["id"]

    store.install_schema(**preset("biomedical"))

    row = store.conn.execute(
        "SELECT schema_version_id FROM nodes WHERE name = 'TP53'"
    ).fetchone()
    assert row["schema_version_id"] == before, "the proposal was re-typed"
    assert store.active_schema_version()["id"] != before
    store.close()


def test_an_earlier_ontology_can_be_switched_back_to(tmp_path) -> None:
    store = _store(tmp_path)
    original = store.active_schema_version()["id"]
    store.install_schema(**preset("biomedical"))

    store.activate_schema(original)

    assert store.get_schema()["schema_label"] == "software-docs-v1"
    store.close()


def test_the_list_says_which_ontology_carries_decisions(tmp_path) -> None:
    """Switching away from one with items behind it is the consequential
    case, so the count is what the screen needs to show."""
    store = _store(tmp_path)
    doc, _ = store.insert_document(
        source_kind="paper_api", source_uri="u://a", title="t",
        raw_text="TP53 here.", content_hash="h",
    )
    store.insert_proposed(
        [ProposedEntity(id="e1", entity_type="Concept", name="TP53",
                        confidence=0.9, source_span=SourceSpan(0, 4))],
        [], source_doc_id=doc.id, extractor_engine="mock",
        extractor_model=None, prompt_version="v1",
    )
    store.install_schema(**preset("biomedical"))

    listed = {s["label"]: s for s in store.list_schemas()}

    assert listed["software-docs-v1"]["items"] == 1
    assert listed["biomed-v1"]["items"] == 0
    assert listed["biomed-v1"]["active"] is True
    store.close()


# --------------------------------------------------------------------------
# A schema that could not work is refused
# --------------------------------------------------------------------------


def test_a_relation_naming_an_absent_type_is_refused(tmp_path) -> None:
    """Otherwise the extractor is handed a rule nothing can satisfy, and
    every use of that relation is rejected after the model has done the
    work — an expensive way to learn about a typo."""
    store = _store(tmp_path)

    with pytest.raises(KGStoreError, match="not an entity type"):
        store.install_schema(
            label="x", description="",
            entity_types=[{"name": "Gene"}],
            relation_types=[{"name": "r", "domain_type": "Protein",
                             "range_type": "*"}],
        )
    store.close()


@pytest.mark.parametrize(
    "kwargs, why",
    [
        ({"label": "x", "entity_types": []}, "nothing to extract"),
        ({"label": "   ", "entity_types": [{"name": "A"}]}, "unnameable"),
    ],
)
def test_an_unusable_schema_is_refused(tmp_path, kwargs, why) -> None:
    store = _store(tmp_path)

    with pytest.raises(KGStoreError):
        store.install_schema(description="", relation_types=[], **kwargs)
    store.close()


def test_an_unknown_schema_cannot_be_activated(tmp_path) -> None:
    store = _store(tmp_path)

    with pytest.raises(UnknownItem):
        store.activate_schema(9999)
    store.close()


# --------------------------------------------------------------------------
# Through the endpoint
# --------------------------------------------------------------------------


@pytest.fixture()
def client(tmp_path):
    os.environ.setdefault("ONTOLOGYLAB_ALLOWED_HOSTS", "testserver")
    data_dir = tmp_path / "data"
    routes.attach_data_dir(data_dir)
    return TestClient(create_app(data_dir=data_dir, packs_dir=tmp_path / "packs"))


def test_the_screen_can_see_what_is_active_and_what_is_available(
    client,
) -> None:
    body = client.get("/api/schema").json()

    assert body["active"]["schema_label"] == "software-docs-v1"
    assert {p["name"] for p in body["presets"]} == set(PRESETS)
    assert body["installed"][0]["active"] is True


def test_a_preset_installs_and_becomes_active(client) -> None:
    body = client.post("/api/schema", json={"preset": "biomedical"}).json()

    assert body["ok"] is True
    assert body["active"]["schema_label"] == "biomed-v1"
    assert client.get("/api/schema").json()["active"]["schema_label"] == (
        "biomed-v1"
    )


def test_a_hand_written_ontology_installs(client) -> None:
    """The presets are a starting point, not a standard — an ontology that
    fits a literature is a research artifact this repo cannot guess."""
    body = client.post("/api/schema", json={
        "label": "legal-v1",
        "description": "Cases and statutes.",
        "entity_types": [{"name": "Case"}, {"name": "Statute"}],
        "relation_types": [
            {"name": "cites", "domain_type": "Case", "range_type": "*"}
        ],
    }).json()

    assert body["active"]["schema_label"] == "legal-v1"
    assert len(body["active"]["entity_types"]) == 2


@pytest.mark.parametrize(
    "payload, status",
    [
        ({"preset": "nope"}, 400),
        ({}, 400),
        ({"label": "x", "entity_types": [{"name": "A"}],
          "relation_types": [{"name": "r", "domain_type": "Ghost"}]}, 400),
    ],
)
def test_a_request_that_could_not_work_is_refused(client, payload, status) -> None:
    assert client.post("/api/schema", json=payload).status_code == status


def test_activating_an_unknown_schema_is_a_404(client) -> None:
    assert client.post("/api/schema/9999/activate").status_code == 404


# --------------------------------------------------------------------------
# The screen
# --------------------------------------------------------------------------


def test_the_settings_screen_can_change_the_ontology() -> None:
    """The store was built for this and nothing could reach it.

    An API with no caller is the state `/api/jobs/{id}/asked` shipped in
    earlier this session, so the wiring is checked rather than assumed.
    """
    from pathlib import Path

    markup = Path("web/index.html").read_text(encoding="utf-8")
    script = Path("web/app.js").read_text(encoding="utf-8")

    assert 'id="schema-active"' in markup
    assert 'id="schema-presets"' in markup
    assert "/api/schema" in script, "no caller for the endpoint"
    assert "data-schema-preset" in script
    assert "data-schema-activate" in script, "no way back to an earlier one"


def test_the_screen_says_switching_does_not_re_type_the_queue() -> None:
    """The property that makes this safe mid-review is invisible unless
    stated: someone with 1,406 pending proposals needs to know they are not
    about to be re-interpreted."""
    from pathlib import Path

    markup = Path("web/index.html").read_text(encoding="utf-8")
    panel = markup.split('id="schema-active"', 1)[1].split("</div>", 3)[-1]

    assert "이미 쌓인 제안은 그대로" in markup
    assert "새로 추출하는 것부터" in markup


# --------------------------------------------------------------------------
# The offline engine has to work under any ontology
# --------------------------------------------------------------------------


def test_the_mock_engine_emits_types_the_active_schema_defines() -> None:
    """It hardcoded `Component`, a type only software-docs defines.

    Found by installing biomed-v1 and running a real 23-document research
    job: it finished `complete`, with no error, and zero proposals. The
    provenance said why — `entity[0] 'Glu255Lys': unknown entity_type
    'Component'; rejected` — but nothing on screen did. An offline engine
    that silently produces nothing under every ontology but one is worse
    than an engine that fails, because the failure looks like an empty
    corpus.
    """
    from ontologylab.extractor import (
        Chunk, build_extraction_prompt, parse_and_validate_extraction,
    )
    from ontologylab.engines import MockEngine
    import asyncio

    text = "The RateLimiter uses TokenBucketAlgorithm internally."
    for name in ("software-docs", "biomedical"):
        p = preset(name)
        schema = {
            "schema_label": p["label"],
            "entity_types": p["entity_types"],
            "relation_types": p["relation_types"],
        }
        raw, _ = asyncio.run(
            MockEngine().generate(build_extraction_prompt(schema, text))
        )
        result = parse_and_validate_extraction(
            raw, schema, Chunk(index=0, char_offset=0, text=text)
        )

        assert result.entities, f"{name}: nothing survived validation"
        assert not result.warnings, f"{name}: {result.warnings}"
        allowed = {e["name"] for e in p["entity_types"]}
        assert {e.entity_type for e in result.entities} <= allowed


def test_the_mock_relations_use_endpoints_the_schema_accepts() -> None:
    """The first fix changed the entity type and left the relation
    endpoints as `Component`, so entities passed and every relation was
    still rejected — a half-fix that looked like a whole one."""
    from ontologylab.extractor import (
        Chunk, build_extraction_prompt, parse_and_validate_extraction,
    )
    from ontologylab.engines import MockEngine
    import asyncio

    text = "The RateLimiter uses TokenBucketAlgorithm internally."
    p = preset("biomedical")
    schema = {
        "schema_label": p["label"],
        "entity_types": p["entity_types"],
        "relation_types": p["relation_types"],
    }
    raw, _ = asyncio.run(
        MockEngine().generate(build_extraction_prompt(schema, text))
    )
    result = parse_and_validate_extraction(
        raw, schema, Chunk(index=0, char_offset=0, text=text)
    )

    assert result.relations, "no relation survived"
    assert not result.warnings
