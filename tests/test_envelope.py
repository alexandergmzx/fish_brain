"""The mouth pulse models: position (Billy Bass) and gate (the Sorting Hat's cam)."""
import pytest

from fish_brain.config import MouthConfig
from fish_brain.envelope import gate_pulses, mouth_pulses


def test_position_mode_is_the_default_and_unchanged():
    cfg = MouthConfig()
    assert cfg.mode == "position"
    # A rise from closed to fully open costs the whole open curve, a fall the close curve.
    track = [(0, 0.0), (30, 1.0), (500, 0.0)]
    assert mouth_pulses(track, cfg) == [(30, cfg.open_pwm, 104), (500, cfg.close_pwm, 74)]


def test_gate_runs_while_loud_and_stops_at_the_fall():
    cfg = MouthConfig(mode="gate", open_pwm=200, gate_pulse_ms=150, gate_refresh_ms=100)
    track = [(0, 0.5), (400, 0.0)]
    pulses = gate_pulses(track, cfg)
    # Refreshed every 100 ms while the level holds, each pulse 150 ms, then a 1 ms zero pulse.
    assert pulses == [(0, 200, 150), (100, 200, 150), (200, 200, 150), (300, 200, 150),
                      (400, 0, 1)]
    # The motor never runs past the last line by more than one pulse.
    assert all(ms <= 150 for _, _, ms in pulses)


def test_gate_skips_quiet_stretches_and_sends_no_stop_when_already_stopped():
    cfg = MouthConfig(mode="gate", gate_level=0.08)
    track = [(0, 0.0), (30, 0.05), (60, 0.0)]
    assert gate_pulses(track, cfg) == []
    track = [(0, 0.3), (120, 0.0), (300, 0.0), (330, 0.4), (360, 0.0)]
    pulses = gate_pulses(track, cfg)
    assert pulses == [(0, cfg.open_pwm, 150), (100, cfg.open_pwm, 150), (120, 0, 1),
                      (330, cfg.open_pwm, 150), (360, 0, 1)]


def test_gate_does_not_resend_while_the_running_pulse_covers_the_next_refresh():
    cfg = MouthConfig(mode="gate", gate_pulse_ms=150, gate_refresh_ms=100)
    # Events every 30 ms, all loud: a new pulse only when the running one is about to end.
    track = [(t, 0.6) for t in range(0, 300, 30)] + [(300, 0.0)]
    pulses = gate_pulses(track, cfg)
    times = [t for t, pwm, _ in pulses if pwm]
    assert times == [0, 60, 120, 180, 240]
    assert pulses[-1] == (300, 0, 1)


def test_mouth_pulses_dispatches_on_mode_and_rejects_unknown():
    cfg = MouthConfig(mode="gate")
    assert mouth_pulses([(0, 0.5), (100, 0.0)], cfg) == gate_pulses([(0, 0.5), (100, 0.0)], cfg)
    with pytest.raises(ValueError):
        mouth_pulses([(0, 0.5)], MouthConfig(mode="held"))
