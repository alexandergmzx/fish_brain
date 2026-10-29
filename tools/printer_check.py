#!/usr/bin/env python3
"""Desk checks for the MP210 Bluetooth ticket printer over RFCOMM (classic serial port).

Measures what the ticket code needs before it exists: connect time, the code page that
prints Spanish, raster band, chunk and gap, status bytes, how long an idle link lives.

    tools/printer_check.py connect --tries 10                    # no paper: connect, close
    tools/printer_check.py send 1B40 1C2E --text "Hola" --feed 3  # bytes, then a text line
    tools/printer_check.py send --codepage 19 --text "¿Tú eres Ñandú? ¡Sí! ÁÉÍÓÚ üÜ €"
    tools/printer_check.py status                                # no paper: DLE EOT, GS r, GS I
    tools/printer_check.py raster --pattern test --rows 800 --band 24 --chunk 192 --gap 0.04
    tools/printer_check.py raster --pbm card.pbm --align center --barrier
    tools/printer_check.py idle --minutes 60 --every 60          # no paper: DLE EOT 1 a minute
    tools/printer_check.py --self-test                           # no printer at all

The printer is `--mac` (default: FISH_PRINTER when it holds a MAC) on `--channel` (1). It
takes one connection at a time: while the fish (FISH_PRINTER set) or a phone holds it, a
connect fails. The tool warns when the `fish-brain` user service is active.

Paper. `send` and `raster` make paper; `connect`, `status` and `idle` send nothing that
prints. Nothing here touches the motors. `send --codepage N` starts with
`1B 40 1C 2E 1B 52 00 1B 74 N` (init, cancel Chinese mode, international set USA, code
page N; `--no-cancel` leaves out `1C 2E`) and encodes the text with the codec of that page
(`--encoding` overrides). Without `--codepage` the bytes go out exactly as given.

Every connect is bounded twice: the socket's timeout, and a thread join a second later in
case the Bluetooth stack does not honour it (the report then says so).

Like uart_check.py this file imports nothing from fish_brain and needs only the standard
library: copy it to any machine with Python 3.

Exit code: 0 = pass (paper still needs a human eye), 1 = a connect, send or idle link
failed, 2 = could not run (bad arguments, no Bluetooth socket, a text the codec cannot
encode, the printer not reachable for `send`, `status`, `raster`, `idle`), 130 = interrupted.
"""
from __future__ import annotations

import argparse
import contextlib
import errno
import io
import os
import re
import socket
import statistics
import subprocess
import sys
import tempfile
import threading
import time
from typing import Callable, Optional

DEFAULT_CHANNEL = 1
DOTS = 384                  # 48 mm at 8 dots/mm (the MP210 manual)
MM_PER_S = 70.0             # the manual's maximum speed, for the paper estimate
DEFAULT_BAND = 24           # rows per GS v 0 command (the PT-210 SDK's value)
DEFAULT_CHUNK = 192         # bytes per sendall (the PT-210 SDK's value)
DEFAULT_GAP = 0.04          # seconds between chunks
DEFAULT_TIMEOUT = 8.0       # connect and send; the page timeout is 5.12 s
QUIET_S = 0.2               # a reply has ended after this long with no byte

INIT = b"\x1b\x40"
CANCEL_CHINESE = b"\x1c\x2e"
INTL_USA = b"\x1b\x52\x00"
LF = b"\n"

# ESC t n -> codec, as the generic tables give it (the self-test page settles the MP210's).
CODEPAGES = {0: "cp437", 2: "cp850", 16: "cp1252", 19: "cp858"}

STATUS_QUERIES = (
    ("DLE EOT 1 printer", "100401"),
    ("DLE EOT 2 off-line", "100402"),
    ("DLE EOT 3 error", "100403"),
    ("DLE EOT 4 paper", "100404"),
    ("GS r 1 paper", "1d7201"),
    ("GS I A firmware", "1d4941"),
    ("GS I C model", "1d4943"),
)
BARRIER = bytes.fromhex("1d7201")
IDLE_POLL = bytes.fromhex("100401")

MAC_RE = re.compile(r"^[0-9A-Fa-f]{2}(:[0-9A-Fa-f]{2}){5}$")
ERRNO_WORDS = {
    errno.EBUSY: "busy (another holder, or a reconnect too soon)",
    errno.EHOSTDOWN: "host down (printer off or out of range)",
    errno.EHOSTUNREACH: "unreachable (printer off or out of range)",
    errno.ECONNREFUSED: "refused (wrong channel?)",
    errno.ECONNRESET: "reset by the printer",
    errno.EPIPE: "the printer closed the link",
    errno.EACCES: "permission denied",
    errno.ETIMEDOUT: "timed out",
}


class SetupError(Exception):
    """The check could not start (bad input, no Bluetooth socket, unreadable file)."""


class ConnectFailed(Exception):
    def __init__(self, reason: str, seconds: float):
        super().__init__(reason)
        self.reason = reason
        self.seconds = seconds


def why(e: BaseException) -> str:
    """A short reason for a socket error."""
    if isinstance(e, (socket.timeout, TimeoutError)):
        return "timed out"
    if isinstance(e, OSError) and e.errno in ERRNO_WORDS:
        return f"{ERRNO_WORDS[e.errno]} [errno {e.errno}]"
    return f"{type(e).__name__}: {e}"


# --- bytes ---------------------------------------------------------------------------------------

