"""Entry point: build the engine and run the conversation loop.

  python -m fish_brain.app --dry-run --text   # no fish, no mic: type a turn, prints cmds
  python -m fish_brain.app --dry-run          # no fish: push-to-talk, prints cmds
  python -m fish_brain.app                      # full: real serial + mic + fish
"""
from __future__ import annotations

import argparse
import sys

from .config import load as load_config
from .conversation import FishConversation
from .serial_link import open_link


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="fish-brain", description="Conversational Billy Bass")
    parser.add_argument("--dry-run", action="store_true",
                        help="mock serial: print MOUTH/NECK/TAIL instead of driving motors")
    parser.add_argument("--text", action="store_true",
                        help="type the user turn instead of using the mic (skips STT)")
    parser.add_argument("--no-audio", action="store_true",
                        help="don't play TTS audio (silent player); still streams motion")
    parser.add_argument("--port", help="override the serial port (e.g. /dev/ttyACM0)")
    parser.add_argument("--say", help="speak one phrase and exit (skips the conversation loop)")
    parser.add_argument("--say-canned", metavar="NAME",
                        help="speak one canned phrase by name and exit")
    parser.add_argument("--list-canned", action="store_true",
                        help="list available canned phrase names and exit")
    parser.add_argument("--viz", action="store_true",
                        help="serve the on-screen fish (browser fallback/debug view)")
    parser.add_argument("--viz-port", type=int, help="port for --viz (default from config)")
    args = parser.parse_args(argv)

    # Load .env so OPENAI_API_KEY (and optional overrides) are available.
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except Exception:
        pass

    cfg = load_config()
    if args.port:
        cfg.serial.port = args.port
    if args.viz_port:
        cfg.viz.port = args.viz_port

    if args.list_canned:
        for name in cfg.canned.phrases:
            print(name)
        return 0

    # Warm the loq daemon so the first phrase isn't slow.
    if cfg.tts.warm_on_start:
        from . import tts
        tts.warm(cfg.tts)

    # Pre-render canned phrases so the first welcome/goodbye is instant.
    if cfg.canned.enabled:
        from . import canned
        canned.prerender_all(cfg)

    # On-screen fish (browser fallback/debug view), optional.
    viz = None
    if args.viz:
        from .viz import VizServer
        viz = VizServer(cfg)
        viz.start()

    try:
        try:
            link_cm = open_link(cfg.serial, dry_run=args.dry_run)
        except Exception as e:
            print(f"Could not open serial port {cfg.serial.port}: {e}\n"
                  f"Tip: use --dry-run to test without hardware, or pass --port.", file=sys.stderr)
            return 1

        with link_cm as link:
            if args.say is not None or args.say_canned is not None:
                from .conductor import make_player
                player = make_player(not args.no_audio)
                if args.say is not None:
                    from .speak import speak
                    speak(args.say, link, cfg, player=player, viz=viz)
                else:
                    from . import canned
                    canned.play(args.say_canned, link, cfg, player=player, viz=viz)
                return 0
            convo = FishConversation(cfg, link, text_input=args.text,
                                     play_audio=not args.no_audio, viz=viz)
            convo.run()
    finally:
        if viz is not None:
            viz.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
