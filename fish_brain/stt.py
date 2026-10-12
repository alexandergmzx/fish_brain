"""Speech-to-text: local faster-whisper by default, or a cloud transcription service.

- `Transcriber` (backend `local`): faster-whisper on the CPU. Only text leaves the machine.
  Loads the model once (lazy) and transcribes a mono 16 kHz WAV to text. VAD filtering drops
  non-speech so Whisper doesn't hallucinate on silence/noise.
- `CloudTranscriber` (backend `openai` | `groq`, see `config.STT_PROFILES`): the recording
  itself is uploaded to that service. Nothing to load, but it needs the internet and a key.

`make_transcriber(cfg)` picks one by `STTConfig.backend`. Both drop the canned phrases the
models emit on near-silence (e.g. the "Amara.org" subtitle credit); the cloud one also drops
a reply that is just its own context prompt read back.
"""
from __future__ import annotations

import re
import time
import unicodedata
from pathlib import Path

from . import cloud, debug
from .config import STT_PROFILES, STTConfig

# Normalized substrings Whisper hallucinates on near-silence; treated as "no speech".
_HALLUCINATIONS = (
    "amara.org",
    "subtítulos realizados por",
    "subtítulos por la comunidad",
    "subtitulado por la comunidad",
    "gracias por ver el video",
    "gracias por ver el vídeo",
)


def _is_hallucination(text: str) -> bool:
    norm = text.strip().lower()
    return any(h in norm for h in _HALLUCINATIONS)


def _words(text: str) -> list[str]:
    """Lowercase, accents stripped, punctuation turned into spaces, split into words."""
    plain = "".join(c for c in unicodedata.normalize("NFKD", text.lower())
                    if not unicodedata.combining(c))
    return re.sub(r"[^\w]+|_", " ", plain).split()


def _is_prompt_echo(text: str, prompt: str) -> bool:
    """True when the transcript is (nearly) the context prompt read back, as cloud models do
    on silence. Compared by whole words, never by substring, so a real "sí" or "pez" that
    happens to be part of the prompt survives."""
    said, hint = _words(text), _words(prompt)
    if not said or not hint:
        return False
    if said == hint:
        return True
    # Longest run of consecutive words the transcript shares with the prompt.
    best = 0
    prev = [0] * (len(hint) + 1)
    for w in said:
        cur = [0] * (len(hint) + 1)
        for j, h in enumerate(hint, 1):
            if w == h:
                cur[j] = prev[j - 1] + 1
                best = max(best, cur[j])
        prev = cur
    # The run must also be most of what was said: a long real sentence that happens to
    # quote the prompt is speech, not an echo.
    return best >= 4 and best >= 0.6 * len(hint) and best >= 0.6 * len(said)


class Transcriber:
    def __init__(self, cfg: STTConfig):
        self.cfg = cfg
        self._model = None

    def _ensure_model(self):
        if self._model is None:
            from faster_whisper import WhisperModel  # lazy: heavy import
            self._model = WhisperModel(
                self.cfg.model, device=self.cfg.device, compute_type=self.cfg.compute_type
            )
        return self._model

    def ensure_loaded(self) -> None:
        """Download (if needed) and load the model now, e.g. to prefetch at setup."""
        self._ensure_model()

    def transcribe(self, wav_path: str | Path) -> str:
        sent = {"backend": "local", "model": self.cfg.model, "language": self.cfg.language}
        t0 = time.monotonic()
        try:
            model = self._ensure_model()
            # vad_filter drops non-speech segments -> far fewer silence hallucinations.
            segments, _info = model.transcribe(
                str(wav_path), language=self.cfg.language, vad_filter=True)
            text = " ".join(seg.text.strip() for seg in segments).strip()
        except Exception as e:
            debug.model("stt", sent, error=e, seconds=time.monotonic() - t0)
            raise
        dropped = "hallucination" if _is_hallucination(text) else ""
        # For /debug: the text as the model gave it, and the filter that emptied it.
        debug.model("stt", sent, seconds=time.monotonic() - t0, raw=text,
                    final="" if dropped else text, dropped=dropped)
        return "" if dropped else text


class CloudTranscriber:
    """Uploads the recording to an OpenAI-compatible transcription endpoint."""

    def __init__(self, cfg: STTConfig):
        if cfg.backend not in STT_PROFILES:
            raise ValueError(_unknown_backend(cfg.backend))
        self.cfg = cfg
        self.profile = STT_PROFILES[cfg.backend]
        self.model = cfg.cloud_model or self.profile["model"]

    def ensure_loaded(self) -> None:
        """Nothing to download or load for a cloud backend."""

    def _request(self, wav_path: str | Path) -> dict:
        req: dict = {"file": Path(wav_path), "model": self.model}
        if self.cfg.prompt:
            req["prompt"] = self.cfg.prompt
        if self.model.startswith("gpt-transcribe"):
            # This model takes a list of languages (not `language`) plus vocabulary hints;
            # extra_body keeps it working on SDK versions that lack those arguments.
            extra: dict = {"languages": [self.cfg.language]}
            if self.cfg.keywords:
                extra["keywords"] = list(self.cfg.keywords)
            req["extra_body"] = extra
        else:
            req["language"] = self.cfg.language
        return req

    def transcribe(self, wav_path: str | Path) -> str:
        sent = {"backend": self.cfg.backend, "model": self.model, "language": self.cfg.language,
                "prompt": self.cfg.prompt, "keywords": list(self.cfg.keywords or ())}
        if not cloud.is_online():
            debug.model("stt", sent, sent=False, note="not sent: known offline")
            raise cloud.CloudUnavailable("offline")
        client = cloud.client(self.profile["base_url"], self.profile["api_key_env"])
        t0 = time.monotonic()
        try:
            with cloud.guard():
                resp = client.audio.transcriptions.create(**self._request(wav_path))
        except Exception as e:
            debug.model("stt", sent, error=e, seconds=time.monotonic() - t0)
            raise
        text = (getattr(resp, "text", "") or "").strip()
        dropped = ("hallucination" if _is_hallucination(text) else
                   "prompt echo" if _is_prompt_echo(text, self.cfg.prompt) else "")
        # For /debug: the text as the model gave it, and the filter that emptied it.
        debug.model("stt", sent, seconds=time.monotonic() - t0, raw=text,
                    final="" if dropped else text, dropped=dropped)
        return "" if dropped else text


def _unknown_backend(backend: str) -> str:
    choices = ", ".join(["local", *STT_PROFILES])
    return f"unknown STT backend {backend!r} (choices: {choices})"


def make_transcriber(cfg: STTConfig) -> Transcriber | CloudTranscriber:
    """The transcriber for `cfg.backend`: local faster-whisper or a cloud profile."""
    if cfg.backend == "local":
        return Transcriber(cfg)
    if cfg.backend in STT_PROFILES:
        return CloudTranscriber(cfg)
    raise ValueError(_unknown_backend(cfg.backend))
