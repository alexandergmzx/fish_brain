"""A reading turn through the conversation loop with a mock link and a fake page (no
hardware, no network, no audio)."""
from __future__ import annotations

import numpy as np
import io

import pytest

from fish_brain import ptt
from fish_brain.config import Config
from fish_brain.conversation import FishConversation
from fish_brain.reading import Reading
from fish_brain.serial_link import MockSerialLink


class FakeViz:
    """What the loop needs from the page: an inbox that yields one item, and the pushes."""

    def __init__(self, item):
        self._items = [item]
        self.listening = []
        self.readings = []
        self.transcripts = []
        self.pages = 0                 # pages with a microphone ready (mic_pages)
        self.relayed = []

    def take_inbox(self):
        return self._items.pop(0) if self._items else None

    def set_listening(self, flag):
        self.listening.append(bool(flag))

    def push_reading(self, stage, **fields):
        self.readings.append(stage)

    def push_transcript(self, text, role):
        self.transcripts.append((role, text))

    def push_level(self, rms):
        pass

    def ptt_source(self):
        return ptt.ButtonSource(lambda: False, name="web")

    def wait_enabled(self):
        return False

    def mic_pages(self):
        return self.pages

    def relay_ptt(self, held):
        self.relayed.append(bool(held))


class FakeLLM:
    def __init__(self):
        self.extra_rules = ""
        self.remembered = []
        self.replies = []
        self.resets = 0
        self.last_error = None

    def reset(self):
        self.resets += 1
        self.extra_rules = ""

    def remember(self, user_text, answer):
        self.remembered.append((user_text, answer))

    def reply(self, text):
        self.replies.append(text)
        return "Tu futuro: helado."


@pytest.fixture
def make(monkeypatch):
    # The wait returns the inbox item at once: no microphone, no button.
    monkeypatch.setattr(ptt, "record_multi",
                        lambda cfg, sources, inbox=None, **kw: inbox())

    def build(item, *, echo=True):
        cfg = Config()
        viz = FakeViz(item)
        convo = FishConversation(cfg, MockSerialLink(cfg.serial, stream=io.StringIO()),
                                 play_audio=False, viz=viz, echo=echo)
        spoken = []
        monkeypatch.setattr(convo.speaker, "speak", lambda text, role="fish": spoken.append(text) or True)
        return convo, viz, spoken

    return build


def test_badge_reading_asks_the_name(make):
    convo, viz, spoken = make(Reading(name="Garcia Lopez Maria Jose", first_name="María José"))
    assert convo.turn() is True
    assert spoken == ["¿Tú eres María José?"]
    assert viz.readings == ["ask"]
    assert viz.listening == [True, False]


def test_confirmed_echo_reading_tells_the_echo_fortune(make):
    convo, viz, spoken = make(Reading(name="Valeria Ruiz", first_name="Valeria", confirmed=True))
    assert convo.turn() is True
    assert len(spoken) == 1 and spoken[0].startswith("Valeria")
    assert viz.readings == ["speaking"]


def test_reading_with_the_model_seeds_history_and_rules(make):
    convo, viz, spoken = make(Reading(name="Valeria Ruiz", first_name="Valeria",
                                      look="gorra roja"), echo=False)
    llm = FakeLLM()
    convo._llm = llm
    assert convo.turn() is True
    assert llm.resets == 1 and llm.extra_rules == convo.cfg.reading.rules
    assert len(llm.remembered) == 1
    user_text, answer = llm.remembered[0]
    assert "Valeria Ruiz" in user_text and "Lleva: gorra roja." in user_text
    assert answer == spoken[0] == "¿Tú eres Valeria?"
    assert llm.replies == []


def test_confirmed_reading_with_the_model_asks_for_the_future(make):
    convo, viz, spoken = make(Reading(name="Valeria Ruiz", first_name="Valeria",
                                      confirmed=True), echo=False)
    llm = FakeLLM()
    convo._llm = llm
    assert convo.turn() is True
    assert llm.replies == ["[Lectura] Se llama Valeria Ruiz, confirmado. Dile su futuro."]
    assert spoken == ["Tu futuro: helado."] and llm.remembered == []


def test_unknown_item_keeps_the_loop(make):
    convo, viz, spoken = make(object())
    assert convo.turn() is True and spoken == []


def test_canned_lines_go_through_the_speaker_lock(make, capsys):
    """`_apologize` must not drive the link beside a /badge handler's canned line."""
    convo, viz, spoken = make(object())
    said = []
    monkeypatch_say = lambda name: said.append(name) or True
    convo.speaker.say_canned = monkeypatch_say
    convo._apologize(convo.cfg.canned.no_signal)
    assert said == [convo.cfg.canned.no_signal]
    convo.speaker.say_canned = lambda name: False       # the fish is already talking
    convo._apologize(convo.cfg.canned.no_mic)
    assert said == [convo.cfg.canned.no_signal]
    assert "already speaking" in capsys.readouterr().out


# --- an uploaded recording (the phone's microphone) ----------------------------------
import wave

from fish_brain.reading import Utterance


class FakeSTT:
    def __init__(self, text="hola"):
        self.text = text
        self.calls = []

    def transcribe(self, path):
        self.calls.append(str(path))
        return self.text


def loud_wav(path, seconds=1.0):
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        w.writeframes(b"\x00\x20" * int(16000 * seconds))     # well above silence_rms
    return path


