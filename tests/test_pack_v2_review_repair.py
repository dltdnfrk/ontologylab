"""Task 12 review repair: provenance, counts, exclusions, raw text, CLI, caps."""
# noqa: SIZE_OK — single SUT review-repair matrix; Task 12 owns only this file

from __future__ import annotations

import hashlib
import json
import re
import shutil
import sqlite3
import stat
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Final, Literal, TypeAlias

import pytest

from ontologylab.extraction_state import ChunkSpan, ExtractionRunBinding, put_extraction_receipts
from ontologylab.h1_store import persist_decision
from ontologylab.h1_types import H1Classification, H1Decision, H1Family, H1QuarantineReason
from ontologylab.mcp_server import PackSession
from ontologylab.migration import compute_source_fingerprint
from ontologylab.pack_readiness import authorize_publication, receipt_inventory
from ontologylab.pack_verifier import PackVerifyCode, PackVerifyRefused, verify_pack
from ontologylab.packbuilder import build_pack, list_packs
from ontologylab.verified_pack_reader import PackIntegrityError, activate_pack
from tests.factories import make_entity
from tests.test_pack_readiness_refusal import (
    _plant_c036,
    _ready_fixture,
    _request_sourced,
    _seal_ready,
)
from tests.test_pack_v2_closure import (
    _GENERATION,
    _TEXT,
    _V2Fixture,
    _plant_v2,
    _staging_residue,
    _visible_pack_names,
)
from tests.test_pack_v2_publication_surface import _reviewed_pack

_REVIEWED: Final = "reviewed"
_SOURCED: Final = "sourced-answer-v2"


def _unreviewed_pack(tmp_path: Path, *, name: str) -> tuple[Path, str]:
    fixture = _ready_fixture(tmp_path / "kg")
    packs = tmp_path / "packs"
    manifest = build_pack(fixture.kg, packs, name=name, evidence_mode="full")
    fixture.store.close()
    return packs, manifest.pack_id


def test_mcp_fact_results_carry_work_representation_citation_receipts(
    tmp_path: Path,
) -> None:
    packs, pack_id = _reviewed_pack(tmp_path, name="prov")
    session = PackSession(str(packs))
    try:
        session.load_pack(pack_id)
        lookup = session.entity_lookup(name="PaymentGateway", detail=False)
        match = lookup["matches"][0]
        pack = lookup["pack"]
        assert pack["pack_id"] == pack_id
        assert pack["content_hash"]
        assert pack.get("pack_schema_version") == 2
        assert pack.get("integrity_level")
        assert pack.get("evidence_mode") == "full"
        assert match.get("work_id")
        assert match.get("representation_id")
        assert match.get("representation_content_hash")
        assert match.get("citation_id")
        assert match.get("selected_text_hash")
        assert match.get("start_offset") is not None
        assert match.get("end_offset") is not None
        assert match.get("policy_identity")
        conn = sqlite3.connect(f"file:{packs / pack_id / 'pack.sqlite'}?mode=ro", uri=True)
        try:
            cite = conn.execute(
                "SELECT receipt_id, representation_id, selected_text_hash, "
                "start_offset, end_offset, policy_identity FROM citation_receipts "
                "WHERE fact_kind = 'node' AND fact_id = ?",
                (match["id"],),
            ).fetchone()
            work = conn.execute(
                "SELECT work_id, content_hash FROM documents WHERE id = ?",
                (match["representation_id"],),
            ).fetchone()
        finally:
            conn.close()
        assert cite is not None and work is not None
        assert match["citation_id"] == cite[0]
        assert match["representation_id"] == cite[1]
        assert match["selected_text_hash"] == cite[2]
        assert match["start_offset"] == cite[3]
        assert match["end_offset"] == cite[4]
        assert match["policy_identity"] == cite[5]
        assert match["work_id"] == work[0]
        assert match["representation_content_hash"] == work[1]
        search = session.semantic_search("PaymentGateway", detail=False)
        assert search["results"][0].get("citation_id")
        entity = session.get_entity(match["id"])
        assert entity["entity"].get("citation_id") or entity["entity"].get("citations")
        assert entity["pack"].get("pack_schema_version") == 2
    finally:
        session.close()


def test_v2_counts_use_packed_observation_and_review_tables(
    tmp_path: Path,
) -> None:
    packs, pack_id = _reviewed_pack(tmp_path, name="counts")
    payload = json.loads((packs / pack_id / "manifest.json").read_text(encoding="utf-8"))
    conn = sqlite3.connect(f"file:{packs / pack_id / 'pack.sqlite'}?mode=ro", uri=True)
    try:
        observations = int(conn.execute("SELECT COUNT(*) FROM document_observations").fetchone()[0])
        reviews = int(conn.execute("SELECT COUNT(*) FROM grounded_review_decisions").fetchone()[0])
        cites = int(conn.execute("SELECT COUNT(*) FROM citation_receipts").fetchone()[0])
        runs = int(conn.execute("SELECT COUNT(*) FROM extraction_run_receipts").fetchone()[0])
        nodes_v = int(conn.execute(
            "SELECT COUNT(*) FROM nodes WHERE status = 'verified'"
        ).fetchone()[0])
        edges_v = int(conn.execute(
            "SELECT COUNT(*) FROM edges WHERE status = 'verified' AND invalidated_ts IS NULL"
        ).fetchone()[0])
    finally:
        conn.close()
    assert payload["counts"]["observations"] == observations >= 1
    assert payload["counts"]["review_decisions"] == reviews >= 1
    assert payload["counts"]["citations"] == cites >= 1
    assert payload["counts"]["extraction_runs"] == runs >= 1
    assert payload["counts"]["nodes_verified"] == nodes_v >= 1
    assert payload["counts"]["edges_verified"] == edges_v >= 1
    session = PackSession(str(packs))
    try:
        session.load_pack(pack_id)
        stale = session.get_staleness()
        assert stale["pack_verified_count"] == nodes_v + edges_v
    finally:
        session.close()


def test_v2_manifest_emits_required_exclusion_counts(tmp_path: Path) -> None:
    fixture = _ready_fixture(tmp_path / "kg")
    ghost = make_entity("UngroundedGhost")
    fixture.store.insert_proposed(
        [ghost], [], source_doc_id=fixture.representation_id,
        extractor_engine="mock", commit=False,
    )
    fixture.store.conn.execute(
        "INSERT INTO grounded_review_decisions ("
        "receipt_id, fact_kind, fact_id, proposal_id, fact_revision, action, "
        "actor, reason, decided_ts, as_of_ts, citation_set_digest, "
        "citation_receipt_ids_json, representation_id, selection_receipt_id, "
        "policy_identity, run_receipt_id, predecessor_receipt_id, "
        "pack_ineligible, waived_fact_ids_json, waived_citation_ids_json, "
        "scoped_defects_json) "
        "SELECT 'review-waived-excl', fact_kind, fact_id, proposal_id, "
        "fact_revision, action, actor, reason, decided_ts, as_of_ts, "
        "citation_set_digest, citation_receipt_ids_json, representation_id, "
        "selection_receipt_id, policy_identity, run_receipt_id, "
        "predecessor_receipt_id, 1, waived_fact_ids_json, "
        "waived_citation_ids_json, scoped_defects_json "
        "FROM grounded_review_decisions WHERE receipt_id = ?",
        (fixture.review_ids[0],),
    )
    fixture.store.conn.execute(
        "INSERT INTO identifier_decisions "
        "(id, identifier_id, action, actor, reason, created_ts) "
        "VALUES ('idd-conflict', ?, 'resolve_collision', 'tester', 'conflict', 2.0)",
        (fixture.identifier_id,),
    )
    persist_decision(
        fixture.store.conn,
        H1Decision(
            family=H1Family.CITATION,
            anchor_id="legacy-bad",
            legacy_pk="legacy-bad",
            classification=H1Classification.QUARANTINED,
            reason=H1QuarantineReason.UNREADABLE_SOURCE,
            family_receipt_id=None,
            representation_id=fixture.representation_id,
            raw_byte_seal="sha256:" + "ab" * 32,
            file_hash="sha256:" + "cd" * 32,
            span_hash="sha256:" + "ef" * 32,
            evidence_json="{}",
        ),
    )
    _request_sourced(fixture.store.conn)
    inventory = receipt_inventory(fixture.store.conn)
    _plant_c036(
        fixture.store.conn,
        generation=fixture.generation,
        fingerprint=compute_source_fingerprint(fixture.store.conn),
        root=inventory.root,
    )
    fixture.store.conn.commit()
    packs = tmp_path / "packs"
    manifest = build_pack(fixture.kg, packs, name="excl", evidence_mode="full")
    fixture.store.close()
    payload = json.loads(
        (packs / manifest.pack_id / "manifest.json").read_text(encoding="utf-8"),
    )
    exclusions = payload["exclusions"]
    assert exclusions["ungrounded"] >= 1
    assert exclusions["waived"] >= 1
    assert exclusions["identity_conflicts"] >= 1
    assert exclusions["invalid_legacy_evidence"] >= 1


