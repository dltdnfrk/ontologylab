from __future__ import annotations

from pathlib import Path

import pytest

from ontologylab.kgstore import KGStore
from ontologylab.packbuilder import PackBuildError, build_pack
from tests.test_method_pack import seed_method_pack_database
from tests.test_packbuilder import _populate


def test_duplicate_selection_rejects_before_stage(tmp_path: Path) -> None:
    kg = tmp_path / "kg.sqlite"
    store = KGStore.open(kg)
    _populate(store)
    store.close()
    method = seed_method_pack_database(kg)
    method.close()
    packs = tmp_path / "packs"
    with pytest.raises(
        PackBuildError,
        match="duplicate method release id 'release-1'",
    ):
        build_pack(
            kg,
            packs,
            "demo",
            method_release_ids=("release-1", "release-1"),
            allow_incomplete_extraction=True,
            incomplete_extraction_intent="fixture",
        )
    assert not packs.exists()
    assert not list(tmp_path.glob(".packs-*-staging-*"))


def test_unknown_selection_rejects_before_stage(tmp_path: Path) -> None:
    kg = tmp_path / "kg.sqlite"
    store = KGStore.open(kg)
    _populate(store)
    store.close()
    packs = tmp_path / "packs"
    with pytest.raises(PackBuildError, match="unknown Method release"):
        build_pack(
            kg,
            packs,
            "demo",
            method_release_ids=("missing",),
            allow_incomplete_extraction=True,
            incomplete_extraction_intent="fixture",
        )
    assert not packs.exists()
    assert not list(tmp_path.glob(".packs-*-staging-*"))
