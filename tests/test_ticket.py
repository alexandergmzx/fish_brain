"""ticket.py: the fortune's ticket is the act's own data on 32 columns, its bytes are exact
ESC/POS, nothing the model or a visitor typed reaches the printer as a command, and a plate
is a picture only when its file is good."""
import dataclasses
import random
import subprocess
import sys
from datetime import datetime
from types import SimpleNamespace

import pytest

from fish_brain import fortune, fortune_bank as fb, ticket as tk
from fish_brain.fortune_run import FortuneRun

TAROT = fortune.DECKS["tarot"]
P = fb.FORTUNE_PHRASES
NOW = datetime(2026, 10, 28, 21, 30)


def act(**over) -> dict:
    """FortuneRun.v at the closing line of a clips act that heard everything."""
    v = {"n": 37, "first": "Mónica", "deck": TAROT, "place": "fiesta", "reading": None,
         "magic": "fortune_magic_1", "clips": [],
         "data": {"signo": "escorpio", "numero": 6, "carta": 13, "deseo": "amor",
                  "luna": "llena", "palabra": "Zumbalí"}}
    v.update(over)
    return v


def made(v, *, place=None, now=NOW) -> tk.Ticket:
    return tk.ticket_of(v, FortuneRun._said_data(v), phrases=P, place=place, now=now)


@pytest.fixture
def no_art(tmp_path):
    return tmp_path / "none"


def text_of(blocks) -> list[str]:
    return [b.text for b in blocks if isinstance(b, tk.Line)]


# ---- bytes -----------------------------------------------------------------------------------
def test_every_ticket_starts_with_init_chinese_off_usa_and_the_code_page():
    assert tk.header() == bytes.fromhex("1b 40 1c 2e 1b 52 00 1b 74") + bytes((tk.CODEPAGE,))
    assert tk.encode(tk.layout(tk.SAMPLE))[0].startswith(tk.header())


def test_an_8_by_2_image_is_one_exact_gs_v_0():
    assert tk.raster(b"\xff\x81", 1, 2) == [bytes.fromhex("1d 76 30 00 01 00 02 00 ff 81")]


def test_a_tall_image_goes_in_bands_with_their_own_headers():
    data = bytes(range(48)) * 50
    parts = tk.raster(data, 48, 50, band=24)
    assert [p[:8] for p in parts] == [bytes.fromhex("1d 76 30 00 30 00 18 00")] * 2 + [
        bytes.fromhex("1d 76 30 00 30 00 02 00")]
    assert b"".join(p[8:] for p in parts) == data
    assert len(tk.raster(data, 48, 50, band=256)) == 1


def test_a_narrow_picture_is_centred_in_white():
    assert tk.pad(b"\xaa\xbb", 2, 1, to=6) == b"\x00\x00\xaa\xbb\x00\x00"
    assert len(tk.pad(bytes(32 * 3), 32, 3)) == 48 * 3


def test_the_modes_change_only_when_a_line_needs_it():
    blocks = [tk.Line("uno", bold=True), tk.Line("dos", bold=True), tk.Line("tres")]
    run = tk.encode(blocks)[0][len(tk.header()):]
    assert run == (bytes.fromhex("1b 61 00 1b 4d 00 1d 21 00 1b 45 01") + b"uno\ndos\n"
                   + bytes.fromhex("1b 45 00") + b"tres\n")


# ---- text ------------------------------------------------------------------------------------
def test_printable_drops_controls_markdown_and_emoji_and_maps_what_the_page_lacks():
    assert tk.printable("¿ Hola…  **ojo** 😀\x1b@\x07 Łódź​ , ya ¡") == "¿Hola... ojo @ Lódz, ya"
    assert tk.printable("“sí” — ‘no’", "cp858") == "\"sí\" - 'no'"
    assert tk.printable("“sí” — …", "cp1252") == "“sí” — …"           # the page has them
    assert tk.printable(None) == "" and tk.printable("\x00\x1b\x9b") == ""
    assert tk.printable("ñandú\tÁÉÍÓÚ\nüÜ ¿¡") == "ñandú ÁÉÍÓÚ üÜ"


