"""Ontology term lifecycle and xref review over HTTP.

Every mutation here is one explicit human action against a real store on
disk. The tests drive the app through TestClient — never by calling a route
function, whose defaults are `Query` objects rather than values (CLAUDE.md).
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from ontologylab.kgstore import KGStore
from ontologylab.server.app import create_app

REVIEWER = {"reviewer": "curator-1", "provenance": "curation:web-test"}
XSS = "<img src=x onerror=alert('xss')>"
TERMS = "/api/ontology/terms"


def _client(tmp_path: Path) -> tuple[TestClient, Path]:
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    return TestClient(create_app(data_dir=data_dir)), data_dir / "kg.sqlite"


def _seed_term(db_path: Path, *, label: str = "Leaf blight", **over: Any) -> str:
    store = KGStore.open(db_path)
    try:
        fields: dict[str, Any] = {
            "preferred_label": label, "language": "en",
            "definition": "A plant disease characterized by blighted leaves.",
            "schema_version_id": store.active_schema_version()["id"],
            "reviewer": "curator-0", "provenance": "curation:seed",
        }
        return store.create_ontology_term(**{**fields, **over})
    finally:
        store.close()


def _row(db_path: Path, term_id: str) -> dict[str, Any]:
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        return dict(conn.execute(
            "SELECT * FROM ontology_term WHERE id = ?", (term_id,)
        ).fetchone())


def _xref_body(**over: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "authority": "AGROVOC", "external_id": "c_12345",
        "mapping_predicate": "close", "source_version": "2026-08",
        "source_uri": "https://example.test/agrovoc/c_12345",
        "retrieved_at": 1_786_233_600.0, "confidence": 0.8,
        "license_gate": "identifier-only", "reviewer": REVIEWER["reviewer"],
    }
    return {**body, **over}


def test_schema_route_and_static_app_already_serve_the_settings_screen(
    tmp_path: Path,
) -> None:
    """Given a fresh store, When the schema screen loads, Then it answers."""
    client, _ = _client(tmp_path)

    schema = client.get("/api/schema")

    assert schema.status_code == 200 and schema.json()["active"]["schema_label"]
    assert client.get("/static/app.js").status_code == 200
    assert client.get("/").status_code == 200


def test_term_detail_carries_definition_lifecycle_and_provenance(
    tmp_path: Path,
) -> None:
    """Given a reviewed term, When fetched, Then the audit fields come back."""
    client, db_path = _client(tmp_path)
    term_id = _seed_term(db_path)

    body = client.get(f"{TERMS}/{term_id}").json()

    term = body["term"]
    assert term["id"] == term_id and term["iri"].endswith(f"/term/{term_id}")
    assert (term["preferred_label"], term["language"]) == ("Leaf blight", "en")
    assert term["definition"].startswith("A plant disease")
    assert term["lifecycle"] == "active"
    assert term["replacement_term_id"] is None and term["change_reason"] is None
    assert (term["reviewer"], term["provenance"]) == ("curator-0", "curation:seed")
    assert body["aliases"] == [] and body["xrefs"] == []


def test_term_list_reports_the_vocabulary_and_unknown_ids_are_typed_404(
    tmp_path: Path,
) -> None:
    """Given the bundled ontology, When listed, Then its terms are there."""
    client, db_path = _client(tmp_path)
    term_id = _seed_term(db_path)

    body = client.get(TERMS).json()
    missing = client.get(f"{TERMS}/not-a-term")

    listed = {item["id"]: item for item in body["terms"]}
    assert listed[term_id]["preferred_label"] == "Leaf blight"
    assert body["count"] == len(body["terms"]) >= 7
    assert missing.status_code == 404
    assert missing.json()["detail"]["error_kind"] == "unknown_term"


def test_rename_keeps_identity_and_files_the_former_label(
    tmp_path: Path,
) -> None:
    """Given a term, When renamed, Then same UUID/IRI with a new label."""
    client, db_path = _client(tmp_path)
    term_id = _seed_term(db_path)
    before = _row(db_path, term_id)

    resp = client.post(
        f"{TERMS}/{term_id}/rename",
        json={"preferred_label": "Leaf spot", "language": "en", **REVIEWER},
    )

    assert resp.status_code == 200 and resp.json()["ok"] is True
    after = client.get(f"{TERMS}/{term_id}").json()
    term = after["term"]
    assert (term["id"], term["iri"]) == (term_id, before["iri"])
    assert term["preferred_label"] == "Leaf spot"
    assert term["reviewer"] == REVIEWER["reviewer"]
    assert [(a["label"], a["alias_kind"]) for a in after["aliases"]] == [
        ("Leaf blight", "former-preferred")
    ]


@pytest.mark.parametrize(
    "payload",
    [{"preferred_label": "  ", "language": "en", **REVIEWER},
     {"preferred_label": "Leaf spot", "language": "", **REVIEWER},
     {"preferred_label": "Leaf blight", "language": "en", **REVIEWER},
     {"preferred_label": "Leaf spot", "language": "en"}],
    ids=["blank-label", "blank-language", "unchanged", "no-reviewer"],
)
def test_a_refused_rename_leaves_the_row_untouched(
    tmp_path: Path, payload: dict[str, Any]
) -> None:
    """Given bad input, When renaming, Then 4xx and the DB row is unchanged."""
    client, db_path = _client(tmp_path)
    term_id = _seed_term(db_path)
    before = _row(db_path, term_id)

    resp = client.post(f"{TERMS}/{term_id}/rename", json=payload)

    assert 400 <= resp.status_code < 500
    assert _row(db_path, term_id) == before


def test_replacement_and_deprecation_record_the_link_and_the_reason(
    tmp_path: Path,
) -> None:
    """Given two terms, When retired, Then link and reason are auditable."""
    client, db_path = _client(tmp_path)
    old_id = _seed_term(db_path)
    new_id = _seed_term(db_path, label="Leaf necrosis")

    replaced = client.post(
        f"{TERMS}/{old_id}/lifecycle",
        json={"lifecycle": "replaced", "replacement_term_id": new_id,
              "change_reason": "narrowed to necrotic lesions", **REVIEWER},
    )
    deprecated = client.post(
        f"{TERMS}/{new_id}/lifecycle",
        json={"lifecycle": "deprecated", "change_reason": "superseded",
              **REVIEWER},
    )

    assert (replaced.status_code, deprecated.status_code) == (200, 200)
    old = client.get(f"{TERMS}/{old_id}").json()
    assert old["term"]["lifecycle"] == "replaced"
    assert old["term"]["replacement_term_id"] == new_id
    assert old["term"]["change_reason"] == "narrowed to necrotic lesions"
    assert old["replacement"]["preferred_label"] == "Leaf necrosis"
    new = client.get(f"{TERMS}/{new_id}").json()["term"]
    assert (new["lifecycle"], new["change_reason"]) == ("deprecated", "superseded")
    assert new["replacement_term_id"] is None


@pytest.mark.parametrize(
    ("payload", "field"),
    [({"lifecycle": "replaced", "change_reason": "merged upstream",
       "replacement_term_id": "00000000-0000-4000-8000-000000000000"},
      "replacement_term_id"),
     ({"lifecycle": "replaced", "change_reason": "merged upstream"},
      "replacement_term_id"),
     ({"lifecycle": "deprecated", "change_reason": "   "}, "change_reason")],
    ids=["unknown-replacement", "missing-replacement", "blank-reason"],
)
def test_a_refused_lifecycle_change_names_the_field_and_changes_nothing(
    tmp_path: Path, payload: dict[str, Any], field: str
) -> None:
    """Given a bad replacement, When applied, Then typed 4xx, row unchanged."""
    client, db_path = _client(tmp_path)
    term_id = _seed_term(db_path)
    before = _row(db_path, term_id)

    resp = client.post(f"{TERMS}/{term_id}/lifecycle", json={**payload, **REVIEWER})

    assert resp.status_code == 400
    detail = resp.json()["detail"]
    assert detail["error_kind"] == "ontology_term_invalid"
    assert detail["field"] == field
    assert _row(db_path, term_id) == before


def test_a_repeated_failed_mutation_never_accumulates_state(
    tmp_path: Path,
) -> None:
    """Given repeated refusals, When retried, Then the row is still original."""
    client, db_path = _client(tmp_path)
    term_id = _seed_term(db_path)
    before = _row(db_path, term_id)
    bad = {"lifecycle": "replaced", "change_reason": "x", **REVIEWER}
    made_up = {"lifecycle": "retired", "change_reason": "x", **REVIEWER}

    codes = [
        client.post(f"{TERMS}/{term_id}/lifecycle", json=body).status_code
        for body in (bad, bad, made_up, bad)
    ]

    assert codes == [400, 400, 422, 400]
    assert _row(db_path, term_id) == before
    assert client.get(f"{TERMS}/{term_id}").json()["aliases"] == []


def test_an_alias_is_appended_with_its_reviewer_and_bad_kinds_are_refused(
    tmp_path: Path,
) -> None:
    """Given a term, When an alias is added, Then it is listed with review."""
    client, db_path = _client(tmp_path)
    term_id = _seed_term(db_path)
    alias = {"label": "잎마름병", "language": "ko",
             "alias_kind": "alternative", **REVIEWER}

    added = client.post(f"{TERMS}/{term_id}/aliases", json=alias)
    refused = client.post(
        f"{TERMS}/{term_id}/aliases", json={**alias, "alias_kind": "nickname"}
    )

    assert (added.status_code, refused.status_code) == (200, 422)
    aliases = client.get(f"{TERMS}/{term_id}").json()["aliases"]
    assert [(a["label"], a["language"], a["reviewer"]) for a in aliases] == [
        ("잎마름병", "ko", REVIEWER["reviewer"])
    ]


def test_an_xref_is_retired_by_its_own_term_and_by_no_other(
    tmp_path: Path,
) -> None:
    """Given an xref, When retired, Then the mapping record survives.

    The cross-term attempt is here rather than apart because it is the same
    control reached with someone else's row id — the outcome only means
    something next to the outcome of the legitimate call.
    """
    client, db_path = _client(tmp_path)
    term_id = _seed_term(db_path)
    other = _seed_term(db_path, label="Boscalid")
    xref_id = client.post(
        f"{TERMS}/{term_id}/xrefs", json=_xref_body()
    ).json()["xref_id"]
    review = {"lifecycle": "deprecated", "reviewer": REVIEWER["reviewer"],
              "change_reason": "authority withdrew the concept"}

    stranger = client.post(f"{TERMS}/{other}/xrefs/{xref_id}/review", json=review)
    owner = client.post(f"{TERMS}/{term_id}/xrefs/{xref_id}/review", json=review)

    assert (stranger.status_code, owner.status_code) == (404, 200)
    xrefs = client.get(f"{TERMS}/{term_id}").json()["xrefs"]
    assert len(xrefs) == 1
    assert xrefs[0]["lifecycle"] == "deprecated"
    assert xrefs[0]["mapping_predicate"] == "close"
    assert xrefs[0]["change_reason"] == "authority withdrew the concept"


@pytest.mark.parametrize(
    ("over", "field"),
    [({"license_gate": "public-domain"}, "license_gate"),
     ({"mapping_predicate": "sameAs"}, "mapping_predicate"),
     ({"confidence": 1.5}, "confidence"),
     ({"source_version": None}, "source_version_or_valid_time"),
     ({"source_uri": "  "}, "source_uri")],
    ids=["license", "predicate", "confidence", "no-source-version", "no-uri"],
)
def test_a_refused_xref_names_its_field_and_stores_nothing(
    tmp_path: Path, over: dict[str, Any], field: str
) -> None:
    """Given an invalid xref, When posted, Then typed 4xx and no row."""
    client, db_path = _client(tmp_path)
    term_id = _seed_term(db_path)

    resp = client.post(f"{TERMS}/{term_id}/xrefs", json=_xref_body(**over))

    assert 400 <= resp.status_code < 500
    if resp.status_code == 400:
        detail = resp.json()["detail"]
        assert detail["error_kind"] == "term_xref_invalid"
        assert detail["field"] == field
    assert client.get(f"{TERMS}/{term_id}").json()["xrefs"] == []


def test_markup_in_reviewed_text_is_returned_verbatim_as_json_data(
    tmp_path: Path,
) -> None:
    """Given script-shaped text, When read back, Then it is data, not markup."""
    client, db_path = _client(tmp_path)
    term_id = _seed_term(db_path, definition=XSS)
    client.post(
        f"{TERMS}/{term_id}/aliases",
        json={"label": XSS, "language": "en", "alias_kind": "alternative",
              **REVIEWER},
    )
    client.post(
        f"{TERMS}/{term_id}/xrefs", json=_xref_body(external_id=XSS, authority=XSS)
    )

    resp = client.get(f"{TERMS}/{term_id}")

    body = resp.json()
    assert body["term"]["definition"] == XSS
    assert body["aliases"][0]["label"] == XSS
    assert body["xrefs"][0]["external_id"] == XSS
    assert "text/html" not in resp.headers["content-type"]
