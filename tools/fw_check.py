#!/usr/bin/env python3
"""Host-side checker for the fish firmware on the motor-MCU link.

uart_check.py judges the wire with an echo sketch; this tool judges the firmware that
executes the motor commands: what it answers, whether it loses lines, and (with a trace
build) how long its pulses really are.

    tools/fw_check.py --release-router                 # UNO Q: probe, STATUS, 300 PING lines
    tools/fw_check.py replay --release-router          # every line of the protocol script
    tools/fw_check.py timing --drive --release-router  # trace build: pulse lengths, clock
    tools/fw_check.py soak --seconds 60 --drive --bursts --release-router
    tools/fw_check.py send "STATUS" --release-router
    tools/fw_check.py listen --seconds 5 --release-router
    tools/fw_check.py analyze /tmp/fish_link.log       # a log written with FISH_LINK_LOG
    tools/fw_check.py --self-test                      # no hardware at all

Motor safety. `check`, `replay` without --drive, `soak` without --drive, `listen` and
`analyze` never make the firmware drive an output: they use `PING <n>` (answered
"Unknown command. Type HELP"), STATUS and STOP. Everything that drives needs --drive, and
a held PWM (`MOUTH <n>`, stopped only by the firmware's 5 s limit) needs --held on top.
Every driving run ends with STOP, also after Ctrl-C, SIGTERM or an error.

Frame of one command (Big_mouth src/main.cpp): the firmware echoes each character, ends
the echoed line with CRLF, prints the reply lines, then "> " with no newline. Replies are
matched to sent lines by that echo, never by position, so a lost line is named and a
banner or stray bytes do not shift the pairing.

Trace build (-DFISH_TRACE=1). Records are written between prompts and start with '#':

    #T <millis> <micros> <M|N|T> <signed pwm> <in1><in2> <ena duty>   an output changed
    #B <text>                                                         once at boot
    #L <millis> <loops> <max_gap_us>                                  once a second
    #X <dropped>                                                      trace records lost

A line starting with '#' is never a reply. Without trace records `timing` prints SKIP.

Like uart_check.py this file imports nothing from fish_brain: copy both files to any
machine with Python 3 and pyserial. Before any router call the link lock is taken, the
same lock the app holds while it owns the port (--force skips it).

Exit code: 0 = pass, 1 = a mismatch or lost lines, 2 = could not run, 3 = the peer
answered "ACK ..." (an echo sketch is flashed, not the firmware), 130 = interrupted.
"""
from __future__ import annotations

import argparse
import ast
import collections
import os
import re
import select
import sys
import threading
import time
from typing import Callable, Iterable, Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import uart_check  # noqa: E402
from uart_check import (RouterError, SerialTransport, SetupError, _percentile,  # noqa: E402
                        link_lock, router_released)

DEFAULT_COUNT = 300
DEFAULT_HZ = 33.0
GRID_MS = 1000.0 / 33.0         # the app's mouth frame period
MAX_SAMPLES = 8                 # mismatches / lost lines shown per row

# --- the contract: what the firmware prints (Big_mouth include/*.h) --------------------------

R_UNKNOWN = "Unknown command. Type HELP"
R_STOPPED = "All motors stopped"
R_SPECIFY = "ERROR: specify OPEN/CLOSE/STOP or <pwm> [ms ...]"
R_PARSE = "ERROR: could not parse numbers"
R_PAIRS = "ERROR: timed commands need pairs of <pwm> <ms>"
R_DURATION = "ERROR: step duration must be 1-5000 ms"
R_STATUS_HEAD = "===== STATUS ====="
R_WATCHDOG = "[{name}] watchdog stop (MAX_RUN_TIME)"
MAX_RUN_TIME_MS = 5000          # Config.h MAX_RUN_TIME
MAX_INTS = 40                   # 2 * MAX_CHAIN_COMMANDS
MAX_PWM = 255
CHANNELS = {"MOUTH": "MOUTH", "M": "MOUTH", "NECK": "NECK", "N": "NECK",
            "TAIL": "TAIL", "T": "TAIL"}

# Pieces of the replies as they stand in the firmware source. tests/test_fw_check.py
# looks each one up in Big_mouth/include/*.h, so a reply edited there fails a host test.
FW_LITERALS = (
    R_UNKNOWN, R_STOPPED, R_SPECIFY, R_PARSE, R_PAIRS, R_STATUS_HEAD,
    "ERROR: step duration must be 1-", " ms", " -> pwm ", " -> ", " step", " step chain",
    " stopped", "RUNNING", "stopped", " (pwm ", ", step ", "  [open=", " close=",
    " pulse=", "ms]", "] watchdog stop (MAX_RUN_TIME)", "MAX_RUN_TIME = 5000",
    "MAX_CHAIN_COMMANDS = 20",
)

STATUS_RE = re.compile(r"^(MOUTH|NECK|TAIL): (stopped|RUNNING)(?: \((.*?)\))?\s+"
                       r"\[open=(-?\d+) close=(-?\d+) pulse=(\d+)ms\]$")
HELD_RE = re.compile(r"^\s*(MOUTH|NECK|TAIL|M|N|T)\s+[+-]?\d+\s*$", re.IGNORECASE)
TRACE_T_RE = re.compile(r"^#T (\d+) (\d+) ([MNT]) (-?\d+) ([01])([01]) (\d+)$")
TRACE_L_RE = re.compile(r"^#L (\d+) (\d+) (\d+)$")
TRACE_X_RE = re.compile(r"^#X (\d+)$")

# The lines the app really sends (fish_brain/config.py: mouth drive PWMs, gestures).
MOUTH_OPEN_PWM, MOUTH_CLOSE_PWM, MOUTH_CLOSE_MAX_MS = 238, -200, 74
NECK_OUT, NECK_RETURN, TAIL_FLAP = "NECK 230 650", "NECK -200 560", "TAIL 210 230 -210 210"
CHAIN_LINES = (NECK_OUT, NECK_RETURN, TAIL_FLAP)
SOAK_GESTURES = (NECK_OUT, TAIL_FLAP, NECK_RETURN)
SOAK_MOUTH_MS = (14, 30, 22, 8, 18)
DEFAULT_LENGTHS = "1,2,3,4,6,8,12,16,24,32,48,74,104"
HELD_PWM = 120
HELD_WINDOW_S = (4.99, 5.10)    # host clock, command to watchdog line (proposal)


def _ints(rest: str) -> Optional[list]:
    """The integers in `rest` as the firmware's parseInts reads them, or None (an error)."""
    out: list = []
    i, n = 0, len(rest)
    while i < n:
        while i < n and rest[i] == " ":
            i += 1
        if i >= n:
            break
        start = i
        if rest[i] in "+-":
            i += 1
        while i < n and rest[i] in "0123456789":
            i += 1
        if i == start or len(out) >= MAX_INTS:
            return None
        word = rest[start:i]
        out.append(int(word) if word not in "+-" else 0)    # toInt of a bare sign is 0
    return out or None


def expected_reply(line: str) -> Optional[list]:
    """Reply lines for `line` (CommandProcessor.h), or None when they depend on state."""
    cmd = line.strip().upper()
    if not cmd:
        return []
    if cmd in ("STOP", "S"):
        return [R_STOPPED]
    if cmd in ("HELP", "H", "STATUS", "GET") or cmd.startswith("SET"):
        return None
    word, _, rest = cmd.partition(" ")
    rest = rest.strip()
    name = CHANNELS.get(word)
    if name is None:
        return [R_UNKNOWN]
    if not rest:
        return [R_SPECIFY]
    if rest in ("OPEN", "CLOSE"):
        return []                           # a preset pulse prints nothing
    if rest == "STOP":
        return [f"{name} stopped"]
    nums = _ints(rest)
    if nums is None:
        return [R_PARSE]
    if len(nums) == 1:
        return [f"{name} -> pwm {nums[0]}"]
    if len(nums) % 2:
        return [R_PAIRS]
    if any(d <= 0 or d > MAX_RUN_TIME_MS for d in nums[1::2]):
        return [R_DURATION]
    steps = len(nums) // 2
    return [f"{name} -> {steps} step" + ("" if steps == 1 else " chain")]


def reply_type(replies: list) -> str:
    if not replies:
        return "no reply"
    first = replies[0]
    if first == R_UNKNOWN:
        return "unknown"
    if first.startswith("ERROR"):
        return "error"
    if first == R_STOPPED or first.endswith(" stopped"):
        return "stopped"
    if " -> pwm " in first:
        return "held"
    if " -> " in first and " step" in first:
        return "accepted"
    if first == R_STATUS_HEAD:
        return "status"
    return "other"


# --- matching: echo, reply lines, prompt -------------------------------------------------------

