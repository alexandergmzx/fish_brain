"""The fortune's ticket printer (the MP210 over Bluetooth RFCOMM): one worker owns the socket.

The act hands over a finished `ticket.Ticket` (plain values, built on the loop's thread) and
never waits: `submit` is a `put_nowait` on a queue of two. The worker lays the ticket out,
connects, sends the parts paced, waits for the tail and closes. It connects per ticket and
never holds the link between acts: the printer takes one connection at a time and skips
standby while connected.

    make_printer(cfg) -> Printer | None      empty FISH_PRINTER: None (the laptop)
    printer.submit(t) -> bool                the act, at the closing line; never blocks
    printer.keep(t)                          kept for Reprint only (tickets switched off)
    printer.reprint() -> (ok, n | why)       the page's button; refused while a job runs
    printer.probe() -> bool                  one connect and close, at an act's start
    printer.snapshot() -> dict               any thread
    printer.close()                          wakes the worker, joins 1 s at most

Failure policy: each connect is bounded by CONNECT_S and retried every RETRY_S until LATE_S
after the ticket was handed over (time queued behind another job counts, and no connect runs
past it); a stall or a drop mid-ticket fails with no resend (there is
no cutter, the paper would come out twice): Reprint is the human retry. A reason is logged
once until it changes.

Stand-ins: `MockPort` (FISH_PRINTER=mock) takes the bytes and logs the ticket as text; the
tests give a port on `socket.socketpair()`. The Bluetooth socket family is looked up only
when a real printer is set (`_bt`).
"""
from __future__ import annotations

import errno
import queue
import socket
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TextIO

from . import ticket
from .config import PrinterConfig

# ---- the printer's timing (estimate until the desk results: research.md #2, #8, #11) --------
CONNECT_S = 6.0          # one connect attempt; the Bluetooth page timeout is 5.12 s
RETRY_S = 2.0            # between attempts
LATE_S = 20.0            # give up this long after the hand-over (the closing line is 13 to 17 s)
WRITE_S = 5.0            # one piece not taken in this long: the printer stalled
CHUNK = 192              # bytes per sendall (the PT-210 SDK's pacing)
GAP_S = 0.04             # between pieces
TAIL_S = 0.5             # after the last byte, before closing (an immediate close may lose it)
REOPEN_S = 0.5           # between a close and the next connect (a fast reconnect gets EBUSY)
PROBE_S = 60.0           # a probe is skipped when the last contact is newer than this
JOIN_S = 1.0             # close() waits this long for the worker


@dataclass(frozen=True)
class Timing:
    connect_s: float = CONNECT_S
    retry_s: float = RETRY_S
    late_s: float = LATE_S
    write_s: float = WRITE_S
    chunk: int = CHUNK
    gap_s: float = GAP_S
    tail_s: float = TAIL_S
    reopen_s: float = REOPEN_S
    probe_s: float = PROBE_S


def _log(msg: str) -> None:
    print(f"[printer] {msg}", file=sys.stderr, flush=True)


def _bt() -> tuple[int, int]:
    family = getattr(socket, "AF_BLUETOOTH", None)
    proto = getattr(socket, "BTPROTO_RFCOMM", None)
    if family is None or proto is None:
        raise RuntimeError(
            "the ticket printer needs Bluetooth sockets (AF_BLUETOOTH, BTPROTO_RFCOMM): "
            "a Linux Python built with the BlueZ headers (apt update && apt install "
            "libbluetooth-dev, then rebuild), or FISH_PRINTER=mock")
    return family, proto


def _why(e: BaseException) -> str:
    """A short reason for a failed connect or send."""
    if isinstance(e, (socket.timeout, TimeoutError)):
        return "timed out"
    if isinstance(e, OSError) and e.errno:
        name = errno.errorcode.get(e.errno, str(e.errno))
        return f"{e.strerror or name} ({name})"
    return str(e) or type(e).__name__


def _shut(sock) -> None:
    """Wake whatever waits on `sock` (a connect, a sendall) without closing its descriptor."""
    try:
        sock.shutdown(socket.SHUT_RDWR)
    except (OSError, AttributeError):
        pass


def _close(sock) -> None:
    _shut(sock)
    try:
        sock.close()
    except OSError:
        pass


class _Stopped(Exception):
    pass


class _Late(Exception):
    """LATE_S after the hand-over has passed before a connect could start."""


