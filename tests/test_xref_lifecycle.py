"""Typed external cross-reference lifecycle regression tests."""

from __future__ import annotations

from pathlib import Path
from typing import TypedDict
from uuid import uuid4

import pytest

from ontologylab.kgstore import KGStore, XrefValidationError


class XrefFields(TypedDict, total=False):
    authority: str
    external_id: str
    mapping_predicate: str
    source_uri: str
    source_version: str | None
    valid_from: float
    valid_to: float
    retrieved_at: float
    confidence: float
    reviewer: str
    license_gate: str
    lifecycle: str
    replacement_xref_id: str
    change_reason: str


def _create_term(store: KGStore) -> str:
    return store.create_ontology_term(
        preferred_label="Boscalid",
        language="en",
        definition="A fungicidal active ingredient.",
        schema_version_id=store.active_schema_version()["id"],
        reviewer="reviewer-1",
        provenance="curation:test-fixture",
    )


def _xref_fields() -> XrefFields:
    return {
        "authority": "AGROVOC",
        "external_id": "c_12345",
        "mapping_predicate": "close",
        "source_uri": "https://example.test/agrovoc/c_12345",
        "source_version": "2026-08",
        "retrieved_at": 1_786_233_600.0,
        "confidence": 0.8,
        "reviewer": "reviewer-2",
        "license_gate": "identifier-only",
    }


def test_close_mapping_is_data_and_cannot_merge_or_mutate_term_identity(
    tmp_path: Path,
) -> None:
    # Given
    store = KGStore.open(tmp_path / "kg.sqlite")
    term_id = _create_term(store)
    before = dict(
        store.conn.execute(
            "SELECT id, iri, preferred_label, lifecycle FROM ontology_term "
            "WHERE id = ?",
            (term_id,),
        ).fetchone()
    )
    term_count = store.conn.execute(
        "SELECT COUNT(*) FROM ontology_term"
    ).fetchone()[0]

    # When
    xref_id = store.add_term_xref(term_id=term_id, **_xref_fields())

    # Then
    after = dict(
        store.conn.execute(
            "SELECT id, iri, preferred_label, lifecycle FROM ontology_term "
            "WHERE id = ?",
            (term_id,),
        ).fetchone()
    )
    xref = store.get_term_xref(xref_id)
    assert after == before
    assert store.conn.execute(
        "SELECT COUNT(*) FROM ontology_term"
    ).fetchone()[0] == term_count
    assert xref["term_id"] == term_id
    assert xref["mapping_predicate"] == "close"
    assert store.conn.execute(
        "SELECT COUNT(*) FROM term_xref"
    ).fetchone()[0] == 1
    store.close()


@pytest.mark.parametrize(
    "field",
    [
        "authority",
        "external_id",
        "mapping_predicate",
        "source_uri",
        "retrieved_at",
        "confidence",
        "reviewer",
        "license_gate",
    ],
)
def test_missing_xref_contract_field_is_a_typed_error_without_insert(
    tmp_path: Path,
    field: str,
) -> None:
    # Given
    store = KGStore.open(tmp_path / "kg.sqlite")
    term_id = _create_term(store)
    fields = _xref_fields()
    fields.pop(field)

    # When
    with pytest.raises(XrefValidationError) as caught:
        store.add_term_xref(term_id=term_id, **fields)

    # Then
    assert caught.value.field == field
    assert store.conn.execute(
        "SELECT COUNT(*) FROM term_xref"
    ).fetchone()[0] == 0
    store.close()


def test_xref_requires_source_version_or_valid_time(tmp_path: Path) -> None:
    # Given
    store = KGStore.open(tmp_path / "kg.sqlite")
    term_id = _create_term(store)
    fields = _xref_fields()
    fields.pop("source_version")

    # When
    with pytest.raises(XrefValidationError) as caught:
        store.add_term_xref(term_id=term_id, **fields)

    # Then
    assert caught.value.field == "source_version_or_valid_time"
    assert store.conn.execute(
        "SELECT COUNT(*) FROM term_xref"
    ).fetchone()[0] == 0
    store.close()


