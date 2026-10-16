"""Keeps the fish page on the board's own display (run inside the kiosk X session).

  python3 -m fish_brain.kiosk

Standard library only, so the system Python can run it and a broken venv cannot take the
screen down. Every two seconds it looks at three things and makes the browser match:

- no display connected, or the pause file exists  -> no browser at all
- display connected, the fish does not answer      -> the local waiting page
- display connected, the fish answers /status      -> the visitor view, /face?kiosk=1

The fish itself (the `fish-brain` user unit) never depends on any of this.

Settings, from the environment or from `FISH_KIOSK_*` / `FISH_VIZ_PORT` lines of `.env`
(no other line of that file is looked at):
  FISH_KIOSK_MODE     e.g. 1280x720; empty = the display's preferred mode
  FISH_KIOSK_OUTPUT   e.g. DP-1; empty = the first connected output
  FISH_KIOSK_BROWSER  default chromium
"""
from __future__ import annotations

import os
import re
import shutil
import signal
import subprocess
import sys
import time
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

REPO = Path(__file__).resolve().parent.parent
WAIT_PAGE = Path(__file__).resolve().parent / "web" / "wait.html"
PROFILE = "/tmp/fish-kiosk"                 # RAM-backed and wiped at every start
POLL_S = 2.0

_OUTPUT_RE = re.compile(r"^(\S+) (connected|disconnected)(?: primary)?(?: (\d+)x(\d+)\+\d+\+\d+)?")


@dataclass(frozen=True)
class Output:
    name: str
    connected: bool
    width: int = 0          # 0 = connected but not lit (no mode set)
    height: int = 0


def parse_outputs(xrandr_text: str) -> list[Output]:
    """Outputs from `xrandr --current`."""
    outs = []
    for line in xrandr_text.splitlines():
        m = _OUTPUT_RE.match(line)
        if m:
            outs.append(Output(m.group(1), m.group(2) == "connected",
                               int(m.group(3) or 0), int(m.group(4) or 0)))
    return outs


def read_settings(env_file: Path, environ=os.environ) -> dict:
    """`FISH_KIOSK_*` and `FISH_VIZ_PORT` only; the environment wins over the file."""
    found: dict = {}
    try:
        for raw in env_file.read_text(encoding="utf-8").splitlines():
            key, sep, value = raw.strip().partition("=")
            if sep and (key.startswith("FISH_KIOSK_") or key == "FISH_VIZ_PORT"):
                found[key] = value.strip()
    except OSError:
        pass
    for key, value in environ.items():
        if key.startswith("FISH_KIOSK_") or key == "FISH_VIZ_PORT":
            found[key] = value
    return found


def pick_output(outputs: list[Output], wanted: str = "") -> Optional[Output]:
    for o in outputs:
        if o.connected and (not wanted or o.name == wanted):
            return o
    return None


def decide(output: Optional[Output], paused: bool, fish_up: bool) -> str:
    """What should be on the screen: `none`, `wait` or `fish`."""
    if paused or output is None:
        return "none"
    return "fish" if fish_up else "wait"


def browser_argv(browser: str, url: str, width: int, height: int) -> list[str]:
    return [
        browser, "--kiosk", f"--user-data-dir={PROFILE}",
        "--no-first-run", "--no-default-browser-check", "--noerrdialogs",
        "--disable-infobars", "--disable-session-crashed-bubble",
        "--disable-features=Translate,TranslateUI",
        "--disable-pinch", "--overscroll-history-navigation=0",
        "--disable-component-update", "--disable-background-networking",
        "--disk-cache-size=10485760", "--password-store=basic",
        "--window-position=0,0", f"--window-size={width},{height}",
        url,
    ]


def _run(*cmd: str, timeout: float = 8.0) -> str:
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout).stdout
    except (OSError, subprocess.SubprocessError):
        return ""


def _fish_answers(port: int) -> bool:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/status", timeout=1.5) as r:
            return r.status == 200
    except Exception:
        return False


def _log(msg: str) -> None:
    print(f"[kiosk] {msg}", flush=True)


class Browser:
    def __init__(self) -> None:
        self.proc: Optional[subprocess.Popen] = None
        self.showing = "none"
        self.size = (0, 0)

    def alive(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def stop(self) -> None:
        if self.proc is not None and self.proc.poll() is None:
            try:
                os.killpg(self.proc.pid, signal.SIGTERM)
                self.proc.wait(timeout=5)
            except (OSError, subprocess.TimeoutExpired):
                try:
                    os.killpg(self.proc.pid, signal.SIGKILL)
                except OSError:
                    pass
        self.proc = None
        self.showing = "none"

    def show(self, what: str, url: str, browser: str, size: tuple[int, int]) -> None:
        self.stop()
        shutil.rmtree(PROFILE, ignore_errors=True)      # no restore prompt after a power cut
        try:
            self.proc = subprocess.Popen(browser_argv(browser, url, *size),
                                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                         start_new_session=True)
        except OSError as e:
            _log(f"could not start {browser}: {e}")
            return
        self.showing, self.size = what, size


def main() -> int:
    runtime = Path(os.environ.get("XDG_RUNTIME_DIR") or "/tmp")
    pause_file = runtime / "fish-kiosk.pause"
    browser = Browser()
    signal.signal(signal.SIGTERM, lambda *_: (_ for _ in ()).throw(KeyboardInterrupt))
    last, last_blank = "", 0.0
    try:
        while True:
            cfg = read_settings(REPO / ".env")
            port = int(cfg.get("FISH_VIZ_PORT") or 8723)
            exe = cfg.get("FISH_KIOSK_BROWSER") or "chromium"
            mode = cfg.get("FISH_KIOSK_MODE", "")
            out = pick_output(parse_outputs(_run("xrandr", "--current")),
                              cfg.get("FISH_KIOSK_OUTPUT", ""))
            if out is not None:
                want_size = tuple(int(n) for n in mode.split("x")) if mode else None
                if not out.width or (want_size and (out.width, out.height) != want_size):
                    # A display that was plugged in later is not lit by itself.
                    args = ["--mode", mode] if mode else ["--auto"]
                    _run("xrandr", "--output", out.name, *args)
                    out = pick_output(parse_outputs(_run("xrandr", "--current")), out.name)
                if time.monotonic() - last_blank > 60:           # keep the screen awake
                    _run("xset", "s", "off"), _run("xset", "-dpms")
                    last_blank = time.monotonic()
            lit = out if out is not None and out.width else None
            want = decide(lit, pause_file.exists(), _fish_answers(port))
            state = f"{want} on {lit.name} {lit.width}x{lit.height}" if lit else want
            if state != last:
                _log(state if lit or want != "none" else "no display, nothing to show")
                last = state
            if want == "none":
                browser.stop()
            elif (not browser.alive() or browser.showing != want
                  or browser.size != (lit.width, lit.height)):
                url = (f"http://127.0.0.1:{port}/face?kiosk=1" if want == "fish"
                       else WAIT_PAGE.as_uri())
                browser.show(want, url, exe, (lit.width, lit.height))
            time.sleep(POLL_S)
    except KeyboardInterrupt:
        pass
    finally:
        browser.stop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
