"""Speech-to-text: local faster-whisper by default, Canary, or a cloud transcription service.

- `Transcriber` (backend `local`): faster-whisper on the CPU. Only text leaves the machine.
  Loads the model once (lazy) and transcribes a mono 16 kHz WAV to text. VAD filtering drops
  non-speech so Whisper doesn't hallucinate on silence/noise. `FISH_STT_WINDOW_S` makes the
  encoder window follow the clip (`transcribe_window`), for a small CPU.
- `CanaryTranscriber` (backend `canary`): NVIDIA Canary through sherpa-onnx, also on this
  machine; the UNO Q's choice (docs/results/2026-10-12-unoq-stt-candidates.md).
- `CloudTranscriber` (backend `openai` | `groq`, see `config.STT_PROFILES`): the recording
  itself is uploaded to that service. Nothing to load, but it needs the internet and a key.

`make_transcriber(cfg)` picks one by `STTConfig.backend`. All drop the canned phrases the
models emit on near-silence (e.g. the "Amara.org" subtitle credit); the cloud one also drops
a reply that is just its own context prompt read back.
"""
from __future__ import annotations

import re
import threading
import time
import unicodedata
import wave
import zlib
from dataclasses import replace
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


def _window_frames(frames: int, window_s: float, tail_s: float,
                   frame_s: float = 0.01) -> int | None:
    """Encoder frames for a clip of `frames`: the clip plus `tail_s` of silence, never less
    than `window_s`. None when that passes the model's 30 s, which the stock path handles."""
    n = max(frames + round(tail_s / frame_s), round(window_s / frame_s))
    return n if n <= round(30.0 / frame_s) else None


# New tokens allowed in the window path: speech is about 6 tokens a second.
_NEW_TOKENS_BASE = 24
_NEW_TOKENS_PER_S = 12.0
# faster-whisper's own thresholds (no_speech_threshold, log_prob_threshold).
_NO_SPEECH = 0.6
_LOG_PROB = -1.0


def _repeats(text: str) -> bool:
    """True for a reply stuck on one phrase. The measure is the library's own: text that
    compresses to under 1/2.4 of its size."""
    raw = text.encode("utf-8")
    return len(raw) > 2.4 * len(zlib.compress(raw))


def _whisper_tokenizer(model, language: str):
    from faster_whisper.tokenizer import Tokenizer
    return Tokenizer(model.hf_tokenizer, model.model.is_multilingual,
                     task="transcribe", language=language)


def transcribe_window(model, audio, *, language: str = "es", window_s: float = 10.0,
                      tail_s: float = 3.0, beam_size: int = 1,
                      max_new_tokens: int | None = None, vad: bool = True) -> str:
    """One utterance through a faster-whisper `WhisperModel` with an encoder window sized to
    the clip instead of the library's fixed 30 s, which is most of the time on a small CPU.

    `audio` is mono float32 at 16 kHz. faster-whisper has no setting for this (`chunk_length`
    pads every piece back to 30 s), so the encoder and the decoder are called directly:
    one pass, no timestamps, no temperature fallback. The model was trained on padded 30 s
    windows: the clip always keeps `tail_s` of silence after it, and a short `window_s`
    costs accuracy (see docs/results). A clip that does not fit goes the stock way, and so
    does a reply that is one phrase over and over ("no, no, no, ..."), which the single
    pass falls into on some one-word clips; `max_new_tokens` (default: by the clip's
    length) keeps that case short.
    """
    import numpy as np
    from faster_whisper.audio import pad_or_trim

    if vad:
        # The same filter the stock path runs: without it silence comes back as words.
        from faster_whisper.vad import VadOptions, collect_chunks, get_speech_timestamps
        chunks = get_speech_timestamps(audio, VadOptions())
        if not chunks:
            return ""
        audio = np.concatenate(collect_chunks(audio, chunks)[0], axis=0)
    extractor = model.feature_extractor
    features = extractor(audio)[:, :-1]
    frames = features.shape[-1]
    n = _window_frames(frames, window_s, tail_s, extractor.time_per_frame)

    def stock() -> str:
        segments, _info = model.transcribe(audio, language=language, beam_size=beam_size)
        return " ".join(seg.text.strip() for seg in segments).strip()

    if n is None:
        return stock()
    if not max_new_tokens:
        max_new_tokens = _NEW_TOKENS_BASE + round(_NEW_TOKENS_PER_S * frames
                                                  * extractor.time_per_frame)
    tokenizer = _whisper_tokenizer(model, language)
    prompt = model.get_prompt(tokenizer, [], without_timestamps=True)
    result = model.model.generate(
        model.encode(pad_or_trim(features, n)), [prompt], beam_size=beam_size,
        max_length=min(model.max_length, len(prompt) + max_new_tokens),
        return_scores=True, return_no_speech_prob=True)[0]
    tokens = result.sequences_ids[0]
    # The stock path's rule for noise that got past the VAD: the model says "no speech"
    # and is unsure of its words (the score is the sum of the log-probabilities).
    if (result.no_speech_prob > _NO_SPEECH and tokens
            and result.scores[0] * len(tokens) / (len(tokens) + 1) < _LOG_PROB):
        return ""
    text = tokenizer.decode(tokens).strip()
    # A loop runs to the limit; a finished sentence that repeats itself ends on its own.
    stuck = len(tokens) >= max_new_tokens - 1 and _repeats(text)
    return stock() if stuck else text


