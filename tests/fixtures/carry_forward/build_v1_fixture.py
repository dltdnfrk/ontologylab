"""Synthetic production-shape carry-forward rehearsal; never reads a real store.

Run: uv run python -m tests.fixtures.carry_forward.build_v1_fixture
     --data-dir /private/tmp/<fresh-directory>
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from ontologylab.kgstore import KGStore
from ontologylab.models import ProposedEntity, ProposedRelation, SourceSpan
from ontologylab.schemas import preset


def build_fixture(data_dir: Path) -> tuple[int, int]:
    """Build five synthetic documents using only public store write methods."""
    target = data_dir.resolve()
    if not target.is_relative_to(Path("/private/tmp")):
        raise ValueError("synthetic fixture must be under /private/tmp")
    if (target / "kg.sqlite").exists():
        raise ValueError("synthetic fixture requires a fresh data directory")
    entities = [
        ProposedEntity(
            id=f"v1-node-{i:03}", entity_type="ActiveIngredient" if i < 36 else "Pest",
            name=f"Synthetic entity {i:03}", aliases=[f"Synthetic alias {i:03}"],
        )
        for i in range(72)
    ]
    entities.extend([
        ProposedEntity(
            id="v1-node-072", entity_type="DoseRate", name="Synthetic rate",
            properties={"value": "250", "unit": "g/ha"},
        ),
        ProposedEntity(
            id="v1-rejected", entity_type="Pest", name="Synthetic rejected entity",
        ),
    ])
    relations = [
        ProposedRelation(
            id=f"v1-edge-{i:03}", relation_type="controls",
            src_entity_id=entities[i // 36].id,
            dst_entity_id=entities[36 + i % 36].id,
        )
        for i in range(133)
    ]
    with KGStore.open(target / "kg.sqlite") as store:
        source = store.install_schema(**preset("agrochem"))
        for index in range(5):
            text = f"Synthetic document {index}.\n" + "\n".join(e.name for e in entities)
            document, _ = store.insert_document(
                source_kind="upload", source_uri=f"synthetic:carry-forward:{index}",
                title=f"Synthetic document {index}", raw_text=text,
                content_hash="sha256:" + hashlib.sha256(text.encode()).hexdigest(),
            )
            for entity in entities:
                start = text.index(entity.name)
                entity.source_span = SourceSpan(start, start + len(entity.name))
            selected = relations[index::5]
            for relation in selected:
                relation.source_span = SourceSpan(0, len(text))
            store.insert_proposed(
                entities, selected, source_doc_id=document.id,
                extractor_engine="synthetic", extractor_model="fixture-v1",
                prompt_version="fixture-1", decode_params={"temperature": 0},
            )
        for entity in entities[:-1]:
            store.approve(entity.id, by="fixture-reviewer")
        store.reject(entities[-1].id, by="fixture-reviewer", note="synthetic rejection")
        for relation in relations[:106] + relations[130:]:
            store.approve(relation.id, by="fixture-reviewer")
        for relation in relations[130:]:
            store.invalidate_edge(relation.id, by="fixture-reviewer", reason="synthetic history")
        destination = store.install_schema(**preset("agrochem-v2"))
    return source, destination


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, required=True)
    args = parser.parse_args()
    source, destination = build_fixture(args.data_dir)
    print(json.dumps({"from_schema": source, "to_schema": destination}))
