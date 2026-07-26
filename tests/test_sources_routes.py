"""The one endpoint that receives a secret, and every way it could leak it.

`POST /api/sources` takes a publisher API key. Everything else in this server
has only ever handled data the user could already read, so this is the first
request whose *body* is worth protecting, not just its response.

The measured surprise: FastAPI's default 422 carries the offending value back
in an `input` field. Submitting `{"key": "<secret>"}` without the required
`id` answered with the whole body echoed. `SecretStr` does not help — masking
happens after validation and the error is raised before it. So `create_app`
strips `input`/`ctx` from every validation error, and these tests hold that
in place for every shape of malformed request, not just the one that was
found first.

Keychain-touching tests are redirected to a test-only service name, so a
failure here can never leave junk in the real `ontologylab` service.
"""

from __future__ import annotations

import json
import subprocess
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from ontologylab import keychain
from ontologylab.keychain import keychain_available, read_key, write_key
from ontologylab.paths import sources_path
from ontologylab.server import routes
from ontologylab.server.app import create_app

SECRET = "ELS-key-that-must-never-come-back-9f3a"
TEST_SERVICE = "ontologylab-pytest-routes"
_REAL_RUN = subprocess.run

needs_keychain = pytest.mark.skipif(
    not keychain_available(), reason="no macOS `security` binary"
)


@pytest.fixture(autouse=True)
def _isolated_keychain(monkeypatch):
    monkeypatch.setattr(keychain, "KEYCHAIN_SERVICE", TEST_SERVICE)
    yield
    if not keychain_available():
        return
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


def _client(tmp_path: Path) -> TestClient:
    data_dir = tmp_path / "data"
    routes.attach_data_dir(data_dir)
    return TestClient(create_app(data_dir=data_dir))


def _connect(client: TestClient, **overrides) -> dict:
    payload = {
        "id": "journals",
        "role": "literature",
        "label": "저널 접근",
        "key": SECRET,
        **overrides,
    }
    return client.post("/api/sources", json=payload).json()


# --------------------------------------------------------------------------
# The key never comes back
# --------------------------------------------------------------------------


@needs_keychain
def test_connecting_returns_presence_not_the_key(tmp_path) -> None:
    client = _client(tmp_path)

    body = _connect(client)

    assert body["ok"] is True
    assert body["source"]["key_present"] is True
    assert SECRET not in json.dumps(body)


@needs_keychain
def test_listing_never_carries_the_key(tmp_path) -> None:
    client = _client(tmp_path)
    _connect(client)

    body = client.get("/api/sources").json()

    assert body["sources"][0]["key_present"] is True
    assert SECRET not in json.dumps(body)


@needs_keychain
def test_the_key_is_not_written_to_the_registry_file(tmp_path) -> None:
    """The registry lives in `data/`, which was found syncing to iCloud."""
    client = _client(tmp_path)
    _connect(client)

    raw = sources_path(tmp_path / "data").read_text(encoding="utf-8")

    assert SECRET not in raw
    assert "ontologylab.literature" in raw, "only the reference is stored"


@needs_keychain
def test_the_key_reaches_the_keychain_under_the_role_bundle(tmp_path) -> None:
    """"Connect journal access" should not ask the user for an account name."""
    client = _client(tmp_path)

    _connect(client, keychain_account="")

    assert read_key("ontologylab.literature") == SECRET


@needs_keychain
def test_no_provenance_record_mentions_the_key(tmp_path) -> None:
    """Provenance is append-only and re-read by `cost_summary` forever."""
    client = _client(tmp_path)
    _connect(client)

    for path in (tmp_path / "data").rglob("*.json*"):
        assert SECRET not in path.read_text(encoding="utf-8"), path