def test_valid_time_can_supply_xref_version_context(tmp_path: Path) -> None:
    # Given
    store = KGStore.open(tmp_path / "kg.sqlite")
    term_id = _create_term(store)
    fields = _xref_fields()
    fields["source_version"] = None
    fields["valid_from"] = 1_700_000_000.0
    fields["valid_to"] = 1_800_000_000.0

    # When
    xref_id = store.add_term_xref(term_id=term_id, **fields)

    # Then
    xref = store.get_term_xref(xref_id)
    assert xref["source_version"] is None
    assert xref["valid_from"] == 1_700_000_000.0
    assert xref["valid_to"] == 1_800_000_000.0
    store.close()


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("mapping_predicate", "closeMatch"),
        ("mapping_predicate", "equivalent"),
        ("license_gate", "permit"),
        ("license_gate", "deny"),
        ("lifecycle", "retired"),
    ],
)
def test_invalid_xref_enum_is_rejected_without_insert(
    tmp_path: Path,
    field: str,
    value: str,
) -> None:
    # Given
    store = KGStore.open(tmp_path / "kg.sqlite")
    term_id = _create_term(store)
    fields = _xref_fields()
    fields[field] = value

    # When
    with pytest.raises(XrefValidationError) as caught:
        store.add_term_xref(term_id=term_id, **fields)

    # Then
    assert caught.value.field == field
    assert store.conn.execute(
        "SELECT COUNT(*) FROM term_xref"
    ).fetchone()[0] == 0
    store.close()


def test_bogus_xref_replacement_is_rejected_without_insert(tmp_path: Path) -> None:
    # Given
    store = KGStore.open(tmp_path / "kg.sqlite")
    term_id = _create_term(store)
    fields = _xref_fields()
    fields.update(
        {
            "lifecycle": "replaced",
            "replacement_xref_id": str(uuid4()),
            "change_reason": "External record was superseded.",
        }
    )

    # When
    with pytest.raises(XrefValidationError) as caught:
        store.add_term_xref(term_id=term_id, **fields)

    # Then
    assert caught.value.field == "replacement_xref_id"
    assert store.conn.execute(
        "SELECT COUNT(*) FROM term_xref"
    ).fetchone()[0] == 0
    store.close()


def test_replaced_xref_is_terminal_and_replacement_stays_on_same_term(
    tmp_path: Path,
) -> None:
    # Given
    store = KGStore.open(tmp_path / "kg.sqlite")
    term_id = _create_term(store)
    old_fields = _xref_fields()
    old_fields["external_id"] = "old"
    old_id = store.add_term_xref(term_id=term_id, **old_fields)
    replacement_fields = _xref_fields()
    replacement_fields["external_id"] = "replacement"
    replacement_id = store.add_term_xref(
        term_id=term_id, **replacement_fields
    )
    store.set_term_xref_lifecycle(
        old_id,
        lifecycle="replaced",
        replacement_xref_id=replacement_id,
        change_reason="Authority superseded the record.",
        reviewer="reviewer-3",
    )

    other_term_id = store.create_ontology_term(
        preferred_label="Fluopyram",
        language="en",
        definition="A different fungicidal active ingredient.",
        schema_version_id=store.active_schema_version()["id"],
        reviewer="reviewer-1",
        provenance="curation:test-fixture",
    )
    other_fields = _xref_fields()
    other_fields["external_id"] = "other-term"
    other_xref_id = store.add_term_xref(
        term_id=other_term_id, **other_fields
    )

    # When / Then
    with pytest.raises(XrefValidationError) as terminal_error:
        store.set_term_xref_lifecycle(
            old_id,
            lifecycle="active",
            change_reason="Attempted reactivation.",
            reviewer="reviewer-4",
        )
    assert terminal_error.value.field == "lifecycle"
    assert store.get_term_xref(old_id)["lifecycle"] == "replaced"

    with pytest.raises(XrefValidationError) as cross_term_error:
        store.set_term_xref_lifecycle(
            replacement_id,
            lifecycle="replaced",
            replacement_xref_id=other_xref_id,
            change_reason="Invalid cross-term replacement.",
            reviewer="reviewer-4",
        )
    assert cross_term_error.value.field == "replacement_xref_id"
    assert store.get_term_xref(replacement_id)["lifecycle"] == "active"
    store.close()