def test_full_v2_document_raw_text_reads_snapshot_evidence(
    tmp_path: Path,
) -> None:
    packs, pack_id = _reviewed_pack(tmp_path, name="raw")
    payload = json.loads((packs / pack_id / "manifest.json").read_text(encoding="utf-8"))
    rep_id = payload["closure"]["representation"][0]
    session = PackSession(str(packs))
    try:
        session.load_pack(pack_id)
        result = session.document_raw_text(rep_id)
        assert result["text"] == _TEXT
        assert result["representation_id"] == rep_id
        assert result["evidence_mode"] == "full"
        assert result["path"] == f"evidence/{rep_id}/full.txt"
        assert "documents/" not in str(result.get("path") or "")
    finally:
        session.close()


def test_excerpt_document_raw_text_is_typed_limitation(tmp_path: Path) -> None:
    fixture = _ready_fixture(tmp_path / "kg")
    packs = tmp_path / "packs"
    manifest = build_pack(fixture.kg, packs, name="excerpt", evidence_mode="excerpt")
    payload = json.loads(
        (packs / manifest.pack_id / "manifest.json").read_text(encoding="utf-8"),
    )
    rep_id = payload["closure"]["representation"][0]
    fixture.store.close()
    session = PackSession(str(packs))
    try:
        session.load_pack(manifest.pack_id)
        result = session.document_raw_text(rep_id)
        assert result.get("available") is False
        assert result.get("limitation")
        assert result.get("text") in {None, ""}
    finally:
        session.close()


def test_cli_publish_emits_json_for_closure_refusal(tmp_path: Path) -> None:
    fixture = _ready_fixture(tmp_path / "kg")
    packs = tmp_path / "packs"
    fixture.store.close()
    result = subprocess.run(
        [
            sys.executable, "-m", "ontologylab.pack_readiness",
            str(fixture.kg), "--publish", str(packs),
            "--name", "none-mode", "--evidence-mode", "none",
        ],
        check=False, capture_output=True, text=True,
    )
    assert result.returncode == 2
    payload = json.loads(result.stdout)
    assert payload["ok"] is False
    assert payload["code"]
    assert "Traceback" not in result.stderr
    assert _visible_pack_names(packs) == []
    assert _staging_residue(tmp_path) == []


def test_forged_reviewed_labels_are_refused_after_publish(tmp_path: Path) -> None:
    packs, pack_id = _unreviewed_pack(tmp_path, name="forge")
    pack_dir = packs / pack_id
    manifest_path = pack_dir / "manifest.json"
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert _REVIEWED not in payload["capabilities"]
    payload["capabilities"] = list(payload["capabilities"]) + [_REVIEWED, _SOURCED]
    manifest_path.chmod(stat.S_IMODE(manifest_path.stat().st_mode) | 0o200)
    manifest_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    manifest_path.chmod(0o444)
    with pytest.raises(PackVerifyRefused) as refused:
        verify_pack(pack_dir, working=tmp_path / "kg")
    assert refused.value.code is PackVerifyCode.INVALID_MANIFEST
    listed = list_packs(packs)
    for item in listed:
        caps = item.get("capabilities") or []
        assert _REVIEWED not in caps
        assert _SOURCED not in caps
    with pytest.raises(PackIntegrityError):
        activate_pack(pack_dir, working=tmp_path / "kg")
    session = PackSession(str(packs))
    try:
        with pytest.raises(PackIntegrityError):
            session.load_pack(pack_id)
    finally:
        session.close()


_WITNESS: Final = "receipt-inventory.json"


def _plant_extra_run(fixture) -> str:
    extra = put_extraction_receipts(
        fixture.store.conn,
        ExtractionRunBinding(
            representation_id=fixture.representation_id,
            policy_identity="policy-unshipped",
            config_identity="config-unshipped-extra",
            schema_version_id=1,
            extractor_engine="mock",
            extractor_model="",
            prompt_version="extract-v1",
            decode_params_json="{}",
        ),
        (
            ChunkSpan(
                index=0,
                start_offset=0,
                end_offset=len(_TEXT),
                text=_TEXT,
                text_hash=fixture.content_hash,
                coordinate_profile="document-utf8-v1",
            ),
        ),
    )
    return extra.run.receipt_id


def _authorized_extra_run(tmp_path: Path) -> tuple[_V2Fixture, str]:
    fixture = _ready_fixture(tmp_path / "kg")
    extra_id = _plant_extra_run(fixture)
    _request_sourced(fixture.store.conn)
    inventory = receipt_inventory(fixture.store.conn)
    _plant_c036(
        fixture.store.conn,
        generation=fixture.generation,
        fingerprint=compute_source_fingerprint(fixture.store.conn),
        root=inventory.root,
    )
    fixture.store.conn.commit()
    granted = authorize_publication(fixture.store.conn)
    assert _REVIEWED in granted.capabilities
    assert _SOURCED in granted.capabilities
    return fixture, extra_id


def test_extra_live_run_keeps_reviewed_labels_and_stays_unshipped(
    tmp_path: Path,
) -> None:
    fixture, extra_id = _authorized_extra_run(tmp_path)
    packs = tmp_path / "packs"
    manifest = build_pack(fixture.kg, packs, name="extra-run", evidence_mode="full")
    fixture.store.close()
    pack_dir = packs / manifest.pack_id
    payload = json.loads((pack_dir / "manifest.json").read_text(encoding="utf-8"))
    assert _REVIEWED in payload["capabilities"]
    assert _SOURCED in payload["capabilities"]
    conn = sqlite3.connect(f"file:{pack_dir / 'pack.sqlite'}?mode=ro", uri=True)
    try:
        packed_runs = {
            str(row[0])
            for row in conn.execute("SELECT receipt_id FROM extraction_run_receipts")
        }
    finally:
        conn.close()
    assert extra_id not in packed_runs
    witness = json.loads((pack_dir / _WITNESS).read_text(encoding="utf-8"))
    witness_runs = {
        entry[1] for entry in witness["entries"] if entry[0] == "run"
    }
    assert extra_id in witness_runs
    verify_pack(pack_dir, working=tmp_path / "kg")
    listed = list_packs(packs)
    assert any(_REVIEWED in (item.get("capabilities") or []) for item in listed)
    snapshot = activate_pack(pack_dir, working=tmp_path / "kg")
    try:
        caps = snapshot.manifest.get("capabilities")
        assert isinstance(caps, list) and _REVIEWED in caps
    finally:
        snapshot.close()
    session = PackSession(str(packs))
    try:
        session.load_pack(manifest.pack_id)
        lookup = session.entity_lookup(name="PaymentGateway")
        assert lookup["matches"]
        assert _REVIEWED in (lookup["pack"].get("capabilities") or payload["capabilities"])
    finally:
        session.close()


