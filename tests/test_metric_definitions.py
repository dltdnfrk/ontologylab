"""Committed metric definitions compile, release, pack and read back over MCP."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ontologylab.main import main
from ontologylab.mcp_server import PackSession
from ontologylab.method_ir import canonical_json_bytes, parse_method
from ontologylab.packbuilder import build_pack

DEFINITIONS = Path(__file__).resolve().parent.parent / "docs" / "method-definitions"
METRICS = {
    "control-efficacy": ("metric-control-efficacy", "efficacy"),
    "ec50-comparison": ("metric-ec50-comparison", "resistance-factor"),
    "limit-of-detection": ("metric-limit-of-detection", "lod"),
    "signal-to-background": ("metric-signal-to-background", "signal-to-background"),
}


def _cli(*args: str) -> None:
    with pytest.raises(SystemExit) as exit_info:
        main(["method", *args])
    assert exit_info.value.code == 0


def test_definitions_are_canonical_method_ir() -> None:
    assert {p.name.removesuffix(".method.json") for p in DEFINITIONS.glob("*.method.json")} == set(METRICS)
    for name, (method_id, result) in METRICS.items():
        raw = (DEFINITIONS / f"{name}.method.json").read_bytes()
        assert raw == canonical_json_bytes(json.loads(raw))
        method = parse_method(raw)
        assert method.id == method_id
        derived = next(f for f in method.fragments if f.id == result)
        assert derived.epistemic_class.value == "deterministic_derivation"


@pytest.mark.parametrize("name", sorted(METRICS))
def test_definition_releases_and_reads_back(tmp_path: Path, name: str) -> None:
    method_id, result = METRICS[name]
    data = str(tmp_path)
    source = DEFINITIONS / f"{name}.method.json"
    _cli("workspace-create", "--id", "ws", "--name", name, "--objective", "metric",
         "--scope", "{}", "--created-by", "analyst", "--data-dir", data)
    _cli("fragment-import", "--workspace-id", "ws", "--file", str(source), "--data-dir", data)
    _cli("link-import", "--workspace-id", "ws", "--file", str(source), "--data-dir", data)
    method = parse_method(source.read_bytes())
    for kind, items in (("fragment", method.fragments), ("link", method.links)):
        for item in items:
            _cli("decide", "--kind", kind, "--id", item.id, "--decision", "accepted",
                 "--reviewer", "human-analyst", "--note", "definition reviewed",
                 "--data-dir", data)
    fixtures = tmp_path / "fixtures.json"
    fixtures.write_bytes(canonical_json_bytes([
        {"id": "expected-output", "kind": "expected_output", "expected": method_id,
         "query": {"op": "get", "path": "/id"}},
        {"id": "expected-error", "kind": "expected_error",
         "query": {"op": "get", "path": "/does-not-exist"}},
        {"id": "expected-no-output", "kind": "expected_no_output",
         "query": {"field": "/id", "op": "select", "path": "/fragments",
                   "where": {"id": "absent"}}},
        {"id": "unknown-output", "kind": "unknown",
         "query": {"op": "get", "path": "/unknown"}},
    ]))
    _cli("compile", "--workspace-id", "ws", "--fixtures", str(fixtures),
         "--attempt-id", "attempt-1", "--release-id", "release-1",
         "--method-id", method_id, "--release-version", "1", "--data-dir", data)

    manifest = build_pack(
        tmp_path / "kg.sqlite", tmp_path / "packs", name=name,
        method_release_ids=("release-1",),
    )
    session = PackSession(tmp_path / "packs")
    try:
        session.load_pack(manifest.pack_id)
        served = session.get_method(method_id)["method"]
        assert {f["id"] for f in served["fragments"]} == {f.id for f in method.fragments}
        derived = next(f for f in served["fragments"] if f["id"] == result)
        assert derived["payload"]["formula"]["state"] == "known"
        assert session.list_method_gaps(method_id)["gaps"] == []
    finally:
        session.close()
