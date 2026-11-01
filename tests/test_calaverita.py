"""La calaverita: the verse's checks, the act from a tap, never an error line, never in the way of
the fortune that may follow."""
import io
import threading
import time
from types import SimpleNamespace

import pytest

from fish_brain import calaverita as cal
from fish_brain import cloud, texts, voice_guard
from fish_brain.config import Config
from fish_brain.conversation import FishConversation
from fish_brain.fortune_run import FortuneInput
from fish_brain.serial_link import MockSerialLink

VERSE = """Estudiaba el buen Rodrigo
cada puerta antes de entrar,
y a un negocio con su amigo
le dio todo sin dudar.

Llegó la Flaca por él
con su guadaña y su pluma;
él leyó todo el papel
y exigió que lo resuma.

La Flaca se fue sin nada:
de Slytherin no se cobra,
y él sigue en la madrugada
contando lo que le sobra."""


# ---- the verse --------------------------------------------------------------------------------
def test_a_good_verse_passes_with_its_stanzas():
    s = cal.clean_verse(VERSE)
    assert len(s) == 3 and all(len(x) == 4 for x in s) and s[1][0] == "Llegó la Flaca por él"


def test_markdown_a_title_and_a_house_line_are_taken_off():
    s = cal.clean_verse("**Calaverita de Rodrigo**\n\n" + VERSE.replace("Estudiaba", "*Estudiaba")
                        + "\nCASA: Slytherin")
    assert s == cal.clean_verse(VERSE)
    assert cal.clean_verse(VERSE.replace("\n\n", "\n")) == s      # twelve lines with no blanks


@pytest.mark.parametrize("raw, why", [
    ("", "empty"),
    ("\n".join(VERSE.splitlines()[:5]), "lines"),
    (VERSE.replace("le dio todo sin dudar.", "x " * 40), "long"),
    (VERSE.replace("sin nada", "[ETAPA 2]"), "a tag"),
    (VERSE.replace("sin nada", "sin su ex,"), "nunca: ex"),
    (VERSE.replace("sin nada", "sin Cabrón"), "nunca: cabrón"),
])
def test_a_bad_verse_is_refused_and_says_why(raw, why):
    assert cal.clean_verse(raw) is None
    assert why in "; ".join(cal.verse_problems(cal.stanzas_of(raw)))


def test_a_word_inside_another_is_not_a_hit():
    assert cal.clean_verse(VERSE.replace("sin nada", "su examen")) is not None


def test_the_voice_pauses_at_each_verse_without_doubling_a_mark():
    said = cal.spoken_verse((("uno", "dos,", "tres!", "cuatro;"), ("cinco", "seis", "siete", "ocho.")))
    assert said == "uno, dos, tres! cuatro. cinco, seis, siete, ocho."
    assert "\n" not in cal.spoken_verse(cal.clean_verse(VERSE))


def test_the_tag_carries_only_what_the_visit_knows():
    tag = cal.verse_tag("Ana", "Ravenclaw", "fiesta", {"edad": "adulto"}, ["Un libro", "A mi gato"])
    assert tag.startswith("[CALAVERITA: nombre=Ana; casa=Ravenclaw; lugar=fiesta;")
    assert 'dijo="Un libro"|"A mi gato"' in tag and "adulto" in tag and tag.endswith("]")
    assert "nombre" not in cal.verse_tag("", "Slytherin", "", {}, [])


# ---- meter, rhyme and the versions -------------------------------------------------------------
@pytest.mark.parametrize("line", [
    "Estudiaba el buen Rodrigo", "cada puerta antes de entrar,", "y a un negocio con su amigo",
    "le dio todo sin dudar.", "Llegó la Flaca por él", "con su guadaña y su pluma;",
    "él leyó todo el papel", "y exigió que lo resuma.", "La Flaca se fue sin nada:",
    "contando lo que le sobra."])
def test_the_scanner_counts_the_example_at_eight(line):
    assert cal.syllables(line) == 8