class Sent:
    """One line written to the link and what came back for it."""

    def __init__(self, n: int, text: str, t_sent: float):
        self.n = n
        self.text = text
        self.t_sent = t_sent
        self.t_echo: Optional[float] = None     # None = the firmware never echoed it
        self.t_done: Optional[float] = None     # None = no prompt after the replies
        self.replies: list = []
        self.ack = False                        # answered "ACK <line>": an echo sketch
        self.done = threading.Event()

    @property
    def echoed(self) -> bool:
        return self.t_echo is not None

    @property
    def complete(self) -> bool:
        return self.t_done is not None


class Trace:
    """One '#' record. kind T: ms, us, ch, pwm, pins, ena. kind L: ms, loops, gap_us."""

    def __init__(self, t: float, text: str):
        self.t = t
        self.text = text
        self.kind = "?"
        self.ms = self.us = self.pwm = self.ena = self.loops = self.gap_us = 0
        self.dropped = 0
        self.ch = self.pins = ""
        if (m := TRACE_T_RE.match(text)):
            self.kind = "T"
            self.ms, self.us, self.ch = int(m[1]), int(m[2]), m[3]
            self.pwm, self.pins, self.ena = int(m[4]), m[5] + m[6], int(m[7])
        elif (m := TRACE_L_RE.match(text)):
            self.kind, self.ms, self.loops, self.gap_us = "L", int(m[1]), int(m[2]), int(m[3])
        elif (m := TRACE_X_RE.match(text)):
            self.kind, self.dropped = "X", int(m[1])
        elif text.startswith("#B"):
            self.kind = "B"


class Matcher:
    """Turns the byte stream into echoes, replies, prompts and trace records.

    A sent line is paired with the first echo that equals it; lines sent before it that
    were not echoed by then are lost. Everything up to the next "> " prompt is its reply,
    except '#' records. Fed by the reader thread (or by `analyze`), read by the caller.
    """

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.lines: list = []                   # every Sent, in send order
        self.traces: list = []
        self.stray: list = []                   # (t, text) outside any command
        self.junk: list = []                    # text seen before the first send
        self.on_line: Optional[Callable[[float, str], None]] = None
        self._pending: collections.deque = collections.deque()
        self._current: Optional[Sent] = None
        self._buf = b""

    def sent(self, text: str, t: Optional[float] = None) -> Sent:
        with self.lock:
            s = Sent(len(self.lines) + 1, text.strip(),
                     time.monotonic() if t is None else t)
            self.lines.append(s)
            self._pending.append(s)
            return s

    def feed(self, t: float, data: bytes) -> None:
        with self.lock:
            self._buf += data
            while True:
                if self._buf.startswith(b"> "):     # the prompt has no line end
                    self._buf = self._buf[2:]
                    self._prompt(t)
                    continue
                cut = min((i for i in (self._buf.find(b"\n"), self._buf.find(b"\r"))
                           if i >= 0), default=-1)
                if cut < 0:
                    break
                raw, self._buf = self._buf[:cut], self._buf[cut + 1:]
                self._line(t, raw)
            if len(self._buf) > 4096:   # a stream with no line ends: don't grow forever
                raw, self._buf = self._buf, b""
                self._line(t, raw)

    def _prompt(self, t: float) -> None:
        if self._current is not None:
            self._current.t_done = t
            self._current.done.set()
            self._current = None

    def _line(self, t: float, raw: bytes) -> None:
        text = raw.decode("utf-8", "replace").strip(" \t\x00")
        if not text:
            return
        if self.on_line is not None:
            self.on_line(t, text)
        if text.startswith("#"):
            self.traces.append(Trace(t, text))
            return
        if not self.lines:
            self.junk.append(text)
            return
        if text.startswith("ACK ") and self._pending and text[4:] == self._pending[0].text:
            s = self._pending.popleft()
            s.ack = True
            s.done.set()
            return
        for i, s in enumerate(self._pending):
            if s.text == text:
                for _ in range(i):              # sent earlier, never echoed: lost
                    self._pending.popleft().done.set()
                self._pending.popleft()
                if self._current is not None:   # its prompt never came
                    self._current.done.set()
                s.t_echo = t
                self._current = s
                return
        if self._current is not None:
            self._current.replies.append(text)
        else:
            self.stray.append((t, text))


class Session:
    """A Matcher on a live transport: a reader thread, and send helpers."""

    def __init__(self, transport, line_timeout: float = 1.0):
        self.transport = transport
        self.line_timeout = line_timeout
        self.m = Matcher()
        self.error = ""
        self.drove = False              # a line that can move a motor was written
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._reader, daemon=True)

    def _reader(self) -> None:
        while not self._stop.is_set():
            try:
                data = self.transport.read()
            except Exception as e:      # unplugged port: end the run with a note
                self.error = self.error or f"read failed: {e}"
                return
            if data:
                self.m.feed(time.monotonic(), data)

    def start(self, settle: float) -> None:
        """Start reading and wait `settle` s, so a boot banner is not taken for a reply."""
        self._thread.start()
        time.sleep(settle)

    def stop(self) -> None:
        self._stop.set()
        self._thread.join(1.0)

    def post(self, *texts: str) -> list:
        """Write the lines back to back in one write; do not wait for the replies."""
        sent = [self.m.sent(t) for t in texts]
        if any(t.split()[:1] and t.split()[0].upper() in CHANNELS for t in texts):
            self.drove = True
        try:
            self.transport.write_line("\n".join(s.text for s in sent))
        except Exception as e:
            self.error = self.error or f"write failed at line {sent[0].n}: {e}"
        return sent

    def xfer(self, text: str, timeout: Optional[float] = None) -> Sent:
        """Write one line and wait for its echo, replies and prompt."""
        s = self.post(text)[0]
        s.done.wait(self.line_timeout if timeout is None else timeout)
        return s

    def wait(self, found: Callable[[], object], timeout: float) -> object:
        """Poll `found()` (called with the matcher lock held) until it returns a value."""
        deadline = time.monotonic() + timeout
        while True:
            with self.m.lock:
                hit = found()
            if hit or time.monotonic() >= deadline or self.error:
                return hit
            time.sleep(0.002)

    def traces(self, start: int = 0) -> list:
        with self.m.lock:
            return self.m.traces[start:]

    def strays(self, start: int = 0) -> list:
        with self.m.lock:
            return self.m.stray[start:]


class Report:
    """Rows of (name, PASS|FAIL|SKIP|INFO, detail), and numbers for the tests."""

    def __init__(self) -> None:
        self.rows: list = []
        self.data: dict = {}

    def add(self, name: str, verdict: str, detail: str = "") -> None:
        self.rows.append((name, verdict, detail))

    def ok(self, name: str, passed: bool, detail: str = "") -> bool:
        self.add(name, "PASS" if passed else "FAIL", detail)
        return passed

    def verdict(self, name: str) -> list:
        return [v for n, v, _ in self.rows if n == name]

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


def _samples(items: Iterable, limit: int = MAX_SAMPLES) -> str:
    items = list(items)
    more = f" ... {len(items) - limit} more" if len(items) > limit else ""
    return "; ".join(str(i) for i in items[:limit]) + more


def _failure(s: Sent, want: Optional[list]) -> str:
    """Why `s` is not a clean exchange, or "" when it is."""
    if s.ack:
        return f"{s.text!r}: answered ACK (echo sketch)"
    if not s.echoed:
        return f"{s.text!r}: never echoed"
    if not s.complete:
        return f"{s.text!r}: no prompt after {s.replies}"
    if want is not None and s.replies != want:
        return f"{s.text!r}: got {s.replies}, want {want}"
    return ""


# --- STATUS and the paced stream, shared by the sub-commands -----------------------------------

def read_status(sess: Session) -> tuple:
    """Send STATUS. Returns (Sent, {channel: (state, in the brackets)})."""
    s = sess.xfer("STATUS")
    channels = {}
    for line in s.replies:
        if (m := STATUS_RE.match(line)):
            channels[m[1]] = (m[2], m[3] or "")
    return s, channels


def check_stopped(sess: Session, rep: Report, name: str = "status") -> bool:
    s, ch = read_status(sess)
    problem = _failure(s, None)
    if not problem and sorted(ch) != ["MOUTH", "NECK", "TAIL"]:
        problem = f"want three channel lines, got {s.replies}"
    if not problem:
        running = [f"{k} {v[0]} ({v[1]})" for k, v in ch.items() if v[0] != "stopped"]
        problem = ", ".join(running)
    return rep.ok(name, not problem, problem or "MOUTH, NECK, TAIL stopped")


