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


def test_an_uploaded_recording_names_how_the_hold_ended(make, tmp_path, monkeypatch):
    from fish_brain import conversation as conv_mod
    seen = []
    monkeypatch.setattr(conv_mod.debug, "turn_set", lambda **f: seen.append(f))
    wav = loud_wav(tmp_path / "fish_in_end.wav")
    convo, viz, spoken = make(Utterance(path=wav, hold_s=10.4, upload_s=0.1, ended="silence"))
    convo._stt = FakeSTT("hola")
    assert convo.turn() is True
    assert {"trigger": "phone microphone", "ended": "silence"} in seen


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


def test_the_model_is_built_by_the_provider_factory_from_the_current_profile(monkeypatch):
    from fish_brain import llm
    built = []
    monkeypatch.setattr(llm, "make_conversation", lambda cfg: built.append(cfg.profile) or object())
    cfg = Config()
    convo = FishConversation(cfg, MockSerialLink(cfg.serial), play_audio=False, echo=False)
    first = convo.llm
    assert convo.llm is first and built == [cfg.llm.profile]       # built once, on first use


# --- the debug hub sees every turn, and can never break one ---

def test_turn_records_for_the_debug_page(make, tmp_path, capsys):
    from fish_brain import debug
    hub = debug.install(Config())
    try:
        wav = loud_wav(tmp_path / "a.wav")
        convo, viz, spoken = make(Utterance(path=wav, hold_s=1.0, upload_s=0.25))
        convo._stt = FakeSTT("hola")
        convo.turn()
        quiet = tmp_path / "q.wav"
        with wave.open(str(quiet), "wb") as w:
            w.setnchannels(1); w.setsampwidth(2); w.setframerate(16000)
            w.writeframes(b"\x00\x00" * 16000)
        viz._items.append(Utterance(path=quiet, hold_s=1.0, upload_s=0.1))
        convo.turn()
        convo._stt = FakeSTT("")
        viz._items.append(Utterance(path=loud_wav(tmp_path / "c.wav"), hold_s=1.0, upload_s=0.1))
        convo.turn()
        good, silent, missed = hub.recent("turn")
        assert good["outcome"] == "spoken" and good["user"] == "hola" and good["reply"] == "hola"
        assert good["trigger"] == "phone microphone" and good["rec"]["rms"] > 0.1
        line = [l for l in capsys.readouterr().out.splitlines() if l.startswith("[turn] ")][0]
        assert f"rec={good['times']['rec']:.1f}s" in line and f"stt={good['times']['stt']:.1f}s" in line
        assert silent["outcome"] == "silence" and silent["rec"]["zero_frac"] == 1.0
        assert missed["outcome"] == "not understood"
        assert hub.recording_bytes()[:4] == b"RIFF"
    finally:
        debug.uninstall()


def test_a_turn_survives_a_debug_hub_that_only_raises(make, tmp_path):
    from fish_brain import debug
    hub = debug.install(Config())
    try:
        for name in ("emit", "turn_open", "turn_set", "turn_close", "recording"):
            setattr(hub, name, lambda *a, **k: 1 / 0)
        convo, viz, spoken = make(Utterance(path=loud_wav(tmp_path / "a.wav"), hold_s=1.0, upload_s=0.2))
        convo._stt = FakeSTT("hola")
        assert convo.turn() is True and spoken == ["hola"]
        assert hub.errors > 0
    finally:
        debug.uninstall()


def test_a_debug_item_runs_in_the_loop(make):
    ran = []
    item = type("Item", (), {"run_in_loop": lambda self, convo: ran.append(convo)})()
    convo, viz, spoken = make(item)
    assert convo.turn() is True and ran == [convo] and spoken == []


# ---- the hat's visit (visit.py) -----------------------------------------------------------
from fish_brain import canned  # noqa: E402
from fish_brain.conversation import TurnTimeout  # noqa: E402
from fish_brain.visit import NewVisit  # noqa: E402


class VisitViz(FakeViz):
    def __init__(self):
        super().__init__(None)
        self.visits = []

    def push_visit(self, **view):
        self.visits.append(view)


class ScriptLLM(FakeLLM):
    """Replies from a list; an item ("error", text) answers like a failed call."""

    def __init__(self, replies):
        super().__init__()
        self.script = list(replies)
        self.kwargs = []

    def reply(self, text, remember=True):
        self.replies.append(text)
        self.kwargs.append(remember)
        r = self.script.pop(0) if self.script else "Mmm."
        if isinstance(r, tuple):
            self.last_error = "APIError"
            return r[1]
        self.last_error = None
        return r


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


