"""The fortune's ticket (the MP210, 58 mm ESC/POS): what goes on the paper and its bytes.

Pure: no socket, no Pillow, no state. The act builds a `Ticket` (plain values, no I/O) on the
turn loop's thread; the printer's worker (printer.py) lays it out and sends the parts:

    ticket_of(v, said, phrases=, place=, now=) -> Ticket     sample(card) -> Ticket
    layout(t) -> [Line | Rule | Art | Feed]     encode(blocks) -> [bytes, ...]
    preview(blocks) -> the ticket as 32 columns of text (the mock printer, the tests)

The content reuses what the act already has (PLAN Decision 16): the name, the card's plate
with its numeral, name and meaning, the reading (the model's text, or the texts of the
number, moon and magic word clips), leader lines for the number, the moon, the wish and the
magic word, and a footer in Font B: the date when the clock is sane and the place. No folio and
no plate credit, to save paper (his word, 2026-10-29: the credit belongs on the page). The dream,
the cup, the house and the mode stay off the paper.

Text: printer fonts only, Font A (12x24 dots, 32 columns) for what the visitor reads and Font
B (9x17, 42 columns) for the footer; every text passes `printable` (no control byte reaches
the printer, whatever the model or a typed name carried) and is wrapped after it. Pictures:
1-bit PBM P4 plates under ticket_art/<deck>/NN.pbm, whose bits are already GS v 0's (MSB the
leftmost dot, 1 = black), sent in bands; a missing or bad file means no picture, never an
error.

The labels below are drafts for the owner to edit (2026-10-28), like fortune_bank.py's texts.
"""
from __future__ import annotations

import re
import textwrap
import unicodedata
from dataclasses import dataclass
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import NamedTuple

from . import fortune, fortune_bank
from .visit import clean_cue_text

# ---- the printer (MP210 manual; the rest decided on the desk) -------------------------------
PAPER_DOTS = 384                 # 48 mm of print at 203 dpi
PAPER_BYTES = PAPER_DOTS // 8
COLUMNS = {"a": 32, "b": 42}     # Font A 12x24, Font B 9x17 (estimate) until the desk results
# ESC t n and its codec: 19 (cp858) and 2 (cp850) print ñ á ¿ ¡ right on the MP210, 16 prints
# black blocks (no cp1252), and the power-on page is CP850 (docs/results/2026-10-28-mp210-on-
# the-desk.md). cp858 holds every bank text but "…", which printable() maps.
CODEPAGE = 19
CODEC = "cp858"
BAND_ROWS = 24                   # raster rows per GS v 0 (estimate) until the desk results
TEAR_FEED = 4                    # lines fed past the tear bar (estimate) until the desk results
ART_MAX_ROWS = 800               # a plate taller than this is a bad file
ART_DIR = Path(__file__).resolve().parent / "ticket_art"
YEAR_SANE = 2026                 # fortune.moon_tonight's rule: an earlier clock is not set

# ---- ESC/POS, by hand ------------------------------------------------------------------------
INIT = b"\x1b@"                  # ESC @
CHINESE_OFF = b"\x1c."           # FS .  (some firmwares boot in GB18030 mode)
CHARSET_USA = b"\x1bR\x00"       # ESC R 0
LF = b"\n"


def header(codepage: int = CODEPAGE) -> bytes:
    """What every ticket starts with: init, Chinese mode off, the USA set, the code page."""
    return INIT + CHINESE_OFF + CHARSET_USA + bytes((0x1B, 0x74, codepage))


def _align(a: str) -> bytes:
    return bytes((0x1B, 0x61, {"l": 0, "c": 1, "r": 2}[a]))


def _bold(on: bool) -> bytes:
    return bytes((0x1B, 0x45, int(on)))


def _font(f: str) -> bytes:
    return bytes((0x1B, 0x4D, 0 if f == "a" else 1))


def _size(big: bool) -> bytes:
    return bytes((0x1D, 0x21, 0x11 if big else 0x00))


def _feed(n: int) -> bytes:
    return bytes((0x1B, 0x64, max(0, min(255, n))))


