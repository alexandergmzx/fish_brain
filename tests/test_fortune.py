"""fortune.py: the fortune act's parsers hear dates, signs, dreams, wishes, cards (and a yes
or a no to one), shapes, the moon is right on its check dates, the tag and the filter are
exact; fortune_run's pure steps draw and deal as the act does."""
from datetime import datetime, timezone

import pytest

from fish_brain import fortune
from fish_brain.fortune import (DECKS, DREAM_THEMES, MOON_PHASES, SIGNS, Fortune,
                                clean_reading, dream_theme, lucky_number, moon_phase,
                                moon_tonight, numbers_in, parse_birth, parse_card, parse_shape,
                                parse_sign, reading_tag, sign_of, strip_notes, tokens)
from fish_brain.show import ShowState, phon_key

TAROT = DECKS["tarot"]


# ---- words and numbers ----------------------------------------------------------------------
def test_tokens_fold_keep_digits_and_split_dates():
    assert tokens("El 23/10, Año nuevo [Nota: ruido] 1ro") == ["el", "23", "10", "ano", "nuevo", "1", "ro"]
    assert strip_notes("sí [Nota: se oye música] claro [x]") == "sí claro"
    assert tokens("") == []


@pytest.mark.parametrize("text,expect", [
    ("23", [(0, 23)]), ("veintitrés", [(0, 23)]), ("treinta y uno", [(0, 31)]),
    ("veinti tres de octubre", [(0, 23)]), ("el primero de mayo", [(1, 1)]),
    ("5 de marzo de 2015", [(0, 5)]), ("1990", []), ("diez y seis", [(0, 16)]),
    ("una noche cualquiera", []), ("cero", [(0, 0)]),
])
def test_numbers_in(text, expect):
    assert numbers_in(tokens(text)) == expect


# ---- the birth date -------------------------------------------------------------------------
@pytest.mark.parametrize("text,expect", [
    ("el 23 de octubre", (23, 10)), ("veintitrés de octubre", (23, 10)),
    ("nací el 5 de marzo de 2015", (5, 3)), ("octubre 23", (23, 10)), ("23/10", (23, 10)),
    ("el primero de mayo", (1, 5)), ("diez del once", (10, 11)),
    ("treinta y uno de diciembre", (31, 12)), ("29 de febrero", (29, 2)),
    ("un 23 de octubre [Nota: risas]", (23, 10)), ("2 de setiembre", (2, 9)),
    ("el veinti tres de otubre", (23, 10)),               # a spelling slip, by sound
    ("dos de disiembre del noventa", (2, 12)),
])
def test_birth_dates_heard(text, expect):
    assert parse_birth(text) == expect


@pytest.mark.parametrize("text", [
    "", "no sé", "nací en octubre", "31 de febrero", "30 de febrero", "31 de abril",
    "una noche de octubre", "el 32 de enero", "15 del 13", "en mil novecientos noventa",
])
def test_bad_dates_are_none(text):
    assert parse_birth(text) is None


# ---- the zodiac -----------------------------------------------------------------------------
def test_every_sign_boundary_both_sides():
    order = [s.id for s in SIGNS]
    for i, s in enumerate(SIGNS):
        month, day = s.start
        assert sign_of(day, month) == s.id
        before = (day - 1, month) if day > 1 else (31, month - 1)
        assert sign_of(*before) == order[i - 1]
    assert sign_of(1, 1) == "capricornio" and sign_of(19, 1) == "capricornio"
    assert sign_of(20, 1) == "acuario" and sign_of(31, 12) == "capricornio"
    assert sign_of(23, 10) == "escorpio" and sign_of(22, 10) == "libra"
    assert sign_of(21, 6) == "cancer" and fortune.SIGN_BY_ID["cancer"].said == "Cáncer"


def test_signs_have_elements_and_names():
    assert len(SIGNS) == 12 and len({s.id for s in SIGNS}) == 12
    assert {s.element for s in SIGNS} == {"fuego", "tierra", "aire", "agua"}
    assert all(s.said and s.name and s.aliases[0] == s.id for s in SIGNS)


@pytest.mark.parametrize("text,expect", [
    ("soy escorpio", "escorpio"), ("escorpión", "escorpio"), ("Cáncer", "cancer"),
    ("soy de capricornio", "capricornio"), ("géminis", "geminis"), ("eskorpio", "escorpio"),
    ("leo o virgo", None), ("una fiesta", None), ("", None), ("tauro", "tauro"),
])
def test_signs_said_directly(text, expect):
    assert parse_sign(text) == expect


@pytest.mark.parametrize("day,month,expect", [(23, 10, 6), (31, 12, 7), (1, 1, 2), (29, 9, 2), (9, 9, 9)])
def test_lucky_number_is_one_digit(day, month, expect):
    assert lucky_number(day, month) == expect
    assert 1 <= lucky_number(day, month) <= 9


