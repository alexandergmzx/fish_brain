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

import os
import re
import signal
import threading
import time
from pathlib import Path

ARM_S = 60.0
PICKUP_S = 0.5            # an offered test not started by then is dropped
TOTAL_MS_MAX = 1500       # one test line, all its pairs together
RESTART_GRACE_S = 12.0    # after the stop signal: STOP and a hard exit if still alive
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
        if path == "/debug/say":
            return self.say(body.get("name"))
        if path == "/debug/motor":
            return self.motor(body.get("part"))
        if path == "/debug/restart":
            return self.restart(body.get("confirm"))
        return 404, {"ok": False, "error": "no such action"}
