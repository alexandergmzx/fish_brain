"""fortune_bank.py: every datum the parsers return has a clip, every clip keeps the adult
register's rules, and the names are the contract's."""
import re

import pytest

from fish_brain import fortune, fortune_bank as fb
from fish_brain.visit import _fold

P = fb.FORTUNE_PHRASES
PARTY_WORDS = ("brindis", "brindar", "trago", "cancion", "tequila", "mezcal", "cerveza", "chela",
               "copa", "bebida", "dj")


def sentences(text: str) -> int:
    """Sentence ends; an ellipsis mid-sentence ("Mmm… se junta todo") is a pause, not an end."""
    return len(re.findall(r"[.!?]+(?:\s|$)|…(?:\s+[A-ZÁÉÍÓÚÑ¿¡]|\s*$)", text))


def test_every_clip_is_named_fortune_and_keeps_the_rules():
    assert len(P) >= 141
    for name, text in P.items():
        assert name.startswith("fortune_") and not name.startswith("show_"), name
        assert text.strip() and not text.lstrip().startswith("-"), name     # loq reads "-" as an option
        assert len(text.split()) <= 40, (name, len(text.split()))
        assert sentences(text) <= 2, (name, text)
        assert fortune.banned_in(text) == [], (name, fortune.banned_in(text))
        assert "feria" not in _fold(text) and "cenart" not in _fold(text), name
        if name.startswith(("fortune_q_", "fortune_rq_")):
            assert text.rstrip().endswith("?"), name
        party = [w for w in PARTY_WORDS if re.search(rf"\b{w}\b", _fold(text))]
        assert not party or "fiesta" in name, (name, party)


def test_the_sign_is_asked_first_and_the_date_is_the_fallback():
    assert "signo" in P["fortune_q_fecha"] and "año" not in P["fortune_q_fecha"]
    assert "día" in P["fortune_rq_fecha"] and "mes" in P["fortune_rq_fecha"]
    assert fb.question_text("fecha") == P["fortune_q_fecha"]
    assert fb.question_text("carta") == fb.question_text("carta", fortune.DECKS["tarot"]) == P["fortune_q_carta_tarot"]


def test_names_follow_the_contract():
    assert fb.QIDS == ("fecha", "sueno", "carta", "taza", "animal")
    assert fb.prompt_name("fecha") == "fortune_q_fecha"
    assert fb.prompt_name("carta") == "fortune_q_carta_tarot"
    assert fb.prompt_name("carta", fortune.DECKS["tarot"]) == "fortune_q_carta_tarot"
    assert fb.prompt_name("carta", "tarot") == "fortune_q_carta_tarot"
    assert fb.reprompt_name("sueno") == "fortune_rq_sueno"
    assert fb.reaction_name("fecha", "escorpio") == "fortune_re_fecha_escorpio"
    assert fb.reaction_name("sueno", "dientes") == "fortune_re_sueno_dientes"
    assert fb.reaction_name("carta", 13, fortune.DECKS["tarot"]) == "fortune_re_carta_tarot_13"
    assert fb.reaction_name("taza", "estrella") == "fortune_re_taza_estrella"
    assert fb.reaction_name("animal", "gato") == "fortune_re_animal_gato"
    assert fb.num_name(6) == "fortune_num_6" and fb.moon_name("llena") == "fortune_luna_llena"
    assert fb.pool_names("vision") == [f"fortune_vision_{i}" for i in range(1, 7)]
    for qid in fb.QIDS:
        assert fb.prompt_name(qid) in P and fb.reprompt_name(qid) in P