def test_tampered_source_inventory_witness_is_refused(tmp_path: Path) -> None:
    fixture, extra_id = _authorized_extra_run(tmp_path)
    packs = tmp_path / "packs"
    manifest = build_pack(fixture.kg, packs, name="wit-tamper", evidence_mode="full")
    fixture.store.close()
    pack_dir = packs / manifest.pack_id
    witness_path = pack_dir / _WITNESS
    body = json.loads(witness_path.read_text(encoding="utf-8"))
    body["entries"] = [
        entry for entry in body["entries"]
        if not (entry[0] == "run" and entry[1] == extra_id)
    ]
    witness_path.chmod(stat.S_IMODE(witness_path.stat().st_mode) | 0o200)
    witness_path.write_text(json.dumps(body, separators=(",", ":")), encoding="utf-8")
    witness_path.chmod(0o444)
    _rematerialize_inventory_hashes(pack_dir)
    with pytest.raises(PackVerifyRefused) as refused:
        verify_pack(pack_dir, working=tmp_path / "kg")
    assert refused.value.code is PackVerifyCode.INVALID_MANIFEST
    with pytest.raises(PackIntegrityError):
        activate_pack(pack_dir, working=tmp_path / "kg")
    listed = list_packs(packs)
    assert listed == [] or all(
        item.get("pack_id") != manifest.pack_id for item in listed
    )


def _rematerialize_inventory_hashes(pack_dir: Path) -> None:
    import hashlib
    import os

    files: list[tuple[str, bytes, int]] = []
    for dirpath, _dirnames, filenames in os.walk(pack_dir, followlinks=False):
        base = Path(dirpath)
        for name in filenames:
            child = base / name
            rel = child.relative_to(pack_dir).as_posix()
            if rel == "manifest.json":
                continue
            data = child.read_bytes()
            files.append((rel, data, stat.S_IMODE(child.stat().st_mode)))
    files.sort(key=lambda item: item[0])
    inventory = [
        {
            "file_type": "regular",
            "mode": mode,
            "path": rel,
            "sha256": "sha256:" + hashlib.sha256(data).hexdigest(),
            "size": len(data),
        }
        for rel, data, mode in files
    ]
    sqlite = next(data for rel, data, _mode in files if rel == "pack.sqlite")
    canonical = json.dumps(
        [
            {"file_type": "regular", "mode": mode, "path": rel,
             "sha256": "sha256:" + hashlib.sha256(data).hexdigest(),
             "size": len(data)}
            for rel, data, mode in files
        ],
        sort_keys=True, separators=(",", ":"),
    )
    manifest_path = pack_dir / "manifest.json"
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    payload["artifact_inventory"] = inventory
    payload["sqlite_hash"] = "sha256:" + hashlib.sha256(sqlite).hexdigest()
    payload["pack_content_hash"] = (
        "sha256:" + hashlib.sha256(canonical.encode()).hexdigest()
    )
    manifest_path.chmod(stat.S_IMODE(manifest_path.stat().st_mode) | 0o200)
    manifest_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    manifest_path.chmod(0o444)


def test_packed_receipt_absent_from_witness_is_refused(tmp_path: Path) -> None:
    fixture, _extra = _authorized_extra_run(tmp_path)
    packs = tmp_path / "packs"
    manifest = build_pack(fixture.kg, packs, name="subset-wit", evidence_mode="full")
    fixture.store.close()
    pack_dir = packs / manifest.pack_id
    packed_run = fixture.run_receipt_id
    witness_path = pack_dir / _WITNESS
    body = json.loads(witness_path.read_text(encoding="utf-8"))
    remaining = [
        entry for entry in body["entries"]
        if not (entry[0] == "run" and entry[1] == packed_run)
    ]
    body["entries"] = remaining
    witness_path.chmod(stat.S_IMODE(witness_path.stat().st_mode) | 0o200)
    witness_path.write_text(json.dumps(body, separators=(",", ":"), sort_keys=True), encoding="utf-8")
    witness_path.chmod(0o444)
    sqlite_path = pack_dir / "pack.sqlite"
    sqlite_path.chmod(stat.S_IMODE(sqlite_path.stat().st_mode) | 0o200)
    conn = sqlite3.connect(sqlite_path)
    try:
        from ontologylab.pack_v2_derive import source_inventory_root
        new_root = source_inventory_root(
            tuple((str(a), str(b), str(c)) for a, b, c in remaining)
        )
        conn.execute(
            "UPDATE c036_capability_receipts SET receipt_inventory_root = ?",
            (new_root,),
        )
        conn.commit()
    finally:
        conn.close()
    sqlite_path.chmod(0o444)
    _rematerialize_inventory_hashes(pack_dir)
    with pytest.raises(PackVerifyRefused) as refused:
        verify_pack(pack_dir, working=tmp_path / "kg")
    assert refused.value.code is PackVerifyCode.INVALID_MANIFEST


_FP_WITNESS: Final = "source-fingerprint.json"
_UNPUB_TEXT: Final = "Unpublished extra document bytes."
_UNPUB_HASH: Final = "unpublished-doc-hash-v1"


def _authorized_unpublished_doc(tmp_path: Path) -> tuple[_V2Fixture, str, str]:
    fixture = _plant_v2(tmp_path / "kg")
    extra, _created = fixture.store.insert_document(
        source_kind="upload",
        source_uri="file:///unpublished.txt",
        title="unpublished",
        raw_text=_UNPUB_TEXT,
        content_hash=_UNPUB_HASH,
    )
    _seal_ready(fixture.store.conn, generation=_GENERATION)
    _request_sourced(fixture.store.conn)
    inventory = receipt_inventory(fixture.store.conn)
    _plant_c036(
        fixture.store.conn,
        generation=fixture.generation,
        fingerprint=compute_source_fingerprint(fixture.store.conn),
        root=inventory.root,
    )
    fixture.store.conn.commit()
    granted = authorize_publication(fixture.store.conn)
    assert _REVIEWED in granted.capabilities
    assert _SOURCED in granted.capabilities
    return fixture, extra.id, extra.content_hash or _UNPUB_HASH


_JsonScalar: TypeAlias = str | int | float | bool | None
_JsonValue: TypeAlias = _JsonScalar | list["_JsonValue"] | dict[str, "_JsonValue"]


def _claimed_inventory_entry(payload: dict[str, _JsonValue], path: str) -> dict[str, _JsonValue]:
    inventory = payload["artifact_inventory"]
    assert isinstance(inventory, list)
    for item in inventory:
        assert isinstance(item, dict)
        if item.get("path") == path:
            return item
    raise AssertionError(path)


def _assert_owner_readonly_witness(
    pack_dir: Path, payload: dict[str, _JsonValue], name: str,
) -> None:
    claimed = _claimed_inventory_entry(payload, name)
    data = (pack_dir / name).read_bytes()
    assert claimed["mode"] == 0o444
    assert claimed["file_type"] == "regular"
    assert claimed["size"] == len(data)
    assert claimed["sha256"] == "sha256:" + hashlib.sha256(data).hexdigest()
    assert stat.S_IMODE((pack_dir / name).stat().st_mode) == 0o444


def _assert_pack_surfaces_refuse(packs: Path, pack_dir: Path, pack_id: str, working: Path) -> None:
    with pytest.raises(PackVerifyRefused) as refused:
        verify_pack(pack_dir, working=working)
    assert refused.value.code is PackVerifyCode.INVALID_MANIFEST
    listed = list_packs(packs)
    assert listed == [] or all(item.get("pack_id") != pack_id for item in listed)
    with pytest.raises(PackIntegrityError):
        activate_pack(pack_dir, working=working)
    session = PackSession(str(packs))
    try:
        with pytest.raises(PackIntegrityError):
            session.load_pack(pack_id)
    finally:
        session.close()


