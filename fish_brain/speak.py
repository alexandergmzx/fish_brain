"""High-level: speak(text) -> the fish says it.

Ties together TTS (loq), envelope analysis (mouth track), gesture generation, and the
conductor (audio playback + synced serial streaming).
"""
from __future__ import annotations

from pathlib import Path

from . import gestures, tts
from .conductor import Player, perform
from .config import Config
from .envelope import mouth_track
from .serial_link import BaseLink


def perform_wav(
    wav: str | Path,
    link: BaseLink,
    cfg: Config,
    *,
    player: Player | None = None,
    viz=None,
) -> None:
    """Perform an already-rendered WAV on the fish: mouth track + gestures + playback.

    Shared by `speak()` (fresh TTS) and `canned.play()` (cached WAV). If `viz` is given
    (a VizServer), announce the speech to the on-screen fish before performing.
    """
    track = mouth_track(wav, cfg.mouth, cfg.serial.max_cmd_hz)
    duration_ms = track[-1][0] if track else 0
    gesture_events = (
        gestures.gesture_track(duration_ms, cfg.gesture)
        if cfg.gesture.enabled else []
    )
    if viz is not None:
        viz.announce_speech(wav, duration_ms, gesture_events)
    perform(wav, track, gesture_events, link, cfg, player=player)


def speak(
    text: str,
    link: BaseLink,
    cfg: Config,
    *,
    player: Player | None = None,
    keep_wav: bool = False,
    viz=None,
) -> None:
    """Synthesize `text` and perform it on the fish via `link`."""
    wav = tts.synthesize(text, cfg.tts)
    try:
        perform_wav(wav, link, cfg, player=player, viz=viz)
    finally:
        if not keep_wav:
            Path(wav).unlink(missing_ok=True)
