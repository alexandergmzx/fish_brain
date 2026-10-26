"""The scripted visit's deterministic core: hearing an option, deciding the house, picking lines.

Pure except for `ShowState`, which persists the show's seed, the visit counter and the
deal-before-repeat bags (atomic writes: the power is always pulled). The same answers, chips
and state always give the same house and the same lines. Every choice comes from sha256,
never from Python's hash(), random.choice or shuffle, which are not stable across runs.

    match_option(q, text)    -> Heard   which option of question q a transcript names
    houses_in(text)          -> (preference, vetoes)   "quiero Ravenclaw", "no Slytherin"
    decide(...)              -> (house letter, how)    the ladder in decide()'s docstring
    ShowState.pick(slot, names) / .house_bag(tied)     variety without randomness
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path

from . import show_bank
from .visit import _HOUSE_PREFIXES, _fold

HOUSE_LETTERS = {name: letter for letter, name in show_bank.HOUSES.items()}

# Words that carry no answer ("yo digo el mapa"): dropped before matching.
CARRIERS = frozenset("el la los las un una unos unas mi mis tu yo digo elijo escojo escogo "
                     "prefiero pues este eh mm mmm ah o y a de del que creo".split())
# A bare yes or no answers no either/or question (young children say yes to anything).
YES_NO = frozenset("si no simon nel sip nop claro sale orale ok okey".split())
# "I don't know" and friends: an answer with no evidence, never asked again.
NOT_SURE = ("no se", "nose", "ninguno", "ninguna", "cualquiera", "me da igual", "los dos",
            "las dos", "ambos", "ambas", "todos", "todas")
NEGATIONS = frozenset("no ni nunca menos tampoco".split())
ORDINALS = {"primero": 0, "primera": 0, "uno": 0, "segundo": 1, "segunda": 1, "dos": 1,
            "tercero": 2, "tercera": 2, "tres": 2, "cuarto": 3, "cuarta": 3, "cuatro": 3}
LAST = frozenset({"ultimo", "ultima"})

ACCEPT_RATIO = 0.88    # a fuzzy (not exact) match must be at least this close...
ACCEPT_MARGIN = 0.15   # ...and this much ahead of the next option,
LOOSE_RATIO = 0.80     # or a little less close but far ahead of every other option
LOOSE_MARGIN = 0.25
MAX_WORDS = 8          # a long sentence is not an answer to an either/or question


def words(text: str) -> list[str]:
    return re.sub(r"[^a-zñ ]", " ", _fold(text or "")).split()


def phon_key(word: str) -> str:
    """A Spanish sound key, so a transcript's spelling slip still matches ("bolcan", "litro"
    -> close to "volcan", "libro"). Rules written for this project."""
    w = _fold(word)
    w = w.replace("ch", "\x01").replace("h", "").replace("\x01", "ch")
    w = re.sub(r"qu([ei])", r"k\1", w)
    w = re.sub(r"gu([ei])", r"g\1", w)
    w = re.sub(r"g([ei])", r"j\1", w)
    w = re.sub(r"c([ei])", r"s\1", w)
    w = w.replace("ll", "y").replace("v", "b").replace("z", "s").replace("ñ", "ny")
    w = w.replace("c", "k").replace("rr", "r")
    w = re.sub(r"y$", "i", w)
    return re.sub(r"(.)\1+", r"\1", w)


@dataclass
class Heard:
    option: str | None      # the option id, or None
    kind: str               # "option", "not_sure", "none"
    score: float = 0.0
    how: str = ""           # "exact", "fuzzy", "ordinal", "operator"


def _content(ws: list[str]) -> list[str]:
    return [w for w in ws if w not in CARRIERS]


def match_option(q: dict, text: str) -> Heard:
    """Which option of question `q` a transcript names, conservatively: a wrong callback breaks
    the illusion more than a generic line, so anything unclear is "none"."""
    ws = words(text)
    if not ws:
        return Heard(None, "none")
    joined = " ".join(ws)
    if any(re.search(rf"\b{p}\b", joined) for p in NOT_SURE):
        return Heard(None, "not_sure")
    content = _content(ws)
    if not content or all(w in YES_NO for w in content) or len(ws) > MAX_WORDS:
        return Heard(None, "none")
    options = q["options"]
    for w in content:                                  # "el primero", "la última"
        if w in LAST:
            return Heard(options[-1]["id"], "option", 1.0, "ordinal")
        if w in ORDINALS and ORDINALS[w] < len(options) and len(content) <= 2:
            return Heard(options[ORDINALS[w]]["id"], "option", 1.0, "ordinal")
    keys = [phon_key(w) for w in content]
    scores = []
    for o in options:
        best = 0.0
        for syn in o["words"]:
            sk = [phon_key(w) for w in _content(syn.split())] or [phon_key(syn)]
            n = len(sk)
            for i in range(len(keys) - n + 1):
                if keys[i:i + n] == sk:
                    best = 1.0
                    break
            if best == 1.0:
                break
            # Fuzzy: the synonym against 1 to 3 transcript words run together, so a word split
            # in two ("tro feo") or a one-letter slip ("litro") still comes close.
            # The first sound must agree: "estas" is not "fiesta", "litro" can be "libro".
            target = "".join(sk)
            for i in range(len(keys)):
                for m in range(1, 4):
                    if i + m <= len(keys):
                        gram = "".join(keys[i:i + m])
                        if gram[:1] == target[:1]:
                            best = max(best, SequenceMatcher(None, gram, target).ratio())
        scores.append((best, o["id"]))
    scores.sort(reverse=True)
    top, second = scores[0], (scores[1] if len(scores) > 1 else (0.0, None))
    if top[0] == 1.0 and second[0] < 1.0:
        return Heard(top[1], "option", 1.0, "exact")
    gap = top[0] - second[0]
    if (top[0] >= ACCEPT_RATIO and gap >= ACCEPT_MARGIN) or (
            top[0] >= LOOSE_RATIO and gap >= LOOSE_MARGIN):
        return Heard(top[1], "option", round(top[0], 3), "fuzzy")
    return Heard(None, "none", round(top[0], 3))


def _house_word(word: str) -> str | None:
    for prefix, house in _HOUSE_PREFIXES:
        if word.startswith(prefix):
            return HOUSE_LETTERS[house]
    return None


def houses_in(text: str) -> tuple[str | None, set[str]]:
    """(the last house asked for, the houses ruled out) in a transcript. A house with a
    negation in the two words before it is ruled out ("no Slytherin", "ni Gryffindor"),
    except the "no" of "no sé"."""
    ws = words(text)
    pref, vetoes = None, set()
    for i, w in enumerate(ws):
        h = _house_word(w)
        if h is None:
            continue
        before = ws[max(0, i - 2):i]
        negated = any(b in NEGATIONS and not (b == "no" and j + 1 < len(before)
                                               and before[j + 1] == "se")
                      for j, b in enumerate(before))
        if negated:
            vetoes.add(h)
            if pref == h:
                pref = None
        else:
            pref = h
    return pref, vetoes


def scores_for(answers: dict[str, str | None], cues: dict[str, str]) -> dict[str, int]:
    s = {h: 0 for h in show_bank.HOUSES}
    for qid, opt in answers.items():
        if not opt:
            continue
        for o in show_bank.question(qid)["options"]:
            if o["id"] == opt:
                for h, v in o["scores"].items():
                    s[h] += v
    for (key, value), add in show_bank.CHIP_WEIGHTS.items():
        if cues.get(key) == value:
            for h, v in add.items():
                s[h] += v
    return s


def decide(answers: dict[str, str | None], cues: dict[str, str], *, force: str | None = None,
           preference: str | None = None, vetoes: set[str] | frozenset = frozenset(),
           bag=None) -> tuple[str, str]:
    """The house letter and how it was decided. The first rule that settles it wins:
    1 the operator's "Forzar casa"   2 the visitor's stated preference (not vetoed)
    3 answers and chips, without the vetoed houses (all vetoed: vetoes ignored)
    4 a tie: the latest four-way answer whose house is tied   5 the house bag (`bag(tied)`)."""
    if force in show_bank.HOUSES:
        return force, "operator"
    if preference in show_bank.HOUSES and preference not in vetoes:
        return preference, "preference"
    s = scores_for(answers, cues)
    candidates = [h for h in show_bank.HOUSES if h not in vetoes] or list(show_bank.HOUSES)
    top = max(s[h] for h in candidates)
    tied = [h for h in candidates if s[h] == top]
    if len(tied) == 1:
        return tied[0], "answers" if any(answers.values()) else "chips"
    for qid in reversed(list(answers)):
        opt = answers[qid]
        if not opt:
            continue
        o = next(o for o in show_bank.question(qid)["options"] if o["id"] == opt)
        if len(o["scores"]) == 1:
            (h,) = o["scores"]
            if h in tied:
                return h, "tie: trait"
    if bag is not None:
        return bag(tied), "tie: bag" if any(answers.values()) else "bag"
    return sorted(tied)[0], "tie: order"


def _int(*parts) -> int:
    return int(hashlib.sha256("|".join(str(p) for p in parts).encode()).hexdigest()[:16], 16)


def perm(items: list, *key) -> list:
    """A permutation of `items` fixed by `key` (Fisher-Yates driven by sha256)."""
    out = list(items)
    for i in range(len(out) - 1, 0, -1):
        j = _int(*key, i) % (i + 1)
        out[i], out[j] = out[j], out[i]
    return out


class ShowState:
    """The show's memory across visits and reboots: {seed, visit, bags: {slot: {cycle, dealt}}}.
    A file that cannot be read starts a fresh state (and says so in `recovered`)."""

    def __init__(self, path: str | Path | None, seed: str | None = None):
        self.path = Path(path).expanduser() if path else None
        self.recovered = False
        data = None
        if self.path is not None and self.path.exists():
            try:
                data = json.loads(self.path.read_text())
                if not isinstance(data, dict) or "seed" not in data:
                    raise ValueError("no seed")
            except (OSError, ValueError):
                data, self.recovered = None, True
        if data is None:
            data = {"seed": seed or os.urandom(8).hex(), "visit": 0, "bags": {}}
        if seed:
            data["seed"] = seed
        self.data = data

    @property
    def seed(self) -> str:
        return self.data["seed"]

    @property
    def visit(self) -> int:
        return int(self.data.get("visit", 0))

    def next_visit(self) -> int:
        self.data["visit"] = self.visit + 1
        self.save()
        return self.visit

    def pick(self, slot: str, names: list[str]) -> str | None:
        """Deal-before-repeat: every name once per cycle, in an order fixed by the seed; a new
        cycle never starts with the last cycle's last name."""
        names = sorted(names)
        if not names:
            return None
        bag = self.data["bags"].setdefault(slot, {"cycle": 0, "dealt": []})
        dealt = [n for n in bag["dealt"] if n in names]
        if len(dealt) >= len(names):
            last = dealt[-1] if dealt else None
            bag["cycle"] += 1
            dealt = []
            order = perm(names, self.seed, slot, bag["cycle"])
            if len(order) > 1 and order[0] == last:
                order = order[1:] + order[:1]
        else:
            order = perm(names, self.seed, slot, bag["cycle"])
        name = next(n for n in order if n not in dealt)
        bag["dealt"] = dealt + [name]
        self.save()
        return name

    def house_bag(self, tied: list[str]) -> str:
        """The first tied house still in this cycle's order of the four houses."""
        bag = self.data["bags"].setdefault("house", {"cycle": 0, "dealt": []})
        for _ in range(2):
            order = perm(sorted(show_bank.HOUSES), self.seed, "house", bag["cycle"])
            left = [h for h in order if h not in bag["dealt"]]
            pick = next((h for h in left if h in tied), None)
            if pick is not None:
                bag["dealt"].append(pick)
                if len(bag["dealt"]) >= len(order):
                    bag["cycle"] += 1
                    bag["dealt"] = []
                self.save()
                return pick
            bag["cycle"] += 1                  # nothing tied is left in this cycle
            bag["dealt"] = []
        return sorted(tied)[0]

    def save(self) -> None:
        if self.path is None:
            return
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp = tempfile.mkstemp(dir=self.path.parent, prefix=".show-", suffix=".json")
            with os.fdopen(fd, "w") as f:
                json.dump(self.data, f)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, self.path)
        except OSError as e:
            print(f"[show] state not saved: {e}", flush=True)


def question_set(visit: int) -> str:
    sets = sorted(show_bank.SETS)
    return sets[(visit - 1) % len(sets)]
