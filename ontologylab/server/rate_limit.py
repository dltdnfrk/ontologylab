"""Process-local rate limits for sensitive local-API actions.

State lives in this process only and can be cleared between tests. Nothing
here is written to disk, and generate/engine calls are not limited.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field


PROVIDER_TEST_WINDOW_S = 10.0


class RateLimitExceeded(Exception):
    """The caller must wait ``retry_after_s`` seconds before retrying."""

    def __init__(self, retry_after_s: float) -> None:
        self.retry_after_s = max(1, int(retry_after_s))
        super().__init__("too many requests")


@dataclass
class WindowLimiter:
    """One successful check per ``key`` inside ``window_s`` seconds."""

    window_s: float
    _lock: threading.Lock = field(default_factory=threading.Lock)
    _hits: dict[str, float] = field(default_factory=dict)

    def check(self, key: str, *, now: float | None = None) -> None:
        ts = time.monotonic() if now is None else now
        with self._lock:
            last = self._hits.get(key)
            if last is not None:
                remaining = self.window_s - (ts - last)
                if remaining > 0:
                    raise RateLimitExceeded(remaining)
            self._hits[key] = ts

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()


_provider_test_limiter = WindowLimiter(PROVIDER_TEST_WINDOW_S)


def check_provider_test_limit(
    provider_id: str, *, now: float | None = None
) -> None:
    """Refuse a second ``/api/providers/{id}/test`` inside the window."""
    _provider_test_limiter.check(provider_id, now=now)


def reset_provider_test_limiter() -> None:
    """Drop all recorded test hits. For tests only."""
    _provider_test_limiter.reset()
