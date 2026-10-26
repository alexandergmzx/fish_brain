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
import subprocess
import tempfile
import time
import wave
from pathlib import Path

from . import cloud, debug, voice_guard
from .config import TTSConfig


def warm(cfg: TTSConfig) -> None:
    """Start/warm the loq daemon so the first phrase isn't slow. Best-effort; loq only."""
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
        return str(cfg.sample_rate) + (f"|{rules}" if rules else "")
    how = hashlib.sha1(cfg.openai_instructions.encode("utf-8")).hexdigest()[:8]
    return f"{cfg.backend}|{cfg.openai_model}|{cfg.openai_voice}|{how}"


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
        w.setframerate(cfg.openai_pcm_rate)
        w.writeframes(pcm)
    os.replace(part, out_path)


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
    except Exception as e:
        debug.model("tts", sent, error=e, seconds=time.monotonic() - t0)
        raise
    debug.model("tts", sent, seconds=time.monotonic() - t0)
    return out_path