# ---- the dream ------------------------------------------------------------------------------
def test_the_21_themes_and_their_keywords_are_distinct():
    ids = [t.id for t in DREAM_THEMES]
    assert len(ids) == 21 and ids[-2:] == ["nada", "otro"]
    assert {"ex", "desnudo", "fortuna", "dientes", "seres_queridos", "perseguido"} <= set(ids)
    assert fortune.DREAM_BY_ID["dientes"].weight == 2 and fortune.DREAM_BY_ID["seres_queridos"].weight == 2
    seen = {}
    for t in DREAM_THEMES:
        for k in t.keywords:
            assert k not in seen, (k, t.id, seen.get(k))
            seen[k] = t.id
            assert dream_theme(k.replace("*", "")) == t.id, (k, t.id)   # heard alone, its own


@pytest.mark.parametrize("text,expect", [
    ("soñé que se me caían los dientes en la boda de mi prima", "dientes"),   # weight 2 over caer
    ("me perseguía un señor con una pistola", "perseguido"),                  # chase beats violence
    ("mi abuelita que ya murió me perseguía", "seres_queridos"),
    ("soñé con la ofrenda de mi abuela", "seres_queridos"),
    ("corría lento y no llegaba", "tarde"), ("perdí el camión", "tarde"),
    ("era bruja y volaba", "volar"), ("una araña y una víbora", "bichos"),   # a tie: first mentioned
    ("una víbora y una araña", "serpientes"),
    ("soñé con mi ex", "ex"), ("andaba sin ropa en la oficina", "desnudo"),
    ("me saqué la lotería", "fortuna"), ("tenía sexo con mi novio", "otro"),
    ("estaba embarazada", "otro"), ("soñé con dios y los ángeles", "otro"),
    ("me mataban en una guerra", "otro"),
    ("no me acuerdo", "nada"), ("no soñé nada", "nada"), ("no sé", "nada"),
    ("no me acuerdo bien pero había una araña", "bichos"),                    # content beats nada
    ("la pizza con queso", "jugar"), ("me caía al vacío [Nota: ruido]", "caer"),
    ("se me hacía tarde para el examen", "tarde"),                            # a tie: first mentioned
])
def test_dream_themes_heard(text, expect):
    assert dream_theme(text) == expect


NEW_ANIMAL_STEMS = ("borreg*", "oveja*", "rebano*", "cabra*", "ajolote*", "gallina*", "pato*",
                    "zorro*", "xolo*")


def test_the_new_animal_stems_are_the_animals_own():
    animals = fortune.DREAM_BY_ID["animales"].keywords
    assert "borrego" not in animals and "xolo" not in animals
    for stem in NEW_ANIMAL_STEMS:
        assert stem in animals, stem
        body = stem[:-1]
        for t in DREAM_THEMES:
            if t.id == "animales":
                continue
            for k in t.keywords:          # no word of another theme starts with the stem
                assert not any(w.startswith(body) or (w.endswith("*") and body.startswith(w[:-1]))
                               for w in k.split()), (stem, t.id, k)


@pytest.mark.parametrize("text,expect", [
    ("Soñé con unos borreguitos", "animales"), ("un rebaño de ovejas", "animales"),
    ("unas cabras en el monte", "animales"), ("un ajolote rosa", "animales"),
    ("las gallinas de mi rancho", "animales"), ("unos patos en el lago", "animales"),
    ("un zorro", "animales"), ("mi xoloitzcuintle", "animales"),
    # his mixed dream: the relative (weight 2) is mentioned first and wins the tie
    ("Soñé con mi tío y un rebaño de borreguitos", "seres_queridos"),
])
def test_the_wider_animal_dreams(text, expect):
    assert dream_theme(text) == expect


@pytest.mark.parametrize("text", ["", "   ", "hola qué tal", "[Nota: silencio]"])
def test_no_dream_words_is_none(text):
    assert dream_theme(text) is None


# ---- the cards ------------------------------------------------------------------------------
def test_the_deck_is_whole():
    cards = TAROT["cards"]
    assert [c.n for c in cards] == list(range(22)) and TAROT["numbers"] and TAROT["id"] == "tarot"
    assert fortune.card_by_n(TAROT, 13).said == "La Muerte" and fortune.card_by_n(TAROT, 15).es == "El Diablo"
    assert all(c.en and c.es and c.said and c.meaning and len(c.aliases) >= 3 for c in cards)
    with pytest.raises(KeyError):
        fortune.card_by_n(TAROT, 22)


@pytest.mark.parametrize("text,expect", [
    ("la muerte", 13), ("death", 13), ("el loco", 0), ("the fool", 0), ("ful", 0), ("mun", 18),
    ("trece", 13), ("13", 13), ("la carta trece", 13), ("me salió la torre", 16),
    ("el diablo", 15), ("los enamorados", 6), ("la rueda de la fortuna", 10), ("el ahorcado", 12),
    ("el ermitanio", 9),                                                   # by sound
    ("el número 5", 5), ("la estrella", 17), ("star", 17), ("el sol", 19), ("el papa", 5),
    ("la emperatriz", 3), ("el emperador", 4), ("veintiuno", 21), ("cero", 0),
    ("the hanged man [Nota: en inglés]", 12),
])
def test_cards_heard(text, expect):
    assert parse_card(text, TAROT) == expect