# ---- ports: how a connection is made -----------------------------------------------------------
class RfcommPort:
    """The printer's Serial Port profile: stdlib RFCOMM, a fresh socket per connection."""

    def __init__(self, mac: str, channel: int):
        self.mac, self.channel = mac, channel
        self._lock = threading.Lock()
        self._sock = None

    def describe(self) -> str:
        return f"{self.mac} ch{self.channel}"

    def open(self, timeout: float):
        family, proto = _bt()
        s = socket.socket(family, socket.SOCK_STREAM, proto)
        s.settimeout(timeout)
        with self._lock:
            self._sock = s
        try:
            s.connect((self.mac, self.channel))
        except BaseException:
            _close(s)
            raise
        return s

    def abort(self) -> None:
        """Wake a connect in progress (close() from another thread)."""
        with self._lock:
            s = self._sock
        if s is not None:
            _shut(s)

    def show(self, text: str, n: int) -> None:
        pass                                     # the paper is the picture


class _MockConn:
    def __init__(self, port: "MockPort"):
        self._port = port

    def settimeout(self, _t) -> None:
        pass

    def sendall(self, data: bytes) -> None:
        self._port.data.extend(data)

    def shutdown(self, _how) -> None:
        pass

    def close(self) -> None:
        pass


class MockPort:
    """FISH_PRINTER=mock: every connect works at once, the bytes are kept (`data`, the last
    ticket's) and each printed ticket is logged as 32 columns of text."""

    def __init__(self, stream: TextIO | None = None):
        self.stream = stream
        self.data = bytearray()
        self.opened = 0

    def describe(self) -> str:
        return "mock"

    def open(self, timeout: float):
        self.opened += 1
        self.data = bytearray()
        return _MockConn(self)

    def abort(self) -> None:
        pass

    def show(self, text: str, n: int) -> None:
        out = self.stream or sys.stdout
        body = "".join(f"  | {line}\n" for line in text.rstrip("\n").split("\n"))
        out.write(f"[printer] mock ticket #{n} ({len(self.data)} bytes):\n{body}")
        out.flush()


def port_for(cfg: PrinterConfig, stream: TextIO | None = None):
    kind = cfg.kind()
    if kind == "mock":
        return MockPort(stream)
    if kind == "rfcomm":
        return RfcommPort(cfg.mac, cfg.channel)
    raise ValueError(cfg.problem() or "FISH_PRINTER is not set")


def summary(cfg: PrinterConfig) -> str:
    """The start-up line's word: off | mock | <MAC> ch<n>. A bad value is off."""
    kind = cfg.kind()
    if kind == "mock":
        return "mock"
    if kind == "rfcomm":
        return f"{cfg.mac} ch{cfg.channel}"
    return "off"


