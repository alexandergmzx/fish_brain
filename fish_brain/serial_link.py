"""Link to the motor MCU: Uno R4 WiFi (laptop, `/dev/ttyACM0`) or UNO Q STM32U585 (`/dev/ttyHS1`).

The firmware is a thin executor: newline-terminated, upper-cased commands at 115200 baud,
PWM -255..255. It echoes every command back. Replies are never used as acknowledgements;
they are drained and counted, which tells whether the MCU is running at all.

Safety: the firmware has no current sensing (only a 5 s MAX_RUN_TIME watchdog), so this
link guarantees a STOP on close/exit/exception via the context-manager protocol.

Use `open_link(cfg, dry_run=...)` to get one of:
- `MockSerialLink`: prints commands instead of driving motors (`--dry-run`).
- `SerialLink`: pyserial on `cfg.port`. On the UNO Q (`/dev/ttyHS*`) the arduino-router daemon
  owns that port, so the link first asks the router to release it, watches for router
  restarts (which silently grab the port again) and gives the port back on close.
- `BridgeLink`: no serial port at all; commands travel as RPC notifications through the
  router to a Bridge sketch on the MCU.
- `ResilientLink`: wraps either of the two above when `cfg.required` is false. If the link
  cannot open, the fish keeps talking without motors and the open is retried.
"""
from __future__ import annotations

import errno
import fcntl
import os
import sys
import tempfile
import threading
import time
from typing import Callable, Optional

from . import debug
from .config import SerialConfig

# Where systemd keeps the router unit on the UNO Q image. If any exists, the router is
# expected to show up even when its socket is not there yet (early boot).
_ROUTER_UNIT_HINTS = (
    "/etc/systemd/system/arduino-router.service",
    "/usr/lib/systemd/system/arduino-router.service",
    "/run/systemd/generator/arduino-router.service.d/10-imola.conf",
)
_ROUTER_WAIT_S = 30.0
_router_waited = False         # the boot-time wait happens once per process, not per retry
_last_note = ""


def _log(msg: str) -> None:
    print(f"[link] {msg}", file=sys.stderr, flush=True)


def _note(msg: str) -> None:
    """Log, but not the same line twice in a row (the open is retried every few seconds)."""
    global _last_note
    if msg != _last_note:
        _last_note = msg
        _log(msg)


def _is_unoq_port(port: str) -> bool:
    return port.startswith("/dev/ttyHS")


class LinkBusy(RuntimeError):
    """Another process on this machine holds the motor port."""


def link_lock_path(port: str) -> str:
    """One lock file per port, shared with tools/uart_check.py and tools/fw_check.py."""
    name = f"fish_brain-{os.path.basename(port)}.lock"
    folder = "/run/lock"
    if not (os.path.isdir(folder) and os.access(folder, os.W_OK)):
        folder = tempfile.gettempdir()
    return os.path.join(folder, name)


def take_link_lock(port: str):
    """Claim `port` for this process, or raise `LinkBusy` naming the holder.

    On the UNO Q whoever opens the port also tells the router to let go of it and, when done,
    to take it back. A second opener would hand the UART to the router under the first one, so
    the claim comes before any word to the router. The lock dies with the process."""
    path = link_lock_path(port)
    f = open(path, "a+")
    try:
        fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        f.seek(0)
        holder = f.read().strip() or "unknown"
        f.close()
        raise LinkBusy(f"{port} is held by another fish process ({holder}); stop it first "
                       "(systemctl --user stop fish-brain)") from None
    f.seek(0)
    f.truncate()
    f.write(f"pid {os.getpid()} {os.path.basename(sys.argv[0] or 'python')}\n")
    f.flush()
    return f


