"""A reading turn through the conversation loop with a mock link and a fake page (no
hardware, no network, no audio)."""
from __future__ import annotations

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
                        lambda cfg, sources, on_level=None, inbox=None: inbox())

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