def run_stream(sess: Session, slots: Iterable, hz: float, total: int = 0) -> list:
    """Write each slot (a list of lines) on one `hz` schedule; wait for the late replies."""
    period = 1.0 / hz
    sent: list = []
    t0 = time.monotonic()
    next_note = t0 + 5.0
    for k, slot in enumerate(slots):
        # One monotonic schedule for the whole run, like the app's command stream.
        wait = t0 + k * period - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        sent.extend(sess.post(*slot))
        if sess.error:
            break
        if time.monotonic() >= next_note:
            next_note += 5.0
            print(f"[fw_check] sent {len(sent)}" + (f"/{total}" if total else ""), flush=True)
    deadline = time.monotonic() + sess.line_timeout
    while time.monotonic() < deadline and not all(s.done.is_set() for s in sent):
        time.sleep(0.005)
    return sent


def judge_stream(sent: list) -> dict:
    out = {"sent": len(sent), "echoed": 0, "answered": 0, "lost": [], "wrong": [],
           "types": collections.Counter(), "rtts": []}
    for s in sent:
        if not s.echoed:
            out["lost"].append(s.text)
            continue
        out["echoed"] += 1
        out["types"][reply_type(s.replies)] += 1
        problem = _failure(s, expected_reply(s.text))
        if problem:
            out["wrong"].append(problem)
        else:
            out["answered"] += 1
            out["rtts"].append((s.t_done - s.t_sent) * 1000.0)
    return out


def stream_row(rep: Report, name: str, res: dict, error: str) -> None:
    detail = (f"sent {res['sent']}, echoed {res['echoed']}, answered {res['answered']}, "
              f"lost {len(res['lost'])}")
    if res["rtts"]:
        r = res["rtts"]
        detail += (f"; round trip ms avg {sum(r) / len(r):.2f} "
                   f"p95 {_percentile(r, 0.95):.2f} max {max(r):.2f}")
    if error:
        detail += f"; {error}"
    rep.data["lost"] = len(res["lost"])
    rep.ok(name, bool(res["sent"]) and res["answered"] == res["sent"] and not error, detail)
    if res["lost"]:
        rep.add(name + " lost", "INFO", _samples(res["lost"]))
    if res["wrong"]:
        rep.add(name + " wrong", "INFO", _samples(res["wrong"]))


# --- check: the motor-safe tier ------------------------------------------------------------------

def cmd_check(sess: Session, args, rep: Report) -> Optional[int]:
    problems = []
    for n in (1, 2, 3):
        s = sess.xfer(f"PING {n}")
        if s.ack or any(text.startswith("ACK ") for _, text in sess.strays()):
            rep.add("probe", "FAIL", "the peer answers 'ACK ...': an echo sketch is "
                                     "flashed, not the firmware")
            return 3
        problem = _failure(s, [R_UNKNOWN])
        if problem:
            problems.append(problem)
    rep.ok("probe", not problems, _samples(problems) or "3 PING lines echoed and answered "
                                                         f"{R_UNKNOWN!r}")
    if len(problems) == 3:
        return None             # nothing answers: the soak would only repeat that
    check_stopped(sess, rep)
    slots = ([f"PING {n}"] for n in range(100, 100 + args.count))
    res = judge_stream(run_stream(sess, slots, args.hz, args.count))
    stream_row(rep, "soak", res, sess.error)
    return None


# --- replay: the firmware repo's protocol script -------------------------------------------------

def parse_script(text: str) -> list:
    """Lines of a v1.script: [(command, drives)]. '#' starts a comment; '#drive' marks."""
    out = []
    for raw in text.splitlines():
        cmd, _, comment = raw.partition("#")
        if cmd.strip():
            out.append((cmd.strip(), comment.strip().lower().split()[:1] == ["drive"]))
    return out


def parse_expect(text: str) -> dict:
    """Blocks of a v1.expect: {line as sent: deque of reply-line lists, in file order}."""
    out: dict = {}
    block = None
    for raw in text.splitlines():
        if raw.startswith(">>>"):
            block = []
            out.setdefault(raw[3:].strip(), collections.deque()).append(block)
        elif block is not None and raw.strip() and not raw.lstrip().startswith("#"):
            block.append(raw.strip())
    return out


def _protocol_file(given: Optional[str], name: str) -> str:
    if given:
        return given
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    for folder in (os.path.join(here, "..", "Big_mouth", "protocol"),
                   os.path.expanduser("~/fish_fw/protocol")):
        path = os.path.normpath(os.path.join(folder, name))
        if os.path.isfile(path):
            return path
    raise SetupError(f"no {name} found (looked in ../Big_mouth/protocol and "
                     "~/fish_fw/protocol): give --script and --expect")


def load_protocol(args) -> tuple:
    try:
        with open(_protocol_file(args.script, "v1.script"), encoding="utf-8") as f:
            script = parse_script(f.read())
        with open(_protocol_file(args.expect, "v1.expect"), encoding="utf-8") as f:
            expect = parse_expect(f.read())
    except OSError as e:
        raise SetupError(f"cannot read the protocol files: {e}") from e
    if not script:
        raise SetupError("the script has no command lines")
    return script, expect


def cmd_replay(sess: Session, args, rep: Report) -> Optional[int]:
    script, expect = args.protocol
    ok = skipped = 0
    bad = []
    for line, drives in script:
        # A block is used once per occurrence, also for a skipped line, so a line that
        # appears twice keeps its own expectation.
        blocks = expect.get(line)
        want = (blocks.popleft() if len(blocks) > 1 else blocks[0]) if blocks else None
        if drives and not args.drive:
            skipped += 1
            continue
        s = sess.xfer(line)
        if s.ack:
            rep.add("replay", "FAIL", "the peer answers 'ACK ...': an echo sketch is flashed")
            return 3
        problem = _failure(s, want)
        if not problem and want is None:
            problem = f"{line!r}: no '>>> {line}' block in the expect file"
        if problem:
            bad.append(problem)
        else:
            ok += 1
    rep.data["mismatches"] = bad
    rep.ok("replay", not bad and ok > 0,
           f"{ok} of {ok + len(bad)} lines answered as expected"
           + (f", {skipped} '#drive' lines skipped (no --drive)" if skipped else ""))
    for problem in bad[:MAX_SAMPLES]:
        rep.add("mismatch", "FAIL", problem)
    if len(bad) > MAX_SAMPLES:
        rep.add("mismatch", "FAIL", f"... {len(bad) - MAX_SAMPLES} more")
    stray = [text for _, text in sess.strays()]
    if stray:
        rep.add("unasked lines", "INFO", _samples(repr(t) for t in stray))
    return None


# --- timing: needs the trace build ---------------------------------------------------------------

def _steps(events: list) -> list:
    """[(pwm, ms on the MCU clock)] between consecutive #T records of one channel."""
    return [(a.pwm, ((b.us - a.us) % (1 << 32)) / 1000.0) for a, b in zip(events, events[1:])]


def run_line(sess: Session, line: str) -> tuple:
    """Send a timed line, wait until its channel is back at 0. Returns (Sent, #T records)."""
    ch = CHANNELS[line.split()[0].upper()][0]
    nums = [int(w) for w in line.split()[1:]]
    start = len(sess.traces())
    s = sess.xfer(line)

    def ended() -> bool:
        mine = [r for r in sess.m.traces[start:] if r.kind == "T" and r.ch == ch]
        return len(mine) > 1 and mine[-1].pwm == 0

    sess.wait(ended, sum(nums[1::2]) / 1000.0 + 1.0)
    return s, [r for r in sess.traces(start) if r.kind == "T" and r.ch == ch]


def line_errors(line: str, s: Sent, events: list) -> tuple:
    """Compare what the trace shows with what `line` asked. Returns (errors ms, problem)."""
    nums = [int(w) for w in line.split()[1:]]
    want_pwm = [max(-MAX_PWM, min(MAX_PWM, p)) for p in nums[0::2]]
    problem = _failure(s, expected_reply(line))
    steps = _steps(events)
    if not problem and [p for p, _ in steps] != want_pwm:
        problem = f"{line!r}: trace shows pwm {[r.pwm for r in events]}, want {want_pwm + [0]}"
    if problem:
        return [], problem
    return [got - want for (_, got), want in zip(steps, nums[1::2])], ""


def _err_row(rep: Report, name: str, errs: list, problems: list, args) -> None:
    if problems or not errs:
        rep.add(name, "FAIL", _samples(problems) or "no pulse measured")
        return
    rep.ok(name, args.pulse_min <= min(errs) and max(errs) <= args.pulse_max,
           f"n={len(errs)} error ms min {min(errs):+.2f} avg {sum(errs) / len(errs):+.2f} "
           f"max {max(errs):+.2f} (pass {args.pulse_min:+g}..{args.pulse_max:+g})")


