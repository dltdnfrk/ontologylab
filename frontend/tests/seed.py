import hashlib
import sys
from pathlib import Path

from ontologylab.kgstore import KGStore
from ontologylab.models import ProposedEntity, ProposedRelation, SourceSpan

root = Path(sys.argv[1]).resolve()
if not root.is_relative_to(Path("/private/tmp")) or (root / "kg.sqlite").exists():
    raise SystemExit("Use a fresh data directory under /private/tmp")
store = KGStore.open(root / "kg.sqlite")
try:
    text = "RecoveryAlpha uses RecoveryBeta. RecoveryGamma and RecoveryDelta are isolated."
    doc, created = store.insert_document(
        source_kind="upload",
        source_uri="file:///recovery-qa.txt",
        title="Recovery QA",
        raw_text=text,
        content_hash="sha256:" + hashlib.sha256(text.encode()).hexdigest(),
    )
    assert created, "Refusing to seed an already populated QA store"
    entities = [
        ProposedEntity(
            id=f"recovery-{name.lower()}",
            entity_type="Component",
            name=name,
            confidence=0.9,
            source_span=SourceSpan(start=text.index(name), end=text.index(name) + len(name)),
        )
        for name in ("RecoveryAlpha", "RecoveryBeta", "RecoveryGamma", "RecoveryDelta")
    ]
    relation = ProposedRelation(
        id="recovery-uses",
        relation_type="uses",
        src_entity_id=entities[0].id,
        dst_entity_id=entities[1].id,
        confidence=0.8,
        source_span=SourceSpan(start=0, end=31),
    )
    print(store.insert_proposed(
        entities, [relation], source_doc_id=doc.id,
        extractor_engine="mock", extractor_model=None, prompt_version="recovery-qa",
    ))
    print(store.counts())
finally:
    store.close()
