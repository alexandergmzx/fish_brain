"""Turn a speech WAV into a mouth-motion track.

Two stages:
- `mouth_track` -> a list of (t_ms, level) events: the openness fraction (0..1) the mouth
  should have at time t_ms relative to playback start. Loudness maps proportionally to how
  far the mouth opens. This is the shared "intent" — the on-screen fish renders it directly.
- `mouth_pulses` -> a list of (t_ms, pwm, ms) timed motor pulses realizing that intent on
  hardware: the mouth is driven by *time* (attack-time calibration), not held PWM magnitude.

Level pipeline: mono float samples -> per-frame RMS -> per-clip normalize -> noise floor ->
attack/release smoothing -> decimate to the serial command-rate cap -> dedup consecutive
identical values.
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


def mouth_track(path: str | Path, cfg: MouthConfig, max_cmd_hz: float) -> list[tuple[int, float]]:
    """Compute the (t_ms, level) openness track for a WAV (level in 0..1)."""
    data, sr = load_wav_mono(path)
    if len(data) == 0:
        return [(0, 0.0)]

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

    # Decimate to the command-rate cap: sample the fine track onto a coarse grid.
    grid_dt = 1.0 / max_cmd_hz if max_cmd_hz > 0 else frame_dt
    total_s = len(smoothed) * frame_dt
    track: list[tuple[int, float]] = []
    last_val = None
    t = 0.0
    while t < total_s:
        idx = min(len(smoothed) - 1, int(t / frame_dt))
        val = round(float(smoothed[idx]), 3)
        if val != last_val:
            track.append((int(t * 1000), val))
            last_val = val
        t += grid_dt

    # Always end closed, just after the audio ends.
    if not track or track[-1][1] != 0.0:
        track.append((int(total_s * 1000), 0.0))
    return track


def _interp_ms(curve: tuple[tuple[float, int], ...], openness: float) -> float:
    """Linear-interpolate drive-ms for an openness fraction over the calibration anchors."""
    o = min(1.0, max(0.0, openness))
    prev_x, prev_y = curve[0]
    if o <= prev_x:
        return float(prev_y)
    for x, y in curve[1:]:
        if o <= x:
            span = x - prev_x
            frac = (o - prev_x) / span if span > 1e-9 else 0.0
            return prev_y + frac * (y - prev_y)
        prev_x, prev_y = x, y
    return float(curve[-1][1])


def end_pulse(cfg: MouthConfig) -> tuple[int, int]:
    """The pulse that ends every utterance: a full close stroke for a jaw (position), the
    gate_stop line for a cam (gate)."""
    if cfg.mode == "gate":
        return cfg.stop_pulse()
    return cfg.close_pwm, int(cfg.close_curve[-1][1])


def mouth_pulses(level_track: list[tuple[int, float]],
                 cfg: MouthConfig) -> list[tuple[int, int, int]]:
    """Convert an openness `level_track` into (t_ms, pwm, ms) timed motor pulses.

    `cfg.mode == "gate"` hands over to `gate_pulses` (a one-way mechanism). Otherwise the
    position model: treats the open attack-time curve as a position-in-time axis: moving the
    jaw between two openness levels costs the difference of their drive-ms. Opens at
    +open_pwm, closes at close_pwm (its own faster curve). Pulses rounding to <1 ms are
    skipped, and the skipped delta accumulates (o_cur only advances when a pulse is actually
    emitted).
    """
    if cfg.mode == "gate":
        return gate_pulses(level_track, cfg)
    if cfg.mode != "position":
        raise ValueError(f"FISH_MOUTH_MODE={cfg.mode!r}; choose position or gate")
    pulses: list[tuple[int, int, int]] = []
    o_cur = 0.0
    for t_ms, level in level_track:
        if level > o_cur:
            ms = round(_interp_ms(cfg.open_curve, level) - _interp_ms(cfg.open_curve, o_cur))
            pwm = cfg.open_pwm
        elif level < o_cur:
            ms = round(_interp_ms(cfg.close_curve, o_cur) - _interp_ms(cfg.close_curve, level))
            pwm = cfg.close_pwm
        else:
            continue
        if ms >= 1:
            pulses.append((t_ms, pwm, int(ms)))
            o_cur = level
    return pulses


def _gate_phrases(level_track: list[tuple[int, float]],
                  cfg: MouthConfig) -> list[tuple[int, int, int]]:
    """The phrases of a level track as (start_ms, end_ms, pwm): the runs above gate_level,
    joined across quiet stretches shorter than gate_gap_ms, each at least gate_min_run_ms
    long. With gate_calm_pwm set, a phrase quieter than the median phrase runs at it."""
    spans: list[list[float]] = []         # [start, end, level sum, points]
    for t, level in level_track:
        if level > cfg.gate_level:
            if spans and spans[-1][1] < 0:
                spans[-1][2] += level
                spans[-1][3] += 1
            else:
                spans.append([t, -1, level, 1])
        elif spans and spans[-1][1] < 0:
            spans[-1][1] = t
    if spans and spans[-1][1] < 0:
        spans[-1][1] = level_track[-1][0]
    merged: list[list[float]] = []
    for s in spans:
        s[1] = max(s[1], s[0] + max(0, cfg.gate_min_run_ms))
        if merged and s[0] - merged[-1][1] < max(0, cfg.gate_gap_ms):
            m = merged[-1]
            m[1] = max(m[1], s[1])
            m[2] += s[2]
            m[3] += s[3]
        else:
            merged.append(s)
    means = sorted(m[2] / m[3] for m in merged)
    median = means[len(means) // 2] if means else 0.0
    out = []
    for s, e, total, n in merged:
        calm = cfg.gate_calm_pwm and len(merged) > 1 and total / n < median
        out.append((int(s), int(e), cfg.gate_calm_pwm if calm else cfg.open_pwm))
    return out


def gate_pulses(level_track: list[tuple[int, float]],
                cfg: MouthConfig) -> list[tuple[int, int, int]]:
    """Keep the motor running through each phrase and stop it at the pauses.

    For a mechanism with no position (the Sorting Hat: one motor turns a cam that moves the
    mouth, the brow and the tip), where a pulse is motion rather than a place. Through a
    phrase (see `_gate_phrases`) a pulse of gate_pulse_ms is sent, and sent again before
    the running one ends (the MCU replaces a running pulse with the next line), so the motor
    runs without a gap and never more than gate_pulse_ms past the last line the host managed
    to send. Each phrase is moved gate_lead_start_ms / gate_lead_stop_ms early and ends with
    the gate_stop line ("0 1" lets it coast). Every line is a timed pulse: the firmware's
    limit still applies and nothing is ever held.
    """
    pulses: list[tuple[int, int, int]] = []
    refresh = max(10, int(cfg.gate_refresh_ms))
    pulse_ms = max(refresh + 1, int(cfg.gate_pulse_ms))
    stop = cfg.stop_pulse()
    windows: list[list[int]] = []
    for s, e, pwm in _gate_phrases(level_track, cfg):
        a = max(0, s - max(0, cfg.gate_lead_start_ms))
        b = max(a + max(1, cfg.gate_min_run_ms), e - max(0, cfg.gate_lead_stop_ms))
        if windows and a <= windows[-1][1] + 30:       # no room for a stop: one phrase
            windows[-1][1] = max(windows[-1][1], b)
        else:
            windows.append([a, b, pwm])
    times = [t for t, _ in level_track]
    for a, b, pwm in windows:
        # Checks at the track's own points inside the window, and every refresh between them.
        marks = [a] + [t for t in times if a < t < b] + [b]
        until = -1
        for t, t_next in zip(marks, marks[1:]):
            tt = t
            while tt < t_next:
                if until - tt < refresh:
                    pulses.append((tt, pwm, pulse_ms))
                    until = tt + pulse_ms
                tt += refresh
        pulses.append((b, stop[0], stop[1]))
    return pulses
