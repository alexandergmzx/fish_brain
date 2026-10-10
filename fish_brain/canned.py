"""Canned phrase library: pre-rendered fixed phrases (welcome, goodbye, …).

Phrases live in `cfg.canned.phrases` (name -> Spanish text). Each is synthesized once by the
configured TTS backend and cached on disk under a filename keyed by a hash of the text and
of how it is rendered (backend, voice, rate), so:
  - replays are instant (no LLM, no re-synthesis),
  - editing a phrase's wording transparently re-renders it (the hash changes).

Playback reuses the exact same sync pipeline as live speech via `speak.perform_wav`, so
canned phrases drive the mouth/gestures (and the on-screen fish) identically.
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path

from . import cloud, speak as speak_mod, tts
from .conductor import Player
from .config import Config
from .serial_link import BaseLink


def _cache_path(name: str, text: str, cfg: Config) -> Path:
    """Cache file for a phrase, keyed by text + rendering so edits invalidate it."""
    digest = hashlib.sha1(f"{text}|{tts.fingerprint(cfg.tts)}".encode("utf-8")).hexdigest()[:8]
    return cfg.canned.cache_dir / f"{name}-{digest}.wav"


def ensure_rendered(name: str, cfg: Config) -> Path:
    """Return the cached WAV for `name`, synthesizing it if missing. Raises if unknown."""
    text = cfg.canned.phrases.get(name)
    if text is None:
        raise KeyError(f"unknown canned phrase: {name!r}")
    path = _cache_path(name, text, cfg)
    if path.exists():
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    part = path.with_name(path.name + ".new.wav")
    try:
        # Render next to the target and move it in, so a failed render is never cached.
        tts.synthesize(text, cfg.tts, out_path=part)
        os.replace(part, path)
        return path
    except Exception:
        part.unlink(missing_ok=True)
        # Offline or TTS down: any earlier rendering of this phrase beats silence.
        older = sorted((p for p in path.parent.glob(f"{name}-*.wav")
                        if not p.name.endswith(".new.wav")),
                       key=lambda p: p.stat().st_mtime)
        if older:
            return older[-1]
        raise


def play(
    name: str,
    link: BaseLink,
    cfg: Config,
    *,
    player: Player | None = None,
    viz=None,
) -> None:
    """Speak a canned phrase by name. No-op (with a warning) if the name is unknown."""
    if not name:
        return
    try:
        wav = ensure_rendered(name, cfg)
    except Exception as e:  # unknown name or TTS failure: don't crash the loop
        print(f"[canned] could not play {name!r}: {e}", flush=True)
        return
    # keep_wav is implicit: perform_wav never deletes; we just don't unlink the cache file.
    # Pass the phrase text so the neck/tail gestures track the words too.
    text = cfg.canned.phrases.get(name)
    speak_mod.perform_wav(wav, link, cfg, player=player, viz=viz, text=text)


def prerender_all(cfg: Config) -> list[str]:
    """Render every configured phrase up front so the first welcome/goodbye is instant.

    Returns the names that could not be rendered exactly as configured.
    """
    failed: list[str] = []
    if not cfg.canned.enabled:
        return failed
    for name, text in cfg.canned.phrases.items():
        try:
            if ensure_rendered(name, cfg) != _cache_path(name, text, cfg):
                failed.append(name)          # fell back to an older rendering
        except Exception as e:
            failed.append(name)
            print(f"[canned] prerender of {name!r} failed: {e}", flush=True)
            if isinstance(e, cloud.CloudUnavailable):
                break                        # offline: don't wait once per phrase
    return failed
