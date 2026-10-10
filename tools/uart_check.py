#!/usr/bin/env python3
"""Soak test for the Linux <-> motor-MCU command link.

Sends numbered lines at a fixed rate and counts the replies, so a link can be judged
with numbers (loss, round-trip time, achieved rate) before any motor is wired:

    tools/uart_check.py --port /dev/ttyACM0 --expect any      # laptop, real firmware
    tools/uart_check.py --release-router                      # UNO Q, uart_echo sketch
    tools/uart_check.py --transport bridge                    # UNO Q, bridge_echo sketch
    tools/uart_check.py --self-test                           # no hardware at all

The default payload `PING {n}` is motor-safe on every target: the echo sketches answer
`ACK PING <n>` (`--expect ack`) and the real firmware answers `Unknown command. Type HELP`
(`--expect any`, which counts one reply line per sent line and skips the firmware's echo).

UNO Q notes. The arduino-router daemon owns /dev/ttyHS1. `--release-router` asks it to
let go (`$/serial/close`) and hands the port back (`$/serial/open`) on exit, also after
Ctrl-C or an error, unless `--keep-released` is given. While the port is released every
Bridge method is unregistered, so a Bridge sketch needs an MCU reset after the hand-back.
`--transport bridge` sends each line as a `fish_cmd` notification through the router and
reads the replies from the router's Monitor port (TCP 127.0.0.1:7500).

This file is standalone on purpose (no fish_brain import): copy it to any machine with
Python 3. It needs `pyserial` for the serial transport and `msgpack` only when it talks
to the router.

Exit code: 0 = no loss, 1 = lost lines, 2 = could not run the test, 130 = interrupted
(the partial numbers are still printed).
"""
from __future__ import annotations

import argparse
import collections
import math
import os
import signal
import socket
import sys
import threading
import time
from dataclasses import dataclass, field
from typing import Callable, Optional

DEFAULT_COUNT = 1000
DEFAULT_HZ = 33.0
JUNK_WINDOW_S = 0.5     # listen this long after opening, to report boot text / stale bytes
MAX_SAMPLES = 8         # garbage lines shown in the report
PING_METHOD = "fish_ping"


class SetupError(Exception):
    """The test could not start (port busy, router unreachable, missing module)."""


# --- arduino-router: MessagePack-RPC over a stream socket -------------------------------

class RouterError(Exception):
    def __init__(self, code: object, message: object):
        super().__init__(f"router error {code}: {message}")
        self.code = code


class RouterRPC:
    """Tiny client: bare MessagePack arrays on a unix path or `tcp://host:port`.

    Request `[0, id, method, params]` -> response `[1, id, error, result]`;
    notification `[2, method, params]` gets no answer at all.
    """

    def __init__(self, address: str, timeout: float = 2.0):
        try:
            import msgpack  # lazy: only the router paths need it
        except ImportError as e:
            raise SetupError("the router paths need the 'msgpack' module "
                             "(pip install msgpack)") from e
        self._mp = msgpack
        self._id = 0
        try:
            if address.startswith("tcp://"):
                host, _, port = address[len("tcp://"):].rpartition(":")
                self._sock = socket.create_connection((host, int(port)), timeout=timeout)
            else:
                self._sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                self._sock.settimeout(timeout)
                self._sock.connect(address)
        except (OSError, ValueError) as e:
            raise SetupError(f"cannot reach the router at {address}: {e}") from e
        self._sock.settimeout(timeout)
        self._timeout = timeout

    def notify(self, method: str, *params: object) -> None:
        self._sock.sendall(self._mp.packb([2, method, list(params)]))

    def call(self, method: str, *params: object) -> object:
        self._id += 1
        self._sock.sendall(self._mp.packb([0, self._id, method, list(params)]))
        unpacker = self._mp.Unpacker(raw=False)
        deadline = time.monotonic() + self._timeout
        while True:
            # The deadline covers a router that keeps talking but never answers us.
            if time.monotonic() > deadline:
                raise OSError(f"no answer to {method} in {self._timeout:g} s")
            data = self._sock.recv(4096)    # socket.timeout (an OSError) when no answer
            if not data:
                raise OSError("router closed the connection")
            unpacker.feed(data)
            for msg in unpacker:
                if isinstance(msg, list) and len(msg) == 4 and msg[:2] == [1, self._id]:
                    if msg[2] is not None:
                        err = msg[2] if isinstance(msg[2], list) else [None, msg[2]]
                        raise RouterError(err[0], err[-1])
                    return msg[3]

    def close(self) -> None:
        try:
            self._sock.close()
        except OSError:
            pass


