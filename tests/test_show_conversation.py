"""The scripted visit in the turn loop: no model, no live voice, no error line, never stuck."""
import io

import pytest

from fish_brain import cloud, ptt, show_bank, voice_guard
from fish_brain.config import CannedConfig, Config
from fish_brain.conversation import FishConversation
from fish_brain.serial_link import MockSerialLink

ERROR_LINES = {"no_signal", "no_mic", "reading_fail", "timeout_stt_1", "timeout_stt_2"}


class Speaker:
    def __init__(self):
        self.stages: list[list[str]] = []
        self.other: list[tuple] = []
        self.last_timing = {}

    def say_sequence(self, names, *, wait_s=5.0):
        self.stages.append(list(names))
        return True

    def say_canned(self, name, **kw):
        self.other.append(("canned", name))
        return True

    def speak(self, text, **kw):
        self.other.append(("speak", text))
        return True

    def all(self):
        return [n for st in self.stages for n in st]


class NoLLM:
    """A model that must not be asked (script) or that fails (the hand-over)."""
    extra_rules = ""

    def __init__(self, fail=False):
        self.calls, self.fail = 0, fail
        self.last_error = None

    def reply(self, text, remember=True):
        self.calls += 1
        if self.fail:
            self.last_error = "boom"
            return "Se me nubló la mente."
        raise AssertionError("the script must never ask the model")

    def reset(self):
        pass

    def remember(self, *a):
        pass


@pytest.fixture
def make(monkeypatch, tmp_path):
    def build(mode="script", llm=None):
        monkeypatch.setenv("FISH_PERSONA", "hat")
        monkeypatch.setenv("FISH_SHOW", mode)
        cfg = Config()
        cfg.canned.cache_dir = tmp_path / "canned"
        cfg.show.state = str(tmp_path / "show.json")
        cfg.show.seed = "test"
        cfg.filler.enabled = False
        convo = FishConversation(cfg, MockSerialLink(cfg.serial, stream=io.StringIO()),
                                 text_input=True, play_audio=False)
        convo.speaker = Speaker()
        convo._llm = llm or NoLLM()
        return convo
    return build


def say(convo, text):
    convo._heard_at = convo._clock()
    return convo._finish_turn(text, {})


def test_a_whole_visit_from_answers_with_no_model(make):
    c = make()
    say(c, "hola")
    first = c.speaker.stages[-1]
    assert first[0].startswith("show_greet_") and first[-1] == "show_q_A1"
    say(c, "la fiesta")
    assert c.speaker.stages[-1] == ["show_re_A1_fiesta", "show_q_A2"]
    say(c, "un volcán")
    assert c.speaker.stages[-1] == ["show_re_A2_volcan", "show_q_A3"]
    say(c, "el mapa")
    verdict = c.speaker.stages[-1]
    assert verdict[0] == "show_re_A3_mapa"
    assert any(n.startswith("show_house_G_") for n in verdict)
    assert verdict[-1].startswith("show_farewell_")
    assert c.visit.house == "Gryffindor" and not c.show.open
    assert c._llm.calls == 0 and c.speaker.other == []


def test_nothing_understood_still_reaches_a_verdict_with_no_error_line(make):
    c = make()
    say(c, "hola")
    for _ in range(12):
        if not c.show.open:
            break
        say(c, "")
    assert not c.show.open and c.visit.house in show_bank.HOUSES.values()
    names = c.speaker.all()
    assert not (set(names) & ERROR_LINES) and c.speaker.other == []
    assert sum(n.startswith("show_rq_") for n in names) <= c.cfg.show.reprompts
    assert any(n.startswith("show_bridge_") for n in names)


def test_a_stated_house_wins_at_once(make):
    c = make()
    say(c, "hola")
    say(c, "yo quiero ser de Ravenclaw")
    assert c.visit.house == "Ravenclaw" and any(n.startswith("show_pref_R_")
                                                for n in c.speaker.stages[-1])


