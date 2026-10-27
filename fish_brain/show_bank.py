"""The scripted visit's data (show.py, show_run.py): questions, weights and every line.

The "cross" (docs/adr/0015): Q1 and Q2 are either/or and cross into the four houses, so the 16
answer paths give 4 per house with no ties; Q3 offers four traits and can move a visitor to a
neighbouring house, never to the opposite one (3 < 4, 5 > 4 in points). Weights are integer
units of 1/8 point: an axis answer gives 16 to each of two houses, a trait 24 to one. The
operator's colour chip gives 4 (half a point): chips can only break a tie.

Options are short nouns that sound different within a question, each with the words a visitor
may use for it (folded: no accents, lower case). Every line is a canned phrase named `show_*`,
rendered ahead while the voice is clean and played from the cache, never rendered at show time.
All texts are drafts for the owner to edit (2026-10-26): original, gender-neutral, no clock
times, no venue names; the Halloween and Día de Muertos season, never really scary. Nothing here is taken from the books, the films or the official quiz.
"""
from __future__ import annotations

HOUSES = {"G": "Gryffindor", "H": "Hufflepuff", "R": "Ravenclaw", "S": "Slytherin"}

AXIS = 16          # an either/or answer, to each of its two houses
TRAIT = 24         # a four-way answer, to its one house
CHIP = 4           # the operator's colour chip

