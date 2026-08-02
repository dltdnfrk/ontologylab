"""EPPO normalization between extraction and human review.

The fixtures are tiny imported caches, never network lookups. The model may
suggest an identifier, but only the local registry is authoritative.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from pathlib import Path
from types import SimpleNamespace

from ontologylab.extractor import run_extraction
from ontologylab.kgstore import KGStore
from ontologylab.models import ProposedEntity
from ontologylab.normalization import normalize_proposal
from ontologylab.provenance import Provenance
from ontologylab.registry import RegistryCache, import_eppo
from ontologylab.safety import Caps
from ontologylab.schemas import preset


def _cache(tmp_path: Path) -> RegistryCache:
    source = tmp_path / "eppo.csv"
    source.write_text(
        "code,name,type\n"
        "BOTRCI,Botrytis cinerea,scientific\n"
        "BOTRCI,Botryotinia fuckeliana,synonym\n"
        "SOLTU,Solanum tuberosum,scientific\n",
        encoding="utf-8",
    )
    import_eppo(source, tmp_path / "data")
    return RegistryCache(tmp_path / "data")


def _entity(
    name: str,
    entity_type: str = "Pathogen",
    *,
    aliases: list[str] | None = None,
    properties: dict | None = None,
) -> ProposedEntity:
    return ProposedEntity(
        id=uuid.uuid4().hex,
        entity_type=entity_type,
        name=name,
        aliases=list(aliases or []),
        properties=dict(properties or {}),
    )


def _install_agrochem(store: KGStore) -> None:
    schema = preset("agrochem")
    store.install_schema(
        label=schema["label"],
        description=schema["description"],
        entity_types=schema["entity_types"],
        relation_types=schema["relation_types"],
    )


def test_name_then_aliases_resolve_on_the_first_registry_match(tmp_path) -> None:
    cache = _cache(tmp_path)
    via_name = _entity(
        "Botrytis cinerea",
        aliases=["Botryotinia fuckeliana"],
        properties={"eppo_code": "BOTRCI"},
    )
    via_alias = _entity(
        "grey mould pathogen",
        aliases=["Botryotinia fuckeliana", "Botrytis cinerea"],
    )

    assert normalize_proposal(via_name, cache) is via_name
    normalize_proposal(via_alias, cache)

    assert via_name.properties == {
        "eppo_code": "BOTRCI",
        "eppo_matched_surface": "Botrytis cinerea",
    }
    assert via_alias.properties == {
        "eppo_code": "BOTRCI",
        "eppo_matched_surface": "Botryotinia fuckeliana",
    }


def test_cache_outvotes_a_wrong_model_code_and_records_what_was_dropped(
    tmp_path,
) -> None:
    proposal = _entity(
        "Botrytis cinerea",
        properties={"eppo_code": "WRONG", "group": "fungus"},
    )

    normalize_proposal(proposal, _cache(tmp_path))

    assert proposal.properties == {
        "group": "fungus",
        "eppo_code": "BOTRCI",
        "eppo_matched_surface": "Botrytis cinerea",
        "eppo_code_dropped": "WRONG",
    }


def test_unresolved_organism_is_kept_flagged_and_model_code_is_dropped(
    tmp_path,
) -> None:
    proposal = _entity(
        "Imaginary blight organism",
        properties={"eppo_code": "HALLUCINATED"},
    )

    normalize_proposal(proposal, _cache(tmp_path))

    assert proposal.name == "Imaginary blight organism"
    assert proposal.properties == {
        "eppo_code_dropped": "HALLUCINATED",
        "normalization": "no_eppo_match",
    }


def test_absent_cache_disables_codes_without_per_item_exception_flags(tmp_path) -> None:
    proposal = _entity(
        "Botrytis cinerea",
        properties={"eppo_code": "MODEL-CODE", "group": "fungus"},
    )

    normalize_proposal(proposal, RegistryCache(tmp_path / "missing"))

    assert proposal.properties == {"group": "fungus"}


def test_non_organism_passes_through_byte_for_byte(tmp_path) -> None:
    proposal = _entity(
        "boscalid",
        entity_type="ActiveIngredient",
        aliases=["BOS"],
        properties={"eppo_code": "MODEL-VALUE", "cas_number": "188425-85-6"},
    )
    before = (
        proposal.id,
        proposal.entity_type,
        proposal.name,
        list(proposal.aliases),
        dict(proposal.properties),
    )

    assert normalize_proposal(proposal, RegistryCache(tmp_path / "missing")) is proposal
    assert (
        proposal.id,
        proposal.entity_type,
        proposal.name,
        proposal.aliases,
        proposal.properties,
    ) == before


class _ExtractionEngine:
    async def generate(self, prompt: str, *, model: str | None = None):
        entities = [
            {
                "name": "grey mould pathogen",
                "entity_type": "Pathogen",
                "aliases": ["Botryotinia fuckeliana"],
                "properties": {"eppo_code": "WRONG"},
                "confidence": 0.9,
                "source_span": {"start": 0, "end": 20},
            },
            {
                "name": "mystery weed",
                "entity_type": "Weed",
                "aliases": [],
                "properties": {},
                "confidence": 0.7,
                "source_span": {"start": 25, "end": 37},
            },
        ]
        return (
            "```json\n" + json.dumps({"entities": entities, "relations": []}) + "\n```",
            {"calls": 1, "elapsed": 0.0},
        )


def _extract(store: KGStore, data_dir: Path, provenance: Provenance) -> None:
    caps = Caps(SimpleNamespace(iterations=0, time_budget_s=0, max_engine_calls=0))
    doc_id = store.list_documents()[0].id
    asyncio.run(
        run_extraction(
            store,
            _ExtractionEngine(),
            provenance,
            caps,
            [doc_id],
            extractor_engine="test",
            extractor_model=None,
            on_progress=lambda _message: None,
            on_stats=lambda _stats: None,
        )
    )


def _pipeline_store(data_dir: Path) -> KGStore:
    store = KGStore.open(data_dir / "kg.sqlite")
    _install_agrochem(store)
    text = "grey mould pathogen and mystery weed"
    store.insert_document(
        source_kind="upload",
        source_uri="file:///crop.txt",
        title="crop",
        raw_text=text,
        content_hash="sha256:normalization-pipeline",
    )
    return store


def test_extraction_normalizes_before_storage_and_review_exposes_properties(
    tmp_path,
) -> None:
    data_dir = tmp_path / "data"
    source = tmp_path / "eppo.csv"
    source.write_text(
        "code,name,type\nBOTRCI,Botryotinia fuckeliana,synonym\n",
        encoding="utf-8",
    )
    import_eppo(source, data_dir)
    store = _pipeline_store(data_dir)
    try:
        _extract(store, data_dir, Provenance(str(tmp_path / "job"), seed=0))
        rows = {row["label"]: row for row in store.pending_review(kind="node")}
    finally:
        store.close()

    assert rows["grey mould pathogen"]["properties"] == {
        "eppo_code": "BOTRCI",
        "eppo_matched_surface": "Botryotinia fuckeliana",
        "eppo_code_dropped": "WRONG",
    }
    assert rows["mystery weed"]["properties"] == {
        "normalization": "no_eppo_match"
    }


def test_absent_cache_logs_one_run_warning_not_one_per_organism(tmp_path) -> None:
    data_dir = tmp_path / "data"
    store = _pipeline_store(data_dir)
    provenance = Provenance(str(tmp_path / "job"), seed=0)
    try:
        _extract(store, data_dir, provenance)
        properties = [
            json.loads(row[0])
            for row in store.conn.execute("SELECT properties_json FROM nodes")
        ]
    finally:
        store.close()

    entries = [json.loads(line) for line in provenance.jsonl_path.read_text().splitlines()]
    absent = [
        entry
        for entry in entries
        if entry["step"] == "extract.warning"
        and entry["payload"].get("warning") == "EPPO cache absent"
    ]
    assert len(absent) == 1
    assert properties == [{}, {}]