def clock_ppm(traces: list) -> tuple:
    """MCU millis against the host clock: (ppm, span s, source), by least squares."""
    for kind in ("L", "T"):
        pts = [(r.t, r.ms) for r in traces if r.kind == kind]
        if len(pts) >= 3 and pts[-1][0] - pts[0][0] > 0:
            break
    else:
        return None, 0.0, ""
    # Unwrap millis (it wraps after 49 days) and fit ms = a + b * host seconds.
    xs = [t - pts[0][0] for t, _ in pts]
    ys = [((ms - pts[0][1] + (1 << 31)) % (1 << 32)) - (1 << 31) for _, ms in pts]
    mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
    slope = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sum((x - mx) ** 2 for x in xs)
    return (slope / 1000.0 - 1.0) * 1e6, xs[-1], f"#{kind}"


def cmd_timing(sess: Session, args, rep: Report) -> Optional[int]:
    names = ["truth table", "pulse length", "chain steps", "pre-emption", "stop latency",
             "held limit", "clock rate"]
    if not sess.wait(lambda: len(sess.m.traces), 1.5):
        for name in names:
            rep.add(name, "SKIP", "no trace records: not a -DFISH_TRACE=1 build")
        return None
    first = sess.xfer("PING 1")
    if _failure(first, [R_UNKNOWN]):
        rep.add("probe", "FAIL", _failure(first, [R_UNKNOWN]))
        return 3 if first.ack else None

    # Pulse lengths: each open pulse is followed by a close pulse, as in speech.
    all_errs: list = []
    for pwm, label in ((MOUTH_OPEN_PWM, "open"), (MOUTH_CLOSE_PWM, "close")):
        rep.data[label] = {}
    for ms in args.lengths:
        for _ in range(args.repeat):
            for pwm, label, n in ((MOUTH_OPEN_PWM, "open", ms),
                                  (MOUTH_CLOSE_PWM, "close", min(ms, MOUTH_CLOSE_MAX_MS))):
                line = f"MOUTH {pwm} {n}"
                errs, problem = line_errors(line, *run_line(sess, line))
                slot = rep.data[label].setdefault(n, ([], []))
                slot[0].extend(errs)
                if problem:
                    slot[1].append(problem)
    for label, pwm in (("open", MOUTH_OPEN_PWM), ("close", MOUTH_CLOSE_PWM)):
        for n, (errs, problems) in sorted(rep.data[label].items()):
            _err_row(rep, f"pulse MOUTH {pwm} {n}", errs, problems, args)
            all_errs.extend(errs)
    rep.data["pulse_err_us"] = [e * 1000.0 for e in all_errs]

    # Chains, as the app sends them.
    for line in CHAIN_LINES:
        errs, problem = line_errors(line, *run_line(sess, line))
        _err_row(rep, f"chain {line}", errs, [problem] if problem else [], args)

    # Pre-emption: a second NECK line replaces the first while it runs.
    start = len(sess.traces())
    a = sess.xfer(NECK_OUT)
    time.sleep(max(0.0, a.t_sent + 0.1 - time.monotonic()))
    b, events = run_line(sess, NECK_RETURN)
    events = [r for r in sess.traces(start) if r.kind == "T" and r.ch == "N"]
    steps = _steps(events)
    gap = (b.t_sent - a.t_sent) * 1000.0
    if [p for p, _ in steps] == [230, -200] and not _failure(b, expected_reply(NECK_RETURN)):
        err = steps[1][1] - 560
        rep.ok("pre-emption", args.pulse_min <= err <= args.pulse_max
               and -1.0 <= steps[0][1] - gap <= args.stop_ms,
               f"first step cut at {steps[0][1]:.1f} ms (lines {gap:.1f} ms apart), "
               f"second step error {err:+.2f} ms")
    else:
        rep.add("pre-emption", "FAIL", f"trace shows pwm {[r.pwm for r in events]}, want "
                                       f"[230, -200, 0]; {_failure(b, None)}")

    # STOP mid-flight.
    start = len(sess.traces())
    a = sess.xfer(NECK_OUT)
    time.sleep(max(0.0, a.t_sent + 0.1 - time.monotonic()))
    b = sess.xfer("STOP")
    sess.wait(lambda: any(r.kind == "T" and r.ch == "N" and r.pwm == 0
                          for r in sess.m.traces[start:]), 1.0)
    steps = _steps([r for r in sess.traces(start) if r.kind == "T" and r.ch == "N"])
    gap = (b.t_sent - a.t_sent) * 1000.0
    problem = _failure(b, [R_STOPPED])
    if not problem and [p for p, _ in steps][:1] != [230]:
        problem = "no #T record for the stop"
    if problem:
        rep.add("stop latency", "FAIL", problem)
    else:
        late = steps[0][1] - gap
        rep.ok("stop latency", -1.0 <= late <= args.stop_ms,
               f"output off {late:+.2f} ms after the STOP line was written "
               f"(pass up to {args.stop_ms:g}); reply after "
               f"{(b.t_done - b.t_sent) * 1000.0:.2f} ms")
    check_stopped(sess, rep, "status after STOP")

    if args.held:
        held_limit(sess, args, rep)
    else:
        rep.add("held limit", "SKIP", "needs --held")

    # Truth table over every #T record of the run.
    records = [r for r in sess.traces() if r.kind == "T"]
    wrong = [r.text for r in records
             if r.pins != ("10" if r.pwm > 0 else "01" if r.pwm < 0 else "00")
             or r.ena != abs(r.pwm)]
    seen = {(r.ch, (r.pwm > 0) - (r.pwm < 0)) for r in records}
    missing = [f"{ch}{'+' if sign > 0 else '-' if sign < 0 else '0'}"
               for ch in "MNT" for sign in (1, -1, 0) if (ch, sign) not in seen]
    rep.ok("truth table", not wrong and not missing,
           (_samples(wrong) if wrong else f"not seen: {missing}" if missing else
            f"{len(records)} records: + is 10, - is 01, stop is 00, duty = |pwm|"))

    # Clock: keep listening until the stamps span enough host time.
    sess.wait(lambda: clock_ppm(sess.m.traces)[1] >= args.clock_seconds,
              args.clock_seconds + 2.0)
    traces = sess.traces()
    ppm, span, source = clock_ppm(traces)
    if ppm is None:
        rep.add("clock rate", "FAIL", "fewer than 3 stamped records")
    else:
        rep.data["clock_ppm"] = ppm
        rep.ok("clock rate", abs(ppm) <= args.clock_pct * 1e4,
               f"MCU clock {ppm:+.0f} ppm against the host over {span:.1f} s of {source} "
               f"stamps (pass within {args.clock_pct:g} %)")
    loops = [r for r in traces if r.kind == "L"]
    drops = sum(r.dropped for r in traces if r.kind == "X")
    unread = [r.text for r in traces if r.kind == "?"]
    rep.add("loop", "INFO", (f"longest loop gap {max(r.gap_us for r in loops)} us, " if loops
                             else "no #L records, ") + f"{drops} trace records dropped (#X)")
    if unread:
        rep.add("trace format", "FAIL", "records not understood: " + _samples(unread))
    return None


def held_limit(sess: Session, args, rep: Report) -> None:
    """`MOUTH <n>` with no duration: the firmware must stop it by itself after 5 s."""
    line = f"MOUTH {HELD_PWM}"
    want_line = R_WATCHDOG.format(name="MOUTH")
    start_t, start_s = len(sess.traces()), len(sess.strays())
    s = sess.xfer(line)
    problem = _failure(s, [f"MOUTH -> pwm {HELD_PWM}"])
    try:
        if not problem:
            _, ch = read_status(sess)
            if ch.get("MOUTH") != ("RUNNING", f"pwm {HELD_PWM}"):
                problem = f"STATUS shows MOUTH {ch.get('MOUTH')}, want RUNNING (pwm {HELD_PWM})"
        hit = sess.wait(lambda: next((t for t, text in sess.m.stray[start_s:]
                                      if text == want_line), None),
                        max(0.0, s.t_sent + MAX_RUN_TIME_MS / 1000.0 + 1.5 - time.monotonic()))
    finally:
        sess.xfer("STOP")       # whatever happened, the output is off now
    if not problem and not hit:
        problem = f"no {want_line!r} within {MAX_RUN_TIME_MS / 1000.0 + 1.5:g} s"
    if problem:
        rep.add("held limit", "FAIL", problem)
        return
    host_s = hit - s.t_sent
    steps = _steps([r for r in sess.traces(start_t) if r.kind == "T" and r.ch == "M"])
    mcu = f", {steps[0][1]:.1f} ms on the MCU clock" if steps else ""
    rep.data["held_s"] = host_s
    rep.ok("held limit", HELD_WINDOW_S[0] <= host_s <= HELD_WINDOW_S[1],
           f"watchdog line {host_s:.3f} s after the command on the host clock{mcu} "
           f"(pass {HELD_WINDOW_S[0]:g}..{HELD_WINDOW_S[1]:g})")
    check_stopped(sess, rep, "status after limit")


