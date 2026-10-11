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
    # An empty value means "not set": a blanked line in .env falls back to the default.
    return os.environ.get(name, "").strip() or default


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ[name])
    except (KeyError, ValueError):
        return default


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ[name])
    except (KeyError, ValueError):
        return default


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_list(name: str) -> tuple[str, ...]:
    return tuple(x.strip() for x in os.environ.get(name, "").split(",") if x.strip())


def _env_opt(name: str) -> str | None:
    return os.environ.get(name, "").strip() or None


@dataclass
class SerialConfig:
    port: str = field(default_factory=lambda: _env("FISH_SERIAL_PORT", "/dev/ttyACM0"))
    baud: int = 115200
    # Don't send mouth updates faster than this; protects the firmware's per-loop
    # single-line reader and keeps the link from flooding.
    max_cmd_hz: float = 33.0
    # Newline the firmware splits on (main.cpp reads byte by byte; '\n' or '\r' ends a line).
    newline: bytes = b"\n"
    # How commands reach the motor MCU: "serial" (pyserial on `port`) or "bridge"
    # (MessagePack-RPC through the UNO Q's arduino-router to a Bridge sketch).
    transport: str = field(default_factory=lambda: _env("FISH_SERIAL_TRANSPORT", "serial"))
    # False = keep talking when the link can't open (voice-only, retried in the background).
    required: bool = field(default_factory=lambda: _env_bool("FISH_SERIAL_REQUIRED", True))
    # UNO Q only: the arduino-router daemon owns /dev/ttyHS1. A unix socket path or tcp://host:port.
    router_socket: str = field(
        default_factory=lambda: _env("FISH_ROUTER_SOCKET", "/var/run/arduino-router.sock"))
    # Ask the router to let go of the port ($/serial/close) before opening a /dev/ttyHS* port.
    release_router: bool = field(default_factory=lambda: _env_bool("FISH_ROUTER_RELEASE", True))
    bridge_method: str = field(default_factory=lambda: _env("FISH_BRIDGE_METHOD", "fish_cmd"))
    bridge_ping_method: str = field(default_factory=lambda: _env("FISH_BRIDGE_PING", "fish_ping"))
    # A file that records every line written to the MCU and every byte read back. Empty = off.
    log_path: str = field(default_factory=lambda: _env("FISH_LINK_LOG", ""))


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
    backend: str = field(default_factory=lambda: _env("FISH_TTS_BACKEND", "loq"))  # loq | openai
    loq_bin: str = field(default_factory=lambda: _env("FISH_LOQ_BIN", "loq"))
    sample_rate: int = 22050        # passed to loq -r; envelope reads the actual WAV rate
    warm_on_start: bool = True      # `loq --start` to warm the daemon at boot (loq only)
    # OpenAI speech (backend "openai"). Rendered as raw PCM and wrapped into a WAV here.
    openai_model: str = field(default_factory=lambda: _env("FISH_TTS_MODEL", "gpt-4o-mini-tts"))
    openai_voice: str = field(default_factory=lambda: _env("FISH_TTS_VOICE", "ash"))
    openai_instructions: str = field(default_factory=lambda: _env(
        "FISH_TTS_INSTRUCTIONS",
        "Voz masculina de caricatura: un pez parlante bromista y sarcástico. Español "
        "mexicano, entonación exagerada, ritmo ágil y con energía."))
    openai_pcm_rate: int = 24000    # what the API returns for response_format="pcm"


# Cloud speech-to-text services (OpenAI-compatible transcription endpoints).
STT_PROFILES: dict[str, dict] = {
    "openai": {"base_url": "", "api_key_env": "OPENAI_API_KEY", "model": "gpt-transcribe"},
    "groq": {"base_url": "https://api.groq.com/openai/v1", "api_key_env": "GROQ_API_KEY",
             "model": "whisper-large-v3-turbo"},
}


@dataclass
class STTConfig:
    # local = faster-whisper on this machine; openai | groq = upload the recording (STT_PROFILES).
    backend: str = field(default_factory=lambda: _env("FISH_STT_BACKEND", "local"))
    model: str = field(default_factory=lambda: _env("FISH_STT_MODEL", "small"))  # local model
    language: str = "es"
    device: str = "cpu"
    compute_type: str = "int8"      # CPU-friendly faster-whisper setting
    # Cloud model override; empty = the profile's model.
    cloud_model: str = field(default_factory=lambda: _env("FISH_STT_CLOUD_MODEL", ""))
    # Context sentence and literal vocabulary hints for the cloud model.
    prompt: str = field(default_factory=lambda: _env(
        "FISH_STT_PROMPT", "Conversación en español mexicano con un pez animatrónico parlante."))
    keywords: tuple[str, ...] = field(default_factory=lambda: _env_list("FISH_STT_KEYWORDS"))
    min_clip_s: float = 0.3         # shorter recordings are skipped (the cloud rejects < 0.1 s)


