"""Entry point: build the engine and run the conversation loop.

  python -m fish_brain.app --dry-run --text   # no fish, no mic: type a turn, prints cmds
  python -m fish_brain.app --dry-run          # no fish: push-to-talk, prints cmds
  python -m fish_brain.app                      # full: real serial + mic + fish
"""
from __future__ import annotations

import argparse
import os
import signal
import sys
import threading

from .config import load as load_config
from .conversation import FishConversation
from .serial_link import open_link


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="fish-brain", description="Conversational Billy Bass")
    parser.add_argument("--dry-run", action="store_true",
                        help="mock serial: print MOUTH/NECK/TAIL instead of driving motors")
    parser.add_argument("--text", action="store_true",
                        help="type the user turn instead of using the mic (skips STT)")
    parser.add_argument("--echo", action="store_true",
                        help="repeat back what you say (no LLM/API key); test the STT->TTS->mouth pipeline")
    parser.add_argument("--no-audio", action="store_true",
                        help="don't play TTS audio (silent player); still streams motion")
    parser.add_argument("--port", help="override the serial port (e.g. /dev/ttyACM0)")
    parser.add_argument("--say", help="speak one phrase and exit (skips the conversation loop)")
    parser.add_argument("--say-canned", metavar="NAME",
                        help="speak one canned phrase by name and exit")
    parser.add_argument("--list-canned", action="store_true",
                        help="list available canned phrase names and exit")
    parser.add_argument("--prefetch-stt", action="store_true",
                        help="download/load the faster-whisper STT model, then exit "
                             "(run once after install so the first turn isn't slow)")
    parser.add_argument("--viz", action="store_true",
                        help="serve the on-screen fish (browser fallback/debug view)")
    parser.add_argument("--viz-port", type=int, help="port for --viz (default from config)")
    parser.add_argument("--viz-host", help="address --viz listens on (0.0.0.0 = reachable "
                                           "from other devices)")
    parser.add_argument("--stt", choices=["local", "openai", "groq"],
                        help="speech-to-text backend (default: FISH_STT_BACKEND or local)")
    parser.add_argument("--tts", choices=["loq", "openai"],
                        help="text-to-speech backend (default: FISH_TTS_BACKEND or loq)")
    parser.add_argument("--llm", metavar="PROFILE",
                        help="LLM profile, e.g. groq or luna (default: FISH_LLM_PROFILE)")
    parser.add_argument("--transport", choices=["serial", "bridge"],
                        help="how commands reach the motor board (default: serial)")
    parser.add_argument("--check-link", action="store_true",
                        help="open the motor link, send STOP, report, and exit")
    parser.add_argument("--prerender-canned", action="store_true",
                        help="render every canned phrase with the current TTS backend, then exit")
    parser.add_argument("--read-badge", metavar="FILE",
                        help="read the name on a badge photo (JPEG) with the vision model, "
                             "print the result as JSON and exit (--llm / FISH_READING_PROFILE "
                             "pick the profile)")
    args = parser.parse_args(argv)

    # Load .env so OPENAI_API_KEY (and optional overrides) are available.
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except Exception:
        pass

    if args.llm:
        os.environ["FISH_LLM_PROFILE"] = args.llm      # read when the config is built
    try:
        cfg = load_config()
    except ValueError as e:
        print(e, file=sys.stderr)
        return 78
    if args.port:
        cfg.serial.port = args.port
    if args.viz_port:
        cfg.viz.port = args.viz_port
    if args.viz_host:
        cfg.viz.host = args.viz_host
    if args.stt:
        cfg.stt.backend = args.stt
    if args.tts:
        cfg.tts.backend = args.tts
    if args.transport:
        cfg.serial.transport = args.transport
    if cfg.serial.transport.strip().lower() not in ("serial", "bridge"):
        print(f"Configuration problem: unknown transport {cfg.serial.transport!r} "
              f"(FISH_SERIAL_TRANSPORT: serial or bridge)", file=sys.stderr)
        return 78
    if cfg.tts.backend not in ("loq", "openai"):
        print(f"Configuration problem: unknown TTS backend {cfg.tts.backend!r} "
              f"(FISH_TTS_BACKEND: loq or openai)", file=sys.stderr)
        return 78

    # A stop request from a service manager should end like Ctrl-C: goodbye, then STOP.
    def _on_sigterm(_signum, _frame):
        raise KeyboardInterrupt
    try:
        signal.signal(signal.SIGTERM, _on_sigterm)
    except ValueError:
        pass                                            # not the main thread

    from . import cloud
    from .config import STT_PROFILES
    cloud.configure(cfg.cloud)
    cloud_keys: set[str] = set()
    if cfg.tts.backend == "openai":
        cloud_keys.add("OPENAI_API_KEY")
    if cfg.stt.backend in STT_PROFILES and not args.text:
        cloud_keys.add(STT_PROFILES[cfg.stt.backend]["api_key_env"])
    if not args.echo:
        cloud_keys.add(cfg.llm.api_key_env)
    one_shot = (args.list_canned or args.prefetch_stt or args.check_link
                or args.read_badge is not None)
    if cloud_keys and not one_shot:
        # Know whether the internet is there without ever blocking a turn on it.
        cloud.start_probe(wait_s=3.0)

    if args.list_canned:
        for name in cfg.canned.phrases:
            print(name)
        return 0

    if args.read_badge is not None:
        # Before any voice warm-up: this never starts Loquendo or touches the motors.
        import json
        from dataclasses import asdict
        from . import reading
        try:
            data = open(args.read_badge, "rb").read()
            res = reading.read_badge(data, cfg, want_look=cfg.reading.look)
        except Exception as e:
            print(f"read-badge FAILED ({type(e).__name__}): {e}", file=sys.stderr)
            return 1
        print(json.dumps(asdict(res), ensure_ascii=False, indent=2))
        return 0

    if args.prefetch_stt:
        if cfg.stt.backend != "local":
            print(f"STT backend '{cfg.stt.backend}' runs in the cloud: nothing to fetch.")
            return 0
        from .stt import Transcriber
        print(f"Fetching STT model '{cfg.stt.model}' (first run may take a while)…", flush=True)
        Transcriber(cfg.stt).ensure_loaded()
        print("STT model ready (cached under ~/.cache/huggingface).")
        return 0

    if args.prerender_canned:
        from . import canned, tts
        tts.warm(cfg.tts)
        failed = canned.prerender_all(cfg)
        for name in cfg.canned.phrases:
            print(f"  {name}: {'FAILED' if name in failed else 'ok'}")
        return 1 if failed else 0

    if args.check_link:
        try:
            with open_link(cfg.serial, dry_run=args.dry_run) as link:
                link.all_stop()
                ok = link.attached
                # The firmware echoes every character: silence means the port opened but
                # nothing is running behind it. None = this kind of link cannot tell.
                answered = link.wait_reply(1.0) if ok else None
                if answered is False:
                    print(f"link open, MCU SILENT: {link.describe()}")
                    return 1
                print(f"link {'ok' if ok else 'NOT ATTACHED'}: {link.describe()}"
                      + (", MCU answered" if answered else ""))
            return 0 if ok else 1
        except Exception as e:
            print(f"link FAILED ({cfg.serial.transport} {cfg.serial.port}): {e}", file=sys.stderr)
            return 1

    missing = cloud.missing_keys(cloud_keys)
    if missing:
        # Keep going: the fish says its "no signal" line instead of restarting in a loop.
        print(f"[cloud] WARNING: {', '.join(missing)} not set; the stages that need it will fail",
              file=sys.stderr, flush=True)

    # Warm the loq daemon so the first phrase isn't slow (does nothing for other backends).
    if cfg.tts.warm_on_start:
        from . import tts
        tts.warm(cfg.tts)

    # Pre-render canned phrases so the first welcome/goodbye is instant. With a cloud voice
    # this must not hold up listening: the welcome falls back to an older rendering meanwhile.
    if cfg.canned.enabled:
        from . import canned
        if cfg.tts.backend == "loq":
            canned.prerender_all(cfg)
        else:
            threading.Thread(target=canned.prerender_all, args=(cfg,), name="prerender",
                             daemon=True).start()

    # Voice mode needs some way to say "talk now". Without a screen or a terminal that is
    # the browser button or a remote; say so instead of failing on every turn.
    conversing = args.say is None and args.say_canned is None
    if (conversing and not args.text and not args.viz and not cfg.ptt.evdev_device
            and not os.environ.get("DISPLAY") and not os.environ.get("WAYLAND_DISPLAY")
            and not sys.stdin.isatty()):
        print("No push-to-talk input: no terminal, no display, no --viz and FISH_PTT_DEVICE "
              "is unset. Add --viz or set FISH_PTT_DEVICE.", file=sys.stderr)
        return 78                                       # EX_CONFIG: restarting won't help

    # On-screen fish (browser fallback/debug view), optional.
    viz = None
    if args.viz:
        from .viz import CertificateError, VizServer
        viz = VizServer(cfg)
        try:
            viz.start()
        except CertificateError as e:   # a set-up error: a restart would not fix it
            print(f"Configuration problem: the page could not start: {e}", file=sys.stderr)
            return 78
        # Any other OSError (a busy port after a quick restart) propagates: the unit retries.

    try:
        try:
            link_cm = open_link(cfg.serial, dry_run=args.dry_run)
        except Exception as e:
            print(f"Could not open the motor link ({cfg.serial.transport} {cfg.serial.port}): "
                  f"{e}\nTip: use --dry-run to test without hardware, pass --port, or set "
                  f"FISH_SERIAL_REQUIRED=false to talk without motors.", file=sys.stderr)
            return 1

        with link_cm as link:
            if args.say is not None or args.say_canned is not None:
                from .conductor import make_player
                player = make_player(not args.no_audio, cfg.ptt.speaker)
                if args.say is not None:
                    from .speak import speak
                    try:
                        speak(args.say, link, cfg, player=player, viz=viz)
                    except RuntimeError as e:      # TTS or cloud problem: say why, no traceback
                        print(f"Could not speak: {e}", file=sys.stderr)
                        return 1
                else:
                    from . import canned
                    canned.play(args.say_canned, link, cfg, player=player, viz=viz)
                return 0
            try:
                convo = FishConversation(cfg, link, text_input=args.text,
                                         play_audio=not args.no_audio, viz=viz, echo=args.echo)
                if not args.text:
                    from .stt import make_transcriber
                    make_transcriber(cfg.stt)       # a wrong backend name is a setup error
            except (ValueError, RuntimeError) as e:
                print(f"Configuration problem: {e}", file=sys.stderr)
                return 78
            if viz is not None:
                viz.register_speaker(convo.speaker)   # let the on-screen text box drive the fish
                from . import reading
                viz.register_reader(                  # a badge photo from the console (/badge)
                    lambda data, look: reading.read_badge(data, cfg, want_look=look))
            stt = "-" if args.text else cfg.stt.backend
            llm = "echo" if args.echo else f"{cfg.llm.profile}:{cfg.llm.model}"
            if viz is not None:
                viz.register_status(lambda: {
                    "link": {"desc": link.describe(), "health": link.health()},
                    "online": cloud.is_online(),
                    "backends": {"stt": stt, "llm": llm, "tts": cfg.tts.backend,
                                 "ptt": convo.ptt_summary()}})
            print(f"[fish] link={link.describe()} stt={stt} llm={llm} tts={cfg.tts.backend} "
                  f"ptt={convo.ptt_summary()}", flush=True)
            from .ptt import PTTUnavailable
            try:
                convo.run()
            except PTTUnavailable as e:
                print(f"No push-to-talk input: {e}", file=sys.stderr)
                return 78
    finally:
        if viz is not None:
            viz.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
