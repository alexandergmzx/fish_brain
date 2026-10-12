"""The debug hub: what the running fish knows about itself, kept for the `/debug` page.

One object, created by `app.py` when the page server runs (`--viz`). It holds:

- a tee on `sys.stdout` / `sys.stderr`: every printed line, with its time, stream, tag and
  thread, in a ring (the journal on the board keeps the full history; C-level lines such as
  PortAudio's and crash traces never pass through Python and stay there only);
- rings of structured records the other modules hand in through the functions below: every
  key of the remote, one record per turn, each performance, the lines sent to the motors and
  what the MCU sent back, the page's own events;
- the newest microphone recording, in memory only, replaced by the next one;
- the slow state for `GET /debug/state` (configuration in effect, devices, link, board).

Rules this module keeps:

- The functions other modules call (`emit`, `key`, `tx`, `turn_*`, ...) do nothing when no hub
  exists and never raise into their caller: a fault here must never break a turn or a print.
  They catch `Exception`, never more: a stop request (KeyboardInterrupt) passes.
- The hub never prints.
- Every record is scrubbed where it enters a ring: the page token and the values of variables
  ending in `_API_KEY` never reach a page. `FISH_PTT_KEY` is a key *code*, not a secret.
- Standard library only at import; numpy is used lazily for the recording's statistics.
"""
from __future__ import annotations

import io
import json
import os
import re
import sys
import threading
import time
from collections import deque
from pathlib import Path

LOG_LINES = 2000          # the ring of printed lines
BOOT_LINES = 200          # the first lines of the process, never evicted (the start-up summary)
LINE_MAX = 2000           # characters kept of one line
PARTIAL_MAX = 4096        # a line with no newline is cut here
RECORDING_MAX = 6 * 1024 * 1024    # bytes: 45 s at 48 kHz mono 16-bit is 4.3 MB
MAX_STREAMS = 4           # debug pages at once (their own list: never one of the phones' 8)
RINGS = {"log": LOG_LINES, "key": 300, "press": 200, "turn": 200, "perf": 100, "tx": 1000,
         "page": 300, "level": 400, "action": 100, "http": 100, "sys": 240}
_TAG = re.compile(r"^\[([a-z]+)\]")
_SECRET_PATTERNS = (re.compile(r"\b(sk|gsk)[-_][A-Za-z0-9_\-]{12,}"),
                    re.compile(r"Bearer\s+[A-Za-z0-9._\-]{8,}"))
# Letters, digits, punctuation and space: a keyboard's text keys. The key feed counts them
# without naming them, so it can never show what somebody typed.
_TEXT_KEYS = frozenset([*range(2, 14), *range(16, 28), *range(30, 42), *range(43, 54), 57,
                        *range(71, 84)])

_hub: "DebugHub | None" = None


class _Tee:
    """Stands in for sys.stdout / sys.stderr: the real stream first, then the hub."""

    def __init__(self, orig, name: str, hub: "DebugHub"):
        self._orig, self._name, self._hub = orig, name, hub

    def write(self, s):
        n = self._orig.write(s)
        try:
            self._hub._feed(self._name, s)
        except Exception:
            self._hub.errors += 1
        return n

    def flush(self):
        return self._orig.flush()

    def __getattr__(self, name):             # fileno, isatty, encoding, buffer...
        return getattr(self._orig, name)


