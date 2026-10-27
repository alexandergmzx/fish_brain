"""Push-to-talk microphone capture.

Hold a key to record from the mic; release to stop. Writes a mono WAV and returns its path.
We prefer 16 kHz (what faster-whisper uses), but fall back to the device's native rate if it
rejects 16 kHz — faster-whisper resamples to 16 kHz internally, so any WAV rate works.

Two ways to say "talk now":
- `record_hold`: a keyboard key via `pynput` (needs a display), else Enter-to-toggle in a
  terminal (never without a TTY: a service has no stdin to read).
- `record_multi`: any number of button-like sources (the browser's hold-to-talk button, a
  remote's button via evdev). Recording starts on a fresh press of any of them. An optional
  inbox (a zero-argument callable) can hand it an input item from the page instead; the wait
  ends with that item and no microphone is opened. A source marked `relay` is not recorded
  from: its edges are handed to a `relay(held)` callable (the page then records with the
  phone's microphone and the recording comes back through the inbox).
"""
from __future__ import annotations

import os
import subprocess
import select
import queue
import sys
import tempfile
import time
import wave
from pathlib import Path
from typing import Callable

import numpy as np

from .config import PTTConfig

# How often to report the live mic level (Hz). Throttled so we don't flood the viz SSE.
_LEVEL_HZ = 25.0


class MicError(RuntimeError):
    """The microphone could not be opened or read (unplugged, wrong name, busy)."""


class PTTUnavailable(Exception):
    """There is no way to trigger a recording (no TTY, no button). Not a per-turn error."""


class ButtonSource:
    """A push-to-talk source: something that is held or not, and can be forced back to idle."""

    def __init__(self, is_held: Callable[[], bool], reset: Callable[[], None] | None = None,
                 arm: Callable[[bool], None] | None = None, name: str = "button",
                 relay: bool = False):
        self.is_held = is_held
        self._reset = reset
        self._arm = arm
        self.name = name
        # True: `record_multi` hands this source's edges to its `relay` callable instead of
        # recording here. Re-evaluated by the caller before every wait.
        self.relay = relay

    def reset(self) -> None:
        if self._reset is not None:
            self._reset()

    def arm(self, on: bool) -> None:
        if self._arm is not None:
            self._arm(on)


def wav_duration_s(path: str | Path) -> float:
    with wave.open(str(path), "rb") as w:
        return w.getnframes() / float(w.getframerate() or 1)


def _write_wav(path: Path, frames: list[np.ndarray], samplerate: int) -> None:
    data = np.concatenate(frames) if frames else np.zeros(0, dtype=np.int16)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)  # int16
        w.setframerate(samplerate)
        w.writeframes(data.astype("<i2").tobytes())


def wav_rms(path: str | Path) -> float:
    """Overall RMS (0..1) of a recorded int16 mono WAV — for silence detection."""
    with wave.open(str(path), "rb") as w:
        raw = w.readframes(w.getnframes())
    if not raw:
        return 0.0
    a = np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768.0
    return float(np.sqrt(np.mean(a * a))) if a.size else 0.0


def _pulse_device(sd):
    """Index of the PipeWire/Pulse-backed input PCM ('pulse', else 'default'), or None."""
    names = {}
    for i, d in enumerate(sd.query_devices()):
        if d["max_input_channels"] > 0 and d["name"] not in names:
            names[d["name"]] = i
    for n in ("pulse", "default"):
        if n in names:
            return names[n]
    return None


def _named_device(sd, device, kind: str):
    """Turn a configured device (index, digit string, or name substring) into an index."""
    if device is None or isinstance(device, int):
        return device
    text = str(device).strip()
    if text.isdigit():
        return int(text)
    key = "max_input_channels" if kind == "input" else "max_output_channels"
    for i, d in enumerate(sd.query_devices()):
        if d[key] > 0 and text.lower() in d["name"].lower():
            return i
    raise MicError(f"no {kind} audio device matches {text!r}")