# --- transports: write one line, read whatever comes back ---------------------------------

class SerialTransport:
    """Raw lines on a tty (pyserial). No flow control, like the firmware link."""

    def __init__(self, port: str, baud: int):
        try:
            import serial  # lazy: bridge mode and --help work without pyserial
        except ImportError as e:
            raise SetupError("the serial transport needs 'pyserial' "
                             "(pip install pyserial)") from e
        try:
            self._ser = serial.Serial(port, baud, timeout=0.05, write_timeout=1,
                                      rtscts=False, dsrdtr=False, xonxoff=False)
        except (serial.SerialException, OSError) as e:
            hint = ""
            if port.startswith("/dev/ttyHS"):
                hint = " (on the UNO Q the router holds this port: add --release-router)"
            raise SetupError(f"cannot open {port}: {e}{hint}") from e
        self.label = f"serial {port} @ {baud}"

    def write_line(self, line: str) -> None:
        self._ser.write(line.encode("ascii", "ignore") + b"\n")

    def read(self) -> bytes:
        return self._ser.read(self._ser.in_waiting or 1)

    def close(self) -> None:
        try:
            self._ser.close()
        except Exception:
            pass


class BridgeTransport:
    """Lines out as router notifications, replies in from the router's Monitor TCP port."""

    def __init__(self, router_socket: str, method: str, port: str, monitor: str,
                 timeout: float):
        self._rpc = RouterRPC(router_socket, timeout)
        self._method = method
        self._mon: Optional[socket.socket] = None
        try:
            # Idempotent: makes sure the router owns the UART (a raw-UART run may have
            # released it). Methods of a sketch that booted meanwhile stay unregistered.
            self._rpc.call("$/serial/open", port)
            try:
                self._rpc.call(PING_METHOD)
            except RouterError as e:
                if e.code == 2:
                    raise SetupError(
                        f"'{PING_METHOD}' is not registered: no Bridge sketch is running, "
                        "or it booted while the router had released the port. Flash "
                        "tools/sketches/bridge_echo (or reset the MCU) and retry.") from e
                print(f"[uart_check] {PING_METHOD}: {e} (continuing)")
            host, _, mport = monitor.rpartition(":")
            self._mon = socket.create_connection((host or "127.0.0.1", int(mport)),
                                                 timeout=timeout)
            self._mon.settimeout(0.05)
        except (OSError, ValueError, RouterError) as e:
            self.close()
            raise SetupError(f"bridge transport setup failed: {e}") from e
        except SetupError:
            self.close()
            raise
        self.label = f"bridge {method} via {router_socket}, replies from {monitor}"

    def write_line(self, line: str) -> None:
        self._rpc.notify(self._method, line)

    def read(self) -> bytes:
        assert self._mon is not None
        try:
            data = self._mon.recv(4096)
        except socket.timeout:
            return b""
        if not data:
            raise OSError("monitor port closed the connection")
        return data

    def close(self) -> None:
        self._rpc.close()
        if self._mon is not None:
            try:
                self._mon.close()
            except OSError:
                pass


# --- matching replies to sent lines -----------------------------------------------------------

@dataclass
class Result:
    sent: int = 0
    acked: int = 0
    duplicates: int = 0
    echoes: int = 0
    rtts_ms: list = field(default_factory=list)
    garbage: list = field(default_factory=list)   # reply-phase lines that match nothing
    junk: list = field(default_factory=list)      # lines seen before the first send
    achieved_hz: float = 0.0
    error: str = ""

    @property
    def lost(self) -> int:
        return self.sent - self.acked