@pytest.mark.parametrize("text", ["", "hola", "la torre y la luna", "el 5 o el 7", "22", "la muerta"])
def test_two_cards_or_none_is_none(text):
    assert parse_card(text, TAROT) is None


# ---- the cup, the wish, the card's yes or no --------------------------------------------------------------------
def test_the_eleven_shapes():
    assert [t.id for t in fortune.CUP_SHAPES] == ["estrella", "corazon", "luna", "anillo", "animal",
                                                  "arbol", "ojo", "nube", "llave", "calabaza", "nada"]
    for t in fortune.CUP_SHAPES:
        for k in t.keywords:
            assert parse_shape(k.replace("*", "")) == t.id, (k, t.id)


@pytest.mark.parametrize("text,expect", [
    ("una estrella", "estrella"), ("un corazón", "corazon"), ("veo un gato", "animal"),
    ("nada", "nada"), ("no veo nada", "nada"), ("una calavera", "calabaza"), ("hojas", "arbol"),
    ("una estrella, no, nada", "estrella"), ("mmm", None), ("", None), ("un ojo", "ojo"),
])
def test_shapes_heard(text, expect):
    assert parse_shape(text) == expect


@pytest.mark.parametrize("text,expect", [
    ("Amor.", "amor"), ("Que me vaya bien con mi novia.", "amor"), ("que regrese mi ex", "amor"),
    ("Dinero, ya que estamos.", "dinero"), ("un trabajo nuevo", "dinero"), ("lana", "dinero"),
    ("Salud.", "salud"), ("salud para mi familia", "salud"),
    ("Venganza.", "venganza"), ("venganza contra mi ex", "venganza"),   # venganza weighs 2
    ("Que te calles.", "otro"), ("que mis alumnos lean", "otro"), ("", None),
])
def test_the_wish(text, expect):
    assert fortune.parse_wish(text) == expect


def test_every_wish_keyword_lands_on_its_wish():
    for t in fortune.WISHES:
        for k in t.keywords:
            assert fortune.parse_wish(k.replace("*", "")) == t.id, (k, t.id)
    assert fortune.WISH_IDS == ("amor", "dinero", "salud", "venganza")


@pytest.mark.parametrize("text,expect", [
    ("Sí.", "yes"), ("Sí, porfa.", "yes"), ("Bueno, sí.", "yes"), ("Sí, échamela.", "yes"),
    ("Bueno, a ver.", "yes"), ("¿Por qué no?", "yes"), ("Órale", "yes"), ("simón", "yes"),
    ("No.", "no"), ("Nel.", "no"), ("No, gracias, no me gustan esas cosas.", "no"),
    ("Mejor no", "no"), ("sí, no, mejor no", "no"), ("Paso", "no"),
    ("La que sea.", "yes"), ("Cualquiera.", "yes"), ("emm", None), ("", None),
])
def test_the_yes_or_no_to_a_card(text, expect):
    assert fortune.parse_yes_no(text) == expect


def test_a_card_said_upside_down():
    assert fortune.said_reversed("La Torre, de cabeza")
    assert fortune.said_reversed("el diablo invertido") and fortune.said_reversed("al revés")
    assert not fortune.said_reversed("La Torre")


# ---- the moon -------------------------------------------------------------------------------
def test_moon_check_values_october_2026():
    assert len(MOON_PHASES) == 8
    assert moon_phase(datetime(2026, 10, 26, 20, 0)) == "llena"              # full 26th 04:12 UTC
    assert moon_phase(datetime(2026, 10, 10, 20, 0)) == "nueva"              # new 10th 15:50 UTC
    assert moon_phase(datetime(2026, 10, 18, 20, 0)) == "cuarto_creciente"   # 18th 16:13 UTC
    assert moon_phase(datetime(2026, 10, 3, 20, 0)) == "cuarto_menguante"    # 3rd 13:25 UTC
    assert moon_phase(datetime(2026, 10, 14, 20, 0)) == "creciente"
    assert moon_phase(datetime(2026, 10, 22, 20, 0)) == "gibosa_creciente"
    assert moon_phase(datetime(2026, 10, 30, 20, 0, tzinfo=timezone.utc)) == "gibosa_menguante"
    assert moon_phase(datetime(2026, 11, 6, 20, 0)) == "menguante"
    assert moon_tonight(datetime(2026, 10, 31, 20, 0)) in MOON_PHASES


def test_an_insane_clock_gives_no_moon():
    assert moon_tonight(datetime(1970, 1, 1)) is None
    assert moon_tonight(datetime(2025, 12, 31, 23, 59)) is None
    assert moon_tonight() in (None, *MOON_PHASES)


