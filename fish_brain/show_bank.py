"""The scripted visit's data (show.py, show_run.py): questions, weights and every line.

The "cross" (docs/adr/0015): Q1 and Q2 are either/or and cross into the four houses, so the 16
answer paths give 4 per house with no ties; Q3 offers four traits and can move a visitor to a
neighbouring house, never to the opposite one (3 < 4, 5 > 4 in points). Weights are integer
units of 1/8 point: an axis answer gives 16 to each of two houses, a trait 24 to one. The
operator's colour chip gives 4 (half a point): chips can only break a tie.

Options are short nouns that sound different within a question, each with the words a visitor
may use for it (folded: no accents, lower case). Every line is a canned phrase named `show_*`,
rendered ahead while the voice is clean and played from the cache, never rendered at show time.
The words live in prompts/house.toml, his to edit; here the houses and the weights. Nothing there
is taken from the books, the films or the official quiz.
"""
from __future__ import annotations

from . import texts

HOUSES = {"G": "Gryffindor", "H": "Hufflepuff", "R": "Ravenclaw", "S": "Slytherin"}

AXIS = 16          # an either/or answer, to each of its two houses
TRAIT = 24         # a four-way answer, to its one house
CHIP = 4           # the operator's colour chip

# The cross, by position: Q1 first option heart and people (G, H), second head and plans (R, S);
# Q2 first out in front (G, S), second inside and steady (H, R); Q3 one house each.
SHAPE = (({"G": AXIS, "H": AXIS}, {"R": AXIS, "S": AXIS}),
         ({"G": AXIS, "S": AXIS}, {"H": AXIS, "R": AXIS}),
         ({"G": TRAIT}, {"R": TRAIT}, {"H": TRAIT}, {"S": TRAIT}))
SET_IDS = ("A", "B", "C")


def _sets() -> dict[str, list[dict]]:
    """The words from the file, the scores from SHAPE (texts.check_house saw the sizes)."""
    out: dict[str, list[dict]] = {}
    for s in SET_IDS:
        out[s] = [{**(q := texts.house()["questions"][f"{s}{i}"]), "id": f"{s}{i}",
                   "options": [{**o, "scores": dict(score)} for o, score in zip(q["options"], SHAPE[i - 1])]}
                  for i in (1, 2, 3)]
    return out


SETS: dict[str, list[dict]] = _sets()

CHIP_WEIGHTS: dict[tuple[str, str], dict[str, int]] = {
    ("color", "rojo"): {"G": CHIP},
    ("color", "amarillo"): {"H": CHIP},
    ("color", "azul"): {"R": CHIP},
    ("color", "verde"): {"S": CHIP},
}

# Pools: slot -> lines. A slot with a house takes "<slot>_<house letter>".
POOLS: dict[str, list[str]] = texts.house()["pools"]
LABELS = {o["id"]: o["label"] for qs in SETS.values() for q in qs for o in q["options"] if o.get("label")}


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


def _check_tables() -> None:
    """Every slot show_run picks must have a line: a None would reach the speaker."""
    slots = ["greet", "nose", "bridge", "suspense", "tie", "season", "farewell"]
    slots += [f"{k}_{h}" for k in ("pref", "reason", "house", "future") for h in HOUSES]
    missing = [s for s in slots if not POOLS.get(s)]
    if missing:
        raise ValueError("house.toml: missing pools." + ", pools.".join(missing))


_check_tables()
SHOW_PHRASES: dict[str, str] = _phrases()
