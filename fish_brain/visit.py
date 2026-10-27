"""The hat's visit (cold reading): four hat turns per visitor, the stage told to the model
as a tag, the operator's cues added once, and the house line taken out before the voice.

A visit opens with a greeting (canned, or the badge's "¿Tú eres X?", or the model's first
answer), then two readings that end in a question, then the verdict: the house with a reason
from the visitor's own words and a short line about the rest of the fair, closed by
"CASA: <house>". The turn loop (conversation.py) and the rehearsal (tools/hat_rehearse.py)
run the same steps:

    needs_new(at) -> start(first, now)       a new visitor (the model's history is reset)
    prepare(text, lugar) -> (tagged, snap)   "[ETAPA n/4] [PISTAS: lugar=…; …] " + what was said
    split_reply(reply) -> (spoken, house)    before anything is said or shown
    delivered(house, snapshot, now)          only once the reply was spoken (or drafted)

The cues belong to the visitor being served when they are set, and every turn carries all of
them (the latest win). Turns never use them up: the act's close files them (the page's
"used:" line) and clears the row up to the cut, the moment the verdict was asked for (a
fortune: the end of its last line), so chips tapped for the next visitor during the verdict
survive. A new visitor keeps only the cues stamped after that cut; a restart for the same
visitor (`start(keep_cues=True)`: the script taking over, the model rebuilt) keeps them all.

A stage counts only when it was delivered, so the counter always equals the hat's answers in
the model's history (the loop remembers an answer after it was spoken, never before).

Threads: the turn loop alone reads and writes the stage, the name and the house. The page's
HTTP threads touch only the cues and the "new visitor" request, under the lock.
"""
from __future__ import annotations

import re
import threading
import time
import unicodedata
from dataclasses import dataclass

HOUSES = ("Gryffindor", "Hufflepuff", "Ravenclaw", "Slytherin")
# How the model (or the speech-to-text) may spell a house: matched on the start of the word,
# accents and case ignored.
_HOUSE_PREFIXES = (("gryf", "Gryffindor"), ("grif", "Gryffindor"), ("huf", "Hufflepuff"),
                   ("jaf", "Hufflepuff"), ("rav", "Ravenclaw"), ("reiv", "Ravenclaw"),
                   ("slyt", "Slytherin"), ("slit", "Slytherin"), ("sliz", "Slytherin"),
                   ("slid", "Slytherin"), ("eslit", "Slytherin"), ("eslid", "Slytherin"),
                   ("esliz", "Slytherin"))

# The operator's cues (the sheet's chips): key -> allowed values. Keys are ASCII for the page;
# the tag uses the labels.
CUE_CHOICES: dict[str, tuple[str, ...]] = {
    "edad": ("joven", "adulto", "mayor"),
    "compania": ("solo", "pareja", "amigos", "familia"),
    "color": ("rojo", "azul", "verde", "amarillo", "negro", "blanco", "rosa", "morado"),
    "impresion": ("tímido", "sonriente", "curioso", "escéptico", "fiestero"),
    "disfraz": ("tenebroso", "chistoso", "elegante"),
}
CUE_TEXT = ("lleva", "nota")          # short free text: something worn or carried, a note
CUE_TEXT_MAX = 60
CUE_ORDER = (*CUE_CHOICES, *CUE_TEXT)
CUE_LABEL = {"edad": "edad", "compania": "compañía", "color": "color",
             "impresion": "impresión", "disfraz": "disfraz", "lleva": "lleva", "nota": "nota"}
# How a value is said in the tag, when not as itself: the impression as a noun, so the hat
# never echoes a gendered adjective about the visitor.
CUE_SAID: dict[str, dict[str, str]] = {
    "impresion": {"tímido": "timidez", "sonriente": "sonrisa", "curioso": "curiosidad",
                  "escéptico": "escepticismo", "fiestero": "ganas de fiesta"},
}
PLACE_IDS = ("casa", "fiesta", "universidad")   # said as themselves; "otro" by its text

