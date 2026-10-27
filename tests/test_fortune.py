"""fortune.py: the fortune act's parsers hear dates, signs, dreams, cards, shapes and the
animal, the moon is right on its check dates, the tag and the filter are exact."""
from datetime import datetime, timezone

import pytest

from fish_brain import fortune
from fish_brain.fortune import (ANIMAL_Q, DECKS, DREAM_THEMES, MOON_PHASES, SIGNS, Fortune,
                                banned_in, clean_reading, dream_theme, lucky_number, moon_phase,
                                moon_tonight, numbers_in, parse_birth, parse_card, parse_shape,
                                parse_sign, reading_tag, sign_of, strip_notes, tokens)
from fish_brain.show import match_option, phon_key

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


# ---- the cup, the animal --------------------------------------------------------------------
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


def test_the_animal_through_match_option():
    heads = [phon_key(o["words"][0]) for o in ANIMAL_Q["options"]]
    assert len(set(heads)) == 4 and ANIMAL_Q["id"] == "animal"
    assert set(fortune.ANIMAL_SAID) == {o["id"] for o in ANIMAL_Q["options"]}
    for text, expect in [("un gato negro", "gato"), ("la lechuza", "buho"), ("tecolote", "buho"),
                         ("murciélago", "murcielago"), ("una rana", "sapo"), ("el sapo", "sapo"),
                         ("el primero", "gato"), ("el último", "sapo")]:
        h = match_option(ANIMAL_Q, strip_notes(text + " [Nota: eco]"))
        assert h.option == expect, (text, h)
    assert match_option(ANIMAL_Q, "no sé").kind == "not_sure"
    assert match_option(ANIMAL_Q, "un perro").kind == "none"


@pytest.mark.parametrize("text,expect", [
    # one of the four, said or by its place: the option
    ("un gato negro", ("option", "gato")), ("el primero", ("option", "gato")),
    ("la lechuza", ("option", "buho")),
    # any other animal: the visitor's own phrase, before the sound match of the four
    ("Un perro.", ("free", "un perro")),
    ("Un perrito xoloitzcuintle.", ("free", "un perrito xoloitzcuintle")),
    ("Pues un ajolote, porque son bonitos", ("free", "un ajolote")),
    ("burro", ("free", "burro")),                  # by sound alone it would be the búho
    ("Una rata.", ("free", "una rata")),           # by sound alone it would be the sapo
    # a diminutive of the four: by sound, after the lexicon
    ("un sapito", ("option", "sapo")), ("una lechucita", ("option", "buho")),
    ("no sé", ("not_sure", None)), ("mmm", ("none", None)), ("", ("none", None)),
])
def test_the_animal_order(text, expect):
    assert fortune.parse_animal(text) == expect


def test_a_free_animal_phrase_is_short_and_safe():
    long = "Mmm, pues yo escojo un zorro plateado de los que salen en la noche con la luna llena"
    phrase = fortune.animal_phrase(long)
    assert phrase.startswith("un zorro plateado") and len(phrase) <= fortune.ANIMAL_TEXT_MAX
    assert not phrase.endswith(" ")
    assert fortune.animal_phrase("un [Nota: eco] perro; = <b>") == "un perro"
    assert fortune.animal_phrase("una telaraña") is None             # no animal by name
    assert "animal" not in fortune.ANIMAL_WORDS and "rebano*" not in fortune.ANIMAL_WORDS


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
                carta=13, taza="estrella", animal="gato", luna="llena", palabra="Zumbalí")
    assert reading_tag(f, TAROT) == (
        '[ADIVINACIÓN: nombre=Ana; lugar=fiesta; signo=Escorpio; elemento=agua; número=6; '
        'sueño=dientes ("se me caían los dientes en la boda de mi prima"); carta=La Muerte; '
        'taza=estrella; animal=gato negro; luna=llena; palabra=Zumbalí; casa=Ravenclaw] Haz la lectura.')


