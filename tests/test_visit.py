"""The hat's visit, pure: stages, the house line, the operator's cues."""
import re
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
    ("[ADIVINACIÓN: signo=Escorpio; luna=llena] Haz la lectura. Veo fuego.", "Haz la lectura. Veo fuego.", None),
    ("[adivinacion: nombre=Ana] Veo un gato.", "Veo un gato.", None),
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
    assert text == "[ETAPA 1/4] hola" and snap == {"at": 100.0, "cues": {}}
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
def test_cues_are_validated_cleaned_and_go_with_every_turn():
    clock = Clock()
    v = Visit(clock=clock)
    v.start()
    v.set_cues({"edad": "joven", "color": "azul", "lleva": "playera [de] dino;s=1\n",
                "impresion": ""})
    assert v.pending() == {"edad": "joven", "color": "azul", "lleva": "playera de dino,s 1"}
    text, snap = v.prepare("me llamo Ana")
    assert text == ("[ETAPA 1/4] [PISTAS: edad=joven; color=azul; lleva=playera de dino,s 1] "
                    "me llamo Ana")
    v.delivered(snapshot=snap)
    assert v.pending() == {"edad": "joven", "color": "azul", "lleva": "playera de dino,s 1"}
    assert v.view()["used"] == {}                      # nothing closed yet
    for n in (2, 3, 4):
        assert v.prepare("x")[0] == (f"[ETAPA {n}/4] [PISTAS: edad=joven; color=azul; "
                                     "lleva=playera de dino,s 1] x")
        v.delivered()


def test_the_latest_cue_rides_the_next_turn():
    clock = Clock()
    v = Visit(clock=clock)
    v.start()
    v.set_cues({"color": "azul", "edad": "adulto"})
    _, snap = v.prepare("x")
    clock.t += 1
    v.set_cues({"color": "rojo", "edad": "adulto"})
    v.delivered(snapshot=snap)
    assert v.pending() == {"color": "rojo", "edad": "adulto"}
    assert v.prepare("y")[0] == "[ETAPA 2/4] [PISTAS: edad=adulto; color=rojo] y"


def test_the_place_goes_first_and_alone_when_no_cue_is_lit():
    v = Visit(clock=Clock())
    v.start()
    assert v.prepare("x", "fiesta")[0] == "[ETAPA 1/4] [PISTAS: lugar=fiesta] x"
    v.set_cues({"compania": "pareja", "disfraz": "tenebroso"})
    assert v.prepare("x", "casa")[0] == ("[ETAPA 1/4] [PISTAS: lugar=casa; compañía=pareja; "
                                         "disfraz=tenebroso] x")


@pytest.mark.parametrize("value, said", [
    ("tímido", "timidez"), ("sonriente", "sonrisa"), ("curioso", "curiosidad"),
    ("escéptico", "escepticismo"), ("fiestero", "ganas de fiesta")])
def test_the_impression_is_said_as_a_noun(value, said):
    v = Visit(clock=Clock())
    v.start()
    v.set_cues({"impresion": value})
    assert v.pending() == {"impresion": value}            # the page keeps its own value
    assert v.prepare("x")[0] == f"[ETAPA 1/4] [PISTAS: impresión={said}] x"


def test_the_new_cue_set():
    assert visit.CUE_CHOICES["edad"] == ("joven", "adulto", "mayor")
    assert visit.CUE_CHOICES["compania"] == ("solo", "pareja", "amigos", "familia")
    assert visit.CUE_CHOICES["impresion"] == ("tímido", "sonriente", "curioso", "escéptico",
                                              "fiestero")
    assert visit.CUE_CHOICES["disfraz"] == ("tenebroso", "chistoso", "elegante")
    assert visit.CUE_ORDER == ("edad", "compania", "color", "impresion", "disfraz", "lleva",
                               "nota")
    v = Visit(clock=Clock())
    for old in ({"edad": "niño"}, {"edad": "adolescente"}, {"disfraz": "monstruo"}):
        with pytest.raises(ValueError):
            v.set_cues(old)


class Place:
    def __init__(self, place, text=""):
        self.place, self.text = place, text


@pytest.mark.parametrize("place, text, word", [
    ("casa", "", "casa"), ("fiesta", "la terraza", "fiesta"), ("universidad", "", "universidad"),
    ("otro", "  la terraza [del] Beto; ", "la terraza del Beto"), ("otro", "", ""),
    ("otro", "   ", ""), ("luna", "", "")])
def test_place_word(place, text, word):
    assert visit.place_word(Place(place, text)) == word


# ---- the cues' lifecycle -------------------------------------------------------------------
def _visit_to_verdict(v, clock, cues=None):
    """Three turns, then the verdict asked at clock.t and delivered 5 s later."""
    v.start("Ana")
    if cues:
        v.set_cues(cues)
    for _ in range(3):
        clock.t += 1
        v.delivered(snapshot=v.prepare("x")[1])
    clock.t += 1
    _, snap = v.prepare("x")
    return snap