@dataclass
class CloudConfig:
    """Timeouts for every cloud call (STT, TTS; the LLM keeps its own read timeout)."""
    timeout_s: float = field(default_factory=lambda: _env_float("FISH_CLOUD_TIMEOUT", 10.0))
    connect_timeout_s: float = field(
        default_factory=lambda: _env_float("FISH_CLOUD_CONNECT_TIMEOUT", 3.0))
    max_retries: int = field(default_factory=lambda: _env_int("FISH_CLOUD_RETRIES", 0))
    # host:port probed in the background to know whether the internet is there.
    online_check_host: str = field(
        default_factory=lambda: _env("FISH_CLOUD_CHECK_HOST", "api.openai.com:443"))


# LLM backends you can switch between with FISH_LLM_PROFILE (or A/B with `python -m fish_brain.ab`).
# All are OpenAI-compatible, so one client serves them all. `temperature: None` = don't send it.
LLM_PROFILES: dict[str, dict] = {
    "groq": {                                   # GPT-OSS-20B on Groq: fastest
        "base_url": "https://api.groq.com/openai/v1",
        "api_key_env": "GROQ_API_KEY",
        "model": "openai/gpt-oss-20b",
        "reasoning_effort": "low",              # GPT-OSS can't go lower
        "extra_body": {"include_reasoning": False},   # Groq-only option
        "temperature": 0.8,
        "price_in": 0.075, "price_out": 0.30,   # USD per 1M tokens, for the A/B cost column
    },
    "luna": {                                   # GPT-6 Luna on OpenAI: smarter, slower
        "base_url": "",                         # empty -> api.openai.com
        "api_key_env": "OPENAI_API_KEY",
        "model": "gpt-6-luna",
        "reasoning_effort": "none",             # default is "medium"; must be explicit
        "extra_body": {},
        "temperature": None,                    # not confirmed for Luna; send only if you add it
        "price_in": 0.10, "price_out": 0.50,
    },
}


@dataclass
class LLMConfig:
    profile: str = field(default_factory=lambda: _env("FISH_LLM_PROFILE", "groq"))
    # Filled from LLM_PROFILES[profile] in __post_init__; env vars below override one field.
    base_url: str | None = None
    api_key_env: str | None = None
    model: str | None = None
    reasoning_effort: str | None = None
    extra_body: dict | None = None
    temperature: float | None = None
    price_in: float = 0.0
    price_out: float = 0.0
    max_completion_tokens: int = 400   # reasoning tokens count toward this cap too
    timeout_s: float = 8.0
    max_history_turns: int = 8      # user+assistant pairs kept for context
    # Spoken instead of crashing when the API is unreachable / errors out.
    fallback_reply: str = "¡Glub! Se me fue la señal. Pregúntame otra vez."
    system_prompt: str = (
        "Eres un pez animatrónico parlante (un Big Mouth Billy Bass) con mucha "
        "personalidad: simpático, bromista y un poco sarcástico. Respondes en español "
        "mexicano, en frases cortas y naturales para ser habladas en voz alta. Evita "
        "listas, emojis y texto que no se pueda pronunciar."
    )

    def __post_init__(self) -> None:
        if self.profile not in LLM_PROFILES:
            raise ValueError(f"FISH_LLM_PROFILE={self.profile!r}; choose one of {list(LLM_PROFILES)}")
        for key, value in LLM_PROFILES[self.profile].items():
            if getattr(self, key) in (None, 0.0):
                setattr(self, key, value)
        # Single-field overrides from .env, applied only to the profile the fish is using
        # (so an A/B run keeps the other profile as defined). Empty FISH_LLM_REASONING = don't send.
        if self.profile == _env("FISH_LLM_PROFILE", "groq"):
            self.model = os.environ.get("FISH_LLM_MODEL") or self.model
            if "FISH_LLM_REASONING" in os.environ:
                self.reasoning_effort = os.environ["FISH_LLM_REASONING"]


