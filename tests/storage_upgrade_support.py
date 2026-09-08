from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from ontologylab.chatstore import ChatStore
from ontologylab.kgstore import KGStore
from ontologylab.storage_quiescence import (
    inspected_storage_paths,
    load_quiescence_proof,
)
from ontologylab.storage_upgrade import QuiescenceProof


def quiescence_proof(root: Path, *, valid: bool = True) -> QuiescenceProof:
    runtime = root / "runtime"
    runtime.mkdir(mode=0o700, parents=True, exist_ok=True)
    runtime.chmod(0o700)
    nonce = "1" * 32
    receipt_nonce = nonce if valid else "2" * 32
    receipt = runtime / "quiescence.json"
    data_dir = root / "data"
    inspected = [str(path) for path in inspected_storage_paths(data_dir)]
    receipt.write_text(
        json.dumps(
            {
                "schema_name": "ontologylab.storage-quiescence.v2",
                "proof_kind": "no_existing_backend",
                "supervisor_pid": os.getppid(),
                "nonce": receipt_nonce,
                "inspected_paths": inspected,
                "inspected_at_ns": 1,
                "initial_holder_pids": [],
                "final_holder_pids": [],
                "verified_owner": None,
                "signals": [],
                "exit_observed": False,
            }
        ),
        encoding="utf-8",
    )
    receipt.chmod(0o600)
    return load_quiescence_proof(
        receipt,
        supervisor_pid=os.getppid(),
        nonce=nonce,
        data_dir=data_dir,
    )


@dataclass(frozen=True, slots=True)
class UpgradeFixture:
    root: Path
    data_dir: Path
    packs_dir: Path
    backups_dir: Path
    database: Path
    source_hashes: tuple[tuple[str, str], ...]
    token: str


def tree_hashes(root: Path) -> tuple[tuple[str, str], ...]:
    return tuple(
        (path.relative_to(root).as_posix(), hashlib.sha256(path.read_bytes()).hexdigest())
        for path in sorted(root.rglob("*"))
        if path.is_file() and not path.name.endswith(("-wal", "-shm"))
    )


def make_older_fixture(root: Path) -> UpgradeFixture:
    data_dir = root / "data"
    packs_dir = root / "packs"
    backups_dir = root / "backups"
    for directory in (root, data_dir, packs_dir, backups_dir):
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    database = data_dir / "kg.sqlite"
    with KGStore.open(database) as store:
        store.conn.execute(
            "INSERT INTO documents (id, source_kind, source_uri, title, fetched_ts, "
            "content_hash, raw_text_path) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                "doc-1",
                "fixture",
                "fixture:1",
                "Fixture",
                1.0,
                "a" * 64,
                "documents/doc-1/raw.txt",
            ),
        )
        store.conn.commit()
    with sqlite3.connect(database) as connection:
        connection.execute("PRAGMA journal_mode=DELETE")
        connection.execute("DROP TABLE ontologylab_storage_metadata")
    with ChatStore.open(data_dir / "chat.sqlite") as chat:
        chat.record(message="hello", action="status", reading="hello", result={"ok": True}, steps=[])
    for name, payload in (
        ("settings.json", {"default_engine": "mock"}),
        ("providers.json", {"providers": []}),
        ("sources.json", {"sources": []}),
    ):
        (data_dir / name).write_text(json.dumps(payload), encoding="utf-8")
    raw = data_dir / "documents" / "doc-1" / "raw.txt"
    raw.parent.mkdir(parents=True)
    raw.write_text("raw body", encoding="utf-8")
    token = "0" * 64
    (data_dir / "session.token").write_text(token, encoding="utf-8")
    os.chmod(data_dir / "session.token", 0o600)
    return UpgradeFixture(
        root=root,
        data_dir=data_dir,
        packs_dir=packs_dir,
        backups_dir=backups_dir,
        database=database,
        source_hashes=tree_hashes(data_dir),
        token=token,
    )