def test_the_verdict_files_the_cues_and_clears_the_row():
    clock = Clock()
    v = Visit(clock=clock)
    snap = _visit_to_verdict(v, clock, {"color": "azul", "edad": "mayor"})
    clock.t += 5
    v.delivered("Ravenclaw", snap)
    assert v.done and v.pending() == {}
    assert v.view()["used"] == {"color": "azul", "edad": "mayor"}


def test_chips_tapped_during_the_verdicts_speech_are_the_next_visitors():
    clock = Clock()
    v = Visit(clock=clock)
    snap = _visit_to_verdict(v, clock, {"color": "azul", "edad": "mayor"})
    asked = clock.t
    clock.t += 2
    v.set_cues({"color": "azul", "edad": "joven"})       # while the verdict is said
    clock.t += 3
    v.delivered("Ravenclaw", snap)
    assert v._cut == asked
    assert v.pending() == {"edad": "joven"}               # azul kept its old stamp: filed
    assert v.view()["used"] == {"color": "azul"}
    clock.t += 1
    v.start("Leo")
    assert v.pending() == {"edad": "joven"} and v.view()["used"] == {}


def test_a_new_visitor_keeps_only_the_cues_set_after_the_cut():
    clock = Clock()
    v = Visit(clock=clock)
    snap = _visit_to_verdict(v, clock)
    v.delivered("Ravenclaw", snap)
    clock.t += 1
    v.set_cues({"color": "verde"})                       # for the next visitor
    clock.t += 1
    v.start()
    assert v.pending() == {"color": "verde"}


def test_the_last_stage_without_a_house_closes_too():
    clock = Clock()
    v = Visit(clock=clock)
    snap = _visit_to_verdict(v, clock, {"color": "rosa"})
    v.delivered(None, snap)
    assert v.done and v.pending() == {} and v.view()["used"] == {"color": "rosa"}


def test_a_close_without_a_snapshot_cuts_at_the_given_time_or_now():
    clock = Clock()
    v = Visit(clock=clock)
    v.start()
    v.set_cues({"color": "rojo"})                        # stamped 100
    clock.t = 110
    v.set_cues({"color": "rojo", "edad": "adulto"})     # edad stamped 110
    clock.t = 120
    v.delivered("Gryffindor", None, cut=105)             # the script's verdict
    assert v._cut == 105 and v.pending() == {"edad": "adulto"}
    v2 = Visit(stages=1, clock=clock)
    v2.start()
    v2.set_cues({"color": "rojo"})
    v2.delivered()
    assert v2._cut == 120 and v2.pending() == {}


def test_a_restart_for_the_same_visitor_keeps_every_cue():
    clock = Clock()
    v = Visit(clock=clock)
    v.start()
    v.set_cues({"color": "azul"})                         # stamped 100
    clock.t = 110
    v.delivered()                                         # a delivered turn after it
    clock.t = 120
    v.start(keep_cues=True)                               # the hand-over, a rebuilt model
    assert v.pending() == {"color": "azul"}


def test_a_visit_left_without_a_verdict_cuts_at_its_last_turn():
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


def test_next_act_carries_the_last_visitors_cues_or_prunes():
    clock = Clock()
    v = Visit(clock=clock)
    snap = _visit_to_verdict(v, clock, {"color": "azul", "edad": "mayor"})
    v.delivered("Ravenclaw", snap)
    clock.t += 1
    v.set_cues({"edad": "joven"})                         # re-set after the verdict
    clock.t += 1
    v.next_act(carry=True)                                # the same visitor's fortune
    assert v.pending() == {"color": "azul", "edad": "joven"}   # the current cue wins
    clock.t += 1
    v.close(clock.t)                                      # the fortune's last line
    assert v.pending() == {} and v.view()["used"] == {"color": "azul", "edad": "joven"}
    clock.t += 1
    v.set_cues({"color": "verde"})
    clock.t += 1
    v.next_act(carry=False)                               # someone else's fortune
    assert v.pending() == {"color": "verde"} and v.view()["used"] == {}


def test_a_fortune_with_no_visit_before_keeps_what_is_lit():
    clock = Clock()
    v = Visit(clock=clock)
    v.set_cues({"color": "verde"})
    v.next_act(carry=False)
    assert v.pending() == {"color": "verde"}


def test_a_turn_not_delivered_keeps_every_cue():
    v = Visit(clock=Clock())
    v.start()
    v.set_cues({"color": "verde"})
    v.prepare("x")
    assert v.pending() == {"color": "verde"}


@pytest.mark.parametrize("bad", [
    "nope", {"edad": "anciano"}, {"sabor": "fresa"}, {"lleva": 3}, {"edad": "niño"}])
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
    assert len(visit.clean_cue_text("a" * 200, 120)) == 120          # the fortune's dream


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
    assert set(v.view()) == {"n", "stage", "of", "first", "house", "cues", "used"}
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


# ---- the verdict's future ---------------------------------------------------------------------
import random  # noqa: E402

