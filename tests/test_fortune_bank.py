"""fortune_bank.py: every datum the parsers return has a clip (and in model mode a beat or a
name beat), every clip keeps the adult register's rules, the names are the contract's, and the
rules are the roast's (ADR 0026)."""
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
    assert fb.QIDS == ("fecha", "sueno", "deseo", "carta", "taza")
    assert fb.prompt_name("fecha") == "fortune_q_fecha"
    assert fb.prompt_name("carta") == "fortune_q_carta_tarot"
    assert fb.prompt_name("carta", fortune.DECKS["tarot"]) == "fortune_q_carta_tarot"
    assert fb.prompt_name("carta", "tarot") == "fortune_q_carta_tarot"
    assert fb.reprompt_name("sueno") == "fortune_rq_sueno"
    assert fb.reaction_name("fecha", "escorpio") == "fortune_re_fecha_escorpio"
    assert fb.reaction_name("sueno", "dientes") == "fortune_re_sueno_dientes"
    assert fb.reaction_name("carta", 13, fortune.DECKS["tarot"]) == "fortune_re_carta_tarot_13"
    assert fb.reaction_name("taza", "estrella") == "fortune_re_taza_estrella"
    assert fb.reaction_name("deseo", "venganza") == "fortune_re_deseo_venganza"
    assert fb.card_name_name(13, fortune.DECKS["tarot"]) == "fortune_nombre_tarot_13"
    assert fb.card_name_name(13) == "fortune_nombre_tarot_13" and fb.REVERSED_NAME == "fortune_reves"
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
    for wish in fortune.WISH_IDS:
        assert fb.reaction_name("deseo", wish) in P
    assert fb.pool_names("re_deseo_otro") == ["fortune_re_deseo_otro_1", "fortune_re_deseo_otro_2"]
    assert all(n in P for n in fb.pool_names("re_deseo_otro"))
    for deck_id, deck in fortune.DECKS.items():                             # the name beats
        for c in deck["cards"]:
            name = fb.card_name_name(c.n, deck)
            assert name in P and P[name].startswith(c.said), name
    assert fb.REVERSED_NAME in P and "de cabeza" in P[fb.REVERSED_NAME]
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
    kinds = {"q": 5, "rq": 5, "re_fecha": 12, "re_sueno": 21, "re_deseo": 6, "re_carta_tarot": 22,
             "re_taza": 11, "nombre_tarot": 22, "reves": 1, "num": 9, "luna": 8, "intro": 12,
             "vision": 6, "bridge": 2, "suspense": 2, "magic": 12, "cierre": 8, "beat": 12,
             "barajo": 3, "sin_carta": 2, "suspense_mas": 2}
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
    assert sum(kinds.values()) == len(P) == 183


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


def test_the_beats_are_short_and_say_nothing_about_the_answer():
    for name in fb.pool_names("beat"):
        assert len(P[name].split()) <= 9, name
    for name in fb.pool_names("barajo") + fb.pool_names("sin_carta"):
        assert name in P
    assert "baraja sola" in P["fortune_barajo_1"]
    # The model mode's own clips speak in the oracle's voice (ADR 0027): no cheek left
    model_only = [P[n] for slot in ("beat", "barajo", "suspense", "suspense_mas")
                  for n in fb.pool_names(slot)]
    for text in model_only:
        for cheek in ("Uy", "Ja.", "chismeando", "en tu contra", "se pone bueno"):
            assert cheek not in text, text
    assert len(fb.pool_names("suspense_mas")) == 2


def test_the_ask_for_a_card_is_his_words():
    assert P["fortune_q_carta_tarot"] == "¿Quieres que te lea una carta de tarot?"
    assert "baraja" in P["fortune_rq_carta_tarot"]
    assert all(w in P["fortune_q_deseo"] for w in ("amor", "dinero", "salud", "venganza", "Muerte"))


def test_the_seeds_are_data_not_clips():
    assert len(fb.GANCHOS) >= 20 and len(set(fb.GANCHOS)) == len(fb.GANCHOS)
    assert len(fb.FORMAS) == 6
    assert {need for need, _t in fb.FORMAS} == {"signo", "sueno", "carta", "deseo", None}
    assert not any(g in P.values() for g in fb.GANCHOS)
    assert set(fb.HAT_DRAW_EXTRA["tarot"]) == {6, 13, 15, 16, 18}
    assert sorted(fb.REVERSED_BAG).count("cabeza") == 1 and len(fb.REVERSED_BAG) == 3


def test_the_rules_are_the_oracles():
    r = fb.FORTUNE_RULES
    assert "FORMATO" in r and "REGLAS FIJAS" in r and "setenta y cinco palabras" in r
    # ADR 0027: the old sorcerer's oracle over the roast's bones (ADR 0026)
    assert "voz de oráculo" in r and "UNA SOLA PROFECÍA SOBRE SU DESEO" in r
    assert "roast" not in r and "búrlate" not in r and "Sin burla" in r
    assert "lo leíste en su cabeza" in r and "dos lecturas" in r
    assert "Cuídate" in r or "cuídate" in r
    assert "ay de ti" in r and "el de rito=" in r and "mal de ojo" in r
    assert r.count("rito=") >= 4                      # the format line, the rule, two+ examples
    assert len(set(fb.RITOS)) == len(fb.RITOS) >= 16 and any("mal de ojo" in x for x in fb.RITOS)
    assert "nunca un porcentaje" in r and "Ningún porcentaje" in r
    for stale in ("Los astros", "el universo", "todo está escrito", "mucho amor"):
        assert stale in r, stale                      # named as stale, so the model avoids them
    assert "forma=aviso" in r and "aviso (abres con una advertencia)" in r
    assert "forma=orden" not in r
    for key in ("deseo=", "tema=", "visión=", "forma=", "evita=", "hoy="):
        assert key in r, key
    for stale in ("Esta noche, más de una vez", "Algo viejo se va", "No te asustes"):
        assert stale in r, stale
    assert "dale un sentido bueno" not in r and "Fallo vuelto futuro" not in r
    assert r.count("<ejemplo>") == 3 and "no copies sus frases" in r
    for place in ("fiesta", "casa", "universidad"):
        assert place in r
    assert "LAS PISTAS" in r and "pistas=" in r
    # ADR 0025: no forbidden topics in the rules
    for ban in ("Nunca digas que alguien murió", "nunca una muerte real", "Nada de enfermedades",
                "Nunca explícito ni grosero", "lotería"):
        assert ban not in r, ban
    assert "trago" in r and "ofrenda" in r and "no des por hecho que estudia" in r
    assert "La Muerte" in r and "El Diablo" in r and "tu palabra mágica es" in r
    assert "Nunca repitas los corchetes" in r and "alcanza a los dos" in r
    assert "enfermedades" not in r and "religión" not in r          # ADR 0025
    assert "Público familiar" not in r and "niños" not in r


def test_the_bank_is_disjoint_from_the_shows():
    from fish_brain.show_bank import SHOW_PHRASES
    assert not set(P) & set(SHOW_PHRASES)
    assert not set(P.values()) & set(SHOW_PHRASES.values())


@pytest.mark.parametrize("slot", ["intro_fiesta", "cierre_fiesta"])
def test_the_party_pools_may_toast_or_sing(slot):
    joined = _fold(" ".join(fb.POOLS[slot]))
    assert any(w in joined for w in PARTY_WORDS)