def test_fuzzed_text_never_puts_a_control_byte_on_the_paper():
    rng = random.Random(7)
    alphabet = [chr(c) for c in range(0, 0x250)] + list("…“”‘’–—😀🎃​ ﻿漢字¿¡*_#`")
    for _ in range(300):
        s = "".join(rng.choice(alphabet) for _ in range(rng.randint(0, 120)))
        out = tk.printable(s).encode(tk.CODEC)
        assert all(b >= 0x20 and b != 0x7F for b in out), s
        blocks = tk.layout(made(act(reading=s, first=s[:20])))
        for line in text_of(blocks):
            assert all(b >= 0x20 and b != 0x7F for b in line.encode(tk.CODEC)), line
        parts = tk.encode(blocks)
        assert parts[0].count(b"\x1b@") == 1 and all(b"\x1b@" not in p for p in parts[1:])


def test_no_line_runs_over_its_columns_or_ends_in_an_opening_mark():
    rng = random.Random(3)
    words = ["¿qué", "¡ay!", "sí,", "calavera", "Cempacuá", "otro-día-más", "…", "ya ."]
    for long_word in ("", "x" * 40):
        for _ in range(100):
            reading = "calavera " + " ".join(rng.choice(words + [long_word]) for _ in range(rng.randint(1, 89)))
            for b in tk.layout(made(act(reading=reading, first="Ana Lucía Fernanda Z"))):
                if isinstance(b, tk.Line):
                    assert 0 < len(b.text) <= tk.columns(b), b
                    assert not b.text.endswith(("¿", "¡")), b
                    # A word longer than the line is cut where it must; anything else breaks at a space.
                    assert long_word or not b.text.startswith((",", ".", "?", "!")), b


def test_every_text_that_reaches_the_ticket_prints_as_written():
    texts = [*fb.NUMBER_LINES.values(), *fb.MOON_LINES.values(), *fb.POOLS["magic"],
             *(t.label.lower() for t in fortune.WISHES), *fortune.MOON_SAID.values(), *fortune.PLACE_SAID.values(),
             *fortune.MAGIC_WORDS, *tk.LABELS]
    for c in TAROT["cards"]:
        texts += [c.es, c.es.upper(), c.meaning, f"{tk.roman(c.n)} · {c.es.upper()}"]
    for s in fortune.SIGNS:
        texts.append(s.name)
    for text in texts:
        assert tk.printable(text) == text, text
        text.encode(tk.CODEC)
    # The rest of the bank lacks only the ellipsis on this page.
    for name, text in P.items():
        assert tk.printable(text) == " ".join(text.replace("…", "...").split()), name


def test_roman_numerals():
    assert [tk.roman(n) for n in (0, 1, 4, 9, 13, 14, 18, 19, 21)] == [
        "0", "I", "IV", "IX", "XIII", "XIV", "XVIII", "XIX", "XXI"]


# ---- the act's data on the ticket ------------------------------------------------------------
def test_a_clips_act_prints_the_number_the_moon_and_the_word_it_said():
    t = made(act())
    assert t.body == (fb.NUMBER_LINES[6], fb.MOON_LINES["llena"], fb.POOLS["magic"][0])
    assert (t.n, t.first, t.deck, t.card, t.card_es, t.card_meaning) == (
        37, "Mónica", "tarot", 13, "La Muerte", "algo viejo se va")
    assert (t.numero, t.luna, t.deseo, t.palabra) == ("6", "llena", "amor", "Zumbalí")
    assert (t.day, t.place) == ("28 de octubre de 2026", "en una fiesta")
    with pytest.raises(dataclasses.FrozenInstanceError):
        t.n = 1


def test_a_model_act_prints_its_reading_and_the_leaders():
    reading = "Escorpio de agua, la Muerte te sonríe: algo viejo se va esta noche."
    t = made(act(reading=reading))
    assert t.body == (reading,)
    lines = text_of(tk.layout(t))
    assert "Número de la suerte .......... 6" in lines and "Palabra mágica ......... Zumbalí" in lines


def test_end_at_the_second_question_prints_what_there_is():
    v = act(magic="fortune_magic_9", data={"signo": "leo", "luna": "nueva", "palabra": "Sombrambrú"})
    t = made(v)
    assert t.body == (P["fortune_luna_nueva"], P["fortune_magic_9"])
    assert t.card is None and t.deck == "" and t.numero == "" and t.deseo == ""
    blocks = tk.layout(t)
    assert not any(isinstance(b, tk.Art) for b in blocks)
    lines = text_of(blocks)
    assert tk.CREDIT not in lines and not any("·" in s for s in lines)
    assert [s.split(" ")[0] for s in lines if " .." in s] == ["Luna", "Palabra"]


