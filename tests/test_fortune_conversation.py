"""The fortune act in the turn loop: voice answers, the clips or the model's reading, never an
error line, never stuck; the page's taps; what it does to the house act beside it."""
import io
import time

import pytest

from fish_brain import cloud, fortune, fortune_bank, voice_guard
from fish_brain.config import Config
from fish_brain.conversation import FishConversation
from fish_brain.fortune_run import FortuneInput
from fish_brain.serial_link import MockSerialLink
from fish_brain.visit import NewVisit

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
    """A model that must not be asked (the clips)."""
    extra_rules = ""

    def __init__(self):
        self.calls = 0
        self.last_error = None

    def reply(self, text, remember=True):
        self.calls += 1
        raise AssertionError("the clips must never ask the model")

    def reset(self):
        pass

    def remember(self, *a):
        pass


class FakeLLM:
    """The model: a four-sentence reading, or a failure, or one that takes too long."""

    def __init__(self, reply="Veo fuego. Veo un gato. Alguien te mira. Tu palabra te guía.",
                 fail=False, delay=0.0):
        self.text, self.fail, self.delay = reply, fail, delay
        self.calls, self.asked, self.remembered = 0, [], []
        self.last_error, self.extra_rules, self.resets = None, "", 0

    def reply(self, text, remember=True):
        self.calls += 1
        self.asked.append(text)
        time.sleep(self.delay)
        if self.fail:
            self.last_error = "boom"
            return "Se me nubló la mente."
        return self.text

    def reset(self):
        self.resets += 1
        self.extra_rules = ""

    def remember(self, user, answer):
        self.remembered.append((user, answer))


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


def render(cfg, *, prefix="fortune_"):
    """Stand-ins for the rendered clips: an older WAV per name counts as cached."""
    cfg.canned.cache_dir.mkdir(parents=True, exist_ok=True)
    for name in cfg.canned.phrases:
        if name.startswith(prefix):
            (cfg.canned.cache_dir / f"{name}-t.wav").touch()


@pytest.fixture
def make(monkeypatch, tmp_path):
    def build(mode="script", llm=None, *, deck="tarot", cup=True, place="fiesta", rendered=True,
              clock=None):
        monkeypatch.setenv("FISH_PERSONA", "hat")
        monkeypatch.setenv("FISH_SHOW", mode)
        monkeypatch.setenv("FISH_FORTUNE_DECK", deck)
        monkeypatch.setenv("FISH_FORTUNE_CUP", "true" if cup else "false")
        monkeypatch.setenv("FISH_PLACE", place)
        monkeypatch.setattr(fortune, "moon_tonight", lambda now=None: "llena")
        cfg = Config()
        cfg.canned.cache_dir = tmp_path / "canned"
        cfg.show.state = str(tmp_path / "show.json")
        cfg.fortune.state = str(tmp_path / "fortune.json")
        cfg.show.seed = "test"
        cfg.filler.enabled = False
        if rendered:
            render(cfg)
        convo = FishConversation(cfg, MockSerialLink(cfg.serial, stream=io.StringIO()),
                                 text_input=True, play_audio=False,
                                 clock=clock or time.monotonic)
        convo.speaker = Speaker()
        convo._llm = llm or NoLLM()
        return convo
    return build


@pytest.fixture
def online(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "x" * 12)
    monkeypatch.setenv("GROQ_API_KEY", "x" * 12)
    monkeypatch.setattr(cloud, "is_online", lambda: True)
    monkeypatch.setattr(voice_guard, "_state", voice_guard.CLEAN)


def say(convo, text):
    convo._heard_at = convo._clock()
    return convo._finish_turn(text, {})


def start(convo, first=""):
    return convo._handle_item(FortuneInput("start", first))


def answer_all(c):
    """The five answers of a full act (deck and cup on)."""
    say(c, "el 23 de octubre")
    say(c, "soñé que se me caían los dientes")
    say(c, "la muerte")
    say(c, "una estrella")
    say(c, "un gato negro")


# ---- the act from the clips ----------------------------------------------------------------