def _read_wav(wav_path: str | Path):
    """A recording as mono float32 at 16 kHz."""
    import numpy as np
    with wave.open(str(wav_path), "rb") as w:
        shape = (w.getnchannels(), w.getsampwidth(), w.getframerate())
        raw = w.readframes(w.getnframes())
    if shape == (1, 2, 16000):
        return np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768.0
    from faster_whisper.audio import decode_audio      # a microphone that refused 16 kHz
    return decode_audio(str(wav_path), sampling_rate=16000)


def _finish(sent: dict, t0: float, text: str) -> str:
    """Drop the canned phrases and record the call for /debug: the text as the model gave
    it, and the filter that emptied it."""
    dropped = "hallucination" if _is_hallucination(text) else ""
    debug.model("stt", sent, seconds=time.monotonic() - t0, raw=text,
                final="" if dropped else text, dropped=dropped)
    return "" if dropped else text


class Transcriber:
    def __init__(self, cfg: STTConfig):
        self.cfg = cfg
        self._model = None
        self._lock = threading.Lock()            # the start-up warm thread and the first turn

    def _ensure_model(self):
        with self._lock:
            if self._model is None:
                from faster_whisper import WhisperModel  # lazy: heavy import
                self._model = WhisperModel(
                    self.cfg.model, device=self.cfg.device, compute_type=self.cfg.compute_type
                )
            return self._model

    def ensure_loaded(self) -> None:
        """Download (if needed) and load the model now, e.g. to prefetch at setup."""
        self._ensure_model()

    def text(self, wav_path: str | Path, *, window_s: float | None = None,
             beam_size: int | None = None) -> str:
        """The model's words for a recording, unfiltered. `window_s` and `beam_size`
        default to the configuration's."""
        model = self._ensure_model()
        window_s = self.cfg.window_s if window_s is None else window_s
        beam_size = beam_size or self.cfg.beam_size
        if window_s > 0:
            return transcribe_window(model, _read_wav(wav_path), language=self.cfg.language,
                                     window_s=window_s, beam_size=beam_size)
        # vad_filter drops non-speech segments -> far fewer silence hallucinations.
        segments, _info = model.transcribe(
            str(wav_path), language=self.cfg.language, vad_filter=True, beam_size=beam_size)
        return " ".join(seg.text.strip() for seg in segments).strip()

    def transcribe(self, wav_path: str | Path) -> str:
        sent = {"backend": "local", "model": self.cfg.model, "language": self.cfg.language,
                "beam": self.cfg.beam_size, "window_s": self.cfg.window_s}
        t0 = time.monotonic()
        try:
            text = self.text(wav_path)
        except Exception as e:
            debug.model("stt", sent, error=e, seconds=time.monotonic() - t0)
            raise
        return _finish(sent, t0, text)


