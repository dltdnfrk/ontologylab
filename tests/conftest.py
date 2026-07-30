"""Shared fixtures for ontologylab tests. Everything runs offline (mock engine)."""

from __future__ import annotations

import os
import uuid

import pytest

from ontologylab.kgstore import KGStore
from ontologylab.models import ProposedEntity, ProposedRelation, SourceSpan


@pytest.fixture(autouse=True)
def _never_touch_the_real_settings(monkeypatch, tmp_path):
    """No test may read or write the developer's own settings.json.

    Three separate times this suite overwrote it — once flipping
    `default_engine` from `claude` to `mock`, twice more from a mutation
    run — because `save_settings` defaulted to a machine-global path. The
    default is now the data directory, but "the default is safe" is a
    property one refactor can remove, so the guard is structural: every
    test gets its own location and the real one is not reachable from here.

    A test that genuinely needs the legacy path (there is one, for the
    upgrade fallback) monkeypatches `_legacy_settings_path` itself, which
    overrides this.
    """
    from ontologylab.server import settings as settings_mod

    sandbox = tmp_path / "_settings"
    sandbox.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(
        settings_mod, "_legacy_settings_path",
        lambda: sandbox / "legacy-settings.json", raising=True,
    )
    real = settings_mod._settings_path

    def guarded(data_dir=None):
        return real(sandbox if data_dir is None else data_dir)

    monkeypatch.setattr(settings_mod, "_settings_path", guarded, raising=True)


@pytest.fixture(autouse=True, scope="session")
def _allow_testclient_host():
    """Let the loopback Host guard accept FastAPI TestClient's 'testserver'.

    The server rejects non-loopback Host headers (DNS-rebinding defense); the
    ASGI TestClient drives the app as host 'testserver', so allowlist it for
    the test session only. Production stays loopback-only.
    """
    prior = os.environ.get("ONTOLOGYLAB_ALLOWED_HOSTS")
    os.environ["ONTOLOGYLAB_ALLOWED_HOSTS"] = "testserver"
    try:
        yield
    finally:
        if prior is None:
            os.environ.pop("ONTOLOGYLAB_ALLOWED_HOSTS", None)
        else:
            os.environ["ONTOLOGYLAB_ALLOWED_HOSTS"] = prior

SAMPLE_TEXT = (
    "# Service notes\n\n"
    "The ApiGateway forwards requests to the RateLimiter before they reach the\n"
    "OrderService. The RateLimiter implements the TokenBucketAlgorithm and stores\n"
    "counters in the SessionCache. The OrderService writes into the OrderDatabase.\n"
)


@pytest.fixture()
def store(tmp_path):
    s = KGStore.open(tmp_path / "kg.sqlite")
    yield s
    s.close()


@pytest.fixture()
def doc(store):
    document, created = store.insert_document(
        source_kind="upload",
        source_uri="file:///notes.md",
        title="notes",
        raw_text=SAMPLE_TEXT,
        content_hash="sha256:test",
    )
    assert created
    return document


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


def insert(store: KGStore, doc, entities, relations=()):
    return store.insert_proposed(
        entities,
        relations,
        source_doc_id=doc.id,
        extractor_engine="mock",
        extractor_model=None,
        prompt_version="extract-v1",
    )


def default_schema_dict():
    """Schema shape expected by parse_and_validate_extraction / prompt builder."""
    from ontologylab.ontology_schema import (
        DEFAULT_ENTITY_TYPES,
        DEFAULT_RELATION_TYPES,
    )

    return {
        "entity_types": [
            {"name": name, "description": desc, "attributes": attrs}
            for name, (desc, attrs) in DEFAULT_ENTITY_TYPES.items()
        ],
        "relation_types": [
            {
                "name": name,
                "description": desc,
                "domain_type": domain,
                "range_type": range_,
                "directed": directed,
            }
            for name, (desc, domain, range_, directed) in DEFAULT_RELATION_TYPES.items()
        ],
    }