class Matcher:
    """Pairs incoming lines with sent lines. Fed by the reader thread, read by main."""

    def __init__(self, expect: str):
        self.expect = expect
        self.res = Result()
        self.lock = threading.Lock()
        self.running = False                 # False = still in the junk window
        self.all_acked = threading.Event()
        self.target = 0
        self._sent_at: dict = {}             # send index -> monotonic send time
        self._by_text: dict = {}             # payload text -> deque of unanswered indices
        self._fifo: collections.deque = collections.deque()
        self._texts: set = set()
        self._answered: set = set()

    def sent(self, n: int, text: str) -> None:
        with self.lock:
            self._sent_at[n] = time.monotonic()
            self._by_text.setdefault(text, collections.deque()).append(n)
            self._fifo.append(n)
            self._texts.add(text.strip().upper())
            self.res.sent += 1

    def _ack(self, n: int, t: float) -> None:
        self.res.acked += 1
        self.res.rtts_ms.append((t - self._sent_at[n]) * 1000.0)
        if self.target and self.res.acked >= self.target:
            self.all_acked.set()

    def line(self, t: float, raw: bytes) -> None:
        text = raw.decode("utf-8", "replace").strip()
        with self.lock:
            if not self.running:
                if text:
                    self.res.junk.append(text)
                return
            if self.expect == "ack":
                body = text[4:] if text.startswith("ACK ") else None
                pending = self._by_text.get(body) if body is not None else None
                if pending:
                    n = pending.popleft()
                    self._answered.add(body)
                    self._ack(n, t)
                elif body is not None and body in self._answered:
                    self.res.duplicates += 1
                elif text:
                    self.res.garbage.append(text)
                return
            # "any": one reply line per sent line. The real firmware echoes what it
            # receives and prints a "> " prompt; neither is a reply.
            while text.startswith(">"):
                text = text[1:].lstrip()
            if not text:
                return
            if text.upper() in self._texts:
                self.res.echoes += 1
            elif self._fifo:
                self._ack(self._fifo.popleft(), t)
            else:
                self.res.garbage.append(text)


def _reader(read: Callable[[], bytes], matcher: Matcher, stop: threading.Event) -> None:
    buf = b""
    while not stop.is_set():
        try:
            data = read()
        except Exception as e:  # unplugged port, closed monitor: end the run with a note
            with matcher.lock:
                matcher.res.error = matcher.res.error or f"read failed: {e}"
            matcher.all_acked.set()
            return
        if not data:
            continue
        t = time.monotonic()
        buf += data
        while True:
            cut = min((i for i in (buf.find(b"\n"), buf.find(b"\r")) if i >= 0), default=-1)
            if cut < 0:
                break
            matcher.line(t, buf[:cut])
            buf = buf[cut + 1:]
        if len(buf) > 4096:     # a stream with no line ends: report it, don't grow forever
            matcher.line(t, buf)
            buf = b""


def run_check(transport, *, count: int, hz: float, payload: str, expect: str,
              timeout: float, quiet: bool = False) -> Result:
    """Send `count` lines at `hz` on `transport`, wait up to `timeout` s for late replies."""
    matcher = Matcher(expect)
    stop = threading.Event()
    reader = threading.Thread(target=_reader, args=(transport.read, matcher, stop),
                              daemon=True)
    reader.start()
    res = matcher.res
    first = last = 0.0
    try:
        time.sleep(JUNK_WINDOW_S)
        with matcher.lock:
            matcher.running = True
            matcher.target = count
        period = 1.0 / hz
        t0 = time.monotonic()
        next_note = t0 + 5.0
        for n in range(1, count + 1):
            # One monotonic schedule for the whole run: a late line does not push the
            # following ones later (same pacing idea as the app's command stream).
            wait = t0 + (n - 1) * period - time.monotonic()
            if wait > 0:
                time.sleep(wait)
            text = payload.format(n=n)
            matcher.sent(n, text)
            try:
                transport.write_line(text)
            except Exception as e:
                res.error = res.error or f"write failed at line {n}: {e}"
                break
            last = time.monotonic()
            first = first or last
            if res.error:
                break
            if not quiet and last >= next_note:
                next_note = last + 5.0
                with matcher.lock:
                    print(f"[uart_check] sent {res.sent}/{count}  acked {res.acked}",
                          flush=True)
        if not res.error:
            matcher.all_acked.wait(timeout)
    except KeyboardInterrupt:
        res.error = "interrupted"       # still print what was measured so far
    finally:
        stop.set()
        reader.join(1.0)
        if res.sent > 1 and last > first:
            res.achieved_hz = (res.sent - 1) / (last - first)
    return res


