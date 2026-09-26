from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ontologylab.kgstore import KGStore
from ontologylab.mcp_server import PackSession
from ontologylab.models import ProposedEntity, ProposedRelation, SourceSpan
from ontologylab.packbuilder import build_pack
from ontologylab.schemas import preset

_GOLDEN = Path(__file__).parent / "fixtures" / "claims_contract" / "claims_for.json"

SECTION_6_KEYS = frozenset({
    "edge_id",
    "status",
    "provenance",
    "source_uri",
    "source_span",
    "retrieved_at",
    "valid_from",
    "valid_to",
    "value",
    "unit",
    "pack_id",
    "schema_version_id",
})

CURRENT_KEYS = frozenset({
    "edge_id",
    "subject",
    "relation",
    "object",
    "polarity",
    "qualifiers",
    "status",
    "origin",
    "confidence",
    "measurement",
    "evidence",
    "valid_from",
    "invalidated_ts",
    "schema_version_id",
})

_TIMESTAMP_KEYS = frozenset({
    "retrieved_at",
    "valid_from",
    "valid_to",
    "invalidated_ts",
    "fetched_ts",
})
_PACK_ID = "<pack_id>"
_HASH = "<hash>"
_TS = "<ts>"
_DOC_ID = "<source_doc_id>"
_NODE_ID = "<node_id>"
_EDGE_ID = "<edge_id>"
_SCHEMA_ID = "<schema_version_id>"


def _entity(
    eid: str,
    etype: str,
    name: str,
    properties: dict[str, Any] | None = None,
) -> ProposedEntity:
    return ProposedEntity(
        id=eid, entity_type=etype, name=name, properties=properties or {},
    )


def _controls(
    rid: str, src: str, dst: str, polarity: str, span: tuple[int, int],
) -> ProposedRelation:
    return ProposedRelation(
        id=rid,
        relation_type="controls",
        src_entity_id=src,
        dst_entity_id=dst,
        qualifiers={"polarity": polarity},
        source_span=SourceSpan(start=span[0], end=span[1]),
    )


def _paper(store: KGStore, tag: str):
    doc, _created = store.insert_document(
        source_kind="upload",
        source_uri=f"https://doi.org/10.1/{tag}",
        title=tag,
        raw_text=f"Paper {tag} on Fluopyram and Botrytis",
        content_hash=f"sha256:{tag}",
    )
    return doc


def contract_response(tmp_path: Path, *, prior_installs: int = 0) -> dict[str, Any]:
    kg = tmp_path / "kg.sqlite"
    store = KGStore.open(kg)
    try:
        schema = preset("agrochem-v2")
        for _ in range(prior_installs + 1):
            store.install_schema(
                label=schema["label"],
                description=schema["description"],
                entity_types=schema["entity_types"],
                relation_types=schema["relation_types"],
            )
        papers = {tag: _paper(store, tag) for tag in ("a", "b", "c")}
        fluo = ("fluo", "ActiveIngredient", "Fluopyram")
        botrytis = ("botr", "Pathogen", "Botrytis cinerea")
        alternaria = ("alt", "Pathogen", "Alternaria solani")
        measured = (
            "botr",
            "Pathogen",
            "Botrytis cinerea",
            {
                "measurement": {
                    "status": "normalized",
                    "value": 0.25,
                    "unit": "kg/ha",
                },
            },
        )
        batches = [
            ("a", [fluo, measured], [
                _controls("e1", "fluo", "botr", "supports", (0, 18)),
            ]),
            ("b", [fluo, botrytis], [
                _controls("e2", "fluo", "botr", "no_effect", (20, 44)),
            ]),
            ("c", [fluo, alternaria], [
                _controls("e3", "fluo", "alt", "supports", (4, 12)),
            ]),
        ]
        for tag, ents, rels in batches:
            store.insert_proposed(
                [_entity(*ent) for ent in ents],
                rels,
                source_doc_id=papers[tag].id,
                extractor_engine="mock",
            )
        for table in ("nodes", "edges"):
            proposed = store.conn.execute(
                f"SELECT id FROM {table} WHERE status='proposed'"
            ).fetchall()
            for (item,) in proposed:
                store.approve(item)
        ids = dict(store.conn.execute("SELECT name, id FROM nodes").fetchall())
        subject_id = ids["Fluopyram"]
    finally:
        store.close()

    manifest = build_pack(
        kg,
        tmp_path / "packs",
        name="claims",
        allow_incomplete_extraction=True,
        incomplete_extraction_intent="claims contract fixture",
    )
    session = PackSession(tmp_path / "packs")
    try:
        session.load_pack(manifest.pack_id)
        return session.claims_for(subject_id=subject_id)
    finally:
        session.close()