# --------------------------------------------------------------------------
# Malformed requests must not echo the body (the measured defect)
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("name", "payload"),
    [
        ("missing required id", {"key": SECRET}),
        ("body is not an object", [{"id": "x", "key": SECRET}]),
        ("key has the wrong type", {"id": "x", "key": {"nested": SECRET}}),
        ("another field wrong type", {"id": 5, "key": SECRET}),
        ("key is a list", {"id": "x", "key": [SECRET]}),
        ("extra junk alongside", {"id": 5, "key": SECRET, "role": ["x"]}),
    ],
)
def test_a_rejected_request_never_echoes_the_key(tmp_path, name, payload) -> None:
    client = _client(tmp_path)

    response = client.post("/api/sources", json=payload)

    assert SECRET not in response.text, f"{name}: the key came back"


def test_a_validation_error_still_says_which_field_was_wrong(tmp_path) -> None:
    """Redaction must not turn a fixable 422 into an unactionable one."""
    client = _client(tmp_path)

    body = client.post("/api/sources", json={"key": SECRET}).json()

    assert body["detail"][0]["loc"] == ["body", "id"]
    assert "required" in body["detail"][0]["msg"].lower()


def test_the_key_field_has_no_validator_that_could_quote_it() -> None:
    """`msg` is the one part of a 422 that cannot be stripped.

    It is also the one part a custom validator writes: raising
    `ValueError(f"bad: {value}")` inside a `field_validator` puts the value
    straight into `msg`, where `input`/`ctx` stripping cannot reach it. The
    rule for any field carrying a secret is therefore that it has no
    validator and no `Field` constraint at all; its shape is checked inside
    the route, where the message is written by hand.
    """
    from ontologylab.server.schemas import SourceCreate

    decorators = SourceCreate.__pydantic_decorators__
    guarded = set()
    for group in (decorators.field_validators, decorators.field_serializers):
        for info in group.values():
            guarded.update(getattr(info, "info", info).fields or ())
    assert "key" not in guarded, (
        "a validator on `key` can put the key into a 422 `msg`, which is "
        "not strippable — validate it in the route instead"
    )

    field = SourceCreate.model_fields["key"]
    assert not field.metadata, (
        f"`key` carries constraints {field.metadata!r}; a failed constraint "
        "produces a 422 that echoes the value"
    )


def test_the_redaction_covers_other_endpoints_too(tmp_path) -> None:
    """It is an app-level handler, so a future secret-bearing route is
    covered before anyone remembers to think about it."""
    client = _client(tmp_path)

    response = client.post("/api/extract", json={"engine": ["not-a-string"]})

    assert response.status_code == 422
    assert "input" not in response.text
    assert "not-a-string" not in response.text


# --------------------------------------------------------------------------
# Gate failures are typed and quiet
# --------------------------------------------------------------------------


def test_an_oversized_key_is_refused_without_echoing_it(tmp_path) -> None:
    client = _client(tmp_path)
    huge = "k" * 5000

    response = client.post(
        "/api/sources", json={"id": "journals", "role": "literature", "key": huge}
    )

    assert response.status_code == 200, "a gate failure is not a 4xx here"
    assert response.json()["error_kind"] == "rejected"
    assert huge not in response.text


def test_a_source_with_no_key_and_no_reference_is_refused(tmp_path) -> None:
    client = _client(tmp_path)

    body = client.post(
        "/api/sources", json={"id": "journals", "role": "literature"}
    ).json()

    assert body["ok"] is False
    assert body["error_kind"] == "rejected"


def test_an_unknown_role_is_refused(tmp_path) -> None:
    client = _client(tmp_path)

    body = _connect(client, role="not-a-role")

    assert body["error_kind"] == "rejected"


def test_a_keychain_failure_is_reported_without_the_key(
    tmp_path, monkeypatch
) -> None:
    """`security`'s command line contains the key, so its errors might too."""
    def _refuse(_account, _key):
        raise keychain.KeychainError(f"the Keychain refused: {SECRET}")

    monkeypatch.setattr(routes, "write_key", _refuse)
    monkeypatch.setattr(routes, "keychain_available", lambda: True)
    client = _client(tmp_path)

    response = client.post(
        "/api/sources",
        json={"id": "journals", "role": "literature", "key": SECRET},
    )

    assert response.json()["error_kind"] == "failed"
    assert SECRET not in response.text


