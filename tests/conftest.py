"""Shared fixtures for ontologylab tests. Everything runs offline (mock engine)."""

from __future__ import annotations

import os
import threading
import time

import pytest
from starlette.testclient import TestClient as _StarletteTestClient

from ontologylab.kgstore import KGStore
from tests.factories import make_entity, make_relation

# Test-only default credential. Production has no SESSION_OPTIONAL switch;
# existing TestClient callers pick up the process token minted by create_app.
# Auth tests that need a bare client must call drop_test_session().
_SESSION_HEADER = "X-OntologyLab-Session"
_SESSION_COOKIE = "ontologylab_session"
_orig_testclient_init = _StarletteTestClient.__init__


def _authed_testclient_init(self, app, *args, **kwargs):  # type: ignore[no-untyped-def]
    headers = dict(kwargs.get("headers") or {})
    already = any(key.lower() == _SESSION_HEADER.lower() for key in headers)
    token = getattr(getattr(app, "state", None), "session_token", None)
    if token and not already:
        headers[_SESSION_HEADER] = token
        kwargs["headers"] = headers
    # Default the ASGI peer to loopback so tests that set base_url to
    # http://127.0.0.1 satisfy the Host/peer coupling. Attack cases pass
    # client= explicitly.
    kwargs.setdefault("client", ("127.0.0.1", 50000))
    _orig_testclient_init(self, app, *args, **kwargs)


_StarletteTestClient.__init__ = _authed_testclient_init  # type: ignore[method-assign]


def drop_test_session(client):
    """Remove the test-only default session header/cookie."""
    client.headers.pop(_SESSION_HEADER, None)
    try:
        client.cookies.delete(_SESSION_COOKIE)
    except (KeyError, AttributeError):
        client.cookies.pop(_SESSION_COOKIE, None)
    return client


@pytest.fixture(autouse=True)
def _never_touch_the_real_settings(monkeypatch, tmp_path):
    """No test may read or write the developer's own settings.json.

    Three separate times this suite overwrote it — once flipping
    `default_engine` from `claude` to `mock`, twice more from a mutation
    run — because `save_settings` defaulted to a machine-global path. The
    default is now the data directory, but "the default is safe" is a
    property one refactor can remove, so the guard is structural: every
    test gets its own location and the real one is not reachable from here.

    A test that genuinely needs the legacy path (there is one, for the
    upgrade fallback) monkeypatches `_legacy_settings_path` itself, which
    overrides this.
    """
    from ontologylab.server import settings as settings_mod

    sandbox = tmp_path / "_settings"
    sandbox.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(
        settings_mod, "_legacy_settings_path",
        lambda: sandbox / "legacy-settings.json", raising=True,
    )
    real = settings_mod._settings_path

    def guarded(data_dir=None):
        return real(sandbox if data_dir is None else data_dir)

    monkeypatch.setattr(settings_mod, "_settings_path", guarded, raising=True)


# The worker that steals a stub is the one that has not reached its first
# fetch yet, and that one finishes in milliseconds once scheduled. The budget
# only has to cover "finish what you already started".
# The worker that steals a stub is the one that has not reached its first call
# yet, and that one finishes in milliseconds once scheduled. The budget only
# has to cover "finish what you already started".
_JOB_JOIN_BUDGET_S = 10.0


@pytest.fixture(autouse=True)
def _never_boot_out_the_real_launchd(monkeypatch):
    """No test may reach the real `launchctl`.

    `uninstall_app` retires the legacy LaunchAgent, and its label
    `at.ontologylab.server` is a LIVE service on any machine that ran the old
    launcher — including this developer's, where it owns the server on port
    8799. A test that constructed the production adapter would boot out a real
    server, so the seam is replaced here rather than in each test: the guard is
    structural, exactly like the settings sandbox above.

    A test that wants to observe retirement injects its own fake afterwards and
    wins, because it patches the same name later. This stand-in reports the
    legacy service as absent — the normal state — so it keeps every existing
    uninstall test meaningful instead of failing it.
    """
    from scripts import internal_deployment

    class _AbsentLegacySystem:
        def launchctl(self, arguments: tuple[str, ...]) -> int:
            return 113  # launchd's "service not loaded"

        def process_exists(self, pid: int) -> bool:
            return False

        def terminate(self, pid: int) -> None:
            raise AssertionError(f"test tried to signal pid {pid}")

    monkeypatch.setattr(
        internal_deployment, "_retirement_system", _AbsentLegacySystem, raising=True
    )


