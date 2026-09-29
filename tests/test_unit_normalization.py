"""Measured values gain a comparable, platform-owned measurement block."""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest

from ontologylab.extractor import run_extraction
from ontologylab.kgstore import KGStore
from ontologylab.provenance import Provenance
from ontologylab.safety import Caps
from ontologylab.schemas import preset
from ontologylab.unit_normalization import comparable, measurement, normalize_measurement
from tests.factories import make_entity


def test_rates_in_different_units_normalize_to_one_value() -> None:
    grams = measurement("250", "g a.i./ha")
    kilos = measurement("0.25", "kg a.i./ha")
    assert grams["status"] == kilos["status"] == "normalized"
    assert grams["unit"] == kilos["unit"] == "kg/ha"
    assert grams["value"] == pytest.approx(kilos["value"])
    assert grams["basis"] == "a.i."
    assert comparable(grams, kilos)


def test_raw_text_is_preserved_verbatim() -> None:
    block = measurement("0.03", "mg/L")
    assert block["raw"] == "0.03 mg/L"
    assert block["value"] == pytest.approx(0.03)


@pytest.mark.parametrize(
    ("value", "unit", "status"),
    [("85", None, "no_unit"), ("12", "furlongs", "unknown_unit"), ("about half", "%", "unparsed")],
)
def test_unresolvable_inputs_are_flagged_not_guessed(value, unit, status) -> None:
    block = measurement(value, unit)
    assert block["status"] == status
    assert block["unit"] is None


def test_cross_dimension_and_cross_basis_are_not_comparable() -> None:
    rate = measurement("250", "g/ha")
    assert not comparable(rate, measurement("250", "mg/L"))
    assert not comparable(rate, measurement("250", "g a.i./ha"))
    assert not comparable(measurement("12", "furlongs"), measurement("12", "furlongs"))


def test_proposal_keeps_model_strings_and_gains_block() -> None:
    entity = make_entity("250 g/ha", "Component", properties={"value": "250", "unit": "g/ha"})
    normalize_measurement(entity)
    assert entity.properties["value"] == "250"
    assert entity.properties["unit"] == "g/ha"
    assert entity.properties["measurement"]["value"] == pytest.approx(0.25)


def test_proposal_without_value_gets_no_block() -> None:
    entity = make_entity("ApiGateway")
    normalize_measurement(entity)
    assert "measurement" not in entity.properties


def test_measurement_block_is_storable_on_any_schema(store, doc) -> None:
    from tests.conftest import insert

    entity = make_entity("RateLimiter")
    entity.properties["measurement"] = measurement("250", "g/ha")
    insert(store, doc, [entity])
    stored = store.graph_query(include_proposed=True)["nodes"][0]["properties"]
    assert stored["measurement"]["unit"] == "kg/ha"


class _DoseEngine:
    async def generate(self, prompt: str, *, model: str | None = None):
        entity = {
            "name": "250 g a.i./ha", "entity_type": "DoseRate", "aliases": [],
            "properties": {"value": "250", "unit": "g a.i./ha",
                           "measurement": {"value": 999}},
            "confidence": 0.9, "source_span": {"start": 0, "end": 13},
        }
        payload = {"entities": [entity], "relations": []}
        return "```json\n" + json.dumps(payload) + "\n```", {"calls": 1, "elapsed": 0.0}


def test_extraction_stores_platform_measurement_not_model_one(tmp_path) -> None:
    store = KGStore.open(tmp_path / "kg.sqlite")
    schema = preset("agrochem")
    store.install_schema(
        label=schema["label"], description=schema["description"],
        entity_types=schema["entity_types"], relation_types=schema["relation_types"],
    )
    doc, _ = store.insert_document(
        source_kind="upload", source_uri="file:///dose.txt", title="dose",
        raw_text="250 g a.i./ha applied at BBCH 65", content_hash="sha256:dose",
    )
    caps = Caps(SimpleNamespace(iterations=0, time_budget_s=0, max_engine_calls=0))
    try:
        asyncio.run(run_extraction(
            store, _DoseEngine(), Provenance(str(tmp_path / "job"), seed=0), caps,
            [doc.id], extractor_engine="test", extractor_model=None,
            on_progress=lambda _m: None, on_stats=lambda _s: None,
        ))
        props = json.loads(store.conn.execute(
            "SELECT properties_json FROM nodes WHERE entity_type='DoseRate'"
        ).fetchone()[0])
    finally:
        store.close()
    assert props["value"] == "250"
    assert props["measurement"]["status"] == "normalized"
    assert props["measurement"]["value"] == pytest.approx(0.25)
    assert props["measurement"]["basis"] == "a.i."