def test_a_first_sentence_with_a_house_goes_straight_to_it(make):
    c = make()
    say(c, "quiero Slytherin")
    assert c.visit.house == "Slytherin"


def test_a_failure_mid_visit_moves_on_without_an_error(make):
    c = make()
    say(c, "hola")
    c._show_fault("mic")
    assert c.speaker.stages[-1] == ["show_rq_A1"]         # asked once more, narrower
    c._show_fault("timeout: stt")
    assert c.speaker.stages[-1][0].startswith("show_bridge_")
    assert c.speaker.stages[-1][-1] == "show_q_A2"


def test_visits_rotate_question_sets_and_remember_across_restarts(make):
    c = make()
    say(c, "hola"); assert c.show.v["set"] == "A"
    c.show.v = None
    say(c, "hola"); assert c.show.v["set"] == "B"
    again = make()                                         # a reboot: the counter persists
    say(again, "hola")
    assert again.show.v["set"] == "C" and again.show.v["n"] == 3


def test_small_children_get_two_questions(make):
    c = make()
    c.visit.set_cues({"edad": "niño"})
    say(c, "hola")
    say(c, "fiesta")
    say(c, "jardín")
    assert c.visit.house == "Hufflepuff" and not c.show.open


def test_auto_uses_the_model_when_it_can_and_the_script_when_offline(make, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "x" * 12)
    monkeypatch.setenv("GROQ_API_KEY", "x" * 12)
    monkeypatch.setattr(voice_guard, "_state", voice_guard.CLEAN)
    c = make("auto")
    monkeypatch.setattr(cloud, "is_online", lambda: True)
    assert c.show.mode_now() == ("llm", "online")
    assert c._show_turn("hola", {}) is False                # the model's visit runs
    monkeypatch.setattr(cloud, "is_online", lambda: False)
    assert c.show.mode_now() == ("script", "offline")
    monkeypatch.setattr(cloud, "is_online", lambda: True)
    monkeypatch.setattr(voice_guard, "_state", voice_guard.TAINTED)
    assert c.show.mode_now() == ("script", "voice")


def test_a_model_failure_hands_over_and_its_line_is_never_said(make, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "x" * 12)
    monkeypatch.setenv("GROQ_API_KEY", "x" * 12)
    monkeypatch.setattr(cloud, "is_online", lambda: True)
    monkeypatch.setattr(voice_guard, "_state", voice_guard.CLEAN)
    c = make("auto", llm=NoLLM(fail=True))
    c.cfg.tts.backend = "loq"
    say(c, "hola, soy Ana")
    assert c._llm.calls == 1 and c.show.open
    assert c.speaker.stages[-1][0].startswith("show_bridge_")
    assert all(t != "Se me nubló la mente." for _k, t in c.speaker.other)
    assert c.show.mode_now() == ("script", "model failed")    # the next visits too


def test_show_mode_turns_off_the_quit_word_and_long_recordings(make):
    c = make()
    assert c.cfg.ptt.voice_quit is False
    assert c.cfg.ptt.max_record_s <= c.cfg.show.max_record_s
    assert c.cfg.stt.long_online == ()
    say(c, "hola")
    assert say(c, "salir") is True and c.show.open        # "salir" is just an answer


def test_the_show_lines_join_the_canned_set_only_with_the_show_on(monkeypatch):
    monkeypatch.setenv("FISH_PERSONA", "hat")
    monkeypatch.delenv("FISH_SHOW", raising=False)
    assert not any(n.startswith("show_") for n in CannedConfig().phrases)
    monkeypatch.setenv("FISH_SHOW", "auto")
    assert set(show_bank.SHOW_PHRASES) <= set(CannedConfig().phrases)
    monkeypatch.setenv("FISH_PERSONA", "fish")
    assert not any(n.startswith("show_") for n in CannedConfig().phrases)


def test_off_is_todays_behaviour(make):
    c = make("off")
    assert c.show is None
