"""Safety controls: extraction budget caps and the cooperative kill switch.

These are the only guard on a runaway LLM extraction loop (cost + wall time)
and the only way to stop one gracefully, yet nothing asserted they actually
fire. The contracts pinned here are the ones main._extract_async and
server/jobs.py depend on.
"""

from __future__ import annotations

import signal
import threading
from types import SimpleNamespace

from ontologylab.safety import Caps, KillSwitch


def cfg(iterations=0, time_budget_s=0.0, max_engine_calls=0):
    """A budget config shaped like the SimpleNamespace the callers build."""
    return SimpleNamespace(
        iterations=iterations,
        time_budget_s=time_budget_s,
        max_engine_calls=max_engine_calls,
    )


# ---------------------------------------------------------------------------
# Caps — the budget that stops a runaway extraction loop
# ---------------------------------------------------------------------------


def test_under_budget_does_not_stop():
    caps = Caps(cfg(iterations=5, time_budget_s=60.0, max_engine_calls=10))
    stop, reason = caps.should_stop(
        {"iteration": 2, "elapsed": 12.0, "engine_calls": 3}
    )
    assert stop is False
    assert reason == ""


def test_engine_call_cap_fires_at_the_limit():
    """The call cap is the cost guard: it must fire AT the limit, not past it."""
    caps = Caps(cfg(max_engine_calls=200))
    assert caps.should_stop({"engine_calls": 199})[0] is False
    stop, reason = caps.should_stop({"engine_calls": 200})
    assert stop is True
    assert "engine call cap" in reason and "200/200" in reason
    # and it stays stopped past the limit
    assert caps.should_stop({"engine_calls": 5000})[0] is True


def test_time_budget_fires_at_the_limit():
    caps = Caps(cfg(time_budget_s=1800.0))
    assert caps.should_stop({"elapsed": 1799.9})[0] is False
    stop, reason = caps.should_stop({"elapsed": 1800.0})
    assert stop is True
    assert "time budget" in reason


def test_iteration_cap_fires_at_the_limit():
    caps = Caps(cfg(iterations=3))
    assert caps.should_stop({"iteration": 2})[0] is False
    stop, reason = caps.should_stop({"iteration": 3})
    assert stop is True
    assert "iteration cap" in reason


def test_zero_budget_means_unlimited_not_instantly_stopped():
    """Callers pass iterations=0 to disable that cap — 0 must not mean 'stop
    immediately', or extraction would never run a single chunk."""
    caps = Caps(cfg(iterations=0, time_budget_s=0.0, max_engine_calls=0))
    assert caps.should_stop(
        {"iteration": 10**6, "elapsed": 10**6, "engine_calls": 10**6}
    ) == (False, "")


def test_missing_state_keys_default_to_zero():
    """main/jobs pass only elapsed+engine_calls; absent keys must not KeyError."""
    caps = Caps(cfg(iterations=5, time_budget_s=60.0, max_engine_calls=10))
    assert caps.should_stop({}) == (False, "")
    assert caps.should_stop({"engine_calls": 10})[0] is True


def test_elapsed_s_alias_is_honored():
    """Provenance snapshots use elapsed_s; both spellings must work."""
    caps = Caps(cfg(time_budget_s=10.0))
    assert caps.should_stop({"elapsed_s": 10.0})[0] is True
    assert caps.should_stop({"elapsed_s": 1.0})[0] is False


def test_whichever_budget_is_breached_stops_the_run():
    """Each budget is independent: breaching any one is enough."""
    caps = Caps(cfg(iterations=100, time_budget_s=100.0, max_engine_calls=100))
    assert caps.should_stop({"iteration": 100})[0] is True
    assert caps.should_stop({"elapsed": 100.0})[0] is True
    assert caps.should_stop({"engine_calls": 100})[0] is True


def test_extraction_loop_contract_matches_callers():
    """The exact call shape main._extract_async / jobs._run use."""
    caps = Caps(cfg(iterations=0, time_budget_s=1800.0, max_engine_calls=200))
    # mid-run: under both budgets
    assert caps.should_stop({"elapsed": 5.0, "engine_calls": 7}) == (False, "")
    # call budget exhausted first
    stop, reason = caps.should_stop({"elapsed": 5.0, "engine_calls": 200})
    assert stop is True and reason


# ---------------------------------------------------------------------------
# KillSwitch — graceful stop via signal or sentinel file
# ---------------------------------------------------------------------------


def test_not_triggered_when_idle(tmp_path):
    assert KillSwitch(str(tmp_path)).triggered() is False


def test_kill_file_triggers_and_latches(tmp_path):
    ks = KillSwitch(str(tmp_path))
    assert ks.triggered() is False
    (tmp_path / "KILL").write_text("")
    assert ks.triggered() is True
    # latched: removing the file does not un-trigger an in-flight stop
    (tmp_path / "KILL").unlink()
    assert ks.triggered() is True


def test_reset_clears_the_flag_but_kill_file_retriggers(tmp_path):
    ks = KillSwitch(str(tmp_path))
    (tmp_path / "KILL").write_text("")
    assert ks.triggered() is True
    ks.reset()
    # file still present -> triggers again on the next check
    assert ks.triggered() is True
    (tmp_path / "KILL").unlink()
    ks.reset()
    assert ks.triggered() is False


def test_signal_sets_flag_without_raising(tmp_path):
    """SIGINT must set the flag rather than raise, so the loop can finish
    writing partial output instead of dying mid-write."""
    ks = KillSwitch(str(tmp_path))
    ks.install()
    try:
        assert ks.triggered() is False
        ks._handle_signal(signal.SIGINT, None)  # what the OS handler invokes
        assert ks.triggered() is True
    finally:
        ks.uninstall()


def test_install_replaces_then_uninstall_restores_handlers(tmp_path):
    original = signal.getsignal(signal.SIGINT)
    ks = KillSwitch(str(tmp_path))
    ks.install()
    assert signal.getsignal(signal.SIGINT) is not original
    ks.uninstall()
    assert signal.getsignal(signal.SIGINT) is original


def test_uninstall_without_install_is_safe(tmp_path):
    KillSwitch(str(tmp_path)).uninstall()  # must not raise


def test_install_off_main_thread_degrades_to_kill_file(tmp_path):
    """server/jobs.py runs extraction in a daemon thread, where signal.signal
    raises ValueError. install() must swallow it and leave the KILL-file
    watch working, not crash the job."""
    errors: list[BaseException] = []
    ks = KillSwitch(str(tmp_path))

    def worker():
        try:
            ks.install()      # ValueError inside a non-main thread
            ks.uninstall()
        except BaseException as exc:  # noqa: BLE001 - recording for assertion
            errors.append(exc)

    t = threading.Thread(target=worker)
    t.start()
    t.join()
    assert errors == []
    # the filesystem fallback still works
    (tmp_path / "KILL").write_text("")
    assert ks.triggered() is True


def test_unreadable_run_dir_does_not_crash_the_check(tmp_path, monkeypatch):
    """A stat failure must not abort the extraction loop."""
    ks = KillSwitch(str(tmp_path / "gone"))
    assert ks.triggered() is False

    def boom(self):
        raise OSError("stat failed")

    monkeypatch.setattr("pathlib.Path.exists", boom)
    assert ks.triggered() is False  # swallowed, run continues
