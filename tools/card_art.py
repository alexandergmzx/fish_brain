#!/usr/bin/env python3
"""The tarot plates for the fortune's ticket: scans in, 1-bit PBM (P4) plates out.

Desktop only, once: the board never decodes an image. Pillow is imported only for reading
the scans and writing the contact sheet (`/usr/bin/python3` has it on the desktop and the
laptop); the dither is numpy.

    /usr/bin/python3 -I tools/card_art.py build SRC_DIR OUT_DIR [--width 256] [--gamma 1.4]
    /usr/bin/python3 -I tools/card_art.py sheet OUT_DIR sheet.png      # all plates, for a look
    /usr/bin/python3 -I tools/card_art.py --self-test                   # no scans, no Pillow

SRC_DIR holds NN.jpg (00 to 21, the card's number), downloaded into a folder of their own
outside the repo (run with -I: nothing in that folder is imported). Each scan is cropped to
the picture inside its own frame lines (`frame`: the English title band at the bottom goes,
the ticket prints the Spanish name in the printer's font), turned grey, stretched to the full range,
lifted by `--gamma` against the thermal head's dot gain, scaled to `--width` dots and
dithered with Atkinson (it drops a quarter of the error, so the paper stays lighter: less
heat, less battery). A P4 file's bits are GS v 0's: MSB the leftmost dot, 1 = black.

Exit code: 0 = done, 1 = a scan failed, 2 = could not run.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np

# Where a frame line is not found: about the median of the 22 scans of 2026-10-29, as
# fractions of the scan (left, top, right, bottom; the bottom is the title band's top line).
CROP = (0.045, 0.028, 0.945, 0.872)
DARK = 110           # grey below this is ink
LINE = 0.85          # a frame line: this share of its length is ink
THIN = 14            # and it is at most this many pixels thick
INSET = 6            # pixels kept clear inside a line
WIDTH = 256
GAMMA = 1.4
CARDS = 22


def atkinson(grey: np.ndarray) -> np.ndarray:
    """A float image (0 = black, 1 = white) dithered to booleans, True = black dot."""
    img = grey.astype(np.float64).copy()
    h, w = img.shape
    out = np.zeros((h, w), dtype=bool)
    for y in range(h):
        row = img[y]
        for x in range(w):
            old = row[x]
            new = 1.0 if old >= 0.5 else 0.0
            out[y, x] = new == 0.0
            err = (old - new) / 8.0
            if x + 1 < w:
                row[x + 1] += err
            if x + 2 < w:
                row[x + 2] += err
            if y + 1 < h:
                nxt = img[y + 1]
                if x > 0:
                    nxt[x - 1] += err
                nxt[x] += err
                if x + 1 < w:
                    nxt[x + 1] += err
            if y + 2 < h:
                img[y + 2, x] += err
    return out


def _runs(idx) -> list[tuple[int, int]]:
    """Consecutive indices (gaps of up to 2) as (first, last) runs."""
    out: list[list[int]] = []
    for i in idx:
        if out and i - out[-1][-1] <= 2:
            out[-1].append(i)
        else:
            out.append([i])
    return [(r[0], r[-1]) for r in out]


def frame(grey: np.ndarray) -> tuple[tuple[int, int, int, int], list[str]]:
    """The picture's box (left, top, right, bottom) inside the card's own frame lines, and the
    sides that fell back to CROP. The sides: the first full-height line from each edge. The
    top: the first thin full-width line in the top 8 % with paper above it. The bottom: the
    line that starts the title band, between 80 % and 91 % of the height (of lines close
    together, the upper)."""
    h, w = grey.shape
    ink = grey < DARK
    fell: list[str] = []
    cols = ink[h // 4:3 * h // 4].mean(axis=0)
    lefts = _runs([x for x in range(int(w * 0.12)) if cols[x] > LINE])
    rights = _runs([x for x in range(int(w * 0.88), w) if cols[x] > LINE])
    if lefts:
        left = lefts[0][0] + 8 + INSET
    else:
        left = round(CROP[0] * w)
        fell.append("left")
    if rights:
        right = rights[-1][1] - 8 - INSET
    else:
        right = round(CROP[2] * w)
        fell.append("right")
    rows = ink[:, left:right].mean(axis=1)
    lines = [(a, b) for a, b in _runs([y for y in range(h) if rows[y] > LINE]) if b - a <= THIN]
    tops = [b for a, b in lines
            if a < h * 0.08 and rows[max(0, a - 20):max(1, a - 4)].mean() < 0.2]
    if tops:
        top = tops[0] + INSET
    else:
        top = round(CROP[1] * h)
        fell.append("top")
    bottoms = [a for a, _b in lines if h * 0.80 < a < h * 0.91]
    if bottoms:
        bottom = [a for a in bottoms if bottoms[-1] - a <= 30][0] - INSET
    else:
        bottom = round(CROP[3] * h)
        fell.append("bottom")
    return (left, top, right, bottom), fell


def tone(grey: np.ndarray, gamma: float) -> np.ndarray:
    """0..255 grey to 0..1, stretched (1 % clipped each side) and lifted by `gamma`."""
    g = grey.astype(np.float64)
    lo, hi = np.percentile(g, 1), np.percentile(g, 99)
    g = np.clip((g - lo) / max(hi - lo, 1.0), 0.0, 1.0)
    return g ** (1.0 / gamma)


def p4(dots: np.ndarray, comment: str = "") -> bytes:
    """Booleans (True = black) as a binary PBM."""
    h, w = dots.shape
    head = b"P4\n" + b"".join(b"# " + line.encode("ascii", "replace") + b"\n"
                              for line in comment.splitlines() if line) + f"{w} {h}\n".encode()
    return head + np.packbits(dots, axis=1, bitorder="big").tobytes()


def read_p4(raw: bytes) -> np.ndarray:
    """The inverse of p4 (comments skipped), for the sheet and the self-test."""
    pos, fields = 2, []
    while len(fields) < 2:
        while raw[pos:pos + 1].isspace():
            pos += 1
        if raw[pos:pos + 1] == b"#":
            pos = raw.index(b"\n", pos) + 1
            continue
        start = pos
        while raw[pos:pos + 1].isdigit():
            pos += 1
        fields.append(int(raw[start:pos]))
    w, h = fields
    wb = (w + 7) // 8
    bits = np.frombuffer(raw[pos + 1:pos + 1 + wb * h], dtype=np.uint8).reshape(h, wb)
    return np.unpackbits(bits, axis=1, bitorder="big")[:, :w].astype(bool)


def _pil():
    try:
        from PIL import Image
    except ImportError:
        sys.exit("card_art needs Pillow to read the scans: run it with /usr/bin/python3 -I, "
                 "or pip install pillow in a venv of its own")
    return Image


def plate(path: Path, width: int, gamma: float) -> tuple[np.ndarray, list[str]]:
    """The plate's dots, and the sides of its crop that fell back to CROP."""
    Image = _pil()
    im = Image.open(path).convert("L")
    box, fell = frame(np.asarray(im))
    im = im.crop(box)
    rows = round(im.size[1] * width / im.size[0])
    im = im.resize((width, rows), Image.LANCZOS)
    return atkinson(tone(np.asarray(im), gamma)), fell


