"""Speech-to-text: prompt-echo filter, backend dispatch and the cloud request shape (no network)."""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from fish_brain import cloud, stt
from fish_brain.config import STT_PROFILES, STTConfig

PROMPT = "Conversación en español mexicano con un pez animatrónico parlante."


class FakeClient:
    """Stands in for the OpenAI SDK client; records the transcription request."""

    def __init__(self, text: str = "hola pez"):
        self.text = text
        self.calls: list[dict] = []
        self.audio = SimpleNamespace(transcriptions=SimpleNamespace(create=self._create))

    def _create(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(text=self.text)


@pytest.fixture
def fake(monkeypatch):
    client = FakeClient()
    seen: list[tuple] = []

    def fake_client(base_url="", api_key_env="OPENAI_API_KEY", timeout_s=None):
        seen.append((base_url, api_key_env))
        return client

    monkeypatch.setattr(cloud, "client", fake_client)
    monkeypatch.setattr(cloud, "is_online", lambda: True)
    client.seen = seen
    return client


def cfg(**kw) -> STTConfig:
    base = dict(backend="openai", cloud_model="", prompt=PROMPT, keywords=(), language="es")
    base.update(kw)
    return STTConfig(**base)


# --- prompt echo -------------------------------------------------------------------------
@pytest.mark.parametrize("text", ["Sí.", "hola", "no", "pez", "", "con un pez",
                                  "Hablo español mexicano con un amigo."])
def test_real_speech_is_not_an_echo(text):
    assert stt._is_prompt_echo(text, PROMPT) is False


@pytest.mark.parametrize("text", [
    PROMPT,
    "conversacion en espanol mexicano con un pez animatronico parlante",
    "CONVERSACIÓN, en español mexicano... con un pez animatrónico parlante!",
    "español mexicano con un pez animatrónico",            # 6 of 9 words, contiguous
    "Eh, conversación en español mexicano con un pez.",    # echo with a stray word in front
])
def test_prompt_read_back_is_an_echo(text):
    assert stt._is_prompt_echo(text, PROMPT) is True


def test_echo_needs_four_words_and_most_of_the_prompt():
    assert stt._is_prompt_echo("español mexicano con un", PROMPT) is False   # 4 of 9 < 60 %
    assert stt._is_prompt_echo("un pez", "un pez") is True                  # exact match
    assert stt._is_prompt_echo("un pez", "es un pez") is False              # short prompt
    assert stt._is_prompt_echo("hola", "") is False


def test_long_sentence_quoting_the_prompt_is_speech():
    said = ("Oye Billy, ayer en la feria un señor me dijo que esto era una conversación en "
            "español mexicano con un pez animatrónico parlante y yo no le creí nada, "
            "¿tú qué opinas?")
    assert stt._is_prompt_echo(said, PROMPT) is False


# --- dispatch ----------------------------------------------------------------------------
def test_make_transcriber_dispatch():
    assert isinstance(stt.make_transcriber(cfg(backend="local")), stt.Transcriber)
    for name in STT_PROFILES:
        t = stt.make_transcriber(cfg(backend=name))
        assert isinstance(t, stt.CloudTranscriber)
        assert t.model == STT_PROFILES[name]["model"]
        assert t.ensure_loaded() is None


def test_make_transcriber_unknown_backend():
    with pytest.raises(ValueError) as e:
        stt.make_transcriber(cfg(backend="nope"))
    for choice in ("local", *STT_PROFILES):
        assert choice in str(e.value)


# --- cloud request shape -----------------------------------------------------------------
def test_gpt_transcribe_request(fake):
    t = stt.CloudTranscriber(cfg(backend="openai", keywords=("Billy", "Jorge")))
    assert t.transcribe("/tmp/x.wav") == "hola pez"
    assert fake.seen == [("", "OPENAI_API_KEY")]
    assert fake.calls == [{
        "file": Path("/tmp/x.wav"), "model": "gpt-transcribe", "prompt": PROMPT,
        "extra_body": {"languages": ["es"], "keywords": ["Billy", "Jorge"]},
    }]


def test_gpt_transcribe_without_keywords_or_prompt(fake):
    stt.CloudTranscriber(cfg(backend="openai", prompt="")).transcribe("x.wav")
    assert fake.calls == [{"file": Path("x.wav"), "model": "gpt-transcribe",
                           "extra_body": {"languages": ["es"]}}]


def test_whisper_request(fake):
    t = stt.CloudTranscriber(cfg(backend="groq", keywords=("Billy",)))
    t.transcribe(Path("x.wav"))
    assert fake.seen == [("https://api.groq.com/openai/v1", "GROQ_API_KEY")]
    assert fake.calls == [{"file": Path("x.wav"), "model": "whisper-large-v3-turbo",
                           "prompt": PROMPT, "language": "es"}]


def test_cloud_model_override_picks_the_request_shape(fake):
    stt.CloudTranscriber(cfg(backend="openai", cloud_model="whisper-1")).transcribe("x.wav")
    assert fake.calls[0]["model"] == "whisper-1"
    assert fake.calls[0]["language"] == "es" and "extra_body" not in fake.calls[0]


@pytest.mark.parametrize("text", [PROMPT, "Subtítulos por la comunidad de Amara.org", "  "])
def test_junk_transcripts_come_back_empty(fake, text):
    fake.text = text
    assert stt.CloudTranscriber(cfg()).transcribe("x.wav") == ""


def test_short_real_words_survive(fake):
    fake.text = " Sí. "
    assert stt.CloudTranscriber(cfg()).transcribe("x.wav") == "Sí."


def test_offline_raises_before_any_call(fake, monkeypatch):
    monkeypatch.setattr(cloud, "is_online", lambda: False)
    with pytest.raises(cloud.CloudUnavailable, match="offline"):
        stt.CloudTranscriber(cfg()).transcribe("x.wav")
    assert fake.calls == [] and fake.seen == []