_TAG = re.compile(r"\[\s*(?:ETAPA|PISTAS|FIN|FUTURO|ADIVINACI[ÓO]N)\b[^\]]*\]", re.IGNORECASE)
_LINE_LEAD = re.compile(r"^[\s>*_#•·-]+")
_CASA_LINE = re.compile(r"^casa\s*:\s*(.*)$", re.IGNORECASE)
# The tag run into the end of the text ("… feria. CASA: Ravenclaw"): only in capitals and
# after a sentence end, so "Tu casa: Ravenclaw, sin duda" stays what it is.
_CASA_TRAIL = re.compile(r"(^|[.!?…»\"')]\s*)\**\s*CASA\s*:\s*\**\s*([A-Za-zÁÉÍÓÚáéíóúñÑ]+)"
                         r"\s*\**\s*[.!]?\s*$")
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")
_TEXT_DROP = re.compile(r"[\[\]{}<>]")


def _fold(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", text)
                   if unicodedata.category(c) != "Mn").lower()


def house_of(text: str) -> str | None:
    """The house a word names ("Grifindor", "**Ravenclaw.**"), or None."""
    words = re.sub(r"[^a-z ]", " ", _fold(text or "")).split()
    word = words[0] if words else ""
    for prefix, house in _HOUSE_PREFIXES:
        if word.startswith(prefix):
            return house
    return None


def split_reply(text: str) -> tuple[str, str | None]:
    """The model's reply -> (what the hat says, the house or None). Removes any stage or cue
    tag the model echoed and the "CASA:" line (an unknown house is still removed, as None)."""
    text = _TAG.sub(" ", text or "")
    house = None
    kept = []
    for line in text.splitlines():
        bare = _LINE_LEAD.sub("", line).replace("**", "").replace("__", "").strip()
        m = _CASA_LINE.match(bare)
        if m:
            house = house or house_of(m.group(1).strip(" .!*"))
            continue
        kept.append(line)
    spoken = " ".join(" ".join(kept).split())
    m = _CASA_TRAIL.search(spoken)
    if m:
        house = house or house_of(m.group(2))
        spoken = spoken[:m.start()] + m.group(1)
        spoken = " ".join(spoken.split())
    return spoken.strip(), house


def clean_cue_text(text, limit: int = CUE_TEXT_MAX) -> str:
    """A free-text cue, safe inside "[PISTAS: k=v; ...]": no brackets, braces, angle
    brackets, control characters, ";" or "="; collapsed; at most `limit` characters (60 for
    a cue; the fortune keeps 120 of a dream); never starting with "-" (loq reads a leading
    "-" as an option)."""
    if not isinstance(text, str):
        return ""
    s = unicodedata.normalize("NFC", text)
    s = _CONTROL.sub(" ", _TEXT_DROP.sub(" ", s)).replace(";", ",").replace("=", " ")
    s = " ".join(s.split())[:limit]
    return s.strip(" -,").strip()


_HOURS = ("doce", "una", "dos", "tres", "cuatro", "cinco", "seis", "siete", "ocho", "nueve",
          "diez", "once")


def cue_pairs(cues: dict) -> list[tuple[str, str]]:
    """The lit cues as the tags say them, in the sheet's order: (label, value), the
    impression as a noun (CUE_SAID). Shared by the visit's [PISTAS] and the fortune's tag."""
    return [(CUE_LABEL[k], CUE_SAID.get(k, {}).get(cues[k], cues[k]))
            for k in CUE_ORDER if cues.get(k)]


def say_hour(minutes: int) -> str:
    """Minutes after midnight as the hat says it: 917 -> "las 3 y 17" ("la 1 y 5")."""
    h, m = divmod(int(minutes), 60)
    h12 = h % 12 or 12
    art = "la" if h12 == 1 else "las"
    return f"{art} {h12}" + (f" y {m}" if m else " en punto")


def place_word(place) -> str:
    """The place as the tags say it (`place` is the config's PlaceConfig, live through the
    page's switches): the id for casa, fiesta and universidad, the cleaned free text for
    "otro", "" when "otro" has no text."""
    pid = getattr(place, "place", "") or ""
    if pid in PLACE_IDS:
        return pid
    if pid == "otro":
        return clean_cue_text(getattr(place, "text", "") or "")
    return ""