def test_unpublished_live_document_keeps_reviewed_labels_and_stays_unshipped(
    tmp_path: Path,
) -> None:
    fixture, extra_id, extra_hash = _authorized_unpublished_doc(tmp_path)
    packed_id = fixture.representation_id
    packs = tmp_path / "packs"
    manifest = build_pack(fixture.kg, packs, name="extra-doc", evidence_mode="full")
    fixture.store.close()
    pack_dir = packs / manifest.pack_id
    payload = json.loads((pack_dir / "manifest.json").read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    assert _REVIEWED in payload["capabilities"]
    assert _SOURCED in payload["capabilities"]
    conn = sqlite3.connect(f"file:{pack_dir / 'pack.sqlite'}?mode=ro", uri=True)
    try:
        packed_docs = {
            str(row[0]): str(row[1] or "")
            for row in conn.execute("SELECT id, IFNULL(content_hash, '') FROM documents")
        }
        extra_works = conn.execute(
            "SELECT COUNT(*) FROM works WHERE id = ?", (extra_id,),
        ).fetchone()
        extra_obs = conn.execute(
            "SELECT COUNT(*) FROM document_observations WHERE representation_id = ?",
            (extra_id,),
        ).fetchone()
        extra_runs = conn.execute(
            "SELECT COUNT(*) FROM extraction_run_receipts WHERE representation_id = ?",
            (extra_id,),
        ).fetchone()
        claimed_fp = str(conn.execute(
            "SELECT source_fingerprint FROM c036_capability_receipts",
        ).fetchone()[0])
    finally:
        conn.close()
    assert extra_id not in packed_docs
    assert packed_docs.keys() == {packed_id}
    assert extra_works is not None and int(extra_works[0]) == 0
    assert extra_obs is not None and int(extra_obs[0]) == 0
    assert extra_runs is not None and int(extra_runs[0]) == 0
    assert not (pack_dir / "evidence" / extra_id).exists()
    from ontologylab.pack_source_fingerprint import (
        fingerprint_from_entries,
        load_source_fingerprint,
    )
    witness_entries = load_source_fingerprint(pack_dir)
    assert witness_entries is not None
    assert (extra_id, extra_hash) in witness_entries
    assert (packed_id, packed_docs[packed_id]) in witness_entries
    assert fingerprint_from_entries(witness_entries) == claimed_fp
    _assert_owner_readonly_witness(pack_dir, payload, _FP_WITNESS)
    _assert_owner_readonly_witness(pack_dir, payload, _WITNESS)
    verify_pack(pack_dir, working=tmp_path / "kg")
    listed = list_packs(packs)
    assert any(_REVIEWED in (item.get("capabilities") or []) for item in listed)
    snapshot = activate_pack(pack_dir, working=tmp_path / "kg")
    try:
        caps = snapshot.manifest.get("capabilities")
        assert isinstance(caps, list) and _REVIEWED in caps
    finally:
        snapshot.close()
    session = PackSession(str(packs))
    try:
        session.load_pack(manifest.pack_id)
        lookup = session.entity_lookup(name="PaymentGateway")
        assert lookup["matches"]
        names = {item.get("name") for item in lookup["matches"]}
        assert "unpublished" not in names
        assert _UNPUB_TEXT not in json.dumps(lookup)
        missing = session.document_raw_text(extra_id)
        assert missing.get("available") is False
        assert extra_id not in str(missing.get("path") or "")
    finally:
        session.close()


def test_tampered_source_fingerprint_witness_is_refused(tmp_path: Path) -> None:
    fixture, extra_id, _hash = _authorized_unpublished_doc(tmp_path)
    packs = tmp_path / "packs"
    manifest = build_pack(fixture.kg, packs, name="fp-tamper", evidence_mode="full")
    fixture.store.close()
    pack_dir = packs / manifest.pack_id
    path = pack_dir / _FP_WITNESS
    body = json.loads(path.read_text(encoding="utf-8"))
    body["entries"] = [entry for entry in body["entries"] if entry[0] != extra_id]
    path.chmod(stat.S_IMODE(path.stat().st_mode) | 0o200)
    path.write_text(json.dumps(body, separators=(",", ":"), sort_keys=True), encoding="utf-8")
    path.chmod(0o444)
    _rematerialize_inventory_hashes(pack_dir)
    _assert_pack_surfaces_refuse(packs, pack_dir, manifest.pack_id, tmp_path / "kg")


@pytest.mark.parametrize(
    "mutate", ("reorder", "duplicate", "wrong-shape", "packed-missing", "extra-key"),
)
def test_invalid_source_fingerprint_witness_is_refused(
    tmp_path: Path, mutate: str,
) -> None:
    fixture, extra_id, extra_hash = _authorized_unpublished_doc(tmp_path)
    packs = tmp_path / "packs"
    manifest = build_pack(fixture.kg, packs, name=f"fp-{mutate}", evidence_mode="full")
    packed_id = fixture.representation_id
    fixture.store.close()
    pack_dir = packs / manifest.pack_id
    path = pack_dir / _FP_WITNESS
    body = json.loads(path.read_text(encoding="utf-8"))
    entries = list(body["entries"])
    if mutate == "reorder" and len(entries) >= 2:
        body["entries"] = list(reversed(entries))
    elif mutate == "duplicate":
        body["entries"] = [*entries, entries[0]]
    elif mutate == "wrong-shape":
        body["entries"] = [{"id": extra_id, "hash": extra_hash}]
    elif mutate == "extra-key":
        body["extra"] = True
    else:
        body["entries"] = [entry for entry in entries if entry[0] != packed_id]
        sqlite_path = pack_dir / "pack.sqlite"
        sqlite_path.chmod(stat.S_IMODE(sqlite_path.stat().st_mode) | 0o200)
        conn = sqlite3.connect(sqlite_path)
        try:
            from ontologylab.pack_source_fingerprint import fingerprint_from_entries
            remaining = tuple((str(a), str(b)) for a, b in body["entries"])
            conn.execute(
                "UPDATE c036_capability_receipts SET source_fingerprint = ?",
                (fingerprint_from_entries(remaining),),
            )
            conn.commit()
        finally:
            conn.close()
        sqlite_path.chmod(0o444)
    path.chmod(stat.S_IMODE(path.stat().st_mode) | 0o200)
    path.write_text(json.dumps(body, separators=(",", ":"), sort_keys=True), encoding="utf-8")
    path.chmod(0o444)
    _rematerialize_inventory_hashes(pack_dir)
    _assert_pack_surfaces_refuse(packs, pack_dir, manifest.pack_id, tmp_path / "kg")


def test_wrong_c036_source_fingerprint_is_refused(tmp_path: Path) -> None:
    fixture, _extra_id, _hash = _authorized_unpublished_doc(tmp_path)
    packs = tmp_path / "packs"
    manifest = build_pack(fixture.kg, packs, name="fp-wrong-c036", evidence_mode="full")
    fixture.store.close()
    pack_dir = packs / manifest.pack_id
    sqlite_path = pack_dir / "pack.sqlite"
    sqlite_path.chmod(stat.S_IMODE(sqlite_path.stat().st_mode) | 0o200)
    conn = sqlite3.connect(sqlite_path)
    try:
        conn.execute(
            "UPDATE c036_capability_receipts SET source_fingerprint = ?",
            ("deadbeef" * 8,),
        )
        conn.commit()
    finally:
        conn.close()
    sqlite_path.chmod(0o444)
    _rematerialize_inventory_hashes(pack_dir)
    _assert_pack_surfaces_refuse(packs, pack_dir, manifest.pack_id, tmp_path / "kg")


def test_unreviewed_forged_labels_with_fingerprint_witness_are_refused(
    tmp_path: Path,
) -> None:
    packs, pack_id = _unreviewed_pack(tmp_path, name="forge-fp")
    pack_dir = packs / pack_id
    assert (pack_dir / _FP_WITNESS).is_file()
    manifest_path = pack_dir / "manifest.json"
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert _REVIEWED not in payload["capabilities"]
    assert _SOURCED not in payload["capabilities"]
    payload["capabilities"] = list(payload["capabilities"]) + [_REVIEWED, _SOURCED]
    manifest_path.chmod(stat.S_IMODE(manifest_path.stat().st_mode) | 0o200)
    manifest_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    manifest_path.chmod(0o444)
    _assert_pack_surfaces_refuse(packs, pack_dir, pack_id, tmp_path / "kg")


_FAMILY_SQL: Final = (
    ("work", "SELECT id FROM works ORDER BY id"),
    ("identifier", "SELECT id FROM work_identifiers ORDER BY id"),
    ("redirect", "SELECT id FROM work_redirect_decisions ORDER BY id"),
    ("decision", "SELECT id FROM identifier_decisions ORDER BY id"),
    ("observation", "SELECT id FROM document_observations ORDER BY id"),
    ("representation", "SELECT id FROM documents ORDER BY id"),
    ("run", "SELECT receipt_id FROM extraction_run_receipts ORDER BY 1"),
    ("chunk", "SELECT receipt_id FROM extraction_chunk_receipts ORDER BY 1"),
    ("citation", "SELECT receipt_id FROM citation_receipts ORDER BY 1"),
    ("review_decision", "SELECT receipt_id FROM grounded_review_decisions ORDER BY 1"),
    ("policy", "SELECT receipt_id FROM preferred_selection_receipts ORDER BY 1"),
    ("provenance", "SELECT event_id FROM provenance_outbox ORDER BY 1"),
)
def _tamper_pack_sql(pack_dir: Path, mutate: Callable[[sqlite3.Connection], None]) -> None:
    path = pack_dir / "pack.sqlite"
    path.chmod(stat.S_IMODE(path.stat().st_mode) | 0o200)
    connection = sqlite3.connect(path)
    try:
        connection.execute("PRAGMA foreign_keys=OFF")
        mutate(connection)
        connection.commit()
    finally:
        connection.close()
        path.chmod(0o444)


def _rewrite_closure_and_counts(pack_dir: Path) -> None:
    from ontologylab.pack_v2_derive import derive_v2_counts

    connection = sqlite3.connect(f"file:{pack_dir / 'pack.sqlite'}?mode=ro", uri=True)
    try:
        members = {
            name: [str(row[0]) for row in connection.execute(sql)]
            for name, sql in _FAMILY_SQL
        }
        counts = derive_v2_counts(connection)
    finally:
        connection.close()
    manifest_path = pack_dir / "manifest.json"
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    mode = str(payload.get("evidence_mode") or "full")
    pattern = "*/full.txt" if mode == "full" else "*/window.txt"
    evidence = pack_dir / "evidence"
    members["source"] = (
        sorted(path.parent.name for path in evidence.glob(pattern))
        if evidence.is_dir() else []
    )
    payload["closure"] = members
    payload["counts"] = dict(counts)
    manifest_path.chmod(stat.S_IMODE(manifest_path.stat().st_mode) | 0o200)
    manifest_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    manifest_path.chmod(0o444)


def _rematerialize_incomplete_pack(pack_dir: Path) -> None:
    _rewrite_closure_and_counts(pack_dir)
    _rematerialize_inventory_hashes(pack_dir)


def _remove_evidence(pack_dir: Path, owner: str) -> None:
    target = pack_dir / "evidence" / owner
    if not target.exists():
        return
    for child in target.rglob("*"):
        if child.is_file():
            child.chmod(stat.S_IMODE(child.stat().st_mode) | 0o200)
    shutil.rmtree(target)


def _assert_incomplete_surfaces_refuse(
    packs: Path, pack_dir: Path, pack_id: str, working: Path,
) -> None:
    with pytest.raises(PackVerifyRefused) as refused:
        verify_pack(pack_dir, working=working)
    assert refused.value.code is PackVerifyCode.INVALID_MANIFEST
    assert refused.value.path
    cli = subprocess.run(
        [sys.executable, "-m", "ontologylab.pack_verifier", str(pack_dir)],
        check=False, capture_output=True, text=True,
    )
    assert cli.returncode == 2
    body = json.loads(cli.stdout)
    assert body["ok"] is False
    assert body["code"] == "invalid_manifest"
    assert "Traceback" not in cli.stderr
    listed = list_packs(packs)
    assert listed == [] or all(item.get("pack_id") != pack_id for item in listed)
    with pytest.raises(PackIntegrityError):
        activate_pack(pack_dir, working=working)
    session = PackSession(str(packs))
    try:
        with pytest.raises(PackIntegrityError):
            session.load_pack(pack_id)
        with pytest.raises(PackIntegrityError):
            session.resource_manifest(pack_id)
    finally:
        session.close()


def _authorized_combined(
    tmp_path: Path,
) -> tuple[_V2Fixture, str, str, str]:
    fixture = _plant_v2(tmp_path / "kg")
    extra_run = _plant_extra_run(fixture)
    extra_doc, _created = fixture.store.insert_document(
        source_kind="upload",
        source_uri="file:///unpublished.txt",
        title="unpublished",
        raw_text=_UNPUB_TEXT,
        content_hash=_UNPUB_HASH,
    )
    _seal_ready(fixture.store.conn, generation=_GENERATION)
    _request_sourced(fixture.store.conn)
    inventory = receipt_inventory(fixture.store.conn)
    _plant_c036(
        fixture.store.conn,
        generation=fixture.generation,
        fingerprint=compute_source_fingerprint(fixture.store.conn),
        root=inventory.root,
    )
    fixture.store.conn.commit()
    granted = authorize_publication(fixture.store.conn)
    assert _REVIEWED in granted.capabilities
    assert _SOURCED in granted.capabilities
    return fixture, extra_run, extra_doc.id, extra_doc.content_hash or _UNPUB_HASH


def test_deleted_packed_citation_is_refused_after_rehash(tmp_path: Path) -> None:
    packs, pack_id = _reviewed_pack(tmp_path, name="cite-gap")
    pack_dir = packs / pack_id
    working = tmp_path / "kg"

    def _drop_one_citation(connection: sqlite3.Connection) -> None:
        receipt = connection.execute(
            "SELECT receipt_id FROM citation_receipts ORDER BY receipt_id",
        ).fetchone()
        assert receipt is not None
        connection.execute("DROP TRIGGER IF EXISTS trg_citation_receipts_no_delete")
        connection.execute(
            "DELETE FROM citation_receipts WHERE receipt_id = ?", (str(receipt[0]),),
        )

    _tamper_pack_sql(pack_dir, _drop_one_citation)
    _rematerialize_incomplete_pack(pack_dir)
    _assert_incomplete_surfaces_refuse(packs, pack_dir, pack_id, working)


def test_deleted_packed_document_is_refused_after_rehash(tmp_path: Path) -> None:
    packs, pack_id = _reviewed_pack(tmp_path, name="doc-gap")
    pack_dir = packs / pack_id
    working = tmp_path / "kg"
    doc_id = json.loads((pack_dir / "manifest.json").read_text(encoding="utf-8"))[
        "closure"
    ]["representation"][0]

    def _drop_document(connection: sqlite3.Connection) -> None:
        connection.execute("DELETE FROM documents WHERE id = ?", (str(doc_id),))

    _tamper_pack_sql(pack_dir, _drop_document)
    _rematerialize_incomplete_pack(pack_dir)
    _assert_incomplete_surfaces_refuse(packs, pack_dir, pack_id, working)


def _recreate_without_fk(connection: sqlite3.Connection, table: str) -> None:
    row = connection.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = ?", (table,),
    ).fetchone()
    assert row is not None
    stripped = re.sub(r"\s+REFERENCES\s+\w+\s*\([^)]*\)", "", str(row[0]))
    connection.execute(f"ALTER TABLE {table} RENAME TO {table}__old")
    connection.execute(stripped)
    connection.execute(f"INSERT INTO {table} SELECT * FROM {table}__old")
    connection.execute(f"DROP TABLE {table}__old")