def test_a_whole_act_from_the_clips_with_every_toggle(make):
    c = make()
    assert c.fortune is not None and c.fortune.view()["ready"]
    start(c)
    first = c.speaker.stages[-1]
    assert first[0].startswith("fortune_intro_fiesta_") and first[-1] == "fortune_q_fecha"
    view = c.fortune.view()
    assert view["open"] and (view["q"], view["of"], view["qid"]) == (1, 5, "fecha")
    say(c, "el 23 de octubre")
    assert c.speaker.stages[-1] == ["fortune_re_fecha_escorpio", "fortune_q_sueno"]
    say(c, "soñé que se me caían los dientes")
    st = c.speaker.stages[-1]
    assert st[0] == "fortune_re_sueno_dientes" and st[1].startswith("fortune_vision_")
    assert st[-1] == "fortune_q_carta_tarot"
    say(c, "la muerte")
    assert c.speaker.stages[-1] == ["fortune_re_carta_tarot_13", "fortune_q_taza"]
    say(c, "una estrella")
    assert c.speaker.stages[-1] == ["fortune_re_taza_estrella", "fortune_q_animal"]
    say(c, "un gato negro")
    end = c.speaker.stages[-1]
    assert end[0] == "fortune_re_animal_gato" and end[1].startswith("fortune_suspense_")
    assert end[2] == "fortune_num_6" and end[3] == "fortune_luna_llena"
    assert end[4].startswith("fortune_magic_") and end[-1].startswith("fortune_cierre_fiesta_")
    assert not c.fortune.open and c._llm.calls == 0 and c.speaker.other == []
    last = c.fortune.view()["last"]
    assert last["n"] == 1 and last["mode"] == "clips"
    assert last["data"]["signo"] == "Escorpio" and last["data"]["elemento"] == "agua"
    assert last["data"]["numero"] == 6 and last["data"]["carta"] == "La Muerte"
    assert last["data"]["animal"] == "el gato negro" and last["data"]["luna"] == "llena"
    assert last["data"]["palabra"] in fortune.MAGIC_WORDS


def test_the_toggles_off_skip_the_card_and_the_cup(make):
    c = make(deck="off", cup=False)
    start(c)
    assert c.fortune.view()["of"] == 3
    say(c, "23 de octubre")
    say(c, "soñé con serpientes")
    assert c.speaker.stages[-1][-1] == "fortune_q_animal"
    say(c, "el búho")
    assert c.speaker.stages[-1][0] == "fortune_re_animal_buho" and not c.fortune.open
    assert not any(n.startswith(("fortune_q_carta", "fortune_q_taza")) for n in c.speaker.all())


@pytest.mark.parametrize("place", ["casa", "universidad", "otro"])
def test_the_place_picks_the_intro_and_the_closing(make, place):
    c = make(place=place)
    start(c)
    assert c.speaker.stages[-1][0].startswith(f"fortune_intro_{place}_")
    answer_all(c)
    assert c.speaker.stages[-1][-1].startswith(f"fortune_cierre_{place}_")
    assert c.fortune.view()["place"] == place


def test_a_date_missed_twice_still_reaches_the_closing_with_no_error_line(make):
    c = make()
    start(c)
    say(c, "")
    assert c.speaker.stages[-1] == ["fortune_rq_fecha"]          # once more, narrower
    say(c, "mmm")
    st = c.speaker.stages[-1]
    assert st[0].startswith("fortune_bridge_") and st[-1] == "fortune_q_sueno"
    for _ in range(12):
        if not c.fortune.open:
            break
        say(c, "")
    assert not c.fortune.open
    names = c.speaker.all()
    assert not (set(names) & ERROR_LINES) and c.speaker.other == []
    assert sum(n.startswith("fortune_rq_") for n in names) <= c.cfg.fortune.reprompts
    assert names[-1].startswith("fortune_cierre_") and "fortune_num_6" not in names
    assert any(n.startswith("fortune_suspense_") for n in names)


def test_no_se_moves_on_without_a_second_ask(make):
    c = make()
    start(c)
    say(c, "no sé")
    st = c.speaker.stages[-1]
    assert st[0].startswith("fortune_bridge_") and st[-1] == "fortune_q_sueno"
    assert not any(n.startswith("fortune_rq_") for n in c.speaker.all())
    say(c, "soñé que volaba")
    say(c, "ninguna")                                            # the card: the same
    assert c.speaker.stages[-1][0].startswith("fortune_bridge_")
    assert c.speaker.stages[-1][-1] == "fortune_q_taza"