def _percentile(values: list, p: float) -> float:
    ordered = sorted(values)
    return ordered[max(0, math.ceil(p * len(ordered)) - 1)]


def report(res: Result, label: str, hz: float) -> None:
    pct = 100.0 * res.lost / res.sent if res.sent else 0.0
    print(f"link      {label}")
    print(f"sent      {res.sent}")
    print(f"acked     {res.acked}")
    print(f"lost      {res.lost} ({pct:.2f} %)")
    if res.rtts_ms:
        r = res.rtts_ms
        print(f"rtt ms    min {min(r):.2f}  avg {sum(r) / len(r):.2f}  "
              f"p95 {_percentile(r, 0.95):.2f}  max {max(r):.2f}")
    else:
        print("rtt ms    n/a (no replies)")
    print(f"rate      {res.achieved_hz:.1f} Hz achieved (asked {hz:g})")
    if res.duplicates:
        print(f"dup       {res.duplicates} repeated ACK lines")
    if res.echoes:
        print(f"echo      {res.echoes} echoed lines skipped")
    for name, lines in (("junk", res.junk), ("garbage", res.garbage)):
        where = "before the first send" if name == "junk" else "lines that match nothing"
        print(f"{name:<9} {len(lines)} {where}")
        for text in lines[:MAX_SAMPLES]:
            print(f"            {text[:80]!r}")
        if len(lines) > MAX_SAMPLES:
            print(f"            ... {len(lines) - MAX_SAMPLES} more")
    if res.error:
        print(f"error     {res.error}")
    print("RESULT    " + ("PASS" if res.sent and not res.lost and not res.error else "FAIL"))


# --- self-test: a pty pair and a fake router, no hardware ---------------------------------------

def _pty_peer(mode: str, drop_every: int = 0):
    """Open a pty; a thread on the master end plays the MCU. Returns (slave path, stop)."""
    import tty

    master, slave = os.openpty()
    tty.setraw(master)
    tty.setraw(slave)
    path = os.ttyname(slave)
    stop = threading.Event()

    def serve() -> None:
        # A reset banner / stray byte, sent once the port is open (pyserial flushes
        # whatever was queued before the open).
        time.sleep(0.2)
        os.write(master, b"\x00boot junk\r\n")
        buf, seen = b"", 0
        while not stop.is_set():
            try:
                data = os.read(master, 4096)
            except OSError:
                return
            buf += data
            while b"\n" in buf:
                line, buf = buf.split(b"\n", 1)
                seen += 1
                if drop_every and seen % drop_every == 0:
                    continue
                if mode == "firmware":      # echo, reply, prompt (like the real firmware)
                    os.write(master, line + b"\r\nUnknown command. Type HELP\r\n> ")
                else:
                    os.write(master, b"ACK " + line + b"\r\n")
                    if seen == 7:
                        os.write(master, b"stray line\r\n")

    threading.Thread(target=serve, daemon=True).start()

    def close() -> None:
        stop.set()
        for fd in (master, slave):
            try:
                os.close(fd)
            except OSError:
                pass

    return path, close