def _copy_live_row(
    connection: sqlite3.Connection,
    live_kg: Path,
    table: str,
    column: str,
    value: str,
) -> None:
    live = sqlite3.connect(f"file:{live_kg}?mode=ro", uri=True)
    try:
        columns = [str(row[1]) for row in live.execute(f"PRAGMA table_info({table})")]
        source = live.execute(
            f"SELECT * FROM {table} WHERE {column} = ?", (value,),
        ).fetchone()
    finally:
        live.close()
    assert source is not None
    placeholders = ",".join("?" * len(columns))
    connection.execute(
        f"INSERT INTO {table} ({','.join(columns)}) VALUES ({placeholders})",
        tuple(source),
    )


def test_deleted_required_review_is_refused_after_rehash(tmp_path: Path) -> None:
    packs, pack_id = _reviewed_pack(tmp_path, name="drop-review")
    pack_dir = packs / pack_id

    def _drop_review(connection: sqlite3.Connection) -> None:
        row = connection.execute(
            "SELECT receipt_id FROM grounded_review_decisions ORDER BY 1",
        ).fetchone()
        assert row is not None
        connection.execute("DROP TRIGGER IF EXISTS trg_grounded_review_decisions_no_delete")
        connection.execute(
            "DELETE FROM grounded_review_decisions WHERE receipt_id = ?",
            (str(row[0]),),
        )

    _tamper_pack_sql(pack_dir, _drop_review)
    _rematerialize_incomplete_pack(pack_dir)
    _assert_incomplete_surfaces_refuse(packs, pack_dir, pack_id, tmp_path / "kg")


