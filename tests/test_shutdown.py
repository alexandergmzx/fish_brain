"""shutdown.Watcher: STOP reaches the MCU even when the main thread is stuck."""
import os
import signal
import threading
import time

import pytest

from fish_brain import shutdown
from fish_brain.config import SerialConfig
from fish_brain.serial_link import _TX_LOCK, BaseLink, ResilientLink


class Recorder(BaseLink):
    def __init__(self):
        super().__init__(SerialConfig())
        self.lines: list[bytes] = []
        self.calls: list[str] = []

    def _write_raw(self, data: bytes) -> None:
        self.lines.append(data)

    def all_stop(self) -> None:
        self.calls.append("all_stop")
        super().all_stop()

    def emergency_stop(self) -> None:
        self.calls.append("emergency")
        super().emergency_stop()


@pytest.fixture
def quiet_sigint():
    """A Python handler that does nothing: the C handler still writes the wakeup fd, but the
    main thread (the test) carries on as if stuck in a C call."""
    old = signal.signal(signal.SIGINT, lambda *_: None)
    yield
    signal.signal(signal.SIGINT, old)


def _watch(**kw):
    exits: list[int] = []
    w = shutdown.Watcher(kw.pop("grace_s", 0.6), reach_s=kw.pop("reach_s", 0.2),
                         exit_fn=exits.append)
    return w, exits


def test_a_stuck_main_thread_still_sends_stop_then_exits(quiet_sigint):
    w, exits = _watch()
    link = Recorder()
    w.arm(link)
    try:
        os.kill(os.getpid(), signal.SIGINT)
        time.sleep(0.4)
        assert link.calls == ["emergency"] and w.forced
        assert link.muted                                   # only STOP from now on
        time.sleep(0.5)
        assert link.calls == ["emergency", "emergency"] and exits == [1]
    finally:
        w.close()


def test_a_reached_stop_sends_stop_and_is_not_forced(quiet_sigint):
    w, exits = _watch(grace_s=0.8, reach_s=0.3)
    link = Recorder()
    w.arm(link)
    try:
        os.kill(os.getpid(), signal.SIGINT)
        time.sleep(0.05)
        w.reached()
        time.sleep(0.4)
        assert link.calls == ["all_stop"] and not w.forced and exits == []
        time.sleep(0.6)                 # still alive after the grace: out, motors off first
        assert exits == [1] and link.calls[-1] == "emergency"
    finally:
        w.close()


def test_other_signals_are_ignored(quiet_sigint):
    w, exits = _watch()
    link = Recorder()
    w.arm(link)
    old = signal.signal(signal.SIGUSR1, lambda *_: None)
    try:
        os.kill(os.getpid(), signal.SIGUSR1)
        time.sleep(0.8)
        assert link.calls == [] and exits == []
    finally:
        signal.signal(signal.SIGUSR1, old)
        w.close()


def test_emergency_stop_ends_a_half_written_line_when_the_lock_is_held():
    link = Recorder()
    held = threading.Event()
    release = threading.Event()

    def writer():
        with _TX_LOCK:
            held.set()
            release.wait(2)

    t = threading.Thread(target=writer)
    t.start()
    held.wait(1)
    try:
        link.emergency_stop()
    finally:
        release.set()
        t.join()
    assert link.lines == [b"\nSTOP\n"]
    link.send("MOUTH 120 50")                   # muted: dropped
    link.send("STOP")
    assert link.lines == [b"\nSTOP\n", b"STOP\n"]


def test_emergency_stop_with_the_lock_free_is_a_plain_stop():
    link = Recorder()
    link.emergency_stop()
    assert link.lines == [b"STOP\n"] and link.muted


def test_resilient_link_mutes_and_passes_it_down():
    inner = Recorder()
    link = ResilientLink(SerialConfig(), lambda: inner)
    link.emergency_stop()
    assert inner.lines == [b"STOP\n"] and link.muted and inner.muted
    link.send("MOUTH 120 50")
    assert inner.lines == [b"STOP\n"]


def test_resilient_link_without_a_link_just_mutes():
    def fail():
        raise OSError("no port")
    link = ResilientLink(SerialConfig(), fail, retry_s=60)
    link.emergency_stop()
    assert link.muted