# ---- the tag --------------------------------------------------------------------------------
def test_the_tag_exact_string():
    f = Fortune(nombre="Ana", lugar="fiesta", casa="Ravenclaw", fecha=(23, 10), signo="escorpio",
                numero=6, sueno="dientes", sueno_txt="se me caían los dientes en la boda de mi prima",
                deseo="venganza", deseo_txt="contra mi ex", carta=13, carta_de="sombrero",
                carta_reves=True, taza="estrella", luna="llena", palabra="Zumbalí",
                hoy="jueves 29 de octubre", gancho="una llave que ya no sabes qué abre",
                rito="sal en el umbral", forma="aviso", evita=("Ana, bajo tu signo", 'Escorpio "de agua"'))
    assert reading_tag(f, TAROT) == (
        '[ADIVINACIÓN: nombre=Ana; lugar=fiesta; hoy=jueves 29 de octubre; signo=Escorpio; '
        'elemento=agua; número=6; '
        'sueño=dientes ("se me caían los dientes en la boda de mi prima"); '
        'deseo=venganza ("contra mi ex"); carta=La Muerte (de cabeza; la saqué yo); '
        'taza=estrella; luna=llena; palabra=Zumbalí; casa=Ravenclaw; '
        "visión=una llave que ya no sabes qué abre; rito=sal en el umbral; forma=aviso; "
        "evita=Ana, bajo tu signo | Escorpio 'de agua'] Haz la lectura.")


def test_the_tag_leaves_out_what_is_missing_and_never_the_year():
    assert reading_tag(Fortune(), TAROT) == "[ADIVINACIÓN: ] Haz la lectura."
    tag = reading_tag(Fortune(fecha=(23, 10), signo="escorpio", sueno="nada", luna="cuarto_creciente",
                              lugar="la cantina de mi tío"), None)
    assert tag == ("[ADIVINACIÓN: lugar=la cantina de mi tío; signo=Escorpio; elemento=agua; "
                   "sueño=nada; luna=cuarto creciente] Haz la lectura.")
    assert "23" not in tag and "fecha" not in tag
    assert "carta" not in reading_tag(Fortune(carta=13), None)        # no deck: no card
    assert "carta" not in reading_tag(Fortune(carta=99), TAROT)
    assert "casa" not in reading_tag(Fortune(deseo="amor"), TAROT)


def test_the_tag_says_who_drew_the_card_and_a_no():
    assert "carta=El Diablo (la sacó con su mano);" in reading_tag(
        Fortune(carta=15, carta_de="visitante", palabra="x"), TAROT)
    assert "carta=El Diablo (la saqué yo);" in reading_tag(
        Fortune(carta=15, carta_de="sombrero", palabra="x"), TAROT)
    assert "carta=El Diablo;" in reading_tag(Fortune(carta=15, palabra="x"), TAROT)
    # A card declined is no card at all: nothing to mention ("Tu carta no salió", 2026-10-31).
    assert "carta" not in reading_tag(Fortune(sin_carta=True, palabra="x"), TAROT)
    assert "sombrero" not in reading_tag(Fortune(carta=15, carta_de="sombrero", sueno="otro"), TAROT)
    assert "tema=dinero (no dijo qué pide: lee este)" in reading_tag(Fortune(tema="dinero"), TAROT)
    assert "tema" not in reading_tag(Fortune(deseo="amor", tema="dinero"), TAROT)


def test_the_tag_with_cues_and_a_wish_in_the_visitors_words():
    f = Fortune(lugar="fiesta", deseo="otro", deseo_txt="que mis alumnos lean",
                pistas={"edad": "adulto", "impresion": "sonriente", "lleva": "capa negra",
                        "disfraz": "tenebroso"})
    assert reading_tag(f, TAROT) == (
        '[ADIVINACIÓN: lugar=fiesta; deseo=otro ("que mis alumnos lean"); pistas=edad: adulto, '
        "impresión: sonrisa, disfraz: tenebroso, lleva: capa negra] Haz la lectura.")
    assert "pistas" not in reading_tag(Fortune(pistas={}), TAROT)
    assert 'deseo=amor ("un novio' in reading_tag(Fortune(deseo="amor", deseo_txt='un novio "; x=1'), TAROT)


def test_today_and_the_opening():
    assert fortune.today_words(datetime(2026, 10, 29, 21, 0)) == "jueves 29 de octubre"
    assert fortune.today_words(datetime(2026, 11, 1, 1, 0)) == "domingo 1 de noviembre"
    assert fortune.today_words(datetime(1970, 1, 1)) == ""
    assert fortune.opening("[x] Uno dos tres cuatro cinco seis siete ocho nueve.") == \
        "Uno dos tres cuatro cinco seis siete ocho"


