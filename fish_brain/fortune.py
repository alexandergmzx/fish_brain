"""The fortune act's tables and parsers (docs/adr/0019): pure, no state, no clips.

The hat asks an adult visitor the day and month of birth, a recent dream, a tarot card, the
shape in the cup and an animal, and everything heard is parsed here into ids the bank
(fortune_bank.py) has a line for and the model gets as a tag:

    parse_birth(text) -> (day, month)   sign_of(day, month)   lucky_number(day, month)
    dream_theme(text) -> a theme id     parse_card(text, deck) -> 0..21
    parse_shape(text) -> a shape id     ANIMAL_Q for show.match_option
    moon_tonight() -> a phase id        reading_tag(f, deck) -> "[ADIVINACIÓN: …] Haz la lectura."
    clean_reading(reply) -> the model's reading, or None when it breaks the register

Transcripts arrive folded (no accents, lower case; ñ is already n) with 7 to 21 % word errors,
so a keyword can be a stem ("persegu*" matches "perseguian") and a month or a card name is
also tried by sound (show.phon_key). Anything unclear is None: the act asks again or moves on,
a wrong callback breaks the illusion more than a generic line. The matcher conventions follow
show.py; the show modules never import this one.

The moon: the mean phase from the new moon of 2000-01-06 18:14 UTC and the mean synodic
month, rounded to eight phases. Checked against the October 2026 dates (new moon 10th 15:50
UTC, first quarter 18th 16:13, full moon 26th 04:12, last quarter 3rd 13:25:
https://starwalk.space/news/full-moon-october, https://theskylive.com/full-moon-october-2026,
https://cdn.almanac.com/astronomy/moon/calendar/OH/Troy/2026-10): the mean formula is 17 h
late on that new moon and half an hour off on that full moon, well inside the 3.7 days of one
phase, so the boundaries are the plain eighths.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from difflib import SequenceMatcher

from .show import phon_key
from .visit import _fold

_NOTE = re.compile(r"\[[^\]]*\]")
_KEEP = re.compile(r"[^a-z0-9ñ ]")
# Words that carry no answer, dropped before a card is matched (show.CARRIERS, plus the
# ones a visitor adds in front of a card: "me salió la luna", "saqué el sol").
_CARRIERS = frozenset("el la los las un una unos unas mi mis tu yo digo elijo escojo escogo "
                      "prefiero pues este esta eh mm mmm ah o y a de del que creo me sali salio "
                      "saque toco tocó carta numero es".split())


def strip_notes(text: str) -> str:
    """Without the "[Nota: …]" of a transcript and any other bracketed tag."""
    return " ".join(_NOTE.sub(" ", text or "").split())


def tokens(text: str) -> list[str]:
    """Folded words and numbers; "23/10" and "1ro" come apart ("23", "10", "1", "ro")."""
    s = _fold(strip_notes(text).replace("/", " "))
    s = re.sub(r"(\d)([a-zñ])", r"\1 \2", s)
    s = re.sub(r"([a-zñ])(\d)", r"\1 \2", s)
    return _KEEP.sub(" ", s).split()


# ---- numbers and dates ---------------------------------------------------------------------
_UNITS = {"cero": 0, "uno": 1, "primero": 1, "primer": 1, "dos": 2, "tres": 3, "cuatro": 4,
          "cinco": 5, "seis": 6, "siete": 7, "ocho": 8, "nueve": 9, "diez": 10, "once": 11,
          "doce": 12, "trece": 13, "catorce": 14, "quince": 15, "dieciseis": 16,
          "diecisiete": 17, "dieciocho": 18, "diecinueve": 19, "veinte": 20, "veintiuno": 21,
          "veintiun": 21, "veintidos": 22, "veintitres": 23, "veinticuatro": 24,
          "veinticinco": 25, "veintiseis": 26, "veintisiete": 27, "veintiocho": 28,
          "veintinueve": 29, "treinta": 30}
_TENS = {"diez": 10, "veinte": 20, "treinta": 30, "veinti": 20}
MAX_NUMBER = 31


def numbers_in(ws: list[str]) -> list[tuple[int, int]]:
    """(index, value) of every number said in `ws`: digits, the words up to "treinta",
    "treinta y uno" and "veinti tres" as one. Anything over 31 (a year) is dropped."""
    out: list[tuple[int, int]] = []
    i = 0
    while i < len(ws):
        w = ws[i]
        value, used = None, 1
        if w.isdigit():
            value = int(w)
        elif w in _TENS and i + 1 < len(ws):
            nxt = ws[i + 1]
            if w == "veinti" and nxt in _UNITS and 0 < _UNITS[nxt] < 10:
                value, used = 20 + _UNITS[nxt], 2
            elif nxt == "y" and i + 2 < len(ws) and ws[i + 2] in _UNITS and 0 < _UNITS[ws[i + 2]] < 10:
                value, used = _TENS[w] + _UNITS[ws[i + 2]], 3
        if value is None and w in _UNITS:
            value = _UNITS[w]
        if value is not None and value <= MAX_NUMBER:
            out.append((i, value))
        i += used
    return out


MONTHS = ("enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto",
          "septiembre", "octubre", "noviembre", "diciembre")
_MONTH_ALIASES = {"setiembre": 9}
_MONTH_DAYS = (31, 29, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31)   # no year: the 29th is a day
MONTH_RATIO = 0.80


def _month_at(w: str) -> int | None:
    """The month a word names (1..12), by spelling or by sound (unique, first letter equal)."""
    if w in MONTHS:
        return MONTHS.index(w) + 1
    if w in _MONTH_ALIASES:
        return _MONTH_ALIASES[w]
    if len(w) < 4 or w.isdigit():
        return None
    key = phon_key(w)
    scores = sorted(((SequenceMatcher(None, key, phon_key(m)).ratio(), n)
                     for n, m in enumerate(MONTHS, 1) if m[0] == w[0]), reverse=True)
    if scores and scores[0][0] >= MONTH_RATIO and (len(scores) == 1 or scores[0][0] - scores[1][0] >= 0.1):
        return scores[0][1]
    return None


def valid_date(day: int, month: int) -> bool:
    return 1 <= month <= 12 and 1 <= day <= _MONTH_DAYS[month - 1]


def parse_birth(text: str) -> tuple[int, int] | None:
    """(day, month) in "el 23 de octubre", "veintitrés de octubre de 2015" (the year is never
    read), "octubre 23", "23/10", "el primero de mayo", "diez del once". A month word takes
    the nearest number on its left, else on its right; without a month word, the first two
    numbers are day then month. None when no date fits."""
    ws = tokens(text)
    nums = numbers_in(ws)
    month_i = next(((i, m) for i, w in enumerate(ws) if (m := _month_at(w))), None)
    if month_i is not None:
        i, month = month_i
        left = [n for n in nums if n[0] < i]
        right = [n for n in nums if n[0] > i]
        day = left[-1][1] if left else right[0][1] if right else None
        return (day, month) if day is not None and valid_date(day, month) else None
    if len(nums) >= 2:
        day, month = nums[0][1], nums[1][1]
        return (day, month) if valid_date(day, month) else None
    return None


# ---- the zodiac -----------------------------------------------------------------------------
@dataclass(frozen=True)
class Sign:
    id: str
    name: str
    said: str
    element: str
    start: tuple[int, int]          # (month, day) of its first day, tropical cut-offs
    aliases: tuple[str, ...] = ()


SIGNS: tuple[Sign, ...] = (
    Sign("capricornio", "Capricornio", "Capricornio", "tierra", (12, 22), ("capricornio", "capri")),
    Sign("acuario", "Acuario", "Acuario", "aire", (1, 20), ("acuario", "aquario")),
    Sign("piscis", "Piscis", "Piscis", "agua", (2, 19), ("piscis", "pisis")),
    Sign("aries", "Aries", "Aries", "fuego", (3, 21), ("aries",)),
    Sign("tauro", "Tauro", "Tauro", "tierra", (4, 20), ("tauro", "toro")),
    Sign("geminis", "Géminis", "Géminis", "aire", (5, 21), ("geminis", "gemini", "jeminis")),
    Sign("cancer", "Cáncer", "Cáncer", "agua", (6, 21), ("cancer",)),
    Sign("leo", "Leo", "Leo", "fuego", (7, 23), ("leo", "leon")),
    Sign("virgo", "Virgo", "Virgo", "tierra", (8, 23), ("virgo",)),
    Sign("libra", "Libra", "Libra", "aire", (9, 23), ("libra",)),
    Sign("escorpio", "Escorpio", "Escorpio", "agua", (10, 23), ("escorpio", "escorpion", "scorpio")),
    Sign("sagitario", "Sagitario", "Sagitario", "fuego", (11, 22), ("sagitario", "sagitarius")),
)
SIGN_BY_ID: dict[str, Sign] = {s.id: s for s in SIGNS}
SIGN_RATIO = 0.85


def sign_of(day: int, month: int) -> str:
    """The sign id of a birthday: the last sign whose first day is on or before it; before
    the 20th of January it is still Capricornio."""
    md = (month, day)
    if md >= SIGNS[0].start:            # the 22nd of December on: Capricornio wraps the year
        return SIGNS[0].id
    sign = SIGNS[0]
    for s in SIGNS[1:]:
        if md >= s.start:
            sign = s
    return sign.id


def parse_sign(text: str) -> str | None:
    """A sign said directly ("soy escorpio", "escorpión", "Cáncer"), by spelling or by sound
    when one sign alone is close. None when none or two are heard."""
    ws = tokens(text)
    if not ws:
        return None
    found: list[str] = []
    for s in SIGNS:
        if any(a in ws for a in s.aliases):
            found.append(s.id)
    if len(found) == 1:
        return found[0]
    if found:
        return None
    keys = [phon_key(w) for w in ws if len(w) >= 4]
    scores = sorted(((SequenceMatcher(None, k, phon_key(s.aliases[0])).ratio(), s.id)
                     for s in SIGNS for k in keys if k[:1] == phon_key(s.aliases[0])[:1]), reverse=True)
    if scores and scores[0][0] >= SIGN_RATIO and (len(scores) == 1 or scores[0][1] == scores[1][1]
                                                   or scores[0][0] - scores[1][0] >= 0.1):
        return scores[0][1]
    return None


def lucky_number(day: int, month: int) -> int:
    """The digits of the day and the month added until one digit is left (23/10 -> 6)."""
    n = sum(int(c) for c in f"{day}{month}")
    while n > 9:
        n = sum(int(c) for c in str(n))
    return n


# ---- keyword themes (dreams, the cup) -------------------------------------------------------
@dataclass(frozen=True)
class Theme:
    id: str
    label: str
    keywords: tuple[str, ...]       # folded words or phrases; a word ending in "*" is a stem
    weight: int = 1


def _hits(ws: list[str], theme: Theme) -> list[tuple[int, int]]:
    """(index, length) of every keyword of `theme` found in `ws`, whole words only."""
    out = []
    for kw in theme.keywords:
        parts = kw.split()
        n = len(parts)
        for i in range(len(ws) - n + 1):
            if all((ws[i + j].startswith(p[:-1]) if p.endswith("*") else ws[i + j] == p)
                   for j, p in enumerate(parts)):
                out.append((i, n))
                break
    return out


def _best_theme(ws: list[str], themes: tuple[Theme, ...]) -> str | None:
    """The theme with the most weighted hits; a tie goes to the one mentioned first, then to
    the longer phrase. None without a hit."""
    best = None
    for order, t in enumerate(themes):
        hits = _hits(ws, t)
        if not hits:
            continue
        key = (len(hits) * t.weight, -min(i for i, _n in hits), max(n for _i, n in hits), -order)
        if best is None or key > best[0]:
            best = (key, t.id)
    return best[1] if best else None


DREAM_THEMES: tuple[Theme, ...] = (
    Theme("perseguido", "Que te persiguen", (
        "me persegu*", "persegu*", "persecucion", "corret*", "me segui*", "huia", "huyendo",
        "escapaba", "escapando", "me querian atrapar", "me querian agarrar", "me alcanzaba",
        "me alcanzaban", "me atrapa*", "me agarraban", "me escondia", "corria", "corriendo")),
    Theme("caer", "Caer al vacío", (
        "me cai*", "cayendo", "caerme", "caida", "al vacio", "precipicio", "abismo",
        "barranc*", "desde lo alto", "desde un edificio", "me resbal*", "me avent*",
        "me tropezaba", "se me va el piso", "un hoyo", "desperte de golpe")),
    Theme("escuela", "La escuela, un examen sin estudiar", (
        "escuela", "colegio", "la prepa", "secundaria", "primaria", "kinder", "salon de clases",
        "maestr*", "profe*", "tarea", "estudiar", "estudiaba", "clase", "clases", "recreo",
        "mochila", "uniforme", "examen", "examenes", "no estudie", "no habia estudiado",
        "reprob*", "calificacion", "quede en blanco", "no sabia la respuesta", "la tesis",
        "titulo", "la universidad", "universidad")),
    Theme("tarde", "Se te hace tarde, no te puedes mover", (
        "llego tarde", "llegaba tarde", "llegue tarde", "se me hace tarde", "se me hacia tarde",
        "se me hizo tarde", "retraso", "perdi el camion", "pierdo el camion", "el camion se fue",
        "perdi el avion", "perdi el metro", "perdi el vuelo", "no alcanzo", "no alcanzaba",
        "no llegaba", "apurad*", "no podia correr", "corria lento", "corria despacio",
        "en camara lenta", "no avanzaba", "no me podia mover", "no podia moverme",
        "no podia gritar", "no me salia la voz", "paralizad*", "atorad*", "atrapad*",
        "encerrad*", "una y otra vez", "no me salia", "no lo lograba", "se repetia",
        "arena movediza")),
    Theme("seres_queridos", "Un ser querido, o alguien que ya cruzó", (
        "mi abuel*", "abuelit*", "que ya murio", "que ya se murio", "que ya fallecio",
        "que ya se fue", "que ya no esta", "fallecid*", "difunt*", "finad*", "en paz descanse",
        "se me aparecio", "me visito", "vino a verme", "me hablo", "me abrazo", "del mas alla",
        "anima", "animas", "panteon", "cementerio", "se murio", "se moria", "se muere",
        "mi mama", "mi papa", "mis papas", "mi herman*", "mi familia", "mi tia", "mi tio",
        "mi prim*", "mi perrito que ya no esta", "mi esposo", "mi esposa", "mis hijos",
        "mi hijo", "mi hija", "la ofrenda"), weight=2),
    Theme("monstruos", "Monstruos, fantasmas, una presencia", (
        "monstruo*", "mounstr*", "criatura", "fantasma*", "espanto", "espiritu", "una sombra",
        "alguien me miraba", "una presencia", "casa embrujada", "zombi*", "muertos vivientes",
        "bruja", "brujas", "vampir*", "momia", "esqueleto", "payaso*", "dinosaurio*", "dragon*",
        "hombre lobo", "el coco", "el cucuy", "la llorona", "nahual", "chupacabras",
        "me queria comer", "me iba a comer", "me asustaba", "me espantaba", "me dio miedo",
        "daba miedo", "pesadilla*", "susto", "la catrina", "calavera*")),
    Theme("volar", "Volar, flotar, tener poderes", (
        "volaba", "vuelo", "volando", "volar", "vole", "podia volar", "flotaba", "flotando",
        "flotar", "levitar", "levitaba", "me elevaba", "por el cielo", "por los aires",
        "con alas", "como pajaro", "como superman", "superheroe*", "spiderman", "batman",
        "poderes", "superpoderes", "magia", "magic*", "hechizo", "varita", "invisible",
        "superfuerza", "era muy fuerte", "lanzaba rayos", "teletransport*", "era bruja",
        "era mago", "era hada")),
    Theme("agua", "El mar, nadar, la lluvia", (
        "nadaba", "nadando", "nadar", "alberca", "piscina", "el mar", "la playa", "olas",
        "ola gigante", "tsunami", "el rio", "un rio", "lago", "laguna", "cascada", "agua",
        "bajo el agua", "me ahogaba", "inundacion", "se inundaba", "lluvia", "llovia",
        "lloviendo", "me mojaba", "charco", "barco", "lancha", "arcoiris")),
    Theme("dientes", "Que se te caen los dientes", (
        "diente*", "muela*", "se me aflojaban", "sin dientes", "chimuel*", "dentadura",
        "raton de los dientes", "raton perez"), weight=2),
    Theme("bichos", "Arañas, cucarachas, alacranes, ratones", (
        "arana", "aranas", "tarantula", "telarana", "insecto*", "bicho*", "cucaracha*",
        "hormiga*", "abeja*", "avispa*", "mosca*", "gusano*", "escarabajo", "chapulines",
        "grillos", "alacran*", "escorpion*", "piojo*", "liendres", "pulgas", "garrapata",
        "raton", "ratones", "rata", "ratas", "me picaba*")),
    Theme("serpientes", "Víboras y serpientes", (
        "serpiente*", "vibora*", "culebra*", "cascabel", "cobra", "boa", "anaconda", "piton",
        "me mordia una vibora", "me mordio una vibora")),
    Theme("animales", "Perros, gatos, caballos, pájaros", (
        "perro*", "perrit*", "cachorro", "lomito", "xolo", "me ladraba", "gato", "gatos",
        "gatit*", "gata", "gato negro", "michi", "minino", "caballo*", "yegua", "pony",
        "montaba a caballo", "burro", "vaca", "vacas", "toro", "borrego", "pajaro*",
        "pajarit*", "colibri", "paloma", "buho", "lechuza", "tecolote", "murcielago*",
        "mariposa*", "monarca", "conejo", "tortuga", "pez", "peces", "delfin", "ballena",
        "tiburon", "cocodrilo", "leon", "tigre", "lobo", "lobos", "oso", "elefante",
        "mi mascota", "animal", "animales", "sapo", "rana")),
    Theme("jugar", "Jugar, una fiesta, comer rico, la infancia", (
        "jugaba", "jugando", "juego", "juegos", "videojuego*", "minecraft", "roblox",
        "fortnite", "mario", "nintendo", "fiesta", "cumpleanos", "pinata", "pastel", "dulces",
        "chocolate", "helado", "nieve", "tacos", "pizza", "hamburguesa", "tamales", "pozole",
        "pan de muerto", "comida", "comia", "comiendo", "banquete", "feria",
        "parque de diversiones", "montana rusa", "juegos mecanicos", "futbol", "metia gol",
        "mis amigos", "con mis amigos", "me divertia", "bailaba", "cantaba", "mis juguetes",
        "era nino", "era nina", "cuando era chic*", "de pequen*", "mi infancia", "concierto",
        "famos*", "cantante", "youtuber", "me iba de antro", "el antro", "borrach*",
        "la peda", "la cruda")),
    Theme("casa", "Una casa rara, un cuarto nuevo, perderse", (
        "cuarto nuevo", "un cuarto que no conocia", "habitacion nueva", "habitacion secreta",
        "cuarto secreto", "puerta secreta", "puerta escondida", "casa enorme",
        "mi casa era mas grande", "casa nueva", "casa rara", "casa desconocida", "casa vieja",
        "casa abandonada", "escaleras", "sotano", "azotea", "pasillo*",
        "laberinto", "me perdi", "me perdia", "perdid*", "no encontraba el camino",
        "no encontraba mi casa", "no sabia donde estaba", "no sabia como regresar",
        "me dejaron", "me quede sol*", "lugar desconocido", "niebla", "bosque",
        "departamento")),
    Theme("vehiculo", "Un carro, un camión, un avión, un viaje", (
        "carro", "coche", "camioneta", "troca", "manejaba", "manejando", "manejar",
        "iba manejando", "sin frenos", "no frenaba", "los frenos", "perdi el control",
        "sin control", "volante", "choque", "chocaba", "chocabamos", "me atropellaban", "bici",
        "bicicleta", "moto", "avion", "aeropuerto", "tren", "metro", "trafico", "camion",
        "viaje", "viajaba", "viajando", "maleta*", "vacaciones", "otro pais", "carretera",
        "de paseo", "uber")),
    Theme("elementos", "Fuego, tormenta, temblor", (
        "fuego", "lumbre", "llamas", "incendio", "se quemaba", "se quemo", "se incendiaba",
        "quemando", "humo", "fogata", "velas", "explosion", "volcan", "lava", "tormenta",
        "tornado", "huracan", "mucho viento", "truenos", "relampagos", "rayos y truenos",
        "granizo", "temblor", "temblaba", "temblo", "sismo", "terremoto", "alerta sismica",
        "se caia todo", "se derrumbaba", "se movia todo", "simulacro")),
    # The three the kids' act had routed away; adults get a line of their own.
    Theme("ex", "El ex, o un amor", (
        "mi ex", "ex", "exnovi*", "ex novi*", "expareja", "ex pareja", "exesos*", "ex esos*",
        "exmarid*", "ex marid*", "ex mujer", "novio", "novia", "boda", "me casaba", "me case",
        "beso", "besaba", "besos", "enamorad*", "amor", "romance", "mi crush", "ligaba",
        "ligue", "una cita", "me declaraba", "se me declaraba")),
    Theme("desnudo", "Desnudo en público", (
        "desnud*", "encuerad*", "sin ropa", "en calzones", "en ropa interior", "en pelotas",
        "en cueros", "sin pantalones", "en toalla", "en pijama", "me veian todos")),
    Theme("fortuna", "Dinero, un tesoro", (
        "dinero", "billetes", "monedas", "loteria", "tesoro", "me hacia ric*", "era ric*",
        "millonari*", "me sacaba la loteria", "ganaba dinero", "oro", "joyas", "herencia", "me ganaba",
        "premio", "apuesta", "casino", "lingotes", "una maleta llena")),
    Theme("nada", "Ningún sueño, no me acuerdo", (
        "no me acuerdo", "no recuerdo", "no sueno", "no sueno nada", "nunca sueno",
        "no he sonado", "nada", "ninguno", "no se", "no tuve", "casi no sueno", "se me olvido",
        "se me olvidan", "no me acuerdo de nada", "no sueno mucho", "no suelo sonar")),
    # Said with a cheeky deflection, never read: sexual content, violence, a pregnancy,
    # religion. A transcript no other theme hears also lands here, after the reprompt.
    Theme("otro", "Otro sueño (el sombrero se lo guarda)", (
        "sexo", "sexual", "sexuales", "cogiendo", "cogia", "cogimos", "me acostaba con",
        "me acoste con", "relaciones", "hacer el amor", "haciendo el amor", "porno", "orgia",
        "pistola", "me disparaban", "disparos", "balazos", "me mataban", "me mataron", "mataba",
        "matar", "asesin*", "sangre", "cuchillo", "secuestr*", "ladron", "ladrones", "asalt*",
        "se metian a mi casa", "guerra", "pelea*", "me pegaban", "golpe*", "violen*", "me moria",
        "embaraz*", "bebe", "bebes", "parto", "dios", "la virgen", "virgen", "iglesia",
        "angel", "angeles", "infierno", "misa", "rezaba", "santos", "demonio*", "diablo",
        "satanas", "narco*", "la policia", "la carcel")),
)
DREAM_BY_ID: dict[str, Theme] = {t.id: t for t in DREAM_THEMES}


def dream_theme(text: str) -> str | None:
    """The dream's theme id, or None when no theme's words are heard (the run asks again, and
    stores "otro" after a failed reprompt). "nada" only when no dream was told; chase words beat
    the violence words of "otro" (a killer behind you is still a chase)."""
    ws = tokens(text)
    if not ws:
        return None
    scored = [t for t in DREAM_THEMES if _hits(ws, t)]
    if not scored:
        return None
    ids = {t.id for t in scored}
    if len(ids) > 1 and "nada" in ids:
        scored = [t for t in scored if t.id != "nada"]
    if "perseguido" in ids and "otro" in ids:
        scored = [t for t in scored if t.id != "otro"]
    return _best_theme(ws, tuple(scored))


# ---- the tarot ------------------------------------------------------------------------------
@dataclass(frozen=True)
class Card:
    n: int
    en: str
    es: str
    said: str
    aliases: tuple[str, ...]        # folded: Spanish, English, English by a Spanish ear
    meaning: str


_NUMBER_WORDS = ("cero", "uno", "dos", "tres", "cuatro", "cinco", "seis", "siete", "ocho",
                 "nueve", "diez", "once", "doce", "trece", "catorce", "quince", "dieciseis",
                 "diecisiete", "dieciocho", "diecinueve", "veinte", "veintiuno")


def _card(n, en, es, said, aliases, meaning) -> Card:
    return Card(n, en, es, said, tuple(aliases) + (_NUMBER_WORDS[n],), meaning)


_TAROT: tuple[Card, ...] = (
    _card(0, "The Fool", "El Loco", "El Loco", ("el loco", "loco", "the fool", "fool", "ful", "el bufon"),
          "un comienzo sin miedo"),
    _card(1, "The Magician", "El Mago", "El Mago", ("el mago", "mago", "the magician", "magician", "mayishan"),
          "tienes todo lo que hace falta"),
    _card(2, "The High Priestess", "La Sacerdotisa", "La Sacerdotisa",
          ("la sacerdotisa", "sacerdotisa", "la papisa", "papisa", "high priestess", "priestess", "jai pristes"),
          "un secreto que ya sabes"),
    _card(3, "The Empress", "La Emperatriz", "La Emperatriz", ("la emperatriz", "emperatriz", "the empress", "empress", "empres"),
          "abundancia y cariño"),
    _card(4, "The Emperor", "El Emperador", "El Emperador", ("el emperador", "emperador", "the emperor", "emperor"),
          "orden y mando"),
    _card(5, "The Hierophant", "El Sumo Sacerdote", "El Sumo Sacerdote",
          ("el sumo sacerdote", "sumo sacerdote", "el hierofante", "hierofante", "el papa", "papa", "hierophant", "jairofant"),
          "un consejo de alguien mayor"),
    _card(6, "The Lovers", "Los Enamorados", "Los Enamorados", ("los enamorados", "enamorados", "los amantes", "amantes", "the lovers", "lovers", "lovers"),
          "una elección del corazón"),
    _card(7, "The Chariot", "El Carro", "El Carro", ("el carro", "carro", "la carroza", "carroza", "the chariot", "chariot", "chariot"),
          "avanzas con las riendas en la mano"),
    _card(8, "Strength", "La Fuerza", "La Fuerza", ("la fuerza", "fuerza", "strength", "estrengz", "strengz"),
          "fuerza serena"),
    _card(9, "The Hermit", "El Ermitaño", "El Ermitaño", ("el ermitano", "ermitano", "the hermit", "hermit", "jermit"),
          "un rato a solas con tu lámpara"),
    _card(10, "Wheel of Fortune", "La Rueda de la Fortuna", "La Rueda de la Fortuna",
          ("la rueda de la fortuna", "rueda de la fortuna", "la rueda", "rueda", "wheel of fortune", "the wheel", "wheel", "uil"),
          "la suerte da la vuelta"),
    _card(11, "Justice", "La Justicia", "La Justicia", ("la justicia", "justicia", "justice", "yastis"),
          "cada quien lo suyo"),
    _card(12, "The Hanged Man", "El Colgado", "El Colgado", ("el colgado", "colgado", "el ahorcado", "ahorcado", "hanged man", "the hanged", "jangd man"),
          "ver el mundo al revés"),
    _card(13, "Death", "La Muerte", "La Muerte", ("la muerte", "muerte", "death", "dez", "det"),
          "algo viejo se va"),
    _card(14, "Temperance", "La Templanza", "La Templanza", ("la templanza", "templanza", "temperance", "temperans"),
          "la mezcla justa"),
    _card(15, "The Devil", "El Diablo", "El Diablo", ("el diablo", "diablo", "the devil", "devil", "devol"),
          "una tentación deliciosa"),
    _card(16, "The Tower", "La Torre", "La Torre", ("la torre", "torre", "the tower", "tower", "tauer"),
          "se cae lo que estorbaba"),
    _card(17, "The Star", "La Estrella", "La Estrella", ("la estrella", "estrella", "the star", "star", "estar"),
          "esperanza, una luz que guía"),
    _card(18, "The Moon", "La Luna", "La Luna", ("la luna", "luna", "the moon", "moon", "mun", "de mun", "de mong", "mong", "de mon"),
          "lo que no se ve de día"),
    _card(19, "The Sun", "El Sol", "El Sol", ("el sol", "sol", "the sun", "sun", "san"),
          "alegría a plena luz"),
    _card(20, "Judgement", "El Juicio", "El Juicio", ("el juicio", "juicio", "judgement", "judgment", "yachment"),
          "una llamada que despierta"),
    _card(21, "The World", "El Mundo", "El Mundo", ("el mundo", "mundo", "the world", "world", "uorld"),
          "la vuelta completa"),
)

DECKS: dict[str, dict] = {
    "tarot": {"id": "tarot", "label": "Tarot (arcanos mayores)", "numbers": True, "cards": _TAROT},
}
CARD_RATIO = 0.88


def card_by_n(deck: dict, n: int) -> Card:
    for c in deck["cards"]:
        if c.n == n:
            return c
    raise KeyError(n)


def parse_card(text: str, deck: dict) -> int | None:
    """The card a transcript names, by name (any alias, the longest first), by sound (one
    card alone at least 0.88 close), else by number when the deck has them and exactly one
    number 0..21 is said. Two different cards, or none: None."""
    ws = [w for w in tokens(text) if w not in _CARRIERS]
    if not ws:
        return None
    found: set[int] = set()
    for c in deck["cards"]:
        for alias in sorted(c.aliases, key=len, reverse=True):
            parts = alias.split()
            n = len(parts)
            if any(ws[i:i + n] == parts for i in range(len(ws) - n + 1)):
                found.add(c.n)
                break
    if len(found) == 1:
        return found.pop()
    if found:
        return None
    keys = [phon_key(w) for w in ws]
    scores: list[tuple[float, int]] = []
    for c in deck["cards"]:
        best = 0.0
        for alias in c.aliases:
            target = "".join(phon_key(w) for w in alias.split() if w not in _CARRIERS)
            if len(target) < 3:
                continue
            for i in range(len(keys)):
                for m in range(1, 4):
                    if i + m <= len(keys):
                        gram = "".join(keys[i:i + m])
                        if gram[:1] == target[:1]:
                            best = max(best, SequenceMatcher(None, gram, target).ratio())
        scores.append((best, c.n))
    scores.sort(reverse=True)
    if scores and scores[0][0] >= CARD_RATIO and (len(scores) < 2 or scores[1][0] < CARD_RATIO):
        return scores[0][1]
    if deck.get("numbers"):
        nums = {v for _i, v in numbers_in(ws) if 0 <= v < len(deck["cards"])}
        if len(nums) == 1:
            return nums.pop()
    return None


# ---- the cup --------------------------------------------------------------------------------
CUP_SHAPES: tuple[Theme, ...] = (
    Theme("estrella", "Una estrella", ("estrella*", "estrellita")),
    Theme("corazon", "Un corazón", ("corazon*", "corazoncito")),
    Theme("luna", "Una luna", ("luna", "lunita", "media luna", "lunas")),
    Theme("anillo", "Un anillo", ("anillo*", "aro", "argolla", "circulo", "un circulo", "redondo")),
    Theme("animal", "Un animal", ("animal*", "gato*", "perro*", "pajaro*", "pez", "pescado", "conejo",
                                  "caballo", "mariposa", "bicho*", "arana", "serpiente", "vibora",
                                  "buho", "murcielago", "sapo", "rana")),
    Theme("arbol", "Un árbol", ("arbol*", "rama*", "hoja*", "flor", "flores", "planta", "nopal")),
    Theme("ojo", "Un ojo", ("ojo*", "una cara", "cara", "rostro", "carita")),
    Theme("nube", "Una nube", ("nube*", "mancha*", "humo", "borroso", "una bola", "bolita")),
    Theme("llave", "Una llave", ("llave*", "candado", "puerta", "cerradura")),
    Theme("calabaza", "Una calabaza", ("calabaza*", "calavera*", "craneo", "fantasma", "bruja",
                                       "sombrero", "escoba", "esqueleto", "catrina")),
    Theme("nada", "Nada", ("nada", "no veo nada", "no se", "ninguna", "puro cafe", "solo cafe",
                           "no hay nada", "no veo")),
)


def parse_shape(text: str) -> str | None:
    """The shape a visitor sees in the cup, or None when none of the eleven is heard."""
    ws = tokens(text)
    if not ws:
        return None
    scored = [t for t in CUP_SHAPES if _hits(ws, t)]
    if len(scored) > 1:
        scored = [t for t in scored if t.id != "nada"]
    return _best_theme(ws, tuple(scored)) if scored else None


# ---- the animal (a four-way question for show.match_option) ---------------------------------
ANIMAL_Q: dict = {
    "id": "animal",
    "options": [
        {"id": "gato", "words": ["gato", "gatos", "gato negro", "gatito", "un gato", "michi"]},
        {"id": "buho", "words": ["buho", "buhos", "lechuza", "tecolote", "un buho"]},
        {"id": "murcielago", "words": ["murcielago", "murcielagos", "un murcielago", "murcielaguito"]},
        {"id": "sapo", "words": ["sapo", "sapos", "rana", "ranas", "un sapo", "ranita"]},
    ],
}
ANIMAL_SAID: dict[str, str] = {"gato": "el gato negro", "buho": "el búho",
                               "murcielago": "el murciélago", "sapo": "el sapo"}


# ---- the moon -------------------------------------------------------------------------------
MOON_PHASES: tuple[str, ...] = ("nueva", "creciente", "cuarto_creciente", "gibosa_creciente",
                                "llena", "gibosa_menguante", "cuarto_menguante", "menguante")
MOON_SAID: dict[str, str] = {p: p.replace("_", " ") for p in MOON_PHASES}
_MOON_REF = datetime(2000, 1, 6, 18, 14, tzinfo=timezone.utc)
SYNODIC_DAYS = 29.530588853


def moon_phase(when: datetime) -> str:
    """The phase id on `when` (a naive datetime counts as UTC): the mean age since the
    reference new moon, in eighths of the synodic month, each phase centred on its moment."""
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    age = ((when - _MOON_REF).total_seconds() / 86400.0) % SYNODIC_DAYS
    return MOON_PHASES[round(age / SYNODIC_DAYS * 8) % 8]


def moon_tonight(now: datetime | None = None) -> str | None:
    """Tonight's phase, or None when the clock is not sane (a board without network time
    boots in 1970 or so)."""
    now = now or datetime.now(timezone.utc)
    return moon_phase(now) if now.year >= 2026 else None


# ---- the rest of the ending -----------------------------------------------------------------
MAGIC_WORDS: tuple[str, ...] = ("Zumbalí", "Catrinela", "Calaquimba", "Murcielumbra", "Velazumba",
                                "Cempacuá", "Brujicanto", "Tenebrumba", "Sombrambrú",
                                "Luzmalinda", "Ofrendilla", "Espantillo")

PLACES = ("casa", "fiesta", "universidad", "otro")
PLACE_SAID: dict[str, str] = {"casa": "en casa, con la familia", "fiesta": "en una fiesta",
                              "universidad": "en la universidad", "otro": "por ahí"}


@dataclass
class Fortune:
    """What the act has heard so far (ids; the said forms are looked up when told)."""
    nombre: str = ""
    lugar: str = ""                 # a place id, or the operator's free text
    casa: str | None = None         # the house act's verdict, when it just ran
    fecha: tuple[int, int] | None = None
    signo: str | None = None
    numero: int | None = None
    sueno: str | None = None
    sueno_txt: str = ""
    carta: int | None = None
    taza: str | None = None
    animal: str | None = None
    luna: str | None = None
    palabra: str = ""


def _bare(said: str) -> str:
    return re.sub(r"^(el|la|los|las) ", "", said)


def reading_tag(f: Fortune, deck: dict | None) -> str:
    """The one line the model gets for its reading: every datum heard, in its said form,
    never the year. Missing keys are absent."""
    parts = []
    if f.nombre:
        parts.append(f"nombre={f.nombre}")
    if f.lugar:
        parts.append(f"lugar={f.lugar}")
    if f.signo in SIGN_BY_ID:
        s = SIGN_BY_ID[f.signo]
        parts.append(f"signo={s.said}")
        parts.append(f"elemento={s.element}")
    if f.numero is not None:
        parts.append(f"número={f.numero}")
    if f.sueno:
        words = f.sueno_txt.replace('"', "'").strip()
        parts.append(f'sueño={f.sueno} ("{words}")' if words else f"sueño={f.sueno}")
    if f.carta is not None and deck:
        try:
            parts.append(f"carta={card_by_n(deck, f.carta).said}")
        except KeyError:
            pass
    if f.taza:
        parts.append(f"taza={f.taza}")
    if f.animal in ANIMAL_SAID:
        parts.append(f"animal={_bare(ANIMAL_SAID[f.animal])}")
    if f.luna in MOON_SAID:
        parts.append(f"luna={MOON_SAID[f.luna]}")
    if f.palabra:
        parts.append(f"palabra={f.palabra}")
    if f.casa:
        parts.append(f"casa={f.casa}")
    return "[ADIVINACIÓN: " + "; ".join(parts) + "] Haz la lectura."


# ---- the register's filter -------------------------------------------------------------------
# Folded words and phrases the reading must not carry (the adult rules: no illness, accidents,
# real misfortune, explicit sex, religion as doctrine, prizes, the age). La muerte, las
# calaveras and el diablo are the season's guests and stay; "muerto" as a blunt word goes,
# except in the season's own names (EXEMPT).
BANNED: tuple[str, ...] = (
    "enfermedad", "enfermedades", "enfermo", "enferma", "enfermos", "enfermas", "hospital",
    "hospitales", "tumor", "cirugia", "quimio", "tiene cancer", "tienes cancer", "tener cancer",
    "con cancer", "un cancer", "el cancer", "del cancer", "contra el cancer", "cancer de mama",
    "cancer de pulmon", "cancer de piel", "cancer terminal", "murio de cancer",
    "accidente", "accidentes", "funeral", "velorio", "suicidio", "suicida", "asesinato",
    "asesino", "asesina", "violacion", "violar", "muerto", "muerta", "muertos", "muertas",
    "morir", "moriras", "morira", "mueres", "muere", "te mata", "matar",
    "loteria", "premio", "premios", "melate", "rifa", "te sacas",
    "dios", "iglesia", "rezar", "reza", "rezo", "misa", "biblia", "cristo", "jesus", "virgen",
    "sexo", "sexual", "sexuales", "coger", "cogiendo", "verga", "pene", "vagina", "tetas",
    "chichis", "orgasmo", "porno", "follar", "culo", "puta", "puto", "pendejo", "pendeja",
    "chingar", "chingada", "chinga", "pinche",
    "edad", "anos",                 # folded: "años"
)
EXEMPT: tuple[str, ...] = ("pan de muerto", "dia de muertos", "noche de muertos",
                           "dia de los muertos", "fieles difuntos")
_YEAR = re.compile(r"\b(1[89]\d\d|20\d\d)\b")
_CLOCK = re.compile(r"\b\d{1,2}:\d{2}\b|\ba las? (\d{1,2}|una|dos|tres|cuatro|cinco|seis|siete|"
                    r"ocho|nueve|diez|once|doce)\b|\b(\d{1,2}|una|dos|tres|cuatro|cinco|seis|"
                    r"siete|ocho|nueve|diez|once|doce) en punto\b")
MAX_READING_SENTENCES = 6
MAX_READING_WORDS = 90


def banned_in(text: str) -> list[str]:
    """The banned words, years and clock times in `text`, folded, in order; [] when clean."""
    s = " " + " ".join(re.sub(r"[^a-z0-9ñ:]", " ", _fold(text or "")).split()) + " "
    for phrase in EXEMPT:
        s = s.replace(f" {phrase} ", "  ")
    found = []
    for word in BANNED:
        if f" {word} " in s:
            found.append(word)
    found += _YEAR.findall(s)
    found += [m.group(0) for m in _CLOCK.finditer(s)]
    return found


def clean_reading(reply: str) -> str | None:
    """The model's reading fit to be said: any bracket tag removed, whitespace collapsed; None
    when it carries a banned word, more than 6 sentences or more than 90 words."""
    text = strip_notes(reply or "")
    if not text or banned_in(text):
        return None
    sentences = len(re.findall(r"[.!?…]+(?:\s|$)", text)) or 1
    if sentences > MAX_READING_SENTENCES or len(text.split()) > MAX_READING_WORDS:
        return None
    return text
