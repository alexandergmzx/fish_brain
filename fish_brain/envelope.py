"""Turn a speech WAV into a mouth-motion track.

Output: a list of (t_ms, pwm) events — the signed PWM to send to `MOUTH <n>` at time
t_ms relative to playback start. Loudness maps proportionally to how far the mouth opens
(per the user's "proportional loudness" choice). Silence -> rest_pwm (closed).

Pipeline: mono float samples -> per-frame RMS -> per-clip normalize -> noise floor ->
attack/release smoothing -> map to PWM -> decimate to the serial command-rate cap ->
dedup consecutive identical values.
"""
from __future__ import annotations

import wave
from pathlib import Path

import numpy as np

from .config import MouthConfig


def load_wav_mono(path: str | Path) -> tuple[np.ndarray, int]:
    """Load a WAV as float32 mono in [-1, 1] with its sample rate."""
    with wave.open(str(path), "rb") as w:
        sr = w.getframerate()
        n = w.getnframes()
        ch = w.getnchannels()
        sampwidth = w.getsampwidth()
        raw = w.readframes(n)
    if sampwidth == 2:
        data = np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768.0
    elif sampwidth == 1:
        data = (np.frombuffer(raw, dtype=np.uint8).astype(np.float32) - 128.0) / 128.0
    elif sampwidth == 4:
        data = np.frombuffer(raw, dtype="<i4").astype(np.float32) / 2147483648.0
    else:
        raise ValueError(f"unsupported WAV sample width: {sampwidth} bytes")
    if ch > 1:
        data = data.reshape(-1, ch).mean(axis=1)
    return data, sr


def _frame_rms(data: np.ndarray, sr: int, frame_ms: float) -> tuple[np.ndarray, float]:
    """Non-overlapping RMS per frame. Returns (rms[], frame_dt_seconds)."""
    hop = max(1, int(sr * frame_ms / 1000.0))
    n_frames = max(1, len(data) // hop)
    trimmed = data[: n_frames * hop].reshape(n_frames, hop)
    rms = np.sqrt(np.mean(trimmed * trimmed, axis=1) + 1e-12)
    return rms, hop / sr


def mouth_track(path: str | Path, cfg: MouthConfig, max_cmd_hz: float) -> list[tuple[int, int]]:
    """Compute the (t_ms, pwm) mouth track for a WAV."""
    data, sr = load_wav_mono(path)
    if len(data) == 0:
        return [(0, cfg.rest_pwm)]

    rms, frame_dt = _frame_rms(data, sr, cfg.frame_ms)

    peak = float(rms.max())
    norm = rms / peak if peak > 1e-6 else np.zeros_like(rms)

    # Noise floor -> rescale so [floor..1] maps to [0..1]; below floor is silence.
    floor = cfg.noise_floor
    level = np.clip((norm - floor) / max(1e-6, 1.0 - floor), 0.0, 1.0)

    # Attack/release smoothing (asymmetric one-pole).
    smoothed = np.zeros_like(level)
    prev = 0.0
    for i, x in enumerate(level):
        a = cfg.attack if x > prev else cfg.release
        prev = prev + a * (x - prev)
        smoothed[i] = prev

    # Map level -> PWM. Silence -> rest; else min_open..open scaled by level.
    span = cfg.open_pwm - cfg.min_open_pwm
    pwm = np.where(
        smoothed <= 1e-3,
        float(cfg.rest_pwm),
        cfg.min_open_pwm + smoothed * span,
    ).round().astype(int)

    # Decimate to the command-rate cap: sample the fine track onto a coarse grid.
    grid_dt = 1.0 / max_cmd_hz if max_cmd_hz > 0 else frame_dt
    total_s = len(pwm) * frame_dt
    track: list[tuple[int, int]] = []
    last_val = None
    t = 0.0
    while t < total_s:
        idx = min(len(pwm) - 1, int(t / frame_dt))
        val = int(pwm[idx])
        if val != last_val:
            track.append((int(t * 1000), val))
            last_val = val
        t += grid_dt

    # Always end closed, just after the audio ends.
    if not track or track[-1][1] != cfg.rest_pwm:
        track.append((int(total_s * 1000), cfg.rest_pwm))
    return track
