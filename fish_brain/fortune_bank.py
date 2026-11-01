"""The fortune act's data (fortune.py, fortune_run.py): the questions, every line, the rules.

Every line is a canned phrase named `fortune_*` (never `show_*`: the fortune lives with the
show off), rendered ahead while the voice is clean and played from the cache, never rendered
at show time. One clip per datum the parsers can return: a reaction per sign, dream theme,
wish (a pool for any other wish), card and cup shape; a line per lucky number and moon phase;
pools for the intro and the closing by place (and by house, when the house act just ran), the
visions after the dream, the bridges, the suspense and the twelve magic words. The act says a
reaction the moment its datum lands, so a visitor who answers nothing still hears intro,
bridges, moon, word and closing. In model mode (ADR 0026) an answer gets a short beat instead
and a card its name beat, the reactions are held for a fallback, and the model reads the
meaning once; the hat's own draw is announced by a shuffle line.

All texts are drafts for the owner to edit (2026-10-27), in the adult register of
docs/adr/0019: antiguo, cálido, teatral, now spooky and cheeky; the season (calaveras, la
ofrenda, los que ya cruzaron, velas, cempasúchil, pan de muerto, gatos negros); La Muerte and
El Diablo by name; a drink or a song only in the `fiesta` pools; gender-neutral; no clock
time, no venue name, no word list (ADR 0025); at most two sentences and about
35 words; prompts end in a question; the date prompt says the year is never asked.
FORTUNE_RULES is the model's brief for its one reading call, in the shape of the visit's; the
structure of ADR 0026, the old sorcerer's oracle voice over it since ADR 0027, no mockery since ADR 0032, as are
the clips said only in model mode (the beats, the shuffle, the suspense lines). GANCHOS, RITOS and FORMAS are not clips: the act deals one
of each into the model's tag.
"""
from __future__ import annotations

from . import fortune, texts


def _by_number(decks: dict) -> dict[str, dict[int, str]]:
    return {deck: {int(k): v for k, v in cards.items()} for deck, cards in decks.items()}


QIDS = ("fecha", "sueno", "deseo", "carta", "taza")

# qid (the card's per deck) -> prompt and the narrower reprompt.
QUESTIONS: dict[str, dict[str, str]] = texts.lines()["questions"]

# The sign's line: said when the date lands, with the element.
SIGN_LINES: dict[str, str] = texts.lines()["signs"]

# The dream's omen: a good reading of each theme (docs/results/2026-10-27-dream-themes.md).
DREAM_LINES: dict[str, str] = texts.lines()["dreams"]

# The card's line, by number in the deck.
CARD_LINES: dict[str, dict[int, str]] = _by_number(texts.lines()["cards"])

# The shape in the cup.
SHAPE_LINES: dict[str, str] = texts.lines()["shapes"]

# What the visitor wishes for (fortune.WISHES), asked by the hat, never of La Muerte (his word,
# 2026-10-31); any other wish takes the re_deseo_otro pool.
WISH_LINES: dict[str, str] = texts.lines()["wishes"]

# The card's name beat (model mode): the name and a reaction, never the meaning, which the
# model reads once. Said for a card named by the visitor and for one the hat drew.
CARD_NAME_LINES: dict[str, dict[int, str]] = _by_number(texts.lines()["card_names"])
REVERSED_LINE = texts.lines()["reversed"]

# The cards the hat draws itself: every card once, and the five dark ones twice, dealt before
# repeat (a design choice, not measured: the oracle's dark cards come more often). A "_bis" is the
# second copy of the same card.
HAT_DRAW_EXTRA: dict[str, tuple[int, ...]] = {"tarot": (13, 15, 16, 18, 6)}
REVERSED_BAG = ("derecha_1", "derecha_2", "cabeza")     # one hat draw in three, in model mode

# The model's seeds (not clips): one of each per reading, dealt before repeat by the act.
# GANCHOS are high-probability specifics (Rowland's fuzzy facts and stock specifics, made
# Mexican): the one invented detail the model may say, as a vision with an out.
GANCHOS: tuple[str, ...] = tuple(texts.lines()["ganchos"])

# A small rite with its time, dealt before repeat as rito= (ADR 0027): a list of rites in the
# rules was copied, "una vela en la ventana" and "antes del domingo" in 11 of 16 readings
# (2026-10-29). Western sorcery, plus the limpia and the mal de ojo (his word).
RITOS: tuple[str, ...] = tuple(texts.lines()["ritos"])

# How the reading opens: (what it needs in the tag, the word sent as forma=). One word, explained
# once in FORTUNE_RULES: a sentence here was read aloud as the reading's first words (2026-10-29).
# "deseo" is met by a wish or a dealt tema, so it is always there.
FORMAS: tuple[tuple[str | None, str], ...] = (
    ("signo", "signo"),
    ("sueno", "sueño"),
    ("carta", "carta"),
    (None, "aviso"),
    ("deseo", "deseo"),
    (None, "visión"),
)

# The lucky number, 1..9 (fortune.lucky_number).
NUMBER_LINES: dict[int, str] = {int(k): v for k, v in texts.lines()["numbers"].items()}

