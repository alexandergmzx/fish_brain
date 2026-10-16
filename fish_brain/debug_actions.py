"""What the `/debug` page may do to the fish: harmless tests, and, behind an arm switch, motor
test pulses and a restart of the service (ADR 0009).

Safety, in code terms:

- **Armed for 60 s.** `arm()` sets a deadline kept here, checked when an action is asked
  for. STOP and a restart drop it.
- **A motor test never takes a number from the page.** The request names a part; the lines
  come from the configuration and must pass `check_line` before they are sent: MOUTH, NECK or
  TAIL with one or two `<pwm> <ms>` pairs, 1.5 s at most in all, never a single integer (which
  the firmware would hold).
- **It runs in the turn loop.** The test is offered through the page server's inbox, like a
  typed name, and executed by the loop's own thread: the thread that drives the motors during
  speech is the only one that ever writes a motor line, and a test can only start while the
  fish waits for input. It takes the speaker's lock, has a deadline (an offer that is not
  picked up at once is dropped, never run late), and answers for its own errors.
- **STOP is not armed and never refused.** It aborts a running test, drops the arm and
  sends STOP at once from the request's thread (the link serialises the write). After it a
  test sends nothing more. During speech it ends the current pulse only.
- **Restart only as a systemd service**, by the unit's own stop signal to the main thread,
  so the goodbye and STOP run and the unit starts the fish again.
"""
from __future__ import annotations

import math
import os
import re
import signal
import struct
import tempfile
import threading
import time
import wave
from pathlib import Path

ARM_S = 60.0
PICKUP_S = 0.5            # an offered test not started by then is dropped
TOTAL_MS_MAX = 1500       # one test line, all its pairs together
RESTART_GRACE_S = 12.0    # after the stop signal: STOP and a hard exit if still alive
LOOP_MIN_RMS = 0.02       # the bring-up script's floor for "the microphone heard it"
LOOP_OVER_ROOM = 3.0      # and this many times the room (estimate: the remote's floor is noisy)
VOICE_PHRASE = "Probando la voz."
_LINE = re.compile(r"^(MOUTH|NECK|TAIL)((?: -?\d{1,3} [1-9]\d{0,3}){1,2})$")


def check_line(line: str) -> str:
    """The line if it is a timed test line, else ValueError. Never a held drive."""
    m = _LINE.match(line.strip())
    if not m:
        raise ValueError(f"not a timed test line: {line!r}")
    nums = [int(x) for x in m.group(2).split()]
    if any(abs(p) > 255 for p in nums[0::2]):
        raise ValueError(f"pwm out of range: {line!r}")
    if sum(nums[1::2]) > TOTAL_MS_MAX:
        raise ValueError(f"longer than {TOTAL_MS_MAX} ms: {line!r}")
    return line.strip()


def build_lines(cfg, part: str) -> list[str]:
    """The lines of one motor test, from the configuration (the values speech itself uses)."""
    if part == "mouth":
        lines = [f"MOUTH {int(cfg.mouth.open_pwm)} {int(cfg.mouth.open_curve[-1][1])}",
                 f"MOUTH {int(cfg.mouth.close_pwm)} {int(cfg.mouth.close_curve[-1][1])}"]
    elif part == "neck":
        # One out-and-return chain: the firmware finishes the return by itself.
        lines = [f"NECK {cfg.gesture.neck_out.strip()} {cfg.gesture.neck_return.strip()}"]
    elif part == "tail":
        lines = [f"TAIL {cfg.gesture.tail_flap.strip()}"]
    else:
        raise ValueError(f"unknown part {part!r}")
    return [check_line(" ".join(line.split())) for line in lines]


# ---- the switches ---------------------------------------------------------------------------
# name -> (label, kind, choices, read(actions), apply(actions, value) -> "" or why not).
# `apply` runs in the turn loop, between turns.

def _key_missing(env_name: str | None) -> str:
    return "" if not env_name or os.environ.get(env_name, "").strip() else f"{env_name} is not set"