# Q1: A = heart and people (G, H), B = head and plans (R, S).
# Q2: A = out in front (G, S), B = inside and steady (H, R).
# Q3: one house each.
SETS: dict[str, list[dict]] = {
    "A": [
        {"id": "A1",
         "prompt": "Imagina dos puertas adornadas con calabazas: detrás de una hay fiesta, detrás de la otra, un acertijo. ¿Fiesta... o acertijo?",
         "reprompt": "Dime nomás: ¿fiesta... o acertijo?",
         "options": [
             {"id": "fiesta", "words": ["fiesta", "fiestas", "fiestota", "pachanga", "la fiesta"],
              "scores": {"G": AXIS, "H": AXIS},
              "reaction": "¡Fiesta! Ya sabía: contigo nadie se queda fuera.",
              "why": "people, joy"},
             {"id": "acertijo", "words": ["acertijo", "acertijos", "el acertijo", "adivinanza", "adivinanzas"],
              "scores": {"R": AXIS, "S": AXIS},
              "reaction": "Un acertijo. Esa cabecita no descansa hasta encontrar la respuesta.",
              "why": "head, a puzzle to win"},
         ]},
        {"id": "A2",
         "prompt": "Ahora rápido, sin pensarlo mucho: ¿eres más volcán... o más jardín?",
         "reprompt": "¿Volcán... o jardín?",
         "options": [
             {"id": "volcan", "words": ["volcan", "volcanes", "el volcan", "volcancito"],
              "scores": {"G": AXIS, "S": AXIS},
              "reaction": "¡Volcán! Hay fuego ahí adentro, como en una calabaza encendida.",
              "why": "bold, out in front"},
             {"id": "jardin", "words": ["jardin", "jardines", "el jardin", "jardincito"],
              "scores": {"H": AXIS, "R": AXIS},
              "reaction": "Jardín. Lo tuyo crece despacito, como el cempasúchil, pero crece fuerte.",
              "why": "steady, inside"},
         ]},
        {"id": "A3",
         "prompt": "Última pregunta. Si viajaras a una isla bajo la luna, ¿qué te llevarías: un mapa, un libro, un amigo o un trofeo?",
         "reprompt": "¿Mapa, libro, amigo o trofeo?",
         "options": [
             {"id": "mapa", "words": ["mapa", "mapas", "el mapa", "un mapa"],
              "scores": {"G": TRAIT},
              "reaction": "Un mapa: tú no esperas a que llegue la aventura, la vas a buscar.",
              "why": "adventure"},
             {"id": "libro", "words": ["libro", "libros", "el libro", "un libro"],
              "scores": {"R": TRAIT},
              "reaction": "Un libro. Hasta en una isla, tu cabeza quiere aprender algo nuevo.",
              "why": "curiosity"},
             {"id": "amigo", "words": ["amigo", "amiga", "amigos", "amigas", "mejor amigo", "mejor amiga"],
              "scores": {"H": TRAIT},
              "reaction": "Un amigo. Con buena compañía, hasta una isla desierta se vuelve alegre.",
              "why": "loyalty"},
             {"id": "trofeo", "words": ["trofeo", "trofeos", "copa", "medalla"],
              "scores": {"S": TRAIT},
              "reaction": "¡Un trofeo! Ni en una isla dejas de pensar en ganar.",
              "why": "ambition"},
         ]},
    ],
    "B": [
        {"id": "B1",
         "prompt": "Alguien escondió todas las calabazas de la cuadra. ¿Qué haces: armas un equipo... o investigas tú el misterio?",
         "reprompt": "¿Equipo... o misterio?",
         "options": [
             {"id": "equipo", "words": ["equipo", "equipos", "un equipo", "en equipo"],
              "scores": {"G": AXIS, "H": AXIS},
              "reaction": "Equipo. Sabes que juntos se encuentran hasta las calabazas mejor escondidas.",
              "why": "people"},
             {"id": "misterio", "words": ["misterio", "misterios", "el misterio", "investigar", "investigo"],
              "scores": {"R": AXIS, "S": AXIS},
              "reaction": "El misterio. Tú sigues cada pista hasta llegar al final.",
              "why": "head, on one's own"},
         ]},
        {"id": "B2",
         "prompt": "Para pasear contigo esta temporada, ¿qué mascota mágica eliges: un dragón... o una tortuga?",
         "reprompt": "¿Dragón... o tortuga?",
         "options": [
             {"id": "dragon", "words": ["dragon", "dragones", "un dragon", "dragoncito"],
              "scores": {"G": AXIS, "S": AXIS},
              "reaction": "¡Un dragón! Nada de mascotas tímidas: tú quieres alas y chispas.",
              "why": "bold"},
             {"id": "tortuga", "words": ["tortuga", "tortugas", "tortuguita", "una tortuga"],
              "scores": {"H": AXIS, "R": AXIS},
              "reaction": "Una tortuga. Paciencia por fuera y fuerza por dentro: gran combinación.",
              "why": "patient, steady"},
         ]},
        {"id": "B3",
         "prompt": "Y para terminar: de paseo bajo las estrellas, ¿qué te llevas: una brújula, un telescopio, una canasta o una escalera?",
         "reprompt": "¿Brújula, telescopio, canasta o escalera?",
         "options": [
             {"id": "brujula", "words": ["brujula", "brujulas", "la brujula", "una brujula"],
              "scores": {"G": TRAIT},
              "reaction": "La brújula: tú sigues adelante, aunque no sepas qué hay.",
              "why": "adventure"},
             {"id": "telescopio", "words": ["telescopio", "telescopios", "el telescopio", "un telescopio"],
              "scores": {"R": TRAIT},
              "reaction": "El telescopio. Tú quieres ver lo que hay detrás de la luna.",
              "why": "curiosity"},
             {"id": "canasta", "words": ["canasta", "canastas", "canastita", "cesta", "la canasta"],
              "scores": {"H": TRAIT},
              "reaction": "La canasta, con pan de muerto para compartir. Qué buen corazón.",
              "why": "sharing"},
             {"id": "escalera", "words": ["escalera", "escaleras", "la escalera", "escalerita"],
              "scores": {"S": TRAIT},
              "reaction": "La escalera: siempre un escalón más arriba, ¿verdad?",
              "why": "ambition"},
         ]},
    ],
    "C": [
        {"id": "C1",
         "prompt": "Esta temporada, ¿qué se te antoja más: una fiesta de disfraces... o pedir calaverita de puerta en puerta?",
         "reprompt": "¿Fiesta de disfraces... o de puerta en puerta?",
         "options": [
             {"id": "disfraces", "words": ["disfraces", "disfraz", "fiesta", "la fiesta", "fiesta de disfraces"],
              "scores": {"G": AXIS, "H": AXIS},
              "reaction": "¡Fiesta de disfraces! Ya te veo jalando a todos a la pista de baile.",
              "why": "people, fun"},
             {"id": "puertas", "words": ["puertas", "puerta", "puerta en puerta", "calaverita", "pedir calaverita", "dulce o truco", "trick or treat"],
              "scores": {"R": AXIS, "S": AXIS},
              "reaction": "De puerta en puerta. Seguro ya sabes qué casa tiene más calabazas, y por dónde empezar.",
              "why": "plans, a route"},
         ]},
        {"id": "C2",
         "prompt": "Si fueras un animalito de la noche, ¿serías un murciélago... o un gato negro?",
         "reprompt": "¿Murciélago... o gato negro?",
         "options": [
             {"id": "murcielago", "words": ["murcielago", "murcielagos", "un murcielago", "murcielaguito"],
              "scores": {"G": AXIS, "S": AXIS},
              "reaction": "¡Murciélago! Tú sales a volar cuando los demás apenas se asoman.",
              "why": "bold, out in front"},
             {"id": "gato", "words": ["gato", "gatos", "gato negro", "gatito", "un gato"],
              "scores": {"H": AXIS, "R": AXIS},
              "reaction": "Un gato negro. Tú observas todo en silencio, curioseas, y siempre caes de pie.",
              "why": "steady, curious"},
         ]},
        {"id": "C3",
         "prompt": "Antes de salir a pedir calaverita, ¿qué te llevas: una linterna, un libro de hechizos, una bolsa de dulces o una corona?",
         "reprompt": "¿Linterna, hechizos, dulces o corona?",
         "options": [
             {"id": "linterna", "words": ["linterna", "linternas", "la linterna", "lampara"],
              "scores": {"G": TRAIT},
              "reaction": "La linterna: tú vas por delante, alumbrando la calle para los demás.",
              "why": "courage"},
             {"id": "hechizos", "words": ["hechizos", "hechizo", "libro de hechizos", "libro", "libro de magia"],
              "scores": {"R": TRAIT},
              "reaction": "El libro de hechizos. Tú quieres saber cómo funciona la magia, no solo verla.",
              "why": "curiosity"},
             {"id": "dulces", "words": ["dulces", "dulce", "bolsa de dulces", "dulcecitos", "bolsa"],
              "scores": {"H": TRAIT},
              "reaction": "La bolsa de dulces. Contigo, nadie del grupo se queda con las manos vacías.",
              "why": "sharing"},
             {"id": "corona", "words": ["corona", "coronas", "la corona", "coronita"],
              "scores": {"S": TRAIT},
              "reaction": "¡La corona! Esta noche, la reina o el rey de la calle eres tú.",
              "why": "ambition"},
         ]},
    ],
}