def test_what_rhymes():
    assert cal.pair_rhymes("con su pluma", "que lo resuma.")
    assert cal.pair_rhymes("la casa", "la taza") and cal.pair_rhymes("la cuenta", "la venta")
    assert cal.pair_rhymes("traía", "todavía")
    assert not cal.pair_rhymes("la vaca", "la vida")
    assert not cal.pair_rhymes("quien gane", "al gane")      # a word with itself


def test_the_fallbacks_rhyme():
    for letter in cal.HOUSE_KEYS:
        for verse in cal.FALLBACK[letter]:
            assert cal.bad_pairs(verse) == [] and cal.verse_metrics(verse)["near8"] == 12


LIMPING = VERSE.replace("contando lo que le sobra.", "contando lo que le queda.")


class Versions:
    """Answers from a list, the last again; `asked` what it was sent."""

    def __init__(self, *replies, error=None):
        self.replies, self.asked, self.error = list(replies), [], error
        self.last_error, self.thinking, self.extra_rules = None, None, ""

    def reset(self):
        self.extra_rules = ""

    def reply(self, text, remember=True):
        self.asked.append(text)
        self.last_error = self.error
        return self.replies.pop(0) if len(self.replies) > 1 else self.replies[0]


def test_compose_stops_at_the_first_full_rhyme_and_keeps_the_best():
    a, b = Versions(LIMPING), Versions(VERSE)
    r = cal.compose([a, b], "R", "[T]")
    assert r["rhymed"] == 3 and r["passes"] == 1 and r["versions"] == 2
    assert r["stanzas"] == cal.clean_verse(VERSE) and a.extra_rules == "R"


def test_compose_sends_the_best_back_with_the_pairs_that_do_not_rhyme():
    a = Versions(LIMPING, VERSE)
    r = cal.compose([a], "R", "[T]")
    assert r["passes"] == 2 and r["rhymed"] == 3
    assert a.asked[0] == "[T]" and a.asked[1].startswith("[T]\nTu borrador:")
    assert '"le dio todo sin dudar."' not in a.asked[1].split("no riman")[1]
    assert '"contando lo que le queda." ' not in a.asked[1] and "le queda" in a.asked[1].split("no riman")[1]


def test_compose_gives_up_after_its_passes_or_budget_with_the_best_it_had():
    a = Versions(LIMPING)
    r = cal.compose([a], "R", "[T]", passes=3)
    assert r["passes"] == 3 and r["rhymed"] == 2 and r["stanzas"]
    t = iter([0.0, 13.0, 13.0])
    r = cal.compose([Versions(LIMPING)], "R", "[T]", budget_s=12, clock=lambda: next(t))
    assert r["passes"] == 1


def test_compose_stops_when_every_client_fails_and_one_failure_is_not_fatal():
    bad = Versions("x", error="refusal")
    r = cal.compose([bad], "R", "[T]")
    assert r["error"] == "refusal" and r["stanzas"] is None and r["passes"] == 1
    r = cal.compose([Versions("x", error="boom"), Versions(VERSE)], "R", "[T]")
    assert r["error"] is None and r["rhymed"] == 3


def test_a_verse_that_never_fully_rhymes_is_the_house_clip(make, monkeypatch):
    p = Printer()
    c = make(llm=LLM(reply=LIMPING), printer=p)
    online_mode(c, monkeypatch)
    f = Fail()
    monkeypatch.setattr(c.show, "model_failed", f.model_failed)
    tap(c)
    assert len(c._llm.asked) == 4 and c.speaker.performed == [] and f.n == 0
    assert p.submitted[0].verse in cal.FALLBACK["R"]


# ---- the words file ---------------------------------------------------------------------------
def test_every_fallback_is_a_verse_with_no_name_and_rendered_clips_have_names():
    for letter in cal.HOUSE_KEYS:
        assert len(cal.FALLBACK[letter]) >= 2
        for name in cal.fallback_names(letter):
            assert name in cal.CALAVERITA_PHRASES
            assert cal.clean_verse(cal.page_verse(cal.fallback_stanzas(name)))
    assert all(n.startswith("calaverita_") for n in cal.CALAVERITA_PHRASES)