def parse_hex(tokens) -> bytes:
    """`1B40`, `1B 40`, `1b,40` -> bytes. SetupError on anything else."""
    text = re.sub(r"[\s,:]", "", "".join(tokens))
    try:
        return bytes.fromhex(text)
    except ValueError:
        raise SetupError(f"not hex: {' '.join(tokens)!r}") from None


def header(codepage: int, cancel: bool = True) -> bytes:
    """Init, (cancel Chinese mode), international set USA, code page."""
    if not 0 <= codepage <= 255:
        raise SetupError(f"code page {codepage} is not a byte")
    return INIT + (CANCEL_CHINESE if cancel else b"") + INTL_USA + bytes((0x1B, 0x74, codepage))


def feed(lines: int) -> bytes:
    """ESC d n: print and feed n lines."""
    return bytes((0x1B, 0x64, max(0, min(255, lines))))


def encode_text(text: str, encoding: str) -> bytes:
    """`text` in `encoding`; SetupError names the first character the codec lacks."""
    try:
        return text.encode(encoding)
    except LookupError:
        raise SetupError(f"unknown encoding {encoding!r}") from None
    except UnicodeEncodeError as e:
        bad = text[e.start:e.end]
        raise SetupError(f"{encoding} cannot encode {bad!r} (U+{ord(bad[0]):04X})") from None


def raster_header(width_bytes: int, rows: int) -> bytes:
    """GS v 0, normal mode: x in bytes, y in dots, both little-endian."""
    return bytes((0x1D, 0x76, 0x30, 0x00, width_bytes & 0xFF, width_bytes >> 8,
                  rows & 0xFF, rows >> 8))


def raster_bands(bits: bytes, width_bytes: int, band: int) -> list:
    """One GS v 0 command per `band` rows (0 = the whole image in one)."""
    rows = len(bits) // width_bytes
    if rows * width_bytes != len(bits):
        raise SetupError(f"{len(bits)} bytes is not whole rows of {width_bytes}")
    step = rows if band <= 0 else band
    parts = []
    for top in range(0, rows, step):
        n = min(step, rows - top)
        parts.append(raster_header(width_bytes, n)
                     + bits[top * width_bytes:(top + n) * width_bytes])
    return parts


def read_pbm(data: bytes) -> tuple:
    """A binary PBM (P4) -> (width in dots, rows, bits). P4 rows are byte-padded, MSB is the
    leftmost dot and 1 is black: GS v 0's own layout."""
    if data[:2] != b"P4":
        raise SetupError("not a binary PBM (P4)")
    fields, i = [], 2
    while len(fields) < 2:
        while i < len(data) and data[i:i + 1].isspace():
            i += 1
        if data[i:i + 1] == b"#":
            while i < len(data) and data[i:i + 1] not in (b"\n", b"\r"):
                i += 1
            continue
        start = i
        while i < len(data) and data[i:i + 1].isdigit():
            i += 1
        if start == i:
            raise SetupError("bad PBM header")
        fields.append(int(data[start:i]))
    i += 1                                  # the one whitespace byte before the bits
    width, rows = fields
    width_bytes = (width + 7) // 8
    bits = data[i:i + width_bytes * rows]
    if width < 1 or rows < 1 or len(bits) != width_bytes * rows:
        raise SetupError(f"PBM {width}x{rows}: {len(bits)} bytes of bits, "
                         f"{width_bytes * rows} expected")
    if width > DOTS:
        raise SetupError(f"PBM is {width} dots wide; the printer has {DOTS}")
    return width, rows, bits


PATTERNS = ("test", "stripes", "ramp", "border", "diagonal", "solid")
_BAYER4 = ((0, 8, 2, 10), (12, 4, 14, 6), (3, 11, 1, 9), (15, 7, 13, 5))


def pattern(name: str, width: int, rows: int) -> bytes:
    """A test image, `width` dots (a multiple of 8) by `rows`, as GS v 0 bits.

    stripes: 4 dots on, 4 off (a shifted byte shows at once). ramp: white to black left to
    right, 4x4 ordered dither. border: a 1-dot frame. diagonal: 45-degree lines every 32
    dots (a lost or doubled row bends them). solid: all black (density, battery). test: a
    border around stripes, the ramp and diagonals in thirds.
    """
    if name not in PATTERNS:
        raise SetupError(f"unknown pattern {name!r}")

    def black(x: int, y: int, kind: str) -> bool:
        if kind == "stripes":
            return x % 8 < 4
        if kind == "ramp":
            return _BAYER4[y % 4][x % 4] < (x * 17) // width
        if kind == "border":
            return x in (0, width - 1) or y in (0, rows - 1)
        if kind == "diagonal":
            return (x - y) % 32 == 0
        if kind == "solid":
            return True
        third = y * 3 // rows                       # test
        inner = ("stripes", "ramp", "diagonal")[third]
        return black(x, y, "border") or black(x, y, inner)

    out = bytearray()
    for y in range(rows):
        for xb in range(0, width, 8):
            byte = 0
            for bit in range(8):
                if black(xb + bit, y, name):
                    byte |= 0x80 >> bit
            out.append(byte)
    return bytes(out)


# --- the link ------------------------------------------------------------------------------------

def _bt() -> tuple:
    family = getattr(socket, "AF_BLUETOOTH", None)
    proto = getattr(socket, "BTPROTO_RFCOMM", None)
    if family is None or proto is None:
        raise SetupError("this Python has no AF_BLUETOOTH/BTPROTO_RFCOMM socket "
                         "(Linux with BlueZ headers at build time)")
    return family, proto