# The operator's colour chip (visit.CUE_CHOICES["color"]): a nod to the house colours.
CHIP_WEIGHTS: dict[tuple[str, str], dict[str, int]] = {
    ("color", "rojo"): {"G": CHIP},
    ("color", "amarillo"): {"H": CHIP},
    ("color", "azul"): {"R": CHIP},
    ("color", "verde"): {"S": CHIP},
}

# Pools: slot -> lines. A slot with a house takes "<slot>_<house letter>".
POOLS: dict[str, list[str]] = {
    "greet": [
        "¡Feliz Halloween! Acércate, que este sombrero viejo quiere asomarse a tu cabeza.",
        "Ah, una cabeza nueva. Ayúdame a ver qué guardas ahí adentro, además de dulces.",
        "Pásale, pásale. Contesta mis preguntas y entre tú y yo leemos tu cabeza.",
        "Mmm, siento una mente inquieta. ¿Me ayudas a averiguar a qué casa perteneces?",
        "Aquí estoy, entre calabazas y velitas. Tú contesta con confianza, que del resto me encargo yo.",
        "¡Qué gusto, otra cabeza llena de ideas! Ayúdame a leerla con unas preguntitas.",
        "Este sombrero lleva siglos leyendo cabezas, y la tuya promete. ¿Me echas la mano?",
        "Híjole, cuántas ideas juntas. Ayúdame a ordenarlas y te digo tu casa.",
        "Un gato negro me avisó que venías. Acércate y ayúdame a leer tu cabeza.",
        "Ya desperté de mi siesta entre el cempasúchil. ¿Me prestas tu cabeza un momento?",
    ],
    "nose": [
        "Quien duda es porque piensa. Eso también lo anoto.",
        "No pasa nada: lo que no sabes tú, lo adivino yo.",
        "Ah, un misterio. Me encantan los misterios.",
        "Está bien no saber. Hasta este sombrero viejo duda de vez en cuando.",
    ],
    "bridge": [
        "No hace falta que lo digas: ya lo leí en tu cabeza.",
        "Lo leí entre líneas, como buen sombrero. Vamos adelante.",
        "Ya lo vi. A veces las respuestas se oyen mejor en silencio.",
        "Muy bien, eso lo guardo bajo mi ala.",
        "Tu cabeza contestó primero. Sigamos.",
        "Eso que pensaste me basta. Vamos con lo siguiente.",
        "Lo escuché clarito aquí adentro, entre mis hilos. Sigamos.",
    ],
    "suspense": [
        "Mmm... déjame pensarlo bien.",
        "Ya casi lo tengo...",
        "A ver... se está aclarando.",
        "Siento algo... sí, ya lo veo.",
        "Un momento, que esto es importante.",
        "Mis costuras me están diciendo algo...",
        "Híjole... esto se pone bueno.",
    ],
    "tie": [
        "Tu cabeza tiene lugar para dos casas. Tendré que escoger yo.",
        "Dos casas te quieren, fíjate nomás. Yo decido.",
        "Estás justo en medio de dos caminos. Esta vez escojo yo.",
        "Veo dos casas brillando en tu cabeza, como dos estrellas. Me toca elegir.",
    ],
    "pref_G": [
        "¿Gryffindor? Lo pides con valor, y eso ya dice mucho.",
        "Pides Gryffindor. Tú tocas primero en la puerta nueva, ¿verdad?",
    ],
    "pref_H": [
        "¿Hufflepuff? Buena elección: ahí nadie se queda sin compañía.",
        "Quieres Hufflepuff. Se nota: tú compartes tus dulces para que nadie se quede sin el suyo.",
    ],
    "pref_R": [
        "¿Ravenclaw? Con esa curiosidad, no me sorprende.",
        "Pides Ravenclaw... tú adivinas qué hay en la bolsa antes de abrirla.",
    ],
    "pref_S": [
        "¿Slytherin? Sabes lo que quieres, y eso es muy de esa casa.",
        "Pides Slytherin... y seguro ya planeaste la mejor ruta de la cuadra.",
    ],
    "reason_G": [
        "Por fuera hay calma, pero cuando algo es injusto, levantas la mano antes que nadie.",
        "Lo nuevo a veces te da nervios, y aun así das el primer paso.",
        "A veces dudas en silencio, pero cuando toca, das la cara.",
        "Te encanta la aventura, pero nunca dejas atrás a los tuyos.",
    ],
    "reason_H": [
        "No buscas aplausos, pero todos te buscan cuando necesitan ayuda.",
        "Tienes paciencia de sobra, y cuando hace falta, también sabes plantarte.",
        "Disfrutas el bullicio de una fiesta, y también un ratito en calma con los tuyos.",
        "Compartes lo que tienes, aunque sea tu favorito, y eso dice mucho de ti.",
    ],
    "reason_R": [
        "A veces te pierdes en tus pensamientos, y ahí encuentras las mejores ideas.",
        "Hablas poco cuando piensas, y cuando hablas, sorprendes.",
        "Te gusta entender cómo funcionan las cosas, y también disfrutas un misterio sin resolver.",
        "Tu cabeza guarda todo en su lugar, aunque a veces parezca un remolino de ideas.",
    ],
    "reason_S": [
        "Tienes planes grandes, aunque no se los cuentes a todos.",
        "Sabes esperar tu momento, y cuando llega, no lo dejas pasar.",
        "Puedes ser muy amable, y aun así nadie te convence de lo que no quieres.",
        "Te gusta ganar, pero lo que más disfrutas es el plan para lograrlo.",
    ],
    "house_G": [
        "¡Gryffindor!",
        "Ya está decidido: ¡Gryffindor!",
    ],
    "house_H": [
        "¡Hufflepuff!",
        "Que lo oiga toda la cuadra: ¡Hufflepuff!",
    ],
    "house_R": [
        "¡Ravenclaw!",
        "Lo veo clarísimo: ¡Ravenclaw!",
    ],
    "house_S": [
        "¡Slytherin!",
        "Mis costuras no mienten: ¡Slytherin!",
    ],
    "future_G": [
        "Esta noche vas a tocar una puerta nueva, y te van a abrir con una sonrisa.",
        "Veo que vas a ayudar a alguien sin que te lo pida, cerca de una calabaza encendida.",
        "Antes de que se apaguen las velitas, vas a animarte a algo nuevo, y te va a salir muy bien.",
    ],
    "future_H": [
        "Hoy vas a hacer una amistad nueva, quizá con alguien de disfraz parecido al tuyo.",
        "Alguien va a compartir contigo su pan de muerto, y tú vas a devolver el favor.",
        "Veo una carcajada compartida bajo esta misma luna.",
    ],
    "future_R": [
        "Esta noche se te va a prender el foco: una idea brillante va a llegar de repente.",
        "Vas a descubrir un detalle escondido entre las flores de cempasúchil que nadie más notó.",
        "Esta temporada vas a hacer una pregunta muy buena, y la respuesta te va a encantar.",
    ],
    "future_S": [
        "Un plan que traes en la cabeza va a salir mejor de lo que esperas, quizá esta misma noche.",
        "En tu bolsa vas a encontrar justo el dulce que querías, aunque todavía no sepas cuál es.",
        "Veo un pequeño triunfo en tu camino, antes de que la luna se esconda.",
    ],
    "season": [
        "Fíjate en las calabazas de la cuadra: una de ellas te va a guiñar el ojo.",
        "Si ves un gato negro hoy, salúdalo de mi parte; es amigo mío.",
        "La casa con más calabazas encendidas guarda un buen recuerdo para ti.",
        "Cuando toques la próxima puerta, vas a escuchar una risa antes de que te abran.",
        "Esta temporada las sonrisas abren puertas. Pide con una gran sonrisa: ¿me da mi calaverita?",
        "En el plato de un vecino te espera tu golosina favorita, escondida hasta abajo.",
        "Antes de que acabe la temporada vas a probar pan de muerto recién hecho.",
        "Esta temporada vas a compartir un chocolate caliente con alguien de tu familia.",
        "Vas a encontrar un pétalo de cempasúchil en el lugar menos pensado.",
        "Hoy un murciélago de papel te va a saludar desde una ventana.",
        "Cuando grites dulce o truco, alguien en la cuadra lo va a gritar contigo.",
        "Esta temporada alguien te va a contar una historia divertida que vas a recordar mucho tiempo.",
        "En mis tiempos se pedía con una caja de zapatos y una velita; tu bolsa va a brillar igual.",
        "Vas a seguir un caminito naranja de cempasúchil, y al final va a oler a pan de muerto.",
        "Gato negro y luna llena: esta noche viene buena.",
    ],
    "farewell": [
        "Anda, ve y disfruta la noche. Este sombrero se queda pensando en ti.",
        "Ándale, que la calle está llena de calabazas encendidas. ¡A pedir calaverita!",
        "Que te vaya bonito, y que tu bolsa se llene de dulces.",
        "Ya está. Que pase la siguiente cabeza valiente.",
        "Fue un gusto leerte. Que tengas una temporada llena de dulces y risas.",
        "Ve y presume tu casa. Yo me quedo aquí, con las velitas.",
        "Gracias por prestarme tu cabeza un ratito. ¡Feliz Halloween!",
        "Ahora, a pedir dulces. Y no olvides dar las gracias en cada puerta.",
        "Con tu bolsa y calabaza, ve tocando cada casa.",
        "Órale, a disfrutar la noche. Guárdame un chocolate, aunque yo no tenga con qué comerlo.",
    ],
}


