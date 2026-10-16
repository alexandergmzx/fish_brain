"""The hat's visit, pure: stages, the house line, the operator's cues."""
import threading

import pytest

from fish_brain import visit
from fish_brain.visit import Visit, split_reply


class Clock:
    def __init__(self, t=100.0):
        self.t = t

    def __call__(self):
        return self.t


# ---- the house line ---------------------------------------------------------------------
@pytest.mark.parametrize("reply, spoken, house", [
    ("¡Ravenclaw te espera!\nCASA: Ravenclaw", "¡Ravenclaw te espera!", "Ravenclaw"),
    ("Valiente.\n**CASA:** Gryffindor.", "Valiente.", "Gryffindor"),
    ("Leal.\ncasa: hufflepuff", "Leal.", "Hufflepuff"),
    ("Eres astuto.\n- CASA: Slitherin", "Eres astuto.", "Slytherin"),
    ("Tu casa.\nCASA: Grifindor\nY hoy verás un robot.", "Tu casa. Y hoy verás un robot.",
     "Gryffindor"),
    ("Hoy verás algo azul en la feria. CASA: Hufflepuff", "Hoy verás algo azul en la feria.",
     "Hufflepuff"),
    ("Tu casa es Gryffindor.", "Tu casa es Gryffindor.", None),
    ("Tu casa: Gryffindor, sin duda.", "Tu casa: Gryffindor, sin duda.", None),
    ("Bienvenido.\nCASA: Hogwarts", "Bienvenido.", None),
    ("[ETAPA 3/4] Veo algo [PISTAS: color=azul] azul.", "Veo algo azul.", None),
    ("[FIN] Adiós.", "Adiós.", None),
    ("CASA: Ravenclaw", "", "Ravenclaw"),
    ("", "", None),
])
def test_split_reply(reply, spoken, house):
    assert split_reply(reply) == (spoken, house)


def test_house_of_ignores_case_accents_and_markdown():
    assert visit.house_of("**RÁVENCLAW.**") == "Ravenclaw"
    assert visit.house_of("  gryffindor") == "Gryffindor"
    assert visit.house_of("Hogwarts") is None and visit.house_of("") is None


# ---- stages -----------------------------------------------------------------------------
def test_stages_advance_only_when_delivered():
    clock = Clock()
    v = Visit(clock=clock)
    assert v.stage == 0 and v.needs_new(clock())
    v.start("Ana")
    assert v.stage == 1 and not v.needs_new(clock())
    text, snap = v.prepare("hola")
    assert text == "[ETAPA 1/4] hola" and snap == {}
    assert v.prepare("hola")[0] == "[ETAPA 1/4] hola"          # prepare does not advance
    for n in (2, 3, 4):
        v.delivered()
        assert v.stage == n and v.prepare("x")[0] == f"[ETAPA {n}/4] x"
    v.delivered()
    assert v.done and v.stage == 5 and v.needs_new(clock())


def test_a_house_closes_the_visit_early():
    v = Visit(clock=Clock())
    v.start()
    v.delivered()
    v.delivered("Slytherin")
    assert v.done and v.house == "Slytherin" and v.view()["stage"] == 5


def test_idle_counts_from_the_hats_last_speech():
    clock = Clock()
    v = Visit(idle_s=30, clock=clock)
    v.start()
    v.delivered(now=100)
    assert not v.needs_new(125)
    assert not v.needs_new(99)                  # started talking before the hat was done
    assert v.needs_new(131)
    v.touch(140)
    assert not v.needs_new(160)
    v.idle_s = 0                                # 0 = never expires
    assert not v.needs_new(10_000)
    v.end()
    v.touch(1)                                  # no-op when closed
    assert v.needs_new(0)


def test_a_request_starts_a_new_visit_and_start_clears_it():
    clock = Clock()
    v = Visit(clock=clock)
    v.start()
    v.request_new(101)
    assert v.needs_new(101)
    v.cancel_request(99)                        # another request's stamp: kept
    assert v.needs_new(101)
    v.cancel_request(101)
    assert not v.needs_new(101)
    v.request_new(102)
    clock.t = 103
    v.start()
    assert not v.needs_new(103) and v.n == 2