# Tonight's moon (fortune.MOON_PHASES).
MOON_LINES: dict[str, str] = texts.lines()["moons"]

# Pools: slot -> lines. The intro and the closing take "<slot>_<place>" (fortune.PLACES) or,
# right after the house act, "intro_<house letter>". The magic pool says one word per line,
# in the order of fortune.MAGIC_WORDS.
POOLS: dict[str, list[str]] = texts.lines()["pools"]


def _deck_id(deck) -> str:
    if isinstance(deck, dict):
        return deck.get("id", "tarot")
    return deck or "tarot"


def _qkey(qid: str, deck=None) -> str:
    return f"carta_{_deck_id(deck)}" if qid == "carta" else qid


def prompt_name(qid: str, deck=None) -> str:
    return f"fortune_q_{_qkey(qid, deck)}"


def reprompt_name(qid: str, deck=None) -> str:
    return f"fortune_rq_{_qkey(qid, deck)}"


def reaction_name(qid: str, value, deck=None) -> str:
    """The clip said when a datum lands: the sign for the date, the theme for the dream, the
    wish, the card's number in its deck, the shape."""
    return f"fortune_re_{_qkey(qid, deck)}_{value}"


def card_name_name(n: int, deck=None) -> str:
    """The card's name beat (model mode)."""
    return f"fortune_nombre_{_deck_id(deck)}_{n}"


REVERSED_NAME = "fortune_reves"


def num_name(n: int) -> str:
    return f"fortune_num_{n}"


def moon_name(phase: str) -> str:
    return f"fortune_luna_{phase}"


def pool_names(slot: str) -> list[str]:
    return [f"fortune_{slot}_{i}" for i in range(1, len(POOLS[slot]) + 1)]


def question_text(qid: str, deck=None) -> str:
    return QUESTIONS[_qkey(qid, deck)]["prompt"]


MAGIC_WORD_OF: dict[str, str] = dict(zip(pool_names("magic"), fortune.MAGIC_WORDS))


def _phrases() -> dict[str, str]:
    out: dict[str, str] = {}
    for key, q in QUESTIONS.items():
        out[f"fortune_q_{key}"] = q["prompt"]
        out[f"fortune_rq_{key}"] = q["reprompt"]
    for sign, text in SIGN_LINES.items():
        out[reaction_name("fecha", sign)] = text
    for theme, text in DREAM_LINES.items():
        out[reaction_name("sueno", theme)] = text
    for deck, cards in CARD_LINES.items():
        for n, text in cards.items():
            out[reaction_name("carta", n, deck)] = text
    for shape, text in SHAPE_LINES.items():
        out[reaction_name("taza", shape)] = text
    for wish, text in WISH_LINES.items():
        out[reaction_name("deseo", wish)] = text
    for deck, cards in CARD_NAME_LINES.items():
        for n, text in cards.items():
            out[card_name_name(n, deck)] = text
    out[REVERSED_NAME] = REVERSED_LINE
    for n, text in NUMBER_LINES.items():
        out[num_name(n)] = text
    for phase, text in MOON_LINES.items():
        out[moon_name(phase)] = text
    for slot, lines in POOLS.items():
        for name, text in zip(pool_names(slot), lines):
            out[name] = text
    return out


def _check_tables() -> None:
    """Every line the act can ask for is in lines.toml: a deleted one stops the start-up, naming it."""
    need = {"questions": {"fecha", "sueno", "deseo", "taza", "carta_tarot"}, "signs": set(fortune.SIGN_BY_ID),
            "dreams": set(fortune.DREAM_BY_ID), "wishes": set(fortune.WISH_IDS),
            "shapes": {t.id for t in fortune.CUP_SHAPES}, "moons": set(fortune.MOON_PHASES),
            "numbers": {str(n) for n in range(1, 10)}}
    cards = {str(c.n) for c in fortune.DECKS["tarot"]["cards"]}
    tables = texts.lines()
    missing = [f"{k}.{x}" for k, want in need.items() for x in sorted(want - set(tables[k]))]
    missing += [f"{k}.tarot.{x}" for k in ("cards", "card_names") for x in sorted(cards - set(tables[k].get("tarot", {})))]
    pools = {"beat", "barajo", "sin_carta", "bridge", "suspense", "suspense_mas", "magic", "vision",
             "re_deseo_otro", "intro_G", "intro_H", "intro_R", "intro_S"}
    pools |= {f"{slot}_{place}" for slot in ("intro", "cierre") for place in fortune.PLACES}
    missing += [f"pools.{x}" for x in sorted(pools - set(POOLS))]
    if len(POOLS.get("magic", [])) != len(fortune.MAGIC_WORDS):
        missing.append("pools.magic (one line per magic word)")
    if missing:
        raise ValueError("lines.toml: missing " + ", ".join(missing))


_check_tables()
FORTUNE_PHRASES: dict[str, str] = _phrases()


# The model's brief for its one reading call (fortune_run.py: a fresh history, the data and the
# seeds in the tag, the reply through fortune.clean_reading). One story about the wish since ADR
# 0026, no mockery since ADR 0032, a task with a day. The bans below are on stock phrases, not on
# topics (ADR 0025).
FORTUNE_RULES = texts.rules("reading.md")