BANK = {"hours": ["11:30", "16:45"], "card_odds": 0.5, "lugar": ["la Plaza de las Artes", "la torre morada"],
        "cosa": ["un ajolote impreso en 3D", "un dron"], "carta": ["El sol"]}


def test_only_the_verdict_carries_the_future():
    v = Visit(clock=Clock(), future=BANK, rng=random.Random(3))
    v.start()
    for n in (1, 2, 3):
        assert "[FUTURO" not in v.prepare("x")[0]
        v.delivered()
    tagged = v.prepare("investigo")[0]
    assert tagged.startswith("[ETAPA 4/4] [FUTURO: hora=") and tagged.endswith("] investigo")


def test_the_future_is_random_but_seeded_and_within_the_hours():
    a = [visit.future_tag(BANK, random.Random(5)) for _ in range(2)]
    assert a[0] == a[1]
    many = {visit.future_tag(BANK, random.Random(s)) for s in range(30)}
    assert len(many) > 5
    rng = random.Random(9)
    for _ in range(200):
        h = re.search(r"hora=las? (\d+)(?: y (\d+)| en punto)", visit.future_tag(BANK, rng))
        hour, minute = int(h.group(1)), int(h.group(2) or 0)
        t = (hour if hour >= 11 else hour + 12) * 60 + minute     # 11, 12, then 1..4 pm
        assert 11 * 60 + 30 <= t <= 16 * 60 + 45


def test_no_bank_no_future_and_an_echoed_tag_is_never_spoken():
    v = Visit(clock=Clock())
    v.start()
    v.said = 3
    assert "[FUTURO" not in v.prepare("x")[0]
    assert visit.say_hour(13 * 60 + 5) == "la 1 y 5" and visit.say_hour(15 * 60) == "las 3 en punto"
    assert split_reply("[FUTURO: lugar=x] ¡Ravenclaw!\nCASA: Ravenclaw") == ("¡Ravenclaw!", "Ravenclaw")


@pytest.mark.parametrize("said,reply,name", [
    ("Fernando.", "Fernando, veo una mente que se guarda.", "Fernando"),
    ("Hola, soy Albert.", "¡Albert! Veo una ceja.", "Albert"),
    ("Iván.", "Iván… veo un fuego.", "Iván"),
    ("Ivan.", "Iván, veo.", "Iván"),
    ("María José.", "María José, veo.", "María José"),
    ("María.", "María José, veo.", "María"),
    ("Escorpio.", "Escorpio, veo.", ""),
    ("Hola.", "¡Hola! Dime tu nombre.", ""),
    ("Ravenclaw.", "¡Ravenclaw! Claro.", ""),
    ("Cumplen.", "Fernando, veo.", ""),
    ("Carlos.", "Mira, Carlos, veo.", "Carlos"),
    ("Buenas.", "¡Buenas! Dime tu nombre, criatura.", ""),
    ("¡Feliz Halloween! Soy Ana.", "¡Feliz Halloween, Ana! Veo.", "Ana"),
    ("Nada, solo vine a ver.", "Nada, dices. Eso dicen todos.", ""),
    ("Vengo de Guadalajara.", "Guadalajara, tierra de valientes.", ""),
    ("Tengo miedo.", "Miedo. Eso lo huelo.", ""),
    ("Con amigos.", "Amigos, ya veo.", ""),
    ("Me llamo Leo.", "Leo, veo una melena.", "Leo"),
    ("Juan. Juan Delgado.", "Juan, veo.", "Juan"),
    ("Mucho gusto, soy Carla.", "¡Mucho gusto, Carla! Veo una cabeza.", "Carla"),
    ("Soy de Guadalajara.", "¿De Guadalajara? Tierra de valientes.", ""),
    ("Muy bien, gracias.", "Muy bien, me alegra. ¿Y tu nombre?", ""),
    ("Soy un fantasma.", "Un fantasma, ¿eh? Te veo.", ""),
    ("Mi nombre es secreto.", "Secreto, ¿eh?", ""),
    ("Encantada.", "Encantada, dices.", ""),
    ("Dime qué casa me toca.", "¿Qué casa te toca? Primero tu nombre.", ""),
])
def test_the_name_heard_is_the_one_the_hat_echoed(said, reply, name):
    from fish_brain.visit import heard_name
    assert heard_name(said, reply) == name


def test_another_act_for_someone_else_forgets_the_name_the_same_visitor_keeps_it():
    from fish_brain.visit import Visit
    v = Visit()
    v.start("", 0.0)
    v.first_name = "Fernando"                 # heard at the greeting
    v.next_act(carry=True, now=1.0)
    assert v.first_name == "Fernando"
    v.next_act(carry=False, now=2.0)          # the fortune's visitor is someone else
    assert v.first_name == ""
    v.first_name = "Ana"
    v.start("", 3.0, keep_cues=True)          # the same visitor, a rebuilt model
    assert v.first_name == "Ana"
    v.start("", 4.0)                          # a new visitor
    assert v.first_name == ""
