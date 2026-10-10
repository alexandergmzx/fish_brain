"""Minimal MessagePack-RPC client for the UNO Q's `arduino-router` daemon.

The router owns the internal UART to the STM32 (`/dev/ttyHS1`) and exposes a socket
(`/var/run/arduino-router.sock`). The wire format is a plain stream of MessagePack arrays,
with no length prefix and no handshake:

    request       [0, msgid, method, params]
    response      [1, msgid, error | None, result]      error = [code, message]
    notification  [2, method, params]                   no reply, ever

We use it for two things:
- `$/serial/close` / `$/serial/open`: ask the router to let go of (or take back) the UART so
  `SerialLink` can own the raw port.
- the Bridge transport: `fish_cmd` notifications to a Bridge sketch on the MCU.

`notify()` is built for the mouth stream: it never raises and never blocks for long. The router
has no queue, so a stalled UART shows up as a blocked `send()`; we give it 0.1 s, then drop the
frame, close the socket and reconnect on a later send.

`RouterWatchdog` notices router restarts. A restarted router silently re-opens the UART while we
still hold it (no write error on our side), so the only reliable signal is its socket going away.

`msgpack` is imported lazily: the laptop never needs it.
"""
from __future__ import annotations

import os
import socket
import sys
import threading
import time
from typing import Any, Callable, Optional

ERR_METHOD_NOT_AVAILABLE = 2   # nobody registered that method (MCU not up, or port released)
ERR_TOO_LARGE = 6              # message larger than the MCU accepts (256 B after Bridge.begin)


class RouterError(RuntimeError):
    """The router answered a call with an error."""

    def __init__(self, code: int, msg: str):
        super().__init__(f"router error {code}: {msg}")
        self.code = code
        self.msg = msg


def _log(msg: str) -> None:
    print(f"[router] {msg}", file=sys.stderr, flush=True)


def _msgpack():
    try:
        import msgpack
    except ImportError as e:
        raise ImportError("the arduino-router link needs msgpack: pip install msgpack") from e
    return msgpack


def parse_address(address: str) -> tuple[str, Any]:
    """'tcp://host:port' -> ('tcp', (host, port)); a path or 'unix:<path>' -> ('unix', path)."""
    if address.startswith("tcp://"):
        host, _, port = address[len("tcp://"):].rpartition(":")
        if not host or not port.isdigit():
            raise ValueError(f"bad router address {address!r} (want tcp://host:port)")
        return "tcp", (host.strip("[]"), int(port))     # allow tcp://[::1]:7600
    if address.startswith("unix:"):
        address = address[len("unix:"):]
    return "unix", address


def socket_path(address: str) -> Optional[str]:
    """The unix socket path behind `address`, or None for a TCP address."""
    kind, target = parse_address(address)
    return target if kind == "unix" else None


def _open_socket(address: str, timeout: float) -> socket.socket:
    kind, target = parse_address(address)
    if kind == "tcp":
        sock = socket.create_connection(target, timeout=timeout)
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        return sock
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        sock.settimeout(timeout)
        sock.connect(target)
    except OSError:
        sock.close()
        raise
    return sock


class RouterClient:
    """One connection to the router. Safe to share between threads."""

    def __init__(self, address: str, *, send_timeout: float = 0.1,
                 connect_timeout: float = 1.0, reconnect_s: float = 1.0):
        parse_address(address)               # fail early on a malformed address
        self._msgpack = _msgpack()
        self.address = address
        self._send_timeout = send_timeout
        self._connect_timeout = connect_timeout
        self._reconnect_s = reconnect_s      # notify() waits this long between reconnects
        self._lock = threading.Lock()
        self._sock: Optional[socket.socket] = None
        self._unpacker = None
        self._msgid = 0
        self._next_connect = 0.0
        self._dropping = False               # log the start and end of an outage only once

    # --- connection ---
    def _connect(self, timeout: Optional[float] = None) -> None:
        self._sock = _open_socket(self.address, timeout or self._connect_timeout)
        self._unpacker = self._msgpack.Unpacker(raw=False)

    def _drop(self) -> None:
        if self._sock is not None:
            try:
                self._sock.close()
            except OSError:
                pass
        self._sock = None
        self._unpacker = None

    def close(self) -> None:
        with self._lock:
            self._drop()

    # --- notifications: fire and forget ---
    def notify(self, method: str, *params: Any) -> bool:
        """Send a notification. Never raises; returns False when the frame was dropped."""
        try:
            frame = self._msgpack.packb([2, method, list(params)], use_bin_type=True)
        except Exception as e:
            _log(f"cannot encode {method}: {e}")
            return False
        with self._lock:
            try:
                if self._sock is None:
                    if time.monotonic() < self._next_connect:
                        return False
                    # Connecting is normally instant; cap it so an unreachable tcp://
                    # address cannot stall the mouth stream for the full connect timeout.
                    self._connect(min(self._connect_timeout, max(self._send_timeout, 0.25)))
                self._sock.settimeout(self._send_timeout)
                self._sock.sendall(frame)
            except OSError as e:
                # A timed-out sendall may have written half a frame, so the stream is no
                # longer usable: close it and start clean on a later send.
                self._drop()
                self._next_connect = time.monotonic() + self._reconnect_s
                if not self._dropping:
                    self._dropping = True
                    _log(f"send failed ({e or type(e).__name__}); dropping frames, will reconnect")
                return False
            if self._dropping:
                self._dropping = False
                _log("reconnected")
            return True

    # --- calls: wait for the answer ---
    def call(self, method: str, *params: Any, timeout: float = 1.0) -> Any:
        """Call a method and return its result.

        Raises RouterError (the router said no), TimeoutError (no answer in `timeout`
        seconds) or OSError (cannot reach the router / connection lost).
        """
        with self._lock:
            deadline = time.monotonic() + timeout
            if self._sock is None:
                self._connect()
            self._msgid = (self._msgid + 1) & 0x7FFFFFFF
            msgid = self._msgid
            try:
                self._sock.settimeout(timeout)
                self._sock.sendall(self._msgpack.packb([0, msgid, method, list(params)],
                                                       use_bin_type=True))
                while True:
                    for msg in self._unpacker:
                        if (isinstance(msg, (list, tuple)) and len(msg) == 4
                                and msg[0] == 1 and msg[1] == msgid):
                            return self._result(msg[2], msg[3])
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise TimeoutError(f"no answer to {method} in {timeout:g} s")
                    self._sock.settimeout(remaining)
                    chunk = self._sock.recv(4096)
                    if not chunk:
                        raise ConnectionError("the router closed the connection")
                    self._unpacker.feed(chunk)
            except RouterError:
                raise
            except OSError:
                self._drop()         # a late answer must not be mistaken for the next one
                raise
            except Exception as e:   # msgpack could not decode what came back
                self._drop()
                raise ConnectionError(f"unreadable answer to {method}: {e}") from e

    @staticmethod
    def _result(error: Any, result: Any) -> Any:
        if error is None:
            return result
        if isinstance(error, (list, tuple)) and len(error) >= 2:
            code, msg = error[0], error[1]
        else:
            code, msg = -1, error
        raise RouterError(int(code) if isinstance(code, int) else -1, str(msg))

    # --- the router's own methods ---
    def serial_close(self, port: str, *, timeout: float = 2.0) -> Any:
        """Ask the router to release its UART (returns once released; safe to repeat)."""
        return self.call("$/serial/close", port, timeout=timeout)

    def serial_open(self, port: str, *, timeout: float = 2.0) -> Any:
        """Ask the router to take its UART back (safe to repeat)."""
        return self.call("$/serial/open", port, timeout=timeout)

    def version(self) -> Any:
        return self.call("$/version")

    def __enter__(self) -> "RouterClient":
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        self.close()
        return False


