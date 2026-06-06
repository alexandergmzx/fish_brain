"""On-screen browser fish — a fallback/debug view of what the fish is saying.

Architecture (stdlib only, no extra deps):
  - A `ThreadingHTTPServer` on a daemon thread serves the static page (`web/`) and two
    dynamic endpoints:
      * `GET /events`        -> Server-Sent Events stream (one per connected browser).
      * `GET /audio/<token>` -> the bytes of a spoken WAV, snapshotted in memory.
  - When the host is about to speak, `announce_speech()` snapshots the WAV into memory and
    pushes a `speak` SSE event carrying the audio URL + gesture (NECK/TAIL) timing.

The browser plays + analyzes the audio itself (Web Audio `AnalyserNode`) to drive the
mouth, and tweens neck/tail from the gesture events — so it animates even with no hardware
(`--dry-run`), which is exactly the "physical fish misbehaving" fallback.

Best-effort by design: a slow/absent browser never blocks the conductor (full queues drop).
"""
from __future__ import annotations

import json
import queue
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .config import Config

WEB_DIR = Path(__file__).parent / "web"
IMG_DIR = WEB_DIR / "img"
_CONTENT_TYPES = {".html": "text/html", ".js": "text/javascript", ".css": "text/css",
                  ".png": "image/png"}


class VizServer:
    # Replay the most recent speak event to a browser that connects within this window, so the
    # startup greeting (played before any browser subscribes) still animates the on-screen fish.
    REPLAY_WINDOW_S = 30.0

    def __init__(self, cfg: Config):
        self.cfg = cfg
        self._subscribers: set[queue.Queue] = set()
        self._lock = threading.Lock()
        self._audio: dict[str, bytes] = {}   # token -> WAV bytes (keep the last few)
        self._audio_order: list[str] = []
        self._seq = 0
        self._last_event: str | None = None  # serialized last speak event (for replay-on-connect)
        self._last_event_ts = 0.0
        self._httpd: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None
        self._ptt_held = False                # browser hold-to-talk button state

    # --- lifecycle ---
    def start(self) -> None:
        handler = _make_handler(self)
        self._httpd = ThreadingHTTPServer((self.cfg.viz.host, self.cfg.viz.port), handler)
        self._thread = threading.Thread(target=self._httpd.serve_forever, daemon=True)
        self._thread.start()
        print(f"[viz] on-screen fish at http://{self.cfg.viz.host}:{self.cfg.viz.port}")

    def stop(self) -> None:
        if self._httpd is not None:
            self._httpd.shutdown()
            self._httpd.server_close()
            self._httpd = None

    # --- pub/sub ---
    def _subscribe(self) -> queue.Queue:
        q: queue.Queue = queue.Queue(maxsize=64)
        with self._lock:
            self._subscribers.add(q)
            replay = self._last_event
            fresh = (time.monotonic() - self._last_event_ts) < self.REPLAY_WINDOW_S
        if replay is not None and fresh:
            try:
                q.put_nowait(replay)  # catch up a just-connected browser (e.g. the greeting)
            except queue.Full:
                pass
        return q

    def _unsubscribe(self, q: queue.Queue) -> None:
        with self._lock:
            self._subscribers.discard(q)

    def _publish(self, data: str) -> None:
        with self._lock:
            subs = list(self._subscribers)
        for q in subs:
            try:
                q.put_nowait(data)
            except queue.Full:
                pass  # best-effort; never block the conductor

    # --- audio snapshots ---
    def _store_audio(self, wav: str | Path) -> str:
        self._seq += 1
        token = f"{self._seq}.wav"
        data = Path(wav).read_bytes()
        with self._lock:
            self._audio[token] = data
            self._audio_order.append(token)
            while len(self._audio_order) > 4:        # keep only the most recent few
                old = self._audio_order.pop(0)
                self._audio.pop(old, None)
        return token

    def _get_audio(self, token: str) -> bytes | None:
        with self._lock:
            return self._audio.get(token)

    # --- public API (called from speak.perform_wav) ---
    def announce_speech(self, wav: str | Path, duration_ms: int,
                        gesture_events: list[tuple[int, str, str]],
                        mouth_track: list[tuple[int, int]] | None = None) -> None:
        """Snapshot the WAV and tell connected browsers to play + animate it.

        `mouth_track` is the (t_ms, pwm) mouth schedule; we normalize it to 0..1 levels so the
        browser can drive the mouth from the same envelope the hardware uses (no audio needed).
        """
        try:
            token = self._store_audio(wav)
        except Exception as e:
            print(f"[viz] could not snapshot audio: {e}")
            return
        open_pwm = self.cfg.mouth.open_pwm or 1
        mouth = [[t, round(max(0, pwm) / open_pwm, 3)] for (t, pwm) in (mouth_track or [])]
        data = json.dumps({
            "type": "speak",
            "audio": f"/audio/{token}",
            "duration_ms": duration_ms,
            "gestures": [[t, ch, body] for (t, ch, body) in gesture_events],
            "mouth": mouth,
            "open_pwm": self.cfg.mouth.open_pwm,
        })
        with self._lock:
            self._last_event = data
            self._last_event_ts = time.monotonic()
        self._publish(data)

    def push_level(self, rms: float) -> None:
        """Push a live mic level (0..1 RMS) to browsers while recording (best-effort)."""
        self._publish(json.dumps({"type": "level", "rms": round(float(rms), 4)}))

    def push_transcript(self, text: str, role: str) -> None:
        """Push a transcript line to the browser. role is "user" (STT) or "fish" (reply)."""
        self._publish(json.dumps({"type": "stt", "role": role, "text": text}))

    # --- mic device selection ---
    def list_mics(self) -> dict:
        """Input devices for the web picker. Prefers PipeWire/Pulse sources (stable names that
        record through the sound server); falls back to raw sounddevice indices."""
        sources = _pulse_sources()
        if sources is not None:
            return {"devices": sources, "current": self.cfg.ptt.source}
        try:
            import sounddevice as sd
        except Exception as e:
            return {"devices": [], "current": self.cfg.ptt.device, "error": str(e)}
        try:
            default_in = sd.default.device[0] if sd.default.device else None
        except Exception:
            default_in = None
        devices = []
        for i, d in enumerate(sd.query_devices()):
            if d.get("max_input_channels", 0) > 0:
                devices.append({"id": str(i), "name": d.get("name", f"device {i}"),
                                "default": i == default_in})
        return {"devices": devices, "current": None if self.cfg.ptt.device is None
                else str(self.cfg.ptt.device)}

    def set_mic(self, value) -> dict:
        """Select the mic for the next turn (mutates shared cfg). A PipeWire source name goes to
        `source`; a numeric string is a sounddevice index; empty/None clears to the default."""
        if not value:
            self.cfg.ptt.source = None
            self.cfg.ptt.device = None
        elif str(value).isdigit():
            self.cfg.ptt.device = int(value)
            self.cfg.ptt.source = None
        else:
            self.cfg.ptt.source = str(value)
            self.cfg.ptt.device = None
        return {"ok": True, "current": self.cfg.ptt.source or self.cfg.ptt.device}

    # --- browser hold-to-talk (drives push-to-talk from the on-screen fish) ---
    def set_ptt(self, down: bool) -> dict:
        """Press/release the web push-to-talk button (the record loop polls `ptt_held`)."""
        self._ptt_held = bool(down)
        return {"held": self._ptt_held}

    def ptt_held(self) -> bool:
        return self._ptt_held