def test_no_card_drawn_or_the_deck_off_means_no_caption():
    for v in (act(data={"carta": None}), act(deck=None)):
        t = made(v)
        assert t.card is None and t.card_es == ""
        assert not any("MUERTE" in s for s in text_of(tk.layout(t)))


def test_no_name_no_para_line_and_a_long_name_is_not_doubled():
    assert not any(s.startswith("para") or s.startswith("p a r a") for s in text_of(tk.layout(made(act(first="")))))
    big = [b for b in tk.layout(made(act(first="Ana Lucía Fernanda Z"))) if isinstance(b, tk.Line)
           and "Fernanda" in b.text]
    assert big and not big[0].big and big[0].bold
    named = [b for b in tk.layout(made(act())) if isinstance(b, tk.Line) and "Mónica" in b.text]
    assert named[0].big and named[0].text == "para Mónica"


def test_an_unset_clock_prints_no_date():
    t = made(act(), now=datetime(1970, 1, 1, 0, 5))
    assert t.day == "" and t.place == "en una fiesta"
    assert tk.date_words(None) == ""
    assert not any("1970" in s or "enero" in s for s in text_of(tk.layout(t)))


def test_the_place_is_the_said_one_or_the_operators_text():
    other = SimpleNamespace(place="otro", text="la casa de \x1b[Lupita];")
    assert made(act(place="otro"), place=other).place == "la casa de Lupita"
    assert tk.place_said("otro", SimpleNamespace(place="otro", text="")) == ""
    assert tk.place_said("casa") == "en casa, con la familia" and tk.place_said(None) == ""


def test_a_long_wish_in_the_visitors_words_goes_right_aligned_under_its_label():
    phrase = "que mis alumnos por fin lean algo"
    t = made(act(data={**act()["data"], "deseo": "otro", "deseo_txt": phrase}))
    assert t.deseo == phrase
    blocks = [b for b in tk.layout(t) if isinstance(b, tk.Line)]
    i = [b.text for b in blocks].index("Pediste")
    assert blocks[i + 1].align == "r" and " ".join(b.text for b in blocks[i + 1:i + 3]) == phrase


def test_a_card_the_hat_drew_reversed_says_so_and_drops_the_upright_meaning():
    t = made(act(data={**act()["data"], "carta_de": "sombrero", "carta_reves": True}))
    assert (t.card, t.card_es, t.card_meaning) == (13, "La Muerte, de cabeza", "")
    lines = text_of(tk.layout(t))
    assert "XIII · LA MUERTE, DE CABEZA" in lines and "algo viejo se va" not in lines
    upright = made(act(data={**act()["data"], "carta_de": "sombrero"}))
    assert (upright.card_es, upright.card_meaning) == ("La Muerte", "algo viejo se va")


def test_a_ninety_word_reading_with_emoji_and_controls_is_clean_and_wrapped():
    words = ("La luna 🌕 llena te mira\x1b@ y la **Muerte** sonríe\x07 …").split()
    reading = " ".join((words * 12)[:90])
    lines = text_of(tk.layout(made(act(reading=reading))))
    body = tk.wrap(tk.printable(reading), 32)
    i = lines.index(body[0])
    assert lines[i:i + len(body)] == body and lines[i + len(body):i + len(body) + 1] == [
        "Número de la suerte .......... 6"]
    joined = " ".join(body)
    assert "🌕" not in joined and "\x1b" not in joined and "*" not in joined and "\x07" not in joined
    assert "Muerte sonríe..." in joined and "mira@ y" in joined
    assert len(body) <= 26


# ---- the plates ------------------------------------------------------------------------------
def pbm(path, width, rows, data, comment=b"# Death, 1909 plate, test pattern\n"):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"P4\n" + comment + f"{width} {rows}\n".encode() + data)
    return path