# --- soak ----------------------------------------------------------------------------------------

def soak_slots(seconds: float, hz: float, drive: bool, bursts: bool, every_s: float):
    """One list of lines per grid slot. With `drive`, the lines the fish really sends."""
    every = max(2, round(every_s * hz))
    mouth = gesture = 0
    for k in range(max(1, int(seconds * hz))):
        if not drive:
            yield [f"PING {k + 1}"]
            continue
        extra = None
        if k and k % every == 0:
            extra = SOAK_GESTURES[gesture % len(SOAK_GESTURES)]
            gesture += 1
            if not bursts:
                yield [extra]       # a slot of its own; the mouth sequence is not cut
                continue
        ms = SOAK_MOUTH_MS[(mouth // 2) % len(SOAK_MOUTH_MS)]
        line = f"MOUTH {MOUTH_CLOSE_PWM if mouth % 2 else MOUTH_OPEN_PWM} {ms}"
        mouth += 1
        yield [line, extra] if extra else [line]


def cmd_soak(sess: Session, args, rep: Report) -> Optional[int]:
    total = max(1, int(args.seconds * args.hz))
    sent: list = []
    try:
        sent = run_stream(sess, soak_slots(args.seconds, args.hz, args.drive, args.bursts,
                                           args.gesture_every), args.hz, total)
    finally:
        if args.drive and not sess.error:
            # Leave the body as it was found: head home, mouth closed, then STOP.
            necks = [s.text for s in sess.m.lines if s.text.startswith("NECK")]
            if necks and necks[-1] == NECK_OUT:
                sess.xfer(NECK_RETURN)
                time.sleep(0.6)
            sess.xfer(f"MOUTH {MOUTH_CLOSE_PWM} {MOUTH_CLOSE_MAX_MS}")
            time.sleep(0.1)
    res = judge_stream(sent)
    if any(s.ack for s in sent):
        rep.add("soak", "FAIL", "the peer answers 'ACK ...': an echo sketch is flashed")
        return 3
    stream_row(rep, "soak", res, sess.error)
    rep.add("replies", "FAIL" if res["types"]["error"] or res["types"]["other"] else "INFO",
            ", ".join(f"{k} {v}" for k, v in sorted(res["types"].items())) or "none")
    stop = sess.xfer("STOP")
    rep.ok("stop", not _failure(stop, [R_STOPPED]), _failure(stop, [R_STOPPED]) or R_STOPPED)
    check_stopped(sess, rep)
    traces = sess.traces()
    if traces:
        loops = [r.gap_us for r in traces if r.kind == "L"]
        drops = sum(r.dropped for r in traces if r.kind == "X")
        rep.data["drops"] = drops
        rep.add("trace", "INFO", f"{drops} records dropped (#X), longest loop gap "
                                 + (f"{max(loops)} us" if loops else "not reported"))
    stray = [text for _, text in sess.strays()]
    if stray:
        rep.add("unasked lines", "INFO", _samples(repr(t) for t in stray))
    return None


# --- send, listen --------------------------------------------------------------------------------

def dump(transport, seconds: float) -> int:
    """Print what arrives for `seconds`, one line each with the time since the start."""
    t0 = time.monotonic()
    buf, count = b"", 0
    while time.monotonic() - t0 < seconds:
        buf += transport.read()
        parts = re.split(rb"[\r\n]", buf)
        buf = parts.pop()
        for raw in parts:
            if raw.strip(b" \x00"):
                count += 1
                print(f"{time.monotonic() - t0:8.3f}  {raw.decode('utf-8', 'replace')}",
                      flush=True)
    if buf.strip(b" \x00"):
        print(f"{time.monotonic() - t0:8.3f}  {buf.decode('utf-8', 'replace')}  (no line end)")
    return count


# --- analyze: a link log written by the app ------------------------------------------------------

LOG_RE = re.compile(r"^\s*(\d+(?:\.\d+)?)\s+([TR])\s(.*)$")


def grid_lateness(times: list, period_s: float) -> list:
    """How late each MOUTH line was against a grid of `period_s`, in ms.

    The grid's phase is not in the log: per utterance (lines less than 1 s apart) it is
    taken from the earliest line phase, so the numbers are relative to the best case.
    """
    runs, run = [], []
    for t in times:
        if run and t - run[-1] > 1.0:
            runs.append(run)
            run = []
        run.append(t)
    runs.append(run)
    late = []
    for run in runs:
        if len(run) < 3:
            continue
        phase = sorted((t - run[0]) % period_s for t in run)
        # The widest empty arc of the phase circle ends at the earliest phase.
        gaps = [(phase[i] - phase[i - 1]) % period_s for i in range(len(phase))]
        anchor = phase[gaps.index(max(gaps))]
        late.extend((((t - run[0]) % period_s - anchor) % period_s) * 1000.0 for t in run)
    return late


def analyze(path: str, rep: Report, grid_ms: float = GRID_MS) -> int:
    m = Matcher()
    bad_lines = 0
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            for raw in f:
                hit = LOG_RE.match(raw.rstrip("\n"))
                if not hit:
                    bad_lines += bool(raw.strip())
                    continue
                t = float(hit[1])
                if hit[2] == "T":
                    m.sent(hit[3], t)
                else:
                    try:
                        data = ast.literal_eval(hit[3].strip())
                    except (ValueError, SyntaxError):
                        bad_lines += 1
                        continue
                    if isinstance(data, bytes):
                        m.feed(t, data)
    except OSError as e:
        print(f"[fw_check] cannot read {path}: {e}", file=sys.stderr)
        return 2
    if not m.lines:
        print(f"[fw_check] {path}: no '<time> T <line>' entries", file=sys.stderr)
        return 2
    res = judge_stream(m.lines)
    rejected = [f"{s.text!r}: {s.replies[0]}" for s in m.lines
                if reply_type(s.replies) in ("unknown", "error")]
    rep.data.update(lost=res["lost"], rejected=rejected)
    rep.add("lines sent", "INFO", f"{res['sent']} over "
                                  f"{m.lines[-1].t_sent - m.lines[0].t_sent:.1f} s")
    rep.ok("echoes", not res["lost"], f"{res['echoed']} of {res['sent']} echoed by the MCU")
    if res["lost"]:
        rep.add("never echoed", "FAIL", _samples(repr(t) for t in res["lost"]))
    rep.add("replies", "INFO",
            ", ".join(f"{k} {v}" for k, v in sorted(res["types"].items())) or "none")
    rep.ok("rejected", not rejected, _samples(rejected) or "none")
    late = grid_lateness([s.t_sent for s in m.lines if s.text.upper().startswith("MOUTH")],
                         grid_ms / 1000.0)
    if late:
        rep.data["lateness_ms"] = late
        rep.add("mouth spacing", "INFO",
                f"{len(late)} MOUTH lines against a {grid_ms:.1f} ms grid: late p50 "
                f"{_percentile(late, 0.5):.2f} p95 {_percentile(late, 0.95):.2f} "
                f"max {max(late):.2f} ms")
    else:
        rep.add("mouth spacing", "INFO", "fewer than 3 MOUTH lines in a row")
    if m.traces:
        rep.add("trace", "INFO", f"{len(m.traces)} '#' records")
    if m.junk or m.stray or bad_lines:
        rep.add("other", "INFO", f"{len(m.junk)} lines before the first send, {len(m.stray)} "
                                 f"outside a command, {bad_lines} log lines not understood")
    return 1 if rep.failed else 0


# --- self-test: a pty peer that models the firmware -----------------------------------------------

HELP_LINES = (
    "", "===== COMMANDS =====",
    "Channels: MOUTH | NECK | TAIL   (+ = open/out, - = close/return)",
    "  <CH> OPEN | CLOSE | STOP   - preset pulse / stop",
    "  <CH> <pwm>                 - immediate, run until changed (e.g. MOUTH -180)",
    "  <CH> <pwm> <ms>            - single timed pulse (e.g. NECK 180 600)",
    "  <CH> <pwm> <ms> ...        - gesture chain (e.g. TAIL 200 300 -200 300)", "",
    "Tuning (no reflash):", "  SET <CH> OPEN <pwm>",
    "  SET <CH> CLOSE <pwm>       - use a negative value", "  SET <CH> PULSE <ms>", "",
    "Global:", "  STOP | S    - stop all motors", "  STATUS|GET  - show state + params",
    "  HELP | H    - this help", "",
    "Notes: PWM -255..255, watchdog stops any run > MAX_RUN_TIME.",
    "====================", "",
)


class _Channel:
    def __init__(self, name: str, open_pwm: int, close_pwm: int, pulse_ms: int):
        self.name, self.open, self.close, self.pulse = name, open_pwm, close_pwm, pulse_ms
        self.running = False
        self.speed = 0
        self.start_us = 0.0
        self.target_ms = 0          # 0 = until changed (the watchdog still applies)
        self.queue: list = []
        self.index = 0


class FakeFirmware:
    """The firmware's command processor behind a pty, with knobs to make it wrong.

    trace         write '#T', '#L' and '#B' records, as a -DFISH_TRACE=1 build
    clock_ppm     the MCU clock runs this much fast
    stretch_ms    every timed step lasts this much longer than asked
    drop_every    every n-th line is lost before the MCU (no echo, no reply)
    wrong_reply   (text, replacement) applied to every reply line
    stuck_running a channel name that STATUS always shows as RUNNING
    ack_mode      behave like the uart_echo sketch instead
    """

    def __init__(self, *, trace: bool = False, clock_ppm: float = 0.0,
                 stretch_ms: float = 0.0, drop_every: int = 0,
                 wrong_reply: Optional[tuple] = None, stuck_running: str = "",
                 ack_mode: bool = False):
        import tty

        self.trace, self.stretch_ms, self.drop_every = trace, stretch_ms, drop_every
        self.wrong_reply, self.stuck_running, self.ack_mode = wrong_reply, stuck_running, ack_mode
        self.received: list = []            # every line that reached the model
        self._rate = 1.0 + clock_ppm * 1e-6
        self._master, self._slave = os.openpty()
        tty.setraw(self._master)
        tty.setraw(self._slave)
        self.path = os.ttyname(self._slave)
        self._ch = {"MOUTH": _Channel("MOUTH", 238, -200, 104),
                    "NECK": _Channel("NECK", 255, -100, 500),
                    "TAIL": _Channel("TAIL", 240, -180, 500)}
        self._out = bytearray()
        self._records: list = []
        self._line = ""
        self._seen = 0
        self._dropping = False
        self._stop = threading.Event()
        self._t0 = time.monotonic()
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()

    def close(self) -> None:
        # Join before closing: the next pty may get the same descriptor numbers, and a
        # thread still in its loop would then answer on the new one.
        self._stop.set()
        self._thread.join(2.0)
        for fd in (self._master, self._slave):
            try:
                os.close(fd)
            except OSError:
                pass

    def _us(self) -> float:
        return (time.monotonic() - self._t0) * self._rate * 1e6

    def _serve(self) -> None:
        self._stop.wait(0.2)    # until the checker has the port open (pyserial flushes)
        if self.ack_mode:
            self._out += b"\x00uart_echo ready\r\n"
        else:
            self._out += (b"\x00\r\n===========================================\r\n"
                          b"BIG MOUTH BILLY BASS\r\nReady for commands!\r\n\n> ")
            if self.trace:
                self._records.append("#B fw=model trace=1")
        next_l = self._us() + 1e6
        last = self._us()
        loops = gap = 0
        while not self._stop.is_set():
            try:
                if select.select([self._master], [], [], 0.0005)[0]:
                    for byte in os.read(self._master, 4096):
                        self._char(chr(byte))
                now = self._us()
                loops, gap, last = loops + 1, max(gap, now - last), now
                self._update(now)
                if self.trace and now >= next_l:
                    self._records.append(f"#L {int(now // 1000)} {loops} {int(gap)}")
                    next_l, loops, gap = next_l + 1e6, 0, 0
                if self._records and not self._line:    # between prompts only
                    for rec in self._records:
                        self._out += f"\r{rec}\r\n> ".encode()
                    self._records.clear()
                if self._out:
                    os.write(self._master, bytes(self._out))
                    self._out.clear()
            except (OSError, ValueError):
                return

    def _char(self, c: str) -> None:
        if not self._line and not self._dropping and c not in "\r\n":
            self._seen += 1
            self._dropping = bool(self.drop_every) and self._seen % self.drop_every == 0
        if self._dropping:
            self._dropping = c not in "\r\n"
            return
        if c in "\r\n":
            line, self._line = self._line, ""
            self.received.append(line)
            if self.ack_mode:
                self._out += f"ACK {line}\r\n".encode()
                return
            self._out += b"\r\n"
            for reply in self._process(line.strip().upper()) if line.strip() else ():
                if self.wrong_reply:
                    reply = reply.replace(*self.wrong_reply)
                self._out += reply.encode() + (b"\n" if reply.endswith("\n") else b"\r\n")
            self._out += b"> "
        elif ord(c) >= 32:
            self._line += c
            if not self.ack_mode:
                self._out += c.encode()     # the firmware echoes each character

    def _drive(self, ch: _Channel, pwm: int, stamp_us: float) -> None:
        if self.trace and pwm != ch.speed:
            pins = "10" if pwm > 0 else "01" if pwm < 0 else "00"
            self._records.append(f"#T {int(stamp_us // 1000)} {int(stamp_us) % (1 << 32)} "
                                 f"{ch.name[0]} {pwm} {pins} {abs(pwm)}")
        ch.speed = pwm

    def _halt(self, ch: _Channel, stamp_us: float) -> None:
        self._drive(ch, 0, stamp_us)
        ch.running, ch.target_ms, ch.queue, ch.index = False, 0, [], 0

    def _set_speed(self, ch: _Channel, pwm: int, ms: int = 0) -> None:
        pwm = max(-MAX_PWM, min(MAX_PWM, pwm))
        now = self._us()
        ch.queue, ch.index = [], 0
        self._drive(ch, pwm, now)
        ch.running, ch.start_us, ch.target_ms = pwm != 0, now, ms

    def _update(self, now: float) -> None:
        for ch in self._ch.values():
            if not ch.running:
                continue
            if ch.queue:
                # Stamped at the moment the step was due, so the model adds no jitter.
                due = ch.start_us + (ch.queue[ch.index][1] + self.stretch_ms) * 1000.0
                if now >= due:
                    ch.index += 1
                    if ch.index < len(ch.queue):
                        ch.start_us = due
                        self._drive(ch, ch.queue[ch.index][0], due)
                    else:
                        self._halt(ch, due)
            elif ch.target_ms:
                due = ch.start_us + (ch.target_ms + self.stretch_ms) * 1000.0
                if now >= due:
                    self._halt(ch, due)
            elif now - ch.start_us > MAX_RUN_TIME_MS * 1000.0:
                self._halt(ch, ch.start_us + (MAX_RUN_TIME_MS + 1) * 1000.0)
                self._out += (R_WATCHDOG.format(name=ch.name) + "\r\n").encode()

    def _status(self, ch: _Channel) -> str:
        running = ch.running or ch.name == self.stuck_running
        text = f"  {ch.name}: " + ("RUNNING" if running else "stopped")
        if running:
            text += f" (pwm {ch.speed}"
            if ch.queue:
                text += f", step {ch.index + 1}/{len(ch.queue)}"
            text += ")"
        return text + f"  [open={ch.open} close={ch.close} pulse={ch.pulse}ms]"

    def _process(self, cmd: str) -> list:
        if cmd in ("HELP", "H"):
            return ["\n" + HELP_LINES[1], *HELP_LINES[2:-2], HELP_LINES[-2] + "\n"]
        if cmd in ("STOP", "S"):
            for ch in self._ch.values():
                self._halt(ch, self._us())
            return [R_STOPPED]
        if cmd in ("STATUS", "GET"):
            return ["\n" + R_STATUS_HEAD, *(self._status(c) for c in self._ch.values()),
                    "==================\n"]
        if cmd.startswith("SET"):
            # Cut at the first three spaces, as handleSet does with indexOf.
            s1 = cmd.find(" ")
            s2 = cmd.find(" ", s1 + 1) if s1 >= 0 else -1
            s3 = cmd.find(" ", s2 + 1) if s2 >= 0 else -1
            if s3 < 0:
                return ["ERROR: usage SET <CH> OPEN|CLOSE|PULSE <value>"]
            param = cmd[s2 + 1:s3]
            ch = self._ch.get(CHANNELS.get(cmd[s1 + 1:s2], ""))
            if ch is None:
                return ["ERROR: unknown channel (MOUTH|NECK|TAIL)"]
            number = re.match(r"[+-]?\d+", cmd[s3 + 1:].strip())   # toInt: leading digits
            value = int(number[0]) if number else 0
            if param == "OPEN":
                ch.open = max(-MAX_PWM, min(MAX_PWM, value))
            elif param == "CLOSE":
                ch.close = max(-MAX_PWM, min(MAX_PWM, value))
            elif param == "PULSE":
                ch.pulse = value
            else:
                return ["ERROR: param must be OPEN|CLOSE|PULSE"]
            return [f"{ch.name} {param} = {value}"]
        word, _, rest = cmd.partition(" ")
        rest = rest.strip()
        ch = self._ch.get(CHANNELS.get(word, ""))
        if ch is None:
            return [R_UNKNOWN]
        if not rest:
            return [R_SPECIFY]
        if rest == "OPEN":
            self._set_speed(ch, ch.open, ch.pulse)
            return []
        if rest == "CLOSE":
            self._set_speed(ch, ch.close, ch.pulse)
            return []
        if rest == "STOP":
            self._halt(ch, self._us())
            return [f"{ch.name} stopped"]
        nums = _ints(rest)
        if nums is None:
            return [R_PARSE]
        if len(nums) == 1:
            self._set_speed(ch, nums[0])
            return [f"{ch.name} -> pwm {nums[0]}"]
        if len(nums) % 2:
            return [R_PAIRS]
        if any(d <= 0 or d > MAX_RUN_TIME_MS for d in nums[1::2]):
            return [R_DURATION]
        now = self._us()
        ch.queue = [(max(-MAX_PWM, min(MAX_PWM, p)), d) for p, d in zip(nums[0::2], nums[1::2])]
        ch.index, ch.running, ch.start_us, ch.target_ms = 0, True, now, 0
        self._drive(ch, ch.queue[0][0], now)
        steps = len(ch.queue)
        return [f"{ch.name} -> {steps} step" + ("" if steps == 1 else " chain")]


def self_test() -> int:
    """Run the real code paths against the model and a fake router. Returns an exit code."""
    import signal
    import tempfile

    failures: list = []

    def check(name: str, ok: bool, detail: str = "") -> None:
        print(f"  {'ok  ' if ok else 'FAIL'} {name}{': ' + detail if detail else ''}")
        if not ok:
            failures.append(name)

    def case(name: str, argv: list, want_code: int, **knobs) -> Report:
        print(f"[self-test] {name}")
        fw = FakeFirmware(**knobs)
        try:
            code = main([argv[0], "--port", fw.path, *argv[1:]])
        finally:
            fw.close()
        check("exit code", code == want_code, f"{code}")
        return main.last_report

    fast = ["--count", "300", "--hz", "300"]
    timing = ["timing", "--drive", "--lengths", "2,10,30", "--repeat", "2",
              "--clock-seconds", "2"]
    rep = case("check, clean firmware", ["check", *fast], 0)
    check("every row passes", [v for _, v, _ in rep.rows[:3]] == ["PASS"] * 3
          and not rep.failed, f"{rep.rows}")
    rep = case("check, 1 line in 50 lost", ["check", *fast], 1, drop_every=50)
    check("lost count", rep.data.get("lost") == 6, f"{rep.data.get('lost')}")
    rep = case("check, a channel stuck RUNNING", ["check", *fast], 1, stuck_running="NECK")
    check("status row fails", rep.verdict("status") == ["FAIL"], f"{rep.rows}")
    case("check, echo sketch flashed", ["check", *fast], 3, ack_mode=True)
    rep = case("soak with the fish's lines and bursts",
               ["soak", "--seconds", "4", "--hz", "33", "--drive", "--bursts",
                "--gesture-every", "1"], 0, trace=True)
    check("every row passes", not rep.failed, f"{rep.failed}")
    rep = case("timing, trace build, held limit", [*timing, "--held"], 0, trace=True)
    check("every row passes", not rep.failed, f"{rep.rows}")
    check("held limit near 5 s", 4.99 <= rep.data.get("held_s", 0) <= 5.1,
          f"{rep.data.get('held_s')}")
    rep = case("timing, pulses 3 ms long", timing, 1, trace=True, stretch_ms=3)
    errs = rep.data.get("pulse_err_us") or [0]
    check("average error near 3000 us", abs(sum(errs) / len(errs) - 3000) <= 500,
          f"{sum(errs) / len(errs):.0f}")
    rep = case("timing, MCU clock 2 % fast", timing, 1, trace=True, clock_ppm=20000)
    check("clock near 20000 ppm", abs(rep.data.get("clock_ppm", 0) - 20000) <= 2000,
          f"{rep.data.get('clock_ppm', 0):.0f}")
    rep = case("timing, no trace records", timing, 0)
    check("rows are SKIP", {v for _, v, _ in rep.rows} == {"SKIP", "INFO"}, f"{rep.rows}")

    with tempfile.TemporaryDirectory() as tmp:
        script, expect = os.path.join(tmp, "v1.script"), os.path.join(tmp, "v1.expect")
        with open(script, "w") as f:
            f.write("# fixture\nPING 1\nMOUTH\nMOUTH 238 14  #drive\nSTOP\n")
        with open(expect, "w") as f:
            f.write(f">>> PING 1\n{R_UNKNOWN}\n\n>>> MOUTH\n{R_SPECIFY}\n\n"
                    f">>> MOUTH 238 14\nMOUTH -> 1 step\n\n>>> STOP\n{R_STOPPED}\n")
        replay = ["replay", "--script", script, "--expect", expect]
        rep = case("replay, motor-safe lines only", replay, 0)
        check("drive line skipped", "1 '#drive'" in rep.rows[0][2], f"{rep.rows}")
        rep = case("replay --drive, one reply reworded", [*replay, "--drive"], 1,
                   wrong_reply=("1 step", "1 steps"))
        check("the line is named", any("MOUTH 238 14" in d for _, _, d in rep.rows),
              f"{rep.rows}")

        print("[self-test] analyze: one line never echoed")
        log = os.path.join(tmp, "link.log")
        with open(log, "w") as f:
            for i, line in enumerate(["MOUTH 238 14", "MOUTH -200 14", "MOUTH 238 30",
                                      "NECK 230 650", "STOP"]):
                t = 100.0 + i * GRID_MS / 1000.0
                f.write(f"{t:.6f} T {line}\n")
                if line != "NECK 230 650":
                    reply = expected_reply(line)[0]
                    f.write(f"{t + 0.003:.6f} R {(line + chr(13) + chr(10) + reply).encode()!r}\n"
                            f"{t + 0.004:.6f} R {b'\r\n> '!r}\n")
        code = main(["analyze", log])
        check("exit code", code == 1, f"{code}")
        check("names the line", main.last_report.data.get("lost") == ["NECK 230 650"],
              f"{main.last_report.data.get('lost')}")

        try:
            import msgpack  # noqa: F401
        except ImportError:
            print("[self-test] router cases skipped: 'msgpack' is not installed")
        else:
            sock = os.path.join(tmp, "router.sock")
            router = uart_check._FakeRouter(sock)
            try:
                released = ["--release-router", "--router-socket", sock]
                print("[self-test] --release-router: close before, open after")
                fw = FakeFirmware()
                try:
                    code = main(["check", "--port", fw.path, *released, *fast])
                    check("exit code", code == 0, f"{code}")
                    check("close/open pair", router.calls == [
                        ("$/serial/close", [fw.path]), ("$/serial/open", [fw.path])],
                          f"{router.calls}")

                    print("[self-test] SIGTERM in the middle of a soak")
                    router.calls.clear()
                    timer = threading.Timer(1.5, os.kill, (os.getpid(), signal.SIGTERM))
                    timer.start()
                    try:
                        code = main(["soak", "--port", fw.path, *released, "--seconds", "30",
                                     "--drive"])
                    finally:
                        timer.cancel()
                    check("exit code 130", code == 130, f"{code}")
                    check("port handed back", router.calls == [
                        ("$/serial/close", [fw.path]), ("$/serial/open", [fw.path])],
                          f"{router.calls}")
                    time.sleep(0.1)
                    check("STOP was the last line", fw.received[-1:] == ["STOP"],
                          f"{fw.received[-2:]}")

                    print("[self-test] link lock held elsewhere: refuse before the router")
                    router.calls.clear()
                    holder = link_lock(fw.path)
                    try:
                        code = main(["check", "--port", fw.path, *released, *fast])
                    finally:
                        holder.close()
                    check("exit code 2", code == 2, f"{code}")
                    check("router never called", router.calls == [], f"{router.calls}")
                finally:
                    fw.close()
            finally:
                router.close()

    print("[self-test] " + ("FAILED: " + ", ".join(failures) if failures else "all passed"))
    return 1 if failures else 0


# --- command line --------------------------------------------------------------------------------

COMMANDS = ("check", "replay", "timing", "soak", "send", "listen", "analyze")


def _parse(argv: Optional[list]) -> argparse.Namespace:
    argv = list(sys.argv[1:] if argv is None else argv)
    if "--self-test" in argv:
        return argparse.Namespace(self_test=True)
    if not argv or argv[0] not in COMMANDS + ("-h", "--help"):
        argv.insert(0, "check")         # `check` is the default sub-command

    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--port", default="/dev/ttyHS1",
                        help="serial device (default: %(default)s, the UNO Q internal UART)")
    common.add_argument("--baud", type=int, default=115200)
    common.add_argument("--release-router", action="store_true",
                        help="UNO Q: ask the router to release --port first and hand it "
                             "back on exit")
    common.add_argument("--keep-released", action="store_true",
                        help="with --release-router: do not hand the port back on exit")
    common.add_argument("--router-socket", default="/var/run/arduino-router.sock",
                        help="router address: unix socket path or tcp://host:port")
    common.add_argument("--force", action="store_true",
                        help="do not take the link lock (the fish may be using the port)")
    common.add_argument("--md", action="store_true",
                        help="print the result as a markdown table (for docs/results)")
    common.add_argument("--timeout", type=float, default=2.0,
                        help="seconds for each router call (default: %(default)s)")
    common.add_argument("--line-timeout", type=float, default=1.0,
                        help="seconds to wait for the echo, reply and prompt of one line")
    common.add_argument("--settle", type=float, default=0.5,
                        help="seconds to listen before the first line (boot text)")

    p = argparse.ArgumentParser(
        description="Check the fish firmware over the motor-MCU link.",
        epilog="Exit code: 0 pass, 1 mismatch, 2 could not run, 3 an echo sketch "
               "answered. `--self-test` needs no hardware.")
    p.add_argument("--self-test", action="store_true",
                   help="check this tool against a model of the firmware, then exit")
    sub = p.add_subparsers(dest="cmd", metavar="{" + ",".join(COMMANDS) + "}")

    c = sub.add_parser("check", parents=[common],
                       help="motor-safe: PING probe, STATUS, a soak of PING lines (default)")
    c.add_argument("--count", type=int, default=DEFAULT_COUNT, help="soak lines")
    c.add_argument("--hz", type=float, default=DEFAULT_HZ,
                   help="send rate (default: %(default)s, the app's command-rate cap)")

    c = sub.add_parser("replay", parents=[common],
                       help="send the protocol script, compare each reply")
    c.add_argument("--script", help="v1.script (default: ../Big_mouth/protocol, then "
                                    "~/fish_fw/protocol)")
    c.add_argument("--expect", help="v1.expect, same search")
    c.add_argument("--drive", action="store_true",
                   help="also send the lines marked '#drive' (outputs move)")

    c = sub.add_parser("timing", parents=[common],
                       help="trace build: truth table, pulse lengths, chains, clock")
    c.add_argument("--drive", action="store_true", help="required: every row drives outputs")
    c.add_argument("--held", action="store_true",
                   help=f"also hold MOUTH {HELD_PWM} until the firmware's 5 s limit stops it")
    c.add_argument("--lengths", default=DEFAULT_LENGTHS,
                   help="pulse lengths in ms (default: %(default)s)")
    c.add_argument("--repeat", type=int, default=5, help="pulses per length")
    c.add_argument("--pulse-min", type=float, default=-1.0,
                   help="pass line: shortest allowed error in ms (default: %(default)s)")
    c.add_argument("--pulse-max", type=float, default=2.0,
                   help="pass line: longest allowed error in ms (default: %(default)s)")
    c.add_argument("--clock-pct", type=float, default=0.1,
                   help="pass line: MCU clock against the host, percent (default: %(default)s)")
    c.add_argument("--stop-ms", type=float, default=5.0,
                   help="pass line: output off this long after STOP (default: %(default)s)")
    c.add_argument("--clock-seconds", type=float, default=10.0,
                   help="span of stamps wanted for the clock row (default: %(default)s)")

    c = sub.add_parser("soak", parents=[common], help="a long run on the 33 Hz grid")
    c.add_argument("--seconds", type=float, default=60.0)
    c.add_argument("--hz", type=float, default=DEFAULT_HZ)
    c.add_argument("--drive", action="store_true",
                   help="send the fish's real MOUTH / NECK / TAIL lines instead of PING")
    c.add_argument("--bursts", action="store_true",
                   help="with --drive: write each gesture back to back with a MOUTH line")
    c.add_argument("--gesture-every", type=float, default=3.0,
                   help="with --drive: seconds between gestures (default: %(default)s)")

    c = sub.add_parser("send", parents=[common], help="write one line, print what comes back")
    c.add_argument("line")
    c.add_argument("--wait", type=float, default=1.0, help="seconds to listen")
    c.add_argument("--held", action="store_true",
                   help="allow a line that holds a PWM (`MOUTH <n>`)")

    c = sub.add_parser("listen", parents=[common],
                       help="print what arrives (the probe sketch's 'PP ' lines)")
    c.add_argument("--seconds", type=float, default=5.0)

    c = sub.add_parser("analyze", help="report on a link log written with FISH_LINK_LOG")
    c.add_argument("log")
    c.add_argument("--grid-ms", type=float, default=GRID_MS,
                   help="mouth frame period (default: %(default).1f)")
    c.add_argument("--md", action="store_true")

    args = p.parse_args(argv)
    args.self_test = False
    if args.cmd == "analyze":
        return args
    if args.keep_released and not args.release_router:
        p.error("--keep-released only makes sense with --release-router")
    if args.cmd in ("check", "soak") and args.hz <= 0:
        p.error("--hz must be > 0")
    if args.cmd == "check" and args.count < 1:
        p.error("--count must be >= 1")
    if args.cmd == "timing":
        if not args.drive:
            p.error("timing drives the outputs: give --drive (and be at the fish)")
        try:
            args.lengths = [int(x) for x in args.lengths.split(",") if x.strip()]
        except ValueError:
            p.error("--lengths is a comma-separated list of milliseconds")
        if not args.lengths or min(args.lengths) < 1 or max(args.lengths) > MAX_RUN_TIME_MS:
            p.error(f"--lengths must be 1..{MAX_RUN_TIME_MS}")
    if args.cmd == "soak" and args.bursts and not args.drive:
        p.error("--bursts only makes sense with --drive")
    if args.cmd == "send" and HELD_RE.match(args.line) and not args.held:
        p.error(f"{args.line!r} holds a PWM until the next command: give --held")
    return args


def main(argv: Optional[list] = None) -> int:
    args = _parse(argv)
    if args.self_test:
        return self_test()
    rep = main.last_report = Report()
    if args.cmd == "analyze":
        code = analyze(args.log, rep, args.grid_ms)
        if code != 2:
            rep.show(args.md, "analyze")
        return code
    drives = bool(getattr(args, "drive", False) or getattr(args, "held", False))
    lock = None
    code = 2
    try:
        if args.cmd == "replay":
            args.protocol = load_protocol(args)
        # Before any router call: a running fish holds this lock, and must keep its port.
        if not args.force:
            lock = link_lock(args.port)
        with router_released(args.port, args.router_socket, args.timeout,
                             args.keep_released, release=args.release_router,
                             tag="fw_check") as rel:
            # pyserial opens the tty raw with echo off: what the MCU prints is not sent
            # back to it as input.
            transport = rel.transport = SerialTransport(args.port, args.baud)
            print(f"[fw_check] {args.cmd} on {transport.label}"
                  + (" (drives the outputs)" if drives else " (motor-safe)"), flush=True)
            if args.cmd == "listen":
                count = dump(transport, args.seconds)
                print(f"[fw_check] {count} lines in {args.seconds:g} s")
                return 0
            if args.cmd == "send":
                transport.write_line(args.line)
                dump(transport, args.wait)
                return 0
            sess = Session(transport, args.line_timeout)
            special = None
            interrupted = False
            try:
                sess.start(args.settle)
                special = {"check": cmd_check, "replay": cmd_replay, "timing": cmd_timing,
                           "soak": cmd_soak}[args.cmd](sess, args, rep)
            except KeyboardInterrupt:
                interrupted = True
                rep.add(args.cmd, "FAIL", "interrupted")
            finally:
                if sess.drove:
                    try:        # STOP on every way out
                        transport.write_line("STOP")
                    except Exception as e:
                        print(f"[fw_check] could not send STOP: {e}", file=sys.stderr)
                sess.stop()
            if sess.error and not rep.failed:
                rep.add("link", "FAIL", sess.error)
            if sess.m.junk:
                rep.add("before first line", "INFO", _samples(repr(j[:60]) for j in sess.m.junk))
            rep.show(args.md, args.cmd)
            code = 130 if interrupted else special or (1 if rep.failed or not rep.rows else 0)
        if rel.handback_failed:
            code = code or 2
    except SetupError as e:
        print(f"[fw_check] {e}", file=sys.stderr)
    except (RouterError, OSError) as e:
        print(f"[fw_check] {type(e).__name__}: {e}", file=sys.stderr)
    except KeyboardInterrupt:
        print("\n[fw_check] interrupted", file=sys.stderr)
        code = 130
    finally:
        if lock is not None:
            lock.close()
    return code


main.last_report = Report()

if __name__ == "__main__":
    sys.exit(main())
