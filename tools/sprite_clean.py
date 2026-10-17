#!/usr/bin/env python3
"""Clean the cut-out of the on-screen sprites (fish_brain/web/img/hat/*.png by default).

The sprites were keyed out of a flat #91b9bc background with 1-bit alpha. That left a
one-pixel rim of the background colour around the outline, a few stray specks, and in one
file a white corner. On the page's own background all three show. This tool only ever
turns opaque pixels transparent; it never changes a colour:

  1. keep the largest opaque component (drops specks and the stray corner);
  2. clear outline pixels that touch transparency and still have the matte's colour,
     at most PASSES times;
  3. keep the largest component again.

    python tools/sprite_clean.py                 # report what would change
    python tools/sprite_clean.py --write         # rewrite the files in place

Standard library only. 8-bit RGBA, non-interlaced PNGs.
"""
from __future__ import annotations

import argparse
import struct
import sys
import zlib
from pathlib import Path

IMG_DIR = Path(__file__).resolve().parent.parent / "fish_brain" / "web" / "img" / "hat"
PASSES = 2
SIG = b"\x89PNG\r\n\x1a\n"


def read_png(path: Path) -> tuple[int, int, bytearray]:
    data = path.read_bytes()
    if data[:8] != SIG:
        raise ValueError(f"{path.name}: not a PNG")
    pos, idat, w, h = 8, b"", 0, 0
    while pos < len(data):
        n, kind = struct.unpack(">I4s", data[pos:pos + 8])
        body = data[pos + 8:pos + 8 + n]
        pos += 12 + n
        if kind == b"IHDR":
            w, h, depth, ctype, _, _, interlace = struct.unpack(">IIBBBBB", body)
            if (depth, ctype, interlace) != (8, 6, 0):
                raise ValueError(f"{path.name}: 8-bit RGBA, non-interlaced expected")
        elif kind == b"IDAT":
            idat += body
    raw = zlib.decompress(idat)
    stride, bpp = w * 4, 4
    out = bytearray(h * stride)
    prev = bytearray(stride)
    for y in range(h):
        f = raw[y * (stride + 1)]
        line = bytearray(raw[y * (stride + 1) + 1:(y + 1) * (stride + 1)])
        for i in range(stride):
            a = line[i - bpp] if i >= bpp else 0
            b = prev[i]
            c = prev[i - bpp] if i >= bpp else 0
            if f == 1:
                line[i] = (line[i] + a) & 255
            elif f == 2:
                line[i] = (line[i] + b) & 255
            elif f == 3:
                line[i] = (line[i] + (a + b) // 2) & 255
            elif f == 4:
                p = a + b - c
                pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                line[i] = (line[i] + (a if pa <= pb and pa <= pc else b if pb <= pc else c)) & 255
        out[y * stride:(y + 1) * stride] = line
        prev = line
    return w, h, out


def write_png(path: Path, w: int, h: int, px: bytearray) -> None:
    def chunk(kind: bytes, body: bytes) -> bytes:
        return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body))
    stride = w * 4
    raw = bytearray()
    prev = bytes(stride)
    for y in range(h):                       # "up" filter: these flat-colour sprites pack well
        line = bytes(px[y * stride:(y + 1) * stride])
        raw.append(2)
        raw.extend((line[i] - prev[i]) & 255 for i in range(stride))
        prev = line
    path.write_bytes(SIG + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0))
                     + chunk(b"IDAT", zlib.compress(bytes(raw), 9)) + chunk(b"IEND", b""))


def keep_largest(w: int, h: int, px: bytearray) -> int:
    """Clear every opaque 8-connected component but the largest; returns pixels cleared."""
    label = [0] * (w * h)
    sizes = [0]
    for start in range(w * h):
        if label[start] or not px[start * 4 + 3]:
            continue
        n = len(sizes)
        sizes.append(0)
        label[start] = n
        stack = [start]
        while stack:
            i = stack.pop()
            sizes[n] += 1
            x, y = i % w, i // w
            for dy in (-1, 0, 1):
                for dx in (-1, 0, 1):
                    xx, yy = x + dx, y + dy
                    if 0 <= xx < w and 0 <= yy < h:
                        j = yy * w + xx
                        if not label[j] and px[j * 4 + 3]:
                            label[j] = n
                            stack.append(j)
    if len(sizes) < 3:
        return 0
    best = max(range(1, len(sizes)), key=sizes.__getitem__)
    cleared = 0
    for i in range(w * h):
        if label[i] and label[i] != best:
            px[i * 4 + 3] = 0
            cleared += 1
    return cleared


def is_matte(r: int, g: int, b: int) -> bool:
    """The keyed-out background as it survives on an edge: light, with a teal cast."""
    return (r * 299 + g * 587 + b * 114) // 1000 >= 100 and b - r >= 12 and g - r >= 10


def erode_matte(w: int, h: int, px: bytearray) -> int:
    hit = []
    for y in range(h):
        for x in range(w):
            i = (y * w + x) * 4
            if not px[i + 3] or not is_matte(px[i], px[i + 1], px[i + 2]):
                continue
            edge = x in (0, w - 1) or y in (0, h - 1)
            if not edge:
                for dy in (-1, 0, 1):
                    for dx in (-1, 0, 1):
                        if not px[((y + dy) * w + x + dx) * 4 + 3]:
                            edge = True
            if edge:
                hit.append(i)
    for i in hit:
        px[i + 3] = 0
    return len(hit)


def clean(w: int, h: int, px: bytearray) -> tuple[int, int]:
    """Returns (pixels cleared as stray components, pixels cleared as matte rim)."""
    stray = keep_largest(w, h, px)
    rim = sum(erode_matte(w, h, px) for _ in range(PASSES))
    stray += keep_largest(w, h, px)
    return stray, rim


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("files", nargs="*", type=Path, help="default: every PNG in fish_brain/web/img/hat (the fish's in img/fish/ by path)")
    ap.add_argument("--write", action="store_true", help="rewrite the files (default: report only)")
    args = ap.parse_args()
    files = args.files or sorted(IMG_DIR.glob("*.png"))
    for f in files:
        w, h, px = read_png(f)
        before = bytes(px)
        stray, rim = clean(w, h, px)
        # The promise of this tool, checked on every file: colours untouched, alpha only 255 -> 0.
        for i in range(0, len(px), 4):
            if px[i:i + 3] != before[i:i + 3] or px[i + 3] > before[i + 3]:
                print(f"{f.name}: a pixel changed in a way this tool never does", file=sys.stderr)
                return 1
        print(f"{f.name}: {stray} stray, {rim} rim pixels cleared"
              + (" (written)" if args.write and (stray or rim) else ""))
        if args.write and (stray or rim):
            write_png(f, w, h, px)
    return 0


if __name__ == "__main__":
    sys.exit(main())