def _fresh_llm(a) -> None:
    a.convo._llm = None                          # the next turn builds a client for cfg.llm
    from . import debug
    debug.new_visitor()


def _set_mode(a, value: str) -> str:
    if value == "llm":
        missing = _key_missing(a.cfg.llm.api_key_env)
        if missing:
            return missing
    a.convo.echo = value == "echo"
    _fresh_llm(a)
    return ""


def _set_llm_profile(a, value: str) -> str:
    from .config import LLM_PROFILES, LLMConfig
    missing = _key_missing(LLM_PROFILES[value]["api_key_env"])
    if missing:
        return missing
    old = a.cfg.llm
    a.cfg.llm = LLMConfig(profile=value, system_prompt=old.system_prompt,
                          fallback_reply=old.fallback_reply,
                          max_history_turns=old.max_history_turns)
    _fresh_llm(a)
    return ""


def _fresh_stt(a) -> str:
    """Check the new setting now, so a missing model or package is the switch's answer and
    not the next turn's; then drop the old transcriber and load the new one off the loop."""
    from .stt import make_transcriber
    try:
        make_transcriber(a.cfg.stt)              # cheap: nothing is loaded here
    except (ValueError, RuntimeError) as e:
        return str(e)
    a.convo._stt = None                          # the next turn builds the transcriber
    warm = getattr(a.convo, "warm_stt", None)
    if warm is not None:
        warm()
    return ""


def _set_stt(a, value: str) -> str:
    from .config import STT_PROFILES
    if value in STT_PROFILES:
        missing = _key_missing(STT_PROFILES[value]["api_key_env"])
        if missing:
            return missing
    old, a.cfg.stt.backend = a.cfg.stt.backend, value
    problem = _fresh_stt(a)
    if problem:
        a.cfg.stt.backend = old
    return problem


def _set_stt_model(a, value: str) -> str:
    a.cfg.stt.model = value                      # canary uses it for the long recordings
    return _fresh_stt(a) if a.cfg.stt.backend in ("local", "canary") else ""


def _set_tts(a, value: str) -> str:
    import shutil
    if value == "loq" and not shutil.which(a.cfg.tts.loq_bin):
        return f"{a.cfg.tts.loq_bin} is not installed here"
    if value == "openai":
        missing = _key_missing("OPENAI_API_KEY")
        if missing:
            return missing
    a.cfg.tts.backend = value

    def warm():                                  # off the turn loop: it can take seconds
        try:
            from . import canned, tts
            tts.warm(a.cfg.tts)
            canned.prerender_all(a.cfg)
        except Exception:
            pass
    threading.Thread(target=warm, name="debug-voice-warm", daemon=True).start()
    return ""


def _attr(path: str):
    section, field = path.split(".")
    return (lambda a: getattr(getattr(a.cfg, section), field),
            lambda a, v: setattr(getattr(a.cfg, section), field, v) or "")


def _set_motors(a, value: str) -> str:
    a.link.mute(value == "muted")
    return ""


_gest, _look, _quit, _limit = (_attr("gesture.enabled"), _attr("reading.look"),
                               _attr("ptt.voice_quit"), _attr("ptt.max_record_s"))
_fill, _fill_delay, _burble = (_attr("filler.enabled"), _attr("filler.delay_s"),
                               _attr("burble.enabled"))
