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


# --- the short encoder window (local) ----------------------------------------------------
@pytest.mark.parametrize("frames, window_s, tail_s, want", [
    (300, 10.0, 3.0, 1000),      # a 3 s clip: the floor
    (900, 10.0, 3.0, 1200),      # 9 s: the clip and its tail
    (2700, 10.0, 3.0, 3000),     # just fits the model's 30 s
    (2701, 10.0, 3.0, None),     # does not: the stock path
    (300, 0.0, 0.0, 300),
])
def test_window_frames(frames, window_s, tail_s, want):
    assert stt._window_frames(frames, window_s, tail_s) == want


class FakeWhisper:
    """The parts of faster-whisper's WhisperModel the window path calls."""
    max_length = 448
    tokens, score, no_speech = [7, 8], -0.2, 0.01

    def __init__(self):
        np = pytest.importorskip("numpy")
        self.np = np
        self.encoded: list[tuple] = []
        self.generated: list[dict] = []
        self.stock: list[dict] = []
        # one frame per 160 samples, plus the extra frame the real extractor returns
        self.feature_extractor = type("FE", (), {
            "time_per_frame": 0.01,
            "__call__": lambda _s, audio: np.ones((80, len(audio) // 160 + 1), np.float32)})()
        self.model = SimpleNamespace(is_multilingual=True, generate=self._generate)

    def encode(self, features):
        self.encoded.append(features.shape)
        return "ENC"

    def get_prompt(self, tokenizer, previous, without_timestamps=False):
        assert previous == [] and without_timestamps is True
        return [1, 2, 3, 4]

    def _generate(self, enc, prompts, **kw):
        self.generated.append({"enc": enc, "prompts": prompts, **kw})
        return [SimpleNamespace(sequences_ids=[self.tokens], scores=[self.score],
                                no_speech_prob=self.no_speech)]

    def transcribe(self, audio, **kw):
        self.stock.append(kw)
        return [SimpleNamespace(text=" texto largo ")], None


@pytest.fixture
def whisper(monkeypatch):
    pytest.importorskip("faster_whisper")
    monkeypatch.setattr(stt, "_whisper_tokenizer", lambda model, language: SimpleNamespace(
        decode=lambda tokens: f" {language}:{tokens} "))
    return FakeWhisper()


def test_window_pads_a_short_clip_to_the_floor_only(whisper):
    audio = whisper.np.zeros(3 * 16000, whisper.np.float32)
    text = stt.transcribe_window(whisper, audio, window_s=10.0, tail_s=3.0, vad=False)
    assert text == "es:[7, 8]"
    assert whisper.encoded == [(80, 1000)]
    # 3 s of speech: 24 + 12 a second new tokens after the prompt's 4
    assert whisper.generated == [{"enc": "ENC", "prompts": [[1, 2, 3, 4]],
                                  "beam_size": 1, "max_length": 64,
                                  "return_scores": True, "return_no_speech_prob": True}]
    assert whisper.stock == []


def test_window_grows_with_the_clip_and_bounds_the_reply(whisper):
    audio = whisper.np.zeros(9 * 16000, whisper.np.float32)
    stt.transcribe_window(whisper, audio, window_s=10.0, tail_s=3.0, beam_size=5,
                          max_new_tokens=96, vad=False)
    assert whisper.encoded == [(80, 1200)]
    assert whisper.generated[0]["beam_size"] == 5
    assert whisper.generated[0]["max_length"] == 100       # the prompt's 4 and 96 new


def test_a_clip_past_thirty_seconds_goes_the_stock_way(whisper):
    audio = whisper.np.zeros(28 * 16000, whisper.np.float32)
    text = stt.transcribe_window(whisper, audio, tail_s=3.0, vad=False)
    assert text == "texto largo"
    assert whisper.encoded == [] and whisper.stock == [{"language": "es", "beam_size": 1}]


def test_window_returns_nothing_for_silence(whisper):
    audio = whisper.np.zeros(2 * 16000, whisper.np.float32)
    assert stt.transcribe_window(whisper, audio) == ""        # the real VAD: no speech
    assert whisper.encoded == [] and whisper.stock == []


def test_a_reply_stuck_on_one_phrase_goes_the_stock_way(whisper, monkeypatch):
    monkeypatch.setattr(stt, "_whisper_tokenizer", lambda model, language: SimpleNamespace(
        decode=lambda tokens: "no, " * 40))
    audio = whisper.np.zeros(2 * 16000, whisper.np.float32)
    whisper.tokens = [7] * 48                    # ran to the limit of a 2 s clip
    assert stt.transcribe_window(whisper, audio, vad=False) == "texto largo"
    assert len(whisper.encoded) == 1 and len(whisper.stock) == 1


def test_a_finished_reply_that_repeats_itself_is_kept(whisper, monkeypatch):
    laugh = "ja ja ja ja ja ja ja ja ja ja ja ja"
    monkeypatch.setattr(stt, "_whisper_tokenizer", lambda model, language: SimpleNamespace(
        decode=lambda tokens: laugh))
    audio = whisper.np.zeros(4 * 16000, whisper.np.float32)
    whisper.tokens = [7] * 12                    # ended on its own, well under the limit
    assert stt._repeats(laugh)
    assert stt.transcribe_window(whisper, audio, vad=False) == laugh and whisper.stock == []


def test_noise_the_model_calls_no_speech_comes_back_empty(whisper):
    audio = whisper.np.zeros(9 * 16000, whisper.np.float32)
    whisper.no_speech, whisper.score = 0.76, -5.86
    assert stt.transcribe_window(whisper, audio, vad=False) == ""
    whisper.score = -0.2                         # sure of its words: speech after all
    assert stt.transcribe_window(whisper, audio, vad=False) == "es:[7, 8]"


@pytest.mark.parametrize("text, stuck", [
    ("no, " * 40, True), ("Sí.", False), ("", False), ("no, no, no", False),
    ("Vengo con mis cuates de Iztapalapa y nos tardamos como dos horas en el metro.", False),
])
def test_repeats(text, stuck):
    assert stt._repeats(text) is stuck


# --- the local transcriber's settings ------------------------------------------------------
def test_local_passes_the_beam_and_uses_the_window_when_set(monkeypatch, whisper, tmp_path):
    wav = tmp_path / "a.wav"
    _wav(wav, 3.0)
    t = stt.Transcriber(cfg(backend="local"))
    t._model = whisper
    assert t.cfg.beam_size == 5 and t.cfg.window_s == 0.0       # the laptop's defaults
    assert t.transcribe(wav) == "texto largo"
    assert whisper.stock == [{"language": "es", "vad_filter": True, "beam_size": 5}]
    seen = []
    monkeypatch.setattr(stt, "transcribe_window",
                        lambda model, audio, **kw: seen.append((len(audio), kw)) or "hola")
    t.cfg.window_s, t.cfg.beam_size = 10.0, 1
    assert t.transcribe(wav) == "hola"
    assert seen == [(48000, {"language": "es", "window_s": 10.0, "beam_size": 1})]


def _wav(path, seconds, rate=16000):
    import wave
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"\x10\x00" * int(seconds * rate))


# --- canary ----------------------------------------------------------------------------------
class FakeRecognizer:
    def __init__(self):
        self.heard: list[tuple] = []

    def create_stream(self):
        heard = self.heard
        return SimpleNamespace(accept_waveform=lambda rate, x: heard.append((rate, len(x), x)),
                               result=SimpleNamespace(text=" Sí, simón. "))

    def decode_stream(self, stream):
        pass


@pytest.fixture
def canary_dir(tmp_path, monkeypatch):
    for name in ("encoder.int8.onnx", "decoder.int8.onnx", "tokens.txt"):
        (tmp_path / name).write_bytes(b"x")
    import importlib.util
    real = importlib.util.find_spec
    monkeypatch.setattr(importlib.util, "find_spec",
                        lambda name, *a: object() if name == "sherpa_onnx" else real(name, *a))
    return tmp_path


def test_canary_is_dispatched_and_says_what_it_lacks(canary_dir, monkeypatch):
    t = stt.make_transcriber(cfg(backend="canary", model_dir=str(canary_dir)))
    assert isinstance(t, stt.CanaryTranscriber)
    assert t._paths["encoder"].name == "encoder.int8.onnx"
    with pytest.raises(ValueError, match="FISH_STT_MODEL_DIR"):
        stt.make_transcriber(cfg(backend="canary", model_dir=""))
    (canary_dir / "tokens.txt").unlink()
    with pytest.raises(ValueError, match="tokens.txt"):
        stt.make_transcriber(cfg(backend="canary", model_dir=str(canary_dir)))


def test_canary_without_its_package_is_a_setup_error(canary_dir, monkeypatch):
    import importlib.util
    monkeypatch.setattr(importlib.util, "find_spec", lambda name, *a: None)
    with pytest.raises(RuntimeError, match="sherpa-onnx"):
        stt.make_transcriber(cfg(backend="canary", model_dir=str(canary_dir)))


def test_canary_hears_the_clip_with_silence_around_it(canary_dir, tmp_path):
    pytest.importorskip("numpy")
    wav = tmp_path / "turn.wav"
    _wav(wav, 2.0)
    t = stt.CanaryTranscriber(cfg(backend="canary", model_dir=str(canary_dir)))
    t._recognizer = FakeRecognizer()
    assert t.transcribe(wav) == "Sí, simón."
    rate, n, x = t._recognizer.heard[0]
    assert (rate, n) == (16000, 4 * 16000)                  # 1 s, the clip, 1 s
    assert not x[:16000].any() and not x[-16000:].any() and x[16000:48000].all()


def test_canary_hands_a_long_recording_to_the_local_model(canary_dir, tmp_path):
    pytest.importorskip("numpy")
    wav = tmp_path / "long.wav"
    _wav(wav, 12.0)
    t = stt.CanaryTranscriber(cfg(backend="canary", model_dir=str(canary_dir)))
    t._recognizer = FakeRecognizer()
    asked = []
    t._long.text = lambda path, **kw: asked.append(kw) or "una frase larga"
    assert t.transcribe(wav) == "una frase larga"
    assert asked == [{"window_s": 10.0, "beam_size": 1}] and t._recognizer.heard == []


def test_canary_drops_the_canned_phrases(canary_dir, tmp_path):
    pytest.importorskip("numpy")
    wav = tmp_path / "turn.wav"
    _wav(wav, 1.0)
    t = stt.CanaryTranscriber(cfg(backend="canary", model_dir=str(canary_dir)))
    t._recognizer = SimpleNamespace(
        create_stream=lambda: SimpleNamespace(
            accept_waveform=lambda rate, x: None,
            result=SimpleNamespace(text="Subtítulos realizados por la comunidad de Amara.org")),
        decode_stream=lambda stream: None)
    assert t.transcribe(wav) == ""


def test_canary_loads_the_long_recordings_model_too(canary_dir):
    t = stt.CanaryTranscriber(cfg(backend="canary", model_dir=str(canary_dir)))
    t._recognizer, loaded = FakeRecognizer(), []
    t._long.ensure_loaded = lambda: loaded.append("local")
    t.ensure_loaded()
    assert loaded == ["local"] and t.cfg.canary_long_s == 6.0


# --- canary: the long recordings go online first ---------------------------------------------
class FakeOnline:
    """Stands in for a CloudTranscriber of the long route."""
    profile = {"base_url": ""}

    def __init__(self, answer="texto de la nube", error=None):
        self.answer, self.error, self.calls = answer, error, []

    def transcribe(self, wav_path):
        self.calls.append(str(wav_path))
        if self.error:
            raise self.error
        return self.answer


def long_canary(canary_dir, tmp_path, seconds=7.0, long_online=("groq", "openai"), **kw):
    wav = tmp_path / "turn.wav"
    _wav(wav, seconds)
    t = stt.CanaryTranscriber(cfg(backend="canary", model_dir=str(canary_dir),
                                  long_online=long_online, **kw))
    t._recognizer = FakeRecognizer()
    local = []
    t._long.text = lambda path, **kw: local.append(kw) or "texto local"
    return t, wav, local


def test_a_recording_over_six_seconds_goes_to_the_first_service(canary_dir, tmp_path):
    pytest.importorskip("numpy")
    t, wav, local = long_canary(canary_dir, tmp_path, cloud_model="gpt-transcribe")
    assert [name for name, _ in t._online] == ["groq", "openai"]
    # each service's own model: an override meant for another backend does not leak in
    assert t._online[0][1].model == "whisper-large-v3-turbo"
    groq, openai = FakeOnline(), FakeOnline("otra")
    t._online = [("groq", groq), ("openai", openai)]
    assert t.transcribe(wav) == "texto de la nube"
    assert groq.calls == [str(wav)] and openai.calls == [] and local == []
    assert t._recognizer.heard == []


def test_a_refusal_falls_to_the_next_service_and_then_to_the_board(canary_dir, tmp_path):
    pytest.importorskip("numpy")
    t, wav, local = long_canary(canary_dir, tmp_path)
    groq = FakeOnline(error=cloud.CloudUnavailable("RateLimitError: 429"))
    openai = FakeOnline("de openai")
    t._online = [("groq", groq), ("openai", openai)]
    assert t.transcribe(wav) == "de openai" and local == []
    openai.error = cloud.CloudMisconfigured("OPENAI_API_KEY is not set")
    assert t.transcribe(wav) == "texto local"
    assert local == [{"window_s": 10.0, "beam_size": 1}]
    # groq rests after its refusal and openai for the run: neither is asked again
    assert len(groq.calls) == 1 and len(openai.calls) == 2
    groq.error = openai.error = None
    assert t.transcribe(wav) == "texto local" and len(groq.calls) == 1


def test_a_rested_service_is_asked_again_and_another_services_timeout_is_not_no_internet(
        canary_dir, tmp_path, monkeypatch):
    pytest.importorskip("numpy")
    t, wav, local = long_canary(canary_dir, tmp_path, long_online=("groq",))
    groq = FakeOnline(error=cloud.CloudUnavailable("APITimeoutError"))
    groq.profile = {"base_url": "https://api.groq.com/openai/v1"}
    t._online = [("groq", groq)]
    monkeypatch.setattr(cloud, "_probe_started", True)
    monkeypatch.setattr(cloud, "_online", True)
    real = groq.transcribe

    def timing_out(path):
        cloud.mark_offline()                     # what the cloud layer does on a timeout
        return real(path)
    groq.transcribe = timing_out
    assert t.transcribe(wav) == "texto local"
    assert cloud.is_online() is True             # the stages after this one still try
    groq.error, groq.transcribe = None, real
    t._rest_until["groq"] = 0.0                  # the rest is over
    assert t.transcribe(wav) == "texto de la nube"


def test_offline_the_long_recording_stays_on_the_board(canary_dir, tmp_path, monkeypatch):
    pytest.importorskip("numpy")
    t, wav, local = long_canary(canary_dir, tmp_path, long_online=("groq",))
    monkeypatch.setattr(cloud, "is_online", lambda: False)
    monkeypatch.setattr(cloud, "client", lambda *a, **k: pytest.fail("no call when offline"))
    assert t.transcribe(wav) == "texto local" and len(local) == 1


def test_a_short_recording_never_leaves_the_board(canary_dir, tmp_path):
    pytest.importorskip("numpy")
    t, wav, local = long_canary(canary_dir, tmp_path, seconds=6.0)
    groq = FakeOnline()
    t._online = [("groq", groq)]
    assert t.transcribe(wav) == "Sí, simón."
    assert groq.calls == [] and local == [] and len(t._recognizer.heard) == 1


def test_no_long_route_is_the_board_alone_and_a_wrong_name_is_refused(canary_dir, tmp_path):
    pytest.importorskip("numpy")
    t, wav, local = long_canary(canary_dir, tmp_path, long_online=())
    assert t._online == [] and t.transcribe(wav) == "texto local"
    with pytest.raises(ValueError, match="FISH_STT_LONG.*'grok'"):
        stt.CanaryTranscriber(cfg(backend="canary", model_dir=str(canary_dir),
                                  long_online=("grok",)))


def test_loading_canary_also_builds_the_online_clients(canary_dir, tmp_path, monkeypatch):
    t, _wav_path, _local = long_canary(canary_dir, tmp_path, long_online=("groq",))
    t._long.ensure_loaded = lambda: None
    built = []
    monkeypatch.setattr(cloud, "client", lambda base_url="", api_key_env="", **k:
                        built.append((base_url, api_key_env)))
    t.ensure_loaded()
    assert built == [("https://api.groq.com/openai/v1", "GROQ_API_KEY")]
    monkeypatch.setattr(cloud, "client", lambda *a, **k: 1 / 0)      # a failure here is not fatal
    t.ensure_loaded()