# How an option is written on the operator's buttons (the id without its accents otherwise).
LABELS = {"volcan": "Volcán",
          "jardin": "Jardín",
          "dragon": "Dragón",
          "brujula": "Brújula",
          "puertas": "De puerta en puerta",
          "murcielago": "Murciélago"}


def label(option_id: str) -> str:
    return LABELS.get(option_id, option_id.capitalize())


def question(qid: str) -> dict:
    for qs in SETS.values():
        for q in qs:
            if q["id"] == qid:
                return q
    raise KeyError(qid)


def prompt_name(qid: str) -> str:
    return f"show_q_{qid}"


def reprompt_name(qid: str) -> str:
    return f"show_rq_{qid}"


def reaction_name(qid: str, option: str) -> str:
    return f"show_re_{qid}_{option}"


def pool_names(slot: str) -> list[str]:
    return [f"show_{slot}_{i}" for i in range(1, len(POOLS[slot]) + 1)]


def _phrases() -> dict[str, str]:
    out: dict[str, str] = {}
    for qs in SETS.values():
        for q in qs:
            out[prompt_name(q["id"])] = q["prompt"]
            out[reprompt_name(q["id"])] = q["reprompt"]
            for o in q["options"]:
                out[reaction_name(q["id"], o["id"])] = o["reaction"]
    for slot, lines in POOLS.items():
        for name, text in zip(pool_names(slot), lines):
            out[name] = text
    return out


SHOW_PHRASES: dict[str, str] = _phrases()