def test_a_plate_prints_as_a_centred_picture_with_its_credit(tmp_path):
    tk.read_pbm.cache_clear()
    pbm(tmp_path / "tarot" / "13.pbm", 16, 3, b"\xff\xff\x80\x01\xff\xff")
    blocks = tk.layout(made(act()), art_root=tmp_path)
    art = [b for b in blocks if isinstance(b, tk.Art)]
    assert art == [tk.Art(2, 3, b"\xff\xff\x80\x01\xff\xff")]
    assert tk.CREDIT in text_of(blocks)
    parts = tk.encode(blocks)
    band = [p for p in parts if p.startswith(b"\x1d\x76\x30\x00\x30\x00\x03\x00")]
    assert band == [bytes.fromhex("1d 76 30 00 30 00 03 00") + tk.pad(art[0].data, 2, 3)]
    assert "[ picture 16 x 3 ]" in tk.preview(blocks)


def test_the_pad_bits_of_an_odd_width_are_cleared(tmp_path):
    tk.read_pbm.cache_clear()
    path = pbm(tmp_path / "tarot" / "00.pbm", 12, 2, b"\xff\xff\xff\xff")
    assert tk.read_pbm(str(path)) == (2, 2, b"\xff\xf0\xff\xf0")
    assert tk.card_art("tarot", 0, tmp_path) == (2, 2, b"\xff\xf0\xff\xf0")


@pytest.mark.parametrize("raw", [
    b"P1\n8 1\n1 0 1 0 1 0 1 0\n",            # ASCII PBM
    b"P4\n8 4\n\xff\xff",                      # short data
    b"P4\n392 1\n" + bytes(49),                # wider than the paper
    b"P4\n8 0\n",                              # no rows
    b"P4\n# only a comment",                   # no size
    b"",
])
def test_a_bad_plate_is_no_picture_never_an_error(tmp_path, raw):
    tk.read_pbm.cache_clear()
    (tmp_path / "tarot").mkdir()
    (tmp_path / "tarot" / "13.pbm").write_bytes(raw)
    assert tk.card_art("tarot", 13, tmp_path) is None
    blocks = tk.layout(made(act()), art_root=tmp_path)
    assert not any(isinstance(b, tk.Art) for b in blocks) and tk.CREDIT not in text_of(blocks)
    assert "XIII · LA MUERTE" in text_of(blocks)


def test_a_missing_plate_or_a_strange_deck_is_no_picture(tmp_path):
    assert tk.card_art("tarot", 5, tmp_path) is None
    assert tk.card_art("../tarot", 5, tmp_path) is None and tk.card_art("", 5, tmp_path) is None


def test_importing_the_ticket_loads_no_socket_and_no_pillow():
    code = ("import sys, fish_brain.ticket; "
            "sys.exit(1 if {'socket', 'PIL'} & set(sys.modules) else 0)")
    assert subprocess.run([sys.executable, "-c", code]).returncode == 0


# ---- the sample, as text ---------------------------------------------------------------------
GOLDEN = """\
  L A   A D I V I N A C I Ó N
   del Sombrero Seleccionador
. . . . . . . . . . . . . . . .
     p a r a   P r u e b a
        XIII · LA MUERTE
        algo viejo se va
. . . . . . . . . . . . . . . .
Tu número de la suerte es el
seis: el que se columpia entre
lo que fue y lo que viene. Esta
noche cae del lado bueno.
Y esta noche hay luna llena, la
de los lobos y los gatos negros,
la que destapa secretos. Cuida
el tuyo, y prepárate para que te
cuenten uno.
Y tu palabra mágica de esta
noche es Zumbalí. Dila bajito
antes de dormir, y lo que
soñaste vuelve con final feliz.
. . . . . . . . . . . . . . . .
Número de la suerte .......... 6
Luna ..................... llena
Pediste ................... amor
Palabra mágica ......... Zumbalí
. . . . . . . . . . . . . . . .
           Folio 0000
     28 de octubre de 2026
         en una fiesta
"""


def test_the_sample_preview_is_golden(no_art):
    assert tk.preview(tk.layout(tk.SAMPLE, art_root=no_art)) == GOLDEN
    assert all(len(s) <= tk.PREVIEW_COLUMNS for s in GOLDEN.splitlines())


def test_the_sample_takes_any_card_and_tells_no_date_without_a_clock():
    t = tk.sample(0)
    assert (t.card, t.card_es, t.first, t.day) == (0, "El Loco", "Prueba", "")
    assert "0 · EL LOCO" in text_of(tk.layout(t))