SWITCHES: dict = {
    "mode": ("Mode", "choice", ("echo", "llm"),
             lambda a: "echo" if getattr(a.convo, "echo", False) else "llm", _set_mode),
    "llm_profile": ("LLM profile", "choice", ("groq", "luna"),
                    lambda a: a.cfg.llm.profile, _set_llm_profile),
    "stt": ("Speech-to-text", "choice", ("openai", "groq", "local", "canary"),
            lambda a: a.cfg.stt.backend, _set_stt),
    "stt_model": ("Local speech model", "choice", ("tiny", "base", "small"),
                  lambda a: a.cfg.stt.model, _set_stt_model),
    "tts": ("Voice", "choice", ("loq", "openai"), lambda a: a.cfg.tts.backend, _set_tts),
    "gestures": ("Gestures", "bool", (), lambda a: bool(_gest[0](a)), _gest[1]),
    "reading_look": ("Reading's look line", "bool", (), lambda a: bool(_look[0](a)), _look[1]),
    "voice_quit": ("Voice quit word", "bool", (), lambda a: bool(_quit[0](a)), _quit[1]),
    "burble": ("Burble on release", "bool", (), lambda a: bool(_burble[0](a)), _burble[1]),
    "filler": ("Fillers while it thinks", "bool", (), lambda a: bool(_fill[0](a)), _fill[1]),
    "filler_delay_s": ("First filler after (s)", "number", (0.5, 6.0),
                       lambda a: float(_fill_delay[0](a)), _fill_delay[1]),
    "max_record_s": ("Recording limit (s)", "number", (3.0, 60.0),
                     lambda a: float(_limit[0](a)), _limit[1]),
    "mic": ("Microphone", "choice", ("host", "browser"), lambda a: a.cfg.ptt.capture,
            lambda a, v: setattr(a.cfg.ptt, "capture", v) or ""),
    "motors": ("Motors", "choice", ("on", "muted"),
               lambda a: "muted" if getattr(a.link, "muted", False) else "on", _set_motors),
}


def _switch_note(a, name: str, value) -> str:
    if name == "mode" and value == "echo":
        return "the fish only repeats what it hears"
    if name == "stt" and value == "local":
        return f"faster-whisper '{a.cfg.stt.model}' on this machine: loading now"
    if name == "stt" and value == "canary":
        far = " > ".join([*a.cfg.stt.long_online, f"local '{a.cfg.stt.model}'"])
        return (f"Canary on this machine for recordings up to {a.cfg.stt.canary_long_s:g} s, "
                f"about 2.5 s a turn on the board; longer ones: {far}")
    if name == "stt_model":
        used = {"local": "", "canary": "used for the long recordings when nothing online answers · "}.get(
            a.cfg.stt.backend, "not in use (speech-to-text is not local) · ")
        return used + "on the board: tiny about 4 s a turn, base 8 s, small 20 s (measured 2026-10-10)"
    if name == "mic":
        if value == "browser" and not (a.cfg.viz.tls_cert and a.cfg.viz.tls_key):
            return "phones can only record over the HTTPS listener, which is off"
        return "the phone records" if value == "browser" else "this machine's microphone records"
    if name == "motors" and value == "muted":
        return "every motor line is dropped; the fish only talks"
    if name == "burble":
        return ("a bubble sound and a tail flap when a recording is taken; none = not heard"
                if value else "no sound at release")
    if name == "filler":
        f = a.cfg.filler
        return (f"a phrase after {f.delay_s:g} s of waiting, {f.gap_s:g} s between phrases, "
                f"an apology at {f.turn_timeout_s:g} s" if value
                else "silent while it waits, and no limit on a turn")
    if name == "llm_profile":
        return a.cfg.llm.model or ""
    return ""


def _tone(seconds: float = 1.5, rate: int = 22050) -> str:
    """A short 1 kHz tone as a temporary WAV (for the loop test without a rendered phrase)."""
    fd, name = tempfile.mkstemp(suffix=".wav", prefix="fish_tone_")
    os.close(fd)
    n = int(seconds * rate)
    with wave.open(name, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"".join(struct.pack("<h", int(9000 * math.sin(2 * math.pi * 1000 * i / rate)))
                               for i in range(n)))
    return name


def _line_ms(line: str) -> int:
    return sum(int(x) for x in line.split()[2::2])


