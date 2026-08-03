"""Side-effect-free object factories shared by tests."""

from __future__ import annotations

import uuid

from ontologylab.models import ProposedEntity, ProposedRelation, SourceSpan


def make_entity(name: str, entity_type: str = "Component", **kwargs) -> ProposedEntity:
    span = kwargs.pop("source_span", SourceSpan(start=0, end=len(name)))
    return ProposedEntity(
        id=uuid.uuid4().hex,
        entity_type=entity_type,
        name=name,
        confidence=kwargs.pop("confidence", 0.9),
        source_span=span,
        **kwargs,
    )


def make_relation(
    src: ProposedEntity, dst: ProposedEntity, relation_type: str = "uses", **kwargs
) -> ProposedRelation:
    return ProposedRelation(
        id=uuid.uuid4().hex,
        relation_type=relation_type,
        src_entity_id=src.id,
        dst_entity_id=dst.id,
        confidence=kwargs.pop("confidence", 0.8),
        source_span=kwargs.pop("source_span", SourceSpan(start=0, end=10)),
        **kwargs,
    )