@pytest.mark.parametrize("theme", ["seres_queridos", "otro"])
def test_no_dream_words_for_the_dead_and_the_kept(theme):
    tag = reading_tag(Fortune(sueno=theme, sueno_txt="mi tío que se murió"), TAROT)
    assert "tío" not in tag and "murió" not in tag and '"' not in tag
    assert f"sueño={theme} (" in tag
    assert "un ser querido, o alguien que ya cruzó" in reading_tag(
        Fortune(sueno="seres_queridos", sueno_txt="mi abuela"), TAROT)


def test_the_magic_words_and_places():
    assert len(fortune.MAGIC_WORDS) == 12 and len(set(fortune.MAGIC_WORDS)) == 12
    assert all(w[0].isupper() and " " not in w for w in fortune.MAGIC_WORDS)
    assert fortune.PLACES == ("casa", "fiesta", "universidad", "otro")
    assert set(fortune.PLACE_SAID) == set(fortune.PLACES)


# ---- the reading's length (no word list: ADR 0025) ----------------------------------------
def test_clean_reading():
    good = "[ADIVINACIÓN: x] Escorpio, de agua. Soñaste con dientes… ¿y la luna? Tu palabra mágica es Zumbalí."
    assert clean_reading(good) == "Escorpio, de agua. Soñaste con dientes… ¿y la luna? Tu palabra mágica es Zumbalí."
    assert clean_reading("") is None and clean_reading(None) is None
    assert clean_reading("Vas al hospital.") == "Vas al hospital."           # ADR 0025: no word list
    assert clean_reading("Algo muere esta noche, y la muerte te visita.") == "Algo muere esta noche, y la muerte te visita."
    assert clean_reading("Uno. Dos. Tres. Cuatro. Cinco. Seis. Siete.") == "Uno. Dos. Tres. Cuatro. Cinco. Siete."
    long = " ".join(["Una frase larga de diez palabras para llenar el espacio aqui."] * 9) + " Tu palabra mágica es Zumbalí."
    cut = clean_reading(long)
    assert cut.endswith("Tu palabra mágica es Zumbalí.") and len(cut.split()) <= 90 and cut.startswith("Una frase")
    assert clean_reading("palabra " * 91) is None
    assert clean_reading("Cuatro frases.  Con   espacios. De sobra. Y fin.") == "Cuatro frases. Con espacios. De sobra. Y fin."


def test_a_roman_numeral_by_a_month_is_the_day_but_vi_alone_is_a_word():
    # Canary wrote "XII de octubre" on the board (docs/results/2026-10-27-fortune-answers-canary.md).
    assert fortune.parse_birth("XII de octubre.") == (12, 10)
    assert fortune.parse_birth("el VI de marzo") == (6, 3)
    assert fortune.parse_birth("octubre xxiii") == (23, 10)
    assert fortune.parse_birth("vi un gato en octubre") is None
    assert fortune.parse_birth("XL de enero") is None            # 40 is no day


def test_the_cup_hears_the_star_as_canary_mangles_it():
    assert fortune.parse_shape("uña extraída.") == "estrella"


def test_reading_problems_say_why_a_reading_is_refused():
    assert fortune.reading_problems("Escorpio, de agua. Tu palabra es Zumbalí.") == []
    assert fortune.reading_problems("[ADIVINACIÓN: x]") == ["empty"]
    assert fortune.reading_problems(None) == ["empty"]
    assert fortune.reading_problems("Vas al hospital en 2027, y tu abuelo muerto te mira.") == []
    assert fortune.reading_problems("Uno. Dos. Tres. Cuatro. Cinco. Seis. Siete.") == ["7 sentences"]
    assert fortune.reading_problems("palabra " * 91) == ["91 words"]


# ---- the act's pure steps (fortune_run), shared with the rehearsal ---------------------------
def test_parse_answer_fills_the_data_as_the_act_does():
    from fish_brain.fortune_run import parse_answer
    data: dict = {}
    assert parse_answer("fecha", "diecisiete de junio", TAROT, data) == ("sign", "geminis")
    assert data["fecha"] == (17, 6) and data["signo"] == "geminis" and data["numero"]
    assert parse_answer("fecha", "no sé", TAROT, {}) == ("not_sure", None)
    assert parse_answer("sueno", "no me acuerdo", TAROT, {})[0] == "theme"
    assert parse_answer("carta", "la luna", TAROT, data)[0] == "card"
    assert parse_answer("taza", "un corazón", TAROT, data) == ("shape", data["taza"])
    assert data["carta_de"] == "visitante" and not data["carta_reves"]
    assert parse_answer("deseo", "Venganza contra mi ex.", TAROT, data) == ("wish", "venganza")
    assert data["deseo_txt"] == "Venganza contra mi ex."
    assert parse_answer("deseo", "no sé", TAROT, {}) == ("not_sure", None)
    assert parse_answer("deseo", "", TAROT, {}) == ("none", None)
    assert parse_answer("carta", "Sí, porfa.", TAROT, {}) == ("draw", None)
    no: dict = {}
    assert parse_answer("carta", "No, gracias.", TAROT, no) == ("no_card", None) and no["sin_carta"]
    assert parse_answer("carta", "La que sea.", TAROT, {}) == ("draw", None)
    assert parse_answer("carta", "La de la esquina.", TAROT, {}) == ("none", None)
    upside: dict = {}
    assert parse_answer("carta", "Sí, me salió La Torre de cabeza", TAROT, upside) == ("card", 16)
    assert upside["carta_reves"]
    assert parse_answer("otra", "algo", TAROT, {}) == ("none", None)


