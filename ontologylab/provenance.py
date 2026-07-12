"""Per-run provenance logging and cost/usage tracking.

This module records a durable, append-only audit trail for a single ontologylab
run: one JSON line per step in ``<run_dir>/provenance.jsonl``, plus a live
``<run_dir>/status.json`` snapshot that is rewritten on every update so an
external observer (or the TUI) can poll run progress without parsing the
JSONL log.

It also tracks lightweight cost/usage accounting -- number of engine calls,
cumulative elapsed engine time, and a per-step call/elapsed breakdown -- so a
run's resource consumption can be inspected without re-deriving it from the
log.

Because the run's random seed fully determines the fixed problem instances
and the MockEngine's deterministic output, recording the seed alongside the
run's configuration is sufficient to make a run replayable: re-running with
the same seed and config reproduces the same instances and (for MockEngine)
the same generated candidates.

No out-of-domain content: everything here is generic run
bookkeeping (steps, timings, call counts) with no domain-specific meaning
attached to payload contents.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class StepUsage:
    """Aggregated usage counters for one named step."""

    calls: int = 0
    elapsed_s: float = 0.0
    log_entries: int = 0


class Provenance:
    """Append-only provenance log + live status snapshot for one run.

    Parameters
    ----------
    run_dir:
        Directory the run writes its outputs into. Created if missing.
    seed:
        The run's random seed. Recorded in every status snapshot so the run
        can be replayed later (same seed + config -> same instances and, for
        MockEngine, the same generated candidates).
    """

    def __init__(self, run_dir: str, seed: int) -> None:
        self.run_dir: Path = Path(run_dir)
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self.seed: int = seed

        self.jsonl_path: Path = self.run_dir / "provenance.jsonl"
        self.status_path: Path = self.run_dir / "status.json"

        self._start_ts: float = time.time()
        self._engine_calls: int = 0
        self._engine_elapsed_s: float = 0.0
        self._per_step: dict[str, StepUsage] = {}
        self._log_count: int = 0
        self._last_step: str | None = None
        self._last_payload: dict[str, Any] = {}

    def log(self, step: str, payload: dict[str, Any] | None = None) -> None:
        """Append one JSON line recording ``step`` and ``payload``.

        Also updates the per-step log-entry counter and rewrites the
        status.json snapshot so external observers see the change
        immediately.
        """
        payload = dict(payload) if payload is not None else {}
        entry: dict[str, Any] = {
            "ts": time.time(),
            "seed": self.seed,
            "step": step,
            "payload": payload,
        }
        with self.jsonl_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, default=str) + "\n")

        usage = self._per_step.setdefault(step, StepUsage())
        usage.log_entries += 1
        self._log_count += 1
        self._last_step = step
        self._last_payload = payload

        self._write_status()

    def track_engine_call(
        self,
        step: str,
        elapsed_s: float,
        usage_meta: dict[str, Any] | None = None,
    ) -> None:
        """Record one engine invocation's cost against ``step``.

        ``elapsed_s`` is added to both the run-wide and per-step elapsed
        totals; the run-wide and per-step call counters are each
        incremented by one. ``usage_meta`` (an engine's returned usage
        dict, e.g. containing extra timing/call-count detail) is logged
        verbatim alongside the accounting fields.
        """
        self._engine_calls += 1
        self._engine_elapsed_s += elapsed_s

        usage = self._per_step.setdefault(step, StepUsage())
        usage.calls += 1
        usage.elapsed_s += elapsed_s

        self.log(
            step,
            {
                "engine_call": True,
                "elapsed_s": elapsed_s,
                "usage_meta": usage_meta or {},
            },
        )

    @property
    def engine_calls(self) -> int:
        """Total number of engine calls tracked so far in this run."""
        return self._engine_calls

    @property
    def engine_elapsed_s(self) -> float:
        """Total elapsed engine time (seconds) tracked so far in this run."""
        return self._engine_elapsed_s

    @property
    def elapsed_s(self) -> float:
        """Wall-clock seconds since this Provenance object was created."""
        return time.time() - self._start_ts

    def snapshot(self) -> dict[str, Any]:
        """Return the current run status as a plain dict.

        This is the exact structure written to ``status.json``.
        """
        return {
            "run_dir": str(self.run_dir),
            "seed": self.seed,
            "started": self._start_ts,
            "updated": time.time(),
            "elapsed_s": self.elapsed_s,
            "engine_calls": self._engine_calls,
            "engine_elapsed_s": self._engine_elapsed_s,
            "log_entries": self._log_count,
            "last_step": self._last_step,
            "last_payload": self._last_payload,
            "per_step": {
                name: {
                    "calls": usage.calls,
                    "elapsed_s": usage.elapsed_s,
                    "log_entries": usage.log_entries,
                }
                for name, usage in self._per_step.items()
            },
        }

    def _write_status(self) -> None:
        """Rewrite status.json with the current snapshot (best-effort atomic)."""
        data = self.snapshot()
        tmp_path = self.status_path.with_suffix(".json.tmp")
        with tmp_path.open("w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2, default=str)
        tmp_path.replace(self.status_path)