# ---- the printer ------------------------------------------------------------------------------
class Printer:
    def __init__(self, cfg: PrinterConfig, port=None, *, timing: Timing | None = None,
                 art_root: Path | str | None = None):
        self.cfg = cfg
        self.port = port if port is not None else port_for(cfg)
        self.timing = timing or Timing()
        self.art_root = art_root
        self._q: queue.Queue = queue.Queue(maxsize=2)
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._idle = threading.Condition(self._lock)
        self._thread = threading.Thread(target=self._run, name="printer", daemon=True)
        self._conn = None
        self._last: ticket.Ticket | None = None
        self._busy = 0                     # tickets queued or running
        self._probing = False
        self._closed_at = 0.0              # monotonic time of the last close (REOPEN_S)
        self._said = ""                    # the reason last logged
        # what snapshot() shows; written under the lock
        self._state = "idle"               # idle | queued | connecting | printing | printed | failed
        self._why = ""
        self._n: int | None = None
        self._reprint = False
        self._reach: bool | None = None    # the last connect worked; None = not tried yet
        self._contact: float | None = None
        self._bytes = 0
        self._seconds = 0.0
        self._connect_s = 0.0
        self._printed = 0
        self._failed = 0

    # ---- any thread ---------------------------------------------------------------------------
    def start(self) -> "Printer":
        if not self._thread.is_alive() and not self._stop.is_set():
            self._thread.start()
        return self

    def describe(self) -> str:
        return self.port.describe()

    def keep(self, t: ticket.Ticket) -> None:
        """Keep `t` as the ticket Reprint prints, without printing it."""
        with self._lock:
            self._last = t

    def submit(self, t: ticket.Ticket) -> bool:
        """Print `t` (and keep it for Reprint). Never blocks: False when the worker is not
        running or two jobs are already waiting."""
        with self._lock:
            self._last = t
            if not self._thread.is_alive() or self._stop.is_set():
                return False
            try:
                self._q.put_nowait(("ticket", t, False, time.monotonic()))
            except queue.Full:
                return False
            self._busy += 1
            if self._busy == 1:            # else the running one stays on show
                self._set(state="queued", n=t.n, why="", reprint=False)
        self._emit(t.n, "queued", reprint=False)
        return True

    def reprint(self) -> tuple[bool, int | str]:
        """The last ticket again: (True, n), or (False, why) with why "no ticket yet",
        "printing" or "no printer"."""
        with self._lock:
            t = self._last
            if t is None:
                return False, "no ticket yet"
            if not self._thread.is_alive() or self._stop.is_set():
                return False, "no printer"
            if self._busy:
                return False, "printing"
            try:
                self._q.put_nowait(("ticket", t, True, time.monotonic()))
            except queue.Full:
                return False, "printing"
            self._busy += 1
            self._set(state="queued", n=t.n, why="", reprint=True)
        self._emit(t.n, "queued", reprint=True)
        return True, t.n

    def probe(self) -> bool:
        """Queue one connect-and-close so the page knows whether the printer is there.
        Skipped while a ticket waits or runs, or when the last contact is recent."""
        with self._lock:
            if (self._busy or self._probing or not self._thread.is_alive()
                    or self._stop.is_set()):
                return False
            if (self._contact is not None
                    and time.monotonic() - self._contact < self.timing.probe_s):
                return False
            try:
                self._q.put_nowait(("probe", None, False, 0.0))
            except queue.Full:
                return False
            self._probing = True
        return True

    def wait(self, timeout: float) -> bool:
        """Until no ticket waits or runs (the one-shot); False on the timeout."""
        with self._idle:
            return self._idle.wait_for(lambda: self._busy == 0, timeout)

    def snapshot(self) -> dict:
        with self._lock:
            age = None if self._contact is None else round(time.monotonic() - self._contact, 1)
            return {"device": self.port.describe(), "alive": self._thread.is_alive(),
                    "state": self._state, "why": self._why, "n": self._n,
                    "reprint": self._reprint, "busy": self._busy > 0, "reach": self._reach,
                    "contact_age_s": age, "bytes": self._bytes,
                    "seconds": round(self._seconds, 2), "connect_s": round(self._connect_s, 2),
                    "printed": self._printed, "failed": self._failed,
                    "last_n": None if self._last is None else self._last.n}

    def close(self) -> None:
        """Wake the worker and join it briefly. A ticket mid-send is cut (shutdown)."""
        self._stop.set()
        try:
            self._q.put_nowait(None)
        except queue.Full:
            pass
        self.port.abort()
        with self._lock:
            conn = self._conn
        if conn is not None:
            _shut(conn)
        if self._thread.is_alive() and self._thread is not threading.current_thread():
            self._thread.join(timeout=JOIN_S)

    # ---- the worker ---------------------------------------------------------------------------
    def _set(self, **fields) -> None:
        for k, v in fields.items():
            setattr(self, "_" + k, v)

    def _emit(self, n, state, **fields) -> None:
        try:
            from . import debug
            debug.emit("ticket", n=n, state=state, **fields)
        except Exception:
            pass

    def _report(self, why: str) -> None:
        if why != self._said:              # say it once, not on every retry
            self._said = why
            _log(f"not reachable ({why}); the reading is spoken, Reprint prints it later")

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                job = self._q.get(timeout=0.2)
            except queue.Empty:
                continue
            if job is None:
                break
            kind, t, again, at = job
            try:
                if kind == "probe":
                    self._probe()
                else:
                    self._print(t, again, at)
            except Exception as e:         # a bug must not kill the worker
                _log(f"worker error: {type(e).__name__}: {e}")
                if kind == "ticket":
                    with self._lock:
                        self._set(state="failed", why=f"error: {type(e).__name__}")
                        self._failed += 1
            finally:
                with self._lock:
                    if kind == "probe":
                        self._probing = False
                    else:
                        self._busy -= 1
                        self._idle.notify_all()
        with self._lock:                   # stopped: nothing waits for the queue any more
            self._busy = 0
            self._idle.notify_all()

    def _pause(self, seconds: float) -> None:
        if seconds > 0 and self._stop.wait(seconds):
            raise _Stopped

    def _open(self, deadline: float | None = None):
        """One connect attempt, after the reopen gap, bounded by CONNECT_S and by `deadline`
        (monotonic) when one is given. Returns the connection."""
        self._pause(self.timing.reopen_s - (time.monotonic() - self._closed_at))
        limit = self.timing.connect_s
        if deadline is not None:
            limit = min(limit, deadline - time.monotonic())
            if limit <= 0:
                raise _Late
        conn = self.port.open(limit)
        with self._lock:
            self._conn = conn
        if self._stop.is_set():
            self._release(conn)
            raise _Stopped
        return conn

    def _release(self, conn) -> None:
        _close(conn)
        with self._lock:
            if self._conn is conn:
                self._conn = None
        self._closed_at = time.monotonic()

    def _contacted(self, ok: bool, why: str = "") -> None:
        with self._lock:
            self._reach = ok
            if ok:
                self._contact = time.monotonic()
        if ok and self._said:
            _log("reachable again")
            self._said = ""
        elif not ok:
            self._report(why)

    def _probe(self) -> None:
        try:
            conn = self._open()
        except _Stopped:
            return
        except Exception as e:
            self._contacted(False, _why(e))
            return
        self._release(conn)
        self._contacted(True)

    def _print(self, t: ticket.Ticket, again: bool, at: float) -> None:
        """`at` is the monotonic time of the hand-over: the time queued behind another job
        counts toward LATE_S."""
        t0 = time.monotonic()
        blocks = ticket.layout(t, art_root=self.art_root)
        parts = ticket.encode(blocks)
        size = sum(len(p) for p in parts)
        with self._lock:
            self._set(state="connecting", n=t.n, why="", reprint=again, bytes=size,
                      seconds=0.0, connect_s=0.0)
        self._emit(t.n, "connecting", reprint=again, bytes=size)
        deadline = at + self.timing.late_s
        conn = None
        why = ""
        while conn is None:
            c0 = time.monotonic()
            try:
                conn = self._open(deadline)
            except _Stopped:
                return self._done(t, again, t0, "failed", "stopped")
            except _Late:                  # queued past the limit, or no time left to connect
                return self._done(t, again, t0, "failed",
                                  f"not reachable ({why})" if why else "late")
            except RuntimeError as e:      # no Bluetooth sockets: retrying cannot help
                self._contacted(False, str(e))
                return self._done(t, again, t0, "failed", str(e))
            except Exception as e:
                why = _why(e)
                self._contacted(False, why)
                if time.monotonic() + self.timing.retry_s >= deadline:
                    return self._done(t, again, t0, "failed", f"not reachable ({why})")
                try:
                    self._pause(self.timing.retry_s)
                except _Stopped:
                    return self._done(t, again, t0, "failed", "stopped")
        connect_s = time.monotonic() - c0
        self._contacted(True)
        with self._lock:
            self._set(state="printing", connect_s=connect_s)
        self._emit(t.n, "printing", reprint=again, bytes=size, connect_s=round(connect_s, 2))
        try:
            self._send(conn, parts)
            self._pause(self.timing.tail_s)
        except _Stopped:
            return self._done(t, again, t0, "failed", "stopped", conn)
        except (socket.timeout, TimeoutError):
            return self._done(t, again, t0, "failed", "stalled", conn)
        except OSError as e:
            if self._stop.is_set():
                return self._done(t, again, t0, "failed", "stopped", conn)
            return self._done(t, again, t0, "failed", f"dropped ({_why(e)})", conn)
        self.port.show(ticket.preview(blocks), t.n)
        self._done(t, again, t0, "printed", "", conn)

    def _send(self, conn, parts: list[bytes]) -> None:
        conn.settimeout(self.timing.write_s)
        chunk = self.timing.chunk
        pieces = [p[i:i + chunk] for p in parts for i in range(0, len(p), chunk)] \
            if chunk > 0 else [p for p in parts if p]
        for i, piece in enumerate(pieces):
            if i:
                self._pause(self.timing.gap_s)
            conn.sendall(piece)

    def _done(self, t, again, t0, state, why, conn=None) -> None:
        if conn is not None:
            self._release(conn)
        seconds = time.monotonic() - t0
        with self._lock:
            self._set(state=state, why=why, seconds=seconds)
            if state == "printed":
                self._printed += 1
            else:
                self._failed += 1
            size, connect_s = self._bytes, self._connect_s
        self._emit(t.n, state, why=why, reprint=again, bytes=size,
                   seconds=round(seconds, 2), connect_s=round(connect_s, 2))
        what = "reprint" if again else "ticket"
        if state == "printed":
            _log(f"{what} #{t.n} printed: {size} bytes in {seconds:.1f} s "
                 f"(connect {connect_s:.1f} s)")
        else:
            _log(f"{what} #{t.n} failed: {why}")


def make_printer(cfg: PrinterConfig, *, stream: TextIO | None = None) -> Printer | None:
    """The started printer, or None: none set (the laptop), or a bad setting (one line,
    never an exit: a typo must not keep the fish down)."""
    kind = cfg.kind()
    if kind == "off":
        return None
    if kind == "bad":
        _log(f"off: {cfg.problem()}")
        return None
    if kind == "rfcomm":
        try:
            _bt()
        except RuntimeError as e:
            _log(f"off: {e}")
            return None
    return Printer(cfg, port_for(cfg, stream)).start()
