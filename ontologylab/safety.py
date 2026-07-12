"""Safety controls for the ontologylab pipeline: iteration/time/call caps and a kill switch.

This module provides two independent safety primitives used by the
Coordinator's closed loop:

- ``Caps``: derives stop decisions from a ``RunConfig`` by comparing
  iteration count, wall-clock elapsed time, and engine call count against
  configured budgets.
- ``KillSwitch``: installs SIGINT/SIGTERM handlers and watches for a
  ``KILL`` sentinel file inside the run directory, allowing either an
  operating-system signal or a simple filesystem touch to request a
  graceful stop.

Nothing here touches domain content; it is purely about run-loop control
flow and process lifecycle.
"""

from __future__ import annotations

import signal
import types
from pathlib import Path
from typing import Any


class Caps:
    """Evaluate whether the run loop should stop based on configured budgets.

    Expects an object (typically a config instance)
    exposing ``iterations`` (int), ``time_budget_s`` (float), and
    ``max_engine_calls`` (int) attributes.
    """

    def __init__(self, config: Any) -> None:
        self.config = config

    def should_stop(self, state: dict[str, Any]) -> tuple[bool, str]:
        """Return (stop, reason) given a state dict with progress counters.

        Recognized state keys: ``iteration`` (int, iterations completed),
        ``elapsed`` (float, seconds since run start), ``engine_calls``
        (int, total engine invocations so far). Missing keys default to 0.
        """
        iteration = int(state.get("iteration", 0))
        elapsed = float(state.get("elapsed", state.get("elapsed_s", 0.0)))
        engine_calls = int(state.get("engine_calls", 0))

        max_iterations = int(getattr(self.config, "iterations", 0))
        time_budget_s = float(getattr(self.config, "time_budget_s", 0.0))
        max_engine_calls = int(getattr(self.config, "max_engine_calls", 0))

        if max_iterations and iteration >= max_iterations:
            return True, f"iteration cap reached ({iteration}/{max_iterations})"
        if time_budget_s and elapsed >= time_budget_s:
            return True, f"time budget reached ({elapsed:.2f}s/{time_budget_s:.2f}s)"
        if max_engine_calls and engine_calls >= max_engine_calls:
            return True, f"engine call cap reached ({engine_calls}/{max_engine_calls})"
        return False, ""


class KillSwitch:
    """Cooperative kill switch driven by OS signals and a sentinel file.

    Installs handlers for SIGINT and SIGTERM that set an internal flag
    instead of raising, so the coordinator can observe ``triggered()`` at
    safe points and shut down gracefully (writing partial outputs) rather
    than being interrupted mid-write. Also treats the presence of a
    ``KILL`` file inside ``run_dir`` as an equivalent stop request, which
    lets an external process or user request a stop without sending a
    signal.
    """

    def __init__(self, run_dir: str) -> None:
        self.run_dir = Path(run_dir)
        self._flag = False
        self._previous_handlers: dict[int, Any] = {}

    def install(self) -> None:
        """Register signal handlers for SIGINT and SIGTERM."""
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                self._previous_handlers[sig] = signal.getsignal(sig)
                signal.signal(sig, self._handle_signal)
            except (ValueError, OSError):
                # Not the main thread, or platform does not support this
                # signal; the KILL-file watch still works as a fallback.
                continue

    def uninstall(self) -> None:
        """Restore any previously installed signal handlers."""
        for sig, handler in self._previous_handlers.items():
            try:
                signal.signal(sig, handler)
            except (ValueError, OSError):
                continue
        self._previous_handlers.clear()

    def _handle_signal(self, signum: int, frame: types.FrameType | None) -> None:
        self._flag = True

    def _kill_file_path(self) -> Path:
        return self.run_dir / "KILL"

    def triggered(self) -> bool:
        """Return True if a stop was requested via signal or KILL file."""
        if self._flag:
            return True
        try:
            if self._kill_file_path().exists():
                self._flag = True
                return True
        except OSError:
            pass
        return False

    def reset(self) -> None:
        """Clear the internal flag (does not remove the KILL file)."""
        self._flag = False