def rfcomm_socket(mac: str, channel: int, timeout: float) -> tuple:
    """An unconnected RFCOMM socket and its address."""
    family, proto = _bt()
    s = socket.socket(family, socket.SOCK_STREAM, proto)
    s.settimeout(timeout)
    return s, (mac, channel)


def connect(make: Callable, mac: str, channel: int, timeout: float) -> tuple:
    """Connect on a worker thread joined `timeout + 1` s at most. Returns (sock, seconds);
    raises ConnectFailed. `make(mac, channel, timeout)` gives (sock, address)."""
    sock, address = make(mac, channel, timeout)
    box: dict = {}

    def run() -> None:
        try:
            sock.connect(address)
            box["ok"] = True
        except BaseException as e:      # noqa: BLE001 - reported to the caller
            box["error"] = e

    t0 = time.monotonic()
    worker = threading.Thread(target=run, name="rfcomm-connect", daemon=True)
    worker.start()
    worker.join(timeout + 1.0)
    seconds = time.monotonic() - t0
    if worker.is_alive():
        _close(sock)
        raise ConnectFailed("still blocked a second past its timeout "
                            "(the socket timeout was not honoured)", seconds)
    if "ok" in box:
        sock.settimeout(timeout)
        return sock, seconds
    _close(sock)
    if isinstance(box.get("error"), KeyboardInterrupt):
        raise KeyboardInterrupt
    raise ConnectFailed(why(box["error"]), seconds)


def _close(sock) -> None:
    with contextlib.suppress(OSError):
        sock.shutdown(socket.SHUT_RDWR)
    with contextlib.suppress(OSError):
        sock.close()


def paced_send(sock, parts, chunk: int, gap: float,
               sleep: Callable = time.sleep) -> tuple:
    """sendall each part in `chunk`-byte pieces (0 = whole), `gap` s between pieces.
    Returns (bytes sent, sendall calls)."""
    pieces = []
    for part in parts:
        if chunk > 0:
            pieces.extend(part[i:i + chunk] for i in range(0, len(part), chunk))
        elif part:
            pieces.append(part)
    sent = 0
    for n, piece in enumerate(pieces):
        if n and gap > 0:
            sleep(gap)
        sock.sendall(piece)
        sent += len(piece)
    return sent, len(pieces)


def read_reply(sock, wait: float, quiet: float = QUIET_S) -> tuple:
    """Bytes until `quiet` s pass with nothing after the first byte, or `wait` s in all.
    Returns (bytes, seconds to the first byte or None)."""
    got = bytearray()
    first = None
    t0 = time.monotonic()
    deadline = t0 + wait
    try:
        while True:
            now = time.monotonic()
            left = deadline - now
            if left <= 0:
                break
            sock.settimeout(min(left, quiet) if got else left)
            try:
                data = sock.recv(256)
            except (socket.timeout, TimeoutError):
                if got:
                    break
                continue
            if not data:
                break
            if first is None:
                first = time.monotonic() - t0
            got += data
    finally:
        with contextlib.suppress(OSError):
            sock.settimeout(None)
    return bytes(got), first


def _show_bytes(data: bytes) -> str:
    if not data:
        return "no reply"
    text = "".join(chr(b) if 32 <= b < 127 else "." for b in data)
    return f"{data.hex(' ')} ({text!r}, bits {' '.join(f'{b:08b}' for b in data[:4])})"


def service_active(name: str = "fish-brain") -> bool:
    try:
        out = subprocess.run(["systemctl", "--user", "is-active", name],
                             capture_output=True, text=True, timeout=3)
    except (OSError, subprocess.SubprocessError):
        return False
    return out.stdout.strip() == "active"


# --- report --------------------------------------------------------------------------------------

class Report:
    """Rows of (name, PASS|FAIL|INFO, detail), and numbers for the self-test."""

    def __init__(self) -> None:
        self.rows: list = []
        self.data: dict = {}

    def add(self, name: str, verdict: str, detail: str = "") -> None:
        self.rows.append((name, verdict, detail))

    def ok(self, name: str, passed: bool, detail: str = "") -> bool:
        self.add(name, "PASS" if passed else "FAIL", detail)
        return passed

    @property
    def failed(self) -> list:
        return [n for n, v, _ in self.rows if v == "FAIL"]

    def show(self, md: bool, title: str) -> None:
        if md:
            print(f"| {title} | result | detail |\n|---|---|---|")
            for name, verdict, detail in self.rows:
                print(f"| {name} | {verdict} | {detail.replace('|', '/')} |")
        else:
            for name, verdict, detail in self.rows:
                print(f"{verdict:<5} {name:<20} {detail}")
        print("RESULT    " + ("FAIL" if self.failed or not self.rows else "PASS"))


# --- commands ------------------------------------------------------------------------------------

def _open(args, rep: Report, make: Callable):
    """Connect once for send/status/raster/idle; a failure ends the check with code 2."""
    try:
        sock, seconds = connect(make, args.mac, args.channel, args.timeout)
    except ConnectFailed as e:
        rep.add("connect", "FAIL", f"{e.reason} after {e.seconds:.2f} s")
        rep.data["code"] = 2
        return None
    rep.add("connect", "PASS", f"{seconds:.2f} s")
    rep.data["connect_s"] = seconds
    return sock


def _finish(sock, args, rep: Report) -> None:
    """Wait `--tail` s so the last bytes reach the printer, then close."""
    if args.tail > 0:
        time.sleep(args.tail)
    _close(sock)
    rep.add("close", "INFO", f"after a {args.tail:g} s tail")


