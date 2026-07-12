"""Lightweight, dependency-free status reporting for a ontologylab job.

Prints a compact one-line status update per iteration to stdout and mirrors
the same information as JSON to ``<run_dir>/status.json`` so an external
process (or a human) can poll run progress without parsing log output.

Standard library only. No third-party dependencies. Domain-agnostic: this
module knows nothing about the content of any candidate or run, only about
generic run-progress numbers (iteration counters, a scalar score, call
counts, elapsed seconds).
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any


class Tui:
    """Minimal text UI: one status line per iteration plus a JSON snapshot.

    Usage:
        tui = Tui(run_dir="/path/to/run")
        tui.start(total_iterations=12)
        tui.update(iteration=1, best_score=0.5, engine_calls=1, elapsed_s=2.3)
        tui.finish(best_score=0.9, engine_calls=12, elapsed_s=60.0)
    """

    def __init__(self, run_dir: str) -> None:
        self.run_dir = Path(run_dir)
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self.status_path = self.run_dir / "status.json"
        self._started_at = time.time()
        self._total_iterations: int | None = None

    def start(self, total_iterations: int | None = None, **extra: Any) -> None:
        """Record the beginning of a run and write an initial status file."""
        self._started_at = time.time()
        self._total_iterations = total_iterations
        state = {
            "phase": "running",
            "iteration": 0,
            "total_iterations": total_iterations,
            "best_score": None,
            "engine_calls": 0,
            "elapsed_s": 0.0,
            "started_at": self._started_at,
            "updated_at": self._started_at,
        }
        state.update(extra)
        self._write_status(state)
        line = "[ontologylab] starting run"
        if total_iterations is not None:
            line += f" (iterations={total_iterations})"
        print(line, flush=True)

    def update(
        self,
        *,
        iteration: int,
        best_score: float | None,
        engine_calls: int,
        elapsed_s: float,
        note: str | None = None,
        **extra: Any,
    ) -> None:
        """Print a compact status line and refresh status.json.

        Fields: iteration, best_score, engine_calls, elapsed_s, plus any
        caller-supplied extra keys are merged into the JSON snapshot only.
        """
        now = time.time()
        total = f"/{self._total_iterations}" if self._total_iterations else ""
        score_str = "n/a" if best_score is None else f"{best_score:.6g}"
        line = (
            f"[ontologylab] iter {iteration}{total} | best={score_str} "
            f"| calls={engine_calls} | elapsed={elapsed_s:.1f}s"
        )
        if note:
            line += f" | {note}"
        print(line, flush=True)

        state = {
            "phase": "running",
            "iteration": iteration,
            "total_iterations": self._total_iterations,
            "best_score": best_score,
            "engine_calls": engine_calls,
            "elapsed_s": elapsed_s,
            "note": note,
            "started_at": self._started_at,
            "updated_at": now,
        }
        state.update(extra)
        self._write_status(state)

    def finish(
        self,
        *,
        best_score: float | None,
        engine_calls: int,
        elapsed_s: float,
        reason: str = "completed",
        **extra: Any,
    ) -> None:
        """Print a final summary line and write the terminal status.json."""
        now = time.time()
        score_str = "n/a" if best_score is None else f"{best_score:.6g}"
        print(
            f"[ontologylab] finished ({reason}) | best={score_str} "
            f"| calls={engine_calls} | elapsed={elapsed_s:.1f}s",
            flush=True,
        )
        state = {
            "phase": "finished",
            "reason": reason,
            "iteration": self._total_iterations,
            "total_iterations": self._total_iterations,
            "best_score": best_score,
            "engine_calls": engine_calls,
            "elapsed_s": elapsed_s,
            "started_at": self._started_at,
            "updated_at": now,
        }
        state.update(extra)
        self._write_status(state)

    def _write_status(self, state: dict[str, Any]) -> None:
        tmp_path = self.status_path.with_suffix(".json.tmp")
        tmp_path.write_text(json.dumps(state, indent=2, default=str), encoding="utf-8")
        tmp_path.replace(self.status_path)
