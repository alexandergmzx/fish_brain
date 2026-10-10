"""Push-to-talk microphone capture.

Hold a key to record from the mic; release to stop. Writes a mono WAV and returns its path.
We prefer 16 kHz (what faster-whisper uses), but fall back to the device's native rate if it
rejects 16 kHz — faster-whisper resamples to 16 kHz internally, so any WAV rate works.

Three ways to say "talk now":
- `record_hold`: a keyboard key via `pynput` (needs a display), else Enter-to-toggle in a
  terminal (never without a TTY: a service has no stdin to read).
- `record_multi`: any number of button-like sources (the browser's hold-to-talk button, a
  remote's button via evdev). Recording starts on a fresh press of any of them.
"""
from __future__ import annotations

import os
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
                 arm: Callable[[bool], None] | None = None, name: str = "button"):
        self.is_held = is_held
        self._reset = reset
        self._arm = arm
        self.name = name

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


def _record_until(stop_predicate, cfg: PTTConfig,
                  on_level: Callable[[float], None] | None = None) -> Path:
    """Record from the mic until `stop_predicate()` returns True.

    If `on_level` is given, it's called with the per-chunk RMS (0..1) at ~`_LEVEL_HZ`
    so the web GUI can draw a live level meter while recording.
    """
    try:
        import sounddevice as sd
        device, samplerate = _resolve_input(sd, cfg)
    except MicError:
        raise
    except Exception as e:      # PortAudio missing, no input device, bad index...
        raise MicError(f"microphone unavailable: {e}") from e
    q: "queue.Queue[np.ndarray]" = queue.Queue()

    def callback(indata, _frames, _time, _status):
        # indata is float32 [-1,1]; store as int16.
        q.put((indata[:, 0] * 32767).astype(np.int16).copy())

    frames: list[np.ndarray] = []
    last_level = 0.0
    min_dt = 1.0 / _LEVEL_HZ
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
                continue
            frames.append(chunk)
            if on_level is not None:
                now = time.monotonic()
                if now - last_level >= min_dt:
                    last_level = now
                    f = chunk.astype(np.float32) / 32768.0
                    on_level(float(np.sqrt(np.mean(f * f) + 1e-12)))
    # Drain anything buffered.
    while not q.empty():
        frames.append(q.get())

    fd, name = tempfile.mkstemp(suffix=".wav", prefix="fish_in_")
    os.close(fd)
    out = Path(name)
    _write_wav(out, frames, samplerate)
    return out


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


def record_multi(cfg: PTTConfig, sources: list[ButtonSource],
                 on_level: Callable[[float], None] | None = None) -> Path:
    """Record while any of `sources` is held; returns the WAV path.

    Starts only on a fresh press: a source that already reads "held" when we begin waiting
    (a lost release, a tap while the fish was talking) must be released first. A recording
    longer than `cfg.max_record_s` is cut, and every source is then reset so a stuck button
    cannot start one recording after another.
    """
    global _cut_last
    if not sources:
        raise PTTUnavailable("no push-to-talk source configured")

    def any_held() -> bool:
        return any(s.is_held() for s in sources)

    for s in sources:
        s.arm(True)
    try:
        # Whatever is held right now is stale: clear it, then wait for idle.
        if _cut_last or any_held():
            for s in sources:
                s.reset()
            while any_held():
                time.sleep(0.02)
        _cut_last = False
        while not any_held():
            time.sleep(0.02)
        t0 = time.monotonic()

        def stop() -> bool:
            return not any_held() or time.monotonic() - t0 >= cfg.max_record_s

        path = _record_until(stop, cfg, on_level)
        if time.monotonic() - t0 >= cfg.max_record_s:
            _cut_last = True
            print(f"[ptt] {cfg.max_record_s:.0f} s limit reached; release and press again",
                  flush=True)
            for s in sources:
                s.reset()
        return path
    finally:
        for s in sources:
            s.arm(False)


def record_web(cfg: PTTConfig, is_held: Callable[[], bool],
               on_level: Callable[[float], None] | None = None) -> Path:
    """Record while one button-like predicate is true (kept for callers with a bare predicate)."""
    return record_multi(cfg, [ButtonSource(is_held, name="web")], on_level)


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