def _send_parts(sock, parts, args, rep: Report, sleep: Callable) -> bool:
    t0 = time.monotonic()
    try:
        sent, calls = paced_send(sock, parts, args.chunk, args.gap, sleep)
    except OSError as e:
        rep.add("send", "FAIL", f"{why(e)} after {time.monotonic() - t0:.2f} s")
        return False
    seconds = time.monotonic() - t0
    rate = sent / seconds if seconds > 0 else 0.0
    rep.data.update(sent=sent, calls=calls, send_s=seconds)
    pace = f"{args.chunk} B chunks, {args.gap:g} s gap" if args.chunk else "whole parts"
    rep.add("send", "PASS", f"{sent} bytes in {calls} sendall, {seconds:.2f} s "
                            f"({rate / 1000:.1f} kB/s; {pace})")
    return True


def cmd_connect(args, rep: Report, make: Callable) -> Optional[int]:
    times, fails = [], []
    for n in range(1, args.tries + 1):
        try:
            sock, seconds = connect(make, args.mac, args.channel, args.timeout)
        except ConnectFailed as e:
            fails.append(e.reason)
            rep.add(f"try {n}", "FAIL", f"{e.reason} after {e.seconds:.2f} s")
        else:
            times.append(seconds)
            _close(sock)
            rep.add(f"try {n}", "PASS", f"{seconds:.2f} s")
        if n < args.tries and args.pause > 0:
            time.sleep(args.pause)
    rep.data.update(times=times, fails=fails)
    if times:
        rep.add("connect time", "INFO", f"median {statistics.median(times):.2f} s, "
                                        f"max {max(times):.2f} s over {len(times)}")
    rep.ok("connects", not fails, f"{len(times)} of {args.tries}"
                                  + (f", pause {args.pause:g} s" if args.tries > 1 else ""))
    return None


def build_send(args) -> bytes:
    """The bytes of `send`: hex and text items in order, framed by --codepage and --feed."""
    encoding = args.encoding or CODEPAGES.get(args.codepage, "ascii")
    out = bytearray()
    if args.codepage is not None:
        out += header(args.codepage, cancel=not args.no_cancel)
    has_text = False
    for kind, value in args.items:
        if kind == "hex":
            out += parse_hex([value])
        else:
            text = value.replace("\\n", "\n")
            if any(ord(c) < 32 and c != "\n" or ord(c) == 127 for c in text):
                raise SetupError("control characters in --text: give them as hex")
            out += encode_text(text, encoding) + LF
            has_text = True
    lines = args.feed if args.feed is not None else (3 if has_text else 0)
    if lines:
        out += feed(lines)
    if not out:
        raise SetupError("nothing to send: give hex bytes or --text")
    return bytes(out)


def cmd_send(args, rep: Report, make: Callable, sleep: Callable) -> Optional[int]:
    data = build_send(args)
    rep.add("bytes", "INFO", data.hex(" ") if len(data) <= 48 else f"{len(data)} bytes")
    sock = _open(args, rep, make)
    if sock is None:
        return rep.data["code"]
    try:
        if not _send_parts(sock, [data], args, rep, sleep):
            return 1
        if args.listen > 0:
            reply, first = read_reply(sock, args.listen)
            rep.data["reply"] = reply
            rep.add("reply", "INFO", _show_bytes(reply)
                    + (f" after {first:.2f} s" if first is not None else ""))
        _finish(sock, args, rep)
        sock = None
    finally:
        if sock is not None:
            _close(sock)
    return None


def cmd_status(args, rep: Report, make: Callable) -> Optional[int]:
    sock = _open(args, rep, make)
    if sock is None:
        return rep.data["code"]
    answered = 0
    try:
        for name, hexed in STATUS_QUERIES:
            try:
                sock.sendall(bytes.fromhex(hexed))
            except OSError as e:
                rep.add(name, "FAIL", why(e))
                return 1
            reply, first = read_reply(sock, args.wait)
            answered += bool(reply)
            rep.data[hexed] = reply
            rep.add(name, "INFO", f"{hexed}: {_show_bytes(reply)}"
                    + (f" after {first:.2f} s" if first is not None else ""))
        rep.add("answered", "INFO", f"{answered} of {len(STATUS_QUERIES)} queries")
        _finish(sock, args, rep)
        sock = None
    finally:
        if sock is not None:
            _close(sock)
    return None


def raster_image(args) -> tuple:
    """(width in dots, rows, bits) from --pbm or --pattern."""
    if args.pbm:
        try:
            with open(args.pbm, "rb") as f:
                return read_pbm(f.read())
        except OSError as e:
            raise SetupError(f"cannot read {args.pbm}: {e}") from None
    return args.width, args.rows, pattern(args.pattern, args.width, args.rows)


