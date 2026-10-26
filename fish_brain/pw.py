"""PipeWire's sinks and sources, by node name, refreshed in the background.

Device indices change between boots and sounddevice names are not PipeWire's, so the speaker
routes (audio_route.py) pick a sink by its `node.name` (e.g. `alsa_output.usb-Jieli_...`,
`bluez_output.XX_XX...`). One thread runs `pw-dump` every `period_s` (2 s, each call limited to
2 s) and keeps the lists; `refresh_now()` runs one at once (after a playback failure). Started
only when something needs it, so the laptop never runs `pw-dump`.
"""
from __future__ import annotations

import fnmatch
import json
import shutil
import subprocess
import threading
import time


def _dump() -> list[dict]:
    try:
        out = subprocess.run(["pw-dump"], capture_output=True, text=True, timeout=2.0).stdout
        return json.loads(out or "[]")
    except (OSError, subprocess.TimeoutExpired, ValueError):
        return []


def parse(objects: list[dict]) -> dict[str, list[dict]]:
    """pw-dump's objects -> {"sinks": [...], "sources": [...]}, each {id, name, desc}."""
    out = {"sinks": [], "sources": []}
    for o in objects:
        if o.get("type") != "PipeWire:Interface:Node":
            continue
        props = (o.get("info") or {}).get("props") or {}
        cls = props.get("media.class", "")
        kind = "sinks" if cls == "Audio/Sink" else "sources" if cls == "Audio/Source" else None
        if kind is None:
            continue
        out[kind].append({"id": o.get("id"), "name": props.get("node.name", ""),
                          "desc": props.get("node.description", "")})
    return out


class Cache:
    def __init__(self, period_s: float = 2.0, dump=_dump):
        self.period_s = period_s
        self._dump = dump
        self._lock = threading.Lock()
        self._data = {"sinks": [], "sources": []}
        self._at = 0.0
        self._wake = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> "Cache":
        if self._thread is None and shutil.which("pw-dump"):
            self.refresh_now()
            self._thread = threading.Thread(target=self._loop, name="pw-cache", daemon=True)
            self._thread.start()
        return self

    def _loop(self) -> None:
        while True:
            self._wake.wait(self.period_s)
            self._wake.clear()
            self.refresh_now()

    def refresh_now(self) -> None:
        data = parse(self._dump())
        with self._lock:
            self._data, self._at = data, time.monotonic()

    def poke(self) -> None:
        self._wake.set()

    def sinks(self) -> list[dict]:
        with self._lock:
            return list(self._data["sinks"])

    def sources(self) -> list[dict]:
        with self._lock:
            return list(self._data["sources"])

    def find_sink(self, pattern: str) -> dict | None:
        for s in self.sinks():
            if fnmatch.fnmatch(s["name"], pattern):
                return s
        return None


_cache: Cache | None = None


def cache() -> Cache:
    global _cache
    if _cache is None:
        _cache = Cache().start()
    return _cache


def volume(node_id) -> float | None:
    """The sink's volume, 0..1 (wpctl), or None."""
    try:
        out = subprocess.run(["wpctl", "get-volume", str(node_id)], capture_output=True,
                             text=True, timeout=2.0).stdout
        return round(float(out.split()[1]), 2)
    except (OSError, subprocess.TimeoutExpired, IndexError, ValueError):
        return None


def set_volume(node_id, value: float) -> bool:
    value = max(0.0, min(1.0, float(value)))
    try:
        r = subprocess.run(["wpctl", "set-volume", str(node_id), f"{value:.2f}"],
                           capture_output=True, timeout=2.0)
        return r.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False