# ---- the labels (drafts for the owner to edit, 2026-10-28) ----------------------------------
TITLE = "LA ADIVINACIÓN"
SUBTITLE = "del Sombrero Seleccionador"
FOR = "para"
LABEL_NUMBER = "Número de la suerte"
LABEL_MOON = "Luna"
LABEL_WISH = "Pediste"
LABEL_MAGIC = "Palabra mágica"
SAMPLE_NAME = "Prueba"
LABELS = (TITLE, SUBTITLE, FOR, LABEL_NUMBER, LABEL_MOON, LABEL_WISH, LABEL_MAGIC,
          SAMPLE_NAME)


# ---- text -------------------------------------------------------------------------------------
_SPACES = re.compile(r"[\t\n\r\v\f   -     　]")
_CONTROLS = re.compile(r"[\x00-\x1f\x7f-\x9f]")
_ZERO_WIDTH = re.compile(r"[­​-‍⁠﻿]")
_MARKDOWN = re.compile(r"[*_`#]")
_OPENERS_GLUE = re.compile(r"([¿¡])\s+")
_SPACE_BEFORE = re.compile(r"\s+([?!,.;:])")
# Used only when the code page lacks the character.
_MAP = {"…": "...", "“": '"', "”": '"', "„": '"', "«": '"', "»": '"', "‘": "'", "’": "'",
        "‚": "'", "–": "-", "—": "-", "―": "-", "‐": "-", "‑": "-", "−": "-", "·": "-",
        "Ł": "L", "ł": "l", "Œ": "OE", "œ": "oe", "Æ": "AE", "æ": "ae", "ß": "ss", "€": "EUR"}


def _encodes(ch: str, codec: str) -> bool:
    try:
        ch.encode(codec)
        return True
    except UnicodeEncodeError:
        return False


def printable(text, codec: str = CODEC) -> str:
    """`text` as the code page can print it, on one line: control characters (an ESC from
    the model or a typed name) never pass, markdown marks go, what the page lacks is mapped
    ("…" to "...") or falls back to its base letter, anything else (emoji) is dropped; "¿"
    and "¡" stay glued to their word and no space is left before ". , ; : ? !"."""
    if not isinstance(text, str):
        return ""
    s = _SPACES.sub(" ", text)
    s = _CONTROLS.sub("", _ZERO_WIDTH.sub("", s))
    s = _MARKDOWN.sub("", unicodedata.normalize("NFC", s))
    out = []
    for ch in s:
        if _encodes(ch, codec):
            out.append(ch)
        elif ch in _MAP and all(_encodes(c, codec) for c in _MAP[ch]):
            out.append(_MAP[ch])
        else:
            base = unicodedata.normalize("NFD", ch)[0]
            if base != ch and not unicodedata.combining(base) and _encodes(base, codec):
                out.append(base)
    s = " ".join("".join(out).split())
    s = _SPACE_BEFORE.sub(r"\1", _OPENERS_GLUE.sub(r"\1", s))
    return s.rstrip("¿¡ ")


def wrap(text: str, width: int) -> list[str]:
    """Lines of at most `width` columns (one character is one column after `printable`),
    broken at spaces only, never inside a hyphenated word unless it alone is too long."""
    return textwrap.wrap(text, width, break_on_hyphens=False) if text else []


def roman(n: int) -> str:
    """The plate's numeral: 13 -> "XIII"; the Fool's 0 stays "0"."""
    if n <= 0:
        return "0"
    out = ""
    for value, sym in ((1000, "M"), (900, "CM"), (500, "D"), (400, "CD"), (100, "C"),
                       (90, "XC"), (50, "L"), (40, "XL"), (10, "X"), (9, "IX"), (5, "V"),
                       (4, "IV"), (1, "I")):
        while n >= value:
            out, n = out + sym, n - value
    return out


