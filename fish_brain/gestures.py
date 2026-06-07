"""Neck/tail gestures to play while the fish talks.

Produces a list of (t_ms, channel, chain_body) events. Each chain_body is a firmware
timed-chain (e.g. "230 650" or "210 230 -210 210"); the firmware sequences and auto-stops
it, so these fire-and-forget alongside the mouth stream.

Two modes:
  - text-driven (when the spoken text is known): the head swings OUT near the start of each
    clause and HOLDS (no return pair) — sometimes across a sentence boundary — then RETURNS
    home on sentence-ending punctuation and always at the phrase end; the tail flaps on word
    boundaries. Character index is mapped linearly onto the audio duration (no word timing
    from the TTS), which is a good-enough approximation for expressive motion.
  - random fallback (no text): roughly-Poisson self-contained chains on each channel.
"""
from __future__ import annotations

import random

from .config import GestureConfig


def _channel_events(
    duration_ms: int, mean_gap_s: float, min_gap_s: float,
    chains: tuple[str, ...], channel: str, rng: random.Random,
) -> list[tuple[int, str, str]]:
    if duration_ms <= 0 or not chains:
        return []
    events: list[tuple[int, str, str]] = []
    # Start somewhere in the first gap, then step by random gaps to the end.
    t = rng.expovariate(1.0 / mean_gap_s) * 1000.0
    while t < duration_ms:
        events.append((int(t), channel, rng.choice(chains)))
        gap = max(min_gap_s, rng.expovariate(1.0 / mean_gap_s))
        t += gap * 1000.0
    return events


def _random_track(
    duration_ms: int, cfg: GestureConfig, rng: random.Random,
) -> list[tuple[int, str, str]]:
    events = _channel_events(
        duration_ms, cfg.neck_mean_gap_s, cfg.min_gap_s, cfg.neck_chains, "NECK", rng
    )
    events += _channel_events(
        duration_ms, cfg.tail_mean_gap_s, cfg.min_gap_s, cfg.tail_chains, "TAIL", rng
    )
    events.sort(key=lambda e: e[0])
    return events


def _text_track(
    duration_ms: int, cfg: GestureConfig, text: str, rng: random.Random,
) -> list[tuple[int, str, str]]:
    """Drive the head/tail from the text: out on word boundaries, home on sentence ends."""
    n = len(text)
    if n <= 0:
        return []

    def t_at(i: int) -> int:
        return max(0, min(duration_ms, int(i / n * duration_ms)))

    enders = set(cfg.sentence_end)
    min_gap_ms = cfg.text_min_gap_s * 1000.0
    events: list[tuple[int, str, str]] = []
    neck_open = False
    opened_this_sentence = False
    last_neck_t = -1e9
    last_tail_t = -1e9

    for i, ch in enumerate(text):
        t = t_at(i)
        if ch.isspace():
            # Word boundary: open the head for this clause (and hold), else maybe nudge it;
            # flap the tail for liveliness.
            if not neck_open and not opened_this_sentence:
                events.append((t, "NECK", cfg.neck_out))
                neck_open = True
                opened_this_sentence = True
                last_neck_t = t
            elif (neck_open and t - last_neck_t >= min_gap_ms
                  and rng.random() < cfg.neck_nudge_prob):
                events.append((t, "NECK", cfg.neck_nudge))
                last_neck_t = t
            if t - last_tail_t >= min_gap_ms and rng.random() < cfg.tail_flap_prob:
                events.append((t, "TAIL", cfg.tail_flap))
                last_tail_t = t
        elif ch in enders:
            # Sentence end: bring the head home — but sometimes leave it out for emphasis.
            if neck_open and rng.random() >= cfg.neck_hold_over_prob:
                events.append((t, "NECK", cfg.neck_return))
                neck_open = False
                last_neck_t = t
            opened_this_sentence = False  # the next clause may open the head again

    # Always end with the head home.
    if neck_open:
        events.append((duration_ms, "NECK", cfg.neck_return))

    events.sort(key=lambda e: e[0])
    return events


def gesture_track(
    duration_ms: int, cfg: GestureConfig, *,
    text: str | None = None, rng: random.Random | None = None,
) -> list[tuple[int, str, str]]:
    """Neck + tail gestures across [0, duration_ms]. Text-driven if `text` is given."""
    if not cfg.enabled or duration_ms <= 0:
        return []
    rng = rng or random.Random()
    if text and text.strip():
        return _text_track(duration_ms, cfg, text, rng)
    return _random_track(duration_ms, cfg, rng)