class _Item:
    """Something for the turn loop to run (it looks for `run_in_loop`)."""

    def __init__(self, fn, deadline: float, clock):
        self._fn, self._deadline, self._clock = fn, deadline, clock
        self.cancelled = False
        self.done = threading.Event()
        self.result: dict = {"ok": False, "error": "not run"}

    def run_in_loop(self, convo) -> None:
        try:
            if self.cancelled or self._clock() > self._deadline:
                self.result = {"ok": False, "error": "expired"}
            else:
                self.result = self._fn(convo)
        except Exception as e:                   # a test must never make the fish apologise
            self.result = {"ok": False, "error": type(e).__name__}
        finally:
            self.done.set()


class DebugActions:
    def __init__(self, cfg, link, convo, viz, hub, *, clock=time.monotonic, supervised=None,
                 terminate=None, sleep=None):
        self.cfg, self.link, self.convo, self.viz, self.hub = cfg, link, convo, viz, hub
        self._clock = clock
        self._armed_until = 0.0
        self._abort = threading.Event()
        self._stops = 0                          # counts STOPs: a test started before one never runs
        self._running = False
        self._ping_n = 0
        self.last: dict = {}                     # what each test last said, for the Checks tab
        self._start = {name: read(self) for name, (_l, _k, _c, read, _a) in SWITCHES.items()}
        self.restarting = False
        self._lock = threading.Lock()
        self._supervised = supervised
        self._terminate = terminate or self._signal_main
        self._wait = sleep or self._abort.wait   # returns True when STOP came

    # ---- arm --------------------------------------------------------------------------------

    def armed_s(self) -> int:
        return max(0, int(round(self._armed_until - self._clock())))

    def arm(self, on: bool) -> tuple[int, dict]:
        self._armed_until = self._clock() + ARM_S if on else 0.0
        self.hub.emit("action", what="arm" if on else "disarm", result="ok")
        return 200, {"ok": True, "armed_s": self.armed_s()}

    def _is_armed(self) -> bool:
        return self._clock() < self._armed_until

    # ---- what the tests would send ----------------------------------------------------------

    def planned_lines(self) -> dict:
        out = {}
        for part in ("mouth", "neck", "tail"):
            try:
                out[part] = build_lines(self.cfg, part)
            except Exception as e:
                out[part] = {"error": str(e)[:120]}
        return out

    # ---- through the turn loop --------------------------------------------------------------

    def _offer(self, fn, wait_s: float) -> tuple[int, dict]:
        if self.viz is None or not self.viz.listening:
            return 409, {"ok": False, "error": "busy"}
        if any(s.is_held() for s in getattr(self.convo, "sources", ())):
            return 409, {"ok": False, "error": "recording"}
        if self.cfg.ptt.capture == "browser" and self.viz.mic_pages() > 0:
            # A phone records by itself and only says so when it uploads: a test could land
            # in the middle of a visitor's sentence. Not in this mode.
            return 409, {"ok": False, "error": "a phone is the microphone"}
        item = _Item(fn, self._clock() + PICKUP_S, self._clock)
        if not self.viz.offer(item):
            return 409, {"ok": False, "error": "busy"}
        if not item.done.wait(wait_s):
            item.cancelled = True
            return 504, {"ok": False, "error": "not picked up"}
        return (200 if item.result.get("ok") else 409), item.result

    def motor(self, part: str) -> tuple[int, dict]:
        stops = self._stops                      # before anything else: a STOP from here on wins
        if not self._is_armed():
            return 403, {"ok": False, "error": "not armed"}
        try:
            lines = build_lines(self.cfg, str(part))
        except ValueError as e:
            return 400, {"ok": False, "error": str(e)[:120]}
        if not self.link.attached:
            return 409, {"ok": False, "error": "link off"}
        with self._lock:
            if self._running:
                return 409, {"ok": False, "error": "test running"}
            self._running = True
        if stops == self._stops:
            self._abort.clear()
        try:
            status, out = self._offer(
                lambda convo: self._run_motor(convo, part, lines, stops), 4.0)
        finally:
            self._running = False
        self.hub.emit("action", what=f"motor {part}", lines=out.get("lines", []),
                      result=out.get("result") or out.get("error", ""))
        return status, out

    def _run_motor(self, convo, part: str, lines: list[str], stops: int) -> dict:
        if stops != self._stops or not self._is_armed():
            return {"ok": False, "error": "stopped"}     # a STOP came since the request
        lock = convo.speaker._lock
        if not lock.acquire(blocking=False):
            return {"ok": False, "error": "speaking"}
        sent: list[str] = []
        stopped = False
        try:
            if self._abort.is_set() or stops != self._stops:
                return {"ok": False, "error": "stopped"}
            first, rest = lines[0], lines[1:]
            try:
                self.link.send(first, throttle=False)
                sent.append(first)
                stopped = bool(self._wait(_line_ms(first) / 1000.0 + 0.15))
            finally:
                # The return stroke always follows (the mouth's close pulse), unless STOP
                # came: then nothing but STOP is sent.
                if stopped or self._abort.is_set() or stops != self._stops:
                    stopped = True
                    self.link.all_stop()
                else:
                    for line in rest:
                        self.link.send(line, throttle=False)
                        sent.append(line)
                        self._wait(_line_ms(line) / 1000.0 + 0.05)
        finally:
            lock.release()
        mock = "nothing moves (mock link)" if type(self.link).__name__ == "MockSerialLink" else ""
        return {"ok": True, "part": part, "lines": sent,
                "result": "stopped" if stopped else "sent", "note": mock}

    def mic(self, seconds) -> tuple[int, dict]:
        try:
            seconds = max(0.5, min(5.0, float(seconds or 2.0)))
        except (TypeError, ValueError):
            seconds = 2.0

        def run(convo) -> dict:
            from . import ptt
            wav = ptt.record_for(seconds, self.cfg.ptt,
                                 on_level=lambda lvl: self.hub.emit("level", rms=round(lvl, 4)))
            try:
                self.hub.recording(wav, "microphone check")
            finally:
                Path(wav).unlink(missing_ok=True)
            return {"ok": True, "rec": self.hub.recording_stats()}

        status, out = self._offer(run, seconds + 4.0)
        self.hub.emit("action", what="microphone check",
                      result="ok" if out.get("ok") else out.get("error", ""))
        return status, out

    def say(self, name) -> tuple[int, dict]:
        """A canned phrase that is already rendered, as audio only: nothing is synthesized
        and nothing goes to the motors."""
        name = str(name or "")
        if name not in self.cfg.canned.phrases:
            return 400, {"ok": False, "error": "unknown phrase"}
        files = sorted(self.cfg.canned.cache_dir.glob(f"{name}-*.wav"),
                       key=lambda p: p.stat().st_mtime)
        files = [f for f in files if not f.name.endswith(".new.wav")]
        if not files:
            return 404, {"ok": False, "error": "not rendered"}

        def run(convo) -> dict:
            lock = convo.speaker._lock
            if not lock.acquire(blocking=False):
                return {"ok": False, "error": "speaking"}
            try:
                convo.player.play(files[-1])
                convo.player.wait()
            finally:
                lock.release()
            return {"ok": True, "player": type(convo.player).__name__}

        status, out = self._offer(run, 20.0)
        self.hub.emit("action", what=f"speaker test {name}",
                      result="played" if out.get("ok") else out.get("error", ""))
        return status, out

    # ---- from the request's own thread ------------------------------------------------------

    def stop(self) -> tuple[int, dict]:
        self._stops += 1
        self._abort.set()
        self._armed_until = 0.0
        error = ""
        try:
            self.link.all_stop()
            if not self.link.attached:
                error = "link off"               # nothing reached the MCU: say so
        except Exception as e:
            error = type(e).__name__
        speaking = self.convo.speaker._lock.locked() if self.convo is not None else False
        self.hub.emit("action", what="STOP", result=error or "sent")
        return 200, {"ok": not error, "error": error, "speaking": speaking}

    def ping(self) -> tuple[int, dict]:
        """The motor-safe `PING <n>`: the firmware answers "Unknown command" (and echoes).
        Through the turn loop like the other tests, so no request thread ever holds the
        speaker's lock or reads the port."""
        def run(convo) -> dict:
            lock = convo.speaker._lock
            if not lock.acquire(blocking=False):
                return {"ok": False, "error": "speaking"}
            try:
                if not self.link.attached:
                    return {"ok": False, "error": "link off"}
                self.link.wait_reply(0.05)       # what is still unread belongs to older lines
                self._ping_n += 1
                t0 = time.monotonic()
                self.link.send(f"PING {self._ping_n}", throttle=False)
                answered = self.link.wait_reply(0.3)
                ms = round((time.monotonic() - t0) * 1000.0, 1)
            finally:
                lock.release()
            word = {True: "answered", False: "silent", None: "cannot tell"}[answered]
            return {"ok": True, "answered": answered, "result": word, "ms": ms,
                    "health": self.link.health()}

        status, out = self._offer(run, 3.0)
        self.hub.emit("action", what="ping", result=out.get("result") or out.get("error", ""))
        if out.get("ok"):
            self._note("ping", {True: "pass", False: "fail", None: "skip"}[out["answered"]],
                       f"{out['result']} in {out['ms']} ms", "LED4 must blink green")
        return status, out

    def _note(self, key: str, status: str, detail: str, fix: str = "") -> None:
        self.last[key] = {"status": status, "detail": f"{detail} · {time.strftime('%H:%M:%S')}",
                          "fix": fix}

    # ---- the bring-up tests that make sound, take time or cost a call ----------------------

    def loop(self) -> tuple[int, dict]:
        """Speaker to microphone: the room, then a rendered phrase (or a tone) played while
        recording. Never changes the volume, nothing goes to the motors."""
        def run(convo) -> dict:
            from . import ptt
            from .debug import wav_stats
            if type(convo.player).__name__ == "SilentPlayer":
                return {"ok": False, "error": "no audio (silent player)"}
            lock = convo.speaker._lock
            if not lock.acquire(blocking=False):
                return {"ok": False, "error": "speaking"}
            made = None
            try:
                room_wav = ptt.record_for(0.5, self.cfg.ptt)
                try:
                    room = wav_stats(Path(room_wav).read_bytes()).get("rms", 0.0)
                finally:
                    Path(room_wav).unlink(missing_ok=True)
                files = sorted((f for f in self.cfg.canned.cache_dir.glob("*.wav")
                                if not f.name.endswith(".new.wav")),
                               key=lambda p: p.stat().st_mtime)
                src, what = (files[-1], files[-1].name.split("-")[0]) if files else (None, "a tone")
                if src is None:
                    src = made = _tone()
                convo.player.play(src)
                try:
                    wav = ptt.record_for(2.0, self.cfg.ptt, on_level=lambda lvl: self.hub.emit(
                        "level", rms=round(lvl, 4)))
                finally:
                    stop = getattr(convo.player, "stop", None)
                    if stop is not None:
                        stop()
                try:
                    self.hub.recording(wav, "loop test")
                finally:
                    Path(wav).unlink(missing_ok=True)
                rec = self.hub.recording_stats() or {}
            finally:
                if made is not None:
                    Path(made).unlink(missing_ok=True)
                lock.release()
            rms, zeros = rec.get("rms", 0.0), rec.get("zero_frac", 0.0)
            verdict = ("zeros" if zeros > 0.95 else
                       "heard" if rms >= max(LOOP_MIN_RMS, LOOP_OVER_ROOM * room) else
                       "too quiet at the microphone")
            return {"ok": True, "verdict": verdict, "played": what, "room": round(room, 4),
                    "level": rms, "zero_frac": zeros}

        status, out = self._offer(run, 12.0)
        if out.get("ok"):
            self._note("loop", "pass" if out["verdict"] == "heard" else "fail",
                       f"{out['verdict']}: room {out['room']}, playing {out['level']} "
                       f"({out['played']}), zeros {round(out['zero_frac'] * 100)} %",
                       "hold the microphone near the speaker; check the sink's volume and the source")
        self.hub.emit("action", what="loop test", result=out.get("verdict") or out.get("error", ""))
        return status, out

    def voice(self) -> tuple[int, dict]:
        """Render one short phrase with the configured voice, timed, never played."""
        def run(convo) -> dict:
            from . import tts
            lock = convo.speaker._lock
            if not lock.acquire(blocking=False):
                return {"ok": False, "error": "speaking"}
            fd, name = tempfile.mkstemp(suffix=".wav", prefix="fish_dbg_")
            os.close(fd)
            Path(name).unlink(missing_ok=True)
            t0 = time.monotonic()
            try:
                tts.synthesize(VOICE_PHRASE, self.cfg.tts, out_path=name)
                return {"ok": True, "seconds": round(time.monotonic() - t0, 2),
                        "backend": self.cfg.tts.backend}
            except Exception as e:
                return {"ok": False, "error": type(e).__name__,
                        "seconds": round(time.monotonic() - t0, 2)}
            finally:
                Path(name).unlink(missing_ok=True)
                lock.release()

        status, out = self._offer(run, 30.0)
        if "seconds" in out:
            self._note("voice", "pass" if out.get("ok") else "fail",
                       f"{self.cfg.tts.backend}: " + (f"{out['seconds']} s" if out.get("ok")
                                                      else f"{out['error']} after {out['seconds']} s"),
                       "see the [tts] record in the Model tab and the log")
        self.hub.emit("action", what="voice render",
                      result=f"{out.get('seconds')} s" if out.get("ok") else out.get("error", ""))
        return status, out

    def cloud(self) -> tuple[int, dict]:
        """One call to each cloud model in use, with its real key: ok and seconds, or the
        error's type. The LLM call leaves the conversation's history alone."""
        def run(convo) -> dict:
            from .config import STT_PROFILES
            parts: dict = {}
            if self.cfg.stt.backend in STT_PROFILES:
                wav = _tone(0.6)
                t0 = time.monotonic()
                try:
                    convo.stt.transcribe(wav)
                    parts["stt"] = {"ok": True, "seconds": round(time.monotonic() - t0, 2)}
                except Exception as e:
                    parts["stt"] = {"ok": False, "error": type(e).__name__,
                                    "status": getattr(e, "status_code", None)}
                finally:
                    Path(wav).unlink(missing_ok=True)
            else:
                parts["stt"] = {"skipped": f"{self.cfg.stt.backend} runs here"}
            if getattr(convo, "echo", False):
                parts["llm"] = {"skipped": "echo mode: no model is called"}
            else:
                try:
                    parts["llm"] = {"ok": True, **convo.llm.probe()}
                except Exception as e:
                    parts["llm"] = {"ok": False, "error": type(e).__name__,
                                    "status": getattr(e, "status_code", None)}
            return {"ok": True, "parts": parts}

        status, out = self._offer(run, 25.0)
        if out.get("ok"):
            parts = out["parts"]
            bad = [k for k, v in parts.items() if v.get("ok") is False]
            words = [f"{k}: " + (v.get("skipped") or (f"{v['seconds']} s" if v.get("ok") else
                     f"{v['error']}" + (f" {v['status']}" if v.get("status") else "")))
                     for k, v in parts.items()]
            ran = [v for v in parts.values() if "ok" in v]
            self._note("cloud", "fail" if bad else "pass" if ran else "skip", "; ".join(words),
                       "a key (401), the model's name (404) or the network: see the Model tab")
        self.hub.emit("action", what="cloud round trip",
                      result="ok" if out.get("ok") else out.get("error", ""))
        return status, out

    # ---- switches: the running fish only, never .env; a restart brings the start values back --

    def switches(self) -> list[dict]:
        out = []
        for name, (label, kind, choices, read, _apply) in SWITCHES.items():
            value = read(self)
            out.append({"name": name, "label": label, "kind": kind, "choices": list(choices),
                        "value": value, "start": self._start.get(name),
                        "changed": value != self._start.get(name),
                        "armed": name == "motors", "note": _switch_note(self, name, value)})
        return out

    def set(self, name, value) -> tuple[int, dict]:
        if name not in SWITCHES:
            return 400, {"ok": False, "error": "unknown switch"}
        label, kind, choices, read, apply = SWITCHES[name]
        if kind == "bool":
            value = bool(value)
        elif kind == "number":
            try:
                value = float(value)
            except (TypeError, ValueError):
                return 400, {"ok": False, "error": "a number expected"}
            if not choices[0] <= value <= choices[1]:
                return 400, {"ok": False, "error": f"{choices[0]:g} to {choices[1]:g} expected"}
        elif value not in choices:
            return 400, {"ok": False, "error": f"one of {', '.join(choices)} expected"}
        if name == "motors" and not self._is_armed():
            return 403, {"ok": False, "error": "not armed"}
        before = read(self)
        if value == before:
            return 200, {"ok": True, "value": value, "unchanged": True}

        def run(convo) -> dict:
            problem = apply(self, value)             # a word when it cannot be done
            if problem:
                return {"ok": False, "error": problem}
            return {"ok": True, "value": read(self)}

        status, out = self._offer(run, 5.0)
        if out.get("ok"):
            # In the journal too: a mode change is something to find later.
            print(f"[debug] {label.lower()}: {before} -> {out['value']}", flush=True)
        self.hub.emit("action", what=f"switch {name}",
                      result=f"{before} -> {out['value']}" if out.get("ok") else out.get("error", ""))
        return status, out

    # ---- restart ----------------------------------------------------------------------------

    def supervised(self) -> bool:
        if self._supervised is not None:
            return bool(self._supervised)
        from . import debug_state
        return bool(debug_state.service()["supervised"])

    def restart(self, confirm) -> tuple[int, dict]:
        if not self._is_armed():
            return 403, {"ok": False, "error": "not armed"}
        if confirm != "restart":
            return 400, {"ok": False, "error": "confirmation missing"}
        if not self.supervised():
            return 409, {"ok": False, "error": "not a service: nothing would start it again"}
        with self._lock:
            if self.restarting:
                return 409, {"ok": False, "error": "already restarting"}
            self.restarting = True
        self._armed_until = 0.0
        self.hub.emit("action", what="restart", result="signalled")
        threading.Thread(target=self._terminate, name="debug-restart", daemon=True).start()
        return 200, {"ok": True}

    def _signal_main(self) -> None:
        time.sleep(0.3)                      # let the reply reach the page
        # The unit's own stop signal, aimed at the main thread so a blocking call returns:
        # KeyboardInterrupt, the goodbye, STOP, exit; Restart=always brings the fish back.
        signal.pthread_kill(threading.main_thread().ident, signal.SIGINT)
        time.sleep(RESTART_GRACE_S)
        try:                                 # still here: stuck in a call. Motors off, then out.
            self.link.all_stop()
        except Exception:
            pass
        os._exit(1)

    # ---- the routes -------------------------------------------------------------------------

    def post(self, path: str, body: dict) -> tuple[int, dict]:
        if path == "/debug/arm":
            return self.arm(bool(body.get("on")))
        if path == "/debug/stop":
            return self.stop()
        if path == "/debug/ping":
            return self.ping()
        if path == "/debug/mic":
            return self.mic(body.get("seconds"))
        if path == "/debug/set":
            return self.set(body.get("name"), body.get("value"))
        if path == "/debug/loop":
            return self.loop()
        if path == "/debug/voice":
            return self.voice()
        if path == "/debug/cloud":
            return self.cloud()
        if path == "/debug/say":
            return self.say(body.get("name"))
        if path == "/debug/motor":
            return self.motor(body.get("part"))
        if path == "/debug/restart":
            return self.restart(body.get("confirm"))
        return 404, {"ok": False, "error": "no such action"}