def cmd_build(args) -> int:
    src, out = Path(args.src), Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    bad = 0
    for n in range(CARDS):
        scan = src / f"{n:02d}.jpg"
        try:
            dots, fell = plate(scan, args.width, args.gamma)
        except Exception as e:
            print(f"FAIL {n:02d}: {type(e).__name__}: {e}")
            bad += 1
            continue
        note = (f"tarot {n:02d}, Pamela Colman Smith (public domain)\n"
                f"card_art.py frame width={args.width} gamma={args.gamma} atkinson")
        (out / f"{n:02d}.pbm").write_bytes(p4(dots, note))
        print(f"ok   {n:02d}: {dots.shape[1]} x {dots.shape[0]} dots, "
              f"{dots.shape[0] / 8:.0f} mm, black {dots.mean():.0%}"
              + (f", fell back on {', '.join(fell)}" if fell else ""))
    return 1 if bad else 0


def cmd_sheet(args) -> int:
    Image = _pil()
    plates = [read_p4((Path(args.dir) / f"{n:02d}.pbm").read_bytes()) for n in range(CARDS)
              if (Path(args.dir) / f"{n:02d}.pbm").exists()]
    if not plates:
        print("no plates")
        return 2
    cols, gap = 6, 12
    w = max(p.shape[1] for p in plates)
    h = max(p.shape[0] for p in plates)
    rows = (len(plates) + cols - 1) // cols
    sheet = Image.new("L", (cols * (w + gap) + gap, rows * (h + gap) + gap), 255)
    for i, p in enumerate(plates):
        im = Image.fromarray(np.where(p, 0, 255).astype(np.uint8))
        sheet.paste(im, (gap + (i % cols) * (w + gap), gap + (i // cols) * (h + gap)))
    sheet.save(args.png)
    print(f"sheet {args.png}: {len(plates)} plates")
    return 0


def self_test() -> int:
    ok = True

    def check(name, cond):
        nonlocal ok
        ok &= bool(cond)
        print(f"{'PASS' if cond else 'FAIL'}  {name}")

    ramp = np.tile(np.linspace(0, 1, 64), (16, 1))
    d = atkinson(ramp)
    check("black end is black", d[:, :4].all())
    check("white end is white", not d[:, -4:].any())
    check("the middle is half dots", 0.3 < d[:, 28:36].mean() < 0.7)
    card = np.full((400, 240), 230.0)                    # paper
    card[10:14, 10:230] = card[380:384, 10:230] = 0      # the frame's top and bottom
    card[10:384, 10:14] = card[10:384, 226:230] = 0      # its sides
    card[345:349, 10:230] = 0                            # the title band's top line
    card[40:300, 40:200] = 120                           # a picture
    (left, top, right, bottom), fell = frame(card)
    check("the frame is found on every side", fell == [])
    check("the crop sits inside the frame", 14 <= left < 40 and 14 <= top < 40 and 200 < right < 226)
    check("the title band is left out", 300 < bottom < 345)
    dots = np.zeros((3, 10), dtype=bool)
    dots[0, 0] = dots[2, 9] = True
    raw = p4(dots, "a comment")
    check("P4 header", raw.startswith(b"P4\n# a comment\n10 3\n"))
    check("P4 row bytes", raw.endswith(bytes([0x80, 0, 0, 0, 0, 0x40])))
    check("P4 round trip", (read_p4(raw) == dots).all())
    print("[self-test] all passed" if ok else "[self-test] FAILED")
    return 0 if ok else 1


def main(argv=None) -> int:
    if argv is None:
        argv = sys.argv[1:]
    if "--self-test" in argv:
        return self_test()
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build", help="scans to plates")
    b.add_argument("src")
    b.add_argument("out")
    b.add_argument("--width", type=int, default=WIDTH)
    b.add_argument("--gamma", type=float, default=GAMMA)
    s = sub.add_parser("sheet", help="all plates on one PNG")
    s.add_argument("dir")
    s.add_argument("png")
    args = ap.parse_args(argv)
    return cmd_build(args) if args.cmd == "build" else cmd_sheet(args)


if __name__ == "__main__":
    sys.exit(main())
