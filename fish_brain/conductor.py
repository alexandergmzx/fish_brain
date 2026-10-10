"""The conductor: play the audio and stream motor commands on one monotonic clock.

Given a pre-computed mouth track and gesture events, it starts audio playback and then
dispatches each command at its scheduled time relative to playback start (`t0`), shifted
by `sync_offset_ms` to cover audio-output latency + motor mechanical lag.

Audio playback is pluggable so the rest of the system works with or without an audio
device: sounddevice (tight clock) -> paplay/aplay subprocess -> silent (sleep only).
"""
from __future__ import annotations

import shutil
import subprocess
import time
import wave
from pathlib import Path

from .config import Config
from .serial_link import BaseLink


def _wav_duration_s(path: str | Path) -> float:
    with wave.open(str(path), "rb") as w:
        return w.getnframes() / float(w.getframerate())


class Player:
    """Non-blocking audio playback handle."""

    def play(self, wav_path: str | Path) -> None: ...
    def wait(self) -> None: ...
    def stop(self) -> None: ...


class SilentPlayer(Player):
    """No sound; just tracks the clip duration so the conductor can wait it out."""

    def __init__(self):
        self._end = 0.0

    def play(self, wav_path):
        self._end = time.monotonic() + _wav_duration_s(wav_path)

    def wait(self):
        remaining = self._end - time.monotonic()
        if remaining > 0:
            time.sleep(remaining)

    def stop(self):
        self._end = 0.0


class SubprocessPlayer(Player):
    """Play via paplay/aplay as a background process."""

    def __init__(self, exe: str):
        self._exe = exe
        self._proc: subprocess.Popen | None = None

    def play(self, wav_path):
        self._proc = subprocess.Popen(
            [self._exe, str(wav_path)],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )

    def wait(self):
        if self._proc:
            self._proc.wait()

    def stop(self):
        if self._proc and self._proc.poll() is None:
            self._proc.terminate()


class SounddevicePlayer(Player):
    """Play via sounddevice (tightest clock; needs libportaudio2)."""

    def __init__(self, device: int | str | None = None):
        import sounddevice as sd  # noqa: F401  (validate availability early)
        self._sd = sd
        self._dur = 0.0
        self._device = device       # index or name substring; None = system default

    def play(self, wav_path):
        import numpy as np
        from .envelope import load_wav_mono
        data, sr = load_wav_mono(wav_path)
        self._dur = len(data) / float(sr)
        self._sd.play(data, sr, device=self._device)

    def wait(self):
        self._sd.wait()

    def stop(self):
        self._sd.stop()


def make_player(play_audio: bool = True, device: int | str | None = None) -> Player:
    """Pick the best available player. `play_audio=False` -> silent.

    `device` (a sounddevice index or name substring) picks the speaker; None = default.
    """
    if not play_audio:
        return SilentPlayer()
    if isinstance(device, str) and device.strip().isdigit():
        device = int(device)
    try:
        return SounddevicePlayer(device)
    except Exception:
        pass
    for exe in ("paplay", "pw-play", "aplay"):
        if shutil.which(exe):
            return SubprocessPlayer(exe)
    return SilentPlayer()


def perform(
    wav_path: str | Path,
    mouth_pulses: list[tuple[int, int, int]],
    gesture_events: list[tuple[int, str, str]],
    link: BaseLink,
    cfg: Config,
    player: Player | None = None,
) -> float:
    """Play `wav_path` while streaming mouth + gesture commands in sync.

    Returns the monotonic time at which playback started (for per-turn timing).

    mouth_pulses: list of (t_ms, pwm, ms) timed motor pulses (see envelope.mouth_pulses).
    gesture_events: list of (t_ms, channel, chain_body).
    """
    if player is None:
        player = make_player()

    # Merge into one time-sorted event stream. kind: 0=mouth, 1=gesture.
    events: list[tuple[int, int, object]] = []
    for t_ms, pwm, ms in mouth_pulses:
        events.append((t_ms, 0, (pwm, ms)))
    for t_ms, channel, body in gesture_events:
        events.append((t_ms, 1, (channel, body)))
    events.sort(key=lambda e: e[0])

    offset = cfg.conductor.sync_offset_ms / 1000.0

    player.play(wav_path)
    t0 = time.monotonic()
    try:
        for t_ms, kind, payload in events:
            target = t0 + t_ms / 1000.0 - offset
            dt = target - time.monotonic()
            if dt > 0:
                time.sleep(dt)
            if kind == 0:
                pwm, ms = payload                   # type: ignore[misc]
                link.mouth_pulse(int(pwm), int(ms))
            else:
                channel, body = payload              # type: ignore[misc]
                link.gesture(channel, body)
        player.wait()
    finally:
        # Always close the mouth when the utterance ends or is interrupted: a full close
        # pulse (the jaw may hold open between pulses, so coasting to 0 isn't enough).
        link.mouth_pulse(cfg.mouth.close_pwm, cfg.mouth.close_curve[-1][1])
    return t0