@dataclass
class CannedConfig:
    """Pre-rendered fixed phrases (welcome/goodbye/etc.) cached as WAVs.

    Phrases are synthesized once by the configured TTS backend and cached on disk keyed by a hash of the text,
    so they replay instantly and skip the LLM round-trip. The cache auto-invalidates when a
    phrase's wording changes.
    """
    enabled: bool = True
    cache_dir: Path = field(default_factory=lambda: Path(
        os.environ.get("XDG_CACHE_HOME", str(Path.home() / ".cache"))) / "fish_brain" / "canned")
    # Which phrase plays at startup / on exit. Empty string disables that hook.
    welcome: str = "welcome"
    goodbye: str = "goodbye"
    no_signal: str = "no_signal"    # spoken when a cloud call fails
    no_mic: str = "no_mic"          # spoken when the microphone can't be opened
    # True = greet once per boot, not on every (re)start. Marker lives in $XDG_RUNTIME_DIR.
    welcome_once: bool = field(default_factory=lambda: _env_bool("FISH_WELCOME_ONCE", False))
    # name -> Spanish text spoken by the fish.
    phrases: dict[str, str] = field(default_factory=lambda: {
        "welcome": "¡Hola pendejos! Llevenme al río y ponganme algo en el ojo, no sean culero",
        "goodbye": "¡Adiós! Me voy a la verga!",
        "no_signal": "Uy, se me fue la señal. Dame un segundo y repítemelo.",
        "no_mic": "No te escucho, revisa el micrófono.",
    })


@dataclass
class VizConfig:
    """On-screen browser fish (fallback/debug view). See viz.py + web/."""
    host: str = field(default_factory=lambda: _env("FISH_VIZ_HOST", "127.0.0.1"))
    port: int = field(default_factory=lambda: _env_int("FISH_VIZ_PORT", 8723))
    # When set, the page's POST endpoints need it (open the page as /?token=...).
    token: str = field(default_factory=lambda: _env("FISH_VIZ_TOKEN", ""))
    # True = requests from this machine itself (127.0.0.1) need no token. For a browser on
    # the board's own display, so the token never has to sit in a URL.
    trust_local: bool = field(default_factory=lambda: _env_bool("FISH_VIZ_TRUST_LOCAL", False))
    # A certificate and its key: with both set, a second, HTTPS listener on `tls_port` serves
    # the same page (a phone's microphone needs a secure context). The plain one stays.
    tls_cert: str = field(default_factory=lambda: _env("FISH_VIZ_TLS_CERT", ""))
    tls_key: str = field(default_factory=lambda: _env("FISH_VIZ_TLS_KEY", ""))
    tls_port: int = field(default_factory=lambda: _env_int("FISH_VIZ_TLS_PORT", 8724))
    # True = after the welcome the fish says the last two octets of its LAN address (only
    # when bound to 0.0.0.0, where a phone has to type it).
    say_address: bool = field(default_factory=lambda: _env_bool("FISH_SAY_ADDRESS", False))


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
    source: str | None = field(default_factory=lambda: _env_opt("FISH_MIC_SOURCE"))
    # A sounddevice index, or a device-name substring (FISH_MIC_DEVICE); None = default.
    device: int | str | None = field(default_factory=lambda: _env_opt("FISH_MIC_DEVICE"))
    # Output device for playback: index or name substring (FISH_SPEAKER_DEVICE); None = default.
    speaker: str | None = field(default_factory=lambda: _env_opt("FISH_SPEAKER_DEVICE"))
    # Push-to-talk from an input device button (python-evdev), e.g. a USB voice remote.
    # A /dev/input path, "name:<substring>", or "auto" (any node that has the key). Empty = off.
    evdev_device: str = field(default_factory=lambda: _env("FISH_PTT_DEVICE", ""))
    evdev_key: str = field(default_factory=lambda: _env("FISH_PTT_KEY", "KEY_VOICECOMMAND"))
    # hold = record while pressed; toggle = one press starts, the next stops.
    mode: str = field(default_factory=lambda: _env("FISH_PTT_MODE", "hold"))
    max_record_s: float = field(default_factory=lambda: _env_float("FISH_PTT_MAX_S", 15.0))
    grab: bool = field(default_factory=lambda: _env_bool("FISH_PTT_GRAB", False))
    # Saying salir/quit/exit ends the program (text mode always can).
    voice_quit: bool = field(default_factory=lambda: _env_bool("FISH_VOICE_QUIT", True))
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
    cloud: CloudConfig = field(default_factory=CloudConfig)
    ptt: PTTConfig = field(default_factory=PTTConfig)
    canned: CannedConfig = field(default_factory=CannedConfig)
    viz: VizConfig = field(default_factory=VizConfig)


def load() -> Config:
    """Build the config (env/.env already loaded by the entry point)."""
    return Config()
