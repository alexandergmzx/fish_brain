"""Text-to-speech: render text to a WAV file with the configured backend.

- `loq` (default): the local Loquendo "Jorge" engine. The loq daemon stays warm once started.
- `openai`: OpenAI speech. Requested as raw PCM and wrapped into a WAV here, because the
  service's own streamed WAV header can carry a placeholder length.

Either way the result is a plain integer-PCM WAV on disk and nothing is played: the
conductor owns playback so it stays in sync with the streamed motor commands.
"""
from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import sys
import tempfile
import time
import wave
from pathlib import Path

from . import cloud, debug, voice_guard
from .config import TTS_ROOMS, TTSConfig


def warm(cfg: TTSConfig) -> None:
    """Start/warm the loq daemon so the first phrase isn't slow. Best-effort; loq only.
    Also says at start-up when the reshaping is asked for and its program is missing."""
    if shaping(cfg) and cfg.formants == "keep" and shutil.which(cfg.rubberband_bin) is None:
        print(f"[tts] WARNING: FISH_TTS_PITCH_ST/FISH_TTS_TEMPO set but {cfg.rubberband_bin} "
              "is not installed: every render fails (sudo apt update && sudo apt install "
              "rubberband-cli)", file=sys.stderr, flush=True)
    if _sox_effects(cfg) and shutil.which(cfg.sox_bin) is None:
        print(f"[tts] WARNING: FISH_TTS_FORMANTS=shift or FISH_TTS_ROOM set but {cfg.sox_bin} "
              "is not installed: "
              "every render fails (sudo apt update && sudo apt install sox)",
              file=sys.stderr, flush=True)
    if cfg.backend != "loq":
        return
    try:
        subprocess.run([cfg.loq_bin, "--start"], check=False,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except FileNotFoundError:
        return
    voice_guard.warm(cfg)            # the licence probe, where FISH_LOQ_PROBE_S is set


def fingerprint(cfg: TTSConfig) -> str:
    """What makes two renderings of the same text differ (used in the canned cache key)."""
    if cfg.backend == "loq":
        from .say_as import rules_hash
        rules = rules_hash(cfg.loq_prefix, cfg.loq_hum, cfg.say_as)
        return str(cfg.sample_rate) + (f"|{rules}" if rules else "") + _shape_key(cfg)
    how = hashlib.sha1(cfg.openai_instructions.encode("utf-8")).hexdigest()[:8]
    rate = "" if cfg.openai_rate_factor == 1.0 else f"|x{cfg.openai_rate_factor:g}"
    return f"{cfg.backend}|{cfg.openai_model}|{cfg.openai_voice}|{how}{rate}{_shape_key(cfg)}"


def _shape_key(cfg: TTSConfig) -> str:
    key = ""
    if shaping(cfg):
        key = f"|p{cfg.pitch_st:g}t{cfg.tempo:g}" + ("fs" if cfg.formants == "shift" else "")
    return key + (f"|room={cfg.room}" if cfg.room else "")


def _validate_wav(path: Path) -> None:
    """Refuse a file the envelope/conductor can't use, before any motor command is sent."""
    try:
        with wave.open(str(path), "rb") as w:
            frames, rate, width = w.getnframes(), w.getframerate(), w.getsampwidth()
        ok = width in (1, 2, 4) and rate > 0 and 0.05 <= frames / rate <= 600
    except (wave.Error, EOFError, OSError, ZeroDivisionError):
        ok = False
    if not ok:
        path.unlink(missing_ok=True)
        raise RuntimeError(f"TTS produced an unusable WAV ({path.name})")


_LOQ_TIMEOUT_S = 30.0
_SHAPE_TIMEOUT_S = 30.0       # (estimate) a 15 s line on the board's CPU; not measured


def _synthesize_loq(text: str, cfg: TTSConfig, out_path: Path) -> None:
    # "--" so a reply starting with "-" is not read as an option.
    cmd = [cfg.loq_bin, "-o", str(out_path), "-r", str(cfg.sample_rate), "--", text]
    try:
        # A warm render is under a second and a cold one about 8 s; one that hangs must
        # still end, or the turn loop waits for it at every later turn.
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=_LOQ_TIMEOUT_S)
    except subprocess.TimeoutExpired:
        raise RuntimeError(f"loq failed: no WAV after {_LOQ_TIMEOUT_S:.0f} s") from None
    if proc.returncode != 0 or not out_path.exists():
        raise RuntimeError(
            f"loq failed (rc={proc.returncode}): {proc.stderr.strip() or proc.stdout.strip()}"
        )


