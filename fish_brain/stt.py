"""Local speech-to-text with faster-whisper (CPU). Only text leaves the machine.

Loads the model once (lazy) and transcribes a mono 16 kHz WAV to text.
"""
from __future__ import annotations

from pathlib import Path

from .config import STTConfig


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

    def transcribe(self, wav_path: str | Path) -> str:
        model = self._ensure_model()
        segments, _info = model.transcribe(str(wav_path), language=self.cfg.language)
        return " ".join(seg.text.strip() for seg in segments).strip()