class _FakeRouter:
    """Unix-socket router + TCP monitor. Records calls; ACKs `fish_cmd` on the monitor."""

    def __init__(self, sock_path: str):
        import msgpack

        self._mp = msgpack
        self.calls: list = []
        self._monitors: list = []
        self._unix = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self._unix.bind(sock_path)
        self._unix.listen(4)
        self._tcp = socket.socket()
        self._tcp.bind(("127.0.0.1", 0))
        self._tcp.listen(4)
        self.monitor = f"127.0.0.1:{self._tcp.getsockname()[1]}"
        threading.Thread(target=self._accept, args=(self._unix, self._client),
                         daemon=True).start()
        threading.Thread(target=self._accept, args=(self._tcp, self._monitors.append),
                         daemon=True).start()

    def _accept(self, server: socket.socket, handle) -> None:
        while True:
            try:
                conn, _ = server.accept()
            except OSError:
                return
            if handle == self._client:
                threading.Thread(target=handle, args=(conn,), daemon=True).start()
            else:
                handle(conn)

    def _client(self, conn: socket.socket) -> None:
        unpacker = self._mp.Unpacker(raw=False)
        while True:
            try:
                data = conn.recv(4096)
            except OSError:
                return
            if not data:
                return
            unpacker.feed(data)
            for msg in unpacker:
                if msg[0] == 2:
                    if msg[1] == "fish_cmd":
                        for mon in list(self._monitors):
                            mon.sendall(f"ACK {msg[2][0]}\n".encode())
                    continue
                _, msgid, method, params = msg
                self.calls.append((method, params))
                if method in ("$/serial/close", "$/serial/open"):
                    reply = [1, msgid, None, True]
                elif method == PING_METHOD:
                    reply = [1, msgid, None, 1]
                else:
                    reply = [1, msgid, [2, f"method {method} not available"], None]
                conn.sendall(self._mp.packb(reply))

    def close(self) -> None:
        for s in (self._unix, self._tcp, *self._monitors):
            try:
                s.close()
            except OSError:
                pass


def self_test() -> int:
    """Run the real code paths against local stand-ins. Returns a process exit code."""
    import tempfile

    failures: list = []

    def check(name: str, ok: bool, detail: str = "") -> None:
        print(f"  {'ok  ' if ok else 'FAIL'} {name}{': ' + detail if detail else ''}")
        if not ok:
            failures.append(name)

    def serial_case(name: str, mode: str, expect: str, drop: int, want_lost: int,
                    want_code: int) -> Result:
        print(f"[self-test] {name}")
        path, close = _pty_peer(mode, drop)
        try:
            code = main(["--port", path, "--count", "200", "--hz", "200",
                         "--expect", expect, "--timeout", "1"])
        finally:
            close()
        res = main.last_result
        check("exit code", code == want_code, f"{code}")
        check("lost count", res.lost == want_lost, f"{res.lost}")
        check("boot junk reported", any("boot junk" in j for j in res.junk))
        return res

    res = serial_case("serial, echo sketch (ack)", "ack", "ack", 0, 0, 0)
    check("stray line counted as garbage", res.garbage == ["stray line"], f"{res.garbage}")
    check("rate near 200 Hz", 150 <= res.achieved_hz <= 250, f"{res.achieved_hz:.1f}")
    serial_case("serial, 1 line in 50 dropped", "ack", "ack", 50, 4, 1)
    res = serial_case("serial, real-firmware replies (any)", "firmware", "any", 0, 0, 0)
    check("echoes skipped", res.echoes == 200, f"{res.echoes}")

    try:
        import msgpack  # noqa: F401
    except ImportError:
        print("[self-test] router cases skipped: 'msgpack' is not installed")
    else:
        with tempfile.TemporaryDirectory() as tmp:
            sock = os.path.join(tmp, "router.sock")
            router = _FakeRouter(sock)
            try:
                print("[self-test] bridge transport through a fake router")
                code = main(["--transport", "bridge", "--router-socket", sock,
                             "--monitor", router.monitor, "--count", "100", "--hz", "200",
                             "--timeout", "1"])
                check("exit code", code == 0, f"{code}")
                check("serial_open then ping", router.calls[:2] == [
                    ("$/serial/open", ["/dev/ttyHS1"]), (PING_METHOD, [])],
                      f"{router.calls[:2]}")

                print("[self-test] --release-router: close before, open after")
                router.calls.clear()
                path, close = _pty_peer("ack")
                try:
                    code = main(["--port", path, "--release-router", "--router-socket",
                                 sock, "--count", "50", "--hz", "200", "--timeout", "1"])
                finally:
                    close()
                check("exit code", code == 0, f"{code}")
                check("close/open pair", router.calls == [
                    ("$/serial/close", [path]), ("$/serial/open", [path])],
                      f"{router.calls}")

                print("[self-test] --release-router with a port that cannot open")
                router.calls.clear()
                missing = os.path.join(tmp, "no-such-port")
                code = main(["--port", missing, "--release-router", "--router-socket",
                             sock, "--count", "5"])
                check("exit code 2", code == 2, f"{code}")
                check("port handed back after the failure", router.calls == [
                    ("$/serial/close", [missing]), ("$/serial/open", [missing])],
                      f"{router.calls}")

                print("[self-test] --keep-released: no hand-back")
                router.calls.clear()
                path, close = _pty_peer("ack")
                try:
                    main(["--port", path, "--release-router", "--keep-released",
                          "--router-socket", sock, "--count", "20", "--hz", "200",
                          "--timeout", "1"])
                finally:
                    close()
                check("only the close call", router.calls == [("$/serial/close", [path])],
                      f"{router.calls}")
            finally:
                router.close()

    print("[self-test] " + ("FAILED: " + ", ".join(failures) if failures else "all passed"))
    return 1 if failures else 0