class CanaryTranscriber:
    """NVIDIA Canary-180m-flash through sherpa-onnx, on this machine: the language is told,
    not guessed, and the time follows the clip (about 2.5 s for a 4 s turn on the UNO Q,
    where `small` takes 20). Its library and its model are only needed when this backend is
    chosen. It is for short phrases: its time grows faster than the clip, so a recording
    over `canary_long_s` goes to the services in `long_online` while the machine is online,
    and to the local model on a short window when none of them answers."""

    FILES = ("encoder", "decoder")

    def __init__(self, cfg: STTConfig):
        import importlib.util
        self.cfg = cfg
        self._recognizer = None
        self._lock = threading.Lock()
        self._long = Transcriber(cfg)            # the long recordings, when nothing online answers
        unknown = [name for name in cfg.long_online if name not in STT_PROFILES]
        if unknown:
            raise ValueError(f"FISH_STT_LONG: unknown service {unknown[0]!r} "
                             f"(choices: {', '.join(STT_PROFILES)})")
        self._online = [(name, CloudTranscriber(replace(cfg, backend=name, cloud_model="")))
                        for name in cfg.long_online]
        self._rest_until: dict[str, float] = {}  # a service that failed is left alone a while
        if not cfg.model_dir:
            raise ValueError("STT backend 'canary' needs FISH_STT_MODEL_DIR (the folder with "
                             "the model: deploy/unoq_setup.sh stt)")
        folder = Path(cfg.model_dir).expanduser()
        self._paths = {stem: _onnx(folder, stem) for stem in self.FILES}
        self._paths["tokens"] = folder / "tokens.txt"
        missing = [str(p) for p in self._paths.values() if not p.exists()]
        if missing:
            raise ValueError(f"STT backend 'canary': no {missing[0]}")
        if importlib.util.find_spec("sherpa_onnx") is None:
            raise RuntimeError("STT backend 'canary' needs the sherpa-onnx package "
                               "(pip install 'fish_brain[unoq]')")

    def _ensure_model(self):
        with self._lock:
            if self._recognizer is None:
                import sherpa_onnx               # lazy: only this backend needs it
                self._recognizer = sherpa_onnx.OfflineRecognizer.from_nemo_canary(
                    encoder=str(self._paths["encoder"]), decoder=str(self._paths["decoder"]),
                    tokens=str(self._paths["tokens"]), src_lang=self.cfg.language,
                    tgt_lang=self.cfg.language, num_threads=self.cfg.canary_threads)
            return self._recognizer

    def ensure_loaded(self) -> None:
        """Both models: Canary, then the local one a long recording needs; and the online
        services' clients, whose first use otherwise costs the first long turn several
        seconds of imports."""
        self._ensure_model()
        self._long.ensure_loaded()
        for _name, online in self._online:
            try:
                cloud.client(online.profile["base_url"], online.profile["api_key_env"])
            except Exception:                    # no key, no SDK: the turn that needs it says so
                pass

    def _canary(self, audio) -> str:
        import numpy as np
        pad = np.zeros(round(self.cfg.canary_pad_s * 16000), np.float32)
        recognizer = self._ensure_model()
        stream = recognizer.create_stream()
        stream.accept_waveform(16000, np.concatenate([pad, audio, pad]))
        recognizer.decode_stream(stream)
        return stream.result.text.strip()

    def transcribe(self, wav_path: str | Path) -> str:
        sent = {"backend": "canary", "model": Path(self.cfg.model_dir).name,
                "language": self.cfg.language}
        t0 = time.monotonic()
        try:
            audio = _read_wav(wav_path)
            if len(audio) / 16000.0 > self.cfg.canary_long_s:
                skipped = []
                for name, online in self._online:
                    text = self._ask(name, online, wav_path, skipped)
                    if text is not None:
                        return text                              # it keeps its own record
                sent["route"] = f"long: local '{self._long.cfg.model}' on a short window"
                if skipped:
                    sent["skipped"] = skipped
                text = self._long.text(wav_path, window_s=self.cfg.window_s or 10.0,
                                       beam_size=1)
            else:
                text = self._canary(audio)
        except Exception as e:
            debug.model("stt", sent, error=e, seconds=time.monotonic() - t0)
            raise
        return _finish(sent, t0, text)


    # After a refusal or a timeout a service is not asked again for this long, so a service
    # that is down costs one wait and not one per recording. A missing or rejected key does
    # not fix itself: that service rests for the run.
    REST_S = 60.0

    def _ask(self, name: str, online, wav_path, skipped: list) -> str | None:
        """The service's text for a long recording, or None when it is to be passed over."""
        now = time.monotonic()
        if now < self._rest_until.get(name, 0.0):
            skipped.append(f"{name}: resting after a failure")
            return None
        if not cloud.is_online():
            skipped.append(f"{name}: offline")
            return None
        try:
            return online.transcribe(wav_path)
        except cloud.CloudMisconfigured as e:
            self._rest_until[name] = float("inf")
            skipped.append(f"{name}: {e}"[:120])
        except cloud.CloudUnavailable as e:
            self._rest_until[name] = now + self.REST_S
            skipped.append(f"{name}: {e}"[:120])
            if online.profile["base_url"]:
                # The online flag speaks for the default host; this was another service's
                # failure, and the stages after this one must not read it as "no internet".
                cloud.mark_online()
        return None


def _onnx(folder: Path, stem: str) -> Path:
    """`stem.int8.onnx` when the folder has it, else `stem.onnx`."""
    quantized = folder / f"{stem}.int8.onnx"
    return quantized if quantized.exists() else folder / f"{stem}.onnx"


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
    choices = ", ".join(["local", "canary", *STT_PROFILES])
    return f"unknown STT backend {backend!r} (choices: {choices})"


def make_transcriber(cfg: STTConfig) -> Transcriber | CanaryTranscriber | CloudTranscriber:
    """The transcriber for `cfg.backend`: local faster-whisper, Canary or a cloud profile."""
    if cfg.backend == "local":
        return Transcriber(cfg)
    if cfg.backend == "canary":
        return CanaryTranscriber(cfg)
    if cfg.backend in STT_PROFILES:
        return CloudTranscriber(cfg)
    raise ValueError(_unknown_backend(cfg.backend))
