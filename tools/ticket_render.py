#!/usr/bin/env python3
"""The fortune's ticket on screen: the exact ESC/POS bytes the MP210 would get, drawn as paper.

Reads the bytes `fish_brain.ticket.encode` makes (or a file of them) and interprets the commands
the ticket uses, at the printer's 384 dots, 8 dots/mm: ESC @, FS ., ESC R, ESC t, ESC a, ESC E,
ESC M, GS !, ESC 3 / ESC 2, ESC d, ESC J, LF and GS v 0. Anything else is reported. It shows what
was sent, not what the paper does: the printer's own font is stood in for by DejaVu Sans Mono
in its 12x24 and 9x17 cells, and its line spacing (`--spacing`, dots) is an estimate until the
desk measures it.

    /usr/bin/python3 tools/ticket_render.py --sample 13             # tickets/ticket-13.png
    /usr/bin/python3 tools/ticket_render.py --all                   # one per card, and plates.png
    /usr/bin/python3 tools/ticket_render.py --sample 13 --art DIR   # plates from DIR (NN.pbm)
    /usr/bin/python3 tools/ticket_render.py --bytes ticket.bin --out x.png

The pictures go to `tickets/` at the repo root (ignored by git, left out of the board sync)
unless `--out` names a file. The plates are fish_brain/ticket_art/tarot/ unless `--art`.

Pillow is needed (`/usr/bin/python3` has it on the desktop and the laptop). Exit code: 0 =
drawn, 1 = unknown commands in the bytes, 2 = could not run.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

DOTS = 384
FONTS = {0: (12, 24), 1: (9, 17)}          # ESC M 0 = Font A, 1 = Font B (the MP210 manual)
CODECS = {0: "cp437", 2: "cp850", 19: "cp858", 16: "cp1252"}
SPACING = 30                               # dots per line (estimate until the desk)
MONO = "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf"
MONO_BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf"


class Paper:
    def __init__(self, spacing: int):
        from PIL import Image, ImageDraw, ImageFont
        self.Image, self.ImageDraw, self.ImageFont = Image, ImageDraw, ImageFont
        self.rows: list = []               # images of DOTS width, top to bottom
        self.spacing = spacing
        self.reset()
        self.line = bytearray()
        self.unknown: list[str] = []
        self._fonts: dict = {}

    def reset(self):
        self.align, self.bold, self.font, self.wmul, self.hmul = 0, False, 0, 1, 1
        self.codec = "cp437"

    def font_for(self, size: int, bold: bool):
        key = (size, bold)
        if key not in self._fonts:
            self._fonts[key] = self.ImageFont.truetype(MONO_BOLD if bold else MONO, size)
        return self._fonts[key]

    def blank(self, h: int):
        if h > 0:
            self.rows.append(self.Image.new("L", (DOTS, h), 255))

    def flush_line(self, feed: bool = True):
        """Print the buffered text as one line (LF, ESC d, ESC J)."""
        cw, ch = FONTS[self.font]
        cw, ch = cw * self.wmul, ch * self.hmul
        text = bytes(self.line).decode(self.codec, "replace")
        self.line = bytearray()
        h = max(self.spacing, ch) if (text or feed) else 0
        if not text:
            self.blank(h)
            return
        img = self.Image.new("L", (DOTS, h), 255)
        d = self.ImageDraw.Draw(img)
        width = cw * len(text)
        x = {0: 0, 1: (DOTS - width) // 2, 2: DOTS - width}[self.align]
        f = self.font_for(int(ch * 0.82), self.bold)
        for i, c in enumerate(text):
            cell = self.Image.new("L", (cw // self.wmul, ch // self.hmul), 255)
            cd = self.ImageDraw.Draw(cell)
            g = self.font_for(int(ch / self.hmul * 0.82), self.bold)
            cd.text((cw / self.wmul / 2, ch / self.hmul * 0.5), c, font=g, fill=0, anchor="mm")
            if self.wmul > 1 or self.hmul > 1:
                cell = cell.resize((cw, ch), self.Image.NEAREST)
            img.paste(cell, (max(0, x + i * cw), 0))
        del f
        self.rows.append(img)

    def raster(self, wb: int, rows: int, data: bytes):
        import numpy as np
        bits = np.unpackbits(np.frombuffer(data, dtype=np.uint8).reshape(rows, wb), axis=1)
        img = self.Image.fromarray(np.where(bits[:, :DOTS], 0, 255).astype("uint8"))
        out = self.Image.new("L", (DOTS, rows), 255)
        out.paste(img, (0, 0))
        self.rows.append(out)

    def image(self):
        h = sum(r.size[1] for r in self.rows)
        out = self.Image.new("L", (DOTS, max(h, 1)), 255)
        y = 0
        for r in self.rows:
            out.paste(r, (0, y))
            y += r.size[1]
        return out


def interpret(data: bytes, spacing: int = SPACING) -> Paper:
    p = Paper(spacing)
    i, n = 0, len(data)
    while i < n:
        b = data[i]
        if b == 0x0A:
            p.flush_line()
            i += 1
        elif b == 0x1B and i + 1 < n:
            c = data[i + 1]
            if c == 0x40:
                p.reset(); i += 2
            elif c == 0x52:
                i += 3
            elif c == 0x74:
                p.codec = CODECS.get(data[i + 2], "cp437"); i += 3
            elif c == 0x61:
                p.align = data[i + 2] % 3; i += 3
            elif c == 0x45:
                p.bold = bool(data[i + 2] & 1); i += 3
            elif c == 0x4D:
                p.font = data[i + 2] & 1; i += 3
            elif c == 0x33:
                p.spacing = data[i + 2]; i += 3
            elif c == 0x32:
                p.spacing = SPACING; i += 2
            elif c == 0x64:
                if p.line:
                    p.flush_line()
                p.blank(data[i + 2] * p.spacing); i += 3
            elif c == 0x4A:
                if p.line:
                    p.flush_line()
                p.blank(data[i + 2]); i += 3
            else:
                p.unknown.append(f"ESC {c:02X} at {i}"); i += 2
        elif b == 0x1C and i + 1 < n and data[i + 1] == 0x2E:
            i += 2
        elif b == 0x1D and i + 1 < n:
            c = data[i + 1]
            if c == 0x21:
                v = data[i + 2]
                p.wmul, p.hmul = (v >> 4) + 1, (v & 7) + 1; i += 3
            elif c == 0x76 and data[i + 2] == 0x30:
                wb = data[i + 4] | data[i + 5] << 8
                rows = data[i + 6] | data[i + 7] << 8
                p.raster(wb, rows, data[i + 8:i + 8 + wb * rows])
                i += 8 + wb * rows
            elif c == 0x72:
                i += 3                             # GS r: a status reply, nothing on paper
            else:
                p.unknown.append(f"GS {c:02X} at {i}"); i += 2
        elif b == 0x10 and i + 1 < n and data[i + 1] == 0x04:
            i += 3                                 # DLE EOT: a status reply
        else:
            p.line.append(b); i += 1
    if p.line:
        p.unknown.append("text after the last LF is never printed")
    return p


def framed(paper, scale: int):
    """The paper at `scale`, on a grey desk, with a mm ruler on the left."""
    from PIL import Image, ImageDraw
    img = paper.resize((paper.size[0] * scale, paper.size[1] * scale), Image.NEAREST)
    m = 40 * scale // 2
    out = Image.new("L", (img.size[0] + 2 * m + 30, img.size[1] + 2 * m), 200)
    out.paste(img, (m + 30, m))
    d = ImageDraw.Draw(out)
    for mm in range(0, paper.size[1] // 8 + 1):
        y = m + mm * 8 * scale
        d.line((m + 30 - (14 if mm % 10 == 0 else 7 if mm % 5 == 0 else 3), y, m + 29, y), fill=0)
        if mm % 10 == 0:
            d.text((m - 22, y - 6), f"{mm // 10}cm", fill=0)
    return out


REPO = Path(__file__).resolve().parent.parent
TICKETS = REPO / "tickets"


def draw(data: bytes, out: Path, spacing: int, scale: int) -> list[str]:
    """`data` drawn to `out`; the unknown commands it held."""
    p = interpret(data, spacing)
    img = p.image()
    framed(img, scale).save(out)
    print(f"{out.relative_to(REPO) if out.is_relative_to(REPO) else out}: {len(data)} bytes, "
          f"paper {img.size[1] / 8:.0f} mm (line spacing {spacing} dots, estimate)")
    for u in p.unknown:
        print(f"  unknown: {u}")
    return p.unknown


def sheet(art_root: Path | None, out: Path) -> None:
    """Every plate side by side, as they are on paper (1 dot = 1 pixel)."""
    from PIL import Image
    import numpy as np
    from fish_brain import ticket
    plates = [ticket.card_art("tarot", n, art_root) for n in range(22)]
    plates = [p for p in plates if p is not None]
    if not plates:
        return
    cols, gap = 6, 12
    w = max(wb * 8 for wb, _r, _d in plates)
    h = max(r for _wb, r, _d in plates)
    img = Image.new("L", (cols * (w + gap) + gap, ((len(plates) + cols - 1) // cols) * (h + gap) + gap), 255)
    for i, (wb, rows, data) in enumerate(plates):
        bits = np.unpackbits(np.frombuffer(data, dtype=np.uint8).reshape(rows, wb), axis=1)
        img.paste(Image.fromarray(np.where(bits, 0, 255).astype("uint8")),
                  (gap + (i % cols) * (w + gap), gap + (i // cols) * (h + gap)))
    img.save(out)
    print(f"{out.relative_to(REPO)}: {len(plates)} plates")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--sample", type=int, metavar="CARD", help="the --print-test ticket")
    src.add_argument("--all", action="store_true", help="one sample ticket per card, and the plates")
    src.add_argument("--bytes", help="a file of ESC/POS bytes")
    ap.add_argument("--art", help="plates folder (holds tarot/NN.pbm or NN.pbm)")
    ap.add_argument("--spacing", type=int, default=SPACING, help="dots per text line")
    ap.add_argument("--scale", type=int, default=2)
    ap.add_argument("--out", help="the picture's file (default: under tickets/)")
    args = ap.parse_args(argv)
    try:
        import PIL  # noqa: F401
    except ImportError:
        print("ticket_render needs Pillow: run it with /usr/bin/python3")
        return 2
    TICKETS.mkdir(exist_ok=True)
    if args.bytes:
        out = Path(args.out) if args.out else TICKETS / (Path(args.bytes).stem + ".png")
        return 1 if draw(Path(args.bytes).read_bytes(), out, args.spacing, args.scale) else 0
    sys.path.insert(0, str(REPO))
    from datetime import datetime
    from fish_brain import ticket
    root = None
    if args.art:
        root = Path(args.art)
        if not (root / "tarot").is_dir():          # a flat folder of NN.pbm
            import tempfile
            tmp = Path(tempfile.mkdtemp())
            (tmp / "tarot").symlink_to(root.resolve())
            root = tmp
    cards = range(22) if args.all else [args.sample]
    unknown = []
    for n in cards:
        t = ticket.sample(n, now=datetime.now())
        data = b"".join(ticket.encode(ticket.layout(t, art_root=root)))
        out = Path(args.out) if args.out and not args.all else TICKETS / f"ticket-{n:02d}.png"
        unknown += draw(data, out, args.spacing, args.scale)
    if args.all:
        sheet(root, TICKETS / "plates.png")
    return 1 if unknown else 0


if __name__ == "__main__":
    sys.exit(main())