class _LinkLog:
    """Optional record of every line written and every byte read back (`FISH_LINK_LOG`).
    A failing log switches itself off; it never raises into a turn."""

    MAX_BYTES = 8 * 1024 * 1024

    def __init__(self, path: str):
        self._path = path
        self._lock = threading.Lock()
        self._f = None
        if path:
            try:
                self._f = open(path, "a", buffering=1)
            except OSError as e:
                _log(f"link log off: {e}")

    @property
    def on(self) -> bool:
        return self._f is not None

    def _write(self, kind: str, text: str) -> None:
        if self._f is None:
            return
        try:
            with self._lock:
                self._f.write(f"{time.monotonic():.6f} {kind} {text}\n")
                if self._f.tell() > self.MAX_BYTES:
                    self._f.close()
                    os.replace(self._path, self._path + ".1")
                    self._f = open(self._path, "a", buffering=1)
        except (OSError, ValueError):
            self._f = None

    def tx(self, data: bytes) -> None:
        self._write("T", data.decode("ascii", "ignore").rstrip())

    def rx(self, data: bytes) -> None:
        if data:
            self._write("R", repr(data))

    def note(self, text: str) -> None:
        self._write("#", text)


_TX_LOCK = threading.Lock()      # guards the write of one line (see BaseLink.send)


class BaseLink:
    """Shared command helpers + rate limiting. Subclasses implement `_write_raw`."""

    def __init__(self, cfg: SerialConfig):
        self.cfg = cfg
        self._min_interval = 1.0 / cfg.max_cmd_hz if cfg.max_cmd_hz > 0 else 0.0
        self._last_send = 0.0
        self._last_mouth: Optional[int] = None

    # --- low level ---
    def _write_raw(self, data: bytes) -> None:  # pragma: no cover - abstract
        raise NotImplementedError

    # Muted (the debug page's switch): every line but STOP is dropped, the fish only talks.
    muted = False

    def mute(self, on: bool) -> None:
        """Motors off without closing the link. Muting sends STOP first; while muted nothing
        but STOP goes out (a phrase's close pulse too: nothing is being driven)."""
        if on:
            self.all_stop()
        self.muted = bool(on)

    def _held_back(self, command: str) -> bool:
        if self.muted and command.strip().upper() not in ("STOP", "S"):
            debug.tx(command.strip(), "muted")
            return True
        return False

    def send(self, command: str, *, throttle: bool = True) -> None:
        """Send one command line (newline appended). `throttle` paces high-rate streams."""
        if self._held_back(command):
            return
        if throttle and self._min_interval:
            now = time.monotonic()
            wait = self._min_interval - (now - self._last_send)
            if wait > 0:
                time.sleep(wait)
        line = command.strip().encode("ascii", "ignore") + self.cfg.newline
        # One writer at a time: the turn loop sends everything, but the debug page's STOP
        # comes from an HTTP thread and must not land inside another line.
        with _TX_LOCK:
            self._write_raw(line)
        debug.tx(command.strip())
        self._last_send = time.monotonic()

    # --- high level helpers ---
    def mouth(self, pwm: int) -> None:
        """Stream a mouth position. Skips redundant repeats of the same value."""
        pwm = max(-255, min(255, int(pwm)))
        if pwm == self._last_mouth:
            return
        self._last_mouth = pwm
        self.send(f"MOUTH {pwm}")

    def mouth_pulse(self, pwm: int, ms: int) -> None:
        """Fire a single timed mouth pulse (`MOUTH <pwm> <ms>`). No dedup: each pulse is a
        discrete move, so repeats are meaningful. Still rate-limited via send()'s throttle."""
        pwm = max(-255, min(255, int(pwm)))
        self._last_mouth = None  # a timed pulse invalidates the held-value dedup state
        self.send(f"MOUTH {pwm} {int(ms)}")

    def gesture(self, channel: str, chain_body: str) -> None:
        """Send a neck/tail timed-chain gesture, e.g. channel='NECK', body='180 450 -180 350'."""
        # Gestures are not throttled against the mouth stream cadence — they're rare.
        self.send(f"{channel.upper()} {chain_body}", throttle=False)

    def all_stop(self) -> None:
        self._last_mouth = None
        self.send("STOP", throttle=False)

    # --- context manager: guarantee a stop + clean close ---
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        try:
            self.all_stop()
        except Exception:
            pass
        self.close()
        return False

    def close(self) -> None:
        pass

    # --- status, for the startup summary ---
    @property
    def attached(self) -> bool:
        """False only while a `ResilientLink` has no working link underneath."""
        return True

    def describe(self) -> str:
        return "link"

    def health(self) -> str:
        """`ok`, `silent` (port open, nothing comes back from the MCU) or `off` (no link)."""
        return "ok"

    def wait_reply(self, timeout: float = 1.0) -> Optional[bool]:
        """True/False: the MCU did or did not send anything back. None: this link cannot tell."""
        return None