# ---- pictures ---------------------------------------------------------------------------------
@lru_cache(maxsize=64)
def read_pbm(path: str) -> tuple[int, int, bytes] | None:
    """A binary PBM (P4) as (bytes per row, rows, bits), or None when it is missing, bad, or
    wider than the paper. The pad bits after the last dot of a row are cleared."""
    try:
        raw = Path(path).read_bytes()
    except OSError:
        return None
    pos, fields = 2, []
    if raw[:2] != b"P4":
        return None
    while len(fields) < 2:
        while pos < len(raw) and raw[pos:pos + 1].isspace():
            pos += 1
        if raw[pos:pos + 1] == b"#":
            end = raw.find(b"\n", pos)
            pos = len(raw) if end < 0 else end + 1
            continue
        start = pos
        while pos < len(raw) and raw[pos:pos + 1].isdigit():
            pos += 1
        if start == pos:
            return None
        fields.append(int(raw[start:pos]))
    width, rows = fields
    if not raw[pos:pos + 1].isspace() or not (0 < width <= PAPER_DOTS and 0 < rows <= ART_MAX_ROWS):
        return None
    wb = (width + 7) // 8
    data = raw[pos + 1:pos + 1 + wb * rows]
    if len(data) < wb * rows:
        return None
    if width % 8:
        keep = (0xFF << (8 - width % 8)) & 0xFF
        data = bytearray(data)
        for r in range(rows):
            data[r * wb + wb - 1] &= keep
        data = bytes(data)
    return wb, rows, data


def card_art(deck: str, n: int, root: Path | str | None = None) -> tuple[int, int, bytes] | None:
    """The plate of card `n` in `deck` (ticket_art/<deck>/NN.pbm), or None."""
    if not deck or n is None or not re.fullmatch(r"[a-z0-9_]+", deck):
        return None
    return read_pbm(str(Path(root or ART_DIR) / deck / f"{int(n):02d}.pbm"))


def pad(data: bytes, wb: int, rows: int, to: int = PAPER_BYTES) -> bytes:
    """Rows of `wb` bytes centred in rows of `to` bytes (white either side)."""
    if wb >= to:
        return data
    left = (to - wb) // 2
    lpad, rpad = bytes(left), bytes(to - wb - left)
    return b"".join(lpad + data[r * wb:(r + 1) * wb] + rpad for r in range(rows))


def raster(data: bytes, wb: int, rows: int, *, band: int = BAND_ROWS) -> list[bytes]:
    """GS v 0 commands, one per band of at most `band` rows."""
    out = []
    for top in range(0, rows, max(1, band)):
        h = min(band, rows - top)
        out.append(bytes((0x1D, 0x76, 0x30, 0x00, wb & 0xFF, wb >> 8, h & 0xFF, h >> 8))
                   + data[top * wb:(top + h) * wb])
    return out


RULE_DOTS = 336                  # a dotted rule, 42 bytes of 2-on 2-off, centred
RULE_ROWS = 2


