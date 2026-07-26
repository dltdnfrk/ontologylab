"""Step 4: where a publisher key lives, and everywhere it must not.

Until now this repository held no secrets, so `data/` being world-readable
and iCloud-synced cost nothing. A publisher key changes that, and `data/` is
where the registry has to live. So the registry stores a *reference* — a
Keychain account name or an environment-variable name — and there is no
field on `Source` that could hold a value.

The Keychain itself was verified on this machine before any of this was
written: a real one-shot LaunchAgent in `gui/$UID`, the same domain the
server runs in, read an item back with no authorization prompt. These tests
cover the code; that probe covered the platform.

Tests that touch the real Keychain are marked and skipped when `security` is
absent. The rest run anywhere.
"""

from __future__ import annotations

import json
import os
import subprocess
import uuid

import pytest

from ontologylab import keychain
from ontologylab.keychain import (
    KeychainError,
    delete_key,
    keychain_available,
    read_key,
    resolve_key,
    write_key,
)
from ontologylab.paths import sources_path
from ontologylab.sources import (
    SOURCE_ROLES,
    Source,
    SourceError,
    add_source,
    get_source,
    load_sources,
    remove_source,
    resolve_source_key,
    source_public,
    validate_source,
)

SECRET = "ELS-secret-value-must-never-hit-disk-9f3a"

needs_keychain = pytest.mark.skipif(
    not keychain_available(), reason="no macOS `security` binary"
)

# Tests write to the developer's real login Keychain — there is no fake one,
# which is the point of testing against it. So they must never write under
# the service name the product uses: a test that dies between writing and
# cleaning up would otherwise leave junk in the user's actual credential
# store. That is not hypothetical; a mutation run with the empty-key guard
# removed left an `ontologylab / ontologylab.test.empty` item behind exactly
# this way, and it had to be deleted by hand.
TEST_SERVICE = "ontologylab-pytest"

# Several tests monkeypatch `keychain.subprocess.run` to raise or hang — and
# `keychain.subprocess` is the same module object as this file's, so those
# patches replace `subprocess.run` globally. Teardown runs before monkeypatch
# unwinds, so the sweep has to hold the real callable from import time or it
# inherits whatever the test installed.
_REAL_RUN = subprocess.run


@pytest.fixture(autouse=True)
def _isolated_keychain_service(monkeypatch):
    """Point every Keychain call at a test-only service, then sweep it."""
    monkeypatch.setattr(keychain, "KEYCHAIN_SERVICE", TEST_SERVICE)
    yield
    if not keychain_available():
        return
    # Sweep whatever this test left, whether it cleaned up after itself or not.
    for _ in range(20):
        found = _REAL_RUN(
            ["security", "find-generic-password", "-s", TEST_SERVICE],
            capture_output=True, text=True, timeout=15,
        )
        if found.returncode != 0:
            break
        account = ""
        for line in found.stdout.splitlines():
            if '"acct"<blob>=' in line:
                account = line.split('="', 1)[-1].rstrip('"')
        if not account:
            break
        _REAL_RUN(
            ["security", "delete-generic-password",
             "-s", TEST_SERVICE, "-a", account],
            capture_output=True, text=True, timeout=15,
        )


def _source(**overrides) -> Source:
    return Source(
        **{
            "id": "journals",
            "role": "literature",
            "keychain_account": "ontologylab.literature",
            "label": "저널 접근",
            **overrides,
        }
    )


# --------------------------------------------------------------------------
# The registry cannot hold a key
# --------------------------------------------------------------------------


def test_the_serialized_field_set_is_exactly_these_five(tmp_path) -> None:
    """The lock. A new field is how a key would get written to disk.

    `data/` syncs to iCloud (that is what killed the original plaintext
    plan), so a field added here without thinking travels off the machine.
    Copied deliberately from `test_providers.py`'s equivalent.
    """
    add_source(tmp_path, _source())

    stored = json.loads(sources_path(tmp_path).read_text(encoding="utf-8"))
    assert set(stored["sources"][0]) == {
        "id", "role", "keychain_account", "api_key_env", "label",
    }


def test_no_field_name_even_suggests_a_value(tmp_path) -> None:
    add_source(tmp_path, _source())

    [stored] = json.loads(sources_path(tmp_path).read_text(encoding="utf-8"))["sources"]
    for field in stored:
        assert field not in ("key", "api_key", "secret", "token", "password")