def test_a_machine_without_a_keychain_says_so_usefully(
    tmp_path, monkeypatch
) -> None:
    """The documented fallback has to be discoverable from the error."""
    monkeypatch.setattr(routes, "keychain_available", lambda: False)
    client = _client(tmp_path)

    body = _connect(client)

    assert body["error_kind"] == "unsupported"
    assert "api_key_env" in body["detail"]
    assert SECRET not in json.dumps(body)


def test_the_env_var_path_needs_no_keychain(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(routes, "keychain_available", lambda: False)
    monkeypatch.setenv("ELSEVIER_API_KEY", SECRET)
    client = _client(tmp_path)

    body = client.post(
        "/api/sources",
        json={"id": "journals", "role": "literature",
              "api_key_env": "ELSEVIER_API_KEY"},
    ).json()

    assert body["ok"] is True
    assert body["source"]["key_present"] is True
    assert SECRET not in json.dumps(body)


# --------------------------------------------------------------------------
# Disconnecting vs forgetting
# --------------------------------------------------------------------------


@needs_keychain
def test_disconnecting_leaves_the_key_and_says_so(tmp_path) -> None:
    """Deleting a config row must not silently destroy a credential."""
    client = _client(tmp_path)
    _connect(client)

    body = client.delete("/api/sources/journals").json()

    assert body["removed"] is True
    assert body["key_retained"] is True, "the UI needs to offer the second step"
    assert read_key("ontologylab.literature") == SECRET


@needs_keychain
def test_forgetting_the_key_actually_removes_it(tmp_path) -> None:
    client = _client(tmp_path)
    _connect(client)

    body = client.delete("/api/sources/journals/key").json()

    assert body["forgotten"] is True
    assert read_key("ontologylab.literature") is None


@needs_keychain
def test_a_forgotten_key_reads_back_as_disconnected(tmp_path) -> None:
    """Presence is resolved, not remembered — the row is still there."""
    client = _client(tmp_path)
    _connect(client)
    client.delete("/api/sources/journals/key")

    listed = client.get("/api/sources").json()["sources"]

    assert listed[0]["id"] == "journals"
    assert listed[0]["key_present"] is False


def test_forgetting_a_key_that_is_not_there_is_a_plain_no(tmp_path) -> None:
    client = _client(tmp_path)

    body = client.delete("/api/sources/nope/key").json()

    assert body["ok"] is True
    assert body["forgotten"] is False


def test_disconnecting_an_unknown_source_is_not_an_error(tmp_path) -> None:
    client = _client(tmp_path)

    body = client.delete("/api/sources/nope").json()

    assert body["ok"] is True
    assert body["removed"] is False


@needs_keychain
def test_reconnecting_replaces_the_stored_key(tmp_path) -> None:
    """Rotating a key is the most common reason to come back here."""
    client = _client(tmp_path)
    _connect(client)
    rotated = "ELS-rotated-value-4d19"

    _connect(client, key=rotated)

    assert read_key("ontologylab.literature") == rotated


@needs_keychain
def test_reconnecting_does_not_duplicate_the_registry_row(tmp_path) -> None:
    client = _client(tmp_path)
    _connect(client)
    _connect(client, label="renamed")

    listed = client.get("/api/sources").json()["sources"]

    assert len(listed) == 1
    assert listed[0]["label"] == "renamed"


# --------------------------------------------------------------------------
# C1 still covers the file this created
# --------------------------------------------------------------------------


@needs_keychain
def test_the_registry_cannot_be_collected_as_a_document(tmp_path) -> None:
    """C1 named `sources.json` as the file worth stealing. It exists now."""
    client = _client(tmp_path)
    _connect(client)

    body = client.post(
        "/api/collect",
        json={"files": [str(sources_path(tmp_path / "data"))]},
    ).json()

    assert body["ok"] is False
    assert body["error_kind"] == "rejected"