@pytest.fixture
def hat(monkeypatch):
    """A hat in text mode: `build(inputs, replies)` -> (convo, viz, llm, spoken)."""
    monkeypatch.setenv("FISH_PERSONA", "hat")

    def build(inputs, replies, *, echo=False, clock=None, spoken_ok=True):
        cfg = Config()
        viz = VisitViz()
        convo = FishConversation(cfg, MockSerialLink(cfg.serial, stream=io.StringIO()),
                                 text_input=True, play_audio=False, viz=viz, echo=echo,
                                 clock=clock or Clock())
        llm = ScriptLLM(replies)
        convo._llm = llm
        spoken = []
        ok = spoken_ok if callable(spoken_ok) else (lambda text: spoken_ok)
        monkeypatch.setattr(convo.speaker, "speak",
                            lambda text, role="fish": (spoken.append(text), ok(text))[1])
        monkeypatch.setattr(convo.speaker, "say_canned", lambda name, **k: True)
        it = iter(inputs)
        monkeypatch.setattr("builtins.input", lambda prompt="": next(it))
        return convo, viz, llm, spoken

    return build


VERDICT = "¡Ravenclaw! Hoy verás un robot.\nCASA: Ravenclaw"


def test_a_whole_visit_tags_four_stages_and_strips_the_house(hat):
    convo, viz, llm, spoken = hat(["hola", "Ana", "libro", "investigo", "gracias"],
                                  ["¡Hola! ¿Tu nombre?", "Ana, ¿mapa o libro?",
                                   "Libros. ¿Abres o investigas?", VERDICT, "¡Hola de nuevo!"])
    for _ in range(4):
        assert convo.turn() is True
    assert llm.replies[:3] == ["[ETAPA 1/4] hola", "[ETAPA 2/4] Ana", "[ETAPA 3/4] libro"]
    assert llm.replies[3].startswith("[ETAPA 4/4] [FUTURO: hora=")      # the day's ingredients
    assert llm.replies[3].endswith("] investigo")
    assert llm.kwargs == [False] * 4
    assert [u for u, _ in llm.remembered] == llm.replies
    assert llm.remembered[-1][1] == VERDICT                 # the history keeps the tag line
    assert spoken[-1] == "¡Ravenclaw! Hoy verás un robot."
    assert not any("CASA" in t for _, t in viz.transcripts)
    assert convo.visit.done and convo.visit.house == "Ravenclaw"
    assert viz.visits[-1]["stage"] == 5 and viz.visits[-1]["house"] == "Ravenclaw"
    assert llm.extra_rules == convo.cfg.visit.rules and llm.resets == 1
    assert convo.turn() is True                              # the next one is a new visitor
    assert llm.replies[-1] == "[ETAPA 1/4] gracias" and llm.resets == 2


def test_a_dropped_reply_is_not_remembered_and_the_stage_stays(hat):
    convo, viz, llm, spoken = hat(["hola", "hola otra vez"], ["Uno", "Dos"], spoken_ok=False)
    convo.turn()
    convo.turn()
    assert llm.remembered == [] and llm.replies == ["[ETAPA 1/4] hola", "[ETAPA 1/4] hola otra vez"]


def test_a_failed_call_echoes_the_visitor_and_changes_nothing(hat):
    """His rule (2026-10-26): when the model fails, the hat repeats; never the error line."""
    convo, viz, llm, spoken = hat(["hola", "Ana"], [("error", "Se me nubló."), "Hola Ana."])
    convo.cfg.tts.backend = "loq"
    convo.turn()
    assert spoken == ["hola"] and llm.remembered == [] and convo.visit.said == 0
    convo.turn()
    assert llm.replies[-1] == "[ETAPA 1/4] Ana" and convo.visit.said == 1


def test_a_verdict_past_the_budget_stays_at_stage_four(hat, monkeypatch):
    convo, viz, llm, spoken = hat(["a", "b", "c", "d"], ["1", "2", "3"])
    convo.visit.set_cues({"color": "azul"})
    for _ in range(3):
        convo.turn()
    assert convo.visit.pending() == {}
    convo.visit.set_cues({"edad": "niño"})

    def too_late(stage, fn, **kw):
        raise TurnTimeout(stage)
    monkeypatch.setattr(convo, "_await", too_late)
    assert convo.turn() is True
    assert convo.visit.stage == 4 and len(llm.remembered) == 3
    assert convo.visit.pending() == {"edad": "niño"}


def test_cues_go_once_with_the_next_turn(hat):
    convo, viz, llm, spoken = hat(["hola", "Ana"], ["¿Nombre?", "Ana..."])
    convo.turn()
    convo.visit.set_cues({"edad": "niño", "lleva": "gorra"})
    convo.turn()
    assert llm.replies[1] == "[ETAPA 2/4] [PISTAS: edad=niño; lleva=gorra] Ana"
    assert convo.visit.pending() == {} and viz.visits[-1]["sent"] == {"edad": "niño",
                                                                      "lleva": "gorra"}


def test_idle_starts_a_new_visitor(hat):
    clock = Clock()
    convo, viz, llm, spoken = hat(["hola", "Ana", "otra"], ["1", "2", "3"], clock=clock)
    convo.turn()
    clock.t += 20
    convo.turn()
    assert llm.replies[1] == "[ETAPA 2/4] Ana" and llm.resets == 1
    clock.t += 31
    convo.turn()
    assert llm.replies[2] == "[ETAPA 1/4] otra" and llm.resets == 2


