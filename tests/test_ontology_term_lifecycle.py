"""Stable ontology term identity and lifecycle regression tests."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from uuid import UUID, uuid4

import pytest

from ontologylab.kgstore import KGStore, OntologyTermValidationError


def _create_term(store: KGStore, label: str = "Leaf blight") -> str:
    return store.create_ontology_term(
        preferred_label=label,
        language="en",
        definition="A plant disease characterized by blighted leaves.",
        schema_version_id=store.active_schema_version()["id"],
        reviewer="reviewer-1",
        provenance="curation:test-fixture",
    )


def _drop_ontology_tables(db_path: Path) -> None:
    with sqlite3.connect(db_path) as conn:
        conn.execute("DROP TABLE IF EXISTS term_xref")
        conn.execute("DROP TABLE IF EXISTS term_alias")
        conn.execute("DROP TABLE IF EXISTS ontology_term")


def test_old_schema_terms_receive_random_stable_ids_on_migration(
    tmp_path: Path,
) -> None:
    # Given
    db_path = tmp_path / "legacy.sqlite"
    legacy = KGStore.open(db_path)
    expected_count = legacy.conn.execute(
        "SELECT (SELECT COUNT(*) FROM entity_type) + "
        "(SELECT COUNT(*) FROM relation_type)"
    ).fetchone()[0]
    legacy.close()
    _drop_ontology_tables(db_path)

    # When
    migrated = KGStore.open(db_path)
    first = [
        dict(row)
        for row in migrated.conn.execute(
            "SELECT id, iri, legacy_kind, legacy_id FROM ontology_term "
            "ORDER BY legacy_kind, legacy_id"
        )
    ]
    migrated.close()
    reopened = KGStore.open(db_path)
    KGStore._migrate(reopened.conn)
    second = [
        dict(row)
        for row in reopened.conn.execute(
            "SELECT id, iri, legacy_kind, legacy_id FROM ontology_term "
            "ORDER BY legacy_kind, legacy_id"
        )
    ]

    # Then
    assert len(first) == expected_count
    assert first == second
    assert len({row["id"] for row in first}) == expected_count
    assert all(UUID(row["id"]).version == 4 for row in first)
    assert all(row["iri"].endswith(f"/term/{row['id']}") for row in first)
    reopened.close()


def test_created_term_carries_definition_review_and_provenance(tmp_path: Path) -> None:
    # Given
    store = KGStore.open(tmp_path / "kg.sqlite")

    # When
    term_id = _create_term(store)
    term = store.get_ontology_term(term_id)

    # Then
    assert UUID(term["id"]).version == 4
    assert term["iri"].endswith(f"/term/{term['id']}")
    assert term["preferred_label"] == "Leaf blight"
    assert term["language"] == "en"
    assert term["definition"] == (
        "A plant disease characterized by blighted leaves."
    )
    assert term["lifecycle"] == "active"
    assert term["schema_version_id"] == store.active_schema_version()["id"]
    assert term["reviewer"] == "reviewer-1"
    assert term["provenance"] == "curation:test-fixture"
    store.close()


def test_rename_twice_preserves_uuid_and_iri_and_appends_old_labels(
    tmp_path: Path,
) -> None:
    # Given
    store = KGStore.open(tmp_path / "kg.sqlite")
    term_id = _create_term(store)
    original = store.get_ontology_term(term_id)

    # When
    store.rename_ontology_term(
        term_id,
        preferred_label="Foliar blight",
        language="en",
        reviewer="reviewer-2",
        provenance="curation:rename-1",
    )
    store.rename_ontology_term(
        term_id,
        preferred_label="Leaf and foliar blight",
        language="en",
        reviewer="reviewer-3",
        provenance="curation:rename-2",
    )
    renamed = store.get_ontology_term(term_id)
    aliases = store.list_term_aliases(term_id)

    # Then
    assert renamed["id"] == original["id"]
    assert renamed["iri"] == original["iri"]
    assert renamed["preferred_label"] == "Leaf and foliar blight"
    assert [alias["label"] for alias in aliases] == [
        "Leaf blight",
        "Foliar blight",
    ]
    assert all(alias["term_id"] == term_id for alias in aliases)
    store.close()


def test_material_meaning_change_creates_replacement_and_retires_old_term(
    tmp_path: Path,
) -> None:
    # Given
    store = KGStore.open(tmp_path / "kg.sqlite")
    old_id = _create_term(store)
    old_iri = store.get_ontology_term(old_id)["iri"]

    # When
    new_id = store.change_ontology_term_meaning(
        old_id,
        preferred_label="Leaf blight syndrome",
        language="en",
        definition="A syndrome grouping multiple causes of leaf blight.",
        change_reason="The scope changed from one disease to a syndrome.",
        reviewer="reviewer-4",
        provenance="curation:meaning-review",
    )
    old_term = store.get_ontology_term(old_id)
    new_term = store.get_ontology_term(new_id)

    # Then
    assert new_id != old_id
    assert new_term["iri"] != old_iri
    assert new_term["lifecycle"] == "active"
    assert old_term["lifecycle"] == "replaced"
    assert old_term["replacement_term_id"] == new_id
    assert old_term["change_reason"] == (
        "The scope changed from one disease to a syndrome."
    )
    assert old_term["iri"] == old_iri

    with pytest.raises(OntologyTermValidationError) as rename_error:
        store.rename_ontology_term(
            old_id,
            preferred_label="Retired leaf blight",
            language="en",
            reviewer="reviewer-5",
            provenance="curation:invalid-rename",
        )
    assert rename_error.value.field == "lifecycle"

    for lifecycle in ("active", "deprecated", "replaced"):
        with pytest.raises(OntologyTermValidationError) as lifecycle_error:
            store.set_ontology_term_lifecycle(
                old_id,
                lifecycle=lifecycle,
                replacement_term_id=new_id,
                change_reason="Attempted terminal-state mutation.",
                reviewer="reviewer-5",
                provenance="curation:invalid-lifecycle",
            )
        assert lifecycle_error.value.field == "lifecycle"

    with pytest.raises(OntologyTermValidationError) as meaning_error:
        store.change_ontology_term_meaning(
            old_id,
            preferred_label="Another meaning",
            language="en",
            definition="A second attempted replacement.",
            change_reason="Attempted terminal-state mutation.",
            reviewer="reviewer-5",
            provenance="curation:invalid-meaning",
        )
    assert meaning_error.value.field == "lifecycle"
    assert store.get_ontology_term(old_id) == old_term
    store.close()


@pytest.mark.parametrize("lifecycle", ["", "retired", "close"])
def test_invalid_term_lifecycle_is_a_typed_domain_error(
    tmp_path: Path,
    lifecycle: str,
) -> None:
    # Given
    store = KGStore.open(tmp_path / "kg.sqlite")
    term_id = _create_term(store)

    # When
    with pytest.raises(OntologyTermValidationError) as caught:
        store.set_ontology_term_lifecycle(
            term_id,
            lifecycle=lifecycle,
            change_reason="invalid transition probe",
            reviewer="reviewer-2",
            provenance="curation:invalid-transition",
        )

    # Then
    assert caught.value.field == "lifecycle"
    assert store.get_ontology_term(term_id)["lifecycle"] == "active"
    store.close()


def test_nonexistent_replacement_term_is_rejected_without_mutation(
    tmp_path: Path,
) -> None:
    # Given
    store = KGStore.open(tmp_path / "kg.sqlite")
    term_id = _create_term(store)

    # When
    with pytest.raises(OntologyTermValidationError) as caught:
        store.set_ontology_term_lifecycle(
            term_id,
            lifecycle="replaced",
            replacement_term_id=str(uuid4()),
            change_reason="invalid replacement probe",
            reviewer="reviewer-2",
            provenance="curation:invalid-replacement",
        )

    # Then
    assert caught.value.field == "replacement_term_id"
    assert store.get_ontology_term(term_id)["lifecycle"] == "active"
    store.close()


def test_failed_migration_leaves_no_partial_ontology_table_set(
    tmp_path: Path,
) -> None:
    # Given
    db_path = tmp_path / "legacy.sqlite"
    KGStore.open(db_path).close()
    _drop_ontology_tables(db_path)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    def deny_alias_table(
        action: int,
        table: str | None,
        _column: str | None,
        _database: str | None,
        _trigger: str | None,
    ) -> int:
        if action == sqlite3.SQLITE_CREATE_TABLE and table == "term_alias":
            return sqlite3.SQLITE_DENY
        return sqlite3.SQLITE_OK

    conn.set_authorizer(deny_alias_table)

    # When
    with pytest.raises(sqlite3.DatabaseError):
        KGStore._migrate(conn)
    conn.set_authorizer(None)
    tables = {
        row[0]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        )
    }

    # Then
    assert not {"ontology_term", "term_alias", "term_xref"} & tables
    conn.close()