def test_fortune_of_and_the_reading_steps():
    from fish_brain.fortune_run import fortune_of, reading_request, reading_result
    data = {"signo": "geminis", "numero": 5, "sueno": "agua", "sueno_txt": "un río",
            "luna": "llena", "palabra": "Zumbalí"}
    f = fortune_of(data, nombre="Ana", lugar="fiesta", casa="Ravenclaw",
                   pistas={"compania": "pareja"})
    assert (f.nombre, f.lugar, f.casa, f.signo, f.sueno_txt, f.palabra) == (
        "Ana", "fiesta", "Ravenclaw", "geminis", "un río", "Zumbalí")
    assert f.pistas == {"compania": "pareja"} and fortune_of({}).pistas == {}

    class LLM:
        resets, extra_rules = 0, "old"

        def reset(self):
            self.resets += 1
            self.extra_rules = ""

    llm = LLM()
    tag = reading_request(llm, "RULES", f, TAROT)
    assert llm.resets == 1 and llm.extra_rules == "RULES" and tag == reading_tag(f, TAROT)
    assert reading_result("Tu luna es llena.\nCASA: Ravenclaw") == "Tu luna es llena."
    assert reading_result("Vas al hospital.") == "Vas al hospital." and reading_result(None) is None


# ---- the hat's own draw and the model's seeds (fortune_run, ADR 0026) ----------------------
def test_the_hat_draws_every_card_and_the_dark_ones_twice_before_repeating():
    from fish_brain.fortune_bank import HAT_DRAW_EXTRA
    from fish_brain.fortune_run import hat_draw
    state = ShowState(None, seed="draw")
    drawn = []
    for _ in range(27):
        d: dict = {}
        drawn.append(hat_draw(state, TAROT, d, reversible=False))
        assert d["carta_de"] == "sombrero" and d["carta_reves"] is False
    assert sorted(set(drawn)) == list(range(22))
    for n in HAT_DRAW_EXTRA["tarot"]:
        assert drawn.count(n) == 2
    assert len(drawn) == 22 + len(HAT_DRAW_EXTRA["tarot"])


def test_a_reversed_draw_one_in_three_and_only_when_reversible():
    from fish_brain.fortune_run import hat_draw
    state = ShowState(None, seed="rev")
    flags = []
    for _ in range(9):
        d: dict = {}
        hat_draw(state, TAROT, d, reversible=True)
        flags.append(d["carta_reves"])
    assert flags.count(True) == 3


def test_the_seeds_deal_before_repeat_and_fit_the_data():
    from fish_brain.fortune_bank import FORMAS, GANCHOS
    from fish_brain.fortune_run import deal_seeds
    state = ShowState(None, seed="seeds")
    ganchos = [deal_seeds(state, {"deseo": "amor"}, has={"signo"})["gancho"] for _ in GANCHOS]
    assert sorted(ganchos) == sorted(GANCHOS)
    from fish_brain.fortune_bank import RITOS
    fresh = ShowState(None, seed="ritos")
    ritos = [deal_seeds(fresh, {"deseo": "amor"}, has=set())["rito"] for _ in RITOS]
    assert sorted(ritos) == sorted(RITOS)                        # dealt before repeat
    for _ in range(12):
        seeds = deal_seeds(state, {}, has=set())
        assert seeds["tema"] in fortune.WISH_IDS
        need = next(n for n, t in FORMAS if t == seeds["forma"])
        assert need in (None, "deseo")                   # no sign, dream or card heard
    assert "tema" not in deal_seeds(state, {"deseo": "otro"}, has=set())


# ---- a question back and the long answer (the board, 2026-10-31) -----------------------------
_PROTEST = ("No, mira, me voy a salir un poquito del rol. Este, se supone que antes de decir la "
            "muerte, o sea, tenías que haber dicho que si me sacabas una carta del tarot. "
            "Entonces, aquí continuamos porque quiero ver seguir viendo experimentos, pero solo "
            "para que lo sepas, ¿ok? Sí, saco una carta de tarot.")


