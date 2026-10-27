"""Speaker routes: the USB speaker, then a Bluetooth speaker, then the phone (ADR 0016).

At the fair the hub lost power and the USB speaker with it; PipeWire then moves a stream to
the board's onboard codec, whose pins go nowhere, so the hat played into silence. With
FISH_AUDIO_ROUTES set, each phrase goes to the first route that is there:

- a sink pattern (`alsa_output.usb-*`, `bluez_output.*`): `pw-play --target <node>` with no
  fallback to another sink, as a subprocess with a time limit (it can always be killed, so a
  vanished device never hangs the turn loop);
- `phone`: the operator page plays it (POST /speakerstate arms it; the board publishes a
  `play` event and waits for `/speaker/started`).

A route that fails cools for `retry_s` and the same phrase goes to the next route before any
motor line. With no route left the phrase is silent and the hat stays still (`route` "none").
`started_at` is when the sound really started; `delay_s` is the route's measured delay, so the
conductor can run the motors later than the sound when the route needs it.
"""
from __future__ import annotations

import fnmatch
import subprocess
import time
import wave
from pathlib import Path

from . import debug
from .conductor import Player


class PlaybackError(RuntimeError):
    pass


def _duration_s(path) -> float:
    with wave.open(str(path), "rb") as w:
        return w.getnframes() / float(w.getframerate())


