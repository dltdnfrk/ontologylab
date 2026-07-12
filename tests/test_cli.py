"""CLI-level MVP loop: collect --file -> extract --engine mock -> review ->
approve --filter -> build-pack, all through ontologylab.main (in-process)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_ROOT = str(Path(__file__).resolve().parent.parent)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from ontologylab.kgstore import KGStore  # noqa: E402
from ontologylab.main import main  # noqa: E402
from ontologylab.packbuilder import list_packs  # noqa: E402

FIXTURE = (
    "The PaymentGateway validates cards through the FraudDetector. "
    "The FraudDetector consults the RiskModel for scoring."
)


def _run(*argv: str) -> int:
    with pytest.raises(SystemExit) as excinfo:
        main(list(argv))
    return int(excinfo.value.code or 0)


def test_cli_mvp_loop(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    packs_dir = tmp_path / "packs"
    fixture = tmp_path / "notes.md"
    fixture.write_text(FIXTURE, encoding="utf-8")

    assert _run("collect", "--file", str(fixture), "--data-dir", str(data_dir)) == 0
    assert (
        _run("extract", "--engine", "mock", "--data-dir", str(data_dir)) == 0
    )
    assert _run("review", "--data-dir", str(data_dir)) == 0

    # nothing is verified until the human approve command runs
    store = KGStore.open(data_dir / "kg.sqlite")
    nodes, edges = store.verified_subgraph()
    assert nodes == [] and edges == []
    store.close()

    assert (
        _run(
            "approve",
            "--filter",
            "entity_type=Component",
            "--data-dir",
            str(data_dir),
        )
        == 0
    )
    # second pass approves edges whose endpoints verified in pass one
    assert _run("approve", "--filter", "min_confidence=0", "--data-dir", str(data_dir)) == 0

    store = KGStore.open(data_dir / "kg.sqlite")
    nodes, edges = store.verified_subgraph()
    assert len(nodes) >= 2 and len(edges) >= 1
    store.close()

    assert (
        _run(
            "build-pack",
            "--name",
            "cli-demo",
            "--packs-dir",
            str(packs_dir),
            "--data-dir",
            str(data_dir),
        )
        == 0
    )
    packs = list_packs(packs_dir)
    assert len(packs) == 1
    assert packs[0]["counts"]["nodes_verified"] >= 2


def test_cli_collect_rejects_non_allowlisted_url(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    code = _run(
        "collect", "--url", "https://not-allowlisted.example/x", "--data-dir", str(data_dir)
    )
    assert code == 2