def future_tag(bank: dict | None, rng) -> str:
    """The verdict's ingredients, picked at random (the model alone settles on the same few):
    `[FUTURO: hora=…; lugar=…; …] `. `bank` is the persona's: {"hours": [from, to] as "H:MM",
    "card_odds": 0..1, kind: [choices], …}. Empty bank: no tag."""
    if not bank:
        return ""
    parts = []
    hours = bank.get("hours")
    if hours:
        lo, hi = (int(a) * 60 + int(b) for a, b in (h.split(":") for h in hours))
        parts.append("hora=" + say_hour(rng.randint(lo, hi)))
    for kind, choices in bank.items():
        if kind in ("hours", "card_odds") or not isinstance(choices, (list, tuple)) or not choices:
            continue
        if kind == "carta" and rng.random() >= float(bank.get("card_odds", 1.0)):
            continue
        parts.append(f"{kind}={rng.choice(list(choices))}")
    return "[FUTURO: " + "; ".join(parts) + "] " if parts else ""


def note(template: str, first: str = "", look: str | None = None) -> str:
    """A persona's note to the model with the visitor's first name and the look clause.
    Plain replacement, so braces in the owner's text never break it."""
    look_clause = f" Lleva: {look}." if look else ""
    return (template or "").replace("{first}", first or "").replace("{look}", look_clause)


def begin_model(llm, rules: str) -> None:
    """A new visitor for the model: no history, the visit's rules after the persona."""
    llm.reset()
    llm.extra_rules = rules


@dataclass
class NewVisit:
    """The operator's "New visitor" (POST /visit), an input item for the turn loop.
    `at` is when it was asked for: a turn that started a visit after it makes it moot."""
    at: float = 0.0