def test_a_broken_words_file_names_itself():
    good = texts.parse_lines(texts.DIR / "calaverita.toml")
    assert texts.check_calaverita(good)
    for broken, what in (({**good, "rules": ""}, "rules"), ({**good, "nunca": []}, "nunca"),
                         ({**good, "pools": {}}, "pools.lead"),
                         ({**good, "fallback": {"G": ["x"]}}, "fallback.H")):
        with pytest.raises(ValueError, match=what):
            texts.check_calaverita(broken)


def test_a_rehearsal_folder_from_before_it_uses_the_packages(monkeypatch, tmp_path):
    monkeypatch.setenv("FISH_PROMPTS_DIR", str(tmp_path))
    texts.calaverita.cache_clear()
    try:
        assert "LA BURLA" in texts.calaverita()["rules"]
    finally:
        monkeypatch.delenv("FISH_PROMPTS_DIR")
        texts.calaverita.cache_clear()


def test_the_rules_carry_la_burla_and_the_family_rule():
    r = cal.RULES
    assert "LA BURLA" in r and "NIÑOS Y ABUELAS" in r and "tres estrofas" in r


# ---- the act ----------------------------------------------------------------------------------
class Speaker:
    def __init__(self, *, perform_ok=True, sequence_ok=True, tts_error=False):
        self.stages, self.performed, self.last_timing = [], [], {}
        self.perform_ok, self.sequence_ok, self.tts_error = perform_ok, sequence_ok, tts_error
        self.log = []

    def say_sequence(self, names, *, wait_s=5.0, at=None):
        self.log.append(("say", list(names)))
        if not self.sequence_ok:
            return False
        self.stages.append(list(names))
        if at is not None and at[0] in names:
            at[1]()
        return True

    def synthesize(self, text, timing):
        if self.tts_error:
            raise OSError("no voice")
        timing["tts"] = 0.5
        return "/nonexistent/verse.wav"

    def perform(self, wav, text, timing):
        self.performed.append(text)
        return self.perform_ok

    def all(self):
        return [n for st in self.stages for n in st]


class LLM:
    extra_rules = ""

    def __init__(self, reply=VERSE, error=None, delay=0.0, raises=None):
        self.text, self.error, self.delay, self.raises = reply, error, delay, raises
        self.asked, self.rules_seen, self.thinking_seen = [], [], []
        self.last_error, self.thinking, self.last_latency_s = None, None, 0.1

    def reply(self, text, remember=True):
        assert remember is False
        self.asked.append(text)
        self.rules_seen.append(self.extra_rules)
        self.thinking_seen.append(self.thinking)
        time.sleep(self.delay)
        if self.raises:
            raise self.raises
        self.last_error = self.error
        return self.text

    def reset(self):
        self.extra_rules, self.thinking = "", None

    def remember(self, *a):
        raise AssertionError("the verse is never remembered")


class Printer:
    def __init__(self, submit=True):
        self.submitted, self.kept, self.ok, self.probes = [], [], submit, 0

    def submit(self, t):
        self.submitted.append(t)
        return self.ok

    def keep(self, t):
        self.kept.append(t)

    def probe(self):
        self.probes += 1


class Fail:
    def __init__(self):
        self.n = 0

    def model_failed(self):
        self.n += 1