@pytest.mark.parametrize("qid,text,expect", [
    ("deseo", "¿Y cómo que muerte?", ("ask_back", None)),
    ("deseo", "¿Cómo? Dinero.", ("wish", "dinero")),
    ("deseo", "¿Mande?", ("ask_back", None)),
    ("deseo", "No, no entendí.", ("ask_back", None)),
    ("deseo", "No.", ("none", None)),
    ("deseo", "Sí, tengo uno.", ("none", None)),
    ("deseo", "Pues no sé, ¿amor?", ("wish", "amor")),
    ("deseo", "no sé", ("not_sure", None)),
    ("deseo", "Que mis alumnos lean.", ("wish", "otro")),
    ("fecha", "¿Mi signo?", ("ask_back", None)),
    ("fecha", "No sé, creo que escorpio.", ("sign", "escorpio")),
    ("sueno", "Como que me caía de un edificio.", ("theme", "caer")),
    ("sueno", "Otra vez soñé que me caía.", ("theme", "caer")),
    ("sueno", "Otra vez, por favor.", ("ask_back", None)),
    ("carta", _PROTEST, ("draw", None)),
    ("carta", "¿Y cómo que muerte?", ("card", 13)),     # at the card, a question about a card is it
    ("carta", "¿Qué carta?", ("ask_back", None)),
    ("carta", "¿Una carta?", ("ask_back", None)),
    ("carta", "¿Por qué no?", ("draw", None)),
    ("carta", "¿La Torre?", ("card", 16)),
    ("carta", "Me salió la muerte.", ("card", 13)),
    ("carta", "Sí, dame uno.", ("draw", None)),
    ("carta", "Cualquiera.", ("draw", None)),
    ("carta", "No, gracias.", ("no_card", None)),
    ("carta", "No sé.", ("not_sure", None)),
])
def test_the_nights_answers(qid, text, expect):
    from fish_brain.fortune_run import parse_answer
    assert parse_answer(qid, text, TAROT, {}) == expect


def test_a_long_card_answer_keeps_the_card_and_its_reversal():
    from fish_brain.fortune_run import parse_answer
    data: dict = {}
    assert parse_answer("carta", "Sí, la torre. Me salió de cabeza.", TAROT, data) == ("card", 16)
    assert data["carta_reves"]
    long = ("Pues mira, la verdad es que yo ya traía una carta de mi casa, me la dio mi abuela. "
            "Me salió la torre, de cabeza. Qué miedo, ¿no?")
    data = {}
    assert parse_answer("carta", long, TAROT, data) == ("card", 16) and data["carta_reves"]


def test_a_question_back_is_never_stored():
    from fish_brain.fortune_run import parse_answer
    data: dict = {}
    parse_answer("deseo", "¿Cómo? Venganza contra mi jefe.", TAROT, data)
    assert data["deseo_txt"] == "Venganza contra mi jefe." and "¿" not in data["deseo_txt"]


def test_reask_books_the_budget_and_the_questions_back_apart():
    from fish_brain.fortune_run import reask
    st = {"tries": 0, "reprompts": 0, "asked_back": set()}
    assert reask("none", "fecha", st, 2) and st["reprompts"] == 1
    assert not reask("none", "fecha", st, 2)                      # once a question
    st["tries"] = 0
    assert reask("none", "sueno", st, 2) and st["reprompts"] == 2
    st["tries"] = 0
    assert not reask("none", "deseo", st, 2)                       # the budget is spent
    assert reask("ask_back", "deseo", st, 2) and st["reprompts"] == 2   # but a question back
    assert not reask("none", "deseo", st, 2)                       # its try is spent
    assert not reask("ask_back", "deseo", st, 2)                   # and once a question
    st["tries"] = 0
    assert reask("ask_back", "carta", st, 2)


@pytest.mark.parametrize("qid,text,expect", [
    # A card the visitor drew, then a comment with a yes or a no in it: still the card.
    ("carta", "Sí, la Torre, ya la saqué de tu baraja y me salió al revés. ¿Eso es malo, no?", ("card", 16)),
    ("carta", "Me salió la Muerte de tu baraja hace rato. No me gusta nada.", ("card", 13)),
    ("carta", "Me tocó la Emperatriz, la saqué de la baraja que tienes. A ver qué dice.", ("card", 3)),
    ("carta", "Me salió el Sol cuando la saqué de tu baraja hace rato. Claro, aquí la tengo.", ("card", 19)),
    ("carta", "Ya saqué una de tu baraja hace rato y me salió La Torre. ¿Me la lees? Sí, por favor.", ("card", 16)),
    # A card left out is not named.
    ("carta", "Cualquiera menos la Muerte.", ("draw", None)),
    ("carta", "Sí, pero que no sea la Muerte.", ("draw", None)),
    ("carta", "¿Y si me sale la Muerte?", ("none", None)),
    # Yes words are not cards by sound; "uno" is a card only when it names one.
    ("carta", "Claro.", ("draw", None)),
    ("carta", "Sí, ¿no?", ("draw", None)),
    ("carta", "Sí, me salió el uno.", ("card", 1)),
    ("carta", "Sí, el uno.", ("card", 1)),
    # Courtesy before the question, or a request to repeat.
    ("deseo", "Perdón, ¿qué dijiste?", ("ask_back", None)),
    ("deseo", "Disculpa, ¿cómo?", ("ask_back", None)),
    ("deseo", "Mande.", ("ask_back", None)),
    ("deseo", "¿Me lo repites?", ("ask_back", None)),
    ("deseo", "¿Puedes repetir la pregunta?", ("ask_back", None)),
    # Not catching the question, then the answer in the same sentence.
    ("deseo", "No te escuché bien, pero quiero dinero.", ("wish", "dinero")),
    ("carta", "No te escuché, pero la Torre.", ("card", 16)),
    ("sueno", "No te oí bien, pero soñé que volaba.", ("theme", "volar")),
    ("sueno", "No oí la alarma y llegué tarde al examen.", ("theme", "tarde")),
    # An answer said unsure, with a rising tone, is an answer.
    ("deseo", "¿Que regrese mi ex?", ("wish", "amor")),
    ("deseo", "¿Qué tal dinero?", ("wish", "dinero")),
    ("sueno", "¿Como que me caía de un edificio?", ("theme", "caer")),
    ("fecha", "¿Mi signo es Escorpio?", ("sign", "escorpio")),
    # "¿Tienes algún deseo?" answered yes, or with the prompt's own words: asked again.
    ("deseo", "Sí, tengo un deseo.", ("none", None)),
    ("deseo", "Lo que sea.", ("none", None)),
])
def test_what_the_review_found(qid, text, expect):
    from fish_brain.fortune_run import parse_answer
    assert parse_answer(qid, text, TAROT, {}) == expect



