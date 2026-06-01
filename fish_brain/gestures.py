"""Random neck/tail gestures to play while the fish talks.

Produces a list of (t_ms, channel, chain_body) events spread across the utterance. Each
chain_body is a firmware timed-chain (e.g. "180 450 -180 350"); the firmware sequences
and auto-stops it, so these fire-and-forget alongside the mouth stream.

Timing is roughly Poisson (random gaps around a mean) with a minimum gap so the two
channels don't pile onto each other.
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


def gesture_track(
    duration_ms: int, cfg: GestureConfig, rng: random.Random | None = None,
) -> list[tuple[int, str, str]]:
    """Random neck + tail gestures across [0, duration_ms]."""
    if not cfg.enabled:
        return []
    rng = rng or random.Random()
    events = _channel_events(
        duration_ms, cfg.neck_mean_gap_s, cfg.min_gap_s, cfg.neck_chains, "NECK", rng
    )
    events += _channel_events(
        duration_ms, cfg.tail_mean_gap_s, cfg.min_gap_s, cfg.tail_chains, "TAIL", rng
    )
    events.sort(key=lambda e: e[0])
    return events
