"""One calaverita through the act's real code path and real model, with a stand-in speaker and
printer: no voice, no paper, no motors. Prints the verse, the record's model and the 32-column ticket.
    .venv/bin/python tools/calaverita_once.py [house] [name] [answer ...]"""
from __future__ import annotations

import io
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


class Speaker:
    last_timing: dict = {}

    def say_sequence(self, names, *, wait_s=5.0, at=None):
        if at is not None and at[0] in names:
            at[1]()
        return True

    def synthesize(self, text, timing):
        timing["tts"] = 0.0
        return "/nonexistent/verse.wav"

    def perform(self, wav, text, timing):
        return True


class Printer:
    def probe(self):
        pass

    def submit(self, t):
        from fish_brain import ticket
        print(ticket.preview(ticket.layout(t)))
        return True


def main() -> int:
    from dotenv import load_dotenv
    load_dotenv()
    os.environ.update(FISH_PERSONA="hat", FISH_SHOW="auto", FISH_LLM_PROFILE="claude")
    from fish_brain.config import Config
    from fish_brain.conversation import FishConversation
    from fish_brain.fortune_run import FortuneInput
    from fish_brain.serial_link import MockSerialLink
    args = sys.argv[1:]
    house = args[0] if args else "Slytherin"
    with tempfile.TemporaryDirectory() as tmp:
        cfg = Config()
        cfg.canned.cache_dir = Path(tmp) / "canned"
        cfg.canned.cache_dir.mkdir()
        cfg.show.state = f"{tmp}/show.json"
        cfg.fortune.state = f"{tmp}/fortune.json"
        for name in cfg.canned.phrases:
            if name.startswith("calaverita_"):
                (cfg.canned.cache_dir / f"{name}-t.wav").touch()
        c = FishConversation(cfg, MockSerialLink(cfg.serial, stream=io.StringIO()), text_input=True,
                             play_audio=False, printer=Printer())
        c.speaker = Speaker()
        c.visit.start(args[1] if len(args) > 1 else "Rodrigo")
        for said in args[2:] or ["La estudio primero", "Un negocio con un amigo"]:
            c.visit.hear(said)
        c.visit.delivered(house)
        c.fortune.mode_now = lambda: ("llm", "forced")
        c._handle_item(FortuneInput("calaverita", ""))
        print("verse from:", c.fortune.calaverita._own_llms[0].cfg.model if c.fortune.calaverita._own_llms else "clips")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
