"""La calaverita, pure (ADR 0034): its clips' names and texts from prompts/calaverita.toml, the tag
sent to the model and the checks on the verse it sends back. calaverita_run.py is the act."""
from __future__ import annotations

import concurrent.futures as cf
import re
import time
import unicodedata

from . import texts
from .visit import _fold, begin_model, cue_pairs

_WORDS = texts.calaverita()
RULES: str = _WORDS["rules"].strip()
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


def verse_problems(stanzas: list[list[str]]) -> list[str]:
    """Why a verse would be refused ([] = it would be said and printed). Its shape only, no word
    list (ADR 0034, amended); the rhyme is `compose`'s to judge, and the meter is never a reason."""
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
    return out


# ---- meter and rhyme ---------------------------------------------------------------------------
_VOWELS = "aeiouáéíóúüy"
_STRONG = "aeoáéó"


def _nuclei(word: str) -> list[bool]:
    """The word's syllable nuclei, True where one has the accent mark. Two strong vowels, or a
    weak one with its mark beside another, are two; "y" counts only as the end of a word."""
    w = word.lower()
    out, i = [], 0
    while i < len(w):
        ch = w[i]
        if ch not in _VOWELS or (ch == "y" and i < len(w) - 1 and len(w) > 1):
            i += 1
            continue
        j = i
        while j < len(w) and w[j] in _VOWELS and (w[j] != "y" or j == len(w) - 1):
            j += 1
        group = w[i:j]
        if group.startswith("u") and i and w[i - 1] in "qg" and len(group) > 1:
            group = group[1:]                    # que, gui: the u is silent
        nuclei: list[bool] = []
        hard = False
        for c in group:
            this = c in "aeoáéóíú"
            if not nuclei or (this and hard):
                nuclei.append(False)
                hard = False
            nuclei[-1] = nuclei[-1] or c in "áéíóú"
            hard = hard or this
        out += nuclei
        i = j
    return out


def _stress(word: str) -> int:
    """Which syllable from the end carries the stress: 0 aguda, 1 llana, 2 esdrújula."""
    n = _nuclei(word)
    if len(n) < 2:
        return 0
    if any(n):
        return len(n) - 1 - max(i for i, m in enumerate(n) if m)
    return 1 if word.lower()[-1] in "aeiouns" else 0


def syllables(line: str) -> int:
    """A verse's metric count: vowels joined across words, +1 on an aguda, -1 on an esdrújula. A
    crude scanner, good enough to compare versions."""
    words = re.findall(r"[^\W\d_]+", line)
    if not words:
        return 0
    total = sum(len(_nuclei(w)) or 1 for w in words)
    for a, b in zip(words, words[1:]):
        if a[-1].lower() in _VOWELS and b.lower().lstrip("h")[:1] in tuple(_VOWELS):
            total -= 1
    return total + {0: 1, 1: 0}.get(_stress(words[-1]), -1)


def rhyme_key(line: str) -> str:
    """The verse's rhyme: its last word from the stressed vowel on, with no accents and as Mexico
    says it (s, z and soft c alike, b and v, ll and y)."""
    words = re.findall(r"[^\W\d_]+", line.lower())
    if not words:
        return ""
    word = words[-1]
    back, at = _stress(word), 0
    spans = [m.start() for m in re.finditer(r"[aeiouáéíóúü]+", word)]
    if spans:
        at = spans[max(0, len(spans) - 1 - back)]
    marked = [i for i, c in enumerate(word) if c in "áéíóú"]
    if marked:
        at = marked[-1]                          # traía: from the í, whatever the groups say
    tail = "".join(c for c in unicodedata.normalize("NFD", word[at:])
                   if unicodedata.category(c) != "Mn")
    for a, b in (("ce", "se"), ("ci", "si"), ("z", "s"), ("v", "b"), ("ll", "y")):
        tail = tail.replace(a, b)
    if marked:
        return tail
    return re.sub(r"^[iu](?=[aeo])", "", tail)    # cuenta and venta rhyme