def _synthesize_openai(text: str, cfg: TTSConfig, out_path: Path) -> None:
    if not cloud.is_online():
        raise cloud.CloudUnavailable("offline")
    with cloud.guard():
        with cloud.client().audio.speech.with_streaming_response.create(
            model=cfg.openai_model,
            voice=cfg.openai_voice,
            input=text[:4096],
            instructions=cfg.openai_instructions,
            response_format="pcm",          # 24 kHz, 16-bit little-endian, mono, no header
        ) as resp:
            pcm = resp.read()
    part = out_path.with_name(out_path.name + ".part")
    with wave.open(str(part), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(round(cfg.openai_pcm_rate * cfg.openai_rate_factor))
        w.writeframes(pcm)
    os.replace(part, out_path)


def shaping(cfg: TTSConfig) -> bool:
    """Whether the render is reshaped (pitch and tempo set apart)."""
    return cfg.pitch_st != 0.0 or cfg.tempo != 1.0


def _reshape(path: Path, cfg: TTSConfig) -> None:
    """Pitch and tempo changed apart with the formants kept, so a lower voice stays the same
    voice (ash at -2 and 0.72, 2026-10-28)."""
    _filter(path, ".shaped.wav", "rubberband", "rubberband-cli",
            lambda src, dst: [cfg.rubberband_bin, "-q", "-F", f"-p{cfg.pitch_st:g}",
                              f"-T{cfg.tempo:g}", src, dst])


def _sox_effects(cfg: TTSConfig) -> list[str]:
    """One sox pass: with the formants shifted, sox's `pitch` moves pitch and formants together
    (older and bigger: Jorge at -2, the hat's pick of 2026-10-31) and `tempo` the speed; then
    the room. Empty = no sox."""
    fx = []
    if shaping(cfg) and cfg.formants == "shift":
        if cfg.pitch_st:
            fx += ["pitch", f"{round(cfg.pitch_st * 100)}"]
        if cfg.tempo != 1.0:
            fx += ["tempo", f"{cfg.tempo:g}"]
    return fx + (TTS_ROOMS[cfg.room] if cfg.room else [])


def _sox(path: Path, cfg: TTSConfig) -> None:
    _filter(path, ".sox.wav", "sox", "sox",
            lambda src, dst: [cfg.sox_bin, "-q", src, dst, *_sox_effects(cfg)])


def _filter(path: Path, suffix: str, name: str, package: str, make_cmd) -> None:
    """Run one audio program from `path` to a side file and put the result in its place."""
    part = path.with_name(path.name + suffix)
    cmd = make_cmd(str(path), str(part))
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=_SHAPE_TIMEOUT_S)
    except FileNotFoundError:
        raise RuntimeError(f"{cmd[0]} is not installed "
                           f"(sudo apt update && sudo apt install {package})") from None
    except subprocess.TimeoutExpired:
        part.unlink(missing_ok=True)
        raise RuntimeError(f"{name}: no WAV after {_SHAPE_TIMEOUT_S:.0f} s") from None
    if proc.returncode != 0 or not part.exists():
        part.unlink(missing_ok=True)
        raise RuntimeError(f"{name} failed (rc={proc.returncode}): {proc.stderr.strip()[-200:]}")
    os.replace(part, path)


def synthesize(text: str, cfg: TTSConfig, out_path: str | Path | None = None) -> Path:
    """Render `text` to a WAV and return its path. Raises on failure."""
    text = text.strip()
    if not text:
        raise ValueError("synthesize(): empty text")
    if out_path is None:
        fd, name = tempfile.mkstemp(suffix=".wav", prefix="fish_")
        os.close(fd)
        Path(name).unlink(missing_ok=True)  # the backend writes it; we just want the name
        out_path = name
    out_path = Path(out_path)
    sent = {"backend": cfg.backend, "text": text}             # for /debug: what the voice got
    if cfg.backend == "openai":
        sent.update(model=cfg.openai_model, voice=cfg.openai_voice,
                    instructions=cfg.openai_instructions)
    t0 = time.monotonic()
    try:
        if cfg.backend == "loq":
            from .say_as import voice_text
            spoken = voice_text(text, cfg.loq_prefix, cfg.loq_hum, cfg.say_as)
            if spoken != text:
                sent["voice_text"] = spoken            # what Jorge was really given
            voice_guard.before_render(cfg)
            _synthesize_loq(spoken, cfg, out_path)
        elif cfg.backend == "openai":
            _synthesize_openai(text, cfg, out_path)
        else:
            raise ValueError(f"FISH_TTS_BACKEND={cfg.backend!r}; choose loq or openai")
        _validate_wav(out_path)
        if cfg.backend == "loq":
            voice_guard.after_render(cfg, out_path)   # the licence warning is never kept
        sent["render_s"] = round(time.monotonic() - t0, 3)
        # After the guard, which times the raw render.
        if shaping(cfg):
            sent.update(pitch_st=cfg.pitch_st, tempo=cfg.tempo, formants=cfg.formants)
        if shaping(cfg) and cfg.formants == "keep":
            t1 = time.monotonic()
            _reshape(out_path, cfg)
            _validate_wav(out_path)
            sent["rubberband_s"] = round(time.monotonic() - t1, 3)
        if _sox_effects(cfg):
            t1 = time.monotonic()
            if cfg.room:
                sent["room"] = cfg.room
            _sox(out_path, cfg)
            _validate_wav(out_path)
            sent["sox_s"] = round(time.monotonic() - t1, 3)
    except Exception as e:
        debug.model("tts", sent, error=e, seconds=time.monotonic() - t0)
        raise
    debug.model("tts", sent, seconds=time.monotonic() - t0)
    return out_path
