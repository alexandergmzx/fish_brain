"""A stop signal always reaches STOP, even when the main thread is stuck.

The SIGINT/SIGTERM handlers raise KeyboardInterrupt, but Python runs a handler only when the
main thread gets back to Python. On 2026-10-13 the fish sat inside PortAudio, ignored the stop
signal until systemd killed it 15 s later, and no STOP was sent. The C-level signal handler
still writes the signal number to the wakeup fd, so a watcher thread notices the signal at
once: if the main thread has not reached its stop within `reach_s`, the watcher sends STOP
itself and mutes the link. Either way, `grace_s` after the signal it sends STOP once more and
exits hard, before the unit's TimeoutStopSec.
"""
from __future__ import annotations

import os
import signal
import sys
import threading
import time
from typing import Callable, Optional

_STOP_SIGNALS = (signal.SIGINT, signal.SIGTERM)


class Watcher:
    def __init__(self, grace_s: float, *, reach_s: float = 1.0,
                 exit_fn: Callable[[int], None] = os._exit):
        self.grace_s = grace_s
        self.reach_s = reach_s
        self._exit = exit_fn
        self._link = None
        self._reached = threading.Event()
        self._signalled = threading.Event()
        self.forced = False               # True once the watcher had to send STOP itself
        self._r, self._w = os.pipe()
        os.set_blocking(self._w, False)
        self._previous_fd = signal.set_wakeup_fd(self._w, warn_on_full_buffer=False)
        threading.Thread(target=self._watch, name="stop-watch", daemon=True).start()

    def arm(self, link) -> None:
        self._link = link

    def reached(self) -> None:
        """The main thread got to its stop: send STOP now, the goodbye may still move."""
        self._reached.set()
        link = self._link
        if link is not None:
            try:
                link.all_stop()
            except Exception:
                pass

    def close(self) -> None:
        signal.set_wakeup_fd(self._previous_fd)

    def _watch(self) -> None:
        while True:
            try:
                data = os.read(self._r, 64)
            except OSError:
                return
            if not data:
                return
            if self._signalled.is_set() or not any(b in _STOP_SIGNALS for b in data):
                continue
            self._signalled.set()
            from . import record
            record.write("stop", {"signal": signal.Signals(data[0]).name
                                  if data[0] in _STOP_SIGNALS else data[0]})
            threading.Thread(target=self._after_signal, name="stop-grace",
                             daemon=True).start()

    def _after_signal(self) -> None:
        t0 = time.monotonic()
        from . import record
        if not self._reached.wait(self.reach_s):
            self.forced = True
            record.write("stop", {"forced": True})
            print("[stop] the main thread is stuck: STOP sent from the watcher",
                  file=sys.stderr, flush=True)
            self._emergency()
        # A normal stop ends the process (and this daemon thread) well inside the grace.
        # Still alive after it: whatever the main thread is doing, motors off and out.
        time.sleep(max(0.0, self.grace_s - (time.monotonic() - t0)))
        print("[stop] still running after the grace: STOP and exit", file=sys.stderr, flush=True)
        self._emergency()
        record.write("stop", {"exit": "grace"})
        record.flush()
        self._exit(1)

    def _emergency(self) -> None:
        link = self._link
        if link is None:
            return
        try:
            link.emergency_stop()
        except Exception as e:
            print(f"[stop] emergency STOP failed: {e}", file=sys.stderr, flush=True)


_watcher: Optional[Watcher] = None


def install(grace_s: float) -> Optional[Watcher]:
    """Start the watcher (main thread only). None where wakeup fds cannot be set."""
    global _watcher
    if _watcher is not None:
        return _watcher
    try:
        _watcher = Watcher(grace_s)
    except (ValueError, OSError):           # not the main thread, or no pipes
        _watcher = None
    return _watcher


def installed() -> bool:
    return _watcher is not None


def arm(link) -> None:
    if _watcher is not None:
        _watcher.arm(link)


def reached() -> None:
    if _watcher is not None:
        _watcher.reached()