@needs_keychain
def test_a_stored_key_does_not_appear_in_the_registry_file(tmp_path) -> None:
    """The end-to-end version: put a real key in the Keychain, then look."""
    account = f"ontologylab.test.{uuid.uuid4().hex[:12]}"
    write_key(account, SECRET)
    try:
        add_source(tmp_path, _source(keychain_account=account))

        raw = sources_path(tmp_path).read_text(encoding="utf-8")
        assert SECRET not in raw
        assert account in raw, "only the reference is stored"
    finally:
        delete_key(account)


def test_the_env_fallback_stores_only_the_variable_name(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setenv("ELSEVIER_API_KEY", SECRET)
    add_source(tmp_path, _source(keychain_account="", api_key_env="ELSEVIER_API_KEY"))

    raw = sources_path(tmp_path).read_text(encoding="utf-8")
    assert SECRET not in raw
    assert "ELSEVIER_API_KEY" in raw


def test_the_public_view_reports_presence_and_nothing_else(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setenv("ELSEVIER_API_KEY", SECRET)
    source = _source(keychain_account="", api_key_env="ELSEVIER_API_KEY")

    public = source_public(source)

    assert public["key_present"] is True
    assert SECRET not in json.dumps(public)


def test_presence_is_computed_not_assumed(tmp_path, monkeypatch) -> None:
    """A registry entry whose key was deleted must read as disconnected.

    Reporting "connected" from the registry alone would tell the user their
    journal access works right up until a research run silently fails.
    """
    monkeypatch.delenv("ELSEVIER_API_KEY", raising=False)
    source = _source(keychain_account="", api_key_env="ELSEVIER_API_KEY")

    assert source_public(source)["key_present"] is False


# --------------------------------------------------------------------------
# Validation
# --------------------------------------------------------------------------


def test_a_source_with_no_reference_at_all_is_refused() -> None:
    """It could never resolve, and would sit in the UI unfixable."""
    with pytest.raises(SourceError):
        validate_source(_source(keychain_account="", api_key_env=""))


@pytest.mark.parametrize(
    "account",
    ["Upper", "has space", "../escape", "a/b", "x" * 65, "", "-leading"],
)
def test_a_malformed_keychain_account_is_refused(account) -> None:
    """The account name is passed to `security` in argv."""
    if account == "":
        pytest.skip("empty means 'use the env fallback', covered separately")
    with pytest.raises(SourceError):
        validate_source(_source(keychain_account=account))


@pytest.mark.parametrize("env", ["lower", "has space", "1LEADING", "a-b"])
def test_a_malformed_env_var_name_is_refused(env) -> None:
    with pytest.raises(SourceError):
        validate_source(_source(keychain_account="", api_key_env=env))


def test_an_unknown_role_is_refused() -> None:
    with pytest.raises(SourceError):
        validate_source(_source(role="not-a-role"))


def test_the_shipped_role_validates() -> None:
    for role in SOURCE_ROLES:
        validate_source(_source(role=role))


# --------------------------------------------------------------------------
# Registry mechanics (mirrors providers.py, so mirror its tests)
# --------------------------------------------------------------------------


def test_a_missing_registry_is_an_empty_list_not_an_error(tmp_path) -> None:
    assert load_sources(tmp_path) == []


def test_a_corrupt_registry_does_not_block_the_open_sources(tmp_path) -> None:
    """Losing publisher access must not also lose the five keyless ones."""
    sources_path(tmp_path).parent.mkdir(parents=True, exist_ok=True)
    sources_path(tmp_path).write_text("{not json", encoding="utf-8")

    assert load_sources(tmp_path) == []


def test_one_malformed_entry_does_not_sink_the_others(tmp_path) -> None:
    sources_path(tmp_path).parent.mkdir(parents=True, exist_ok=True)
    sources_path(tmp_path).write_text(
        json.dumps({"sources": [{"nope": 1}, _source().to_dict()]}),
        encoding="utf-8",
    )

    loaded = load_sources(tmp_path)

    assert [s.id for s in loaded] == ["journals"]


def test_adding_the_same_id_twice_replaces_rather_than_duplicates(
    tmp_path,
) -> None:
    add_source(tmp_path, _source(label="first"))
    add_source(tmp_path, _source(label="second"))

    loaded = load_sources(tmp_path)

    assert len(loaded) == 1
    assert loaded[0].label == "second"


def test_removing_reports_whether_anything_was_removed(tmp_path) -> None:
    add_source(tmp_path, _source())

    assert remove_source(tmp_path, "journals") is True
    assert remove_source(tmp_path, "journals") is False
    assert get_source(tmp_path, "journals") is None


@needs_keychain
def test_removing_a_source_leaves_the_keychain_item_alone(tmp_path) -> None:
    """Deleting a config row must not destroy a credential.

    They are different decisions and should not be one click.
    """
    account = f"ontologylab.test.{uuid.uuid4().hex[:12]}"
    write_key(account, SECRET)
    try:
        add_source(tmp_path, _source(keychain_account=account))

        remove_source(tmp_path, "journals")

        assert read_key(account) == SECRET
    finally:
        delete_key(account)


def test_the_write_is_atomic(tmp_path) -> None:
    """A half-written registry would fail-soft to empty and lose everything."""
    add_source(tmp_path, _source())

    leftovers = list(tmp_path.glob("*.tmp"))

    assert not leftovers, f"a temp file survived the write: {leftovers}"
    assert load_sources(tmp_path)


# --------------------------------------------------------------------------
# Keychain access
# --------------------------------------------------------------------------


@needs_keychain
def test_a_key_round_trips_through_the_real_keychain() -> None:
    account = f"ontologylab.test.{uuid.uuid4().hex[:12]}"
    try:
        write_key(account, SECRET)

        assert read_key(account) == SECRET
    finally:
        delete_key(account)


@needs_keychain
def test_a_long_key_round_trips_intact() -> None:
    """The transport question, settled by measurement.

    `-w` with the value on stdin stored an EMPTY password at every length
    from 32 to 1024 bytes — silently. argv was correct at all of them. A key
    that round-trips to nothing authenticates as garbage with nothing in any
    log to explain it, so this locks the working transport in place.
    """
    account = f"ontologylab.test.{uuid.uuid4().hex[:12]}"
    long_key = "k" * 512
    try:
        write_key(account, long_key)

        assert read_key(account) == long_key
    finally:
        delete_key(account)


@needs_keychain
def test_writing_twice_replaces_rather_than_duplicating() -> None:
    account = f"ontologylab.test.{uuid.uuid4().hex[:12]}"
    try:
        write_key(account, "first-value")
        write_key(account, "second-value")

        assert read_key(account) == "second-value"
    finally:
        delete_key(account)


def test_a_replacement_never_modifies_an_existing_item(monkeypatch) -> None:
    """The regression that put a password dialog on the user's screen.

    `add-generic-password -U -T /usr/bin/security` against an item that
    already exists is an ACL *modification*, and macOS demands the login
    password for it: "security wants to change the access permissions of the
    item". Creating a fresh item with the same `-T` raises nothing.

    Rotating a key is the single most common reason to write twice, so the
    prompt landed on the most ordinary path there is. It also explained an
    earlier 15-second write timeout that had been dismissed as a transient.

    This asserts the shape of the command rather than the absence of a
    dialog, because a test cannot see a dialog — it can only hang, which is
    exactly how this was discovered.
    """
    calls = []
    monkeypatch.setattr(keychain, "keychain_available", lambda: True)
    monkeypatch.setattr(
        keychain.subprocess, "run",
        lambda argv, **k: calls.append(list(argv))
        or subprocess.CompletedProcess(argv, 0, "", ""),
    )
    monkeypatch.setattr(keychain, "read_key", lambda _acct: "new-value")

    write_key("ontologylab.test.rotate", "new-value")

    adds = [c for c in calls if "add-generic-password" in c]
    assert adds, "nothing was written"
    for argv in adds:
        assert "-U" not in argv, (
            "-U turns a create into an ACL modification, which prompts"
        )
    assert any("delete-generic-password" in c for c in calls), (
        "without deleting first, a second write has nothing to replace"
    )


def test_a_failed_replacement_puts_the_old_key_back(monkeypatch) -> None:
    """Deleting first means a failed create would otherwise lose the key.

    Rotation is precisely when that happens: the user has a working key,
    asks to replace it, the write fails, and they are left with nothing.
    """
    restored = []
    monkeypatch.setattr(keychain, "keychain_available", lambda: True)
    monkeypatch.setattr(keychain, "read_key", lambda _acct: "old-value")
    monkeypatch.setattr(keychain, "delete_key", lambda _acct: True)
    monkeypatch.setattr(
        keychain, "_restore", lambda acct, value: restored.append((acct, value))
    )
    monkeypatch.setattr(
        keychain.subprocess, "run",
        lambda *a, **k: subprocess.CompletedProcess(a, 1, "", "refused"),
    )

    with pytest.raises(KeychainError):
        write_key("ontologylab.test.rollback", "new-value")

    assert restored == [("ontologylab.test.rollback", "old-value")]


@needs_keychain
def test_rotation_round_trips_against_the_real_keychain() -> None:
    """Five rotations in a row, which is what raised the dialog before."""
    account = f"ontologylab.test.{uuid.uuid4().hex[:12]}"
    try:
        for n in range(5):
            write_key(account, f"value-{n}")

        assert read_key(account) == "value-4"
    finally:
        delete_key(account)


def test_a_missing_item_reads_as_none_not_an_exception() -> None:
    """"Not connected" is a normal state, not a failure."""
    assert read_key(f"ontologylab.test.absent.{uuid.uuid4().hex[:12]}") is None


def test_an_empty_key_is_refused_before_any_subprocess(monkeypatch) -> None:
    """Storing "" would report connected and resolve to nothing.

    Asserting only that it raises is not enough: the read-back check raises
    for an empty key anyway, so the guard could be deleted and this would
    still pass — while leaving a junk item with an empty password in the
    user's Keychain on the way through. Same discipline as the account
    check: refuse before `security` is ever invoked.
    """
    calls = []
    monkeypatch.setattr(keychain, "keychain_available", lambda: True)
    monkeypatch.setattr(
        keychain.subprocess, "run",
        lambda *a, **k: calls.append(a) or pytest.fail("subprocess was reached"),
    )

    for empty in ("", "   ", "\n\t"):
        with pytest.raises(KeychainError):
            write_key("ontologylab.test.empty", empty)
    assert not calls


def test_a_malformed_account_never_reaches_the_subprocess(monkeypatch) -> None:
    """The account name goes into argv; validate before, not after."""
    calls = []
    monkeypatch.setattr(
        keychain.subprocess, "run",
        lambda *a, **k: calls.append(a) or pytest.fail("subprocess was reached"),
    )

    assert read_key("../../etc/passwd") is None
    with pytest.raises(KeychainError):
        write_key("has space", "value")
    assert not calls


def test_a_keychain_failure_message_never_quotes_the_key(monkeypatch) -> None:
    """The command line contains the key, so the error must not echo it."""
    monkeypatch.setattr(keychain, "keychain_available", lambda: True)
    monkeypatch.setattr(
        keychain.subprocess, "run",
        lambda *a, **k: subprocess.CompletedProcess(a, 1, "", f"failed on {SECRET}"),
    )

    with pytest.raises(KeychainError) as excinfo:
        write_key("ontologylab.test.fail", SECRET)

    assert SECRET not in str(excinfo.value)


def test_a_prompt_that_blocks_becomes_an_error_not_a_hang(monkeypatch) -> None:
    """`security` blocks forever on a GUI authorization prompt.

    A request thread parked on one would hang the dashboard, so the timeout
    is the contract and this pins it.
    """
    def _hang(*a, **k):
        raise subprocess.TimeoutExpired(cmd="security", timeout=15)

    monkeypatch.setattr(keychain, "keychain_available", lambda: True)
    monkeypatch.setattr(keychain.subprocess, "run", _hang)

    assert read_key("ontologylab.test.hang") is None  # reads degrade
    with pytest.raises(KeychainError):  # writes report
        write_key("ontologylab.test.hang", "value")


def test_a_write_that_timed_out_but_landed_is_reported_as_success(
    monkeypatch,
) -> None:
    """Observed once during development: `securityd` blew the timeout on a
    write that had in fact stored the value.

    Calling that a failure sends the user to re-enter a key that is already
    there, and leaves them believing journal access is unconfigured while it
    works. So the read-back, not the clock, decides.
    """
    monkeypatch.setattr(keychain, "keychain_available", lambda: True)

    def _slow_but_effective(*a, **k):
        raise subprocess.TimeoutExpired(cmd="security", timeout=15)

    monkeypatch.setattr(keychain.subprocess, "run", _slow_but_effective)
    monkeypatch.setattr(keychain, "read_key", lambda _acct: SECRET)

    write_key("ontologylab.test.slow", SECRET)  # must not raise


def test_a_write_that_exits_zero_without_storing_is_still_an_error(
    monkeypatch,
) -> None:
    """A zero exit was measured not to mean "stored".

    The rejected stdin transport exited 0 and stored an empty password at
    every length from 32 to 1024 bytes. Trusting the exit status is exactly
    how that would have shipped unnoticed.
    """
    monkeypatch.setattr(keychain, "keychain_available", lambda: True)
    monkeypatch.setattr(
        keychain.subprocess, "run",
        lambda *a, **k: subprocess.CompletedProcess(a, 0, "", ""),
    )
    monkeypatch.setattr(keychain, "read_key", lambda _acct: None)  # nothing stored

    with pytest.raises(KeychainError) as excinfo:
        write_key("ontologylab.test.silent", SECRET)

    assert SECRET not in str(excinfo.value)


def test_a_write_that_stored_the_wrong_value_is_an_error(monkeypatch) -> None:
    """Truncation would look like this — a stored value that is a prefix.

    The long key is deliberate: `SECRET` is 41 characters, so a naive
    `SECRET[:128]` here would equal `SECRET` and the test would pass while
    asserting nothing.
    """
    long_key = "k" * 300
    monkeypatch.setattr(keychain, "keychain_available", lambda: True)
    monkeypatch.setattr(
        keychain.subprocess, "run",
        lambda *a, **k: subprocess.CompletedProcess(a, 0, "", ""),
    )
    monkeypatch.setattr(keychain, "read_key", lambda _acct: long_key[:128])

    with pytest.raises(KeychainError):
        write_key("ontologylab.test.truncated", long_key)


def test_a_read_never_raises_whatever_the_platform_does(monkeypatch) -> None:
    def _explode(*a, **k):
        raise OSError("no such binary")

    monkeypatch.setattr(keychain, "keychain_available", lambda: True)
    monkeypatch.setattr(keychain.subprocess, "run", _explode)

    assert read_key("ontologylab.test.boom") is None


def test_without_the_security_binary_everything_degrades(monkeypatch) -> None:
    """Non-macOS is a capability question, not an error."""
    monkeypatch.setattr(keychain.shutil, "which", lambda _name: None)

    assert keychain_available() is False
    assert read_key("ontologylab.literature") is None
    assert delete_key("ontologylab.literature") is False
    with pytest.raises(KeychainError):
        write_key("ontologylab.literature", "value")


# --------------------------------------------------------------------------
# The documented fallback
# --------------------------------------------------------------------------


def test_the_env_fallback_resolves_when_there_is_no_keychain_item(
    monkeypatch,
) -> None:
    """The plan's stated retreat, kept live rather than written down."""
    monkeypatch.setattr(keychain, "keychain_available", lambda: False)
    monkeypatch.setenv("ELSEVIER_API_KEY", SECRET)

    assert resolve_key("ontologylab.literature", "ELSEVIER_API_KEY") == SECRET


@needs_keychain
def test_the_keychain_wins_over_a_stale_environment_variable(
    monkeypatch,
) -> None:
    """A machine with both configured chose the Keychain deliberately."""
    account = f"ontologylab.test.{uuid.uuid4().hex[:12]}"
    monkeypatch.setenv("ELSEVIER_API_KEY", "stale-leftover")
    try:
        write_key(account, SECRET)

        assert resolve_key(account, "ELSEVIER_API_KEY") == SECRET
    finally:
        delete_key(account)


def test_neither_configured_resolves_to_none(monkeypatch) -> None:
    monkeypatch.delenv("ELSEVIER_API_KEY", raising=False)

    assert resolve_key("", "") is None
    assert resolve_key("", "ELSEVIER_API_KEY") is None


def test_a_whitespace_only_env_value_counts_as_absent(monkeypatch) -> None:
    monkeypatch.setattr(keychain, "keychain_available", lambda: False)
    monkeypatch.setenv("ELSEVIER_API_KEY", "   ")

    assert resolve_key("", "ELSEVIER_API_KEY") is None


def test_resolve_source_key_uses_both_references(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(keychain, "keychain_available", lambda: False)
    monkeypatch.setenv("ELSEVIER_API_KEY", SECRET)
    source = _source(api_key_env="ELSEVIER_API_KEY")

    assert resolve_source_key(source) == SECRET


def test_the_collect_guard_still_covers_the_new_registry_file(tmp_path) -> None:
    """C1 and step 4 meet here.

    `sources.json` was named in C1's rationale as the file worth stealing.
    Now that it exists, the guard that refuses to collect it has to actually
    cover it.
    """
    from ontologylab.connectors.allowlist import NotAllowlisted, check_collect_file

    data_dir = tmp_path / "data"
    add_source(data_dir, _source())

    with pytest.raises(NotAllowlisted):
        check_collect_file(str(sources_path(data_dir)), data_dir)


def test_the_registry_lives_in_the_gitignored_data_area(tmp_path) -> None:
    assert sources_path(tmp_path) == tmp_path / "sources.json"
    assert sources_path(tmp_path).parent == tmp_path
