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
    """Loudness -> openness fraction -> attack-time motor pulses for the mouth.

    The mouth is driven by *time*, not by held PWM magnitude: a DC motor's travel ≈ how
    long it runs at a fixed drive speed. So loudness maps to an openness fraction (0..1,
    the same value the on-screen fish renders), and that fraction maps to a drive duration
    via the measured attack-time curves below. We emit firmware `MOUTH <pwm> <ms>` timed
    pulses at full drive. Polarity (firmware): + = open, - = close, 0 = rest.

    Calibration (measured on the real fish, openness_fraction -> ms to reach it under drive):
    opening saturates at open_pwm and takes longer than closing (spring/gravity assist close).
    Mid-range anchors are interpolated linearly; refine on hardware.
    """
    # Drive magnitudes. open_pwm = the PWM that reaches full mechanical travel (255 gives
    # no more and is no faster). close_pwm = the close-stroke drive the close_curve was timed at.
    open_pwm: int = 238
    close_pwm: int = -200
    # Below the loudness threshold the jaw returns to rest (fully closed).
    rest_pwm: int = 0
    # Attack-time calibration: (openness_fraction, ms) anchors, ascending by openness.
    open_curve: tuple[tuple[float, int], ...] = (
        (0.00, 0), (0.01, 1), (0.05, 2), (0.08, 4), (0.15, 14), (1.00, 104),
    )
    close_curve: tuple[tuple[float, int], ...] = (
        (0.00, 0), (0.05, 4), (0.08, 14), (1.00, 74),
    )
    # Frame analysis
    frame_ms: float = 15.0          # envelope hop size
    noise_floor: float = 0.04       # normalized RMS below this counts as silence
    # Attack/release smoothing (0..1 per frame): higher attack = snappier open.
    attack: float = 0.6
    release: float = 0.35


@dataclass
class GestureConfig:
    """Neck/tail motion while the fish talks (firmware timed chains).

    Text-driven when the spoken text is known (the normal speech path): the head swings OUT
    near the start of each spoken clause and HOLDS there (motor off, no return pair) — for
    eloquence it sometimes stays out across a sentence boundary — then RETURNS home on
    sentence-ending punctuation and always at the end of the phrase. The tail flaps on word
    boundaries for liveliness. Character position is mapped linearly to audio time (we have no
    word-level timing from the TTS). Falls back to random Poisson gestures when no text is
    available (e.g. performing a raw WAV).

    Command bodies are firmware "<pwm> <ms> [<pwm> <ms> ...]" chains; + = out, - = return.
    """
    enabled: bool = True

    # --- text-driven (preferred path) ---
    # NECK is split into separate out/return strokes so the head can hold out between them.
    # Bigger pwm/ms => more travel ("move more").
    neck_out: str = "230 650"            # swing out and hold (no return pair)
    neck_return: str = "-200 560"        # bring the head home
    neck_nudge: str = "180 240"          # small extra out-push on some in-clause words
    neck_nudge_prob: float = 0.3         # chance an in-clause word boundary gets a nudge
    neck_hold_over_prob: float = 0.45    # chance the head stays out past a sentence end
    tail_flap: str = "210 230 -210 210"  # a quick flap (out+back) on word boundaries
    tail_flap_prob: float = 0.7          # chance a given word boundary triggers a flap
    sentence_end: str = ".!?…"           # characters that bring the head home
    text_min_gap_s: float = 0.32         # per-channel rate cap for nudges/flaps (keeps motors sane)

    # --- random fallback (no text available) ---
    neck_mean_gap_s: float = 3.0
    tail_mean_gap_s: float = 2.2
    min_gap_s: float = 1.2               # minimum gap so random gestures don't pile up
    # Candidate self-contained chains (out+return); one is picked at random.
    neck_chains: tuple[str, ...] = (
        "230 650 -200 560",
        "190 720 -190 520",
        "240 480 -210 460",
    )
    tail_chains: tuple[str, ...] = (
        "210 230 -210 210",
        "220 200 -200 200 200 200 -200 200",
        "190 320 -190 300",
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
        "welcome": "¡Hola pendejos! Llevenme al río y ponganme algo en el ojo, no sean culero",
        "goodbye": "¡Adiós! Me voy a la verga!",
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