@pytest.fixture
def make(monkeypatch, tmp_path):
    def build(*, llm=None, speaker=None, printer=None, mode="auto", house="Ravenclaw", first="Ana",
              rendered=True, ticket=True, profile="main"):
        monkeypatch.setenv("FISH_PERSONA", "hat")
        monkeypatch.setenv("FISH_SHOW", mode)
        monkeypatch.setenv("FISH_PLACE", "fiesta")
        monkeypatch.setenv("FISH_FORTUNE_ASK", "false")
        monkeypatch.setenv("OPENAI_API_KEY", "x" * 12)
        monkeypatch.setenv("ANTHROPIC_API_KEY", "x" * 12)
        monkeypatch.setenv("GROQ_API_KEY", "x" * 12)
        monkeypatch.setattr(cloud, "is_online", lambda: True)
        monkeypatch.setattr(voice_guard, "_state", voice_guard.CLEAN)
        cfg = Config()
        cfg.canned.cache_dir = tmp_path / "canned"
        cfg.show.state = str(tmp_path / "show.json")
        cfg.fortune.state = str(tmp_path / "fortune.json")
        cfg.fortune.ticket = ticket
        cfg.fortune.calaverita_profile = profile
        cfg.show.seed = "test"
        cfg.filler.enabled = False
        cfg.canned.cache_dir.mkdir(parents=True, exist_ok=True)
        if rendered:
            for name in cfg.canned.phrases:
                if name.startswith(("fortune_", "calaverita_")):
                    (cfg.canned.cache_dir / f"{name}-t.wav").touch()
        clock = SimpleNamespace(t=1000.0)
        c = FishConversation(cfg, MockSerialLink(cfg.serial, stream=io.StringIO()), text_input=True,
                             play_audio=False, clock=lambda: clock.t, printer=printer,
                             wait=lambda ev, s: ev.wait(0.01))
        c.speaker = speaker or Speaker()
        c._llm = llm if llm is not None else LLM()
        c.clock = clock
        if mode == "script":                      # these tests are about the clips
            c.show.model_ok = lambda: (False, "no trust")
        c.visit.start(first, clock.t)
        c.visit.set_cues({"edad": "adulto"})
        c.visit.hear("Un libro")
        c.visit.hear("A mi gato")
        if house:
            clock.t += 1
            c.visit.delivered(house, now=clock.t)
        return c
    return build


def tap(c, name=""):
    return c._handle_item(FortuneInput("calaverita", name))


def online_mode(c, monkeypatch):
    monkeypatch.setattr(c.show, "model_ok", lambda: (True, "trusted"))


def test_the_model_verse_is_said_shown_and_printed_after_the_lead(make, monkeypatch):
    p = Printer()
    c = make(printer=p)
    online_mode(c, monkeypatch)
    assert tap(c) is True
    assert c.speaker.performed == [cal.spoken_verse(cal.clean_verse(VERSE))]
    lead, tail = c.speaker.stages
    assert lead[0].startswith("calaverita_lead_") and lead[1].startswith("calaverita_suspense_")
    assert tail[-1].startswith("calaverita_cierre_")
    tag = c._llm.asked[0]
    assert "nombre=Ana" in tag and "casa=Ravenclaw" in tag and "lugar=fiesta" in tag
    assert 'dijo="Un libro"|"A mi gato"' in tag
    assert "LA BURLA" in c._llm.rules_seen[0] and c._llm.thinking_seen == [None]
    assert len(p.submitted) == 1
    t = p.submitted[0]
    assert t.first == "Ana" and t.casa == "Ravenclaw" and t.verse == cal.clean_verse(VERSE)
    assert p.probes == 1
    v = c.fortune.view()["calaverita"]
    assert v["last"]["verse"] == cal.page_verse(cal.clean_verse(VERSE)) and not v["busy"]


def test_the_model_starts_before_the_lead_is_said(make, monkeypatch):
    c = make()
    online_mode(c, monkeypatch)
    started = threading.Event()
    real = c._llm.reply
    c._llm.reply = lambda text, remember=True: (started.set(), real(text, remember))[1]
    say = c.speaker.say_sequence
    seen = []

    def spy(names, **kw):
        seen.append(started.wait(2))
        return say(names, **kw)
    c.speaker.say_sequence = spy
    tap(c)
    assert seen[0] is True


def test_a_second_tap_composes_again_in_the_window(make, monkeypatch):
    p = Printer()
    c = make(printer=p)
    online_mode(c, monkeypatch)
    tap(c)
    tap(c)
    assert len(c._llm.asked) == 2 and len(p.submitted) == 2


def test_the_script_says_the_house_clip_with_no_model(make):
    p = Printer()
    c = make(mode="script", printer=p, llm=LLM(raises=AssertionError("never")))
    tap(c)
    names = c.speaker.all()
    assert c._llm.asked == [] and c.speaker.performed == []
    assert any(n.startswith("calaverita_verso_R_") for n in names)
    assert names[0].startswith("calaverita_lead_") and names[-1].startswith("calaverita_cierre_")
    assert p.submitted[0].verse in cal.FALLBACK["R"]
    assert c.fortune.view()["calaverita"]["last"]["verse"]