def cmd_raster(args, rep: Report, make: Callable, sleep: Callable) -> Optional[int]:
    width, rows, bits = raster_image(args)
    width_bytes = (width + 7) // 8
    parts = raster_bands(bits, width_bytes, args.band)
    align = {"left": 0, "center": 1, "right": 2}[args.align]
    lead = INIT + bytes((0x1B, 0x61, align))
    tail = bytes((0x1B, 0x61, 0)) + (feed(args.feed) if args.feed else b"")
    mm = rows / 8.0
    source = args.pbm or f"pattern {args.pattern}"
    rep.add("image", "INFO", f"{source}: {width}x{rows} dots, {len(bits)} bytes, "
                             f"{len(parts)} command(s) of {args.band or rows} rows")
    rep.add("paper (estimate)", "INFO", f"{mm:.0f} mm, {mm / MM_PER_S:.1f} s at "
                                        f"{MM_PER_S:g} mm/s")
    sock = _open(args, rep, make)
    if sock is None:
        return rep.data["code"]
    try:
        if not _send_parts(sock, [lead, *parts, tail], args, rep, sleep):
            return 1
        if args.barrier:
            t0 = time.monotonic()
            try:
                sock.sendall(BARRIER)
            except OSError as e:
                rep.add("barrier", "FAIL", why(e))
                return 1
            reply, first = read_reply(sock, args.wait)
            rep.data["barrier_s"] = first
            if first is None:
                rep.add("barrier", "INFO", f"GS r 1: no reply in {args.wait:g} s")
            else:
                rep.add("barrier", "INFO", f"GS r 1: {_show_bytes(reply)} "
                                           f"{time.monotonic() - t0:.2f} s after the last byte")
        _finish(sock, args, rep)
        sock = None
    finally:
        if sock is not None:
            _close(sock)
    return None


def cmd_idle(args, rep: Report, make: Callable, sleep: Callable) -> Optional[int]:
    sock = _open(args, rep, make)
    if sock is None:
        return rep.data["code"]
    total = args.minutes * 60.0
    t0 = time.monotonic()
    polls = answered = 0
    try:
        while True:
            elapsed = time.monotonic() - t0
            if elapsed >= total:
                break
            sleep(min(args.every, total - elapsed))
            elapsed = time.monotonic() - t0
            try:
                sock.sendall(IDLE_POLL)
                reply, _ = read_reply(sock, min(args.wait, args.every))
            except OSError as e:
                rep.add("link", "FAIL", f"{why(e)} after {elapsed:.0f} s, {polls} polls")
                rep.data.update(polls=polls, answered=answered)
                return 1
            polls += 1
            answered += bool(reply)
            if args.verbose:
                print(f"[printer_check] {elapsed:7.1f} s  poll {polls}: {_show_bytes(reply)}",
                      flush=True)
            if not reply and args.need_reply:
                rep.add("link", "FAIL", f"no status byte after {elapsed:.0f} s, {polls} polls")
                rep.data.update(polls=polls, answered=answered)
                return 1
        rep.data.update(polls=polls, answered=answered)
        rep.add("link", "PASS", f"held {time.monotonic() - t0:.0f} s, {polls} polls, "
                                f"{answered} answered")
        _finish(sock, args, rep)
        sock = None
    finally:
        if sock is not None:
            _close(sock)
    return None


# --- self-test: a socketpair plays the printer ---------------------------------------------------

class FakePrinter:
    """The far end of a socketpair: records every byte, answers DLE EOT, GS r and GS I.

    Knobs: `silent` answers nothing; `close_after` closes once that many bytes arrived;
    `refuse` makes the connect fail with EHOSTDOWN; `hang` blocks the connect forever.
    """

    def __init__(self, *, silent: bool = False, close_after: int = 0,
                 refuse: bool = False, hang: bool = False):
        self.silent, self.close_after = silent, close_after
        self.refuse, self.hang = refuse, hang
        self.data = bytearray()
        self.connects = 0
        self._ends: list = []
        self._threads: list = []

    def make(self, mac: str, channel: int, timeout: float) -> tuple:
        """Stands in for rfcomm_socket: a socket whose connect is faked."""
        printer = self
        host, peer = socket.socketpair()
        self._ends += [host, peer]

        class Sock:
            def __init__(self):
                self.s = host

            def connect(self, address):
                if printer.hang:
                    threading.Event().wait()
                if printer.refuse:
                    raise OSError(errno.EHOSTDOWN, "Host is down")
                printer.connects += 1
                t = threading.Thread(target=printer._serve, args=(peer,), daemon=True)
                printer._threads.append(t)
                t.start()

            def __getattr__(self, name):
                return getattr(self.s, name)

        return Sock(), (mac, channel)

    def _serve(self, peer) -> None:
        scanned = 0
        while True:
            try:
                chunk = peer.recv(4096)
            except OSError:
                return
            if not chunk:
                return
            self.data += chunk
            if self.close_after and len(self.data) >= self.close_after:
                _close(peer)
                return
            if self.silent:
                continue
            buf = bytes(self.data)
            while True:
                hits = [(buf.find(q, scanned), q) for q in (b"\x10\x04", b"\x1d\x72", b"\x1d\x49")]
                hits = [(i, q) for i, q in hits if i >= 0 and i + 2 < len(buf)]
                if not hits:
                    break
                i, q = min(hits)
                n = buf[i + 2]
                reply = {b"\x10\x04": bytes((0x12,)), b"\x1d\x72": b"\x00",
                         b"\x1d\x49": b"_MP210\x00" if n == 0x43 else b"_V1.0\x00"}[q]
                with contextlib.suppress(OSError):
                    peer.sendall(reply)
                scanned = i + 3
            scanned = max(scanned, len(buf) - 2)

    def close(self) -> None:
        for s in self._ends:
            _close(s)


