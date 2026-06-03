"""Canned phrase library: pre-rendered fixed phrases (welcome, goodbye, …).

Phrases live in `cfg.canned.phrases` (name -> Spanish text). Each is synthesized once via
`loq` and cached on disk under a filename keyed by a hash of (text + sample_rate), so:
  - replays are instant (no LLM, no re-synthesis),
  - editing a phrase's wording transparently re-renders it (the hash changes).

Playback reuses the exact same sync pipeline as live speech via `speak.perform_wav`, so
canned phrases drive the mouth/gestures (and the on-screen fish) identically.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

from . import speak as speak_mod, tts
from .conductor import Player
from .config import Config
from .serial_link import BaseLink


def _cache_path(name: str, text: str, cfg: Config) -> Path:
    """Cache file for a phrase, keyed by text+sample_rate so edits invalidate it."""
    digest = hashlib.sha1(f"{text}|{cfg.tts.sample_rate}".encode("utf-8")).hexdigest()[:8]
    return cfg.canned.cache_dir / f"{name}-{digest}.wav"


def ensure_rendered(name: str, cfg: Config) -> Path:
    """Return the cached WAV for `name`, synthesizing it if missing. Raises if unknown."""
    text = cfg.canned.phrases.get(name)
    if text is None:
        raise KeyError(f"unknown canned phrase: {name!r}")
    path = _cache_path(name, text, cfg)
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        tts.synthesize(text, cfg.tts, out_path=path)
    return path


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
    except Exception as e:  # unknown name or loq failure: don't crash the loop
        print(f"[canned] could not play {name!r}: {e}")
        return
    # keep_wav is implicit: perform_wav never deletes; we just don't unlink the cache file.
    speak_mod.perform_wav(wav, link, cfg, player=player, viz=viz)


def prerender_all(cfg: Config) -> None:
    """Render every configured phrase up front so the first welcome/goodbye is instant."""
    if not cfg.canned.enabled:
        return
    for name in cfg.canned.phrases:
        try:
            ensure_rendered(name, cfg)
        except Exception as e:
            print(f"[canned] prerender of {name!r} failed: {e}")