class RouterWatchdog:
    """Background thread that calls `on_restart()` each time the router comes back.

    It keeps one idle connection to the router socket. The router is considered gone when that
    connection ends, fails, or the socket file is replaced (new inode). Once a new connection
    works, `on_restart()` runs; if it raises, the whole thing is retried with a growing pause
    (0.5 s doubling up to 5 s), because a freshly started router may not answer yet.

    A router that is down when the watchdog starts counts as "gone" too, so the callback also
    runs when it first appears. `assume_lost=True` runs it on the very first connection as
    well, for a caller whose own first attempt at the router failed.
    """

    def __init__(self, address: str, on_restart: Callable[[], None], *,
                 poll_s: float = 1.0, backoff_min_s: float = 0.5, backoff_max_s: float = 5.0,
                 assume_lost: bool = False):
        parse_address(address)
        self.address = address
        self._on_restart = on_restart
        self._poll_s = poll_s
        self._backoff_min = backoff_min_s
        self._backoff_max = backoff_max_s
        self._assume_lost = assume_lost
        self._stop = threading.Event()
        self._sock: Optional[socket.socket] = None
        self._thread: Optional[threading.Thread] = None
        self.restarts = 0                    # how many times on_restart() succeeded

    def start(self) -> "RouterWatchdog":
        if self._thread is None:
            self._thread = threading.Thread(target=self._run, name="router-watchdog",
                                            daemon=True)
            self._thread.start()
        return self

    def stop(self) -> None:
        self._stop.set()
        sock = self._sock
        if sock is not None:
            try:
                sock.shutdown(socket.SHUT_RDWR)   # wakes the thread out of recv()
            except OSError:
                pass
        if self._thread is not None and self._thread is not threading.current_thread():
            self._thread.join(timeout=self._poll_s + 0.5)

    def _inode(self) -> Optional[int]:
        path = socket_path(self.address)
        if path is None:
            return None
        try:
            return os.stat(path).st_ino
        except OSError:
            return None

    def _run(self) -> None:
        lost = self._assume_lost
        warned = False
        delay = self._backoff_min
        while not self._stop.is_set():
            try:
                sock = _open_socket(self.address, 1.0)
            except OSError:
                lost = True
                self._stop.wait(delay)
                delay = min(delay * 2, self._backoff_max)
                continue
            self._sock = sock
            inode = self._inode()
            if lost:
                try:
                    self._on_restart()
                except Exception as e:
                    if not warned:
                        warned = True
                        _log(f"router is back but the restart handler failed ({e}); retrying")
                    self._close(sock)
                    self._stop.wait(delay)
                    delay = min(delay * 2, self._backoff_max)
                    continue
                if self._stop.is_set():
                    self._close(sock)
                    return
                self.restarts += 1
            lost, warned, delay = False, False, self._backoff_min
            self._watch(sock, inode)
            self._close(sock)
            lost = True
            self._stop.wait(delay)

    def _watch(self, sock: socket.socket, inode: Optional[int]) -> None:
        """Block until the connection ends or the socket file changes."""
        sock.settimeout(self._poll_s)
        while not self._stop.is_set():
            try:
                if not sock.recv(4096):
                    return                       # EOF: the router went away
            except TimeoutError:
                if self._inode() != inode:
                    return
            except OSError:
                return

    def _close(self, sock: socket.socket) -> None:
        self._sock = None
        try:
            sock.close()
        except OSError:
            pass
