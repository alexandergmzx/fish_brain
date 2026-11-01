#!/usr/bin/env python3
"""The scripted house act through the act's own code: real clips (--tts, openai on the desktop: never
loq), typed words for the microphone, a mock link, no audio played. Shows what would be said.

    .venv/bin/python tools/house_live.py --clips DIR "Hola" "Me llamo Ana." ANSWER ANSWER ANSWER
"""
from __future__ import annotations

import argparse
import io
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--clips", type=Path, required=True)
    ap.add_argument("--tts", default="openai")
    ap.add_argument("said", nargs="+")
    args = ap.parse_args()
    from dotenv import load_dotenv
    load_dotenv()
    os.environ.update(FISH_PERSONA="hat", FISH_SHOW="script", FISH_FILLER="false", FISH_BURBLE="false")
    from fish_brain import canned
    from fish_brain.config import Config
    from fish_brain.conversation import FishConversation
    from fish_brain.serial_link import MockSerialLink
    cfg = Config()
    cfg.tts.backend = args.tts
    cfg.canned.cache_dir = args.clips
    cfg.show.state = str(args.clips / "show.json")
    args.clips.mkdir(parents=True, exist_ok=True)
    c = FishConversation(cfg, MockSerialLink(cfg.serial, stream=io.StringIO()), text_input=True, play_audio=False)
    real = c.speaker.say_sequence

    def say(names, **k):
        for n in names:
            canned.ensure_rendered(n, cfg)
            print("   hat:", cfg.canned.phrases.get(n, n))
        return real(names, **k)
    c.speaker.say_sequence = say
    for text in args.said:
        print("visitor:", text)
        c._heard_at = c._clock()
        c._finish_turn(text, {})
    print("name:", repr(c.visit.first_name), "house:", c.visit.house, "heard:", getattr(c.visit, "heard", None))
    return 0


if __name__ == "__main__":
    sys.exit(main())