def test_every_datum_has_its_clip():
    for s in fortune.SIGNS:
        assert fb.reaction_name("fecha", s.id) in P
        assert s.said.split()[0] in P[fb.reaction_name("fecha", s.id)]          # the sign by name
    assert "Cáncer" in P["fortune_re_fecha_cancer"]
    for t in fortune.DREAM_THEMES:
        assert fb.reaction_name("sueno", t.id) in P
    for deck_id, deck in fortune.DECKS.items():
        for c in deck["cards"]:
            name = fb.reaction_name("carta", c.n, deck)
            assert name in P and c.said in P[name], name                        # the card by name
    assert "La Muerte" in P["fortune_re_carta_tarot_13"] and "El Diablo" in P["fortune_re_carta_tarot_15"]
    for t in fortune.CUP_SHAPES:
        assert fb.reaction_name("taza", t.id) in P
    for o in fortune.ANIMAL_Q["options"]:
        assert fb.reaction_name("animal", o["id"]) in P
    assert fb.pool_names("re_animal_otro") == ["fortune_re_animal_otro_1", "fortune_re_animal_otro_2"]
    assert all(n in P for n in fb.pool_names("re_animal_otro"))
    for n in range(1, 10):
        assert fb.num_name(n) in P
    for phase in fortune.MOON_PHASES:
        assert fb.moon_name(phase) in P and "luna" in P[fb.moon_name(phase)]
    for place in fortune.PLACES:
        assert len(fb.pool_names(f"intro_{place}")) == 2 and len(fb.pool_names(f"cierre_{place}")) == 2
    for house in "GHRS":
        assert len(fb.pool_names(f"intro_{house}")) == 1
    assert len(fb.pool_names("vision")) == 6 and len(fb.pool_names("bridge")) == 2
    assert len(fb.pool_names("suspense")) == 2 and len(fb.pool_names("magic")) == 12


def test_the_counts_are_the_plans():
    kinds = {"q": 5, "rq": 5, "re_fecha": 12, "re_sueno": 21, "re_carta_tarot": 22, "re_taza": 11,
             "re_animal": 6, "num": 9, "luna": 8, "intro": 12, "vision": 6, "bridge": 2, "suspense": 2,
             "magic": 12, "cierre": 8}
    got = {k: 0 for k in kinds}
    for name in P:
        rest = name[len("fortune_"):]
        for k in sorted(kinds, key=len, reverse=True):
            if rest == k or rest.startswith(k + "_"):
                got[k] += 1
                break
        else:
            raise AssertionError(name)
    assert got == kinds
    assert sum(kinds.values()) == len(P) == 141


def test_magic_words_one_per_clip_in_order():
    names = fb.pool_names("magic")
    assert list(fb.MAGIC_WORD_OF) == names
    assert list(fb.MAGIC_WORD_OF.values()) == list(fortune.MAGIC_WORDS)
    for name, word in fb.MAGIC_WORD_OF.items():
        assert word in P[name], name
        others = [w for w in fortune.MAGIC_WORDS if w != word and w in P[name]]
        assert not others, (name, others)
        assert "palabra mágica" in P[name]


def test_the_english_is_spelled_right():
    joined = " ".join(_fold(t) for t in P.values())
    for bad in ("grifindor", "slitherin", "hufflepuf ", "ravenclow", "halowen", "haloween"):
        assert bad not in joined
    for house in ("Gryffindor", "Hufflepuff", "Ravenclaw", "Slytherin"):
        assert any(house in t for t in P.values())


def test_the_rules_are_the_adult_ones():
    r = fb.FORTUNE_RULES
    assert "FORMATO" in r and "REGLAS FIJAS" in r and "cuatro oraciones" in r and "setenta" in r
    for move in ("Eco", "Arcoíris", "Acierto", "Fallo vuelto futuro"):
        assert move in r
    for place in ("fiesta", "casa", "universidad"):
        assert place in r
    assert "LAS PISTAS" in r and "pistas=" in r
    assert "Nunca digas que alguien murió" in r and "nunca una muerte real" in r
    assert "brindis" in r and "ofrenda" in r and "profesor" in r
    assert "La Muerte" in r and "El Diablo" in r and "tu palabra mágica es" in r
    assert "Nunca repitas los corchetes" in r and "no hace falta decirla" in r
    assert "enfermedades" in r and "lotería" in r and "religión" in r
    assert "Público familiar" not in r and "niños" not in r


def test_the_bank_is_disjoint_from_the_shows():
    from fish_brain.show_bank import SHOW_PHRASES
    assert not set(P) & set(SHOW_PHRASES)
    assert not set(P.values()) & set(SHOW_PHRASES.values())


@pytest.mark.parametrize("slot", ["intro_fiesta", "cierre_fiesta"])
def test_the_party_pools_may_toast_or_sing(slot):
    joined = _fold(" ".join(fb.POOLS[slot]))
    assert any(w in joined for w in PARTY_WORDS)
