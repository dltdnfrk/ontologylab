"""The shared extraction loop: budgets, refusals, and abort actually bite.

`main._extract_async` and `jobs._extract_async` were near-identical copies of
this loop; a third caller would have made three. They now both call
`run_extraction`, so the behaviours below are tested once and hold for every
caller — which is the point of extracting it.

These cover ground the suite did not. A mutation run showed the budget check,
the parse-rejection swallow, and the abort hook could each be deleted with all
472 tests still passing. The parse-rejection path even carried a comment
naming it an acceptance criterion, with nothing enforcing it.
"""

from __future__ import annotations

import asyncio
import hashlib
from pathlib import Path
from types import SimpleNamespace

from ontologylab.engines import EngineError, MockEngine
from ontologylab.extractor import TOTALS_KEYS, run_extraction, unprocessed_doc_ids
from ontologylab.kgstore import KGStore
from ontologylab.provenance import Provenance
from ontologylab.safety import Caps

TEXT = (
    "The PaymentGateway validates cards through the FraudDetector. "
    "The FraudDetector consults the RiskModel for scoring. "
    "The RiskModel reads features from the FeatureStore."
)


def _document(store: KGStore, text: str, name: str):
    doc, _ = store.insert_document(
        source_kind="upload",
        source_uri=f"file:///{name}",
        title=name,
        raw_text=text,
        content_hash="sha256:" + hashlib.sha256(text.encode()).hexdigest(),
    )
    return doc


def _store(tmp_path: Path) -> KGStore:
    store = KGStore.open(tmp_path / "kg.sqlite")
    _document(store, TEXT, "notes.md")
    return store


def _caps(*, time_budget: float = 0.0, max_calls: int = 0) -> Caps:
    return Caps(
        SimpleNamespace(
            iterations=0,
            time_budget_s=time_budget,
            max_engine_calls=max_calls,
        )
    )


class _Recorder:
    """Collect what a caller would print and accumulate."""

    def __init__(self) -> None:
        self.lines: list[str] = []
        self.totals = dict.fromkeys(TOTALS_KEYS, 0)

    def progress(self, message: str) -> None:
        self.lines.append(message)

    def stats(self, stats: dict[str, int]) -> None:
        for key in self.totals:
            self.totals[key] += stats[key]


class _CountingEngine:
    """A MockEngine that reports how many times it was actually called."""

    def __init__(self) -> None:
        self._inner = MockEngine()
        self.calls = 0

    async def generate(self, prompt: str, *, model: str | None = None):
        self.calls += 1
        return await self._inner.generate(prompt, model=model)


class _BrokenEngine:
    """Answers with text that is not a valid extraction payload."""

    def __init__(self) -> None:
        self.calls = 0

    async def generate(self, prompt: str, *, model: str | None = None):
        self.calls += 1
        return "not a fenced json block at all", {"calls": 1, "elapsed": 0.0}


class _FailingEngine:
    """Raises the way a CLI engine does when its subprocess fails."""

    def __init__(self) -> None:
        self.calls = 0

    async def generate(self, prompt: str, *, model: str | None = None):
        self.calls += 1
        raise EngineError("engine exploded")


def _extract(
    store: KGStore,
    engine,
    caps: Caps,
    tmp_path: Path,
    recorder: _Recorder,
    doc_ids: list[str] | None = None,
    **kwargs,
) -> str:
    """Drive the loop.

    This repo runs coroutines with `asyncio.run` rather than a plugin, so that
    convention lives here instead of at every call site.
    """
    return asyncio.run(
        run_extraction(
            store,
            engine,
            Provenance(str(tmp_path / "job"), seed=0),
            caps,
            unprocessed_doc_ids(store) if doc_ids is None else doc_ids,
            extractor_engine="mock",
            extractor_model=None,
            on_progress=recorder.progress,
            on_stats=recorder.stats,
            **kwargs,
        )
    )


# --------------------------------------------------------------------------
# The happy path, so every failure below is attributable
# --------------------------------------------------------------------------


def test_a_document_is_extracted_and_its_stats_reported(tmp_path) -> None:
    store = _store(tmp_path)
    recorder = _Recorder()
    try:
        stopped = _extract(store, MockEngine(), _caps(), tmp_path, recorder)
    finally:
        store.close()

    assert stopped == ""
    assert recorder.totals["nodes_new"] > 0
    assert recorder.lines


