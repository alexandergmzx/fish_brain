"""High-level: speak(text) -> the fish says it.

Ties together TTS (loq), envelope analysis (mouth track), gesture generation, and the
conductor (audio playback + synced serial streaming).
"""
from __future__ import annotations

import threading
import time
import wave
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
    text: str | None = None,
    filler: bool = False,
) -> float:
    """Perform an already-rendered WAV on the fish: mouth track + gestures + playback.
    Returns the monotonic time playback started. `filler` marks a phrase said while a turn
    still waits, so the page does not take it for the reply.

    Shared by `speak()` (fresh TTS) and `canned.play()` (cached WAV). If `viz` is given
    (a VizServer), announce the speech to the on-screen fish before performing. `text`, when
    known, drives the neck/tail gestures off the words (out on spaces, home on sentence ends).
    """
    level_track = mouth_track(wav, cfg.mouth, cfg.serial.max_cmd_hz)
    pulses = mouth_pulses(level_track, cfg.mouth)
    duration_ms = level_track[-1][0] if level_track else 0
    gesture_events = (
        gestures.gesture_track(duration_ms, cfg.gesture, text=text)
        if cfg.gesture.enabled else []
    )
    if viz is not None:
        if filler:
            viz.announce_speech(wav, duration_ms, gesture_events, mouth_track=level_track,
                                filler=True)
        else:
            viz.announce_speech(wav, duration_ms, gesture_events, mouth_track=level_track)
    return perform(wav, pulses, gesture_events, link, cfg, player=player)


def speak(
    text: str,
    link: BaseLink,
    cfg: Config,
    *,
    player: Player | None = None,
    keep_wav: bool = False,
    viz=None,
    timing: dict | None = None,
) -> None:
    """Synthesize `text` and perform it on the fish via `link`.

    `timing`, when given, receives "tts" (seconds to synthesize) and "play_start" (seconds
    from the call to the first sample).
    """
    t0 = time.monotonic()
    wav = tts.synthesize(text, cfg.tts)
    if timing is not None:
        timing["tts"] = time.monotonic() - t0
    try:
        started = perform_wav(wav, link, cfg, player=player, viz=viz, text=text)
        if timing is not None:
            timing["play_start"] = started - t0
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
        self.last_timing: dict = {}

    def speak(self, text: str, *, role: str = "fish") -> bool:
        """Speak `text` verbatim. Returns False if empty or already speaking (dropped)."""
        text = (text or "").strip()
        if not text or not self._lock.acquire(blocking=False):
            return False
        try:
            if self.viz is not None:
                self.viz.push_transcript(text, role)   # show what was actually spoken
            self.last_timing = {}
            # A link that is allowed to be absent gets a chance to come back before we talk.
            retry = getattr(self.link, "try_attach", None)
            if retry is not None and not self.link.attached:
                threading.Thread(target=retry, name="link-retry", daemon=True).start()
            speak(text, self.link, self.cfg, player=self.player, viz=self.viz,
                  timing=self.last_timing)
            return True
        finally:
            self._lock.release()

    def say_canned(self, name: str, *, filler: bool = False, render: bool = True) -> bool:
        """Play a canned phrase by name under the same lock. Returns False when the fish is
        already speaking (dropped) or the name is empty; an unknown name is a no-op.
        `filler`: the phrase covers a wait inside a turn (see `perform_wav`); it is never
        rendered here. `render=False`: the same for a phrase that is not a filler."""
        if not name or not self._lock.acquire(blocking=False):
            return False
        try:
            from . import canned   # lazy: canned imports this module
            if filler or not render:
                canned.play(name, self.link, self.cfg, player=self.player, viz=self.viz,
                            filler=filler, render=False)
            else:
                canned.play(name, self.link, self.cfg, player=self.player, viz=self.viz)
            return True
        finally:
            self._lock.release()

    def play_sound(self, wav: str | Path, *, tail_chain: str | None = None) -> float | None:
        """Play a sound that is not speech (the burble) under the same lock: no mouth pulse,
        at most one tail chain, and the close pulse that ends every performance. The page
        gets it as a filler with an empty mouth track. Returns when playback started, or
        None when the fish was already speaking (dropped)."""
        if not self._lock.acquire(blocking=False):
            return None
        try:
            events = [(0, "TAIL", tail_chain)] if tail_chain else []
            if self.viz is not None:
                with wave.open(str(wav), "rb") as w:
                    duration_ms = int(1000 * w.getnframes() / (w.getframerate() or 1))
                self.viz.announce_speech(wav, duration_ms, events, mouth_track=[], filler=True)
            return perform(wav, [], events, self.link, self.cfg, player=self.player)
        finally:
            self._lock.release()

    # The reply in two steps, for a turn that says fillers while the voice is rendered:
    # `speak` holds the lock from the first byte of synthesis, which would drop them.
    def synthesize(self, text: str, timing: dict) -> Path:
        """Render `text` to a WAV, without the lock (any thread). `timing` gets "tts" and
        the moment the rendering started, from which `perform` counts "play_start"."""
        t0 = time.monotonic()
        wav = tts.synthesize(text, self.cfg.tts)
        timing["tts"] = time.monotonic() - t0
        timing["_t0"] = t0
        return wav

    def perform(self, wav: str | Path, text: str, timing: dict, *, role: str = "fish") -> bool:
        """Say a WAV rendered by `synthesize`, under the lock; the file is deleted. Returns
        False when the fish is already speaking (dropped), like `speak`."""
        if not self._lock.acquire(blocking=False):
            Path(wav).unlink(missing_ok=True)
            return False
        try:
            if self.viz is not None:
                self.viz.push_transcript(text, role)   # show what was actually spoken
            t0 = timing.pop("_t0", time.monotonic())
            self.last_timing = timing
            retry = getattr(self.link, "try_attach", None)
            if retry is not None and not self.link.attached:
                threading.Thread(target=retry, name="link-retry", daemon=True).start()
            started = perform_wav(wav, self.link, self.cfg, player=self.player, viz=self.viz,
                                  text=text)
            timing["play_start"] = started - t0
            return True
        finally:
            self._lock.release()
            Path(wav).unlink(missing_ok=True)