def normalize_contract(payload: dict[str, Any]) -> dict[str, Any]:
    normalized = _normalize(payload)
    pack = normalized.get("pack")
    if isinstance(pack, dict):
        normalized["pack"] = {key: f"<{key}>" for key in pack}
    return normalized


def _normalize(value: Any) -> Any:
    if isinstance(value, dict):
        normalized: dict[str, Any] = {}
        for key, item in value.items():
            if (
                key in _TIMESTAMP_KEYS
                and isinstance(item, (int, float))
                and not isinstance(item, bool)
            ):
                normalized[key] = _TS
            elif key == "pack_id" and isinstance(item, str):
                normalized[key] = _PACK_ID
            elif key == "content_hash" and isinstance(item, str):
                normalized[key] = _HASH
            elif key == "edge_id" and isinstance(item, str):
                normalized[key] = _EDGE_ID
            elif key == "id" and isinstance(item, str):
                normalized[key] = _NODE_ID
            elif key == "source_doc_id" and isinstance(item, str):
                normalized[key] = _DOC_ID
            elif key == "schema_version_id":
                normalized[key] = _SCHEMA_ID
            else:
                normalized[key] = _normalize(item)
        return normalized
    if isinstance(value, list):
        return [_normalize(item) for item in value]
    return value


def _assert_claim_keys(result: dict[str, Any]) -> None:
    assert result["claims"], "claims_for returned no claims to pin"
    expected_keys = SECTION_6_KEYS | CURRENT_KEYS
    schema_ids = {claim["schema_version_id"] for claim in result["claims"]}
    assert len(schema_ids) == 1
    schema_id = next(iter(schema_ids))
    assert isinstance(schema_id, int) and not isinstance(schema_id, bool)
    for claim in result["claims"]:
        assert set(claim) == expected_keys, sorted(set(claim) ^ expected_keys)


def test_claims_for_matches_the_section6_contract(tmp_path: Path) -> None:
    result = contract_response(tmp_path)
    _assert_claim_keys(result)
    golden = json.loads(_GOLDEN.read_text(encoding="utf-8"))
    assert normalize_contract(result) == golden


def test_contract_ignores_schema_allocation_and_pack_envelope(tmp_path: Path) -> None:
    baseline = contract_response(tmp_path / "baseline")
    shifted = contract_response(tmp_path / "shifted", prior_installs=1)
    _assert_claim_keys(baseline)
    _assert_claim_keys(shifted)
    baseline_ids = {claim["schema_version_id"] for claim in baseline["claims"]}
    shifted_ids = {claim["schema_version_id"] for claim in shifted["claims"]}
    assert baseline_ids.isdisjoint(shifted_ids)
    before = shifted["pack"]["integrity_level"]
    shifted["pack"]["integrity_level"] = "mutated-envelope"
    shifted["pack"]["pack_schema_version"] = 99
    shifted["pack"]["evidence_mode"] = "mutated-envelope"
    assert before != "mutated-envelope"
    golden = json.loads(_GOLDEN.read_text(encoding="utf-8"))
    assert normalize_contract(baseline) == golden
    assert normalize_contract(shifted) == golden
