"""La calaverita, pure (ADR 0033): its clips' names and texts from prompts/calaverita.toml, the tag
sent to the model and the checks on the verse it sends back. calaverita_run.py is the act."""
from __future__ import annotations

import re

from . import texts
from .visit import _fold, cue_pairs

_WORDS = texts.calaverita()
RULES: str = _WORDS["rules"].strip()
NUNCA = tuple(_WORDS["nunca"])
HOUSE_KEYS = ("G", "H", "R", "S")

STANZAS, STANZA_LINES = 3, 4
LINES = STANZAS * STANZA_LINES
MAX_LINE_CHARS = 48       # a verse this long is not a verse; the ticket folds it (estimate)
MIN_WORDS, MAX_WORDS = 40, 90     # twelve lines of eight syllables are about 60 words (estimate)

_LINE_LEAD = re.compile(r"^[\s>*_#\-–—\d.)]*")   # markdown or a numbered list before a verse
_MARKS = re.compile(r"[*_`#\"“”«»]")
_CASA = re.compile(r"^casa\s*:", re.I)
_TAG = re.compile(r"[\[\]=]")


def stanzas_of(raw: str) -> list[list[str]]:
    """The model's reply as verses, four to a stanza; a title line before them (13 lines with a
    blank after the first) goes. The count is `verse_problems`' to judge: a short reply gives
    a short last stanza."""
    blocks: list[list[str]] = [[]]
    for line in (raw or "").splitlines():
        verse = _MARKS.sub("", _LINE_LEAD.sub("", line)).strip()
        if _CASA.match(verse):
            continue
        if verse:
            blocks[-1].append(verse)
        elif blocks[-1]:
            blocks.append([])
    if len(blocks) > 1 and len(blocks[0]) == 1 and sum(map(len, blocks)) == LINES + 1:
        blocks.pop(0)
    verses = [v for b in blocks for v in b]
    return [verses[i:i + STANZA_LINES] for i in range(0, len(verses), STANZA_LINES)]


def verse_problems(stanzas: list[list[str]], nunca=NUNCA) -> list[str]:
    """Why a verse would be refused ([] = it would be said and printed). Its shape and the family
    word list only: rhyme and meter are for the rehearsal, a crude count never rejects a poem."""
    verses = [v for s in stanzas for v in s]
    if not verses:
        return ["empty"]
    out = []
    if len(verses) != LINES:
        out.append(f"{len(verses)} lines")
    long = [v for v in verses if len(v) > MAX_LINE_CHARS]
    if long:
        out.append(f"{len(long)} long lines")
    words = sum(len(v.split()) for v in verses)
    if not MIN_WORDS <= words <= MAX_WORDS:
        out.append(f"{words} words")
    if any(_TAG.search(v) for v in verses):
        out.append("a tag")
    said = set(re.findall(r"[^\W\d_]+", _fold(" ".join(verses))))
    hits = sorted(w for w in nunca if _fold(w) in said)
    if hits:
        out.append("nunca: " + ", ".join(hits))
    return out


def clean_verse(raw: str, nunca=NUNCA) -> tuple[tuple[str, ...], ...] | None:
    """The model's reply fit to be said and printed, as stanzas; None when it is not."""
    stanzas = stanzas_of(raw)
    if verse_problems(stanzas, nunca):
        return None
    return tuple(tuple(s) for s in stanzas)


def spoken_verse(stanzas) -> str:
    """One line for the voice: the punctuation is the pause, a comma at the end of a verse (only
    when it has no mark of its own) and a period at the end of a stanza."""
    out = []
    for stanza in stanzas:
        for i, verse in enumerate(stanza):
            last = i == len(stanza) - 1
            if verse[-1] in ".!?…" or (verse[-1] in ",;:" and not last):
                out.append(verse)
            else:
                out.append(verse.rstrip(",;:") + ("." if last else ","))
    return " ".join(out)


def page_verse(stanzas) -> str:
    """For the page: a line to a verse, a blank line between stanzas."""
    return "\n\n".join("\n".join(s) for s in stanzas)


def verse_tag(first: str, house: str, lugar: str, cues: dict, heard: list[str]) -> str:
    """What the model gets of this visitor: only what the visit knows."""
    parts = []
    if first:
        parts.append(f"nombre={first}")
    parts.append(f"casa={house}")
    if lugar:
        parts.append(f"lugar={lugar}")
    if heard:
        parts.append("dijo=" + "|".join(f'"{h}"' for h in heard))
    pistas = [f"{k}: {v}" for k, v in cue_pairs(cues)]
    if pistas:
        parts.append("pistas=" + ", ".join(pistas))
    return "[CALAVERITA: " + "; ".join(parts) + "]"


# ---- the clips -------------------------------------------------------------------------------
def pool_names(slot: str) -> list[str]:
    return [f"calaverita_{slot}_{i}" for i in range(1, len(_WORDS["pools"][slot]) + 1)]


def fallback_names(letter: str) -> list[str]:
    return [f"calaverita_verso_{letter}_{i}" for i in range(1, len(FALLBACK[letter]) + 1)]


def _fallbacks() -> dict[str, tuple]:
    out = {}
    for letter in HOUSE_KEYS:
        out[letter] = []
        for i, verse in enumerate(_WORDS["fallback"][letter], 1):
            stanzas = clean_verse(verse)
            if stanzas is None:
                raise ValueError(f"calaverita.toml: fallback.{letter} verse {i}: "
                                 + "; ".join(verse_problems(stanzas_of(verse))))
            out[letter].append(stanzas)
    return out


FALLBACK = _fallbacks()


def fallback_stanzas(name: str):
    """The stanzas of a fallback clip, for the page and the ticket."""
    letter, i = name.rsplit("_", 2)[1:]
    return FALLBACK[letter][int(i) - 1]


def _phrases() -> dict[str, str]:
    out = {}
    for slot, lines in _WORDS["pools"].items():
        out.update(zip(pool_names(slot), lines))
    for letter in HOUSE_KEYS:
        out.update(zip(fallback_names(letter), map(spoken_verse, FALLBACK[letter])))
    return out


CALAVERITA_PHRASES = _phrases()