@pytest.mark.parametrize("qid,text,expect", [
    # Courtesy, politeness and "I can't hear you" around a question back.
    ("deseo", "Perdona, ¿qué?", ("ask_back", None)),
    ("deseo", "Espera, ¿qué?", ("ask_back", None)),
    ("deseo", "Lo siento, ¿qué?", ("ask_back", None)),
    ("deseo", "¿Me lo repites, por favor?", ("ask_back", None)),
    ("carta", "Repite, por favor.", ("ask_back", None)),
    ("sueno", "Repite, por favor", ("ask_back", None)),
    ("deseo", "No escuché.", ("ask_back", None)),
    ("deseo", "No te oigo.", ("ask_back", None)),
    ("deseo", "Más fuerte, no te oigo.", ("ask_back", None)),
    ("carta", "No escuché.", ("ask_back", None)),
    # A card feared or left out is never the visitor's; "Sí, sale." is a yes.
    ("carta", "Sí, pero que no me salga la Muerte.", ("draw", None)),
    ("carta", "Sí, nomás que no me salga la Muerte.", ("draw", None)),
    ("carta", "Sí, pero no la Muerte.", ("draw", None)),
    ("carta", "Sí, pero me da miedo la Muerte.", ("draw", None)),
    ("carta", "Tengo miedo de que salga la Muerte. Sí, saca una.", ("draw", None)),
    ("carta", "Me encanta la Luna, es mi favorita. Tengo miedo de la Muerte. Pero sí, léemela.", ("draw", None)),
    ("carta", "Sí, sale.", ("draw", None)),
    ("carta", "Sí, sale, léemela.", ("draw", None)),
    # A card first, then a comment that opens with a no: still the card.
    ("carta", "La Muerte. No, no me da miedo, la verdad, ya estoy acostumbrado a esas cosas.", ("card", 13)),
    ("carta", "El Diablo. Sí, ya sé, no me lo digas, siempre me sale esa carta cuando juego.", ("card", 15)),
    ("carta", "La Estrella. No me digas que es mala, porque es mi favorita de toda la baraja.", ("card", 17)),
    ("carta", "¿Por qué no? Nunca me han leído las cartas en toda mi vida, a ver qué sale.", ("draw", None)),
    # A question about a named card is that card; one that holds the answer keeps it.
    ("carta", "¿Qué significa la Torre?", ("card", 16)),
    ("carta", "¿Qué es la Templanza? Es la que me salió.", ("card", 14)),
    ("sueno", "¿Qué significa soñar con serpientes? Porque eso soñé anoche.", ("theme", "serpientes")),
    ("fecha", "¿Qué signo es el 23 de octubre? Ese es mi cumpleaños.", ("sign", "escorpio")),
    ("deseo", "¿Qué tal dinero? Eso es lo que quiero.", ("wish", "dinero")),
    ("deseo", "¿Qué tal viajar por el mundo?", ("wish", "otro")),
    # Yes words, courtesy and set phrases are no wish; "¿en serio?" is not El Loco.
    ("deseo", "Ay, sí.", ("none", None)),
    ("deseo", "Sí, por supuesto.", ("none", None)),
    ("deseo", "Sí, cómo no.", ("none", None)),
    ("carta", "¿En serio?", ("none", None)),
])
def test_what_the_second_review_found(qid, text, expect):
    from fish_brain.fortune_run import parse_answer
    assert parse_answer(qid, text, TAROT, {}) == expect