class PwPlayer(Player):
    """One phrase on one PipeWire sink, never moved to another one."""

    def __init__(self, node: str, *, stall_s: float = 2.0, exe: str = "pw-play"):
        self.node, self.stall_s, self.exe = node, stall_s, exe
        self._proc: subprocess.Popen | None = None
        self._dur = 0.0
        self.started_at: float | None = None

    def play(self, wav_path) -> None:
        self._dur = _duration_s(wav_path)
        self._proc = subprocess.Popen(
            [self.exe, "--target", self.node,
             "-P", "{ node.dont-fallback = true node.dont-reconnect = true }", str(wav_path)],
            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        self.started_at = time.monotonic()
        try:                                     # a missing target fails at once
            rc = self._proc.wait(timeout=0.15)
        except subprocess.TimeoutExpired:
            return
        if rc != 0 and self._dur > 0.3:
            err = (self._proc.stderr.read() or b"").decode("utf-8", "replace").strip()[:200]
            raise PlaybackError(f"pw-play exited {rc} at once: {err}")

    def wait(self, timeout: float | None = None) -> bool:
        if self._proc is None:
            return True
        limit = self._dur + self.stall_s if timeout is None else timeout
        try:
            self._proc.wait(timeout=max(0.1, limit))
            return True
        except subprocess.TimeoutExpired:
            self.stop()
            return False

    def stop(self) -> None:
        p = self._proc
        if p is not None and p.poll() is None:
            p.terminate()
            try:
                p.wait(timeout=0.5)
            except subprocess.TimeoutExpired:
                p.kill()


class PhonePlayer(Player):
    """One phrase played by the operator page. The page answers when its sound started."""

    def __init__(self, viz, *, ack_s: float = 2.5):
        self.viz, self.ack_s = viz, ack_s
        self._end = 0.0
        self.started_at: float | None = None

    def play(self, wav_path) -> None:
        dur = _duration_s(wav_path)
        started = self.viz.phone_play(wav_path, timeout_s=self.ack_s)
        if started is None:
            raise PlaybackError("the phone did not start the phrase")
        self.started_at = started
        self._end = started + dur

    def wait(self, timeout: float | None = None) -> bool:
        remaining = self._end - time.monotonic()
        if remaining > 0:
            time.sleep(remaining)
        return True

    def stop(self) -> None:
        self._end = 0.0
        try:
            self.viz.phone_stop()
        except Exception:
            pass


class _Silent(Player):
    def __init__(self):
        self._end = 0.0
        self.started_at: float | None = None

    def play(self, wav_path) -> None:
        self.started_at = time.monotonic()
        self._end = self.started_at + _duration_s(wav_path)

    def wait(self, timeout: float | None = None) -> bool:
        remaining = self._end - time.monotonic()
        if remaining > 0:
            time.sleep(remaining)
        return True

    def stop(self) -> None:
        self._end = 0.0


def parse_delays(spec: str) -> list[tuple[str, int]]:
    """"bluez_output.*=180,phone=120" -> [(pattern, ms)]."""
    out = []
    for part in (spec or "").split(","):
        if "=" in part:
            pat, ms = part.rsplit("=", 1)
            try:
                out.append((pat.strip(), int(ms)))
            except ValueError:
                pass
    return out


class RoutedPlayer(Player):
    def __init__(self, cfg, viz=None, *, cache=None, clock=time.monotonic):
        from . import pw
        self.cfg = cfg.audio
        self.viz = viz
        self.cache = cache if cache is not None else pw.cache()
        self._clock = clock
        self._cool: dict[str, float] = {}
        self._delays = parse_delays(self.cfg.delay_ms)
        self._cur: Player | None = None
        self.route = ""                 # the route of the phrase now (or last) playing
        self.node = ""                  # its sink's node name ("" for phone / none)
        self.started_at: float | None = None
        self.delay_s = 0.0

    def _delay(self, route: str) -> float:
        for pat, ms in self._delays:
            if fnmatch.fnmatch(route, pat):
                return ms / 1000.0
        return 0.0

    def _candidates(self):
        """(route, node, make a player) for each route a phrase can take now, in order: the
        device table's decision (devices.speaker_routes: cooling skipped, a marked USB
        speaker skipped, `phone` only with an armed page)."""
        from . import devices, hw
        pages = getattr(self.viz, "speaker_pages", lambda: 0)() if self.viz is not None else 0
        for route, node in devices.speaker_routes(self.cfg.routes, hw.failed("speaker"),
                                                  self.cache.sinks(), pages, self._cool,
                                                  self._clock()):
            if route == "phone":
                yield route, "", lambda: PhonePlayer(self.viz, ack_s=self.cfg.phone_ack_s)
            else:
                yield route, node, (lambda n=node: PwPlayer(n, stall_s=self.cfg.stall_s))

    def play(self, wav_path) -> None:
        previous = self.route
        for route, node, make in self._candidates():
            player = make()
            try:
                player.play(wav_path)
            except Exception as e:
                self._cool[route] = self._clock() + self.cfg.retry_s
                debug.emit("audio", event="route failed", route=route, error=str(e)[:200])
                print(f"[audio] {route} failed ({e}); trying the next route", flush=True)
                self.cache.poke()
                continue
            self._cur, self.route, self.node = player, route, node
            self.started_at = getattr(player, "started_at", None) or self._clock()
            self.delay_s = self._delay(route)
            if route != previous:
                print(f"[audio] speaker route: {route}" + (f" ({node})" if node else ""),
                      flush=True)
                debug.emit("audio", event="route", route=route, node=node)
            return
        self._cur, self.route, self.node = _Silent(), "none", ""
        self._cur.play(wav_path)
        self.started_at, self.delay_s = self._cur.started_at, 0.0
        if previous != "none":
            print("[audio] no speaker route left: the phrase is silent", flush=True)
            debug.emit("audio", event="route", route="none", node="")

    def wait(self, timeout: float | None = None) -> bool:
        cur = self._cur
        if cur is None:
            return True
        ok = cur.wait(timeout)
        if ok is False and self.route not in ("", "none"):
            self._cool[self.route] = self._clock() + self.cfg.retry_s
            debug.emit("audio", event="route stalled", route=self.route)
            print(f"[audio] {self.route} stalled; it cools for {self.cfg.retry_s:.0f} s", flush=True)
        return ok is not False

    def stop(self) -> None:
        if self._cur is not None:
            self._cur.stop()

    def view(self) -> dict:
        sinks = self.cache.sinks()
        route, node = self.route, self.node
        # `next`: the route the next phrase takes now (a mark or a cooling shows at once);
        # `route` keeps meaning the last one played.
        nxt = next(iter(self._candidates()), None)
        if not route:                           # nothing played yet: the route the next takes
            route, node = (nxt[0], nxt[1]) if nxt else ("none", "")
        live = next((s for s in sinks if s["name"] == node), None)
        return {"routes": list(self.cfg.routes), "route": route, "node": node,
                "next": nxt[0] if nxt else "none",
                "sink_id": live["id"] if live else None,
                "cooling": sorted(r for r, t in self._cool.items() if t > self._clock()),
                "sinks": [s["name"] for s in sinks],
                "phone_pages": getattr(self.viz, "speaker_pages", lambda: 0)() if self.viz else 0}
