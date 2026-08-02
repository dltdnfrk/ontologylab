"""C1: a collect file argument may not name the store's own directory.

A collected document becomes extraction input, and extraction sends it to an
LLM provider; `packbuilder` also copies `source_uri` into distributed packs.
So collecting `data/` would mail out `kg.sqlite`, `providers.json`, and the
publisher keys planned for `sources.json`. The guard runs before any read,
on both the HTTP route and the CLI, because this repository keeps the two
gate orders deliberately identical.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ontologylab.connectors.allowlist import NotAllowlisted, check_collect_file


def _write(path: Path, text: str = "notes") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


# --------------------------------------------------------------------------
# The gate itself
# --------------------------------------------------------------------------


def test_a_sibling_of_the_store_is_accepted(tmp_path: Path) -> None:
    """The layout every existing caller uses must keep working."""
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    notes = _write(tmp_path / "notes.md")

    assert check_collect_file(str(notes), data_dir) == notes.resolve()


def test_a_file_inside_the_store_is_refused(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    secret = _write(data_dir / "sources.json", '{"api_key": "ELS-live"}')

    with pytest.raises(NotAllowlisted) as caught:
        check_collect_file(str(secret), data_dir)
    assert "sources.json" in str(caught.value)


def test_the_store_directory_itself_is_refused(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir()

    with pytest.raises(NotAllowlisted):
        check_collect_file(str(data_dir), data_dir)


def test_a_nested_file_inside_the_store_is_refused(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    nested = _write(data_dir / "jobs" / "run-1" / "provenance.jsonl")

    with pytest.raises(NotAllowlisted):
        check_collect_file(str(nested), data_dir)


def test_a_traversal_back_into_the_store_is_refused(tmp_path: Path) -> None:
    """`..` must not walk out and back in: the check resolves first."""
    data_dir = tmp_path / "data"
    _write(data_dir / "kg.sqlite", "binary")
    sneaky = tmp_path / "outside" / ".." / "data" / "kg.sqlite"
    (tmp_path / "outside").mkdir()

    with pytest.raises(NotAllowlisted):
        check_collect_file(str(sneaky), data_dir)


def test_a_file_that_does_not_exist_yet_is_still_refused(tmp_path: Path) -> None:
    """`sources.json` must be refused before it is ever created."""
    data_dir = tmp_path / "data"
    data_dir.mkdir()

    with pytest.raises(NotAllowlisted):
        check_collect_file(str(data_dir / "sources.json"), data_dir)


def test_a_name_that_merely_shares_the_prefix_is_accepted(tmp_path: Path) -> None:
    """`data-backup` is not inside `data`; a string prefix test would fail."""
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    neighbour = _write(tmp_path / "data-backup" / "notes.md")

    assert check_collect_file(str(neighbour), data_dir) == neighbour.resolve()


# --------------------------------------------------------------------------
# Symlinks: the plan enumerated five combinations; all but the sibling refuse.
# --------------------------------------------------------------------------


def test_a_link_pointing_into_the_store_is_refused(tmp_path: Path) -> None:
    """A: data_dir is the real path, the caller names a link to its interior."""
    data_dir = tmp_path / "data"
    secret = _write(data_dir / "sources.json", "key")
    link = tmp_path / "innocent.json"
    link.symlink_to(secret)

    with pytest.raises(NotAllowlisted):
        check_collect_file(str(link), data_dir)


def test_a_linked_store_named_by_its_real_path_is_refused(tmp_path: Path) -> None:
    """B: data_dir is a link, the caller names the real interior path."""
    real = tmp_path / "real-data"
    secret = _write(real / "sources.json", "key")
    linked = tmp_path / "data"
    linked.symlink_to(real)

    with pytest.raises(NotAllowlisted):
        check_collect_file(str(secret), linked)


def test_a_linked_store_named_through_the_link_is_refused(tmp_path: Path) -> None:
    """C: both sides travel through the link."""
    real = tmp_path / "real-data"
    _write(real / "sources.json", "key")
    linked = tmp_path / "data"
    linked.symlink_to(real)

    with pytest.raises(NotAllowlisted):
        check_collect_file(str(linked / "sources.json"), linked)


# --------------------------------------------------------------------------
# Both call sites. The gate order is deliberately identical, so both are
# checked here rather than trusting one to stand for the other.
# --------------------------------------------------------------------------


def test_the_http_route_refuses_before_reading_anything(tmp_path: Path) -> None:
    from fastapi.testclient import TestClient

    from ontologylab.server.app import create_app
    from ontologylab.server import routes

    data_dir = tmp_path / "data"
    secret = _write(data_dir / "sources.json", '{"api_key": "ELS-must-not-leak"}')
    client = TestClient(create_app(data_dir=data_dir))

    response = client.post("/api/collect", json={"files": [str(secret)]})

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is False
    assert body["error_kind"] == "rejected"
    # The refusal must not quote the file's contents back to the caller.
    assert "ELS-must-not-leak" not in json.dumps(body)


def test_the_http_route_still_collects_a_sibling_file(tmp_path: Path) -> None:
    from fastapi.testclient import TestClient

    from ontologylab.server.app import create_app
    from ontologylab.server import routes

    data_dir = tmp_path / "data"
    data_dir.mkdir()
    notes = _write(tmp_path / "notes.md", "a real research note")
    client = TestClient(create_app(data_dir=data_dir))

    response = client.post("/api/collect", json={"files": [str(notes)]})

    assert response.status_code == 200
    assert response.json()["ok"] is True


def _run_cli(*argv: str) -> int:
    from ontologylab.main import main

    with pytest.raises(SystemExit) as caught:
        main(list(argv))
    return int(caught.value.code or 0)


def test_the_cli_refuses_the_same_file(tmp_path: Path, capsys) -> None:
    data_dir = tmp_path / "data"
    secret = _write(data_dir / "sources.json", '{"api_key": "ELS-must-not-leak"}')

    code = _run_cli("collect", "--data-dir", str(data_dir), "--file", str(secret))

    assert code == 2
    captured = capsys.readouterr()
    assert "ELS-must-not-leak" not in captured.out + captured.err


def test_the_cli_still_collects_a_sibling_file(tmp_path: Path) -> None:
    """The guard must not break the layout every existing CLI test uses."""
    data_dir = tmp_path / "data"
    _write(tmp_path / "notes.md", "a real research note")

    assert (
        _run_cli(
            "collect",
            "--data-dir",
            str(data_dir),
            "--file",
            str(tmp_path / "notes.md"),
        )
        == 0
    )