def self_test() -> int:
    """Run the real code paths against a socketpair printer. Returns an exit code."""
    failures: list = []

    def check(name: str, ok: bool, detail: str = "") -> None:
        print(f"  {'ok  ' if ok else 'FAIL'} {name}{': ' + detail if detail else ''}")
        if not ok:
            failures.append(name)

    def case(name: str, argv: list, want_code: int, printer: FakePrinter) -> Report:
        print(f"[self-test] {name}")
        try:
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                code = main([argv[0], "--mac", "DC:0D:51:92:74:DA", "--tail", "0",
                             *argv[1:]], make=printer.make, sleep=lambda s: time.sleep(
                                 min(s, 0.01)), check_service=False)
            time.sleep(0.05)            # let the fake take the last bytes
        finally:
            printer.close()
        check("exit code", code == want_code, f"{code}")
        case.out = out.getvalue()
        return main.last_report

    print("[self-test] byte builders")
    check("8x2 image", raster_bands(b"\xff\x81", 1, 0) == [bytes.fromhex(
        "1d 76 30 00 01 00 02 00 ff 81")])
    parts = raster_bands(bytes(48 * 50), 48, 24)
    check("50 rows in bands of 24", [p[:8].hex() for p in parts] == [
        "1d76300030001800", "1d76300030001800", "1d76300030000200"],
        f"{[p[:8].hex() for p in parts]}")
    check("band sizes", [len(p) for p in parts] == [8 + 48 * 24, 8 + 48 * 24, 8 + 96])
    check("one command for band 0", len(raster_bands(bytes(48 * 50), 48, 0)) == 1)
    check("header 19", header(19) == bytes.fromhex("1b40 1c2e 1b5200 1b7413"))
    check("header without FS .", header(19, cancel=False) == bytes.fromhex("1b40 1b5200 1b7413"))
    check("hex forms", parse_hex(["1B40", "1c 2e", "1b,64,03"]) == bytes.fromhex("1b401c2e1b6403"))
    try:
        parse_hex(["1B4"])
        check("odd hex refused", False)
    except SetupError:
        check("odd hex refused", True)
    check("cp858 Spanish", encode_text("ñ¿¡á€", "cp858") == bytes.fromhex("a4 a8 ad a0 d5"))
    try:
        encode_text("€", "cp850")
        check("cp850 has no euro", False)
    except SetupError as e:
        check("cp850 has no euro", "U+20AC" in str(e), str(e))
    for name in PATTERNS:
        bits = pattern(name, 384, 48)
        check(f"pattern {name}", len(bits) == 48 * 48)
    check("stripes byte", pattern("stripes", 8, 1) == b"\xf0")
    check("border rows", pattern("border", 16, 3) == bytes.fromhex("ffff 8001 ffff"))
    pbm = b"P4\n# a comment\n16 2\n" + bytes.fromhex("ff00 00ff")
    check("P4 read", read_pbm(pbm) == (16, 2, bytes.fromhex("ff00 00ff")))
    try:
        read_pbm(b"P4\n400 1\n" + bytes(50))
        check("too wide refused", False)
    except SetupError:
        check("too wide refused", True)
    sent: list = []

    class Rec:
        def sendall(self, b):
            sent.append(bytes(b))

    total, calls = paced_send(Rec(), [b"a" * 500, b"b" * 10], 192, 0.0)
    check("chunks", [len(x) for x in sent] == [192, 192, 116, 10] and total == 510
          and calls == 4, f"{[len(x) for x in sent]}")

    p = FakePrinter()
    rep = case("send hex then text, cp858", ["send", "--codepage", "19", "1B4501",
                                             "--text", "¿Tú eres Ñandú?", "--hex", "1B4500"],
               0, p)
    want = (header(19) + bytes.fromhex("1b4501") + "¿Tú eres Ñandú?".encode("cp858") + LF
            + bytes.fromhex("1b4500") + feed(3))
    check("bytes arrive in order", bytes(p.data) == want, bytes(p.data).hex(" "))

    p = FakePrinter()
    case("send hex only: exactly those bytes", ["send", "1B40", "A8A2", "0A"], 0, p)
    check("no feed added", bytes(p.data) == bytes.fromhex("1b40a8a20a"), bytes(p.data).hex())

    p = FakePrinter()
    case("send a text the codec lacks", ["send", "--codepage", "2", "--text", "€"], 2, p)
    check("never connected", p.connects == 0)

    p = FakePrinter(refuse=True)
    rep = case("send to a printer that is off", ["send", "--text", "Hola"], 2, p)
    check("reason named", "host down" in rep.rows[-1][2], rep.rows[-1][2])

    p = FakePrinter()
    rep = case("send --listen reads a GS r reply", ["send", "1D7201", "--listen", "0.5"], 0, p)
    check("reply byte", rep.data.get("reply") == b"\x00", f"{rep.data.get('reply')!r}")

    p = FakePrinter()
    rep = case("raster, test pattern in bands of 24, paced",
               ["raster", "--pattern", "test", "--rows", "100", "--band", "24",
                "--chunk", "192", "--gap", "0.001", "--align", "center"], 0, p)
    bits = pattern("test", 384, 100)
    want = (INIT + b"\x1b\x61\x01" + b"".join(raster_bands(bits, 48, 24))
            + b"\x1b\x61\x00" + feed(3))
    check("raster bytes", bytes(p.data) == want, f"{len(p.data)} of {len(want)}")
    check("sendall per chunk", rep.data.get("calls") == sum(
        -(-len(x) // 192) for x in [INIT + b"\x1b\x61\x01", *raster_bands(bits, 48, 24),
                                    b"\x1b\x61\x00" + feed(3)]), f"{rep.data.get('calls')}")

    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "card.pbm")
        with open(path, "wb") as f:
            f.write(b"P4\n# plate\n256 30\n" + bytes(range(256)) * 3 + bytes(192))
        p = FakePrinter()
        rep = case("raster --pbm, one command, --barrier", ["raster", "--pbm", path,
                                                            "--band", "0", "--chunk", "0",
                                                            "--barrier", "--md"], 0, p)
        check("one GS v 0 of 32x30", raster_header(32, 30) in bytes(p.data))
        check("barrier answered", rep.data.get("barrier_s") is not None)
        check("markdown table", "| raster | result | detail |" in case.out, case.out[:80])

    p = FakePrinter()
    rep = case("status: every query answered", ["status", "--wait", "0.3"], 0, p)
    check("DLE EOT 1", rep.data.get("100401") == b"\x12")
    check("GS I C", rep.data.get("1d4943") == b"_MP210\x00", f"{rep.data.get('1d4943')!r}")

    p = FakePrinter(silent=True)
    rep = case("status: a printer that answers nothing", ["status", "--wait", "0.1"], 0, p)
    check("no reply rows", rep.data.get("100401") == b"")

    p = FakePrinter()
    rep = case("connect x3", ["connect", "--tries", "3", "--pause", "0"], 0, p)
    check("three connects", p.connects == 3 and len(rep.data.get("times", [])) == 3)

    p = FakePrinter(refuse=True)
    case("connect to a printer that is off", ["connect", "--tries", "2", "--pause", "0"], 1, p)

    p = FakePrinter(hang=True)
    t0 = time.monotonic()
    rep = case("a connect that ignores its timeout", ["connect", "--timeout", "0.2"], 1, p)
    check("bounded by the thread", time.monotonic() - t0 < 2.5, f"{time.monotonic() - t0:.1f} s")
    check("said so", "not honoured" in rep.rows[0][2], rep.rows[0][2])

    p = FakePrinter()
    rep = case("idle link held", ["idle", "--minutes", "0.003", "--every", "0.03",
                                  "--wait", "0.2"], 0, p)
    check("polls answered", rep.data.get("polls", 0) >= 1
          and rep.data.get("answered") == rep.data.get("polls"), f"{rep.data}")

    p = FakePrinter(close_after=3)
    case("idle link dropped by the printer", ["idle", "--minutes", "0.01", "--every", "0.03",
                                              "--wait", "0.1"], 1, p)

    p = FakePrinter(close_after=500)
    rep = case("printer closes mid-raster", ["raster", "--pattern", "solid", "--rows", "2000",
                                             "--chunk", "1024", "--gap", "0.001"], 1, p)
    check("send failed", "send" in rep.failed, f"{rep.rows}")

    print("[self-test] " + ("FAILED: " + ", ".join(failures) if failures else "all passed"))
    return 1 if failures else 0