class DebugHub:
    def __init__(self, cfg=None):
        self.boot = os.urandom(4).hex()      # tells a page that the process restarted
        self.started = time.time()
        self.errors = 0                      # faults swallowed in the hooks and the tee
        self._lock = threading.Lock()
        self._seq = 0
        self._rings = {k: deque(maxlen=n) for k, n in RINGS.items()}
        self._boot_log: list[dict] = []
        self._partial: dict[tuple[int, str], str] = {}
        self._local = threading.local()
        self._secrets: list[str] = []
        self._streams: list[dict] = []       # debug pages connected, oldest first
        self._turn: dict | None = None       # the turn being built (the turn loop's thread)
        self._turn_id = 0
        self._rec: dict | None = None        # the newest recording {wav, origin, t, turn, stats}
        self._key_other: dict[str, int] = {}
        self._text_keys = 0
        self._press: dict = {}
        self.counters = {"tx": 0, "tx_dropped": 0, "rx_bytes": 0, "page_dropped": 0,
                         "page_evicted": 0, "last_viewer": 0.0}
        self.cfg = cfg
        self.args = None
        self.link = None
        self.convo = None
        self.viz = None
        self.actions = None
        self.rx_tail = ""
        self._code_sig = _code_signature()
        self._collect_secrets(cfg)

    # ---- secrets ----------------------------------------------------------------------------

    def _collect_secrets(self, cfg) -> None:
        found = []
        token = getattr(getattr(cfg, "viz", None), "token", "") if cfg is not None else ""
        if token:
            found.append(token)
        for name, value in os.environ.items():
            if name.endswith("_API_KEY") and len(value) >= 8:
                found.append(value)
        self._secrets = sorted(set(found), key=len, reverse=True)

    def scrub(self, text: str) -> str:
        for s in self._secrets:
            if s in text:
                text = text.replace(s, "•••")
        for pat in _SECRET_PATTERNS:
            text = pat.sub("•••", text)
        return text

    def _clean(self, value, depth: int = 0):
        if isinstance(value, str):
            return self.scrub(value)
        if depth < 4:
            if isinstance(value, dict):
                return {k: self._clean(v, depth + 1) for k, v in value.items()}
            if isinstance(value, (list, tuple)):
                return [self._clean(v, depth + 1) for v in value]
        return value

    # ---- records ----------------------------------------------------------------------------

    def emit(self, kind: str, **fields) -> dict:
        rec = {"kind": kind, "t": round(time.time(), 3)}
        rec.update(self._clean(fields))
        with self._lock:
            self._seq += 1
            rec["seq"] = self._seq
            ring = self._rings.get(kind)
            if ring is None:
                ring = self._rings[kind] = deque(maxlen=100)
            ring.append(rec)
            if kind == "log" and len(self._boot_log) < BOOT_LINES:
                self._boot_log.append(rec)
        return rec

    def since(self, seq: int, limit: int = 200) -> list[dict]:
        """Records newer than `seq`, oldest first, at most `limit` (the stream sends in ticks,
        so a page loading the whole history never holds the lock or the GIL for long)."""
        with self._lock:
            if seq >= self._seq:
                return []
            out = [r for ring in self._rings.values() for r in ring if r["seq"] > seq]
            if seq < (self._boot_log[-1]["seq"] if self._boot_log else 0):
                first = self._rings["log"][0]["seq"] if self._rings["log"] else 0
                out.extend(r for r in self._boot_log if seq < r["seq"] < first)
        out.sort(key=lambda r: r["seq"])
        return out[:limit]

    def recent(self, kind: str, n: int = 50) -> list[dict]:
        with self._lock:
            return list(self._rings.get(kind, ()))[-n:]

    @property
    def seq(self) -> int:
        return self._seq

    # ---- the log tee ------------------------------------------------------------------------

    def _feed(self, stream: str, s: str) -> None:
        if not isinstance(s, str) or not s:
            return
        if getattr(self._local, "busy", False):
            return                           # re-entered (a write from inside the hub): pass
        self._local.busy = True
        try:
            key = (threading.get_ident(), stream)
            buf = self._partial.pop(key, "") + s
            *lines, rest = buf.split("\n")
            if len(rest) > PARTIAL_MAX:
                lines.append(rest)
                rest = ""
            if rest:
                self._partial[key] = rest
            for line in lines:
                if line.strip():
                    self._log_line(stream, line)
        finally:
            self._local.busy = False

    def _log_line(self, stream: str, line: str) -> None:
        line = line.rstrip("\r")
        m = _TAG.match(line)
        tag = m.group(1) if m else ("you" if line.startswith("you> ") else
                                    "fish" if line.startswith("fish> ") else "")
        self.emit("log", stream=stream, tag=tag, thread=threading.current_thread().name,
                  text=line[:LINE_MAX])

    # ---- the remote's keys ------------------------------------------------------------------

    def key(self, dev: str, name: str, code: int, key: str, value: int, configured: bool,
            armed: bool = False, held: bool = False) -> None:
        if value == 2:
            return                           # autorepeat
        text = (not configured) and code in _TEXT_KEYS
        if text:
            self._text_keys += 1
            key, code = "text key", 0
        elif not configured and value == 1:
            self._key_other[key] = self._key_other.get(key, 0) + 1
        self.emit("key", dev=dev, name=name, key=key, code=code, value=value,
                  configured=configured, armed=armed, held=held)
        if text:
            return
        slot = (dev, key)
        if value == 1:
            self._press[slot] = time.monotonic()
        elif value == 0 and slot in self._press:
            held_s = round(time.monotonic() - self._press.pop(slot), 3)
            self.emit("press", source="remote", dev=dev, name=name, key=key, held_s=held_s,
                      configured=configured,
                      outcome=("not configured" if not configured else
                               "counted" if armed else "ignored: not waiting"))

    # ---- turns ------------------------------------------------------------------------------

    def turn_open(self) -> None:
        self._turn = {"times": {}}

    def turn_set(self, **fields) -> None:
        if self._turn is None:
            self._turn = {"times": {}}
        times = fields.pop("times", None)
        if times:
            self._turn["times"].update({k: round(float(v), 3) for k, v in times.items()})
        self._turn.update(fields)

    def turn_close(self, outcome: str | None = None, error: BaseException | None = None) -> None:
        turn, self._turn = self._turn, None
        if turn is None:
            turn = {"times": {}}
        if outcome:
            turn["outcome"] = outcome
        if error is not None:
            turn["error"] = {"type": type(error).__name__, "text": str(error)[:400]}
        if not (turn.get("outcome") or turn["times"] or turn.get("error")):
            return                           # nothing happened (an inbox item, a quit)
        turn.setdefault("outcome", "spoken")
        if turn["outcome"] == "spoken" and (turn.get("perf") or {}).get("result", "ok") != "ok":
            turn["outcome"] = "not heard: playback failed"
        self._turn_id += 1
        turn["id"] = self._turn_id
        rec = self._rec
        if rec is not None and rec.get("turn") is None and turn.pop("has_rec", False):
            rec["turn"] = self._turn_id
            turn["rec"] = self.recording_stats()
        self.emit("turn", **turn)

    # ---- the newest recording ---------------------------------------------------------------

    def recording(self, path, origin: str = "host") -> None:
        """Keep the bytes of a recording (called before it is transcribed and unlinked). Only
        the read happens here; the statistics are computed when first asked for."""
        p = Path(path)
        size = p.stat().st_size
        self._rec = {"wav": p.read_bytes() if size <= RECORDING_MAX else None, "bytes": size,
                     "origin": origin, "t": round(time.time(), 3), "turn": None, "stats": None}
        if self._turn is not None:
            self._turn["has_rec"] = True

    def recording_bytes(self) -> bytes | None:
        rec = self._rec
        return rec["wav"] if rec else None

    def recording_stats(self) -> dict | None:
        rec = self._rec
        if rec is None:
            return None
        if rec["stats"] is None:
            stats = {"origin": rec["origin"], "bytes": rec["bytes"], "t": rec["t"],
                     "kept": rec["wav"] is not None}
            if rec["wav"] is not None:
                try:
                    stats.update(wav_stats(rec["wav"]))
                except Exception as e:
                    stats["error"] = type(e).__name__
            rec["stats"] = stats
        out = dict(rec["stats"])
        out["turn"] = rec["turn"]
        return out

    # ---- debug pages ------------------------------------------------------------------------

    def stream_open(self) -> dict:
        me = {"closed": False, "since": time.time()}
        with self._lock:
            self._streams.append(me)
            while len(self._streams) > MAX_STREAMS:
                self._streams.pop(0)["closed"] = True
        self.counters["last_viewer"] = time.monotonic()
        return me

    def stream_close(self, me: dict) -> None:
        with self._lock:
            if me in self._streams:
                self._streams.remove(me)

    def viewers(self) -> int:
        return len(self._streams)

    # ---- state ------------------------------------------------------------------------------

    def attach(self, **objects) -> None:
        for name, obj in objects.items():
            setattr(self, name, obj)

    def state(self) -> dict:
        from . import debug_state
        return self._clean(debug_state.build(self))

    def code_changed(self) -> bool:
        return _code_signature() != self._code_sig