def test_deleted_required_run_is_refused_after_rehash(tmp_path: Path) -> None:
    fixture, extra_run, _doc, _hash = _authorized_combined(tmp_path)
    packs = tmp_path / "packs"
    manifest = build_pack(fixture.kg, packs, name="drop-run", evidence_mode="full")
    live_kg = fixture.kg
    original = fixture.run_receipt_id
    fixture.store.close()
    pack_dir = packs / manifest.pack_id

    def _replace_run(connection: sqlite3.Connection) -> None:
        _copy_live_row(
            connection, live_kg, "extraction_run_receipts", "receipt_id", extra_run,
        )
        _recreate_without_fk(connection, "citation_receipts")
        _recreate_without_fk(connection, "extraction_chunk_receipts")
        connection.execute("DROP TRIGGER IF EXISTS trg_extraction_run_receipts_no_delete")
        connection.execute(
            "DELETE FROM extraction_run_receipts WHERE receipt_id = ?", (original,),
        )

    _tamper_pack_sql(pack_dir, _replace_run)
    _rematerialize_incomplete_pack(pack_dir)
    _assert_incomplete_surfaces_refuse(
        packs, pack_dir, manifest.pack_id, tmp_path / "kg",
    )


def test_deleted_required_chunk_is_refused_after_rehash(tmp_path: Path) -> None:
    fixture, extra_run, _doc, _hash = _authorized_combined(tmp_path)
    extra_chunk = str(fixture.store.conn.execute(
        "SELECT receipt_id FROM extraction_chunk_receipts WHERE run_receipt_id = ?",
        (extra_run,),
    ).fetchone()[0])
    packs = tmp_path / "packs"
    manifest = build_pack(fixture.kg, packs, name="drop-chunk", evidence_mode="full")
    live_kg = fixture.kg
    original = fixture.chunk_receipt_id
    fixture.store.close()
    pack_dir = packs / manifest.pack_id

    def _replace_chunk(connection: sqlite3.Connection) -> None:
        _copy_live_row(
            connection, live_kg, "extraction_chunk_receipts", "receipt_id", extra_chunk,
        )
        _recreate_without_fk(connection, "citation_receipts")
        connection.execute("DROP TRIGGER IF EXISTS trg_extraction_chunk_receipts_no_delete")
        connection.execute(
            "DELETE FROM extraction_chunk_receipts WHERE receipt_id = ?", (original,),
        )

    _tamper_pack_sql(pack_dir, _replace_chunk)
    _rematerialize_incomplete_pack(pack_dir)
    _assert_incomplete_surfaces_refuse(
        packs, pack_dir, manifest.pack_id, tmp_path / "kg",
    )


def test_deleted_required_policy_is_refused_after_rehash(tmp_path: Path) -> None:
    from ontologylab.selection import put_selection_receipt
    from ontologylab.selection_types import PolicyVersion

    fixture = _ready_fixture(tmp_path / "kg")
    put_selection_receipt(fixture.store.conn, fixture.alias_work_id, PolicyVersion.V1)
    _request_sourced(fixture.store.conn)
    inventory = receipt_inventory(fixture.store.conn)
    _plant_c036(
        fixture.store.conn,
        generation=fixture.generation,
        fingerprint=compute_source_fingerprint(fixture.store.conn),
        root=inventory.root,
    )
    fixture.store.conn.commit()
    packs = tmp_path / "packs"
    manifest = build_pack(fixture.kg, packs, name="drop-policy", evidence_mode="full")
    original = fixture.policy_receipt_id
    fixture.store.close()
    pack_dir = packs / manifest.pack_id

    def _drop_primary_policy(connection: sqlite3.Connection) -> None:
        connection.execute(
            "DROP TRIGGER IF EXISTS trg_preferred_selection_receipts_no_delete",
        )
        connection.execute(
            "DELETE FROM preferred_selection_receipts WHERE receipt_id = ?",
            (original,),
        )

    _tamper_pack_sql(pack_dir, _drop_primary_policy)
    _rematerialize_incomplete_pack(pack_dir)
    _assert_incomplete_surfaces_refuse(
        packs, pack_dir, manifest.pack_id, tmp_path / "kg",
    )


def test_missing_required_evidence_is_refused_after_rehash(tmp_path: Path) -> None:
    packs, pack_id = _reviewed_pack(tmp_path, name="ev-gap")
    pack_dir = packs / pack_id
    doc_id = json.loads((pack_dir / "manifest.json").read_text(encoding="utf-8"))[
        "closure"
    ]["representation"][0]
    _remove_evidence(pack_dir, str(doc_id))
    decoy = pack_dir / "evidence" / "decoy-source" / "full.txt"
    decoy.parent.mkdir(parents=True)
    decoy.write_text("decoy", encoding="utf-8")
    decoy.chmod(0o444)
    _rematerialize_incomplete_pack(pack_dir)
    _assert_incomplete_surfaces_refuse(packs, pack_dir, pack_id, tmp_path / "kg")


_DangleFamily: TypeAlias = Literal[
    "citation", "run", "chunk", "review_decision", "representation",
]


@pytest.mark.parametrize(
    "family",
    ("citation", "run", "chunk", "review_decision", "representation"),
)
def test_dangling_packed_references_are_refused_after_rehash(
    tmp_path: Path, family: _DangleFamily,
) -> None:
    packs, pack_id = _reviewed_pack(tmp_path, name=f"dangle-{family}")
    pack_dir = packs / pack_id
    manifest_path = pack_dir / "manifest.json"
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    payload["closure"][family] = [*payload["closure"][family], f"ghost-{family}"]
    manifest_path.chmod(stat.S_IMODE(manifest_path.stat().st_mode) | 0o200)
    manifest_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    manifest_path.chmod(0o444)
    _rematerialize_inventory_hashes(pack_dir)
    _assert_incomplete_surfaces_refuse(packs, pack_dir, pack_id, tmp_path / "kg")


