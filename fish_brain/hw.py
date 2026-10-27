"""Hardware the operator marked as failed (ADR 0017): the phone page's "Hardware" checks.

Automatic detection (a missing sink, a microphone sending only zeros, the cloud probe) still
runs; a mark forces the fallback at once, because the operator usually knows first. Marks
survive restarts and reboots (a cable swap reboots the board) until he clears them.

A mark is read where the decision is made, through the device table's functions
(`devices.py`, ADR 0021), never by rewriting the configuration:

    part      effect                                           read by
    speaker   phrases go to Bluetooth, then the phone          devices.speaker_routes (audio_route)
    mic       recordings come from a phone with its            devices.recorder (conversation,
              microphone on; with none, the board records       debug_actions)
    remote    its presses are ignored: the page's Hold to      ButtonSource.off, set by apply()
              talk only
    motors    the link is muted, nothing moves                 apply()
    internet  no model calls: the visit runs as the script     devices.internet (show_run, stt)

`apply()` leaves `cfg.ptt.capture` as configured: the `mic` switch's start value is the boot
value whatever is marked.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

PARTS = ("speaker", "mic", "remote", "motors", "internet")


def _default_path() -> Path:
    base = os.environ.get("XDG_STATE_HOME") or str(Path.home() / ".local/state")
    return Path(base) / "fish_brain" / "hw.json"


class Marks:
    def __init__(self, path: str | Path | None = None):
        self.path = Path(path) if path else _default_path()
        self.failed: set[str] = set()
        try:
            data = json.loads(self.path.read_text())
            self.failed = {p for p in data.get("failed", []) if p in PARTS}
        except (OSError, ValueError, AttributeError):
            pass

    def set(self, part: str, failed: bool) -> None:
        if part not in PARTS:
            raise ValueError(f"unknown part {part!r}")
        (self.failed.add if failed else self.failed.discard)(part)
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps({"failed": sorted(self.failed)}))
            os.replace(tmp, self.path)
        except OSError as e:
            print(f"[hw] marks not saved: {e}", flush=True)

    def view(self) -> dict:
        return {p: p in self.failed for p in PARTS}


_marks: Marks | None = None


def marks() -> Marks:
    global _marks
    if _marks is None:
        _marks = Marks()
    return _marks


def failed(part: str) -> bool:
    return part in marks().failed


def apply(cfg, convo=None, link=None) -> None:
    """Make the running fish follow the marks (at start and after every change)."""
    m = marks()
    for s in getattr(convo, "sources", None) or ():
        if s.name == "remote":
            s.off = "remote" in m.failed            # its presses neither record nor relay
    if link is not None and hasattr(link, "mute"):
        want = "motors" in m.failed
        if bool(getattr(link, "muted", False)) != want:
            try:
                link.mute(want)
            except Exception as e:
                print(f"[hw] motors {'mute' if want else 'unmute'} failed: {e}", flush=True)
    if m.failed:
        print(f"[hw] marked failed: {', '.join(sorted(m.failed))}", flush=True)
