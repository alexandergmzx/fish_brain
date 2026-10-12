# UNO Q: the board with no display, idle and during a turn — 2026-10-12

Host: the board `segunda`, `fish-brain.service` on commit `220c71b`, the HDMI display unplugged by
the owner (`card0-DP-1 disconnected`), the LightDM kiosk session still installed and un-paused
(`kiosk resume`; the supervisor logs "no display, nothing to show" and starts no browser). Home
Wi-Fi, `stt=openai llm=luna tts=loq`, `ptt=web+browser-mic`, MCU link live, no drivers attached.
Level 5 without motors, the turn triggered over loopback. Pass line, set before: "no chromium; idle
under 0.3 cores; hottest zone at or under 50 C; a turn stays under one core".

Commands: `cat /sys/class/drm/card*/card*-*/status`, `pgrep -a chromium`, `top -b -n 3 -d 5`, the
thermal zones; then `top -b -n 6 -d 2` in the background while
`curl -X POST -d '{"name":"Carlos Ruiz"}' http://127.0.0.1:8723/reading` ran.

| | Idle, no display | During the reading turn (`llm=2.5s tts=2.5s`, then about 12 s of speech) |
|---|---|---|
| Load average (1 min) | 0.00 | — |
| CPU total | 1.2 % busy (98 % idle) | peaks of 30 % and 23 % busy (2 s samples), back to 3 % while the voice plays |
| Chromium / Xorg | none / 0.0 to 0.2 % | none / — |
| `fish_brain.app` | 0.8 % | 3.5 to 7.9 % |
| `loqd.exe` (Loquendo under Wine) | — | 84 % of one core in the render sample, 22 % in the next |
| Thermal zones (C) | 40.6 to 43.7 | 40.6 to 43.4 (unchanged) |

Reading: with the page on the phone the board idles at about one percent and does not warm up; a
turn costs Loquendo about one core for two seconds and the fish a few percent. Against the display
on 2026-10-11 (1.1 to 1.3 cores and 60 to 68 C at idle) the display was the whole cost. The LightDM
session can stay installed: it starts nothing without a display. Pass.