def _resolve_input(sd, cfg: PTTConfig):
    """Pick (device, samplerate) for the InputStream.

    A PipeWire/Pulse `source` name is selected via the PULSE_SOURCE env var and recorded
    through the 'pulse' PCM (it resamples, so 16 kHz works). Otherwise a raw device index (or
    the default) is used, falling back to the device's native rate if it rejects 16 kHz
    (-9997) — faster-whisper resamples to 16 kHz internally, so any rate is fine.
    """
    if cfg.source:
        os.environ["PULSE_SOURCE"] = cfg.source
        pulse = _pulse_device(sd)
        if pulse is not None:
            return pulse, cfg.samplerate
        print("[ptt] no PipeWire/Pulse PCM found; falling back to the default device", flush=True)
    else:
        os.environ.pop("PULSE_SOURCE", None)  # don't leak a previous selection
    device = _named_device(sd, cfg.device, "input")
    try:
        sd.check_input_settings(device=device, channels=cfg.channels, samplerate=cfg.samplerate)
        return device, cfg.samplerate
    except Exception:
        sr = int(sd.query_devices(device, "input")["default_samplerate"])
        print(f"[ptt] device rejects {cfg.samplerate} Hz; recording at {sr} Hz instead", flush=True)
        return device, sr


class _PwRecord:
    """`pw-record` of one PipeWire source as raw 16-bit mono on stdout. A subprocess, so a
    microphone that never starts cannot hang the turn loop (2026-10-13): no audio within
    `open_timeout_s` is a MicError, and the process is always ended on the way out."""

    def __init__(self, cfg: PTTConfig):
        import shutil
        exe = shutil.which("pw-record")
        if exe is None:
            raise MicError("pw-record not found")
        self.rate = cfg.samplerate
        self._proc = subprocess.Popen(
            [exe, "--target", cfg.source, "--rate", str(cfg.samplerate), "--channels", "1",
             "--format", "s16", "--raw", "-"],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        self._fd = self._proc.stdout.fileno()
        self._deadline = time.monotonic() + cfg.open_timeout_s
        self._got = False
        self._buf = b""

    def get(self, timeout: float):
        ready, _, _ = select.select([self._fd], [], [], timeout)
        if not ready:
            if not self._got and time.monotonic() > self._deadline:
                raise MicError("the microphone sent nothing (pw-record)")
            if self._proc.poll() is not None:
                raise MicError("pw-record ended")
            return None
        data = os.read(self._fd, 8192)
        if not data:
            raise MicError("pw-record ended")
        self._got = True
        self._buf += data
        n = len(self._buf) // 2 * 2
        out = np.frombuffer(self._buf[:n], dtype="<i2").copy()
        self._buf = self._buf[n:]
        return out if out.size else None

    def close(self) -> None:
        p = self._proc
        if p.poll() is None:
            p.terminate()
            try:
                p.wait(timeout=0.5)
            except subprocess.TimeoutExpired:
                p.kill()


# Microphone health for FISH_MIC_CAPTURE=auto: takes in a row that were exact zeros.
_zero_takes = 0


def mic_dead(cfg: PTTConfig) -> bool:
    """The board's microphone streams nothing (two takes of exact zeros in a row), or its
    PipeWire source is gone: the remote's presses go to a phone microphone instead."""
    if _zero_takes >= 2:
        return True
    if cfg.source and cfg.backend == "pw-record":
        try:
            from . import pw
            sources = pw.cache().sources()
            if sources and not any(s["name"] == cfg.source for s in sources):
                return True
        except Exception:
            pass
    return False


def _note_take(frames) -> None:
    global _zero_takes
    if not frames:
        return
    if any(f.any() for f in frames):
        _zero_takes = 0
    else:
        _zero_takes += 1


class _SilenceEnd:
    """The silence end (cfg.silence_end_s, 0 = off): a recording ends once no chunk has reached
    cfg.quiet_rms for that long, counted from the start of the recording and from the last
    chunk at or above the level. The level sits over the remote's room floor (0.01 to 0.03
    RMS, 2026-10-12) and under speech (0.10 and up)."""

    def __init__(self, cfg: PTTConfig):
        self.after_s = float(cfg.silence_end_s or 0.0)
        self.level = float(cfg.quiet_rms)
        self.last_sound = time.monotonic()

    def over(self, chunk: np.ndarray | None) -> bool:
        """Feed one int16 chunk (None: a poll that brought nothing, which counts as quiet);
        True when the recording should end here."""
        if self.after_s <= 0:
            return False
        now = time.monotonic()
        f = chunk.astype(np.float32) / 32768.0 if chunk is not None else None
        if f is not None and f.size and float(np.sqrt(np.mean(f * f))) >= self.level:
            self.last_sound = now
            return False
        return now - self.last_sound >= self.after_s


def _record_until(stop_predicate, cfg: PTTConfig,
                  on_level: Callable[[float], None] | None = None) -> Path:
    """Record from the mic until `stop_predicate()` returns True.

    If `on_level` is given, it's called with the per-chunk RMS (0..1) at ~`_LEVEL_HZ`
    so the web GUI can draw a live level meter while recording.
    """
    if cfg.backend == "pw-record" and cfg.source:
        return _record_pw(stop_predicate, cfg, on_level)
    try:
        import sounddevice as sd
        device, samplerate = _resolve_input(sd, cfg)
    except MicError:
        raise
    except Exception as e:      # PortAudio missing, no input device, bad index...
        raise MicError(f"microphone unavailable: {e}") from e
    q: "queue.Queue[np.ndarray]" = queue.Queue()
    _info.update(device=str(device), rate=int(samplerate), ended="release")

    def callback(indata, _frames, _time, _status):
        # indata is float32 [-1,1]; store as int16.
        q.put((indata[:, 0] * 32767).astype(np.int16).copy())

    frames: list[np.ndarray] = []
    last_level = 0.0
    min_dt = 1.0 / _LEVEL_HZ
    # Dead-stream rule (cfg.dead_s): exact zeros after sound mean the device stopped streaming.
    heard = False
    last_sound = time.monotonic()
    silence = _SilenceEnd(cfg)
    try:
        stream = sd.InputStream(samplerate=samplerate, channels=cfg.channels,
                                dtype="float32", device=device, callback=callback)
    except Exception as e:
        raise MicError(f"could not open the microphone: {e}") from e
    with stream:
        while not stop_predicate():
            try:
                chunk = q.get(timeout=0.1)
            except queue.Empty:
                if silence.over(None):
                    _info["ended"] = "silence"
                    break
                continue
            frames.append(chunk)
            if cfg.dead_s > 0:
                if chunk.any():
                    heard = True
                    last_sound = time.monotonic()
                elif heard and time.monotonic() - last_sound >= cfg.dead_s:
                    _info["ended"] = "dead stream"
                    break                      # the microphone went dead: the key was released
            if silence.over(chunk):
                _info["ended"] = "silence"
                break                          # nothing heard for silence_end_s
            if on_level is not None:
                now = time.monotonic()
                if now - last_level >= min_dt:
                    last_level = now
                    f = chunk.astype(np.float32) / 32768.0
                    on_level(float(np.sqrt(np.mean(f * f) + 1e-12)))
    # Drain anything buffered.
    while not q.empty():
        frames.append(q.get())
    _note_take(frames)
    return _save(frames, samplerate)


def _save(frames, samplerate) -> Path:
    fd, name = tempfile.mkstemp(suffix=".wav", prefix="fish_in_")
    os.close(fd)
    out = Path(name)
    _write_wav(out, frames, samplerate)
    return out


def _record_pw(stop_predicate, cfg: PTTConfig, on_level=None) -> Path:
    """The same recording through pw-record (see _PwRecord): the release, the dead-stream and
    silence-end rules, the level meter."""
    _info.update(device=f"pw-record {cfg.source}", rate=int(cfg.samplerate), ended="release")
    src = _PwRecord(cfg)
    frames: list[np.ndarray] = []
    heard, last_sound = False, time.monotonic()
    silence = _SilenceEnd(cfg)
    last_level, min_dt = 0.0, 1.0 / _LEVEL_HZ
    try:
        while not stop_predicate():
            chunk = src.get(0.1)
            if chunk is None:
                if silence.over(None):
                    _info["ended"] = "silence"
                    break
                continue
            frames.append(chunk)
            if cfg.dead_s > 0:
                if chunk.any():
                    heard, last_sound = True, time.monotonic()
                elif heard and time.monotonic() - last_sound >= cfg.dead_s:
                    _info["ended"] = "dead stream"
                    break
            if silence.over(chunk):
                _info["ended"] = "silence"
                break
            if on_level is not None:
                now = time.monotonic()
                if now - last_level >= min_dt:
                    last_level = now
                    f = chunk.astype(np.float32) / 32768.0
                    on_level(float(np.sqrt(np.mean(f * f) + 1e-12)))
    finally:
        src.close()
    _note_take(frames)
    return _save(frames, cfg.samplerate)


def record_for(seconds: float, cfg: PTTConfig,
               on_level: Callable[[float], None] | None = None) -> Path:
    """Record for a fixed time (the debug page's microphone check): no button involved."""
    end = time.monotonic() + max(0.2, float(seconds))
    return _record_until(lambda: time.monotonic() >= end, cfg, on_level)


def record_hold(cfg: PTTConfig,
                on_level: Callable[[float], None] | None = None) -> Path:
    """Record while the configured key is held (pynput), else Enter-to-toggle."""
    try:
        from pynput import keyboard
    except Exception:
        return _record_enter_toggle(cfg, on_level)

    target = getattr(keyboard.Key, cfg.hold_key, None) or keyboard.KeyCode.from_char(
        cfg.hold_key[:1]
    )
    state = {"held": False, "armed": True}

    def on_press(key):
        if key == target:
            state["held"] = True

    def on_release(key):
        if key == target and state["held"]:
            state["armed"] = False
            return False  # stop listener

    print(f"[hold '{cfg.hold_key}' to talk] …", flush=True)
    listener = keyboard.Listener(on_press=on_press, on_release=on_release)
    listener.start()
    # Wait for the key to actually go down before we start recording.
    while not state["held"] and listener.running:
        time.sleep(0.005)
    path = _record_until(lambda: not state["armed"], cfg, on_level)
    listener.stop()
    return path


_cut_last = False   # the previous recording hit max_record_s; wait for a release first
# For the debug page: which source triggered the last recording, why it ended, the device
# and rate it was opened with, and whether one is running now.
_info: dict = {"recording": False}


def last_info() -> dict:
    return dict(_info)



def last_recording_was_cut() -> bool:
    """True when the last recording ended at `max_record_s` with the button still held."""
    return _cut_last


def record_multi(cfg: PTTConfig, sources: list[ButtonSource],
                 on_level: Callable[[float], None] | None = None,
                 inbox: Callable[[], object] | None = None,
                 relay: Callable[[bool], None] | None = None,
                 relay_ready: Callable[[], bool] | None = None) -> Path | object:
    """Record while any of `sources` is held; returns the WAV path.

    Starts only on a fresh press: a source that already reads "held" when we begin waiting
    (a lost release, a tap while the fish was talking) must be released first. A recording
    longer than `cfg.max_record_s` is cut, and every source is then reset so a stuck button
    cannot start one recording after another. A recording ended by the silence end
    (`cfg.silence_end_s`) resets the sources the same way but is not a cut.

    `inbox()` is polled while waiting; the first item it returns (anything but None) is
    returned as the turn's input instead of a recording. With no sources, the inbox is the
    only trigger.

    With `relay` given, the sources whose `.relay` is True never start a recording here:
    they are polled while waiting and each edge is handed to `relay(held)` (the page records
    with the phone's microphone and its upload arrives through the inbox). A relayed hold
    that reaches `cfg.max_record_s` is ended with `relay(False)` and the source reset; one
    still held when this returns is ended the same way, so the page never records forever.
    A relayed source held when the wait begins is ignored until it is released.
    `relay_ready()`, when given, is asked at every press edge whether the page is still
    there: if not, that source records here for the rest of this wait (the phone went away
    mid-wait and the remote must not go dead).
    """
    global _cut_last
    if not sources and inbox is None:
        raise PTTUnavailable("no push-to-talk source configured")

    def from_inbox():
        return inbox() if inbox is not None else None

    relayed = [s for s in sources if relay is not None and s.relay]
    local = [s for s in sources if s not in relayed]
    rstate = {"held": False, "since": 0.0,
              "need_release": any(s.is_held() for s in relayed)}

    def poll_relay() -> None:
        """One look at the relayed sources (every 20 ms): edges go to `relay`."""
        if not relayed:
            return
        now_held = any(s.is_held() for s in relayed)
        if rstate["need_release"]:
            if not now_held:
                rstate["need_release"] = False
            return
        if now_held and not rstate["held"] and relay_ready is not None and not relay_ready():
            # The page left since this wait began: this press records on the board.
            print("[ptt] no page with a microphone: the remote records here", flush=True)
            local.extend(relayed)
            relayed.clear()
            return
        if now_held != rstate["held"]:
            rstate["held"] = now_held
            rstate["since"] = time.monotonic()
            relay(now_held)
        elif now_held and time.monotonic() - rstate["since"] >= cfg.max_record_s:
            rstate["held"] = False
            rstate["need_release"] = True
            print(f"[ptt] {cfg.max_record_s:.0f} s limit reached on the relayed press; "
                  "release and press again", flush=True)
            relay(False)
            for s in relayed:
                s.reset()

    def wait_step():
        """One wait iteration: the inbox, the relayed sources, a short sleep."""
        item = from_inbox()
        if item is not None:
            return item
        poll_relay()
        time.sleep(0.02)
        return None

    for s in sources:
        s.arm(True)
    try:
        def any_held() -> bool:            # `local` may grow: a relayed source whose page left
            return any(s.is_held() for s in local)

        # Whatever is held right now is stale: clear it, then wait for idle.
        if _cut_last or any_held():
            for s in local:
                s.reset()
            while any_held():
                item = wait_step()
                if item is not None:
                    return item
        _cut_last = False
        while not any_held():
            item = wait_step()
            if item is not None:
                return item
        t0 = time.monotonic()
        _info["trigger"] = next((s.name for s in local if s.is_held()), "button")

        def stop() -> bool:
            return not any_held() or time.monotonic() - t0 >= cfg.max_record_s

        _info["recording"] = True
        _info["ended"] = "release"
        try:
            path = _record_until(stop, cfg, on_level)
        finally:
            _info["recording"] = False
        if _info.get("ended") == "silence":
            # Not a cut: the clip is answered as it is and the LLM is not told the visitor was
            # still talking. The button may still be held: clear it at once so the next wait
            # starts on a fresh press.
            print(f"[ptt] silence end: nothing heard for {cfg.silence_end_s:g} s; the clip is "
                  "answered, release and press again", flush=True)
            for s in local:
                s.reset()
        elif time.monotonic() - t0 >= cfg.max_record_s:
            _cut_last = True
            _info["ended"] = "limit"
            print(f"[ptt] {cfg.max_record_s:.0f} s limit reached; release and press again",
                  flush=True)
            for s in local:
                s.reset()
        return path
    finally:
        if rstate["held"]:
            rstate["held"] = False
            relay(False)               # the page must not keep recording after we stop waiting
        for s in sources:
            s.arm(False)


def _record_enter_toggle(cfg: PTTConfig,
                         on_level: Callable[[float], None] | None = None) -> Path:
    import threading

    if not sys.stdin.isatty():
        # A service has no keyboard: input() would fail forever. Say what to configure.
        raise PTTUnavailable("no terminal for Enter-to-talk: set FISH_PTT_DEVICE or use --viz")
    input("[press Enter to START recording] ")
    done = threading.Event()

    def waiter():
        input("[press Enter to STOP] ")
        done.set()

    threading.Thread(target=waiter, daemon=True).start()
    return _record_until(done.is_set, cfg, on_level)