class SerialLink(BaseLink):
    def __init__(self, cfg: SerialConfig):
        super().__init__(cfg)
        self._released = False                    # we asked the router to let go of the port
        self._closing = False
        self._watchdog = None
        self._stop_first = threading.Event()      # the MCU was just reset: lead with STOP
        self._ser = None
        self._lock_file = None
        self._log_file = _LinkLog(cfg.log_path)
        # MCU liveness, from the firmware's echo: None until something was written.
        self._mcu_alive: Optional[bool] = None
        self._unanswered = 0                      # lines written since the last byte came back
        self._unanswered_since = 0.0
        if _is_unoq_port(cfg.port):
            self._lock_file = take_link_lock(cfg.port)    # before any word to the router
        if cfg.release_router and _is_unoq_port(cfg.port):
            self._release_router()
        try:
            import serial  # pyserial; imported lazily so --dry-run needs no hardware libs

            self._ser = serial.Serial(cfg.port, cfg.baud, timeout=0, write_timeout=1,
                                      rtscts=False)
        except Exception:
            self._router_cleanup()
            if self._lock_file is not None:
                self._lock_file.close()
                self._lock_file = None
            raise
        # Give the board a moment after the port opens (USB-CDC reset on some boards).
        time.sleep(0.3)
        try:
            self._ser.reset_input_buffer()
            # Whatever ran before us may have died mid-command: start from stopped.
            self._ser.write(self._stop_line())
            self._log_file.note("attach")
            self._log_file.tx(b"STOP")
        except Exception:
            self.close()                          # do not leave the router without its port
            raise

    def _stop_line(self) -> bytes:
        # The leading line end closes any stray bytes left in the firmware's line buffer
        # (an empty line does nothing there), so STOP arrives as STOP.
        return self.cfg.newline + b"STOP" + self.cfg.newline

    # --- UNO Q: take the UART from the arduino-router daemon ---
    def _release_router(self) -> None:
        from . import router_rpc

        cfg = self.cfg
        try:
            path = router_rpc.socket_path(cfg.router_socket)
        except ValueError as e:
            _note(f"router not asked to release {cfg.port}: {e}")
            return
        if path is not None and not os.path.exists(path):
            if not any(os.path.exists(p) for p in _ROUTER_UNIT_HINTS):
                return                            # no router on this machine: nothing holds it
            if not _wait_for_router(path):
                _note(f"router socket {path} did not appear; opening {cfg.port} anyway")
                self._watch_router(assume_lost=True)
                return
        try:
            with router_rpc.RouterClient(cfg.router_socket) as client:
                client.serial_close(cfg.port)
        except PermissionError:
            _note(f"router did not release {cfg.port}: no permission on {cfg.router_socket}. "
                  "Add arduino to group arduino-router and reboot/restart user@1000 "
                  "(router >= 0.11)")
            return
        except ImportError as e:
            _note(f"router did not release {cfg.port}: {e}")
            return
        except Exception as e:
            _note(f"router did not release {cfg.port}: {e}")
            # The router may simply not be up yet. If the port opens anyway, the router
            # will grab it too once it starts, so keep asking until it answers.
            self._watch_router(assume_lost=True)
            return
        self._released = True
        _note(f"router released {cfg.port}")
        self._watch_router()

    def _watch_router(self, *, assume_lost: bool = False) -> None:
        from . import router_rpc

        self._watchdog = router_rpc.RouterWatchdog(
            self.cfg.router_socket, self._on_router_restart, assume_lost=assume_lost).start()

    def _on_router_restart(self) -> None:
        """Runs on the watchdog thread. Raising makes the watchdog try again later."""
        from . import router_rpc

        if self._closing:
            return
        port = self.cfg.port
        with router_rpc.RouterClient(self.cfg.router_socket) as client:
            client.serial_close(port)
            if self._closing:
                # close() ran while we were asking and may already have handed the port
                # back; make sure the router ends up owning it.
                client.serial_open(port)
                return
        self._released = True
        # A restarting router pulses the MCU reset line, so whatever the motors were doing is
        # unknown and a stray byte may sit in the firmware's line buffer.
        self._stop_first.set()
        _log(f"router is back; released {port} again")

    def _router_cleanup(self) -> None:
        self._closing = True
        if self._watchdog is not None:
            self._watchdog.stop()
            self._watchdog = None
        if self._released:
            self._released = False
            from . import router_rpc

            try:
                with router_rpc.RouterClient(self.cfg.router_socket) as client:
                    client.serial_open(self.cfg.port)
                _note(f"router got {self.cfg.port} back")
            except Exception as e:
                _note(f"could not hand {self.cfg.port} back to the router: {e}")

    def _write_raw(self, data: bytes) -> None:
        if self._stop_first.is_set():
            self._stop_first.clear()
            self._last_mouth = None
            self._ser.write(self._stop_line())
            self._log_file.note("router is back")
            self._log_file.tx(b"STOP")
        self._ser.write(data)
        self._log_file.tx(data)
        # Replies are not used as acknowledgements. They are drained so the OS buffer does
        # not grow, and counted: the firmware echoes every character, so bytes coming back
        # mean the MCU is running. The port is non-blocking (timeout=0).
        try:
            got = self._ser.read(4096)
        except Exception:
            got = b""
        self._log_file.rx(got)
        debug.rx(got)
        self._note_reply(bool(got))

    def _note_reply(self, answered: bool) -> None:
        now = time.monotonic()
        if answered:
            if self._mcu_alive is False:
                _log(f"MCU answering again on {self.cfg.port}")
                self._log_file.note("MCU answering again")
            self._mcu_alive = True
            self._unanswered = 0
            return
        if self._unanswered == 0:
            self._unanswered_since = now
        self._unanswered += 1
        if (self._mcu_alive is not False and self._unanswered >= 20
                and now - self._unanswered_since >= 2.0):
            self._mcu_alive = False
            _log(f"MCU silent: nothing comes back on {self.cfg.port} (in reset, in its boot "
                 "animation, another sketch, or the router holds the port)")
            self._log_file.note("MCU silent")

    def wait_reply(self, timeout: float = 1.0) -> Optional[bool]:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                got = self._ser.read(4096)
            except Exception:
                return False
            if got:
                self._log_file.rx(got)
                debug.rx(got)
                self._note_reply(True)
                return True
            time.sleep(0.02)
        self._mcu_alive = False
        return False

    def health(self) -> str:
        return "silent" if self._mcu_alive is False else "ok"

    def close(self) -> None:
        try:
            if self._ser is not None:
                if self._log_file.on:             # the replies to the last lines, for the record
                    time.sleep(0.05)
                    self._log_file.rx(self._ser.read(4096))
                self._ser.close()
        except Exception:
            pass
        self._router_cleanup()
        if self._lock_file is not None:           # last: the router has its port back by now
            try:
                self._lock_file.close()
            except Exception:
                pass
            self._lock_file = None

    def describe(self) -> str:
        return f"serial {self.cfg.port}" + (" (MCU silent)" if self._mcu_alive is False else "")


