"""Local speech-to-text with faster-whisper (CPU). Only text leaves the machine.

Loads the model once (lazy) and transcribes a mono 16 kHz WAV to text. VAD filtering drops
non-speech so Whisper doesn't hallucinate on silence/noise, and a small blocklist drops the
canned phrases it still emits sometimes (e.g. the "Amara.org" subtitle credit).
"""
from __future__ import annotations

from pathlib import Path

from .config import STTConfig

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
        model = self._ensure_model()
        # vad_filter drops non-speech segments -> far fewer silence hallucinations.
        segments, _info = model.transcribe(
            str(wav_path), language=self.cfg.language, vad_filter=True)
        text = " ".join(seg.text.strip() for seg in segments).strip()
        return "" if _is_hallucination(text) else text