@pytest.mark.parametrize("kw, failed", [
    (dict(error="connection lost"), 1),
    (dict(raises=RuntimeError("boom")), 1),
    (dict(error="refusal:violence"), 0),
    (dict(error="empty reply (stop_reason=end_turn)"), 0),
    (dict(reply="no es un verso"), 0),
    (dict(reply=VERSE.replace("sin nada", "sin su ex,")), 0),
])
def test_failures_end_in_the_clip_and_only_an_outage_tells_the_show(make, monkeypatch, kw, failed):
    p = Printer()
    c = make(llm=LLM(**kw), printer=p)
    online_mode(c, monkeypatch)
    f = Fail()
    monkeypatch.setattr(c.show, "model_failed", f.model_failed)
    tap(c)
    assert f.n == failed
    assert c.speaker.performed == []
    assert any(n.startswith("calaverita_verso_R_") for n in c.speaker.all())
    assert p.submitted[0].verse in cal.FALLBACK["R"]


def test_no_voice_for_the_verse_is_the_clip_and_no_outage(make, monkeypatch):
    c = make(speaker=Speaker(tts_error=True))
    online_mode(c, monkeypatch)
    f = Fail()
    monkeypatch.setattr(c.show, "model_failed", f.model_failed)
    tap(c)
    assert f.n == 0 and any(n.startswith("calaverita_verso_R_") for n in c.speaker.all())


def test_a_timeout_says_one_more_line_then_the_clip_and_parks_the_job(make, monkeypatch):
    c = make(llm=LLM(delay=0.4))
    online_mode(c, monkeypatch)
    f = Fail()
    monkeypatch.setattr(c.show, "model_failed", f.model_failed)
    t0 = time.monotonic()
    c.clock_step = 0
    real = c._clock

    def clock():
        return real() + (time.monotonic() - t0) * 100     # 0.2 s here is 20 s of the act's
    c._clock = clock
    tap(c)
    assert f.n == 1 and c._stale.get("llm") is not None
    names = c.speaker.all()
    assert sum(n.startswith("calaverita_suspense_mas_") for n in names) == 1
    assert any(n.startswith("calaverita_verso_R_") for n in names)
    c._stale["llm"].done.wait(2)


def test_an_older_job_still_running_goes_to_the_clip_at_once_with_no_outage(make, monkeypatch):
    c = make()
    online_mode(c, monkeypatch)
    f = Fail()
    monkeypatch.setattr(c.show, "model_failed", f.model_failed)
    c._stale["llm"] = SimpleNamespace(done=threading.Event())
    tap(c)
    assert c._llm.asked == [] and f.n == 0
    assert any(n.startswith("calaverita_verso_R_") for n in c.speaker.all())


def test_a_busy_speaker_moves_page_and_paper_to_what_was_said(make, monkeypatch):
    p = Printer()
    c = make(speaker=Speaker(perform_ok=False), printer=p)
    online_mode(c, monkeypatch)
    tap(c)
    assert p.submitted[0].verse in cal.FALLBACK["R"]
    assert c.fortune.view()["calaverita"]["last"]["verse"] != cal.page_verse(cal.clean_verse(VERSE))


def test_nothing_said_means_no_ticket_and_no_verse_on_the_page(make, monkeypatch):
    p = Printer()
    c = make(mode="script", speaker=Speaker(sequence_ok=False), printer=p)
    tap(c)
    assert p.submitted == []
    assert c.fortune.view()["calaverita"]["last"] is None


def test_tickets_off_keeps_it_for_reprint_and_a_printer_error_is_one_line(make, monkeypatch, capsys):
    p = Printer()
    c = make(mode="script", printer=p, ticket=False)
    tap(c)
    assert p.submitted == [] and len(p.kept) == 1
    p2 = Printer(submit=False)
    c2 = make(mode="script", printer=p2)
    tap(c2)
    assert "did not take the ticket" in capsys.readouterr().out


