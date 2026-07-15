"""Round-2 QA scratch suite conftest: hard network guard + artifact dump.

THROWAWAY QA code — not part of the product test-suite contract.
"""

from __future__ import annotations

import pytest

from qa_round2 import r2_helpers


@pytest.fixture(autouse=True)
def _no_real_network(monkeypatch):
    """Any code path that reaches a fetch seam un-monkeypatched fails loudly."""

    def _boom(*args, **kwargs):  # pragma: no cover - must never be reached
        raise AssertionError("REAL NETWORK I/O ATTEMPTED during round-2 QA run")

    import ontologylab.connectors.paper_api as pa
    import ontologylab.connectors.web_crawl as wc

    monkeypatch.setattr(pa, "urlopen", _boom)
    monkeypatch.setattr(pa, "_http_get_text", _boom)
    monkeypatch.setattr(wc, "_fetch_url", _boom)


@pytest.fixture()
def net_trap(monkeypatch):
    """Booby-trap BOTH fetch seams with counting AssertionError traps (F2)."""
    import ontologylab.connectors.paper_api as pa
    import ontologylab.connectors.web_crawl as wc

    trips = {"paper": 0, "web": 0}

    def _paper_trap(url):
        trips["paper"] += 1
        raise AssertionError(f"paper_api._http_get_text reached: {url!r}")

    def _web_trap(url):
        trips["web"] += 1
        raise AssertionError(f"web_crawl._fetch_url reached: {url!r}")

    monkeypatch.setattr(pa, "_http_get_text", _paper_trap)
    monkeypatch.setattr(wc, "_fetch_url", _web_trap)
    return trips


def pytest_sessionfinish(session, exitstatus):
    r2_helpers.dump_artifacts()
