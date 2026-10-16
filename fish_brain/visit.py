"""The hat's visit (cold reading): four hat turns per visitor, the stage told to the model
as a tag, the operator's cues added once, and the house line taken out before the voice.

A visit opens with a greeting (canned, or the badge's "¿Tú eres X?", or the model's first
answer), then two readings that end in a question, then the verdict: the house with a reason
from the visitor's own words and a short line about the rest of the fair, closed by
"CASA: <house>". The turn loop (conversation.py) and the rehearsal (tools/hat_rehearse.py)
run the same steps:

    needs_new(at) -> start(first, now)       a new visitor (the model's history is reset)
    prepare(text) -> (tagged, snapshot)      "[ETAPA n/4] [PISTAS: ...] " + what was said
    split_reply(reply) -> (spoken, house)    before anything is said or shown
    delivered(house, snapshot, now)          only once the reply was spoken (or drafted)

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
                   ("slid", "Slytherin"))

# The operator's cues (the sheet's chips): key -> allowed values. Keys are ASCII for the page;
# the tag uses the labels.
CUE_CHOICES: dict[str, tuple[str, ...]] = {
    "edad": ("niño", "adolescente", "adulto"),
    "compania": ("solo", "amigos", "familia"),
    "color": ("rojo", "azul", "verde", "amarillo", "negro", "blanco", "rosa", "morado"),
    "impresion": ("tímido", "sonriente", "curioso"),
}
CUE_TEXT = ("lleva", "nota")          # short free text: something worn or carried, a note
CUE_TEXT_MAX = 60
CUE_ORDER = (*CUE_CHOICES, *CUE_TEXT)
CUE_LABEL = {"edad": "edad", "compania": "compañía", "color": "color",
             "impresion": "impresión", "lleva": "lleva", "nota": "nota"}

_TAG = re.compile(r"\[\s*(?:ETAPA|PISTAS|FIN)\b[^\]]*\]", re.IGNORECASE)
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


def clean_cue_text(text) -> str:
    """A free-text cue, safe inside "[PISTAS: k=v; ...]": no brackets, braces, angle
    brackets, control characters, ";" or "="; collapsed; at most 60 characters; never
    starting with "-" (loq reads a leading "-" as an option)."""
    if not isinstance(text, str):
        return ""
    s = unicodedata.normalize("NFC", text)
    s = _CONTROL.sub(" ", _TEXT_DROP.sub(" ", s)).replace(";", ",").replace("=", " ")
    s = " ".join(s.split())[:CUE_TEXT_MAX]
    return s.strip(" -,").strip()


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
    """The operator's "Nuevo visitante" (POST /visit), an input item for the turn loop.
    `at` is when it was asked for: a turn that started a visit after it makes it moot."""
    at: float = 0.0


class Visit:
    def __init__(self, stages: int = 4, idle_s: float = 30.0, clock=time.monotonic):
        self.stages = max(1, int(stages))
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
        self._last_reply: float | None = None   # the last delivered turn, any visit
        # The page's side, under the lock.
        self._lock = threading.Lock()
        self._cues: dict[str, tuple[str, float]] = {}   # key -> (value, when it was set)
        self._sent: dict[str, str] = {}
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

    def start(self, first_name: str = "", now: float | None = None) -> None:
        now = self._clock() if now is None else now
        with self._lock:
            # Cues set before the previous visitor's last answer were that visitor's; the
            # ones set since (during a badge read, or the greeting) are for this one.
            edge = self._last_reply
            if edge is not None:
                self._cues = {k: (v, t) for k, (v, t) in self._cues.items() if t > edge}
            self._sent = {}
            if self._request_at is not None and self._request_at <= now:
                self._request_at = None
        self.n += 1
        self.open, self.said, self.house = True, 0, None
        self.first_name = first_name or ""
        self.started_at = self.last_s = now

    def end(self) -> None:
        self.open = False

    def touch(self, now: float | None = None) -> None:
        """The hat just finished speaking (any line of this visit's turns)."""
        if self.open:
            self.last_s = self._clock() if now is None else now

    def prepare(self, text: str) -> tuple[str, dict]:
        """The text for the model: the stage tag, the pending cues, what was said. The
        snapshot goes back to `delivered` so only the cues that reached the model are used."""
        n = min(self.said + 1, self.stages)
        with self._lock:
            snapshot = dict(self._cues)
        tag = f"[ETAPA {n}/{self.stages}] "
        cues = [f"{CUE_LABEL[k]}={snapshot[k][0]}" for k in CUE_ORDER if k in snapshot]
        if cues:
            tag += "[PISTAS: " + "; ".join(cues) + "] "
        return tag + (text or ""), snapshot

    def delivered(self, house: str | None = None, snapshot: dict | None = None,
                  now: float | None = None) -> None:
        """The hat's turn was spoken: the stage moves on; a house closes the visit."""
        now = self._clock() if now is None else now
        self.said += 1
        if house:
            self.house = house
        self.last_s = self._last_reply = now
        if snapshot:
            with self._lock:
                for k, vt in snapshot.items():
                    if self._cues.get(k) == vt:     # re-tapped meanwhile: it stays pending
                        del self._cues[k]
                self._sent = {k: v for k, (v, _t) in snapshot.items()}

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
            sent = dict(self._sent)
        return {"n": self.n, "stage": self.stage, "of": self.stages,
                "first": self.first_name if self.open else "", "house": self.house,
                "cues": cues, "sent": sent}