def test_an_exception_says_no_error_line_and_the_loop_goes_on(make, monkeypatch):
    p = Printer()
    c = make(mode="script", printer=p)
    monkeypatch.setattr(c.fortune.calaverita, "_compose",
                        lambda rec: (_ for _ in ()).throw(RuntimeError("boom")))
    assert tap(c) is True
    assert p.submitted == [] and c.speaker.all() == [] and not c.fortune.calaverita.busy


def test_clips_that_fail_during_the_wait_let_the_job_go(make, monkeypatch):
    c = make(llm=LLM(delay=0.05), speaker=Speaker(tts_error=True))
    online_mode(c, monkeypatch)
    monkeypatch.setattr(c.speaker, "say_sequence", lambda names, **kw: (_ for _ in ()).throw(ValueError("bad wav")))
    assert tap(c) is True
    assert c._stale.get("llm") is not None and not c.fortune.calaverita.busy
    c._stale["llm"].done.wait(2)


def test_a_stop_signal_starts_no_ticket(make, monkeypatch):
    p = Printer()
    c = make(mode="script", printer=p)

    def stop(rec):
        rec["stanzas"], rec["said"] = cal.FALLBACK["R"][0], True
        raise KeyboardInterrupt
    monkeypatch.setattr(c.fortune.calaverita, "_compose", stop)
    with pytest.raises(KeyboardInterrupt):
        tap(c)
    assert p.submitted == [] and not c.fortune.calaverita.busy


def test_a_scripted_house_still_gets_the_models_verse_and_echo_the_clips(make, monkeypatch):
    c = make(mode="script")                       # FISH_SHOW=script on the board
    online_mode(c, monkeypatch)
    tap(c)
    assert c._llm.asked and c.speaker.performed
    c = make(mode="script")
    online_mode(c, monkeypatch)
    c.echo = True
    tap(c)
    assert c._llm.asked == [] and c.speaker.performed == []


def test_a_verdict_from_the_script_gives_the_model_its_answers(make, monkeypatch):
    c = make(mode="script", house=None, first="")
    online_mode(c, monkeypatch)
    c.visit.heard = []
    c.show.start("test")
    while c.show.open:
        c.show.answer("no sé, la verdad")
    assert c.visit.house and "no sé, la verdad" in c.visit.heard
    tap(c, "Leo")
    assert "nombre=Leo" in c._llm.asked[0] and "no sé, la verdad" in c._llm.asked[0]


# ---- its own model ----------------------------------------------------------------------------
def own(monkeypatch, llm):
    built = []

    def make(cfg):
        built.append(cfg)
        return llm
    monkeypatch.setattr("fish_brain.llm.make_conversation", make)
    return built


def test_sonnet_writes_it_and_the_visits_model_is_never_asked(make, monkeypatch):
    sonnet = LLM()
    built = own(monkeypatch, sonnet)
    c = make(profile="claude-sonnet", llm=LLM(raises=AssertionError("never")))
    online_mode(c, monkeypatch)
    tap(c)
    tap(c)
    assert len(sonnet.asked) == 6 and c._llm.asked == []     # three versions a tap
    assert len(built) == 3 and built[0].model == "claude-sonnet-5-5"
    assert built[0].max_completion_tokens == 2000
    assert set(sonnet.thinking_seen) == {None}               # the profile's own
    assert c.speaker.performed


def test_sonnet_is_the_default_and_main_or_no_key_is_the_visits_model(make, monkeypatch):
    monkeypatch.delenv("FISH_CALAVERITA_PROFILE", raising=False)
    assert Config().fortune.calaverita_profile == "claude-sonnet"
    c = make(profile="claude-sonnet")
    r = c.fortune.calaverita
    assert r._own_profile() == "claude-sonnet"
    monkeypatch.delenv("ANTHROPIC_API_KEY")
    assert r._own_profile() == ""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "x" * 12)
    c.cfg.fortune.calaverita_profile = "main"
    assert r._own_profile() == ""
    c.cfg.fortune.calaverita_profile = "claude-sonnet"
    c.cfg.llm.profile = "claude-sonnet"                  # the board: still a client per version
    assert r._own_profile() == "claude-sonnet"


