"""Wave 2.1 Step 1 G001: deterministic fixture/harness primitives.

These tests pin harness behavior only. They do not treat current product
defects as GREEN and they do not start network listeners or touch live data.
"""

from __future__ import annotations

import threading
from pathlib import Path

import pytest

from tests.wave21.harness import (
    ConcurrencyBarrier,
    DisposableRuntime,
    Failpoint,
    FailpointArmed,
    FixtureByteMismatch,
    FixtureReceiptMissing,
    ProcessJoinTimeout,
    ResearchEventTimeout,
    ResearchSubscriptionRequired,
    Subscription,
    canonical_dump,
    canonical_hash,
    freeze_populated_fixture,
    join_process,
    load_frozen_fixture,
    spawn_blocker,
    spawn_sentinel_writer,
)


def test_frozen_populated_fixture_loads_byte_identically(tmp_path: Path) -> None:
    frozen = freeze_populated_fixture(tmp_path / "fixtures")
    loaded = load_frozen_fixture(frozen.root)

    assert loaded.payload == frozen.payload
    assert loaded.receipt == frozen.receipt
    assert loaded.sha256 == frozen.sha256
    assert loaded.sha256 == canonical_hash(frozen.payload)


def test_canonical_dump_and_hash_are_key_order_stable() -> None:
    left = {"b": 2, "a": {"y": 1, "x": 0}}
    right = {"a": {"x": 0, "y": 1}, "b": 2}

    dump = canonical_dump(left)
    assert dump == canonical_dump(right)
    assert dump == b'{"a":{"x":0,"y":1},"b":2}'
    assert canonical_hash(left) == canonical_hash(right)
    assert canonical_hash(left) == canonical_hash(dump)


def test_failpoint_fires_only_when_armed() -> None:
    failpoint = Failpoint()
    failpoint.hit("after_insert")

    failpoint.arm("after_insert")
    with pytest.raises(FailpointArmed) as raised:
        failpoint.hit("after_insert")
    assert raised.value.name == "after_insert"

    failpoint.disarm("after_insert")
    failpoint.hit("after_insert")


def test_concurrency_barrier_releases_every_party() -> None:
    barrier = ConcurrencyBarrier(3)
    released: list[int] = []
    lock = threading.Lock()

    def worker(token: int) -> None:
        barrier.wait(timeout=2.0)
        with lock:
            released.append(token)

    threads = [
        threading.Thread(target=worker, args=(token,)) for token in (1, 2)
    ]
    for thread in threads:
        thread.start()
    worker(3)
    for thread in threads:
        thread.join(timeout=2.0)
        assert not thread.is_alive()

    assert sorted(released) == [1, 2, 3]


def test_bounded_process_join_completes_on_disposable_state(tmp_path: Path) -> None:
    runtime = DisposableRuntime(tmp_path / "runtime")
    try:
        sentinel = runtime.root / "sentinel.bin"
        process = spawn_sentinel_writer(runtime, sentinel)
        code = join_process(process, timeout=5.0)
        assert code == 0
        assert sentinel.read_bytes() == b"ok"
        assert process.poll() == 0
    finally:
        runtime.cleanup()
    assert not runtime.root.exists()
    assert runtime.owned_pids() == ()


def test_research_event_subscription_completes_after_pre_trigger_subscribe(
    tmp_path: Path,
) -> None:
    from ontologylab.server.jobs import Job, JobRegistry

    registry = JobRegistry(tmp_path / "data")
    job = Job(
        job_id="wave21-g001",
        kind="research",
        engine="mock",
        model=None,
        started_ts=0.0,
    )
    subscription = Subscription(registry)
    subscription.subscribe()

    def trigger() -> None:
        job.status = "complete"
        registry.touch()

    subscription.trigger(trigger)
    finished = subscription.await_terminal(job, timeout=2.0)
    assert finished.status == "complete"
    assert finished is job


def test_frozen_fixture_refuses_a_changed_byte(tmp_path: Path) -> None:
    frozen = freeze_populated_fixture(tmp_path / "fixtures")
    payload_path = frozen.root / "payload.bin"
    mutated = bytearray(payload_path.read_bytes())
    mutated[0] ^= 0xFF
    payload_path.write_bytes(bytes(mutated))

    with pytest.raises(FixtureByteMismatch) as raised:
        load_frozen_fixture(frozen.root)
    assert raised.value.path == payload_path
    assert raised.value.expected == frozen.sha256
    assert raised.value.actual != frozen.sha256


def test_frozen_fixture_refuses_a_missing_receipt(tmp_path: Path) -> None:
    frozen = freeze_populated_fixture(tmp_path / "fixtures")
    receipt_path = frozen.root / "receipt.json"
    receipt_path.unlink()

    with pytest.raises(FixtureReceiptMissing) as raised:
        load_frozen_fixture(frozen.root)
    assert raised.value.path == receipt_path


def test_bounded_join_times_out_without_killing_unrelated_process(
    tmp_path: Path,
) -> None:
    runtime = DisposableRuntime(tmp_path / "runtime")
    try:
        blocked = spawn_blocker(runtime)
        unrelated = spawn_blocker(runtime)
        with pytest.raises(ProcessJoinTimeout) as raised:
            join_process(blocked, timeout=0.2)
        assert raised.value.pid == blocked.pid
        assert blocked.poll() is None
        assert unrelated.poll() is None
        assert blocked.pid != unrelated.pid
    finally:
        runtime.cleanup()
    assert blocked.poll() is not None
    assert unrelated.poll() is not None
    assert not runtime.root.exists()


def test_research_wait_requires_subscription_before_trigger(tmp_path: Path) -> None:
    from ontologylab.server.jobs import Job, JobRegistry

    registry = JobRegistry(tmp_path / "data")
    job = Job(
        job_id="wave21-g001-unsubscribed",
        kind="research",
        engine="mock",
        model=None,
        started_ts=0.0,
    )
    subscription = Subscription(registry)

    with pytest.raises(ResearchSubscriptionRequired):
        subscription.trigger(lambda: job)

    with pytest.raises(ResearchSubscriptionRequired):
        subscription.await_terminal(job, timeout=0.2)


def test_research_wait_times_out_when_completion_never_arrives(
    tmp_path: Path,
) -> None:
    from ontologylab.server.jobs import Job, JobRegistry

    registry = JobRegistry(tmp_path / "data")
    job = Job(
        job_id="wave21-g001-timeout",
        kind="research",
        engine="mock",
        model=None,
        started_ts=0.0,
    )
    subscription = Subscription(registry)
    subscription.subscribe()

    with pytest.raises(ResearchEventTimeout):
        subscription.await_terminal(job, timeout=0.2)
    assert job.status == "running"


def test_runtime_cleanup_removes_owned_temp_and_processes(tmp_path: Path) -> None:
    runtime = DisposableRuntime(tmp_path / "runtime")
    process = spawn_blocker(runtime)
    marker = runtime.root / "owned.txt"
    marker.write_bytes(b"temp")
    assert process.poll() is None
    assert marker.exists()

    runtime.cleanup()

    assert process.poll() is not None
    assert not runtime.root.exists()
    assert runtime.owned_pids() == ()