# --- command line -------------------------------------------------------------------------------

def _parse(argv: Optional[list]) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Count lost lines and round-trip time on the motor-MCU link.",
        epilog="Exit code: 0 no loss, 1 lost lines, 2 the test could not run.")
    p.add_argument("--port", default="/dev/ttyHS1",
                   help="serial device (default: %(default)s, the UNO Q internal UART)")
    p.add_argument("--baud", type=int, default=115200)
    p.add_argument("--count", type=int, default=DEFAULT_COUNT, help="lines to send")
    p.add_argument("--hz", type=float, default=DEFAULT_HZ,
                   help="send rate (default: %(default)s, the app's command-rate cap)")
    p.add_argument("--payload", default="PING {n}",
                   help="line to send; {n} is the line number (default: %(default)r, "
                        "motor-safe)")
    p.add_argument("--expect", choices=("ack", "any"), default="ack",
                   help="ack: wait for 'ACK <line>' (echo sketches). any: one reply line "
                        "per sent line (real firmware)")
    p.add_argument("--transport", choices=("serial", "bridge"), default="serial",
                   help="serial: raw lines on --port. bridge: router notifications")
    p.add_argument("--release-router", action="store_true",
                   help="UNO Q: ask the router to release --port first ($/serial/close) "
                        "and hand it back on exit ($/serial/open)")
    p.add_argument("--keep-released", action="store_true",
                   help="with --release-router: do not hand the port back on exit")
    p.add_argument("--router-socket", default="/var/run/arduino-router.sock",
                   help="router address: unix socket path or tcp://host:port")
    p.add_argument("--method", default="fish_cmd",
                   help="bridge: method that receives each line (default: %(default)s)")
    p.add_argument("--monitor", default="127.0.0.1:7500",
                   help="bridge: host:port of the router Monitor, where replies arrive")
    p.add_argument("--timeout", type=float, default=2.0,
                   help="seconds to wait for late replies after the last line, and for "
                        "each router call (default: %(default)s)")
    p.add_argument("--self-test", action="store_true",
                   help="check this tool against a pty pair and a fake router, then exit")
    args = p.parse_args(argv)
    if args.count < 1 or args.hz <= 0:
        p.error("--count must be >= 1 and --hz > 0")
    if args.keep_released and not args.release_router:
        p.error("--keep-released only makes sense with --release-router")
    if args.release_router and args.transport == "bridge":
        p.error("--release-router detaches the Bridge; it cannot be used with "
                "--transport bridge")
    try:
        args.payload.format(n=1)
    except (KeyError, IndexError, ValueError) as e:
        p.error(f"bad --payload ({e!r}); the only placeholder is {{n}}")
    return args