@pytest.fixture(autouse=True)
def _no_job_thread_outlives_its_test(monkeypatch):
    """No job worker may still be running when the next test begins.

    ``JobRegistry.start`` spawns ``daemon=True`` threads and nothing joins
    them. Eight test files POST ``/api/research`` and return without waiting,
    which leaves a worker that has not yet reached its first fetch. The next
    test installs its own ``_http_get_text`` stub; the late worker resolves
    that name fresh and eats the stub belonging to the test now running.
    Measured 12/12 in a standalone race, and seen once in a full run as a
    ``StopIteration`` out of the two-item iterator in
    ``test_collect_same_doi_with_changed_abstract_creates_representation``.

    Workers are recorded as they start rather than discovered with
    ``threading.enumerate()`` at teardown, because that scan is itself a race:
    a worker that registers microseconds too late is never joined and then
    outlives several tests. Adding a ``print`` to the teardown was enough to
    make the bug disappear, which is how the race announced itself.

    Requesting ``monkeypatch`` is load-bearing, not decoration: it makes this
    fixture finalize *before* the patches come off, so a worker that wakes
    late still meets a stub rather than the real network.

    Not an assertion. A worker parked in a slow call cannot issue a *new*
    fetch, so it is not the thief, and failing tests over it would report a
    leak that cannot cause the bug this guard exists for.
    """
    started: list[threading.Thread] = []
    real_start = threading.Thread.start

    def _recording_start(self: threading.Thread) -> None:
        if self.name.startswith("ontologylab-"):
            started.append(self)
        real_start(self)

    monkeypatch.setattr(threading.Thread, "start", _recording_start)
    yield
    deadline = time.monotonic() + _JOB_JOIN_BUDGET_S
    for thread in started:
        # join() waits on the thread's own exit, not on a guessed duration,
        # so a worker that was merely unscheduled costs microseconds.
        thread.join(max(0.0, deadline - time.monotonic()))


@pytest.fixture(autouse=True, scope="session")
def _allow_testclient_host():
    """Let the loopback Host guard accept FastAPI TestClient's 'testserver'.

    The server rejects non-loopback Host headers (DNS-rebinding defense); the
    ASGI TestClient drives the app as host 'testserver', so allowlist it for
    the test session only. Production stays loopback-only.
    """
    prior = os.environ.get("ONTOLOGYLAB_ALLOWED_HOSTS")
    os.environ["ONTOLOGYLAB_ALLOWED_HOSTS"] = "testserver"
    try:
        yield
    finally:
        if prior is None:
            os.environ.pop("ONTOLOGYLAB_ALLOWED_HOSTS", None)
        else:
            os.environ["ONTOLOGYLAB_ALLOWED_HOSTS"] = prior

SAMPLE_TEXT = (
    "# Service notes\n\n"
    "The ApiGateway forwards requests to the RateLimiter before they reach the\n"
    "OrderService. The RateLimiter implements the TokenBucketAlgorithm and stores\n"
    "counters in the SessionCache. The OrderService writes into the OrderDatabase.\n"
)


@pytest.fixture()
def store(tmp_path):
    s = KGStore.open(tmp_path / "kg.sqlite")
    yield s
    s.close()


@pytest.fixture()
def doc(store):
    document, created = store.insert_document(
        source_kind="upload",
        source_uri="file:///notes.md",
        title="notes",
        raw_text=SAMPLE_TEXT,
        content_hash="sha256:test",
    )
    assert created
    return document


def insert(store: KGStore, doc, entities, relations=()):
    return store.insert_proposed(
        entities,
        relations,
        source_doc_id=doc.id,
        extractor_engine="mock",
        extractor_model=None,
        prompt_version="extract-v1",
    )


def default_schema_dict():
    """Schema shape expected by parse_and_validate_extraction / prompt builder."""
    from ontologylab.ontology_schema import (
        DEFAULT_ENTITY_TYPES,
        DEFAULT_RELATION_TYPES,
    )

    return {
        "entity_types": [
            {"name": name, "description": desc, "attributes": attrs}
            for name, (desc, attrs) in DEFAULT_ENTITY_TYPES.items()
        ],
        "relation_types": [
            {
                "name": name,
                "description": desc,
                "domain_type": domain,
                "range_type": range_,
                "directed": directed,
            }
            for name, (desc, domain, range_, directed) in DEFAULT_RELATION_TYPES.items()
        ],
    }
