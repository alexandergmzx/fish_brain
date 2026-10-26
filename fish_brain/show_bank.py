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
times, no venue names. Nothing here is taken from the books, the films or the official quiz.
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
         "prompt": "Imagina dos puertas. Detrás de una suena una fiesta y detrás de la otra te "
                   "espera un acertijo. ¿Fiesta... o acertijo?",
         "reprompt": "Dime nomás: ¿fiesta... o acertijo?",
         "options": [
             {"id": "fiesta", "words": ["fiesta", "fiestas", "fiestota", "pachanga", "la fiesta"],
              "scores": {"G": AXIS, "H": AXIS},
              "reaction": "¡Fiesta! Ya sabía: contigo nadie se queda fuera.",
              "why": "people, joy"},
             {"id": "acertijo", "words": ["acertijo", "acertijos", "adivinanza", "adivinanzas"],
              "scores": {"R": AXIS, "S": AXIS},
              "reaction": "Un acertijo. Esa cabecita no descansa nunca.",
              "why": "head, a puzzle to win"},
         ]},
        {"id": "A2",
         "prompt": "Ahora, sin pensarlo mucho: ¿eres más volcán... o más jardín?",
         "reprompt": "¿Volcán... o jardín?",
         "options": [
             {"id": "volcan", "words": ["volcan", "volcanes", "el volcan"],
              "scores": {"G": AXIS, "S": AXIS},
              "reaction": "¡Volcán! Hay fuego ahí adentro, se nota.",
              "why": "out in front"},
             {"id": "jardin", "words": ["jardin", "jardines", "el jardin", "jardincito"],
              "scores": {"H": AXIS, "R": AXIS},
              "reaction": "Jardín. Lo tuyo crece despacito, pero crece fuerte.",
              "why": "steady, inside"},
         ]},
        {"id": "A3",
         "prompt": "Última pregunta. Si te mandaran a una isla, ¿qué te llevarías: un mapa, un "
                   "libro, un amigo o un trofeo?",
         "reprompt": "¿Mapa, libro, amigo o trofeo?",
         "options": [
             {"id": "mapa", "words": ["mapa", "mapas", "el mapa", "un mapa"],
              "scores": {"G": TRAIT},
              "reaction": "Un mapa: tú no esperas a que llegue la aventura, la vas a buscar.",
              "why": "adventure"},
             {"id": "libro", "words": ["libro", "libros", "el libro", "un libro"],
              "scores": {"R": TRAIT},
              "reaction": "Un libro. Hasta en una isla quieres aprender algo.",
              "why": "curiosity"},
             {"id": "amigo", "words": ["amigo", "amiga", "amigos", "amigas", "mejor amigo",
                                       "mejor amiga"],
              "scores": {"H": TRAIT},
              "reaction": "Un amigo. Con buena compañía, cualquier isla es fiesta.",
              "why": "loyalty"},
             {"id": "trofeo", "words": ["trofeo", "trofeos", "copa", "medalla"],
              "scores": {"S": TRAIT},
              "reaction": "¡Un trofeo! Ni en una isla dejas de pensar en ganar.",
              "why": "ambition"},
         ]},
    ],
    "B": [
        {"id": "B1",
         "prompt": "Para resolver un problema, ¿qué prefieres: armar un equipo... o investigar "
                   "el misterio por tu cuenta?",
         "reprompt": "¿Equipo... o misterio?",
         "options": [
             {"id": "equipo", "words": ["equipo", "equipos", "un equipo", "en equipo"],
              "scores": {"G": AXIS, "H": AXIS},
              "reaction": "Equipo. Sabes que juntos se llega más lejos.",
              "why": "people"},
             {"id": "misterio", "words": ["misterio", "misterios", "el misterio", "investigar"],
              "scores": {"R": AXIS, "S": AXIS},
              "reaction": "Misterio. Te gusta llegar al fondo de las cosas.",
              "why": "head, on one's own"},
         ]},
        {"id": "B2",
         "prompt": "Si pudieras tener una mascota mágica, ¿sería un dragón... o una tortuga?",
         "reprompt": "¿Dragón... o tortuga?",
         "options": [
             {"id": "dragon", "words": ["dragon", "dragones", "un dragon", "dragoncito"],
              "scores": {"G": AXIS, "S": AXIS},
              "reaction": "¡Un dragón! Nada de mascotas tímidas para ti.",
              "why": "bold"},
             {"id": "tortuga", "words": ["tortuga", "tortugas", "tortuguita", "una tortuga"],
              "scores": {"H": AXIS, "R": AXIS},
              "reaction": "Una tortuga. Paciencia y concha dura: buena combinación.",
              "why": "patient"},
         ]},
        {"id": "B3",
         "prompt": "Y para tu viaje, ¿qué te llevas: una brújula, un telescopio, una canasta o "
                   "una escalera?",
         "reprompt": "¿Brújula, telescopio, canasta o escalera?",
         "options": [
             {"id": "brujula", "words": ["brujula", "brujulas", "la brujula", "una brujula"],
              "scores": {"G": TRAIT},
              "reaction": "La brújula: siempre hacia adelante, aunque no sepas qué hay.",
              "why": "adventure"},
             {"id": "telescopio", "words": ["telescopio", "telescopios", "el telescopio"],
              "scores": {"R": TRAIT},
              "reaction": "El telescopio. Quieres ver más lejos que todos.",
              "why": "curiosity"},
             {"id": "canasta", "words": ["canasta", "canastas", "canastita", "cesta", "la canasta"],
              "scores": {"H": TRAIT},
              "reaction": "La canasta, para compartir el almuerzo. Qué buen corazón.",
              "why": "sharing"},
             {"id": "escalera", "words": ["escalera", "escaleras", "la escalera"],
              "scores": {"S": TRAIT},
              "reaction": "La escalera: siempre un escalón más arriba, ¿verdad?",
              "why": "ambition"},
         ]},
    ],
    "C": [
        {"id": "C1",
         "prompt": "Si mañana armaras algo, ¿sería una banda de música... o un torneo de ajedrez?",
         "reprompt": "¿Banda... o ajedrez?",
         "options": [
             {"id": "banda", "words": ["banda", "bandas", "la banda", "musica", "banda de musica"],
              "scores": {"G": AXIS, "H": AXIS},
              "reaction": "¡Una banda! Te gusta que todos canten contigo.",
              "why": "people"},
             {"id": "ajedrez", "words": ["ajedrez", "el ajedrez", "torneo", "torneo de ajedrez"],
              "scores": {"R": AXIS, "S": AXIS},
              "reaction": "Ajedrez. Piensas tres jugadas antes que los demás.",
              "why": "strategy"},
         ]},
        {"id": "C2",
         "prompt": "Escoge una para ti: ¿un cohete que despega... o una semilla que crece?",
         "reprompt": "¿Cohete... o semilla?",
         "options": [
             {"id": "cohete", "words": ["cohete", "cohetes", "el cohete", "un cohete"],
              "scores": {"G": AXIS, "S": AXIS},
              "reaction": "¡Un cohete! Tú quieres despegar ya.",
              "why": "now, upward"},
             {"id": "semilla", "words": ["semilla", "semillas", "semillita", "la semilla"],
              "scores": {"H": AXIS, "R": AXIS},
              "reaction": "Una semilla. Sabes esperar lo que vale la pena.",
              "why": "growth"},
         ]},
        {"id": "C3",
         "prompt": "Por último, ¿qué palabra te llama más: aventura, invento, amistad o victoria?",
         "reprompt": "¿Aventura, invento, amistad o victoria?",
         "options": [
             {"id": "aventura", "words": ["aventura", "aventuras", "la aventura"],
              "scores": {"G": TRAIT},
              "reaction": "Aventura. Ya te veo empacando la mochila.",
              "why": "adventure"},
             {"id": "invento", "words": ["invento", "inventos", "inventar", "un invento"],
              "scores": {"R": TRAIT},
              "reaction": "Un invento. Algo vas a construir muy pronto, te lo aseguro.",
              "why": "curiosity"},
             {"id": "amistad", "words": ["amistad", "amistades", "la amistad"],
              "scores": {"H": TRAIT},
              "reaction": "Amistad. Esa es la magia más fuerte que conozco.",
              "why": "loyalty"},
             {"id": "victoria", "words": ["victoria", "victorias", "ganar", "la victoria"],
              "scores": {"S": TRAIT},
              "reaction": "Victoria. Te gusta ganar, y eso no tiene nada de malo.",
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
        "¡Qué gusto verte! Acércate, que este sombrero viejo quiere asomarse a tu cabeza.",
        "Ah, una cabeza nueva. Déjame ver qué guardas ahí adentro.",
        "¡Llegaste justo a tiempo! Hoy tengo ganas de leer mentes.",
        "Pásale, pásale. Prometo no despeinarte mucho.",
        "Mmm, siento una mente inquieta. Vamos a averiguar a dónde perteneces.",
        "Hola, hola. Contesta mis preguntas y yo te diré tu casa.",
        "¡Qué alegría! Llevaba rato sin ver una cabeza tan interesante.",
        "Aquí estoy. Tú solo responde, que del resto me encargo yo.",
    ],
    "nose": [
        "Quien duda es porque piensa. Eso también lo anoto.",
        "No pasa nada: tu cara me contesta por ti.",
        "Mmm, un misterio. Me gustan los misterios.",
    ],
    "bridge": [
        "No hace falta que lo digas: tu cara ya me lo contó.",
        "Shh, no digas nada; lo estoy leyendo directo de tu cabeza.",
        "Ya lo vi. A veces las respuestas se oyen mejor en silencio.",
        "Muy bien, lo guardo aquí entre mis costuras.",
        "Tu mirada contestó antes que tú. Sigamos.",
        "Eso que pensaste me basta. Vamos con lo siguiente.",
    ],
    "suspense": [
        "Mmm... déjame pensarlo bien.",
        "Ya casi lo tengo...",
        "A ver, a ver... se está aclarando.",
        "Siento algo... sí, ya lo veo.",
        "Un momento, que esto es importante.",
        "Mis costuras me están diciendo algo...",
    ],
    "tie": [
        "Tu cabeza tiene lugar para dos casas. Tendré que escoger yo.",
        "Dos casas te quieren, fíjate nomás. Yo decido.",
        "Estás justo en medio de dos caminos. Elijo por ti.",
    ],
    "pref_G": ["¿Gryffindor? Lo pides con valor, y eso ya dice mucho.",
               "Pides Gryffindor... y tu corazón no me deja decir que no."],
    "pref_H": ["¿Hufflepuff? Buena elección: ahí nadie se queda sin compañía.",
               "Quieres Hufflepuff, y yo veo que te lo has ganado."],
    "pref_R": ["¿Ravenclaw? Con esa curiosidad, no me sorprende.",
               "Pides Ravenclaw... tu cabeza ya estaba allá antes que tú."],
    "pref_S": ["¿Slytherin? Sabes lo que quieres, y eso es muy de ahí.",
               "Pides Slytherin... y tienes planes, se nota."],
    "reason_G": [
        "Por fuera hay calma, pero cuando algo es injusto, levantas la mano antes que nadie.",
        "Lo nuevo te da nervios, y aun así siempre das el primer paso.",
        "Tienes un corazón que no se rinde, aunque a veces se canse.",
        "Te gusta la aventura, y cuidas a los tuyos en el camino.",
    ],
    "reason_H": [
        "No buscas aplausos, pero todos te buscan cuando necesitan ayuda.",
        "Tienes paciencia, y cuando alguien te importa, no lo sueltas.",
        "Contigo se puede contar, en las buenas y en las malas.",
        "Compartes lo que tienes, y eso vale más que cualquier tesoro.",
    ],
    "reason_R": [
        "A veces te pierdes en tus pensamientos, y ahí encuentras las mejores ideas.",
        "Preguntas por qué a todo, y eso es un regalo.",
        "Te gusta entender cómo funcionan las cosas, hasta las más raras.",
        "Con pocas o muchas palabras, tu mente nunca deja de inventar.",
    ],
    "reason_S": [
        "Tienes planes grandes, aunque no se los cuentes a todos.",
        "Cuando quieres algo, encuentras la manera.",
        "Tienes astucia, y sabes guardar un secreto.",
        "Te gusta ganar, y también sabes esperar el momento justo.",
    ],
    "house_G": ["¡Gryffindor!", "Ya está decidido: ¡Gryffindor!"],
    "house_H": ["¡Hufflepuff!", "Ya está decidido: ¡Hufflepuff!"],
    "house_R": ["¡Ravenclaw!", "Ya está decidido: ¡Ravenclaw!"],
    "house_S": ["¡Slytherin!", "Ya está decidido: ¡Slytherin!"],
    "future_G": [
        "Hoy vas a atreverte a algo nuevo; si no es hoy, será muy pronto.",
        "Veo que vas a ayudar a alguien sin que te lo pida, y te lo van a agradecer.",
        "Antes de irte vas a probar algo que nunca habías probado, y te va a encantar.",
    ],
    "future_H": [
        "Hoy vas a hacer una amistad nueva; fíjate bien quién te sonríe.",
        "Alguien va a compartir algo contigo hoy, y tú vas a devolver el favor.",
        "Veo una risa compartida antes de que termine el día.",
    ],
    "future_R": [
        "Hoy vas a descubrir cómo funciona algo que te intrigaba; si no hoy, muy pronto.",
        "Una idea te va a llegar de repente, quizá aquí mismo. Anótala.",
        "Vas a hacer una pregunta que nadie más se atrevió a hacer, y te va a ir muy bien.",
    ],
    "future_S": [
        "Veo un pequeño triunfo en tu camino, más pronto de lo que crees.",
        "Hoy vas a encontrar justo lo que buscabas, aunque todavía no sepas qué es.",
        "Un plan que traes en la cabeza va a salir mejor de lo que esperas.",
    ],
    "fair": [
        "En esta feria hay un invento esperándote; búscalo con calma.",
        "Date una vuelta por los talleres: algo ahí trae tu nombre.",
        "Si ves un robot hoy, salúdalo de mi parte.",
        "Fíjate en las luces: una de ellas te va a dar una idea.",
        "Antes de irte, pregúntale algo a quien inventó alguna cosa; te va a sorprender la respuesta.",
        "Hoy alguien te va a enseñar a hacer algo con tus propias manos.",
        "Busca el puesto que más ruido haga: ahí hay algo para ti.",
        "Llévate una idea de aquí; las ideas no pesan.",
        "Si algo se descompone hoy, tú vas a saber arreglarlo.",
        "Prueba algo que nunca hayas probado en esta feria.",
        "Un cable, un tornillo o un botón te va a llamar la atención hoy.",
        "Sonríele a la primera persona que veas al salir; te va a traer suerte.",
    ],
    "farewell": [
        "Anda, ve y disfruta. Este sombrero se queda pensando en ti.",
        "Listo. Ve con orgullo a tu casa.",
        "Que te vaya bonito. Y no le digas a nadie lo que vimos en tu cabeza.",
        "Ya está. Que pase la siguiente cabeza valiente.",
        "Fue un gusto leerte. Hasta la próxima.",
        "Ve y presume tu casa. Yo me quedo aquí, pensando.",
        "Gracias por prestarme tu cabeza un ratito.",
        "Listo, ahora a disfrutar la feria.",
    ],
}


# How an option is written on the operator's buttons (the id without its accents otherwise).
LABELS = {"volcan": "Volcán", "jardin": "Jardín", "dragon": "Dragón", "brujula": "Brújula"}


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