def wav_stats(data: bytes) -> dict:
    """What a recording is made of: enough to tell a dead microphone (exact zeros) from a
    quiet room, a clipped one from a loud child."""
    import wave
    import numpy as np
    with wave.open(io.BytesIO(data), "rb") as w:
        rate, channels, width, n = (w.getframerate(), w.getnchannels(), w.getsampwidth(),
                                    w.getnframes())
        raw = w.readframes(n)
    if width != 2 or not raw:
        return {"rate": rate, "dur_s": round(n / rate, 2) if rate else 0.0, "samples": n}
    a = np.frombuffer(raw, dtype="<i2")
    if channels > 1:
        a = a[::channels]
    f = a.astype(np.float32) / 32768.0
    zero = a == 0
    lead = int(np.argmax(~zero)) if (~zero).any() else len(a)
    return {"rate": rate, "dur_s": round(len(a) / rate, 2), "samples": int(len(a)),
            "rms": round(float(np.sqrt(np.mean(f * f))), 4),
            "peak": round(float(np.max(np.abs(f))), 4),
            "zero_frac": round(float(zero.mean()), 4),
            "clip_frac": round(float((np.abs(a) >= 32700).mean()), 4),
            "lead_zero_s": round(lead / rate, 2)}


def _code_signature() -> tuple:
    """Names, sizes and times of the package's Python files: differs once the tree was synced
    after this process started (the new code is not running until a restart)."""
    try:
        here = Path(__file__).parent
        return tuple(sorted((p.name, p.stat().st_size, int(p.stat().st_mtime))
                            for p in here.glob("*.py")))
    except Exception:
        return ()