def test_no_me_acuerdo_at_the_dream_is_its_own_theme(make):
    """"No sé" is the bridge at every question but the dream, where it is the `nada` theme."""
    c = make()
    start(c)
    say(c, "el 23 de octubre")
    say(c, "no me acuerdo")
    st = c.speaker.stages[-1]
    assert st[0] == "fortune_re_sueno_nada" and st[-1] == "fortune_q_carta_tarot"
    assert not any(n.startswith(("fortune_bridge_", "fortune_rq_")) for n in st)
    assert c.fortune.v["data"]["sueno"] == "nada"


def test_a_dream_told_but_unclear_is_otro_and_the_words_are_kept(make, monkeypatch):
    c = make()
    monkeypatch.setattr(fortune, "dream_theme", lambda text: None)
    start(c)
    say(c, "23 de octubre")
    say(c, "pues fíjate que anoche")
    assert c.speaker.stages[-1] == ["fortune_rq_sueno"]
    say(c, "no te lo puedo contar")
    assert c.speaker.stages[-1][0].startswith("fortune_bridge_")
    assert c.fortune.v["data"]["sueno"] == "otro"
    assert c.fortune.v["data"]["sueno_txt"] == "no te lo puedo contar"


# ---- the dream's recording ------------------------------------------------------------------

def test_the_dream_lifts_the_recording_cap_only_online_and_restores_it(make, online):
    c = make()
    assert c.cfg.ptt.max_record_s == 5.5 and c.cfg.stt.long_online == ()
    c.cfg.stt.backend, c.cfg.stt._long_online_configured = "canary", ("groq",)
    start(c)
    assert c.cfg.ptt.max_record_s == 5.5
    say(c, "23 de octubre")                                       # the dream is next
    assert c.cfg.ptt.max_record_s == 10.0 and c.cfg.stt.long_online == ("groq",)
    say(c, "")                                                    # asked again: still lifted
    assert c.cfg.ptt.max_record_s == 10.0
    say(c, "soñé con agua")
    assert c.cfg.ptt.max_record_s == 5.5 and c.cfg.stt.long_online == ()
    # Dropped mid-dream: restored too.
    c.fortune.drop("test") if c.fortune.open else None
    c2 = make()
    c2.cfg.stt.backend, c2.cfg.stt._long_online_configured = "canary", ("groq",)
    start(c2)
    say(c2, "23 de octubre")
    assert c2.cfg.ptt.max_record_s == 10.0
    c2._handle_item(NewVisit(c2._clock()))
    assert c2.cfg.ptt.max_record_s == 5.5 and c2.cfg.stt.long_online == ()


def test_offline_or_without_the_long_route_the_cap_stays(make, monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "x" * 12)
    monkeypatch.setattr(cloud, "is_online", lambda: False)
    c = make()
    c.cfg.stt.backend, c.cfg.stt._long_online_configured = "canary", ("groq",)
    start(c)
    say(c, "23 de octubre")
    assert c.cfg.ptt.max_record_s == 5.5 and c.cfg.stt.long_online == ()
    monkeypatch.setattr(cloud, "is_online", lambda: True)
    c = make()
    c.cfg.stt.backend, c.cfg.stt._long_online_configured = "local", ("groq",)
    start(c)
    say(c, "23 de octubre")
    assert c.cfg.ptt.max_record_s == 5.5                          # the local model: too slow
    c = make()
    c.cfg.stt.backend, c.cfg.stt._long_online_configured = "canary", ()
    start(c)
    say(c, "23 de octubre")
    assert c.cfg.ptt.max_record_s == 5.5                          # no service configured


# ---- the page's taps --------------------------------------------------------------------------

def test_skip_and_end_from_the_page(make):
    c = make()
    c._handle_item(FortuneInput("skip"))                          # no act: ignored
    assert c.speaker.stages == []
    start(c)
    c._handle_item(FortuneInput("skip"))
    st = c.speaker.stages[-1]
    assert st[0].startswith("fortune_bridge_") and st[-1] == "fortune_q_sueno"
    assert not any(n.startswith("fortune_rq_") for n in c.speaker.all())
    say(c, "soñé con mi ex")
    c._handle_item(FortuneInput("end"))
    end = c.speaker.stages[-1]
    assert end[0].startswith("fortune_suspense_") and end[-1].startswith("fortune_cierre_")
    assert "fortune_luna_llena" in end and not any(n.startswith("fortune_num_") for n in end)
    assert not c.fortune.open and c.fortune.view()["last"]["data"].get("sueno")


