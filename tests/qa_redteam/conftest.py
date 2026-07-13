"""QA red-team scratch suite for G001 (paper_api connector).

THROWAWAY QA code — not part of the product test-suite contract.

- Hard network guard: any un-monkeypatched socket-level fetch fails the test.
- CLI transcripts + case verdicts are dumped to
  ~/Documents/MUNI/artifacts/ultragoal-g001/ at session end.
"""

from __future__ import annotations

import pytest

from qa_redteam import qa_helpers


@pytest.fixture(autouse=True)
def _no_real_network(monkeypatch):
    """Any code path that reaches a real socket-level fetch fails loudly."""

    def _boom(*args, **kwargs):  # pragma: no cover - must never be reached
        raise AssertionError("REAL NETWORK I/O ATTEMPTED during QA red-team run")

    import ontologylab.connectors.paper_api as pa
    import ontologylab.connectors.web_crawl as wc

    monkeypatch.setattr(pa, "urlopen", _boom)
    monkeypatch.setattr(wc, "_fetch_url", _boom, raising=False)


def pytest_sessionfinish(session, exitstatus):
    qa_helpers.dump_artifacts()
