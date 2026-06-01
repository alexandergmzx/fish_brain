"""Push-to-talk microphone capture.

Hold a key to record from the mic; release to stop. Writes a mono 16 kHz WAV (what
faster-whisper wants) and returns its path.

Key handling uses `pynput` (no root on X11). If pynput isn't available or no display is
present, falls back to Enter-to-toggle: press Enter to start recording, Enter to stop.
"""
from __future__ import annotations

import queue
import tempfile
import wave
from pathlib import Path

import numpy as np

from .config import PTTConfig


def _write_wav(path: Path, frames: list[np.ndarray], samplerate: int) -> None:
    data = np.concatenate(frames) if frames else np.zeros(0, dtype=np.int16)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)  # int16
        w.setframerate(samplerate)
        w.writeframes(data.astype("<i2").tobytes())


def _record_until(stop_predicate, cfg: PTTConfig) -> Path:
    """Record from the mic until `stop_predicate()` returns True."""
    import sounddevice as sd

    q: "queue.Queue[np.ndarray]" = queue.Queue()

    def callback(indata, _frames, _time, _status):
        # indata is float32 [-1,1]; store as int16.
        q.put((indata[:, 0] * 32767).astype(np.int16).copy())

    frames: list[np.ndarray] = []
    with sd.InputStream(samplerate=cfg.samplerate, channels=cfg.channels,
                        dtype="float32", callback=callback):
        while not stop_predicate():
            try:
                frames.append(q.get(timeout=0.1))
            except queue.Empty:
                pass
    # Drain anything buffered.
    while not q.empty():
        frames.append(q.get())

    fd, name = tempfile.mkstemp(suffix=".wav", prefix="fish_in_")
    import os
    os.close(fd)
    out = Path(name)
    _write_wav(out, frames, cfg.samplerate)
    return out


def record_hold(cfg: PTTConfig) -> Path:
    """Record while the configured key is held (pynput), else Enter-to-toggle."""
    try:
        from pynput import keyboard
    except Exception:
        return _record_enter_toggle(cfg)

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
        pass
    path = _record_until(lambda: not state["armed"], cfg)
    listener.stop()
    return path


def _record_enter_toggle(cfg: PTTConfig) -> Path:
    import threading

    input("[press Enter to START recording] ")
    done = threading.Event()

    def waiter():
        input("[press Enter to STOP] ")
        done.set()

    threading.Thread(target=waiter, daemon=True).start()
    return _record_until(done.is_set, cfg)