def test_honest_combined_extra_run_and_unpublished_doc_pack_remains_valid(
    tmp_path: Path,
) -> None:
    fixture, extra_run, extra_doc, extra_hash = _authorized_combined(tmp_path)
    packs = tmp_path / "packs"
    manifest = build_pack(fixture.kg, packs, name="both-extra", evidence_mode="full")
    fixture.store.close()
    pack_dir = packs / manifest.pack_id
    payload = json.loads((pack_dir / "manifest.json").read_text(encoding="utf-8"))
    assert _REVIEWED in payload["capabilities"]
    assert _SOURCED in payload["capabilities"]
    connection = sqlite3.connect(f"file:{pack_dir / 'pack.sqlite'}?mode=ro", uri=True)
    try:
        packed_runs = {
            str(row[0])
            for row in connection.execute("SELECT receipt_id FROM extraction_run_receipts")
        }
        packed_docs = {
            str(row[0])
            for row in connection.execute("SELECT id FROM documents")
        }
    finally:
        connection.close()
    assert extra_run not in packed_runs
    assert extra_doc not in packed_docs
    assert not (pack_dir / "evidence" / extra_doc).exists()
    witness = json.loads((pack_dir / _WITNESS).read_text(encoding="utf-8"))
    assert extra_run in {entry[1] for entry in witness["entries"] if entry[0] == "run"}
    fingerprint = json.loads((pack_dir / _FP_WITNESS).read_text(encoding="utf-8"))
    assert [extra_doc, extra_hash] in fingerprint["entries"]
    verify_pack(pack_dir, working=tmp_path / "kg")
    listed = list_packs(packs)
    assert any(item.get("pack_id") == manifest.pack_id for item in listed)
    snapshot = activate_pack(pack_dir, working=tmp_path / "kg")
    try:
        caps = snapshot.manifest.get("capabilities")
        assert isinstance(caps, list) and _REVIEWED in caps
    finally:
        snapshot.close()
    session = PackSession(str(packs))
    try:
        session.load_pack(manifest.pack_id)
        lookup = session.entity_lookup(name="PaymentGateway")
        assert lookup["matches"]
        missing = session.document_raw_text(extra_doc)
        assert missing.get("available") is False
        served = session.resource_manifest(manifest.pack_id)
        assert _REVIEWED in (served.get("capabilities") or [])
    finally:
        session.close()


def test_unreviewed_v2_pack_still_verifies(tmp_path: Path) -> None:
    packs, pack_id = _unreviewed_pack(tmp_path, name="unreviewed-ok")
    pack_dir = packs / pack_id
    payload = json.loads((pack_dir / "manifest.json").read_text(encoding="utf-8"))
    assert _REVIEWED not in payload["capabilities"]
    receipt = verify_pack(pack_dir, working=tmp_path / "kg")
    assert receipt.pack_id == pack_id


def test_v1_pack_still_verifies(tmp_path: Path) -> None:
    from ontologylab.kgstore import KGStore

    kg = tmp_path / "kg.sqlite"
    packs = tmp_path / "packs"
    store = KGStore.open(kg)
    document, _created = store.insert_document(
        source_kind="upload",
        source_uri="file:///v1.txt",
        title="v1",
        raw_text="RateLimiter uses TokenBucket",
        content_hash="v1-repair4-hash",
    )
    store.insert_proposed(
        [make_entity("RateLimiter")],
        [],
        source_doc_id=document.id,
        extractor_engine="mock",
    )
    node_id = store.conn.execute("SELECT id FROM nodes").fetchone()["id"]
    store.approve(node_id)
    store.close()
    manifest = build_pack(
        kg, packs, name="legacy-r4",
        allow_incomplete_extraction=True,
        incomplete_extraction_intent="v1-compat",
    )
    pack_dir = packs / manifest.pack_id
    receipt = verify_pack(pack_dir)
    assert receipt.pack_schema_version.value == 1
    allowed = {"knowledge-graph-v1", "methodology-v1"}
    listed = list_packs(packs)
    assert any(item.get("pack_id") == manifest.pack_id for item in listed)
    listed_caps = next(
        item.get("capabilities") or []
        for item in listed
        if item.get("pack_id") == manifest.pack_id
    )
    assert isinstance(listed_caps, list)
    assert set(listed_caps) <= allowed
    snapshot = activate_pack(pack_dir)
    try:
        activated = snapshot.manifest.get("capabilities") or []
        assert isinstance(activated, list)
        assert set(activated) <= allowed
    finally:
        snapshot.close()
    session = PackSession(str(packs))
    try:
        session.load_pack(manifest.pack_id)
        served = session.resource_manifest(manifest.pack_id)
        served_caps = served.get("capabilities") or []
        assert isinstance(served_caps, list)
        assert set(served_caps) <= allowed
        assert session.pack_id == manifest.pack_id
    finally:
        session.close()


def test_prior_loaded_session_survives_sibling_incomplete_pack(tmp_path: Path) -> None:
    fixture, _run, _doc, _hash = _authorized_combined(tmp_path)
    packs = tmp_path / "packs"
    honest = build_pack(fixture.kg, packs, name="honest-hold", evidence_mode="full")
    sibling = build_pack(fixture.kg, packs, name="sib-incomplete", evidence_mode="full")
    fixture.store.close()
    honest_dir = packs / honest.pack_id
    sibling_dir = packs / sibling.pack_id

    def _drop_one_citation(connection: sqlite3.Connection) -> None:
        receipt = connection.execute(
            "SELECT receipt_id FROM citation_receipts ORDER BY receipt_id",
        ).fetchone()
        assert receipt is not None
        connection.execute("DROP TRIGGER IF EXISTS trg_citation_receipts_no_delete")
        connection.execute(
            "DELETE FROM citation_receipts WHERE receipt_id = ?", (str(receipt[0]),),
        )

    session = PackSession(str(packs))
    try:
        session.load_pack(honest.pack_id)
        before = session.entity_lookup(name="PaymentGateway")
        assert before["matches"]
        _tamper_pack_sql(sibling_dir, _drop_one_citation)
        _rematerialize_incomplete_pack(sibling_dir)
        with pytest.raises(PackIntegrityError):
            session.load_pack(sibling.pack_id)
        with pytest.raises(PackIntegrityError):
            activate_pack(sibling_dir, working=tmp_path / "kg")
        after = session.entity_lookup(name="PaymentGateway")
        assert after["matches"][0]["id"] == before["matches"][0]["id"]
        assert session.pack_id == honest.pack_id
        listed = list_packs(packs)
        ids = {item.get("pack_id") for item in listed}
        assert honest.pack_id in ids
        assert sibling.pack_id not in ids
        verify_pack(honest_dir, working=tmp_path / "kg")
    finally:
        session.close()


def test_foreign_key_orphan_is_refused_after_rehash(tmp_path: Path) -> None:
    packs, pack_id = _reviewed_pack(tmp_path, name="fk-orphan")
    pack_dir = packs / pack_id

    def _orphan_alias(connection: sqlite3.Connection) -> None:
        connection.execute(
            "INSERT INTO node_aliases (node_id, normalized_alias, surface) "
            "VALUES ('missing-node', 'ghost-alias', 'Ghost')",
        )

    _tamper_pack_sql(pack_dir, _orphan_alias)
    _rematerialize_incomplete_pack(pack_dir)
    _assert_incomplete_surfaces_refuse(packs, pack_dir, pack_id, tmp_path / "kg")


