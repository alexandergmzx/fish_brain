"""Hardware the operator marked as failed (ADR 0017): the phone page's "Hardware" checks.

Automatic detection (a missing sink, a microphone sending only zeros, the cloud probe) still
runs; a mark forces the fallback at once, because the operator usually knows first. Marks
survive restarts and reboots (a cable swap reboots the board) until he clears them.

    speaker   the USB speaker: phrases go to Bluetooth, then the phone
    mic       the USB microphone (the remote's): recordings come from the phone
    remote    the remote's button: the page's Hold to talk only
    motors    the motors: the link is muted, nothing moves
    internet  no model calls: the visit runs as the script
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
    if not hasattr(cfg.ptt, "_capture_configured"):
        cfg.ptt._capture_configured = cfg.ptt.capture
    cfg.ptt.capture = "browser" if "mic" in m.failed else cfg.ptt._capture_configured
    if link is not None and hasattr(link, "mute"):
        want = "motors" in m.failed
        if bool(getattr(link, "muted", False)) != want:
            try:
                link.mute(want)
            except Exception as e:
                print(f"[hw] motors {'mute' if want else 'unmute'} failed: {e}", flush=True)
    if m.failed:
        print(f"[hw] marked failed: {', '.join(sorted(m.failed))}", flush=True)