def _pulse_sources():
    """Real (non-monitor) PipeWire/Pulse input sources via `pactl`, or None if unavailable.

    Each entry: {"id": <stable source name>, "name": <friendly description>, "default": bool}.
    The id is fed to PULSE_SOURCE when recording, so it survives reboots/USB re-enumeration.
    """
    import subprocess
    try:
        out = subprocess.run(["pactl", "list", "sources"], capture_output=True,
                             text=True, timeout=3)
        if out.returncode != 0:
            return None
        default = subprocess.run(["pactl", "get-default-source"], capture_output=True,
                                 text=True, timeout=3).stdout.strip()
    except (FileNotFoundError, subprocess.SubprocessError):
        return None
    sources = []
    for block in out.stdout.split("Source #")[1:]:
        name = desc = None
        is_monitor = False
        for line in block.splitlines():
            t = line.strip()
            if t.startswith("Name:"):
                name = t[len("Name:"):].strip()
            elif t.startswith("Description:"):
                desc = t[len("Description:"):].strip()
            elif t.startswith("Monitor of Sink:"):
                is_monitor = t.split(":", 1)[1].strip() != "n/a"
        if name and not is_monitor and not name.endswith(".monitor"):
            sources.append({"id": name, "name": desc or name, "default": name == default})
    return sources


def _make_handler(server: "VizServer"):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):  # silence default request logging
            pass

        def do_GET(self):  # noqa: N802
            path = self.path.split("?", 1)[0]
            if path == "/" or path == "/index.html":
                self._serve_file("index.html")
            elif path in ("/fish.js", "/fish.css"):
                self._serve_file(path.lstrip("/"))
            elif path.startswith("/img/"):
                self._serve_img(path[len("/img/"):])
            elif path == "/events":
                self._serve_events()
            elif path == "/mics":
                self._send_json(server.list_mics())
            elif path.startswith("/audio/"):
                self._serve_audio(path[len("/audio/"):])
            else:
                self.send_error(404)

        def do_POST(self):  # noqa: N802
            path = self.path.split("?", 1)[0]
            if path in ("/mic", "/ptt"):
                try:
                    length = int(self.headers.get("Content-Length", 0))
                    body = json.loads(self.rfile.read(length) or b"{}")
                    if path == "/mic":
                        self._send_json(server.set_mic(body.get("device")))
                    else:
                        self._send_json(server.set_ptt(body.get("down")))
                except Exception as e:
                    self._send_json({"ok": False, "error": str(e)}, status=400)
            else:
                self.send_error(404)

        def _send_json(self, obj, status: int = 200):
            body = json.dumps(obj).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _serve_file(self, name: str):
            fp = WEB_DIR / name
            if not fp.exists():
                self.send_error(404)
                return
            body = fp.read_bytes()
            ctype = _CONTENT_TYPES.get(fp.suffix, "application/octet-stream")
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _serve_img(self, name: str):
            # Sanitize to a bare filename (no path traversal) under web/img/.
            safe = Path(name).name
            fp = IMG_DIR / safe
            if not safe or fp.suffix != ".png" or not fp.exists():
                self.send_error(404)
                return
            body = fp.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "image/png")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _serve_audio(self, token: str):
            data = server._get_audio(token)
            if data is None:
                self.send_error(404)
                return
            self.send_response(200)
            self.send_header("Content-Type", "audio/wav")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)

        def _serve_events(self):
            q = server._subscribe()
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "keep-alive")
            self.end_headers()
            try:
                # Prime the stream so the browser knows it's connected.
                self.wfile.write(b": connected\n\n")
                self.wfile.flush()
                while True:
                    try:
                        data = q.get(timeout=15)
                    except queue.Empty:
                        self.wfile.write(b": keep-alive\n\n")  # heartbeat
                        self.wfile.flush()
                        continue
                    self.wfile.write(f"data: {data}\n\n".encode("utf-8"))
                    self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError, OSError):
                pass  # browser disconnected
            finally:
                server._unsubscribe(q)

    return Handler
