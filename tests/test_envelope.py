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
    cfg = MouthConfig(mode="gate", open_pwm=200, gate_pulse_ms=150, gate_refresh_ms=100,
                      gate_gap_ms=0, gate_min_run_ms=0)
    track = [(0, 0.5), (400, 0.0)]
    pulses = gate_pulses(track, cfg)
    # Refreshed every 100 ms while the level holds, each pulse 150 ms, then a 1 ms zero pulse.
    assert pulses == [(0, 200, 150), (100, 200, 150), (200, 200, 150), (300, 200, 150),
                      (400, 0, 1)]
    # The motor never runs past the last line by more than one pulse.
    assert all(ms <= 150 for _, _, ms in pulses)


def test_gate_skips_quiet_stretches_and_sends_no_stop_when_already_stopped():
    cfg = MouthConfig(mode="gate", gate_level=0.08, gate_gap_ms=0, gate_min_run_ms=0)
    track = [(0, 0.0), (30, 0.05), (60, 0.0)]
    assert gate_pulses(track, cfg) == []
    track = [(0, 0.3), (120, 0.0), (300, 0.0), (330, 0.4), (360, 0.0)]
    pulses = gate_pulses(track, cfg)
    assert pulses == [(0, cfg.open_pwm, 150), (100, cfg.open_pwm, 150), (120, 0, 1),
                      (330, cfg.open_pwm, 150), (360, 0, 1)]


def test_gate_does_not_resend_while_the_running_pulse_covers_the_next_refresh():
    cfg = MouthConfig(mode="gate", gate_pulse_ms=150, gate_refresh_ms=100, gate_gap_ms=0,
                      gate_min_run_ms=0)
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


def _hat(**kw):
    base = dict(mode="gate", open_pwm=200, gate_gap_ms=300, gate_min_run_ms=250,
                gate_lead_start_ms=0, gate_lead_stop_ms=0, gate_calm_pwm=0, gate_stop="0 1")
    base.update(kw)
    return MouthConfig(**base)


def _loud(spans, end):
    """A 30 ms track, loud (0.5) inside each (start, end) span, silent elsewhere."""
    return [(t, 0.5 if any(s <= t < e for s, e in spans) else 0.0) for t in range(0, end, 30)] \
        + [(end, 0.0)]


def test_gate_keeps_moving_across_a_short_dip_and_stops_at_a_pause():
    cfg = _hat()
    # 600 ms of voice, a 180 ms dip, 600 ms more, a 420 ms pause, 600 ms more.
    pulses = gate_pulses(_loud([(0, 600), (780, 1380), (1800, 2400)], 2700), cfg)
    stops = [t for t, pwm, ms in pulses if pwm == 0]
    assert stops == [1380, 2400]                            # not at the dip, at the pause
    # No line inside the pause, and the motor is fed without a gap through each phrase.
    assert not [t for t, pwm, _ in pulses if 1380 < t < 1800]
    for a, b in ((0, 1380), (1800, 2400)):
        run = [(t, ms) for t, pwm, ms in pulses if pwm and a <= t < b]
        ends = [t + ms for t, ms in run]
        assert all(nxt <= end for (nxt, _), end in zip(run[1:], ends))
        assert ends[-1] >= b
    assert all(1 <= ms <= 150 for _, pwm, ms in pulses if pwm)


def test_gate_runs_a_short_word_for_the_minimum_and_ends_with_the_stop_line():
    pulses = gate_pulses(_loud([(300, 360)], 1200), _hat(gate_stop="1 150"))
    assert pulses[0] == (300, 200, 150)
    assert pulses[-1] == (550, 1, 150)                      # 250 ms run, then the brake line


def test_gate_leads_move_the_phrase_early_and_clamp_at_zero():
    cfg = _hat(gate_lead_start_ms=100, gate_lead_stop_ms=80)
    pulses = gate_pulses(_loud([(60, 900), (1500, 2100)], 2400), cfg)
    assert pulses[0][0] == 0                                # 60 - 100 clamps at 0
    assert [t for t, pwm, _ in pulses if pwm == 0] == [820, 2020]
    assert (1400, 200, 150) in pulses


def test_gate_calm_speed_is_per_phrase():
    cfg = _hat(gate_calm_pwm=140)
    track = [(t, 0.2 if t < 600 else 0.0 if t < 1200 else 0.8 if t < 1800 else 0.0)
             for t in range(0, 2100, 30)] + [(2100, 0.0)]
    pulses = gate_pulses(track, cfg)
    assert {pwm for t, pwm, _ in pulses if pwm and t < 600} == {140}
    assert {pwm for t, pwm, _ in pulses if pwm and t >= 1200} == {200}


def test_end_pulse_per_mode_and_bad_stop_lines():
    from fish_brain.envelope import end_pulse
    assert end_pulse(MouthConfig()) == (-200, 74)           # Billy Bass: the close stroke
    assert end_pulse(_hat()) == (0, 1)
    assert end_pulse(_hat(gate_stop="-200 74")) == (-200, 74)
    for bad in ("", "0", "300 10", "0 0", "a b"):
        assert _hat(gate_stop=bad).problems()
    assert MouthConfig(mode="phrase").problems()
    assert not _hat().problems() and not MouthConfig().problems()