def _wait_for_router(path: str) -> bool:
    """Wait for the router socket at boot. Our user service cannot order itself after the
    router's system unit, so it may simply be early."""
    global _router_waited
    if _router_waited:
        return os.path.exists(path)
    _router_waited = True
    _log(f"waiting up to {_ROUTER_WAIT_S:g} s for the router socket {path}")
    deadline = time.monotonic() + _ROUTER_WAIT_S
    while time.monotonic() < deadline:
        if os.path.exists(path):
            return True
        time.sleep(0.5)
    return os.path.exists(path)


class BridgeLink(BaseLink):
    """Commands go as `fish_cmd("<line>")` RPC notifications through the arduino-router to a
    Bridge sketch on the MCU. Nothing is opened on our side but the router socket."""

    def __init__(self, cfg: SerialConfig):
        super().__init__(cfg)
        from . import router_rpc

        self._router_error = router_rpc.RouterError
        self._client = router_rpc.RouterClient(cfg.router_socket)
        try:
            self._attach_router_serial()
            self._ping()
        except Exception:
            self._client.close()
            raise

    def _attach_router_serial(self) -> None:
        """Undo an earlier `$/serial/close` (ours or by hand). Harmless when already open."""
        cfg = self.cfg
        if not _is_unoq_port(cfg.port):
            # FISH_SERIAL_PORT still names the laptop's USB port: never ask the router to
            # open that. The ping below tells whether the bridge works anyway.
            return
        try:
            self._client.serial_open(cfg.port)
        except self._router_error as e:
            _note(f"router could not open {cfg.port}: {e}")

    def _ping(self) -> None:
        from . import router_rpc

        ping = self.cfg.bridge_ping_method
        try:
            self._client.call(ping)
        except self._router_error as e:
            if e.code != router_rpc.ERR_METHOD_NOT_AVAILABLE:
                raise RuntimeError(f"{ping} failed: {e}") from e
            raise RuntimeError(
                f"{ping} not registered: the router serial was released (`$/serial/close`) "
                "or no Bridge sketch is running. Run `deploy/unoq_setup.sh router restore`, "
                "then reset/reflash the MCU (a sketch that booted while the port was "
                "released, or one built with wait_linux_boot=no, is stuck in Bridge.begin()). "
                "Otherwise flash tools/sketches/bridge_echo or a Bridge build of the firmware."
            ) from e

    def _write_raw(self, data: bytes) -> None:
        self._client.notify(self.cfg.bridge_method, data.decode("ascii", "ignore").strip())

    def all_stop(self) -> None:
        """STOP goes out twice: as a call, so we learn whether the MCU took it, and as a
        notification in case the call got no answer."""
        self._last_mouth = None
        try:
            self._client.call(self.cfg.bridge_method, "STOP", timeout=0.5)
        except Exception as e:
            _note(f"STOP was not confirmed by the bridge: {e}")
        self._client.notify(self.cfg.bridge_method, "STOP")
        self._last_send = time.monotonic()

    def close(self) -> None:
        self._client.close()

    def describe(self) -> str:
        return f"bridge {self.cfg.bridge_method}"