def test_the_tag_leaves_out_what_is_missing_and_never_the_year():
    assert reading_tag(Fortune(), TAROT) == "[ADIVINACIÓN: ] Haz la lectura."
    tag = reading_tag(Fortune(fecha=(23, 10), signo="escorpio", sueno="nada", luna="cuarto_creciente",
                              lugar="la cantina de mi tío"), None)
    assert tag == ("[ADIVINACIÓN: lugar=la cantina de mi tío; signo=Escorpio; elemento=agua; "
                   "sueño=nada; luna=cuarto creciente] Haz la lectura.")
    assert "23" not in tag and "fecha" not in tag
    assert "carta" not in reading_tag(Fortune(carta=13), None)        # no deck: no card
    assert "carta" not in reading_tag(Fortune(carta=99), TAROT)
    assert "casa" not in reading_tag(Fortune(animal="perro"), TAROT)


def test_the_tag_with_cues_and_a_free_animal():
    f = Fortune(lugar="fiesta", animal="un perrito xoloitzcuintle",
                pistas={"edad": "adulto", "impresion": "sonriente", "lleva": "capa negra",
                        "disfraz": "tenebroso"})
    assert reading_tag(f, TAROT) == (
        "[ADIVINACIÓN: lugar=fiesta; animal=un perrito xoloitzcuintle; pistas=edad: adulto, "
        "impresión: sonrisa, disfraz: tenebroso, lleva: capa negra] Haz la lectura.")
    assert "pistas" not in reading_tag(Fortune(pistas={}), TAROT)
    assert "animal=un perro" in reading_tag(Fortune(animal="un perro; x=1"), TAROT) and \
        "x=1" not in reading_tag(Fortune(animal="un perro; x=1"), TAROT)


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


# ---- the filter -----------------------------------------------------------------------------
@pytest.mark.parametrize("text,expect", [
    ("Esta noche brindas con pan de muerto en el Día de Muertos.", []),
    ("Tu abuelo muerto te mira", ["muerto"]), ("a las 3 de la tarde", ["a las 3"]),
    ("te veo a las once", ["a las once"]), ("son las 10:30", ["10:30"]),
    ("naciste en 1990", ["1990"]), ("Cáncer, de agua, sueña con mares.", []),
    ("la lotería te sonríe", ["loteria"]), ("tiene cáncer", ["tiene cancer"]),
    ("hace años", ["anos"]), ("tu edad", ["edad"]), ("Eres Cáncer", []),
    ("La Muerte, la calavera y El Diablo te acompañan", []),
    ("vas al hospital por un accidente", ["hospital", "accidente"]),
    ("que Dios te bendiga", ["dios"]), ("pura chingada", ["chingada"]),
])
def test_banned_in(text, expect):
    assert banned_in(text) == expect


def test_clean_reading():
    good = "[ADIVINACIÓN: x] Escorpio, de agua. Soñaste con dientes… ¿y la luna? Tu palabra mágica es Zumbalí."
    assert clean_reading(good) == "Escorpio, de agua. Soñaste con dientes… ¿y la luna? Tu palabra mágica es Zumbalí."
    assert clean_reading("") is None and clean_reading(None) is None
    assert clean_reading("Vas al hospital.") is None
    assert clean_reading("Uno. Dos. Tres. Cuatro. Cinco. Seis. Siete.") == "Uno. Dos. Tres. Cuatro. Cinco. Siete."
    long = " ".join(["Una frase larga de diez palabras para llenar el espacio aqui."] * 9) + " Tu palabra mágica es Zumbalí."
    cut = clean_reading(long)
    assert cut.endswith("Tu palabra mágica es Zumbalí.") and len(cut.split()) <= 90 and cut.startswith("Una frase")
    assert clean_reading("Vas al hospital. " * 3 + "Tu palabra es Zumbalí.") is None     # banned: never trimmed away
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
    assert fortune.reading_problems("Vas al hospital en 2027.") == ["banned 'hospital'",
                                                                    "banned '2027'"]
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
    assert parse_answer("animal", "un gato negro", TAROT, data) == ("option", "gato")
    assert parse_answer("animal", "ninguno", TAROT, {}) == ("not_sure", None)
    free: dict = {}
    assert parse_answer("animal", "Un perrito xoloitzcuintle.", TAROT, free) == (
        "free", "un perrito xoloitzcuintle")
    assert free["animal"] == "un perrito xoloitzcuintle"
    assert parse_answer("animal", "mmm", TAROT, {}) == ("none", None)
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
    assert reading_result("Vas al hospital.") is None and reading_result(None) is None