def test_a_sonnet_outage_does_not_script_the_visits(make, monkeypatch):
    own(monkeypatch, LLM(error="connection lost"))
    c = make(profile="claude-sonnet")
    online_mode(c, monkeypatch)
    f = Fail()
    monkeypatch.setattr(c.show, "model_failed", f.model_failed)
    tap(c)
    assert f.n == 0 and any(n.startswith("calaverita_verso_R_") for n in c.speaker.all())


def test_its_own_job_still_running_goes_to_the_clip_and_leaves_the_turns_alone(make, monkeypatch):
    sonnet = LLM()
    own(monkeypatch, sonnet)
    c = make(profile="claude-sonnet")
    online_mode(c, monkeypatch)
    c.fortune.calaverita._own_stale = SimpleNamespace(done=threading.Event())
    tap(c)
    assert sonnet.asked == [] and "llm" not in c._stale
    assert any(n.startswith("calaverita_verso_R_") for n in c.speaker.all())


# ---- when it may start ------------------------------------------------------------------------
def test_refusals_and_the_window(make):
    c = make(house=None)
    r = c.fortune.calaverita
    assert r.refusal() == "no house"
    assert c.fortune.view()["calaverita"]["lit"] is False
    tap(c)
    assert c.speaker.all() == []
    c = make()
    r = c.fortune.calaverita
    assert r.refusal() is None and c.fortune.view()["calaverita"]["lit"] is True
    c.clock.t += 600
    assert r.refusal() is None
    c.clock.t += 1
    assert r.refusal() == "too late"


def test_a_missing_clip_is_not_ready(make):
    c = make(rendered=False)
    assert c.fortune.calaverita.refusal() == "lines not ready"


def test_an_open_fortune_refuses_it(make):
    c = make()
    c.fortune.v = {"stage": "ask"}
    assert c.fortune.calaverita.refusal() == "act open"
    c.fortune.v = None


def test_the_visits_name_beats_the_typed_box_which_fills_in_when_there_is_none(make):
    p = Printer()
    c = make(mode="script", printer=p)
    tap(c, "Bruno")
    assert p.submitted[-1].first == "Ana"
    p2 = Printer()
    c2 = make(mode="script", printer=p2, first="")
    tap(c2, "Bruno")
    assert p2.submitted[-1].first == "Bruno"


def test_a_new_visitor_drops_the_last_verse_from_the_page(make):
    c = make(mode="script")
    tap(c)
    assert c.fortune.view()["calaverita"]["last"]
    c.visit.start("", c.clock.t)
    assert c.fortune.view()["calaverita"]["last"] is None


def test_the_fortune_afterwards_carries_name_house_and_cues(make, monkeypatch):
    c = make(mode="script")
    tap(c)
    assert c.visit.first_name == "Ana" and c.visit.house == "Ravenclaw"
    assert c.visit.view()["used"] == {"edad": "adulto"}
    c.clock.t += 5
    c._handle_item(FortuneInput("start", ""))
    assert c.fortune.open
    assert c.fortune.v["house"] == "Ravenclaw" and c.fortune.v["first"] == "Ana"
    assert c.fortune.v["pistas"].get("edad") == "adulto"


def test_the_verse_never_stays_in_the_models_history_and_next_act_has_its_rules(make, monkeypatch):
    c = make()
    online_mode(c, monkeypatch)
    tap(c)                                        # LLM.remember raises if it is called
    assert c._llm.extra_rules == c.cfg.fortune.calaverita_rules
    c.visit.start("", c.clock.t)
    assert c.visit.heard == []


def test_the_fish_has_no_calaverita(monkeypatch):
    monkeypatch.setenv("FISH_PERSONA", "fish")
    cfg = Config()
    assert not [n for n in cfg.canned.phrases if n.startswith("calaverita_")]


def test_the_record_goes_to_disk():
    from fish_brain import debug
    assert "calaverita" in debug._RECORD_KINDS