# --------------------------------------------------------------------------
# The budget is checked BEFORE the engine call, or it costs what it exists to
# save.
# --------------------------------------------------------------------------


def test_the_call_budget_is_spent_but_never_exceeded(tmp_path) -> None:
    """`max_engine_calls=N` permits exactly N calls, then stops.

    The check runs before each call and compares calls already made, so a
    budget of 1 allows the first and refuses the second — it is a ceiling on
    spend, not a refusal to start.
    """
    text = " ".join(TEXT for _ in range(40))  # long enough to need many chunks
    store = KGStore.open(tmp_path / "kg.sqlite")
    _document(store, text, "long.md")
    engine = _CountingEngine()
    recorder = _Recorder()
    try:
        stopped = _extract(store, engine, _caps(max_calls=1), tmp_path, recorder)
    finally:
        store.close()

    assert "engine call cap reached" in stopped
    assert engine.calls == 1


def test_an_exhausted_time_budget_stops_before_any_engine_call(tmp_path) -> None:
    store = _store(tmp_path)
    engine = _CountingEngine()
    recorder = _Recorder()
    try:
        stopped = _extract(
            store, engine, _caps(time_budget=-1.0), tmp_path, recorder
        )
    finally:
        store.close()

    assert stopped
    assert engine.calls == 0


# --------------------------------------------------------------------------
# A malformed response is refused and logged — never inserted, never a crash.
# --------------------------------------------------------------------------


def test_a_malformed_response_is_refused_without_crashing(tmp_path) -> None:
    store = _store(tmp_path)
    engine = _BrokenEngine()
    recorder = _Recorder()
    try:
        stopped = _extract(store, engine, _caps(), tmp_path, recorder)
        # Nothing was inserted, and the store is still usable afterwards.
        assert store.conn.execute("SELECT COUNT(*) FROM nodes").fetchone()[0] == 0
    finally:
        store.close()

    assert stopped == ""
    assert engine.calls > 0, "the loop must have tried before refusing"
    assert recorder.totals["nodes_new"] == 0


def test_an_engine_failure_on_one_chunk_does_not_abort_the_run(tmp_path) -> None:
    store = _store(tmp_path)
    engine = _FailingEngine()
    recorder = _Recorder()
    try:
        stopped = _extract(store, engine, _caps(), tmp_path, recorder)
    finally:
        store.close()

    assert stopped == ""
    assert engine.calls > 0
    assert any("engine error" in line for line in recorder.lines)


# --------------------------------------------------------------------------
# Abort: the CLI passes its kill switch here. The server has none yet, so this
# is the seam that lets it gain one without touching the loop.
# --------------------------------------------------------------------------


def test_an_abort_signal_stops_the_run_with_its_own_reason(tmp_path) -> None:
    store = _store(tmp_path)
    engine = _CountingEngine()
    recorder = _Recorder()
    try:
        stopped = _extract(
            store,
            engine,
            _caps(),
            tmp_path,
            recorder,
            should_abort=lambda: "kill switch triggered",
        )
    finally:
        store.close()

    assert stopped == "kill switch triggered"
    assert engine.calls == 0


def test_an_abort_hook_that_stays_quiet_does_not_stop_the_run(tmp_path) -> None:
    """An empty reason means "keep going" — it must not read as a stop."""
    store = _store(tmp_path)
    recorder = _Recorder()
    try:
        stopped = _extract(
            store,
            MockEngine(),
            _caps(),
            tmp_path,
            recorder,
            should_abort=lambda: "",
        )
    finally:
        store.close()

    assert stopped == ""
    assert recorder.totals["nodes_new"] > 0


# --------------------------------------------------------------------------
# The default document query is global, so a caller that knows which documents
# it produced must be able to say so.
# --------------------------------------------------------------------------


def test_only_the_requested_documents_are_extracted(tmp_path) -> None:
    store = _store(tmp_path)
    other = _document(
        store,
        TEXT + " The FeatureStore is refreshed by the Ingestor.",
        "other.md",
    )
    recorder = _Recorder()
    try:
        assert len(unprocessed_doc_ids(store)) == 2
        stopped = _extract(
            store, MockEngine(), _caps(), tmp_path, recorder, doc_ids=[other.id]
        )
        remaining = unprocessed_doc_ids(store)
    finally:
        store.close()

    assert stopped == ""
    assert other.id not in remaining
    assert len(remaining) == 1
