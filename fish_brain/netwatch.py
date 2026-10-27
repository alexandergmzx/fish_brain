"""fish-net: the board raises its own Wi-Fi when no known network is there.

At a friend's and at his parents' house the board found no known Wi-Fi and nobody could reach
it. This watcher (a user unit, standard library only, run by /usr/bin/python3) keeps one rule:

- No client network on the interface within FISH_NET_CLIENT_WAIT_S of start, or for
  FISH_NET_LOSS_S after losing one: bring up the access-point profile FISH_NET_AP_PROFILE
  (made by `deploy/unoq_setup.sh ap`; 10.42.0.1, autoconnect off).
- On the access point with no station associated for FISH_NET_AP_IDLE_S: take it down, so
  NetworkManager tries the known networks for FISH_NET_TRY_S; nothing joined, back up. The
  idle tries back off (60, 120, 300 s, ...). Never while a phone is connected.
- A pin (`$XDG_STATE_HOME/fish_brain/net-pin` containing `ap`) keeps the access point up.
- Each time a client network comes up it tells the supplicant to ignore TDLS
  (`wpa_cli -i wlan0 set tdls_disabled 1`; `FISH_NET_TDLS_OFF=false` keeps TDLS): a phone on
  the same access point asks the board for a direct link every 10 to 30 s, the board's driver
  cannot key it, and the phone's page loses its connection while each attempt fails
  (2026-10-27, `docs/results/2026-10-27-home-wifi-drops.md`). The flag lives in the
  supplicant's interface and is set again after every reconnection.

It only runs `nmcli connection up|down <profile>`, that one `wpa_cli set`, and read-only
queries; it never adds or changes a profile. Its state goes to
`$XDG_RUNTIME_DIR/fish_brain/net.json` for the page. No profile configured: it says so and
exits 0 (the laptop never runs it).
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

WAIT, CLIENT, AP, TRYING = "wait", "client", "ap", "trying"


@dataclass
class Settings:
    ap_profile: str = ""
    iface: str = "wlan0"
    client_wait_s: float = 45.0
    loss_s: float = 30.0
    ap_idle_s: float = 60.0
    try_s: float = 40.0
    settle_s: float = 20.0        # after "up": how long the profile may take to come up
    backoff_s: tuple = (60.0, 120.0, 300.0)
    tdls_off: bool = True         # tell the supplicant to ignore TDLS on every client link


@dataclass
class Decider:
    """What to do, from what is seen. Pure: the caller feeds the clock and the facts."""
    s: Settings
    state: str = WAIT
    since: float = 0.0            # when the current state began
    no_client_since: float = 0.0  # last time a client link was up (or the start)
    empty_since: float = 0.0      # on the AP: since when no station was associated
    tries: int = 0                # idle tries back to the known networks
    had_client: bool = False      # a client network was up since start: losses use loss_s
    next_try_at: float = 0.0
    log: list = field(default_factory=list)

    def start(self, now: float) -> None:
        self.since = self.no_client_since = now

    def step(self, now: float, active: str, stations: int, pinned: bool) -> str | None:
        """`active`: the connection on the interface ("" for none). Returns "up", "down" or
        None: what to do with the access-point profile now."""
        on_ap = active == self.s.ap_profile
        if active and not on_ap:                       # a client network
            if self.state != CLIENT:
                self._to(CLIENT, now)
                self.tries = 0
            self.had_client = True
            self.no_client_since = now
            return None
        if on_ap:
            if self.state not in (AP,):
                self._to(AP, now)
                self.empty_since = now
                if not self.next_try_at:
                    self.next_try_at = now + self.s.ap_idle_s
            if stations > 0 or pinned:
                self.empty_since = now
                self.next_try_at = max(self.next_try_at, now + self.s.ap_idle_s)
                return None
            if now - self.empty_since >= self.s.ap_idle_s and now >= self.next_try_at:
                gap = self.s.backoff_s[min(self.tries, len(self.s.backoff_s) - 1)]
                self.tries += 1
                self.next_try_at = now + self.s.try_s + gap
                self._to(TRYING, now)
                return "down"
            return None
        # Nothing on the interface.
        if self.state == AP:                           # raised, still coming up (or it fell)
            if now - self.since < self.s.settle_s:
                return None
            return self._raise(now, again=True)
        if pinned:
            return self._raise(now)
        if self.state == TRYING:
            if now - self.since >= self.s.try_s:
                return self._raise(now)
            return None
        if self.state == CLIENT:                       # just lost it
            self._to(WAIT, now)
            self.no_client_since = now
        limit = self.s.loss_s if self.had_client else self.s.client_wait_s
        if now - self.no_client_since >= limit:
            return self._raise(now)
        return None

    def _raise(self, now: float, again: bool = False) -> str:
        if again:
            self.since = now
        self._to(AP, now)
        self.empty_since = now
        if self.next_try_at < now:
            self.next_try_at = now + self.s.ap_idle_s
        return "up"

    def _to(self, state: str, now: float) -> None:
        if state != self.state:
            self.log.append((round(now, 1), self.state, state))
            self.state, self.since = state, now


# ---- the board side --------------------------------------------------------------------

def _env_file(path: Path) -> dict:
    """KEY=value lines, as deploy/unoq_setup.sh env_get reads them (no shell expansion)."""
    out = {}
    try:
        for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            v = v.strip()
            if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
                v = v[1:-1]
            out[k.strip()] = v
    except OSError:
        pass
    return out


def settings_from(env: dict) -> Settings:
    def num(name, default):
        try:
            return float(env.get(name, "") or default)
        except ValueError:
            return default
    return Settings(ap_profile=env.get("FISH_NET_AP_PROFILE", ""),
                    iface=env.get("FISH_NET_IFACE", "") or "wlan0",
                    client_wait_s=num("FISH_NET_CLIENT_WAIT_S", 45.0),
                    loss_s=num("FISH_NET_LOSS_S", 30.0),
                    ap_idle_s=num("FISH_NET_AP_IDLE_S", 60.0),
                    try_s=num("FISH_NET_TRY_S", 40.0),
                    tdls_off=(env.get("FISH_NET_TDLS_OFF", "") or "true").strip().lower()
                    not in ("0", "false", "no", "off"))


def _run(cmd: list[str], timeout: float = 15.0) -> str:
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout).stdout
    except (OSError, subprocess.TimeoutExpired):
        return ""


def active_connection(iface: str) -> str:
    for line in _run(["nmcli", "-t", "-f", "DEVICE,STATE,CONNECTION", "device"]).splitlines():
        parts = line.split(":")
        if len(parts) >= 3 and parts[0] == iface:
            return parts[2] if parts[1].startswith("connected") else ""
    return ""


def stations(iface: str) -> int:
    iw = next((p for p in ("/usr/sbin/iw", "/sbin/iw") if os.path.exists(p)), "iw")
    return sum(1 for l in _run([iw, "dev", iface, "station", "dump"], 5).splitlines()
               if l.startswith("Station "))


def tdls_off(iface: str, run=None) -> str:
    """Tell wpa_supplicant to discard every TDLS frame on `iface`; returns its reply ("OK",
    "FAIL") or "" when wpa_cli is missing or its socket is not ours (the `netdev` group)."""
    run = run or _run
    cli = next((p for p in ("/usr/sbin/wpa_cli", "/sbin/wpa_cli") if os.path.exists(p)), "wpa_cli")
    return run([cli, "-i", iface, "set", "tdls_disabled", "1"], 5).strip()


def address(iface: str) -> str:
    for line in _run(["ip", "-4", "-o", "addr", "show", "dev", iface], 5).splitlines():
        parts = line.split()
        if "inet" in parts:
            return parts[parts.index("inet") + 1].split("/")[0]
    return ""


def _state_dir(var: str, fallback: str) -> Path:
    base = os.environ.get(var) or os.path.expanduser(fallback)
    return Path(base) / "fish_brain"


def pinned() -> bool:
    try:
        return (_state_dir("XDG_STATE_HOME", "~/.local/state") / "net-pin").read_text().strip() == "ap"
    except OSError:
        return False


def _publish(d: Decider, active: str, n: int, iface: str) -> None:
    out = _state_dir("XDG_RUNTIME_DIR", "/tmp") / "net.json"
    try:
        out.parent.mkdir(parents=True, exist_ok=True)
        tmp = out.with_suffix(".tmp")
        tmp.write_text(json.dumps({"state": d.state, "connection": active, "stations": n,
                                   "ip": address(iface), "pinned": pinned(), "tries": d.tries,
                                   "t": round(time.time(), 1)}))
        os.replace(tmp, out)
    except OSError:
        pass


def main() -> int:
    repo = Path(__file__).resolve().parent.parent
    s = settings_from({**_env_file(repo / ".env"), **os.environ})
    if not s.ap_profile:
        print("[net] FISH_NET_AP_PROFILE is not set: nothing to watch", flush=True)
        return 0
    d = Decider(s)
    d.start(time.monotonic())
    print(f"[net] watching {s.iface}; access point '{s.ap_profile}' after "
          f"{s.client_wait_s:.0f} s without a known network", flush=True)
    while True:
        now = time.monotonic()
        active = active_connection(s.iface)
        n = stations(s.iface) if active == s.ap_profile else 0
        before = d.state
        act = d.step(now, active, n, pinned())
        if act:
            print(f"[net] {act} {s.ap_profile} ({before} -> {d.state})", flush=True)
            _run(["nmcli", "connection", act, s.ap_profile], 30)
        elif d.state != before:
            print(f"[net] {before} -> {d.state}" + (f" ({active})" if active else ""), flush=True)
        if s.tdls_off and d.state == CLIENT and before != CLIENT:
            print(f"[net] tdls off on {s.iface}: {tdls_off(s.iface) or 'no answer'}", flush=True)
        _publish(d, active, n, s.iface)
        time.sleep(2.0)


if __name__ == "__main__":
    sys.exit(main())
