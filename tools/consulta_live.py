#!/usr/bin/env python3
"""La consulta end to end with nothing faked but the motors: the act's own code, the real model
(FISH_CONSULTA_PROFILE), a real voice render to WAV (--tts, openai on this desktop: never loq) and
real clips. Typed words stand in for the microphone; no audio is played. Costs a few cents.

    .venv/bin/python tools/consulta_live.py --clips DIR --out docs/results/2026-11-01-consulta-live.md
"""
from __future__ import annotations

import argparse
import io
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

SITTINGS = (
    ("his first question, his card", ["¿Debería aceptar a una mujer en mi casa y tener una relación con ella?", "La Muerte"]),
    ("a question that opens with qué", ["¿Qué piensa él sobre nuestra relación?", "El Ermitaño"]),
    ("a Thoth name", ["¿Me conviene conservar mi trabajo?", "Me salió el Arte"]),
    ("a protest, then the hat draws", ["¿Cómo?", "¿Renuncio a mi trabajo?", "Saca tú una"]),
    ("a minor card", ["¿Le hablo otra vez?", "Dos de Copas", "La Luna"]),
    ("no question", ["Mejor no."]),
)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--clips", type=Path, required=True, help="a folder for this voice's clips")
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--tts", default="openai")
    args = ap.parse_args(argv)
    from dotenv import load_dotenv
    load_dotenv()
    os.environ.setdefault("FISH_SHOW", "auto")           # as set: the board runs script + FISH_FORTUNE_MODEL
    os.environ.update(FISH_PERSONA="hat", FISH_FILLER="false", FISH_BURBLE="false")
    from fish_brain import canned, cloud, voice_guard
    from fish_brain.config import Config
    from fish_brain.conversation import FishConversation
    from fish_brain.fortune_run import FortuneInput
    from fish_brain.serial_link import MockSerialLink
    cfg = Config()
    cfg.tts.backend = args.tts
    cfg.canned.cache_dir = args.clips
    cfg.show.state = str(args.clips / "show.json")
    cfg.fortune.state = str(args.clips / "fortune.json")
    args.clips.mkdir(parents=True, exist_ok=True)
    names = [n for n in cfg.canned.phrases if "consulta" in n]
    t = time.monotonic()
    for n in names:
        canned.ensure_rendered(n, cfg)
    out = args.out.open("a", encoding="utf-8")
    out.write(f"{len(names)} clips rendered in {time.monotonic() - t:.1f} s, tts={args.tts}\n\n")
    print("online:", cloud.is_online(), "voice:", voice_guard.state(), flush=True)
    bad = 0

    def sitting(title, lines, expect="reading"):
        nonlocal bad
        c = FishConversation(cfg, MockSerialLink(cfg.serial, stream=io.StringIO()), text_input=True, play_audio=False)
        said = []
        real_say, real_perform = c.speaker.say_sequence, c.speaker.perform
        c.speaker.say_sequence = lambda n, **k: (said.append(list(n)), real_say(n, **k))[1]

        def perform(wav, text, timing, **k):
            import wave
            with wave.open(str(wav)) as w:
                said.append(f"{text} [{w.getnframes() / w.getframerate():.1f} s of audio, render {timing.get('tts', 0):.1f} s]")
            return real_perform(wav, text, timing, **k)
        c.speaker.perform = perform
        c._handle_item(FortuneInput("consulta"))
        t0 = time.monotonic()
        for line in lines:
            t0 = time.monotonic()
            c._heard_at = c._clock()
            c._finish_turn(line, {})
        last = c.fortune._last
        ok = not c.fortune.open and last.get("mode") == expect
        bad += not ok
        out.write(f"### {title}: {'PASS' if ok else 'FAIL'}\n\nSaid to it: {lines}. Last turn {time.monotonic() - t0:.1f} s. "
                  f"Result: {last}\n\n" + "\n".join(f"- {s}" for s in said) + "\n\n")
        out.flush()
        print(title, "PASS" if ok else f"FAIL {last}", flush=True)

    for title, lines in SITTINGS:
        sitting(title, lines, "sin pregunta" if title == "no question" else "reading")
    os.environ["ANTHROPIC_API_KEY"] = "wrong-" + "x" * 20        # a real 401 from the real service
    sitting("the model refuses the key", ["¿Me conviene?", "La Luna"], "failed")
    out.close()
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
