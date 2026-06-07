"""High-level: speak(text) -> the fish says it.

Ties together TTS (loq), envelope analysis (mouth track), gesture generation, and the
conductor (audio playback + synced serial streaming).
"""
from __future__ import annotations

import threading
from pathlib import Path

from . import gestures, tts
from .conductor import Player, perform
from .config import Config
from .envelope import mouth_pulses, mouth_track
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
    level_track = mouth_track(wav, cfg.mouth, cfg.serial.max_cmd_hz)
    pulses = mouth_pulses(level_track, cfg.mouth)
    duration_ms = level_track[-1][0] if level_track else 0
    gesture_events = (
        gestures.gesture_track(duration_ms, cfg.gesture)
        if cfg.gesture.enabled else []
    )
    if viz is not None:
        viz.announce_speech(wav, duration_ms, gesture_events, mouth_track=level_track)
    perform(wav, pulses, gesture_events, link, cfg, player=player)


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


class Speaker:
    """Serialized owner of the speak path: synthesize + perform text on the fish.

    Both the conversation loop (main thread) and the on-screen text box (a viz HTTP-handler
    thread) can ask the fish to speak; they share the same serial link + audio player, so a
    lock guards against overlapping speech. The lock is non-blocking: if a phrase is already
    being spoken, a second request is dropped rather than garbling the link/audio.
    """

    def __init__(self, link: BaseLink, cfg: Config, *,
                 player: Player | None = None, viz=None):
        self.link = link
        self.cfg = cfg
        self.player = player
        self.viz = viz
        self._lock = threading.Lock()

    def speak(self, text: str, *, role: str = "fish") -> bool:
        """Speak `text` verbatim. Returns False if empty or already speaking (dropped)."""
        text = (text or "").strip()
        if not text or not self._lock.acquire(blocking=False):
            return False
        try:
            if self.viz is not None:
                self.viz.push_transcript(text, role)   # show what was actually spoken
            speak(text, self.link, self.cfg, player=self.player, viz=self.viz)
            return True
        finally:
            self._lock.release()