def test_uploaded_recording_is_a_voice_turn(make, tmp_path, capsys):
    wav = loud_wav(tmp_path / "fish_in_test.wav")
    convo, viz, spoken = make(Utterance(path=wav, hold_s=1.0, upload_s=0.25))
    convo._stt = FakeSTT("hola")
    assert convo.turn() is True
    assert spoken == ["hola"]                        # echo mode repeats the transcript
    assert convo._stt.calls == [str(wav)]
    assert not wav.exists()                          # unlinked after transcribing
    out = capsys.readouterr().out
    assert "you> hola" in out
    turn_line = [l for l in out.splitlines() if l.startswith("[turn] ")][-1]
    assert "rec=1.2s" in turn_line or "rec=1.3s" in turn_line      # hold + upload
    assert ("user", "hola") in viz.transcripts


def test_uploaded_recording_with_a_quit_word_ends_the_loop(make, tmp_path):
    wav = loud_wav(tmp_path / "fish_in_quit.wav")
    convo, viz, spoken = make(Utterance(path=wav, hold_s=0.5, upload_s=0.1))
    convo._stt = FakeSTT("salir")
    convo.cfg.ptt.voice_quit = True
    assert convo.turn() is False and spoken == [] and not wav.exists()


def test_ptt_summary_names_the_browser_mic(make, tmp_path):
    convo, viz, spoken = make(object())
    assert convo.ptt_summary() == "web"
    convo.cfg.ptt.capture = "browser"
    assert convo.ptt_summary() == "web+browser-mic"


# --- the remote relayed to the page -------------------------------------------------
@pytest.fixture
def remote(make, monkeypatch):
    """A conversation with a plain 'remote' source (no evdev) and a record_multi that
    only captures its keyword arguments."""
    calls = []

    def fake_record_multi(cfg, sources, on_level=None, inbox=None, relay=None,
                          relay_ready=None):
        calls.append({"sources": list(sources), "relay": relay, "relay_ready": relay_ready})
        return inbox()

    monkeypatch.setattr(ptt, "record_multi", fake_record_multi)
    convo, viz, spoken = make(object())
    src = ptt.ButtonSource(lambda: False, name="remote")
    convo.sources.append(src)
    return convo, viz, src, calls


def test_remote_is_relayed_when_a_page_has_a_microphone(remote):
    convo, viz, src, calls = remote
    convo.cfg.ptt.capture = "browser"
    viz.pages = 1
    assert convo.turn() is True
    assert src.relay is True
    assert calls[-1]["relay"] == viz.relay_ptt and calls[-1]["sources"] == convo.sources
    # The check record_multi asks at each press follows the page's state live.
    assert calls[-1]["relay_ready"]() is True
    viz.pages = 0
    assert calls[-1]["relay_ready"]() is False


def test_remote_records_here_without_a_page(remote):
    convo, viz, src, calls = remote
    convo.cfg.ptt.capture = "browser"
    viz.pages = 0
    assert convo.turn() is True
    assert src.relay is False and calls[-1]["relay"] is None
    # A phone that arrives later is seen at the next wait.
    viz.pages = 1
    viz._items.append(object())
    assert convo.turn() is True
    assert src.relay is True and calls[-1]["relay"] == viz.relay_ptt


def test_remote_is_never_relayed_in_host_mode(remote):
    convo, viz, src, calls = remote
    convo.cfg.ptt.capture = "host"
    viz.pages = 1
    assert convo.turn() is True
    assert src.relay is False and calls[-1]["relay"] is None


def test_ptt_summary_says_the_remote_goes_to_the_page(remote):
    convo, viz, src, calls = remote

    class Button:
        def describe(self):
            return "evdev(1 device, KEY_VOICECOMMAND, hold)"

    convo.button = Button()
    assert convo.ptt_summary() == "web+evdev(1 device, KEY_VOICECOMMAND, hold)"
    convo.cfg.ptt.capture = "browser"
    assert convo.ptt_summary() == "web+browser-mic+evdev(1 device, KEY_VOICECOMMAND, hold)→page"


def test_a_cut_recording_tells_the_llm(monkeypatch, tmp_path, capsys):
    """At the hold limit with the button still held the LLM is told the visitor kept talking."""
    import wave
    from fish_brain import ptt
    from fish_brain.config import Config
    from fish_brain.conversation import FishConversation
    from fish_brain.serial_link import MockSerialLink

    wav = tmp_path / "cut.wav"
    with wave.open(str(wav), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(16000)
        w.writeframes((np.full(16000, 8000, dtype="<i2")).tobytes())
    cfg = Config()
    cfg.canned.enabled = False
    convo = FishConversation(cfg, MockSerialLink(cfg.serial), play_audio=False, echo=False)
    monkeypatch.setattr(ptt, "record_hold", lambda *a, **k: wav)
    monkeypatch.setattr(ptt, "last_recording_was_cut", lambda: True)
    convo._stt = type("S", (), {"transcribe": lambda self, p: "y entonces le dije que"})()
    asked = []
    convo._llm = type("L", (), {"reply": lambda self, t: asked.append(t) or "ok", "last_error": None})()
    monkeypatch.setattr(convo.speaker, "speak", lambda text, **k: True)
    assert convo.turn() is True
    assert asked and "seguía hablando" in asked[0] and asked[0].startswith("y entonces le dije que")
    assert "cut=15.0s" in capsys.readouterr().out
