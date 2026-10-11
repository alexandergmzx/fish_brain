# UNO Q: the board with the kiosk browser closed — 2026-10-11

Host: the board `segunda`, fish_brain at commit `2b49172` on the board (the service running, idle),
Chromium 154.0.8037.92 in the kiosk session of ADR 0005, the HDMI display attached and lit. Level 5,
read-only over ssh; no turn was run. Pass line, set before measuring: "no chromium process; the
board idle under 0.3 cores; hottest zone at or under 50 C after a few minutes".

Commands: `pgrep -a chromium Xorg lightdm`, `cat /sys/class/thermal/thermal_zone*/temp`,
`top -b -n 2 -d 5` (then `-n 3`), `deploy/unoq_setup.sh kiosk pause`, the same reads four minutes later.

| | Kiosk browser on the display (before) | `kiosk pause`, 4 min later (display still attached and lit) |
|---|---|---|
| Up | 28 min | 32 min |
| Load average (1 min) | 1.91 to 2.16 | 0.08 |
| CPU total | 33 % user, 7 % system (57 % idle) | 0.6 % user, 0.5 % system (98 % idle) |
| Chromium | 70 + 52 % of a core (two busiest processes) | none |
| Xorg | 14.5 % | 0.0 to 0.4 % |
| `fish_brain.app` | 1.0 % | 0.6 % |
| `fish_brain.kiosk` supervisor | 0.2 % | 0.2 to 0.6 % |
| Thermal zones (C) | 60.0 to 67.8 | 45.0 to 48.1 |

Reading: the whole cost measured on 2026-10-11 (`2026-10-11-kiosk-display.md`) is the browser.
With it closed, X, LightDM and the supervisor are below the noise. The LightDM session can stay
installed for the fair; with no display attached the supervisor starts no browser. Pass.

Not measured: the same with the display unplugged (expected equal or better), and a turn in this
state; the first hotspot turn is still open (fair matrix row 3).
