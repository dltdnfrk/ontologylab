"""Refuse to write the knowledge graph into iCloud.

This repo lives under ``~/Documents``. With macOS 'Desktop & Documents'
syncing on, that directory *is* the CloudDocs one — not a symlink to it, the
same directory — so the default ``ROOT/data`` puts the entity store, the raw
documents and every built pack on Apple's servers.

The trap was already written down, in the launchd plist and in
``launcher/move-data-out-of-icloud.sh``, in plain language. It still caught
someone: a server was started here without ``--data-dir`` and wrote a store
into the synced path. That is the argument for these tests — documentation
cannot refuse, and the failure is silent, so the code has to be the thing
that stops.

The symlink case matters as much as the refusal. The fix for an existing
checkout is to move ``data/``/``packs/`` out and leave symlinks behind, so a
guard that flagged those would condemn the very layout it recommends.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from ontologylab.paths import (
    ALLOW_ICLOUD_ENV,
    icloud_refusal,
    icloud_sync_reason,
)

CLOUD = "Library/Mobile Documents"
CLOUD_DOCS = f"{CLOUD}/com~apple~CloudDocs"


def _home(tmp_path: Path, *, synced: bool) -> Path:
    """A fake home, optionally with Desktop & Documents syncing on.

    Real syncing joins ``~/Documents`` and its CloudDocs twin into one
    directory. A symlink reproduces exactly what the check looks at — both
    names stat to the same device and inode — without needing a firmlink.
    """
    home = tmp_path / "home"
    (home / "Documents").mkdir(parents=True)
    (home / "Desktop").mkdir()
    (home / "Library/Application Support/ontologylab").mkdir(parents=True)
    twins = home / CLOUD_DOCS
    twins.mkdir(parents=True)
    if synced:
        (twins / "Documents").symlink_to(home / "Documents")
        (twins / "Desktop").symlink_to(home / "Desktop")
    return home


@pytest.fixture(autouse=True)
def _no_override(monkeypatch):
    monkeypatch.delenv(ALLOW_ICLOUD_ENV, raising=False)


# --------------------------------------------------------------------------
# What counts as synced
# --------------------------------------------------------------------------


def test_a_path_inside_icloud_drive_is_refused(tmp_path) -> None:
    home = _home(tmp_path, synced=False)
    target = home / CLOUD_DOCS / "ontologylab/data"
    target.mkdir(parents=True)

    assert icloud_sync_reason(target, home=home)


def test_the_repo_under_a_synced_documents_is_refused(tmp_path) -> None:
    """The case that actually bit, and the reason for the inode comparison.

    Nothing about this path looks unusual: it is not a symlink, and
    `resolve()` returns it unchanged. Only its identity with the CloudDocs
    twin gives it away.
    """
    home = _home(tmp_path, synced=True)
    target = home / "Documents/MUNI/ontologylab/data"
    target.mkdir(parents=True)

    reason = icloud_sync_reason(target, home=home)

    assert reason
    assert "Desktop & Documents" in reason


def test_the_same_repo_is_fine_when_syncing_is_off(tmp_path) -> None:
    """`~/Documents` is not inherently unsafe — only a synced one is.

    Without this the guard would refuse on every Mac, which is how a guard
    earns an env-var override that everyone sets and nobody reads.
    """
    home = _home(tmp_path, synced=False)
    target = home / "Documents/MUNI/ontologylab/data"
    target.mkdir(parents=True)

    assert icloud_sync_reason(target, home=home) is None


def test_a_synced_desktop_counts_too(tmp_path) -> None:
    home = _home(tmp_path, synced=True)
    target = home / "Desktop/ontologylab/data"
    target.mkdir(parents=True)

    assert icloud_sync_reason(target, home=home)


def test_application_support_is_the_safe_home(tmp_path) -> None:
    home = _home(tmp_path, synced=True)
    target = home / "Library/Application Support/ontologylab/data"

    assert icloud_sync_reason(target, home=home) is None


def test_the_recommended_symlink_layout_is_not_flagged(tmp_path) -> None:
    """The migration leaves `ROOT/data` as a symlink to Application Support.

    Judging the link by its own location rather than its target would make
    the guard reject the layout its own error message tells you to adopt.
    """
    home = _home(tmp_path, synced=True)
    real = home / "Library/Application Support/ontologylab/data"
    real.mkdir(parents=True)
    repo = home / "Documents/MUNI/ontologylab"
    repo.mkdir(parents=True)
    link = repo / "data"
    link.symlink_to(real)

    assert icloud_sync_reason(link, home=home) is None


def test_a_missing_directory_is_still_judged(tmp_path) -> None:
    """The first run creates the directory, so the check must land before it
    exists — otherwise the guard only ever fires after the leak."""
    home = _home(tmp_path, synced=True)
    target = home / "Documents/MUNI/ontologylab/data"

    assert not target.exists()
    assert icloud_sync_reason(target, home=home)


# --------------------------------------------------------------------------
# The refusal
# --------------------------------------------------------------------------


def test_the_refusal_names_the_switch_and_the_remedy(tmp_path) -> None:
    home = _home(tmp_path, synced=True)
    target = home / "Documents/MUNI/ontologylab/data"

    message = icloud_refusal({"--data-dir": target}, home=home)

    assert message
    assert "--data-dir" in message
    assert "move-data-out-of-icloud.sh" in message, "say how to fix it"
    assert ALLOW_ICLOUD_ENV in message, "and how to proceed anyway"


def test_a_safe_pair_of_paths_produces_no_refusal(tmp_path) -> None:
    home = _home(tmp_path, synced=True)
    safe = home / "Library/Application Support/ontologylab"

    assert icloud_refusal(
        {"--data-dir": safe / "data", "--packs-dir": safe / "packs"}, home=home
    ) is None


def test_packs_are_guarded_as_well_as_data(tmp_path) -> None:
    """A built pack is the knowledge graph in a portable file."""
    home = _home(tmp_path, synced=True)
    safe = home / "Library/Application Support/ontologylab/data"

    message = icloud_refusal(
        {"--data-dir": safe, "--packs-dir": home / "Documents/x/packs"}, home=home
    )

    assert message and "--packs-dir" in message


def test_the_override_is_honoured(tmp_path, monkeypatch) -> None:
    home = _home(tmp_path, synced=True)
    monkeypatch.setenv(ALLOW_ICLOUD_ENV, "1")

    assert icloud_refusal(
        {"--data-dir": home / "Documents/MUNI/ontologylab/data"}, home=home
    ) is None


# --------------------------------------------------------------------------
# Wired into the commands that write
# --------------------------------------------------------------------------


def _force_synced_home(monkeypatch, tmp_path) -> Path:
    home = _home(tmp_path, synced=True)
    monkeypatch.setattr(Path, "home", staticmethod(lambda: home))
    return home


def test_the_server_refuses_to_start(monkeypatch, tmp_path, capsys) -> None:
    from ontologylab import serve

    home = _force_synced_home(monkeypatch, tmp_path)
    doomed = home / "Documents/MUNI/ontologylab/data"
    monkeypatch.setattr(
        "sys.argv",
        ["ontologylab-serve", "--data-dir", str(doomed),
         "--packs-dir", str(home / "Library/Application Support/ontologylab/packs")],
    )

    with pytest.raises(SystemExit) as exit_info:
        serve.main()

    assert exit_info.value.code != 0
    # Read the capture ONCE — readouterr() drains the buffer, so a second
    # call in the same assertion returns "" and the `or` branch is vacuous.
    stderr = capsys.readouterr().err
    assert "Desktop & Documents" in stderr
    assert "move-data-out-of-icloud.sh" in stderr


def test_the_cli_refuses_before_running_a_subcommand(
    monkeypatch, tmp_path, capsys
) -> None:
    from ontologylab import main as cli

    home = _force_synced_home(monkeypatch, tmp_path)
    doomed = home / "Documents/MUNI/ontologylab/data"

    with pytest.raises(SystemExit) as exit_info:
        cli.main(["review", "--data-dir", str(doomed)])

    assert exit_info.value.code != 0
    assert "move-data-out-of-icloud.sh" in capsys.readouterr().err


def test_the_cli_still_runs_on_a_safe_path(monkeypatch, tmp_path) -> None:
    """Guard must not become the thing that breaks ordinary use."""
    from ontologylab import main as cli

    home = _force_synced_home(monkeypatch, tmp_path)
    safe = home / "Library/Application Support/ontologylab/data"
    safe.mkdir(parents=True, exist_ok=True)

    with pytest.raises(SystemExit) as exit_info:
        cli.main(["review", "--data-dir", str(safe)])

    assert exit_info.value.code == 0


def test_the_read_only_mcp_server_is_deliberately_unguarded() -> None:
    """Not an oversight.

    The MCP server only reads packs. Whatever exposure exists happened when
    the pack was written; refusing to read it back would break a deliberate
    choice (packs shared across machines via iCloud) while preventing
    nothing. The guard belongs on the writers.
    """
    from ontologylab import mcp_server

    source = Path(mcp_server.__file__).read_text(encoding="utf-8")

    assert "icloud_refusal" not in source
