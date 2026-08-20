"""Deterministic Wave 2.1 Step 1 fixture and concurrency harness.

Runtime state is confined to a caller-owned directory. Completions wait on
exact JobRegistry version edges or process-exit joins; this module does not
sleep, poll, retry, bind ports, or touch live data.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable

from ontologylab.server.jobs import TERMINAL_STATUSES, Job, JobRegistry


class FixtureByteMismatch(Exception):
    def __init__(self, path: Path, expected: str, actual: str) -> None:
        self.path = Path(path)
        self.expected = expected
        self.actual = actual
        super().__init__(f"{self.path}: expected {expected}, got {actual}")


class FixtureReceiptMissing(Exception):
    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        super().__init__(str(self.path))


class FailpointArmed(Exception):
    def __init__(self, name: str) -> None:
        self.name = name
        super().__init__(name)


class ProcessJoinTimeout(Exception):
    def __init__(self, pid: int) -> None:
        self.pid = pid
        super().__init__(str(pid))


class ResearchEventTimeout(Exception):
    pass


class ResearchSubscriptionRequired(Exception):
    pass


def canonical_dump(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def canonical_hash(value: Any) -> str:
    payload = value if isinstance(value, (bytes, bytearray)) else canonical_dump(value)
    return hashlib.sha256(payload).hexdigest()


@dataclass(frozen=True)
class FrozenFixture:
    root: Path
    payload: bytes
    receipt: dict[str, Any]
    sha256: str


def freeze_populated_fixture(root: Path) -> FrozenFixture:
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    payload = canonical_dump(
        {
            "documents": [
                {
                    "doi": None,
                    "id": "doc-legacy",
                    "source_uri": "https://doi.org/10.1234/legacy",
                },
                {
                    "doi": "10.1234/populated",
                    "id": "doc-doi",
                    "source_uri": "https://doi.org/10.1234/populated",
                },
            ],
            "kind": "populated-historical",
            "seed": 20260820,
        }
    )
    sha256 = hashlib.sha256(payload).hexdigest()
    receipt = {
        "bytes": len(payload),
        "kind": "wave21-populated-fixture",
        "sha256": sha256,
    }
    (root / "payload.bin").write_bytes(payload)
    (root / "receipt.json").write_bytes(canonical_dump(receipt))
    return FrozenFixture(root=root, payload=payload, receipt=receipt, sha256=sha256)


def load_frozen_fixture(root: Path) -> FrozenFixture:
    root = Path(root)
    payload_path = root / "payload.bin"
    receipt_path = root / "receipt.json"
    if not receipt_path.is_file():
        raise FixtureReceiptMissing(receipt_path)
    payload = payload_path.read_bytes()
    receipt = json.loads(receipt_path.read_bytes())
    actual = hashlib.sha256(payload).hexdigest()
    expected = str(receipt["sha256"])
    if actual != expected:
        raise FixtureByteMismatch(payload_path, expected, actual)
    return FrozenFixture(root=root, payload=payload, receipt=receipt, sha256=actual)


class Failpoint:
    def __init__(self) -> None:
        self._armed: set[str] = set()

    def arm(self, name: str) -> None:
        self._armed.add(name)

    def disarm(self, name: str) -> None:
        self._armed.discard(name)

    def hit(self, name: str) -> None:
        if name in self._armed:
            raise FailpointArmed(name)


class ConcurrencyBarrier:
    def __init__(self, parties: int) -> None:
        self._barrier = threading.Barrier(parties)

    def wait(self, timeout: float) -> None:
        self._barrier.wait(timeout=timeout)


class DisposableRuntime:
    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self._processes: list[subprocess.Popen[bytes]] = []

    def spawn(self, argv: Iterable[str]) -> subprocess.Popen[bytes]:
        process = subprocess.Popen(
            list(argv),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=self.root,
            close_fds=True,
        )
        self._processes.append(process)
        return process

    def owned_pids(self) -> tuple[int, ...]:
        return tuple(process.pid for process in self._processes if process.poll() is None)

    def cleanup(self) -> None:
        for process in self._processes:
            if process.poll() is None and process.stdin is not None:
                try:
                    process.stdin.close()
                except OSError:
                    pass
            if process.poll() is None:
                process.terminate()
            try:
                process.wait(timeout=2.0)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=2.0)
            if process.stdout is not None:
                process.stdout.close()
            if process.stderr is not None:
                process.stderr.close()
        self._processes.clear()
        if self.root.exists():
            shutil.rmtree(self.root)


def spawn_sentinel_writer(
    runtime: DisposableRuntime, sentinel: Path
) -> subprocess.Popen[bytes]:
    sentinel = Path(sentinel)
    sentinel.parent.mkdir(parents=True, exist_ok=True)
    code = (
        "from pathlib import Path\n"
        f"Path({str(sentinel)!r}).write_bytes(b'ok')\n"
    )
    return runtime.spawn((sys.executable, "-c", code))


def spawn_blocker(runtime: DisposableRuntime) -> subprocess.Popen[bytes]:
    return runtime.spawn((sys.executable, "-c", "import sys; sys.stdin.read()"))


def join_process(process: subprocess.Popen[bytes], timeout: float) -> int:
    try:
        return int(process.wait(timeout=timeout))
    except subprocess.TimeoutExpired as exc:
        raise ProcessJoinTimeout(int(process.pid)) from exc


class Subscription:
    """Subscribe to JobRegistry version edges before a research trigger."""

    def __init__(self, registry: JobRegistry) -> None:
        self._registry = registry
        self._last_seen: int | None = None

    def subscribe(self) -> None:
        self._last_seen = self._registry.wait_version(-1, 0)

    def trigger(self, action: Callable[[], Any]) -> Any:
        if self._last_seen is None:
            raise ResearchSubscriptionRequired("subscribe before trigger")
        return action()

    def await_terminal(self, job: Job, timeout: float) -> Job:
        if self._last_seen is None:
            raise ResearchSubscriptionRequired("subscribe before await")
        deadline = time.monotonic() + timeout
        last_seen = self._last_seen
        while job.status not in TERMINAL_STATUSES:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise ResearchEventTimeout(job.job_id)
            version = self._registry.wait_version(last_seen, remaining)
            if version == last_seen:
                raise ResearchEventTimeout(job.job_id)
            last_seen = version
        return job
