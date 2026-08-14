from __future__ import annotations

from pathlib import Path

import pytest

from ontologylab.main import build_arg_parser, main


def test_build_pack_accepts_repeatable_method_release_id() -> None:
    args = build_arg_parser().parse_args(
        [
            "build-pack", "--name", "demo",
            "--method-release-id", "release-b",
            "--method-release-id", "release-a",
        ]
    )
    assert args.method_release_id == ["release-b", "release-a"]


def test_build_pack_cli_rejects_duplicate_release_ids_without_job(
    tmp_path: Path,
    capsys,
) -> None:
    data_dir = tmp_path / "data"
    with pytest.raises(SystemExit) as raised:
        main([
            "build-pack",
            "--name",
            "demo",
            "--method-release-id",
            "release-1",
            "--method-release-id",
            "release-1",
            "--data-dir",
            str(data_dir),
            "--packs-dir",
            str(tmp_path / "packs"),
        ])
    captured = capsys.readouterr()
    assert raised.value.code == 2
    assert "duplicate method release id 'release-1'" in captured.err
    assert not data_dir.exists()
    assert not (tmp_path / "packs").exists()