def test_a_start_while_open_is_ignored(make):
    c = make()
    start(c)
    n = len(c.speaker.stages)
    start(c)
    assert len(c.speaker.stages) == n and c.fortune.v["n"] == 1


# ---- beside the house act --------------------------------------------------------------------

def test_the_fortune_takes_the_utterance_before_the_house_act(make):
    c = make()
    start(c)
    say(c, "hola")                                                # not a date
    assert c.speaker.stages[-1] == ["fortune_rq_fecha"] and not c.show.open


def test_after_a_house_act_it_knows_the_house_and_the_name(make):
    c = make()
    say(c, "hola"); say(c, "la fiesta"); say(c, "un volcán"); say(c, "el mapa")
    assert c.visit.house == "Gryffindor" and not c.show.open
    c.visit.first_name = "Leo"
    start(c)
    assert c.speaker.stages[-1][0] == "fortune_intro_G_1"
    view = c.fortune.view()
    assert view["house"] == "Gryffindor" and view["first"] == "Leo"
    answer_all(c)
    c.visit.first_name = ""
    start(c, "Ana [x]")                                           # a typed name wins, cleaned
    assert c.fortune.view()["first"] == "Ana x" and c.fortune.view()["house"] == "Gryffindor"


def test_a_house_given_long_ago_does_not_carry_over(make):
    clock = Clock()
    c = make(clock=clock)
    say(c, "hola"); say(c, "fiesta"); say(c, "volcán"); say(c, "mapa")
    clock.t += c.cfg.fortune.carry_s + 1
    start(c)
    assert c.speaker.stages[-1][0].startswith("fortune_intro_fiesta_")
    assert c.fortune.view()["house"] is None


def test_it_cannot_start_over_a_live_house_act(make):
    c = make()
    say(c, "hola")                                                # the scripted visit asks Q1
    start(c)
    assert not c.fortune.open and c.show.open
    assert c.fortune.view()["last"]["refused"] == "visit open"
    say(c, "la fiesta")
    assert c.speaker.stages[-1] == ["show_re_A1_fiesta", "show_q_A2"]


def test_new_visitor_drops_it_silently(make):
    c = make()
    start(c)
    say(c, "23 de octubre")
    n = len(c.speaker.stages)
    c._handle_item(NewVisit(c._clock()))
    assert not c.fortune.open
    assert c.speaker.stages[n][0].startswith("show_greet_")      # the house act, nothing of the fortune's
    last = c.fortune.view()["last"]
    assert last["mode"] == "dropped" and last["why"] == "new visitor" and last["data"]["signo"] == "Escorpio"


def test_a_typed_name_drops_it_too(make):
    from fish_brain.reading import Reading
    c = make(llm=FakeLLM())                                       # the typed name asks the model
    start(c)
    c._handle_item(Reading(name="Ana", first_name="Ana", confirmed=True))
    assert not c.fortune.open and c.fortune.view()["last"]["mode"] == "dropped"


def test_ninety_one_seconds_of_silence_let_the_next_visitor_through(make):
    clock = Clock()
    c = make(clock=clock)
    start(c)
    clock.t += 89
    say(c, "")                                                    # still the act's
    assert c.fortune.open and c.speaker.stages[-1] == ["fortune_rq_fecha"]
    clock.t += 91
    say(c, "hola")
    assert not c.fortune.open and c.show.open                     # a new visitor: the house act
    assert c.speaker.stages[-1][0].startswith("show_greet_")
    assert c.fortune.view()["last"]["why"] == "quiet"


def test_a_failure_mid_act_moves_on_without_an_error(make):
    c = make()
    start(c)
    c._show_fault("mic")
    assert c.speaker.stages[-1] == ["fortune_rq_fecha"]
    c._show_fault("timeout: stt")
    assert c.speaker.stages[-1][0].startswith("fortune_bridge_")
    assert c.speaker.stages[-1][-1] == "fortune_q_sueno" and c.speaker.other == []