# ---- what the other modules call: no hub, no effect; never raises ---------------------------

def install(cfg=None) -> DebugHub:
    """Create the hub and put the tee on stdout and stderr."""
    global _hub
    hub = DebugHub(cfg)
    sys.stdout = _Tee(sys.stdout, "out", hub)
    sys.stderr = _Tee(sys.stderr, "err", hub)
    _hub = hub
    return hub


def uninstall() -> None:
    """Take the tee off again (only where it is still ours)."""
    global _hub
    for name in ("stdout", "stderr"):
        stream = getattr(sys, name)
        if isinstance(stream, _Tee) and stream._hub is _hub:
            setattr(sys, name, stream._orig)
    _hub = None


def hub() -> DebugHub | None:
    return _hub


def _safe(fn):
    def call(*args, **kwargs):
        h = _hub
        if h is None:
            return None
        try:
            return fn(h, *args, **kwargs)
        except Exception:
            h.errors += 1
            return None
    call.__name__ = fn.__name__
    call.__doc__ = fn.__doc__
    return call


@_safe
def emit(h, kind: str, **fields):
    """One structured record."""
    h.emit(kind, **fields)


@_safe
def key(h, dev, name, code, key_name, value, configured, armed=False, held=False):
    """One EV_KEY event of a device the remote thread reads."""
    h.key(dev, name, code, key_name, value, configured, armed, held)


@_safe
def tx(h, line: str, flag: str = ""):
    """One line handed to the motor link (`flag`: "" sent, "dropped" with no link)."""
    h.counters["tx_dropped" if flag == "dropped" else "tx"] += 1
    h.emit("tx", line=line, flag=flag)


@_safe
def rx(h, data: bytes):
    """What the MCU sent back (its echo, "Unknown command", a boot banner after a reset)."""
    if not data:
        return
    h.counters["rx_bytes"] += len(data)
    # The firmware echoes every character, so one record per chunk would only mirror the
    # lines sent: a rolling tail is kept instead and served with the state.
    h.rx_tail = (h.rx_tail + data.decode("ascii", "replace"))[-2000:]


@_safe
def turn_open(h):
    h.turn_open()


@_safe
def turn_set(h, **fields):
    h.turn_set(**fields)


@_safe
def turn_close(h, outcome=None, error=None):
    h.turn_close(outcome, error)


@_safe
def recording(h, path, origin="host"):
    h.recording(path, origin)


@_safe
def page_event(h, data: str):
    """An event the page server publishes to the phones, copied for the debug page."""
    if data.startswith('{"type": "level"'):
        h.emit("level", rms=json.loads(data).get("rms", 0.0))
        return
    ev = json.loads(data)
    if ev.get("type") == "speak":
        ev = {k: v for k, v in ev.items() if k not in ("mouth", "gestures")}
    h.emit("page", ev=ev)


@_safe
def count(h, name: str, n: int = 1):
    h.counters[name] = h.counters.get(name, 0) + n