# --- command line --------------------------------------------------------------------------------

COMMANDS = ("connect", "send", "status", "raster", "idle")


class _Item(argparse.Action):
    """--text and --hex append (kind, value) to one ordered list."""

    def __call__(self, parser, namespace, values, option_string=None):
        items = list(getattr(namespace, "items", None) or [])
        items.append(("text" if option_string == "--text" else "hex", values))
        namespace.items = items


def _default_mac() -> Optional[str]:
    value = os.environ.get("FISH_PRINTER", "").strip()
    return value if MAC_RE.match(value) else None


def _parse(argv: Optional[list]) -> argparse.Namespace:
    argv = list(sys.argv[1:] if argv is None else argv)
    if "--self-test" in argv:
        return argparse.Namespace(self_test=True)

    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--mac", default=_default_mac(),
                        help="the printer's address (default: FISH_PRINTER when it is a MAC)")
    common.add_argument("--channel", type=int, default=DEFAULT_CHANNEL,
                        help="RFCOMM channel (default: %(default)s, from sdptool records)")
    common.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT,
                        help="seconds for the connect and each send (default: %(default)s)")
    common.add_argument("--tail", type=float, default=1.0,
                        help="seconds to wait after the last byte before closing "
                             "(default: %(default)s; 0 tests an immediate close)")
    common.add_argument("--md", action="store_true",
                        help="print the result as a markdown table (for docs/results)")

    pacing = argparse.ArgumentParser(add_help=False)
    pacing.add_argument("--chunk", type=int, default=DEFAULT_CHUNK,
                        help="bytes per sendall, 0 = each part whole (default: %(default)s)")
    pacing.add_argument("--gap", type=float, default=DEFAULT_GAP,
                        help="seconds between sendall calls (default: %(default)s)")

    p = argparse.ArgumentParser(
        description="Desk checks for the MP210 ticket printer over Bluetooth RFCOMM.",
        epilog="Exit code: 0 pass, 1 a connect, send or idle link failed, 2 could not run, "
               "130 interrupted. `--self-test` needs no printer.")
    p.add_argument("--self-test", action="store_true",
                   help="check this tool against a socketpair printer, then exit")
    sub = p.add_subparsers(dest="cmd", metavar="{" + ",".join(COMMANDS) + "}")

    c = sub.add_parser("connect", parents=[common], help="no paper: connect and close, timed")
    c.add_argument("--tries", type=int, default=1)
    c.add_argument("--pause", type=float, default=0.5,
                   help="seconds between a close and the next connect (default: %(default)s)")

    c = sub.add_parser("send", parents=[common, pacing],
                       help="paper: hex bytes and text lines, in the order given")
    c.add_argument("hex", nargs="*", metavar="HEX", help="bytes sent first, e.g. 1B40 1C2E")
    c.add_argument("--text", action=_Item, dest="items", metavar="TEXT",
                   help="a line of text (\\n for more lines); repeatable")
    c.add_argument("--hex", action=_Item, dest="items", metavar="HEX",
                   help="more bytes after the text before it; repeatable")
    c.add_argument("--codepage", type=int,
                   help="start with init, FS ., ESC R 0, ESC t N; known: "
                        + ", ".join(f"{n}={cp}" for n, cp in CODEPAGES.items()))
    c.add_argument("--no-cancel", action="store_true",
                   help="with --codepage: leave out FS . (is Chinese mode on by default?)")
    c.add_argument("--encoding", help="codec for --text (default: the code page's, else ascii)")
    c.add_argument("--feed", type=int,
                   help="ESC d N at the end (default: 3 when there is text, else none)")
    c.add_argument("--listen", type=float, default=0.0,
                   help="seconds to read replies after the send (default: none)")

    c = sub.add_parser("status", parents=[common],
                       help="no paper: DLE EOT 1-4, GS r 1, GS I A/C, the bytes back")
    c.add_argument("--wait", type=float, default=1.0, help="seconds per query")

    c = sub.add_parser("raster", parents=[common, pacing],
                       help="paper: a test pattern or a P4 PBM as GS v 0 bands")
    src = c.add_mutually_exclusive_group()
    src.add_argument("--pattern", choices=PATTERNS, default="test")
    src.add_argument("--pbm", help="a binary PBM (P4) at most 384 dots wide")
    c.add_argument("--width", type=int, default=DOTS, help="pattern width in dots")
    c.add_argument("--rows", type=int, default=800, help="pattern height in dots")
    c.add_argument("--band", type=int, default=DEFAULT_BAND,
                   help="rows per GS v 0 command, 0 = one command (default: %(default)s)")
    c.add_argument("--align", choices=("left", "center", "right"), default="left",
                   help="ESC a before the image (does it centre a raster?)")
    c.add_argument("--feed", type=int, default=3, help="ESC d N after the image")
    c.add_argument("--barrier", action="store_true",
                   help="send GS r 1 after the image and time its reply")
    c.add_argument("--wait", type=float, default=30.0,
                   help="seconds to wait for the barrier's reply (default: %(default)s)")

    c = sub.add_parser("idle", parents=[common],
                       help="no paper: hold the link, DLE EOT 1 every --every seconds")
    c.add_argument("--minutes", type=float, default=60.0)
    c.add_argument("--every", type=float, default=60.0)
    c.add_argument("--wait", type=float, default=2.0, help="seconds per poll's reply")
    c.add_argument("--need-reply", action="store_true",
                   help="fail at the first poll with no status byte")
    c.add_argument("--verbose", action="store_true", help="print every poll")

    args = p.parse_args(argv)
    args.self_test = False
    if args.cmd is None:
        p.error("give a command: " + ", ".join(COMMANDS))
    if not args.mac or not MAC_RE.match(args.mac):
        p.error("give --mac AA:BB:CC:DD:EE:FF (or FISH_PRINTER=<MAC> in the environment)")
    if not 1 <= args.channel <= 30:
        p.error("--channel is 1..30")
    if args.timeout <= 0 or args.tail < 0:
        p.error("--timeout must be > 0 and --tail >= 0")
    if args.cmd == "connect" and (args.tries < 1 or args.pause < 0):
        p.error("--tries must be >= 1 and --pause >= 0")
    if args.cmd in ("send", "raster") and (args.chunk < 0 or args.gap < 0):
        p.error("--chunk and --gap must be >= 0")
    if args.cmd == "send":
        args.items = [("hex", h) for h in args.hex] + list(args.items or [])
        if args.feed is not None and not 0 <= args.feed <= 255:
            p.error("--feed is 0..255")
    if args.cmd == "raster":
        if args.width < 8 or args.width > DOTS or args.width % 8:
            p.error(f"--width is a multiple of 8, at most {DOTS}")
        if not 1 <= args.rows <= 65535 or args.band < 0:
            p.error("--rows is 1..65535 and --band >= 0")
        if not 0 <= args.feed <= 255:
            p.error("--feed is 0..255")
    if args.cmd == "idle" and (args.minutes <= 0 or args.every <= 0):
        p.error("--minutes and --every must be > 0")
    return args