def _rule_bits() -> bytes:
    return pad(b"\xcc" * (RULE_DOTS // 8) * RULE_ROWS, RULE_DOTS // 8, RULE_ROWS)


# ---- the ticket ------------------------------------------------------------------------------
@dataclass(frozen=True)
class Ticket:
    """One visitor's ticket, plain values: built on the loop's thread, kept for Reprint."""
    n: int
    first: str = ""
    deck: str = ""                  # the deck id, "" when no card was drawn
    card: int | None = None
    card_es: str = ""
    card_meaning: str = ""
    body: tuple[str, ...] = ()      # paragraphs: the model's reading, or the clips' texts
    numero: str = ""
    luna: str = ""
    deseo: str = ""                 # what the visitor asked of La Muerte, as said
    palabra: str = ""
    day: str = ""                   # "28 de octubre de 2026", "" when the clock is not sane
    place: str = ""                 # "en una fiesta", or the operator's own text


def date_words(now: datetime | None) -> str:
    if now is None or now.year < YEAR_SANE:
        return ""
    return f"{now.day} de {fortune.MONTHS[now.month - 1]} de {now.year}"


def place_said(pid, place=None) -> str:
    """The act's place as the ticket says it: PLACE_SAID for casa, fiesta and universidad,
    the operator's free text for "otro" (`place` is the config's PlaceConfig), else ""."""
    if pid in fortune.PLACE_SAID and pid != "otro":
        return fortune.PLACE_SAID[pid]
    if pid == "otro":
        return clean_cue_text(getattr(place, "text", "") or "")
    return ""


def ticket_of(v: dict, said: dict, *, phrases: dict, place=None,
              now: datetime | None = None) -> Ticket:
    """The ticket of an act: `v` is FortuneRun.v, `said` its `_said_data(v)`, `phrases` the
    canned texts by name (cfg.canned.phrases), `place` the PlaceConfig, `now` the local
    time. No I/O. The clips' body is built from the data the way `_finish_clips` names them,
    so it is right before those clips are appended to v["clips"]."""
    data = v.get("data") or {}
    deck = v.get("deck") or None
    card = None
    if deck is not None and data.get("carta") is not None:
        try:
            card = fortune.card_by_n(deck, data["carta"])
        except KeyError:
            card = None
    if v.get("reading"):
        body = (v["reading"],)
    else:
        names = []
        if data.get("numero"):
            names.append(fortune_bank.num_name(data["numero"]))
        if data.get("luna"):
            names.append(fortune_bank.moon_name(data["luna"]))
        if v.get("magic"):
            names.append(v["magic"])
        body = tuple(t for t in (phrases.get(n, "") for n in names) if t)
    return Ticket(
        n=int(v.get("n") or 0), first=v.get("first") or "",
        deck=deck.get("id", "") if card is not None else "",
        card=card.n if card is not None else None,
        # A reversed card: its name says so, and the upright meaning is left off the paper.
        card_es=(card.es + (", de cabeza" if data.get("carta_reves") else "")) if card is not None else "",
        card_meaning=card.meaning if card is not None and not data.get("carta_reves") else "",
        body=body, numero=str(said.get("numero") or ""), luna=said.get("luna") or "",
        deseo=said.get("deseo") or "", palabra=said.get("palabra") or "",
        day=date_words(now), place=place_said(v.get("place"), place))


def sample(card: int = 13, *, now: datetime | None = None) -> Ticket:
    """The test ticket (--print-test): bank texts only, the number six, a full moon, the
    first magic word, a wish for love, at a party."""
    deck = fortune.DECKS["tarot"]
    c = fortune.card_by_n(deck, card)
    return Ticket(
        n=0, first=SAMPLE_NAME, deck="tarot", card=c.n, card_es=c.es, card_meaning=c.meaning,
        body=(fortune_bank.NUMBER_LINES[6], fortune_bank.MOON_LINES["llena"],
              fortune_bank.POOLS["magic"][0]),
        numero="6", luna=fortune.MOON_SAID["llena"], deseo="amor",
        palabra=fortune.MAGIC_WORDS[0], day=date_words(now), place=fortune.PLACE_SAID["fiesta"])


SAMPLE = sample(now=datetime(2026, 10, 28, 21, 0))


# ---- layout ----------------------------------------------------------------------------------
class Line(NamedTuple):
    text: str                       # already printable and fitted to its columns
    font: str = "a"
    big: bool = False               # double width and height
    bold: bool = False
    align: str = "l"


class Rule(NamedTuple):
    pass


class Art(NamedTuple):
    wb: int
    rows: int
    data: bytes


class Feed(NamedTuple):
    lines: int


def columns(line: Line) -> int:
    return COLUMNS[line.font] // (2 if line.big else 1)


def _lines(text: str, codec: str, **style) -> list[Line]:
    probe = Line("", **style)
    return [Line(s, **style) for s in wrap(printable(text, codec), columns(probe))]


def _leader(label: str, value: str, codec: str) -> list[Line]:
    label, value = printable(label, codec), printable(value, codec)
    width = COLUMNS["a"]
    dots = width - len(label) - len(value) - 2
    if dots >= 3:
        return [Line(f"{label} {'.' * dots} {value}")]
    # A long wish in the visitor's words: the label alone, the value on its own right-aligned lines.
    return [Line(label)] + [Line(s, align="r") for s in wrap(value, width)]


def layout(t: Ticket, *, codec: str = CODEC, art_root: Path | str | None = None) -> list:
    """The ticket as blocks, every text line fitted to its font's columns."""
    out: list = []
    out += _lines(TITLE, codec, big=True, bold=True, align="c")
    out += _lines(SUBTITLE, codec, align="c")
    out.append(Rule())
    if t.first:
        named = f"{FOR} {t.first}"
        big = len(printable(named, codec)) <= COLUMNS["a"] // 2
        out += _lines(named, codec, big=big, bold=True, align="c")
    plate = card_art(t.deck, t.card, art_root) if t.card is not None else None
    if t.card is not None:
        if plate is not None:
            out.append(Art(*plate))
        out += _lines(f"{roman(t.card)} · {t.card_es.upper()}", codec, bold=True, align="c")
        out += _lines(t.card_meaning, codec, align="c")
    if t.first or t.card is not None:
        out.append(Rule())
    if t.body:
        for paragraph in t.body:
            out += _lines(paragraph, codec)
        out.append(Rule())
    leaders = [(LABEL_NUMBER, t.numero), (LABEL_MOON, t.luna), (LABEL_WISH, t.deseo),
               (LABEL_MAGIC, t.palabra)]
    leaders = [(k, val) for k, val in leaders if printable(val, codec)]
    for label, value in leaders:
        out += _leader(label, value, codec)
    if leaders:
        out.append(Rule())
    foot = dict(font="b", align="c")
    out += _lines(t.day, codec, **foot)
    out += _lines(t.place, codec, **foot)
    out.append(Feed(TEAR_FEED))
    return out


# ---- bytes -----------------------------------------------------------------------------------
def encode(blocks: list, *, codec: str = CODEC, codepage: int = CODEPAGE,
           band: int = BAND_ROWS) -> list[bytes]:
    """The ticket as parts: one per run of text (and rules) and one per picture band, so the
    sender can pause between bands. The first part starts with `header`."""
    parts: list[bytes] = []
    run = bytearray(header(codepage))
    mode: dict = {}

    def set_mode(key, value, cmd):
        if mode.get(key) != value:
            run.extend(cmd(value))
            mode[key] = value

    for b in blocks:
        if isinstance(b, Line):
            set_mode("align", b.align, _align)
            set_mode("font", b.font, _font)
            set_mode("big", b.big, _size)
            set_mode("bold", b.bold, _bold)
            # printable() already left only what the codec holds; "ignore" is a last guard.
            run.extend(b.text.encode(codec, "ignore") + LF)
        elif isinstance(b, Rule):
            set_mode("align", "l", _align)
            run.extend(raster(_rule_bits(), PAPER_BYTES, RULE_ROWS)[0])
        elif isinstance(b, Art):
            set_mode("align", "l", _align)
            parts.append(bytes(run))
            run = bytearray()
            parts += raster(pad(b.data, b.wb, b.rows), max(b.wb, PAPER_BYTES), b.rows, band=band)
        elif isinstance(b, Feed):
            run.extend(_feed(b.lines))
    if run:
        parts.append(bytes(run))
    return [p for p in parts if p]


# ---- the text picture ------------------------------------------------------------------------
PREVIEW_COLUMNS = COLUMNS["a"]


def preview(blocks: list) -> str:
    """The ticket as 32 columns of text: a double-size line spaced out, a rule dotted, a
    picture as a box with its size, a Font B line over 32 columns folded."""
    w = PREVIEW_COLUMNS
    out: list[str] = []
    for b in blocks:
        if isinstance(b, Line):
            texts = [" ".join(b.text)] if b.big else (wrap(b.text, w) if len(b.text) > w else [b.text])
            for s in texts:
                out.append(s.center(w).rstrip() if b.align == "c"
                           else s.rjust(w) if b.align == "r" else s)
        elif isinstance(b, Rule):
            out.append(". " * (w // 2 - 1) + ".")
        elif isinstance(b, Art):
            label = f"[ picture {b.wb * 8} x {b.rows} ]"
            out.append(label.center(w).rstrip())
    return "\n".join(out) + "\n"
