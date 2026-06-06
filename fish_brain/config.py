"""Central configuration for fish_brain.

All tunables live here. Hardware-ish values (PWM ranges, sync offset) are meant to be
calibrated on the real fish — see CLAUDE.md "Calibration". A few values can be overridden
from the environment / .env so you don't have to edit code for the common ones.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


def _env(name: str, default: str) -> str:
    return os.environ.get(name, default)


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ[name])
    except (KeyError, ValueError):
        return default


@dataclass
class SerialConfig:
    port: str = field(default_factory=lambda: _env("FISH_SERIAL_PORT", "/dev/ttyACM0"))
    baud: int = 115200
    # Don't send mouth updates faster than this; protects the firmware's per-loop
    # single-line reader and keeps the link from flooding.
    max_cmd_hz: float = 33.0
    # Newline the firmware splits on (main.cpp: readStringUntil('\n')).
    newline: bytes = b"\n"


@dataclass
class MouthConfig:
    """Proportional loudness -> signed PWM mapping for the mouth.

    Polarity (firmware): + = open, - = close, 0 = rest. We stream immediate `MOUTH <n>`
    which holds until the next command, so silence -> `MOUTH 0`.
    """
    # PWM applied at peak loudness (fully open). Mirror Big_mouth Config.h (~220).
    open_pwm: int = 220
    # PWM at/just above the speech threshold (mouth barely cracks open).
    min_open_pwm: int = 70
    # Below the loudness threshold we send rest_pwm (closed). 0 = coast closed.
    rest_pwm: int = 0
    # Frame analysis
    frame_ms: float = 15.0          # envelope hop size
    noise_floor: float = 0.04       # normalized RMS below this counts as silence
    # Attack/release smoothing (0..1 per frame): higher attack = snappier open.
    attack: float = 0.6
    release: float = 0.35


@dataclass
class GestureConfig:
    """Random neck/tail motion while the fish talks (firmware timed chains)."""
    enabled: bool = True
    # Mean seconds between gestures on each channel (Poisson-ish).
    neck_mean_gap_s: float = 3.0
    tail_mean_gap_s: float = 2.2
    # Minimum gap so gestures don't pile up.
    min_gap_s: float = 1.2
    # Candidate chains; one is picked at random. Each is a firmware command body
    # (channel is prepended by the generator): "<pwm> <ms> <pwm> <ms> ...".
    neck_chains: tuple[str, ...] = (
        "180 450 -180 350",
        "150 600 -160 400",
        "200 300 -180 300",
    )
    tail_chains: tuple[str, ...] = (
        "200 250 -200 250",
        "220 200 -200 200 200 200 -200 200",
        "180 300 -180 300",
    )


@dataclass
class ConductorConfig:
    # Shift the whole command stream vs audio to cover output latency + motor lag.
    # Positive = send commands earlier than the audio sample they map to.
    sync_offset_ms: float = 0.0


@dataclass
class TTSConfig:
    loq_bin: str = field(default_factory=lambda: _env("FISH_LOQ_BIN", "loq"))
    sample_rate: int = 22050        # passed to loq -r; envelope reads the actual WAV rate
    warm_on_start: bool = True      # `loq --start` to warm the daemon at boot


@dataclass
class STTConfig:
    model: str = field(default_factory=lambda: _env("FISH_STT_MODEL", "small"))
    language: str = "es"
    device: str = "cpu"
    compute_type: str = "int8"      # CPU-friendly faster-whisper setting


@dataclass
class LLMConfig:
    model: str = field(default_factory=lambda: _env("FISH_LLM_MODEL", "gpt-4o-mini"))
    max_history_turns: int = 8      # user+assistant pairs kept for context
    temperature: float = 0.8
    system_prompt: str = (
        "Eres un pez animatrónico parlante (un Big Mouth Billy Bass) con mucha "
        "personalidad: simpático, bromista y un poco sarcástico. Respondes en español "
        "mexicano, en frases cortas y naturales para ser habladas en voz alta. Evita "
        "listas, emojis y texto que no se pueda pronunciar."
    )


@dataclass
class CannedConfig:
    """Pre-rendered fixed phrases (welcome/goodbye/etc.) cached as WAVs.

    Phrases are synthesized once via `loq` and cached on disk keyed by a hash of the text,
    so they replay instantly and skip the LLM round-trip. The cache auto-invalidates when a
    phrase's wording changes.
    """
    enabled: bool = True
    cache_dir: Path = field(default_factory=lambda: Path(
        os.environ.get("XDG_CACHE_HOME", str(Path.home() / ".cache"))) / "fish_brain" / "canned")
    # Which phrase plays at startup / on exit. Empty string disables that hook.
    welcome: str = "welcome"
    goodbye: str = "goodbye"
    # name -> Spanish text spoken by the fish.
    phrases: dict[str, str] = field(default_factory=lambda: {
        "welcome": "¡Hola! Soy el pez parlante. Mantén la tecla para hablar conmigo.",
        "goodbye": "¡Adiós! Nos vemos en el estanque.",
    })


@dataclass
class VizConfig:
    """On-screen browser fish (fallback/debug view). See viz.py + web/."""
    host: str = "127.0.0.1"
    port: int = 8723


@dataclass
class PTTConfig:
    # Key held to record. 'space' by default; see ptt.py for the listener.
    hold_key: str = "space"
    samplerate: int = 16000         # whisper wants 16 kHz mono
    channels: int = 1
    # Which microphone to record from. Prefer `source`: a PipeWire/PulseAudio source NAME
    # (e.g. "alsa_input.usb-RedOctane_...mono-fallback"). It's stable across reboots/replug and
    # records through the sound server (proper gain + 16 kHz resampling), unlike a raw ALSA
    # device. `device` is a fallback for systems without PipeWire/Pulse: a sounddevice index
    # (unstable!) or None for the system default. Both are settable live via the web mic picker.
    source: str | None = None
    device: int | None = None
    # Below this RMS a recording is treated as silence and skipped (Whisper hallucinates
    # phrases like "Subtítulos por la comunidad de Amara.org" on silent input).
    silence_rms: float = 0.005


@dataclass
class Config:
    serial: SerialConfig = field(default_factory=SerialConfig)
    mouth: MouthConfig = field(default_factory=MouthConfig)
    gesture: GestureConfig = field(default_factory=GestureConfig)
    conductor: ConductorConfig = field(default_factory=ConductorConfig)
    tts: TTSConfig = field(default_factory=TTSConfig)
    stt: STTConfig = field(default_factory=STTConfig)
    llm: LLMConfig = field(default_factory=LLMConfig)
    ptt: PTTConfig = field(default_factory=PTTConfig)
    canned: CannedConfig = field(default_factory=CannedConfig)
    viz: VizConfig = field(default_factory=VizConfig)


def load() -> Config:
    """Build the config (env/.env already loaded by the entry point)."""
    return Config()