class MockSerialLink(BaseLink):
    """Prints commands instead of driving motors. For --dry-run testing."""

    def __init__(self, cfg: SerialConfig, stream=sys.stdout):
        super().__init__(cfg)
        self._stream = stream

    def _write_raw(self, data: bytes) -> None:
        self._stream.write("  TX  " + data.decode("ascii", "ignore").rstrip() + "\n")
        self._stream.flush()

    def describe(self) -> str:
        return "mock"


class ResilientLink(BaseLink):
    """Keeps the fish talking when the motor link is missing.

    Holds the real link, or nothing. With nothing underneath, commands are dropped silently
    and the open is retried in the background, at most every `retry_s` seconds and only when
    something is being sent. An error from the real link drops it instead of raising.
    """

    def __init__(self, cfg: SerialConfig, factory: Callable[[], BaseLink], *,
                 retry_s: float = 5.0, label: Optional[str] = None):
        super().__init__(cfg)
        self._factory = factory
        self._retry_s = retry_s
        self._label = label or _describe_cfg(cfg)
        self._link: Optional[BaseLink] = None
        self._attach_lock = threading.Lock()      # one open attempt at a time
        self._state_lock = threading.Lock()       # guards _link swaps and _retrying
        self._retrying = False
        self._closed = False
        self._last_try = 0.0
        self._last_error = ""
        self.try_attach()

    @property
    def attached(self) -> bool:
        return self._link is not None

    def describe(self) -> str:
        link = self._link
        return link.describe() if link is not None else f"{self._label} (degraded)"

    def try_attach(self) -> bool:
        """Try to open the real link now (blocks while it tries). True when attached."""
        with self._attach_lock:
            if self._link is not None:
                return True
            if self._closed:
                return False
            self._last_try = time.monotonic()
            try:
                link = self._factory()
            except Exception as e:
                self._report_down(e)
                return False
            finally:
                self._last_try = time.monotonic()
            with self._state_lock:
                closed = self._closed
                if not closed:
                    self._last_mouth = None
                    self._last_error = ""
                    self._link = link
            if closed:                            # close() ran while we were opening
                _close_quietly(link)
                return False
            _log("attached")
            return True

    def health(self) -> str:
        link = self._link
        return link.health() if link is not None else "off"

    def wait_reply(self, timeout: float = 1.0) -> Optional[bool]:
        link = self._link
        return link.wait_reply(timeout) if link is not None else None

    def _report_down(self, exc: BaseException) -> None:
        if isinstance(exc, LinkBusy):
            reason = str(exc)
        elif getattr(exc, "errno", None) == errno.EBUSY:
            reason = "EBUSY: router still holds it"
        else:
            reason = str(exc) or type(exc).__name__
        if reason != self._last_error:            # say it once, not on every retry
            self._last_error = reason
            _log(f"{self._label} unavailable ({reason}) — voice-only mode, retrying")

    def _detach(self, link: BaseLink, exc: BaseException) -> None:
        """Drop `link` after it failed. A late error from a link that was already replaced
        must not take the new one down with it."""
        with self._state_lock:
            if self._link is not link:
                return
            self._link = None
            self._last_mouth = None
            self._last_try = time.monotonic()
        self._report_down(exc)
        _close_quietly(link)

    def _retry_in_background(self) -> None:
        with self._state_lock:
            if (self._retrying or self._closed
                    or time.monotonic() - self._last_try < self._retry_s):
                return
            self._retrying = True

        def attempt() -> None:
            try:
                self.try_attach()
            finally:
                self._retrying = False

        # Opening can take seconds (router calls, port settle time); the caller is
        # streaming mouth frames against the audio clock and must not wait for it.
        threading.Thread(target=attempt, name="link-retry", daemon=True).start()

    def send(self, command: str, *, throttle: bool = True) -> None:
        if self._held_back(command):
            return
        link = self._link
        if link is None:
            debug.tx(command.strip(), "dropped")
            self._retry_in_background()
            return
        try:
            link.send(command, throttle=throttle)
        except Exception as e:
            self._detach(link, e)

    def all_stop(self) -> None:
        self._last_mouth = None
        link = self._link
        if link is None:
            return
        try:
            link.all_stop()
        except Exception as e:
            self._detach(link, e)

    def close(self) -> None:
        with self._state_lock:
            self._closed = True
            link, self._link = self._link, None
        if link is not None:
            _close_quietly(link)


def _close_quietly(link: BaseLink) -> None:
    try:
        link.close()
    except Exception as e:
        _log(f"closing {link.describe()} failed: {e}")


def _describe_cfg(cfg: SerialConfig) -> str:
    if cfg.transport.strip().lower() == "bridge":
        return f"bridge {cfg.bridge_method}"
    return f"serial {cfg.port}"


def open_link(cfg: SerialConfig, *, dry_run: bool = False) -> BaseLink:
    """Mock for a dry run; else the transport named by `cfg.transport`. With `cfg.required`
    an open failure raises; without it the link comes back degraded and retries."""
    if dry_run:
        return MockSerialLink(cfg)
    transport = cfg.transport.strip().lower()
    if transport == "serial":
        factory: Callable[[], BaseLink] = lambda: SerialLink(cfg)
    elif transport == "bridge":
        factory = lambda: BridgeLink(cfg)
    else:
        raise ValueError(
            f"unknown serial transport {cfg.transport!r} (FISH_SERIAL_TRANSPORT: serial|bridge)")
    if cfg.required:
        return factory()
    return ResilientLink(cfg, factory)