def main(argv: Optional[list] = None, *, make: Callable = rfcomm_socket,
         sleep: Callable = time.sleep, check_service: bool = True) -> int:
    args = _parse(argv)
    if args.self_test:
        return self_test()
    rep = main.last_report = Report()
    if check_service and service_active():
        print("[printer_check] fish-brain is active: with FISH_PRINTER set it may hold the "
              "printer (one connection at a time). Stop it first: "
              "systemctl --user stop fish-brain", file=sys.stderr)
    code = 2
    try:
        if make is rfcomm_socket:
            _bt()
        print(f"[printer_check] {args.cmd} {args.mac} ch{args.channel}", flush=True)
        special = {
            "connect": lambda: cmd_connect(args, rep, make),
            "send": lambda: cmd_send(args, rep, make, sleep),
            "status": lambda: cmd_status(args, rep, make),
            "raster": lambda: cmd_raster(args, rep, make, sleep),
            "idle": lambda: cmd_idle(args, rep, make, sleep),
        }[args.cmd]()
        rep.show(args.md, args.cmd)
        code = special if special is not None else (1 if rep.failed or not rep.rows else 0)
    except SetupError as e:
        print(f"[printer_check] {e}", file=sys.stderr)
    except KeyboardInterrupt:
        rep.add(args.cmd, "FAIL", "interrupted")
        rep.show(args.md, args.cmd)
        print("\n[printer_check] interrupted", file=sys.stderr)
        code = 130
    return code


main.last_report = Report()

if __name__ == "__main__":
    sys.exit(main())