def test_document_missing_work_is_refused_after_rehash(tmp_path: Path) -> None:
    packs, pack_id = _reviewed_pack(tmp_path, name="doc-work")
    pack_dir = packs / pack_id

    def _break_work(connection: sqlite3.Connection) -> None:
        connection.execute("UPDATE documents SET work_id = NULL")

    _tamper_pack_sql(pack_dir, _break_work)
    _rematerialize_incomplete_pack(pack_dir)
    _assert_incomplete_surfaces_refuse(packs, pack_dir, pack_id, tmp_path / "kg")


_UNREVIEWED_EVIDENCE: Final = ("knowledge-graph-v2", "evidence-self-contained-v2")


def _apply_unreviewed_evidence_capability_closure_strip(pack_dir: Path) -> None:
    def _drop_citation_and_c036(connection: sqlite3.Connection) -> None:
        receipt = connection.execute(
            "SELECT receipt_id FROM citation_receipts ORDER BY receipt_id",
        ).fetchone()
        assert receipt is not None
        connection.execute("DROP TRIGGER IF EXISTS trg_citation_receipts_no_delete")
        connection.execute(
            "DELETE FROM citation_receipts WHERE receipt_id = ?",
            (str(receipt[0]),),
        )
        connection.execute("DROP TABLE IF EXISTS c036_capability_receipts")

    _tamper_pack_sql(pack_dir, _drop_citation_and_c036)
    from ontologylab.pack_v2_derive import derive_v2_counts

    connection = sqlite3.connect(f"file:{pack_dir / 'pack.sqlite'}?mode=ro", uri=True)
    try:
        counts = derive_v2_counts(connection)
    finally:
        connection.close()
    manifest_path = pack_dir / "manifest.json"
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    payload.pop("evidence_mode", None)
    payload.pop("closure", None)
    payload["capabilities"] = list(_UNREVIEWED_EVIDENCE)
    payload["counts"] = dict(counts)
    manifest_path.chmod(stat.S_IMODE(manifest_path.stat().st_mode) | 0o200)
    manifest_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    manifest_path.chmod(0o444)
    _rematerialize_inventory_hashes(pack_dir)


def test_stripped_closure_advertising_evidence_capability_is_refused(
    tmp_path: Path,
) -> None:
    fixture, _run, _doc, _hash = _authorized_combined(tmp_path)
    packs = tmp_path / "packs"
    honest = build_pack(fixture.kg, packs, name="honest-hold-ev", evidence_mode="full")
    bypass = build_pack(fixture.kg, packs, name="bypass-strip-ev", evidence_mode="full")
    fixture.store.close()
    honest_dir = packs / honest.pack_id
    bypass_dir = packs / bypass.pack_id
    working = tmp_path / "kg"
    session = PackSession(str(packs))
    try:
        session.load_pack(honest.pack_id)
        before = session.entity_lookup(name="PaymentGateway")
        assert before["matches"]
        _apply_unreviewed_evidence_capability_closure_strip(bypass_dir)
        payload = json.loads((bypass_dir / "manifest.json").read_text(encoding="utf-8"))
        assert "evidence_mode" not in payload
        assert "closure" not in payload
        assert payload["capabilities"] == list(_UNREVIEWED_EVIDENCE)
        _assert_incomplete_surfaces_refuse(packs, bypass_dir, bypass.pack_id, working)
        after = session.entity_lookup(name="PaymentGateway")
        assert after["matches"][0]["id"] == before["matches"][0]["id"]
        assert session.pack_id == honest.pack_id
        listed = list_packs(packs)
        ids = {item.get("pack_id") for item in listed}
        assert honest.pack_id in ids
        assert bypass.pack_id not in ids
        verify_pack(honest_dir, working=working)
    finally:
        session.close()


_V2_AUTHORITY: Final = (
    "knowledge-graph-v2",
    "evidence-self-contained-v2",
    _REVIEWED,
    _SOURCED,
)


def _disguise_reviewed_as_v1(
    pack_dir: Path,
    *,
    schema_version: int | None,
    drop_c036: bool,
) -> None:
    if drop_c036:
        def _drop_c036(connection: sqlite3.Connection) -> None:
            connection.execute("DROP TABLE IF EXISTS c036_capability_receipts")

        _tamper_pack_sql(pack_dir, _drop_c036)
    sqlite_digest = (
        "sha256:" + hashlib.sha256((pack_dir / "pack.sqlite").read_bytes()).hexdigest()
    )
    payload: dict[str, _JsonValue] = {
        "pack_id": pack_dir.name,
        "capabilities": list(_V2_AUTHORITY),
        "content_hash": sqlite_digest,
    }
    if schema_version is not None:
        payload["pack_schema_version"] = schema_version
    manifest_path = pack_dir / "manifest.json"
    manifest_path.chmod(stat.S_IMODE(manifest_path.stat().st_mode) | 0o200)
    manifest_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    manifest_path.chmod(0o444)


@pytest.mark.parametrize(
    ("schema_version", "drop_c036"),
    ((1, False), (None, False), (None, True)),
    ids=("explicit-schema-1", "omitted-schema", "omitted-schema-drop-c036"),
)
def test_reviewed_v2_disguised_as_v1_is_refused_before_session_switch(
    tmp_path: Path, schema_version: int | None, drop_c036: bool,
) -> None:
    fixture, _run, _doc, _hash = _authorized_combined(tmp_path)
    packs = tmp_path / "packs"
    honest = build_pack(fixture.kg, packs, name="honest-v1-hold", evidence_mode="full")
    bypass = build_pack(fixture.kg, packs, name="v1-disguise", evidence_mode="full")
    fixture.store.close()
    honest_dir = packs / honest.pack_id
    bypass_dir = packs / bypass.pack_id
    working = tmp_path / "kg"
    session = PackSession(str(packs))
    try:
        session.load_pack(honest.pack_id)
        before = session.entity_lookup(name="PaymentGateway")
        assert before["matches"]
        _disguise_reviewed_as_v1(
            bypass_dir, schema_version=schema_version, drop_c036=drop_c036,
        )
        payload = json.loads((bypass_dir / "manifest.json").read_text(encoding="utf-8"))
        assert payload["capabilities"] == list(_V2_AUTHORITY)
        assert payload["content_hash"].startswith("sha256:")
        if schema_version is None:
            assert "pack_schema_version" not in payload
        else:
            assert payload["pack_schema_version"] == 1
        with pytest.raises(PackVerifyRefused) as refused:
            verify_pack(bypass_dir, working=working)
        assert refused.value.code is PackVerifyCode.INVALID_MANIFEST
        assert refused.value.path == "capabilities"
        cli = subprocess.run(
            [sys.executable, "-m", "ontologylab.pack_verifier", str(bypass_dir)],
            check=False, capture_output=True, text=True,
        )
        assert cli.returncode == 2
        body = json.loads(cli.stdout)
        assert body["ok"] is False
        assert body["code"] == "invalid_manifest"
        assert body["path"] == "capabilities"
        assert "Traceback" not in cli.stderr
        listed = list_packs(packs)
        ids = {item.get("pack_id") for item in listed}
        assert honest.pack_id in ids
        assert bypass.pack_id not in ids
        for item in listed:
            caps = item.get("capabilities") or []
            if item.get("pack_id") != honest.pack_id:
                assert _REVIEWED not in caps
                assert _SOURCED not in caps
        with pytest.raises(PackIntegrityError):
            activate_pack(bypass_dir, working=working)
        with pytest.raises(PackIntegrityError):
            session.load_pack(bypass.pack_id)
        with pytest.raises(PackIntegrityError):
            session.resource_manifest(bypass.pack_id)
        after = session.entity_lookup(name="PaymentGateway")
        assert after["matches"][0]["id"] == before["matches"][0]["id"]
        assert session.pack_id == honest.pack_id
        honest_caps = session.resource_manifest(honest.pack_id).get("capabilities") or []
        assert _REVIEWED in honest_caps
        verify_pack(honest_dir, working=working)
    finally:
        session.close()