def _router_call(args: argparse.Namespace, method: str) -> None:
    rpc = RouterRPC(args.router_socket, args.timeout)
    try:
        rpc.call(method, args.port)
    finally:
        rpc.close()


def _raise_interrupt(*_: object) -> None:
    raise KeyboardInterrupt


def main(argv: Optional[list] = None) -> int:
    args = _parse(argv)
    if args.self_test:
        return self_test()
    main.last_result = Result()
    # `timeout`, systemd and a closed ssh session send SIGTERM/SIGHUP: unwind through
    # the finally below so the router gets its port back.
    old_handlers: dict = {}
    for name in ("SIGTERM", "SIGHUP"):
        sig = getattr(signal, name, None)
        if sig is None:
            continue
        try:
            old_handlers[sig] = signal.signal(sig, _raise_interrupt)
        except ValueError:
            break   # not the main thread
    released = False
    transport = None
    code = 2
    try:
        if args.release_router:
            # Set first: a close cut short (signal, timeout) may still have taken effect,
            # and an extra $/serial/open is harmless.
            released = True
            try:
                _router_call(args, "$/serial/close")
            except (SetupError, RouterError):
                released = False    # never reached the router, or it refused
                raise
            print(f"[uart_check] router released {args.port}")
        if args.transport == "bridge":
            transport = BridgeTransport(args.router_socket, args.method, args.port,
                                        args.monitor, args.timeout)
        else:
            transport = SerialTransport(args.port, args.baud)
        print(f"[uart_check] {transport.label}: {args.count} lines at {args.hz:g} Hz, "
              f"expect={args.expect}", flush=True)
        res = run_check(transport, count=args.count, hz=args.hz, payload=args.payload,
                        expect=args.expect, timeout=args.timeout)
        main.last_result = res
        report(res, transport.label, args.hz)
        code = 0 if res.sent and not res.lost and not res.error else 1
        if res.error == "interrupted":
            code = 130
    except SetupError as e:
        print(f"[uart_check] {e}", file=sys.stderr)
    except (RouterError, OSError) as e:
        print(f"[uart_check] {type(e).__name__}: {e}", file=sys.stderr)
    except KeyboardInterrupt:
        print("\n[uart_check] interrupted", file=sys.stderr)
        code = 130
    finally:
        # A second signal must not cut the hand-back short. Both steps are bounded by
        # --timeout, so ignoring Ctrl-C here cannot hang.
        for sig in (signal.SIGINT, *old_handlers):
            try:
                old = signal.signal(sig, signal.SIG_IGN)
            except ValueError:
                break
            old_handlers.setdefault(sig, old)
        if transport is not None:
            transport.close()
        if released and args.keep_released:
            print(f"[uart_check] {args.port} left released (--keep-released). Hand it "
                  f"back with: arduino-router-cli '$/serial/open' {args.port}")
        elif released:
            try:
                _router_call(args, "$/serial/open")
                print(f"[uart_check] router re-attached {args.port} (a Bridge sketch "
                      "needs an MCU reset to register again)")
            except (SetupError, RouterError, OSError) as e:
                print(f"[uart_check] could NOT hand {args.port} back to the router: {e}\n"
                      f"             run: arduino-router-cli '$/serial/open' {args.port}",
                      file=sys.stderr)
                code = code or 2
        for sig, old in old_handlers.items():
            # None = a handler set from C; SIG_DFL is the closest we can put back.
            signal.signal(sig, old if old is not None else signal.SIG_DFL)
    return code


main.last_result = Result()

if __name__ == "__main__":
    sys.exit(main())