def test_echo_has_a_visit_that_waits_for_the_model(hat):
    convo, viz, llm, spoken = hat(["hola", "hola"], ["¡Hola!"], echo=True)
    assert convo.visit is not None
    convo.turn()
    assert spoken == ["hola"] and llm.replies == []
    convo.echo = False                             # /debug mode=llm
    convo.turn()
    assert llm.replies == ["[ETAPA 1/4] hola"]


def test_a_rebuilt_model_starts_a_new_visit(hat):
    convo, viz, llm, spoken = hat(["hola", "Ana"], ["1"])
    convo.turn()
    fresh = ScriptLLM(["2"])
    convo._llm = fresh                             # what debug_actions._fresh_llm leads to
    convo.turn()
    assert fresh.extra_rules == convo.cfg.visit.rules and fresh.replies == ["[ETAPA 1/4] Ana"]


def test_a_badge_is_stage_one_with_the_first_name_only(hat):
    convo, viz, llm, spoken = hat(["sí"], ["Laura, ¿mapa o libro?"])
    assert convo._handle_item(Reading(name="Garcia Lopez Maria Jose", first_name="María José"))
    assert spoken == ["¿Tú eres María José?"] and viz.readings == ["ask"]
    user, answer = llm.remembered[0]
    assert user.startswith("[ETAPA 1/4] ") and "María José" in user and "Garcia" not in user
    assert answer == "¿Tú eres María José?" and llm.replies == []
    convo.turn()
    assert llm.replies == ["[ETAPA 2/4] sí"]


def test_a_typed_name_gets_stage_one_from_the_model(hat):
    convo, viz, llm, spoken = hat([], ["¡Valeria! Ayúdame a ver."])
    assert convo._handle_item(Reading(name="Valeria Ruiz", first_name="Valeria", confirmed=True))
    assert llm.replies == ["[ETAPA 1/4] [Lectura] Se llama Valeria, confirmado."]
    assert spoken == ["¡Valeria! Ayúdame a ver."] and convo.visit.said == 1


def test_new_visitor_greets_and_seeds_stage_one(hat, monkeypatch):
    convo, viz, llm, spoken = hat(["Me llamo Ana"], ["Ana, ¿mapa o libro?"])
    monkeypatch.setattr(canned, "cached", lambda name, cfg: True)
    said = []
    monkeypatch.setattr(convo.speaker, "say_canned", lambda name, **k: said.append(name) or True)
    assert convo._handle_item(NewVisit(at=convo._clock()))
    greeting = convo.cfg.canned.phrases["visit_greeting"]
    assert said == ["visit_greeting"] and ("fish", greeting) in viz.transcripts
    assert llm.remembered[0] == ("[ETAPA 1/4] " + convo.cfg.visit.arrival_note, greeting)
    convo.turn()
    assert llm.replies == ["[ETAPA 2/4] Me llamo Ana"]


def test_a_greeting_not_said_is_not_remembered(hat, monkeypatch):
    convo, viz, llm, spoken = hat(["Ana"], ["¿Nombre?"])
    monkeypatch.setattr(canned, "cached", lambda name, cfg: True)
    monkeypatch.setattr(convo.speaker, "say_canned", lambda name, **k: False)
    convo._handle_item(NewVisit(at=convo._clock()))
    assert llm.remembered == []
    convo.turn()
    assert llm.replies == ["[ETAPA 1/4] Ana"]


def test_a_new_visitor_already_started_by_a_turn_is_moot(hat):
    convo, viz, llm, spoken = hat(["hola"], ["1"])
    convo.visit.request_new(convo._clock() - 1)
    convo.turn()                                   # the turn opened the visit the tap asked for
    n = convo.visit.n
    convo._handle_item(NewVisit(at=convo._clock() - 1))
    assert convo.visit.n == n and len(llm.remembered) == 1


def test_echo_new_visitor_only_greets(hat, monkeypatch):
    convo, viz, llm, spoken = hat([], [], echo=True)
    monkeypatch.setattr(canned, "cached", lambda name, cfg: False)
    convo._handle_item(NewVisit(at=convo._clock()))
    assert spoken == [convo.cfg.canned.phrases["visit_greeting"]]
    assert llm.remembered == [] and llm.resets == 0


def test_the_visit_off_keeps_the_hats_old_reading(hat, monkeypatch):
    monkeypatch.setenv("FISH_VISIT", "false")
    convo, viz, llm, spoken = hat([], [])
    assert convo._handle_item(Reading(name="Valeria Ruiz", first_name="Valeria", confirmed=True))
    assert llm.replies == ["[Lectura] Se llama Valeria Ruiz, confirmado. Dile su futuro."]


def test_the_fish_has_no_visit(make):
    convo, viz, spoken = make(Reading(name="Valeria Ruiz", first_name="Valeria",
                                      confirmed=True), echo=False)
    assert convo.visit is None and not convo._visit_on()