class Visit:
    def __init__(self, stages: int = 4, idle_s: float = 30.0, clock=time.monotonic,
                 future: dict | None = None, rng=None):
        import random
        self.stages = max(1, int(stages))
        self.future = future or {}              # the verdict's ingredients (future_tag)
        self._rng = rng or random.Random()
        self.idle_s = float(idle_s)
        self._clock = clock
        # The loop's side.
        self.n = 0                     # visits started (the page tells a new one by it)
        self.open = False
        self.said = 0                  # the hat's delivered turns in this visit
        self.first_name = ""
        self.house: str | None = None
        self.started_at: float | None = None
        self.last_s: float | None = None     # the end of the hat's last speech in this visit
        self._said_at: float | None = None   # this visit's last delivered turn
        # The page's side, under the lock.
        self._lock = threading.Lock()
        self._cues: dict[str, tuple[str, float]] = {}   # key -> (value, when it was set)
        self._cut: float | None = None        # the last act's close: older cues were its own
        self._last: dict[str, str] = {}      # the cues the last act closed with ("used:")
        self._request_at: float | None = None

    # ---- where the visit is ---------------------------------------------------------------
    @property
    def done(self) -> bool:
        return self.open and (self.house is not None or self.said >= self.stages)

    @property
    def stage(self) -> int:
        """0 = no visit; 1..stages = the hat's next turn; stages + 1 = the verdict was given."""
        if not self.open:
            return 0
        return self.stages + 1 if self.done else self.said + 1

    def needs_new(self, at: float) -> bool:
        """True when what the visitor said at `at` (when they started talking) belongs to a
        new visitor: none is open, the last one got its verdict, the operator asked for one,
        or the hat has been quiet longer than idle_s."""
        if not self.open or self.done:
            return True
        with self._lock:
            if self._request_at is not None:
                return True
        since = self.last_s if self.last_s is not None else self.started_at
        return bool(self.idle_s > 0 and since is not None and at - since > self.idle_s)

    def start(self, first_name: str = "", now: float | None = None, *,
              keep_cues: bool = False) -> None:
        """A visit begins. A new visitor keeps only the cues set after the last act closed
        (during a badge read, the greeting, or tapped before "New visitor"); the same
        visitor's restart (`keep_cues`) keeps them all."""
        now = self._clock() if now is None else now
        with self._lock:
            if not keep_cues:
                self._prune_locked()
            if self._request_at is not None and self._request_at <= now:
                self._request_at = None
        self.n += 1
        self.open, self.said, self.house = True, 0, None
        self._said_at = None
        self.first_name = first_name or ""
        self.started_at = self.last_s = now

    def _prune_locked(self) -> None:
        """A new visitor (under the lock): the cues stamped up to the cut were the last
        act's; `_last` is forgotten. A visit left without a verdict cuts at its last
        delivered turn (cues set before it were that visitor's)."""
        edge = self._cut
        if self.open and not self.done and self._said_at is not None:
            edge = self._said_at if edge is None else max(edge, self._said_at)
        if edge is not None:
            self._cues = {k: (v, t) for k, (v, t) in self._cues.items() if t > edge}
        self._last = {}

    def close(self, cut: float) -> None:
        """An act ended (the verdict, a fortune's closing or drop): the cues stamped up to
        `cut` are filed as `_last` and leave the row; newer ones stay for the next visitor."""
        with self._lock:
            self._last = {k: v for k, (v, t) in self._cues.items() if t <= cut}
            self._cues = {k: (v, t) for k, (v, t) in self._cues.items() if t > cut}
            self._cut = cut if self._cut is None else max(self._cut, cut)

    def next_act(self, carry: bool, now: float | None = None) -> None:
        """Another act begins (the fortune) without a visit start. `carry`: the same visitor
        as the last act, whose filed cues are lit again under the current ones; otherwise a
        new visitor's prune."""
        now = self._clock() if now is None else now
        with self._lock:
            if carry:
                relit = {k: (v, now) for k, v in self._last.items()}
                self._cues = {**relit, **self._cues}
            else:
                self._prune_locked()

    def end(self) -> None:
        self.open = False

    def touch(self, now: float | None = None) -> None:
        """The hat just finished speaking (any line of this visit's turns)."""
        if self.open:
            self.last_s = self._clock() if now is None else now

    def prepare(self, text: str, lugar: str = "") -> tuple[str, dict]:
        """The text for the model: the stage tag, the place and every lit cue, what was
        said. The snapshot (when it was asked, the cues sent) goes back to `delivered`: a
        verdict closes the act at the moment it was asked for."""
        n = min(self.said + 1, self.stages)
        asked = self._clock()
        with self._lock:
            cues = {k: v for k, (v, _t) in self._cues.items()}
        tag = f"[ETAPA {n}/{self.stages}] "
        if n == self.stages:
            tag += future_tag(self.future, self._rng)
        parts = [f"lugar={lugar}"] if lugar else []
        parts += [f"{label}={said}" for label, said in cue_pairs(cues)]
        if parts:
            tag += "[PISTAS: " + "; ".join(parts) + "] "
        return tag + (text or ""), {"at": asked, "cues": cues}

    def delivered(self, house: str | None = None, snapshot: dict | None = None,
                  now: float | None = None, *, cut: float | None = None) -> None:
        """The hat's turn was spoken: the stage moves on; a house (or the last stage) closes
        the visit, cut at `cut`, else when the turn was asked for (the snapshot), else `now`."""
        now = self._clock() if now is None else now
        self.said += 1
        if house:
            self.house = house
        self.last_s = self._said_at = now
        if self.done:
            if cut is None:
                cut = snapshot["at"] if snapshot and "at" in snapshot else now
            self.close(cut)

    # ---- the page's side ------------------------------------------------------------------
    def request_new(self, at: float) -> None:
        with self._lock:
            self._request_at = at

    def cancel_request(self, at: float) -> None:
        with self._lock:
            if self._request_at == at:
                self._request_at = None

    def set_cues(self, cues) -> None:
        """The sheet's whole set of lit cues (an empty value or a missing key = unset). A
        value that did not change keeps its stamp. Errors name no text the page sent."""
        if not isinstance(cues, dict):
            raise ValueError("cues must be an object")
        clean: dict[str, str] = {}
        for k, v in cues.items():
            if k in CUE_CHOICES:
                if v in ("", None):
                    continue
                if v not in CUE_CHOICES[k]:
                    raise ValueError(f"bad value for {k}")
                clean[k] = v
            elif k in CUE_TEXT:
                if v in ("", None):
                    continue
                if not isinstance(v, str):
                    raise ValueError(f"bad value for {k}")
                text = clean_cue_text(v)
                if text:
                    clean[k] = text
            else:
                raise ValueError("unknown cue")
        now = self._clock()
        with self._lock:
            old = self._cues
            self._cues = {k: (v, old[k][1] if k in old and old[k][0] == v else now)
                          for k, v in clean.items()}

    def pending(self) -> dict[str, str]:
        with self._lock:
            return {k: v for k, (v, _t) in self._cues.items()}

    def view(self) -> dict:
        """What the operator's sheet shows. Never sent to /status."""
        with self._lock:
            cues = {k: v for k, (v, _t) in self._cues.items()}
            used = dict(self._last)
        return {"n": self.n, "stage": self.stage, "of": self.stages,
                "first": self.first_name if self.open else "", "house": self.house,
                "cues": cues, "used": used}