# ---- cues -------------------------------------------------------------------------------
def test_cues_are_validated_cleaned_and_tagged_once():
    clock = Clock()
    v = Visit(clock=clock)
    v.start()
    v.set_cues({"edad": "niño", "color": "azul", "lleva": "playera [de] dino;s=1\n",
                "impresion": ""})
    assert v.pending() == {"edad": "niño", "color": "azul", "lleva": "playera de dino,s 1"}
    text, snap = v.prepare("me llamo Ana")
    assert text == ("[ETAPA 1/4] [PISTAS: edad=niño; color=azul; lleva=playera de dino,s 1] "
                    "me llamo Ana")
    v.delivered(snapshot=snap)
    assert v.pending() == {} and v.view()["sent"]["color"] == "azul"
    assert v.prepare("x")[0] == "[ETAPA 2/4] x"


def test_a_cue_retapped_after_prepare_stays_pending():
    clock = Clock()
    v = Visit(clock=clock)
    v.start()
    v.set_cues({"color": "azul", "edad": "adulto"})
    _, snap = v.prepare("x")
    clock.t += 1
    v.set_cues({"color": "rojo", "edad": "adulto"})
    v.delivered(snapshot=snap)
    assert v.pending() == {"color": "rojo"}


def test_a_turn_not_delivered_keeps_every_cue():
    v = Visit(clock=Clock())
    v.start()
    v.set_cues({"color": "verde"})
    v.prepare("x")
    assert v.pending() == {"color": "verde"}


def test_an_unchanged_cue_keeps_its_stamp_and_start_drops_the_old_visitors():
    clock = Clock(100)
    v = Visit(clock=clock)
    v.start()
    v.set_cues({"edad": "adulto"})               # stamped 100
    clock.t = 110
    v.delivered(now=110)                         # the old visitor's last answer
    clock.t = 120
    v.set_cues({"edad": "adulto", "color": "rosa"})   # edad keeps 100, color is new
    clock.t = 125
    v.start("Sofía")
    assert v.pending() == {"color": "rosa"} and v.first_name == "Sofía"


@pytest.mark.parametrize("bad", [
    "nope", {"edad": "anciano"}, {"sabor": "fresa"}, {"lleva": 3}])
def test_bad_cues_are_refused_without_echoing_text(bad):
    v = Visit(clock=Clock())
    with pytest.raises(ValueError) as e:
        v.set_cues(bad)
    assert "fresa" not in str(e.value) and "anciano" not in str(e.value)


def test_free_text_is_capped_and_never_starts_with_a_dash():
    assert visit.clean_cue_text("- " + "x" * 80) == "x" * 58
    assert len(visit.clean_cue_text("a" * 80)) == 60
    assert visit.clean_cue_text("<b>{hola}</b>") == "b hola /b"
    assert visit.clean_cue_text(None) == ""


def test_set_cues_from_another_thread_while_preparing():
    v = Visit(clock=Clock())
    v.start()
    stop = threading.Event()

    def tap():
        i = 0
        while not stop.is_set():
            v.set_cues({"color": visit.CUE_CHOICES["color"][i % 8]})
            i += 1

    t = threading.Thread(target=tap)
    t.start()
    try:
        for _ in range(500):
            text, snap = v.prepare("x")
            v.delivered(snapshot=snap)
            v.said = 0
    finally:
        stop.set()
        t.join()


def test_view_has_exactly_the_sheets_keys():
    v = Visit(clock=Clock())
    assert set(v.view()) == {"n", "stage", "of", "first", "house", "cues", "sent"}
    assert v.view()["first"] == ""
    v.start("Ana")
    assert v.view()["first"] == "Ana" and v.view()["n"] == 1


def test_note_and_begin_model():
    assert visit.note("Se llama {first}.{look} Fin", "Ana", "gorra") == \
        "Se llama Ana. Lleva: gorra. Fin"
    assert visit.note("{first}{look} {x}", "Ana") == "Ana {x}"

    class LLM:
        extra_rules = "old"
        resets = 0

        def reset(self):
            self.resets += 1
            self.extra_rules = ""

    llm = LLM()
    visit.begin_model(llm, "reglas")
    assert llm.resets == 1 and llm.extra_rules == "reglas"
