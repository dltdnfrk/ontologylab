"""Literal counts for the offline statement-harness plumbing replay.

The store is the ten statement-harness fixtures, each prefixed with a Results
heading so the harness can see the section. Counts are hand-written from that
corpus: fourteen eligible units, twelve one-arm replies, ten distinct proposed
edges after two identical triples merge. Verified stays zero.
"""

from __future__ import annotations

import asyncio
import importlib.util
import json
import subprocess
import sys
from hashlib import sha256
from pathlib import Path
from typing import Protocol

from ontologylab.kgstore import KGStore
from ontologylab.schemas import preset
from ontologylab.statement_harness import PROMPT_VERSION

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "statement_harness_replay.py"
FIXTURES = ROOT / "tests" / "fixtures" / "statement_harness"
PREFIX = "Results\n"
BANNER = (
    "development-only plumbing replay; scripted slot engine; not an accuracy claim"
)
HASH_KEYS = [
    "rules",
    "cue",
    "prompt",
    "schema",
    "qualifier",
    "normalization",
    "completion",
]
DOCUMENTS = 10
CALLS = 14
RECEIPTS = 12
WRITTEN = 10
VERIFIED = 0


def _build_store(path: Path) -> None:
    with KGStore.open(path) as store:
        store.install_schema(**preset("agrochem-v2"))
        for index, fixture_path in enumerate(sorted(FIXTURES.glob("*.json"))):
            fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
            text = PREFIX + fixture["text"]
            digest = sha256(text.encode("utf-8")).hexdigest()
            store.insert_document(
                source_kind="upload",
                source_uri=f"file:///{fixture_path.name}",
                title=fixture["id"],
                raw_text=text,
                content_hash="sha256:" + digest,
                doi=f"10.5555/replay-{index}",
            )


def _run(store: Path, out: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--store", str(store), "--out", str(out)],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )


class _Generates(Protocol):
    async def generate(
        self, prompt: str, *, model: str | None = None,
    ) -> tuple[str, dict[str, int]]:
        ...


def _engine() -> _Generates:
    spec = importlib.util.spec_from_file_location("statement_harness_replay", SCRIPT)
    if spec is None or spec.loader is None:
        raise AssertionError("replay script did not load")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    engine: _Generates = module.ScriptedSlotEngine()
    return engine


def _prompt(window: str, slots: list[dict[str, str | int]]) -> str:
    return (
        "<statement-unit>\n"
        + json.dumps({"unit_id": "unit", "window": window, "slots": slots})
        + "\n</statement-unit>"
    )


def _slot(window: str, role: str, quote: str) -> dict[str, str | int]:
    start = window.index(quote)
    return {"role": role, "quote": quote, "start": start, "end": start + len(quote)}


def test_fixture_replay_counts_match_literals_and_verified_is_zero(tmp_path: Path) -> None:
    store = tmp_path / "kg.sqlite"
    out = tmp_path / "report.json"
    _build_store(store)
    completed = _run(store, out)
    assert completed.returncode == 0, completed.stderr
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert set(payload) == {
        "banner",
        "documents",
        "status",
        "calls",
        "receipts",
        "harness_edges_written",
        "harness_edges_verified",
        "rejection_reasons",
        "unprocessed_units",
        "hash_keys",
    }
    assert payload["banner"] == BANNER
    assert payload["documents"] == DOCUMENTS
    assert payload["status"] == "complete"
    assert payload["calls"] == CALLS
    assert payload["receipts"] == RECEIPTS
    assert payload["harness_edges_written"] == WRITTEN
    assert payload["harness_edges_verified"] == VERIFIED
    assert payload["rejection_reasons"] == {}
    assert payload["unprocessed_units"] == []
    assert payload["hash_keys"] == HASH_KEYS

    with KGStore.open(store, read_only=True, immutable=False) as opened:
        verified = opened.conn.execute(
            "SELECT COUNT(*) FROM edges WHERE status = 'verified'"
        ).fetchone()
        written = opened.conn.execute(
            "SELECT COUNT(DISTINCT e.id) FROM edges e "
            "JOIN citations c ON c.item_id = e.id AND c.kind = 'edge' "
            "WHERE c.prompt_version = ?",
            (PROMPT_VERSION,),
        ).fetchone()
    assert verified is not None and verified[0] == VERIFIED
    assert written is not None and written[0] == WRITTEN

    engine = _engine()
    window = "Glyphosate reduced density, and mesotrione too."
    one_arm = asyncio.run(engine.generate(_prompt(window, [
        _slot(window, "arm", "Glyphosate"),
        _slot(window, "result", "reduced density"),
    ])))
    one_payload = json.loads(one_arm[0])
    assert len(one_payload["statements"]) == 1
    statement = one_payload["statements"][0]
    assert statement["arm"]["quote"] == "Glyphosate"
    assert statement["result"]["quote"] == "reduced density"
    assert statement["subject"]["quote"] == "Glyphosate"
    assert statement["object"]["quote"] == "reduced density"
    assert statement["polarity"] == "supports"

    two_arm = asyncio.run(engine.generate(_prompt(window, [
        _slot(window, "arm", "Glyphosate"),
        _slot(window, "arm", "mesotrione"),
        _slot(window, "result", "reduced density"),
    ])))
    assert json.loads(two_arm[0]) == {"statements": []}


def test_replay_refuses_application_support_paths(tmp_path: Path) -> None:
    out = tmp_path / "report.json"
    forbidden_store = tmp_path / "Application Support" / "kg.sqlite"
    completed = _run(forbidden_store, out)
    assert completed.returncode == 2
    assert "Application Support" in completed.stderr
    assert not out.exists()

    store = tmp_path / "kg.sqlite"
    store.write_bytes(b"")
    forbidden_out = tmp_path / "Application Support" / "report.json"
    completed = subprocess.run(
        [sys.executable, str(SCRIPT), "--store", str(store), "--out", str(forbidden_out)],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 2
    assert "Application Support" in completed.stderr
    assert not forbidden_out.exists()
