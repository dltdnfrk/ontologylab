from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from ontologylab.kgstore import KGStore
from ontologylab.packbuilder import build_pack, list_packs
from tests.test_method_pack import seed_method_pack_database
from tests.test_packbuilder import _populate


class PublicationInterrupted(BaseException):
    pass


def _seed(path: Path) -> None:
    store = KGStore.open(path)
    _populate(store)
    store.close()
    seed_method_pack_database(path).close()


def _tree_hash(path: Path) -> str:
    digest = hashlib.sha256()
    for item in sorted(path.rglob("*")):
        if item.is_file():
            digest.update(str(item.relative_to(path)).encode())
            digest.update(item.read_bytes())
    return digest.hexdigest()


def test_base_exception_after_method_copy_cleans_stage(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    kg, packs = tmp_path / "kg.sqlite", tmp_path / "packs"
    _seed(kg)
    import ontologylab.packbuilder as packbuilder

    original = packbuilder.copy_method_releases
    calls = 0

    def interrupt(*args, **kwargs):
        nonlocal calls
        calls += 1
        result = original(*args, **kwargs)
        if calls == 2:
            raise PublicationInterrupted
        return result

    monkeypatch.setattr(packbuilder, "copy_method_releases", interrupt)
    with pytest.raises(PublicationInterrupted):
        build_pack(
            kg,
            packs,
            "demo",
            method_release_ids=("release-1",),
            allow_incomplete_extraction=True,
            incomplete_extraction_intent="fixture",
        )
    assert list_packs(packs) == []
    assert not list(tmp_path.glob(".packs-*-staging-*"))


def test_final_validation_failure_preserves_previous_pack(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    kg, packs = tmp_path / "kg.sqlite", tmp_path / "packs"
    _seed(kg)
    previous = build_pack(
        kg,
        packs,
        "previous",
        method_release_ids=("release-1",),
        allow_incomplete_extraction=True,
        incomplete_extraction_intent="fixture",
    )
    previous_dir = packs / previous.pack_id
    before = _tree_hash(previous_dir)
    import ontologylab.packbuilder as packbuilder

    original = packbuilder.validate_method_pack
    calls = 0

    def fail_final(*args, **kwargs):
        nonlocal calls
        calls += 1
        result = original(*args, **kwargs)
        if calls == 3:
            raise RuntimeError("injected final validation failure")
        return result

    monkeypatch.setattr(packbuilder, "validate_method_pack", fail_final)
    with pytest.raises(RuntimeError, match="final validation"):
        build_pack(
            kg,
            packs,
            "next",
            method_release_ids=("release-1",),
            allow_incomplete_extraction=True,
            incomplete_extraction_intent="fixture",
        )
    assert _tree_hash(previous_dir) == before
    assert [row["pack_id"] for row in list_packs(packs)] == [previous.pack_id]
    assert not list(tmp_path.glob(".packs-*-staging-*"))
