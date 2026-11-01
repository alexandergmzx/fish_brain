"""La consulta's pure functions on real sentences. The act itself is proved by tools/consulta_live.py:
the real model and a real voice, no stand-ins here."""
import pytest

from fish_brain import consulta, fortune

TAROT = fortune.DECKS["tarot"]


@pytest.mark.parametrize("text,kind", [
    ("¿Debería aceptar a una mujer en mi casa y tener una relación con ella?", "question"),
    ("¿Qué piensa él sobre nuestra relación?", "question"),
    ("Que piensa el de mi", "question"),
    ("¿Me conviene conservar mi trabajo?", "question"),
    ("¿Por qué me dejó?", "question"),
    ("¿Quién me quiere?", "question"),
    ("¿Cómo le hago para que regrese?", "question"),
    ("¿Qué hago con mi vida?", "question"),
    ("Mi trabajo", "question"),
    ("¿Puedo preguntar por mi hijo?", "question"),
    ("¿Cómo?", "ask_back"), ("Mande.", "ask_back"), ("No te oí.", "ask_back"),
    ("¿Qué dijiste?", "ask_back"), ("Perdón, ¿qué dijiste?", "ask_back"), ("¿Cómo dices?", "ask_back"),
    ("¿Qué te pregunto?", "ask_back"), ("¿Qué hago?", "ask_back"), ("¿Puedo preguntar lo que sea?", "ask_back"),
    ("¿Me lo repites?", "ask_back"), ("¿Y cómo que muerte?", "ask_back"),
    ("", "none"), ("eh… este", "none"), ("Hola.", "none"), ("Sí.", "none"), ("Ya.", "none"),
    ("Gracias.", "none"), ("Déjame pensar.", "none"), ("Quiero hacerte una pregunta.", "none"),
    ("No sé.", "not_sure"), ("No sé qué preguntar.", "not_sure"),
    ("Como que ya no me quiere", "question"), ("¿Otra vez él?", "question"),
    ("No te entendí, repítelo", "ask_back"), ("No te oí, otra vez", "ask_back"),
    ("Buenas noches", "none"), ("Sí, claro", "none"), ("Quiero preguntarte algo", "none"), ("Un momento", "none"),
    ("No sé todavía", "not_sure"), ("No se me ocurre nada", "not_sure"),
    ("No tengo ninguna pregunta", "decline"), ("No, nada", "decline"), ("Ya me voy", "decline"),
    ("Mejor no.", "decline"), ("No, gracias.", "decline"), ("Ninguna.", "decline"),
])
def test_question_or_protest(text, kind):
    assert consulta.parse_question(text)[0] == kind


def test_the_answer_after_a_protest_is_kept_and_a_long_story_keeps_its_end():
    assert consulta.parse_question("¿Cómo? ¿Qué piensa él de mí?") == ("question", "¿Qué piensa él de mí?")
    assert consulta.parse_question("No te entendí, pero quiero saber si renuncio.")[1].endswith("si renuncio")
    long = "Te cuento algo muy largo de mi vida. " * 40 + "¿Renuncio?"
    assert consulta.parse_question(long)[1].endswith("¿Renuncio?") and len(consulta.parse_question(long)[1]) <= 700


@pytest.mark.parametrize("text,kind,n,thoth", [
    ("La Muerte", "card", 13, None), ("Arte", "card", 14, "Arte"), ("Me salió el Arte", "card", 14, "Arte"),
    ("Lujuria", "card", 8, "Lujuria"), ("El Ajuste", "card", 11, "Ajuste"), ("El Eón", "card", 20, "Eón"),
    ("El Universo", "card", 21, "Universo"), ("La Fortuna", "card", 10, "La Fortuna"),
    ("Sí, Arte", "card", 14, "Arte"), ("La Muerte, la trece", "card", 13, None),
    ("Arte y la Torre", "two", None, None), ("Sí, ya la saqué", "none", None, None), ("A ver, espérame", "none", None, None),
    ("La Muerte no", "none", None, None), ("Dos de Copas", "minor", None, None), ("Dos de copa", "minor", None, None), ("Rey de bastos", "minor", None, None),
    ("La Torre y la Luna", "two", None, None), ("Saqué dos cartas", "two", None, None),
    ("Sí", "draw", None, None), ("Saca tú", None, None, None), ("No tengo", "draw", None, None),
    ("Sí, léeme mi fortuna", "draw", None, None), ("Que decida el universo", None, None, None),
])
def test_the_card_answer(text, kind, n, thoth):
    data = {}
    got, value = consulta.parse_card_answer(text, TAROT, data)
    if kind:
        assert got == kind
    assert value == n and data.get("carta") == n and data.get("carta_thoth") == thoth


def test_a_visitors_card_upside_down():
    data = {}
    assert consulta.parse_card_answer("La Muerte, de cabeza", TAROT, data) == ("card", 13)
    assert data["carta_reves"]
    assert "(de cabeza; la sacó de su baraja)" in consulta.tag("¿Sí?", data, TAROT)


def test_the_tag_holds_the_question_and_the_card_only():
    line = consulta.tag('¿Me "conviene"?', {"carta": 14, "carta_de": "visitante", "carta_thoth": "Arte"}, TAROT, "Ana")
    assert line.startswith("[CONSULTA: nombre=Ana; pregunta=\"¿Me 'conviene'?\"; carta=La Templanza (la sacó de su baraja; la llamó Arte)]")
    for word in ("signo", "luna", "palabra", "rito", "casa"):
        assert word not in line


def test_clean_reply():
    assert consulta.clean_reply("**La Muerte** habla.\n\n- Cierra algo. ¿Quieres saber más?") == "La Muerte habla. Cierra algo."
    assert consulta.clean_reply("Una oración. Otra que se cor") == "Una oración."
    assert consulta.clean_reply("Casa: la tuya. Pide calma.") == "Casa: la tuya. Pide calma."
    assert consulta.clean_reply("Cuesta 3.5 veces más. Eso pesa.") == "Cuesta 3.5 veces más. Eso pesa."
    assert consulta.clean_reply('Dice "ven." Y calla.') == 'Dice "ven." Y calla.'
    assert consulta.clean_reply("Pesa. ¿Sí? ¿Lo ves?") == "Pesa."
    assert consulta.clean_reply("") is None
    long = " ".join(f"Oración {i} con varias palabras más aquí dentro." for i in range(5))
    assert consulta.clean_reply(long) == long
    assert len(consulta.clean_reply("Palabras muchas aquí. " * 30 + "Final.").split()) <= consulta.MAX_WORDS