def test_without_the_show_the_act_runs_and_faults_say_no_error_line(make, monkeypatch):
    monkeypatch.setattr(cloud, "is_online", lambda: False)        # the clips, whatever the keys
    c = make("off")
    assert c.show is None and c.fortune is not None
    start(c)
    assert c._acts_on()
    c._show_fault("ValueError")
    assert c.speaker.stages[-1] == ["fortune_rq_fecha"] and c.speaker.other == []
    answer_all(c)
    assert not c.fortune.open and not c._acts_on()


# ---- the model's reading ---------------------------------------------------------------------

def test_the_model_reading_is_said_live_remembered_then_the_closing(make, online):
    llm = FakeLLM()
    c = make("auto", llm=llm)
    c.cfg.place.text = "la terraza"                               # not "otro": not used
    assert c.fortune.mode_now() == ("llm", "online")
    now = c._clock()
    c.visit.start("Ana", now)
    c.visit.delivered("Ravenclaw", None, now)                     # a verdict just given
    start(c)
    assert c.speaker.stages[-1][0] == "fortune_intro_R_1"
    answer_all(c)
    assert llm.calls == 1 and llm.extra_rules == c.cfg.fortune.rules and llm.resets == 1
    tag = llm.asked[0]
    assert tag.startswith("[ADIVINACIÓN: ") and "nombre=Ana" in tag and "lugar=fiesta" in tag
    assert "signo=Escorpio" in tag and 'sueño=dientes ("' in tag and "casa=Ravenclaw" in tag
    assert "carta=La Muerte" in tag and "luna=llena" in tag and "palabra=" in tag
    assert c.speaker.other == [("speak", llm.text)]
    assert llm.remembered == [(tag, llm.text)]
    assert c.speaker.stages[-2][0] == "fortune_re_animal_gato"
    assert c.speaker.stages[-2][-1].startswith("fortune_suspense_")
    assert c.speaker.stages[-1][0].startswith("fortune_cierre_fiesta_")
    assert not any(n.startswith(("fortune_num_", "fortune_luna_", "fortune_magic_"))
                   for n in c.speaker.all())
    assert not c.fortune.open and c.fortune.view()["last"]["mode"] == "llm"
    assert c.show.mode_now() == ("llm", "online")                 # no failure to back off from


def test_the_free_text_of_the_place_reaches_the_model_with_otro(make, online):
    llm = FakeLLM()
    c = make("auto", llm=llm, place="otro")
    c.cfg.place.text = "la terraza del Beto"
    start(c)
    answer_all(c)
    assert "lugar=la terraza del Beto" in llm.asked[0]


@pytest.mark.parametrize("llm", [
    FakeLLM(fail=True),
    FakeLLM(delay=0.6),
    FakeLLM(reply="Te espera una enfermedad larga. Y un gato."),
    FakeLLM(reply=""),
], ids=["error", "timeout", "dirty", "empty"])
def test_a_model_failure_falls_back_to_the_clips_and_marks_the_show(make, online, llm):
    c = make("auto", llm=llm)
    c.cfg.fortune.reading_s = 0.2
    start(c)
    answer_all(c)
    assert llm.calls == 1 and c.speaker.other == [] and llm.remembered == []
    lead, end = c.speaker.stages[-2], c.speaker.stages[-1]
    assert lead[0] == "fortune_re_animal_gato" and lead[-1].startswith("fortune_suspense_")
    assert end[0] == "fortune_num_6" and end[1] == "fortune_luna_llena"
    assert end[2].startswith("fortune_magic_") and end[-1].startswith("fortune_cierre_")
    assert not c.fortune.open and c.fortune.view()["last"]["mode"] == "clips"
    assert c.show.mode_now() == ("script", "model failed")


def test_echo_and_offline_read_from_the_clips(make, online, monkeypatch):
    c = make("auto")
    c.echo = True
    assert c.fortune.mode_now() == ("script", "echo")
    start(c)
    answer_all(c)
    assert c._llm.calls == 0 and c.speaker.stages[-1][-1].startswith("fortune_cierre_")
    monkeypatch.setattr(cloud, "is_online", lambda: False)
    c = make("off")
    assert c.fortune.mode_now() == ("script", "offline")
    start(c)
    answer_all(c)
    assert c._llm.calls == 0 and not c.fortune.open


