#!/usr/bin/env python3
"""Text-to-speech candidates timed on the machine that speaks: the seconds from a text to a
playable WAV, split into the render, rubberband and sox, so the hat's voice is chosen with
numbers from the board. Nothing is played.

    tools/voice_bench.py --cand jorge:backend=loq,pitch_st=-2,formants=shift,room=stone \\
                         --cand ash:backend=openai --runs 5 --keep DIR

A candidate is `name:key=value,...`, the keys being `TTSConfig` fields (numbers are read as
numbers); the shaping fields start at their defaults, not at the `.env`'s. Run it from the
repo with the `.env` there and `FISH_PERSONA` as the fish has it.

Each candidate renders every line once cold and then `--runs` times; the table gives the
cold total and the medians. `--keep DIR` saves the last WAV of each candidate and line.
"""
from __future__ import annotations

import argparse
import shutil
import statistics
import sys
import tempfile
import time
import wave
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fish_brain import tts                    # noqa: E402
from fish_brain.config import TTSConfig   # noqa: E402

LINES = {
    "short": "Espérame tantito.",
    "medium": "Se me nubló la mente. Pregúntame otra vez.",
    "vision": "Sueñas así porque tienes mucha imaginación, y guardas cosas que no le cuentas "
              "a nadie. Lo veo clarito, y no me lo tienes que confirmar.",
    "reading": "Capricornio: todo lo que subes lo cargas, y este año vas a subir con piedras "
               "ajenas. Sueñas con exámenes porque esperas que alguien te califique, Rodrigo, "
               "y nadie va a venir. Pediste dinero, y una suscripción que ya ni abres te sangra "
               "cada mes. Córtala, y camina con una moneda en el zapato izquierdo hasta la luna "
               "llena. Tu palabra mágica es Brujicanto.",
}


def parse_cand(spec: str) -> tuple[str, dict]:
    name, _, rest = spec.partition(":")
    # The shaping starts untouched whatever the .env says; a candidate states what it wants.
    kw = {"pitch_st": 0.0, "tempo": 1.0, "formants": "keep", "room": "", "openai_rate_factor": 1.0}
    for pair in filter(None, rest.split(",")):
        k, _, v = pair.partition("=")
        try:
            kw[k] = float(v)
        except ValueError:
            kw[k] = v
    return name, kw


def render(text: str, cfg: TTSConfig, out: Path) -> dict:
    """One render through the fish's own path; returns the stage seconds it recorded."""
    seen: dict = {}
    orig = tts.debug.model
    tts.debug.model = lambda kind, sent=None, **kw: seen.update(sent or {})
    try:
        t0 = time.monotonic()
        tts.synthesize(text, cfg, out)
        total = time.monotonic() - t0
    finally:
        tts.debug.model = orig
    return {"render": seen.get("render_s", total), "rubberband": seen.get("rubberband_s", 0.0),
            "sox": seen.get("sox_s", 0.0), "total": total}


def seconds(path: Path) -> float:
    with wave.open(str(path)) as w:
        return w.getnframes() / w.getframerate()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--cand", action="append", required=True)
    ap.add_argument("--runs", type=int, default=5)
    ap.add_argument("--lines", default=",".join(LINES))
    ap.add_argument("--keep", type=Path)
    a = ap.parse_args()
    try:
        from dotenv import load_dotenv            # the keys and the licence guard's settings
        load_dotenv()
    except ImportError:
        pass
    if a.keep:
        a.keep.mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkdtemp(prefix="voice_bench_"))
    print(f"{'candidate':14s} {'line':8s} {'audio':>6s} {'cold':>6s} {'render':>7s} "
          f"{'rubb.':>6s} {'sox':>6s} {'total':>6s}  (seconds; medians of {a.runs})", flush=True)
    for spec in a.cand:
        name, kw = parse_cand(spec)
        cfg = TTSConfig(**kw)
        tts.warm(cfg)
        for line in a.lines.split(","):
            out = tmp / f"{name}_{line}.wav"
            cold = render(LINES[line], cfg, out)["total"]
            runs = [render(LINES[line], cfg, out) for _ in range(a.runs)]
            med = {k: statistics.median(r[k] for r in runs) for k in runs[0]}
            print(f"{name:14s} {line:8s} {seconds(out):6.2f} {cold:6.2f} {med['render']:7.2f} "
                  f"{med['rubberband']:6.2f} {med['sox']:6.2f} {med['total']:6.2f}", flush=True)
            if a.keep:
                shutil.move(out, a.keep / out.name)
    return 0


if __name__ == "__main__":
    sys.exit(main())
