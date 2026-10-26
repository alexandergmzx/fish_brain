"""Loquendo licence guard: never let the licence warning out, never cache it.

Loquendo binds its licence to a network adapter's MAC, and the Wine prefix's wineserver fixes
the adapter list when it starts. Started while NetworkManager scanned with a random MAC, every
render is the same warning sentence ("la licencia que posee no es válida...") instead of the
phrase, until the wineserver is gone (docs/results/2026-10-25-loquendo-licence.md).

So, with FISH_LOQ_PROBE_S set (the probe phrase's clean length, measured on the board):
- `warm` renders the probe phrase. Too far from its clean length: the daemon is stopped, the
  prefix's wineserver is killed, the adapter's own MAC is waited for, and it is tried again.
  Still bad: the voice is "tainted", re-checked every minute.
- While tainted, `before_render` refuses every render (canned clips still play from cache).
- `after_render` re-probes any render as long as the warning itself; a bad one is deleted,
  so it is never cached.
Off (the laptop) when FISH_LOQ_PROBE_S is 0.
"""
from __future__ import annotations

import os
import subprocess
import tempfile
import threading
import time
import wave
from pathlib import Path

from .config import TTSConfig

OFF, CLEAN, TAINTED = "off", "clean", "tainted"

_state = OFF
_last_s: float | None = None
_lock = threading.Lock()
_recheck: threading.Thread | None = None


class VoiceUnavailable(RuntimeError):
    """The voice would speak the licence warning: nothing may be rendered now."""


def state() -> str:
    return _state


def view() -> dict:
    return {"state": _state, "probe_s": _last_s}


def _seconds(path: Path) -> float:
    with wave.open(str(path), "rb") as w:
        return w.getnframes() / w.getframerate()


def probe(cfg: TTSConfig) -> float:
    """Render the probe phrase exactly as the fish would and return its length in seconds."""
    from . import tts
    from .say_as import voice_text
    fd, name = tempfile.mkstemp(suffix=".wav", prefix="fish_probe_")
    os.close(fd)
    path = Path(name)
    path.unlink(missing_ok=True)
    try:
        tts._synthesize_loq(voice_text(cfg.loq_probe_text, cfg.loq_prefix, cfg.loq_hum,
                                       cfg.say_as), cfg, path)
        return _seconds(path)
    finally:
        path.unlink(missing_ok=True)


def _clean(cfg: TTSConfig, seconds: float) -> bool:
    return abs(seconds - cfg.loq_probe_s) <= cfg.loq_probe_tol_s


def _check(cfg: TTSConfig) -> bool:
    global _last_s
    try:
        _last_s = probe(cfg)
    except Exception as e:
        print(f"[voice] probe failed: {e}", flush=True)
        _last_s = None
        return False
    return _clean(cfg, _last_s)


def own_mac(iface: str) -> bool:
    """True when `iface` shows its own hardware address (ip reports `permaddr` only when the
    current address differs). The address itself is never read out or logged."""
    try:
        out = subprocess.run(["ip", "-j", "link", "show", "dev", iface], capture_output=True,
                             text=True, timeout=5).stdout
    except (OSError, subprocess.TimeoutExpired):
        return False
    return bool(out.strip()) and '"permaddr"' not in out


def _run(cmd: list[str], timeout: float) -> None:
    try:
        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                       timeout=timeout, check=False)
    except (OSError, subprocess.TimeoutExpired):
        pass


def recover(cfg: TTSConfig) -> None:
    """A fresh daemon on a fresh wineserver, started once the adapter has its own MAC."""
    _run([cfg.loq_bin, "--stop"], 30)
    _run([cfg.loq_wineserver, "-k"], 30)        # the prefix's (WINEPREFIX or ~/.wine)
    if cfg.loq_mac_iface:
        deadline = time.monotonic() + cfg.loq_mac_wait_s
        while not own_mac(cfg.loq_mac_iface) and time.monotonic() < deadline:
            time.sleep(1.0)
    _run([cfg.loq_bin, "--start"], 120)


def _set(new: str, cfg: TTSConfig) -> None:
    global _state
    if new != _state:
        detail = f"{_last_s:.2f} s, clean {cfg.loq_probe_s:.2f} s" if _last_s is not None \
            else "no probe"
        print(f"[voice] {new.upper()} ({detail})", flush=True)
    _state = new


def warm(cfg: TTSConfig) -> str:
    """Probe after the daemon is warm; recover once; else tainted with a background re-check."""
    if cfg.backend != "loq" or cfg.loq_probe_s <= 0:
        return OFF
    with _lock:
        if _check(cfg):
            _set(CLEAN, cfg)
            return _state
        print("[voice] the probe is not clean: restarting the voice on a fresh wineserver",
              flush=True)
        recover(cfg)
        _set(CLEAN if _check(cfg) else TAINTED, cfg)
        if _state == TAINTED:
            _start_recheck(cfg)
        return _state


def _start_recheck(cfg: TTSConfig) -> None:
    global _recheck
    if _recheck is not None and _recheck.is_alive():
        return

    def loop() -> None:
        while _state == TAINTED:
            time.sleep(cfg.loq_recheck_s)
            with _lock:
                if _state != TAINTED:
                    return
                recover(cfg)
                if _check(cfg):
                    _set(CLEAN, cfg)

    _recheck = threading.Thread(target=loop, name="voice-recheck", daemon=True)
    _recheck.start()


def before_render(cfg: TTSConfig) -> None:
    if cfg.backend == "loq" and _state == TAINTED:
        raise VoiceUnavailable("the voice would say the licence warning (tainted)")


def after_render(cfg: TTSConfig, path: Path) -> None:
    """A render as long as the warning is checked again; a bad one is deleted, never cached."""
    if cfg.backend != "loq" or _state == OFF or cfg.loq_warning_s <= 0:
        return
    try:
        seconds = _seconds(path)
    except (wave.Error, EOFError, OSError, ZeroDivisionError):
        return
    if abs(seconds - cfg.loq_warning_s) > cfg.loq_warning_tol_s:
        return
    with _lock:
        ok = _check(cfg)
        if not ok:
            _set(TAINTED, cfg)
    if not ok:
        path.unlink(missing_ok=True)
        _start_recheck(cfg)
        raise VoiceUnavailable("the render was the licence warning")