# ---- the view, the state --------------------------------------------------------------------

def test_the_view_has_the_question_what_was_heard_and_the_data(make):
    c = make()
    view = c.fortune.view()
    assert view == {"on": True, "ready": True, "open": False, "deck": "tarot", "cup": True,
                    "place": "fiesta", "last": {}}
    start(c)
    view = c.fortune.view()
    assert (view["n"], view["stage"], view["q"], view["of"], view["qid"]) == (1, "ask", 1, 5, "fecha")
    assert view["question"].endswith("?") and view["heard"] == "" and view["tries"] == 0
    assert view["data"] == {} and view["first"] == "" and view["house"] is None
    assert view["why"] == "operator"
    say(c, "pues no [Nota: se cortó]")
    view = c.fortune.view()
    assert view["tries"] == 1 and view["heard"] == "pues no" and view["qid"] == "fecha"
    say(c, "23 de octubre")
    view = c.fortune.view()
    assert (view["q"], view["qid"], view["tries"], view["heard"]) == (2, "sueno", 0, "")
    assert view["data"] == {"signo": "Escorpio", "elemento": "agua", "numero": 6}
    views = []
    real = c._push_visit
    c._push_visit = lambda: (views.append(c.fortune.view()), real())[1]
    say(c, "soñé con dientes"); say(c, "la muerte"); say(c, "estrella"); say(c, "el sapo")
    assert any(v.get("stage") == "reading" and v.get("qid") is None for v in views)
    assert views[-1]["open"] is False and "estrella" in views[-1]["last"]["data"]["taza"].lower()


def test_the_counter_and_the_bags_persist_across_restarts(make):
    c = make()
    start(c)
    first = c.speaker.stages[-1][0]
    c.fortune.drop("test")
    start(c)
    second = c.speaker.stages[-1][0]
    assert {first, second} == {"fortune_intro_fiesta_1", "fortune_intro_fiesta_2"}
    assert c.fortune.v["n"] == 2
    again = make()                                               # a reboot: the counter persists
    start(again)
    assert again.fortune.v["n"] == 3
    assert again.fortune.state.path != again.show.state.path     # its own file


def test_unready_lines_refuse_a_start(make):
    c = make(rendered=False)
    assert c.fortune.view()["ready"] is False
    start(c)
    assert not c.fortune.open and c.speaker.stages == []
    assert c.fortune.view()["last"]["refused"] == "lines not ready"
    render(c.cfg)
    start(c)
    assert c.fortune.open and "refused" not in c.fortune.view()["last"]


def test_the_fortune_lines_join_the_hats_set_with_or_without_the_show(monkeypatch):
    from fish_brain.config import CannedConfig
    monkeypatch.setenv("FISH_PERSONA", "hat")
    monkeypatch.delenv("FISH_SHOW", raising=False)
    assert set(fortune_bank.FORTUNE_PHRASES) <= set(CannedConfig().phrases)
    assert not any(n.startswith("show_") for n in CannedConfig().phrases)
    monkeypatch.setenv("FISH_PERSONA", "fish")
    assert not any(n.startswith("fortune_") for n in CannedConfig().phrases)


def test_a_record_is_made_for_the_reading_and_the_drop(make, monkeypatch):
    from fish_brain import debug
    records = []
    monkeypatch.setattr(debug, "emit", lambda kind, **f: records.append((kind, f)))
    c = make()
    start(c)
    answer_all(c)
    kind, rec = records[-1]
    assert kind == "fortune" and rec["n"] == 1 and rec["how"] == "clips" and rec["mode"] == "script"
    assert rec["place"] == "fiesta" and rec["data"]["signo"] == "Escorpio"
    assert len(rec["heard"]) == 5 and rec["clips"][-1].startswith("fortune_cierre_")
    assert rec["reading"] is None and rec["seconds"] >= 0
    start(c)
    c.fortune.drop("test")
    kind, rec = records[-1]
    assert kind == "fortune" and rec["dropped"] == "test" and rec["n"] == 2
    assert "fortune" in debug._RECORD_KINDS
