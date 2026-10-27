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


class _DeafTranscriber:
    """Hears nothing (the show's stand-in when speech-to-text cannot start)."""

    def transcribe(self, path) -> str:
        return ""

    def ensure_loaded(self) -> None:
        pass


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
    parser.add_argument("--stt", choices=["local", "canary", "openai", "groq"],
                        help="speech-to-text backend (default: FISH_STT_BACKEND or local)")
    parser.add_argument("--tts", choices=["loq", "openai"],
                        help="text-to-speech backend (default: FISH_TTS_BACKEND or loq)")
    parser.add_argument("--llm", metavar="PROFILE",
                        help="LLM profile: groq, luna, claude or claude-sonnet (default: FISH_LLM_PROFILE)")
    parser.add_argument("--transport", choices=["serial", "bridge"],
                        help="how commands reach the motor board (default: serial)")
    parser.add_argument("--check-link", action="store_true",
                        help="open the motor link, send STOP, report, and exit")
    parser.add_argument("--prerender-canned", action="store_true",
                        help="render every canned phrase with the current TTS backend, then exit")
    parser.add_argument("--read-badge", metavar="FILE",
                        help="read the name on a badge photo (JPEG) with the vision model, "
                             "print the result as JSON and exit (FISH_READING_PROFILE picks the "
                             "profiles; empty: claude if it has a key, then --llm)")
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
    for problem in cfg.mouth.problems():
        print(f"Configuration problem: {problem}", file=sys.stderr)
        return 78
    if cfg.tts.backend not in ("loq", "openai"):
        print(f"Configuration problem: unknown TTS backend {cfg.tts.backend!r} "
              f"(FISH_TTS_BACKEND: loq or openai)", file=sys.stderr)
        return 78
    cfg.ptt.capture = cfg.ptt.capture.strip().lower()
    if cfg.ptt.capture not in ("host", "browser", "auto"):
        print(f"Configuration problem: unknown microphone capture {cfg.ptt.capture!r} "
              f"(FISH_MIC_CAPTURE: host, browser or auto)", file=sys.stderr)
        return 78
    # A stop request from a service manager should end like Ctrl-C: goodbye, then STOP.
    def _on_sigterm(_signum, _frame):
        raise KeyboardInterrupt
    try:
        signal.signal(signal.SIGTERM, _on_sigterm)
    except ValueError:
        pass                                            # not the main thread
    # If the main thread is stuck in a C call when the stop signal comes, STOP still goes out.
    from . import record, shutdown, voice_guard
    shutdown.install(cfg.serial.stop_grace_s)
    if record.open_record(cfg.record) is not None:
        from . import debug_state
        record.write("start", {"argv": sys.argv[1:], "version": debug_state.version(),
                               "persona": os.environ.get("FISH_PERSONA", ""),
                               "stt": cfg.stt.backend, "llm": cfg.llm.profile,
                               "tts": cfg.tts.backend, "link": cfg.serial.port})

    # The debug hub (docs/debug.md), before anything else prints: the /debug page shows the
    # start-up lines too. Never in the way: a fault here must not stop the fish from starting.
    hub = None
    if args.viz:
        try:
            from . import debug
            hub = debug.install(cfg)
            hub.args = args
        except Exception as e:
            print(f"[viz] no debug view: {type(e).__name__}", file=sys.stderr)

    from . import cloud
    from .config import STT_PROFILES
    cloud.configure(cfg.cloud)
    cloud_keys: set[str] = set()
    if cfg.tts.backend == "openai":
        cloud_keys.add("OPENAI_API_KEY")
    if cfg.stt.backend in STT_PROFILES and not args.text:
        cloud_keys.add(STT_PROFILES[cfg.stt.backend]["api_key_env"])
    if cfg.stt.backend == "canary" and not args.text:
        # The services it asks first and those its long recordings go to (an unknown name
        # is reported further down).
        cloud_keys.update(STT_PROFILES[name]["api_key_env"]
                          for name in (*cfg.stt.online_first, *cfg.stt.long_online)
                          if name in STT_PROFILES)
    if not args.echo:
        cloud_keys.add(cfg.llm.api_key_env)
    one_shot = (args.list_canned or args.prefetch_stt or args.check_link
                or args.read_badge is not None)
    if (cloud_keys or args.viz) and not one_shot:
        # Know whether the internet is there without ever blocking a turn on it. With the
        # page up, a switch on /debug can bring a cloud stage in later.
        cloud.start_probe(wait_s=3.0 if cloud_keys else 0.0)

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
        from .config import STT_PROFILES
        from .stt import make_transcriber
        if cfg.stt.backend in STT_PROFILES:
            print(f"STT backend '{cfg.stt.backend}' runs in the cloud: nothing to fetch.")
            return 0
        try:
            transcriber = make_transcriber(cfg.stt)
        except (ValueError, RuntimeError) as e:
            print(f"Configuration problem: {e}", file=sys.stderr)
            return 78
        what = cfg.stt.model_dir if cfg.stt.backend == "canary" else cfg.stt.model
        print(f"Loading STT model '{what}' (first run may take a while)…", flush=True)
        transcriber.ensure_loaded()
        print("STT model ready.")
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

    # Voice mode needs some way to say "talk now". Without a screen or a terminal that is
    # the browser button or a remote; say so instead of failing on every turn.
    conversing = args.say is None and args.say_canned is None
    if (conversing and not args.text and not args.viz and not cfg.ptt.evdev_device
            and not os.environ.get("DISPLAY") and not os.environ.get("WAYLAND_DISPLAY")
            and not sys.stdin.isatty()):
        print("No push-to-talk input: no terminal, no display, no --viz and FISH_PTT_DEVICE "
              "is unset. Add --viz or set FISH_PTT_DEVICE.", file=sys.stderr)
        return 78                                       # EX_CONFIG: restarting won't help
    # The one-shots and typed turns need no microphone; a voice conversation in browser
    # mode needs the page, or nothing could upload a recording.
    if conversing and not args.text and not args.viz and cfg.ptt.capture == "browser":
        print("Configuration problem: FISH_MIC_CAPTURE=browser needs --viz (the page records "
              "and uploads; without it nothing could)", file=sys.stderr)
        return 78

    # On-screen fish (browser fallback/debug view), optional.
    viz = None
    if args.viz:
        from .viz import VizServer
        viz = VizServer(cfg)
        if hub is not None:
            viz.register_debug(hub)
            hub.attach(viz=viz)
        # A bad certificate leaves the page on http (viz.tls_error). An OSError (a busy port
        # after a quick restart) propagates: the unit retries.
        viz.start()

    try:
        # Warm the loq daemon so the first phrase isn't slow (does nothing for other backends),
        # with the licence probe. After the page: a slow or recovering voice must not leave
        # the phone with nothing to open.
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

        try:
            link_cm = open_link(cfg.serial, dry_run=args.dry_run)
        except Exception as e:
            print(f"Could not open the motor link ({cfg.serial.transport} {cfg.serial.port}): "
                  f"{e}\nTip: use --dry-run to test without hardware, pass --port, or set "
                  f"FISH_SERIAL_REQUIRED=false to talk without motors.", file=sys.stderr)
            return 1

        with link_cm as link:
            shutdown.arm(link)
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
                    try:
                        _ = convo.stt               # a wrong backend or model is a setup error
                    except (ValueError, RuntimeError) as e:
                        if convo.show is None:
                            raise
                        # The show must go on: the script and the page's buttons run the
                        # visit, every answer counts as not heard (ADR 0015).
                        print(f"[show] speech-to-text unavailable ({e}): visits by the "
                              "page's buttons only", file=sys.stderr, flush=True)
                        convo._stt = _DeafTranscriber()
                    convo.warm_stt()                # so the first turn does not pay the load
            except (ValueError, RuntimeError) as e:
                print(f"Configuration problem: {e}", file=sys.stderr)
                return 78
            from . import hw
            hw.apply(cfg, convo, link)              # what he marked failed stays so after a restart
            if viz is not None:
                viz.register_speaker(convo.speaker)   # let the on-screen text box drive the fish
                from . import reading
                viz.register_reader(                  # a badge photo from the console (/badge)
                    lambda data, look: reading.read_badge(data, cfg, want_look=look))
                if convo.visit is not None:           # the hat's visit: /visit, /cues
                    viz.register_visit(convo.visit)
                if convo.fortune is not None:         # the fortune act: /fortune
                    viz.register_fortune(convo.fortune)
                if hub is not None:
                    try:
                        from .debug_actions import DebugActions
                        hub.attach(link=link, convo=convo,
                                   actions=DebugActions(cfg, link, convo, viz, hub))
                    except Exception as e:
                        print(f"[viz] debug view without actions: {type(e).__name__}",
                              file=sys.stderr)
            stt = "-" if args.text else cfg.stt.backend
            if stt == "canary" and (cfg.stt.online_first or cfg.stt.long_online):
                # online first, then canary, then where the long ones go
                stt = ">".join([*cfg.stt.online_first, "canary", *cfg.stt.long_online])
            llm = "echo" if args.echo else f"{cfg.llm.profile}:{cfg.llm.model}"
            if viz is not None:
                # Read when asked, not fixed here: the debug page's switches change them.
                viz.register_status(lambda: {
                    "link": {"desc": link.describe(), "health": link.health()},
                    "online": cloud.is_online(),
                    "voice": voice_guard.view(),
                    "backends": {"stt": "-" if args.text else cfg.stt.backend,
                                 "llm": "echo" if convo.echo else f"{cfg.llm.profile}:{cfg.llm.model}",
                                 "tts": cfg.tts.backend, "ptt": convo.ptt_summary()}})
            print(f"[fish] link={link.describe()} stt={stt} llm={llm} tts={cfg.tts.backend} "
                  f"ptt={convo.ptt_summary()}", flush=True)
            from .ptt import PTTUnavailable
            try:
                convo.run()
            except PTTUnavailable as e:
                print(f"No push-to-talk input: {e}", file=sys.stderr)
                return 78
    finally:
        # A record whose last line is not "end" was cut by a pulled plug or a hard exit.
        record.write("end", {})
        record.flush()
        if viz is not None:
            viz.stop()
        if hub is not None:
            try:
                from . import debug
                debug.uninstall()
            except Exception:
                pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