def pair_rhymes(a: str, b: str) -> bool:
    """Two verses rhyme: the same ending, on two different words (gane does not rhyme with gane)."""
    last = [re.findall(r"[^\W\d_]+", _fold(v))[-1:] for v in (a, b)]
    return bool(rhyme_key(a)) and rhyme_key(a) == rhyme_key(b) and last[0] != last[1]


def bad_pairs(stanzas) -> list[tuple[int, str, str]]:
    """The pairs that should rhyme and do not: (stanza from 1, verse, verse)."""
    return [(n, s[x], s[y]) for n, s in enumerate(stanzas, 1) if len(s) == STANZA_LINES
            for x, y in ((0, 2), (1, 3)) if not pair_rhymes(s[x], s[y])]


def verse_metrics(stanzas) -> dict:
    """How close a verse is to the form: lines at eight syllables and within one, stanzas whose
    first and third, and second and fourth, lines rhyme."""
    lines = [v for s in stanzas for v in s]
    counts = [syllables(v) for v in lines]
    rhymed = sum(len(s) == STANZA_LINES and pair_rhymes(s[0], s[2]) and pair_rhymes(s[1], s[3])
                 for s in stanzas)
    return {"lines": len(lines), "at8": sum(c == 8 for c in counts),
            "near8": sum(abs(c - 8) <= 1 for c in counts), "stanzas": len(stanzas), "rhymed": rhymed}


def correction(tag: str, stanzas) -> str:
    """What the model is sent to mend its best version: the pairs that do not rhyme."""
    verse = "\n\n".join("\n".join(s) for s in stanzas)
    pairs = "\n".join(f'- estrofa {n}: "{a}" no rima con "{b}"' for n, a, b in bad_pairs(stanzas))
    return f"{tag}\n" + _WORDS["corrige"].strip().format(verso=verse, parejas=pairs)


def compose(clients, rules: str, tag: str, *, thinking: str | None = None, passes: int = 4,
            budget_s: float = 12.0, gone=lambda: False, clock=time.monotonic) -> dict:
    """Versions until one rhymes: one from each client at once, then the best one sent back with
    the pairs that do not rhyme, until every stanza rhymes, `passes` run out or no new pass may
    start after `budget_s`. Returns {stanzas (the best fit to be said, or None), rhymed, passes,
    versions, error (the first, only when no version came), raw}. Runs in a worker; each client
    is used by one call at a time."""
    start = clock()
    best, best_score, raw, error = None, None, "", None
    done = versions = 0
    ask = tag

    def one(llm):
        begin_model(llm, rules)
        llm.thinking = thinking or None
        try:
            reply = llm.reply(ask, remember=False)
        except Exception as e:
            return None, f"{type(e).__name__}: {e}"
        return reply, llm.last_error
    with cf.ThreadPoolExecutor(max(1, len(clients))) as pool:
        while done < passes and not gone() and (not done or clock() - start < budget_s):
            done += 1
            answered = 0
            for reply, err in pool.map(one, clients):
                if err:
                    error = error or err
                    continue
                answered += 1
                versions += 1
                raw = raw or reply
                stanzas = stanzas_of(reply)
                if verse_problems(stanzas):
                    continue
                m = verse_metrics(stanzas)
                score = (m["rhymed"], m["near8"])
                if best_score is None or score > best_score:
                    best, best_score, raw = tuple(tuple(s) for s in stanzas), score, reply
            if not answered or (best_score and best_score[0] == STANZAS):
                break
            ask = correction(tag, best) if best else tag
    return {"stanzas": best, "rhymed": best_score[0] if best_score else 0, "passes": done,
            "versions": versions, "error": None if versions else error, "raw": raw}


def clean_verse(raw: str) -> tuple[tuple[str, ...], ...] | None:
    """The model's reply fit to be said and printed, as stanzas; None when it is not."""
    stanzas = stanzas_of(raw)
    if verse_problems(stanzas):
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
